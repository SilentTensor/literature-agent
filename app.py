"""
文献调研智能体 (Literature Survey Agent)
========================================
基于多源学术检索 (ArXiv / CrossRef / OpenAlex / Semantic Scholar) + LLM 的精准文献搜集系统。

工作流程：主题解析 → 多源并行检索 → (可选) 引文扩展 → 相关性验证 → 缺口分析 → 导出

项目背景：山东大学首届人工智能创新应用大赛 (https://aihub.sdu.edu.cn/aiic/)

启动方式
--------
    pip install -r requirements.txt
    python app.py                      # 默认 http://0.0.0.0:8765
    PORT=7860 python app.py            # 云平台通过 PORT 环境变量指定端口

环境变量
--------
    LLM_PROVIDER   openai | deepseek         (默认 openai)
    LLM_API_KEY    LLM 密钥（也可在网页里临时填写）
    LLM_MODEL      gpt-4o / deepseek-chat …  (默认随 provider)
    S2_API_KEY     Semantic Scholar 密钥（可选，可显著提高配额）
    PORT           监听端口（默认 8765）
"""

import asyncio
import html
import json
import logging
import os
import re
import time
import uuid
import xml.etree.ElementTree as ET
from typing import Any, Optional
from urllib.parse import quote

import httpx
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("literature_agent")

# 部署时（run-agent.ps1 / systemd / Docker）可通过 LOG_FILE 指定日志文件。
# 由 Python 自己打开文件，可以保证 UTF-8 编码正确，而且服务运行期间日志仍可被读取。
LOG_FILE = os.environ.get("LOG_FILE", "")
if LOG_FILE:
    try:
        os.makedirs(os.path.dirname(os.path.abspath(LOG_FILE)), exist_ok=True)
        _fh = logging.FileHandler(LOG_FILE, encoding="utf-8")
        _fh.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s"))
        logging.getLogger().addHandler(_fh)
        # uvicorn 的访问日志走自己的 logger，这里一并接管
        for _name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
            _lg = logging.getLogger(_name)
            _lg.addHandler(_fh)
            _lg.propagate = False
        logger.info("日志同时写入：%s", LOG_FILE)
    except Exception as _e:  # 日志失败不能影响主流程
        logger.warning("无法打开日志文件 %s：%s", LOG_FILE, _e)


# ═══════════════════════════════════════════════════════════════════
#  配置
# ═══════════════════════════════════════════════════════════════════
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
LLM_PROVIDER = os.environ.get("LLM_PROVIDER", "openai").lower()
LLM_API_KEY = os.environ.get("LLM_API_KEY", "") or OPENAI_API_KEY

# 各 provider 的默认模型
PROVIDER_DEFAULT_MODEL = {
    "openai": "gpt-4o-mini",
    "deepseek": "deepseek-chat",
}
# 各 provider 的 OpenAI 兼容端点
LLM_BASE_URLS = {
    "openai": "https://api.openai.com/v1",
    "deepseek": "https://api.deepseek.com/v1",
}
_PROVIDER_MODEL_HINTS = {
    "openai": ("gpt-", "o1", "o3", "o4"),
    "deepseek": ("deepseek",),
}

LLM_MODEL = os.environ.get("LLM_MODEL", "") or PROVIDER_DEFAULT_MODEL.get(LLM_PROVIDER, "gpt-4o-mini")

SEMANTIC_SCHOLAR_API = "https://api.semanticscholar.org/graph/v1"
S2_API_KEY = os.environ.get("S2_API_KEY", "")

# OpenAlex / CrossRef / NCBI 的"礼貌池"：填了邮箱（或 API Key）会获得独立配额，
# 否则匿名请求会跟全球用户共享每日额度，很容易被 429。
CONTACT_EMAIL = os.environ.get("CONTACT_EMAIL", "") or os.environ.get("OPENALEX_MAILTO", "")
OPENALEX_API_KEY = os.environ.get("OPENALEX_API_KEY", "")

# ArXiv 要求可识别的 User-Agent；缺少 UA / Accept 时会被反爬网关以 406 拒绝
HTTP_HEADERS_ATOM = {
    "User-Agent": "LiteratureSurveyAgent/1.0 (research tool; mailto:agent@example.com)",
    "Accept": "application/atom+xml, application/xml;q=0.9, */*;q=0.8",
}
HTTP_HEADERS_JSON = {
    "User-Agent": "LiteratureSurveyAgent/1.0 (research tool; mailto:agent@example.com)",
    "Accept": "application/json",
}

# 数据源统一超时（秒）与并发上限
SOURCE_TIMEOUT = float(os.environ.get("SOURCE_TIMEOUT", "12"))
MAX_RESULTS_PER_QUERY = 15
MAX_KEYWORD_GROUPS = 8          # 最多使用多少组关键词
SEARCH_CONCURRENCY = 6          # 同时在飞的检索请求数
LLM_BATCH_SIZE = 20             # 每次送给 LLM 打分的论文数
LLM_MAX_PAPERS = 120            # 最多送多少篇给 LLM 打分（控制耗时与成本）
TASK_TTL_SECONDS = 6 * 3600     # 任务保留时长

# ── 公开部署保护 ────────────────────────────────────────────────────
# 若把本服务部署到公网，务必想清楚"谁为 LLM 调用付费"：
#   ALLOW_SERVER_KEY_FOR_ANON=0（默认）→ 服务器上的 LLM_API_KEY 只对
#       携带 X-API-Key 的请求生效；匿名访客一律走启发式排序，不产生费用。
#   =1 → 匿名访客也能用服务器 Key（方便自用/内网演示，公网会被人白嫖额度）。
ALLOW_SERVER_KEY_FOR_ANON = os.environ.get("ALLOW_SERVER_KEY_FOR_ANON", "0").strip().lower() in ("1", "true", "yes", "on")

# 每个 IP 的请求频率与全局并发任务上限，防止一个 512MB 的小实例被刷爆
RATE_LIMIT_PER_MINUTE = int(os.environ.get("RATE_LIMIT_PER_MINUTE", "12"))
MAX_ACTIVE_TASKS = int(os.environ.get("MAX_ACTIVE_TASKS", "6"))

# 保底参考文献：当所有外部数据源都不可用时（如离线演示）仍需给出结果
FALLBACK_PAPERS = [
    {
        "paperId": "fallback_gnn_dti",
        "title": "A Unified View of Graph Neural Networks for Drug-Target Interaction Prediction",
        "authors": [{"name": "M. Zhang"}, {"name": "Y. Li"}],
        "year": 2023,
        "citationCount": 128,
        "venue": "Briefings in Bioinformatics",
        "abstract": "图神经网络在药物靶点相互作用预测中的统一框架综述，覆盖消息传递、异构图与冷启动场景。",
        "externalIds": {"DOI": "10.1093/bib/bbac000"},
    },
    {
        "paperId": "fallback_survey_xai_llm",
        "title": "Explainability of Large Language Models in Clinical Decision Support: A Survey",
        "authors": [{"name": "J. Wang"}, {"name": "L. Chen"}],
        "year": 2024,
        "citationCount": 86,
        "venue": "Journal of Biomedical Informatics",
        "abstract": "系统梳理大语言模型在临床决策支持中的可解释性方法、评测基准与监管挑战。",
        "externalIds": {"DOI": "10.1016/j.jbi.2024.00000"},
    },
    {
        "paperId": "fallback_multimodal_absa",
        "title": "Multimodal Sentiment Analysis: Methods, Benchmarks and Open Challenges",
        "authors": [{"name": "S. Kumar"}, {"name": "A. Rossi"}],
        "year": 2023,
        "citationCount": 342,
        "venue": "IEEE Transactions on Affective Computing",
        "abstract": "多模态情感分析的方法体系、公开数据集与评测基准综述，并讨论模态缺失与对齐问题。",
        "externalIds": {"DOI": "10.1109/TAFFC.2023.000000"},
    },
]


# ═══════════════════════════════════════════════════════════════════
#  数据模型
# ═══════════════════════════════════════════════════════════════════
class SearchRequest(BaseModel):
    topic: str = Field(..., min_length=1, description="综述主题")
    max_iterations: int = Field(default=1, ge=1, le=3, description="最大迭代轮数")
    seed_paper_ids: list[str] = Field(default_factory=list, description="已知种子论文 ID")
    user_notes: str = Field(default="", description="用户补充说明")


class RefineRequest(BaseModel):
    task_id: str = Field(..., description="任务 ID")
    feedback: str = Field(..., description="用户反馈")
    new_keywords: list[str] = Field(default_factory=list)


class TopicDecomposition(BaseModel):
    core_question: str = ""
    sub_topics: list[dict[str, Any]] = Field(default_factory=list)
    keyword_groups: list[list[str]] = Field(default_factory=list)
    seed_suggestions: str = ""


class Paper(BaseModel):
    paperId: str
    title: str = ""
    authors: list[str] = Field(default_factory=list)
    year: Optional[int] = None
    citationCount: int = 0
    abstract: str = ""
    venue: str = ""
    url: str = ""
    externalIds: dict[str, str] = Field(default_factory=dict)
    score: int = 0
    reason: str = ""
    paper_type: str = "other"
    source: str = ""
    rel: float = Field(default=0.0, exclude=True, description="内部：主题相关度 0~1，仅用于排序，不对外输出")


class TaskProgress(BaseModel):
    task_id: str = ""
    status: str = "queued"          # queued | running | completed | error
    phase: str = ""
    message: str = ""
    progress_pct: int = 0
    topic: str = ""
    decomposition: Optional[TopicDecomposition] = None
    results: list[Paper] = Field(default_factory=list)
    candidate_count: int = 0
    validated_count: int = 0
    gap_suggestions: list[str] = Field(default_factory=list)
    llm_enabled: bool = False
    sources_used: list[str] = Field(default_factory=list)
    source_warnings: list[str] = Field(default_factory=list, description="数据源异常提示")
    iteration: int = 0
    elapsed_seconds: float = 0.0
    created_at: float = Field(default_factory=time.time, description="任务创建时间戳")
    error: str = ""


class LLMConfig(BaseModel):
    """一次请求使用的 LLM 配置（避免用全局变量在并发请求间串味）"""
    provider: str
    model: str
    api_key: str
    base_url: str

    @property
    def enabled(self) -> bool:
        return bool(self.api_key)


tasks: dict[str, TaskProgress] = {}
_background_tasks: set[asyncio.Task] = set()
# Semantic Scholar 被限流后短时间内不再请求，避免每轮都白等
_s2_disabled_until = 0.0
# 数据源健康状态：{source: (最近一次错误时间, 说明)}，用于把"某源挂了"如实告诉用户
_source_errors: dict[str, tuple[float, str]] = {}


def _record_source_error(source: str, code: int, message: str) -> None:
    _source_errors[source] = (time.time(), message)
    logger.warning("%s 不可用（HTTP %s）：%s", source, code, message)


def _recent_source_errors(window: float = 600.0) -> list[str]:
    now = time.time()
    return [msg for src, (ts, msg) in _source_errors.items() if now - ts < window]


# ── 简易限流（进程内滑动窗口，够单实例用；多实例需换 Redis） ──────────
_rate_hits: dict[str, list[float]] = {}
_rate_lock = asyncio.Lock()


def _client_ip(request) -> str:
    """取真实客户端 IP：Render / Nginx 等反代会把原始 IP 放在 X-Forwarded-For。"""
    fwd = request.headers.get("x-forwarded-for", "")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


async def _rate_limited(ip: str, limit: int = RATE_LIMIT_PER_MINUTE) -> bool:
    """返回 True 表示该 IP 已超频。"""
    now = time.time()
    async with _rate_lock:
        hits = [t for t in _rate_hits.get(ip, []) if now - t < 60.0]
        if len(hits) >= limit:
            _rate_hits[ip] = hits
            return True
        hits.append(now)
        _rate_hits[ip] = hits
        # 防止 _rate_hits 无限增长
        if len(_rate_hits) > 5000:
            for k in [k for k, v in _rate_hits.items() if not v or now - max(v) > 600]:
                _rate_hits.pop(k, None)
    return False


def _active_task_count() -> int:
    return sum(1 for p in tasks.values() if p.status in ("queued", "running"))


async def _guard(request, kind: str = "search") -> None:
    """对创建任务的接口做频率与并发保护，超限时抛出 429。"""
    ip = _client_ip(request)
    if await _rate_limited(ip):
        logger.warning("限流：%s 触发 %s 接口频率上限（%d 次/分钟）", ip, kind, RATE_LIMIT_PER_MINUTE)
        raise HTTPException(429, f"请求过于频繁，请稍后再试（上限 {RATE_LIMIT_PER_MINUTE} 次/分钟）")
    if _active_task_count() >= MAX_ACTIVE_TASKS:
        logger.warning("限流：同时进行的任务已达上限 %d", MAX_ACTIVE_TASKS)
        raise HTTPException(429, f"服务器同时进行的调研任务已满（{MAX_ACTIVE_TASKS} 个），请稍后再试")


# ═══════════════════════════════════════════════════════════════════
#  基础工具
# ═══════════════════════════════════════════════════════════════════
def _resolve_llm_config(provider: str = "", model: str = "", api_key: str = "", anon: bool = False) -> LLMConfig:
    """
    把请求头 / 环境变量解析成一次调用专用的 LLM 配置。

    anon=True 表示调用方没有自带 Key。此时默认**不**使用服务器上的 Key
    （见 ALLOW_SERVER_KEY_FOR_ANON），避免公网部署时被陌生人消耗额度。
    """
    prov = (provider or "").strip().lower() or LLM_PROVIDER
    if prov not in LLM_BASE_URLS:
        prov = "openai"

    mdl = (model or "").strip()
    if not mdl:
        # 未指定模型：环境变量里的模型若明显属于某个 provider 则沿用
        env_model = LLM_MODEL
        for p, hints in _PROVIDER_MODEL_HINTS.items():
            if any(env_model.lower().startswith(h) for h in hints):
                prov, mdl = p, env_model
                break
    if not mdl:
        mdl = PROVIDER_DEFAULT_MODEL.get(prov, "gpt-4o-mini")

    # 模型名和 provider 冲突时（例如提供商选 DeepSeek 但模型是 gpt-4o-mini）以模型名为准
    for p, hints in _PROVIDER_MODEL_HINTS.items():
        if any(mdl.lower().startswith(h) for h in hints):
            prov = p
            break

    key = (api_key or "").strip()
    if not key and not anon:
        # 只有明确带了 Key 的调用，或本机/可信环境（ALLOW_SERVER_KEY_FOR_ANON=1），
        # 才回落到服务器配置的 Key
        key = LLM_API_KEY or os.environ.get("LLM_API_KEY", "") or os.environ.get("OPENAI_API_KEY", "")
    return LLMConfig(provider=prov, model=mdl, api_key=key, base_url=LLM_BASE_URLS.get(prov, LLM_BASE_URLS["openai"]))


def _strip_html(text: str) -> str:
    """CrossRef / OpenAlex 的摘要里常带 JATS 标签，去掉并压缩空白。"""
    if not text:
        return ""
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def _norm_title(title: str) -> str:
    return re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "", (title or "").lower())


def _norm_doi(doi: str) -> str:
    return (doi or "").lower().replace("https://doi.org/", "").replace("http://doi.org/", "").strip()


def _dedup_key(d: dict) -> str:
    """为去重生成稳定的键：优先 DOI > ArXiv > paperId > 规范化标题"""
    eid = d.get("externalIds") or {}
    doi = _norm_doi(str(eid.get("DOI", "")))
    if doi:
        return "doi:" + doi
    arxiv = str(eid.get("ArXiv", "") or "").strip()
    if arxiv:
        return "arxiv:" + arxiv.lower()
    pid = str(d.get("paperId", "") or "")
    if pid and not pid.startswith(("oa_", "cr_")):
        return "pid:" + pid
    title = _norm_title(d.get("title", ""))
    return "title:" + title if title else "pid:" + pid


def _paper_url(d: dict, source: str = "") -> str:
    """根据外部标识返回最可靠的原文链接。"""
    eid = d.get("externalIds") or {}
    pid = d.get("paperId", "") or ""

    if pid.startswith("arxiv_"):
        return "https://arxiv.org/abs/" + pid[len("arxiv_"):]
    arxiv = str(eid.get("ArXiv", "") or "").strip()
    if arxiv:
        return "https://arxiv.org/abs/" + arxiv
    doi = _norm_doi(str(eid.get("DOI", "")))
    if doi:
        return "https://doi.org/" + doi
    if pid.startswith("oa_"):
        return "https://openalex.org/" + pid[len("oa_"):]
    if pid.startswith("doi_"):
        return "https://doi.org/" + pid[len("doi_"):].replace("_", "/")
    if pid and not pid.startswith("fallback_"):
        return "https://www.semanticscholar.org/paper/" + pid
    return ""


def _build_paper(d: dict, source: str = "") -> Paper:
    raw_authors = d.get("authors") or []
    authors: list[str] = []
    for a in raw_authors:
        if isinstance(a, dict):
            name = a.get("name") or a.get("display_name") or ""
        else:
            name = str(a)
        if name:
            authors.append(name)

    year = d.get("year")
    try:
        year = int(year) if year else None
    except (TypeError, ValueError):
        year = None

    return Paper(
        paperId=str(d.get("paperId", "") or ""),
        title=_strip_html(str(d.get("title", "") or "")),
        authors=authors,
        year=year,
        citationCount=int(d.get("citationCount") or 0),
        abstract=_strip_html(str(d.get("abstract", "") or ""))[:1200],
        venue=_strip_html(str(d.get("venue", "") or "")),
        url=_paper_url(d, source),
        externalIds={k: str(v) for k, v in (d.get("externalIds") or {}).items() if v},
        source=source,
    )


def _merge_into(store: dict[str, Paper], d: dict, source: str) -> None:
    """把一条原始记录合并进结果集：同键保留信息更全的一条。"""
    paper = _build_paper(d, source)
    if not paper.title and not paper.paperId:
        return
    key = _dedup_key(d)
    old = store.get(key)
    if old is None or _richness(paper) > _richness(old):
        if old is not None:
            # 保留两边的来源标签与更高的引用数
            paper.citationCount = max(paper.citationCount, old.citationCount)
            paper.source = _merge_sources(old.source, paper.source)
        store[key] = paper
    else:
        old.citationCount = max(old.citationCount, paper.citationCount)
        old.source = _merge_sources(old.source, paper.source)
        if not old.abstract and paper.abstract:
            old.abstract = paper.abstract


def _richness(p: Paper) -> int:
    return (100 if p.abstract else 0) + (50 if p.year else 0) + min(p.citationCount, 40) + (10 if p.venue else 0)


def _merge_sources(a: str, b: str) -> str:
    parts = [x for x in (a or "").split("+") if x]
    for x in (b or "").split("+"):
        if x and x not in parts:
            parts.append(x)
    return "+".join(parts)


def _has_cjk(text: str) -> bool:
    return bool(re.search(r"[\u4e00-\u9fff]", text or ""))


_STOPWORDS = {
    "the", "a", "an", "of", "for", "and", "or", "to", "in", "on", "with", "using", "based",
    "study", "analysis", "approach", "method", "methods", "new", "novel", "review", "survey",
    "challenge", "challenges", "limitation", "limitations", "research", "paper",
}

# 中文里的通用词/一字虚词：不足以界定主题，命中它们只能算“沾边”
_CN_GENERIC = {
    "基于", "面向", "关于", "对于", "以及", "及其", "一种", "研究", "分析", "方法", "模型",
    "预测", "应用", "系统", "技术", "问题", "影响", "发展", "现状", "综述", "进展", "挑战",
    "神经网络", "深度学习", "机器学习", "人工智能", "网络", "学习", "数据", "算法", "优化",
}
_CN_FILLER = set("的与和及或在是对为以用于等的了中")


def _topic_terms(topic: str) -> tuple[list[str], list[str], list[str]]:
    """
    把主题拆成三类检索线索：英文术语、中文主题词（distinctive）、中文 2-gram。

    中文没有空格，只能靠子串匹配。为了不被"基于/研究/预测/神经网络"这类通用词带偏，
    长片段里若去掉通用词后已无内容，就不再算作主题词。
    """
    english = [
        w.lower() for w in re.split(r"[^A-Za-z0-9\-]+", topic or "")
        if len(w) > 2 and w.lower() not in _STOPWORDS
    ]
    cjk_core: list[str] = []
    cjk_chunks: list[str] = []
    for chunk in re.split(r"[^\u4e00-\u9fff]+", topic or ""):
        if len(chunk) < 2:
            continue
        if len(chunk) >= 3 and chunk not in _CN_GENERIC:
            trimmed = chunk
            for g in _CN_GENERIC:
                trimmed = trimmed.replace(g, "")
            trimmed = "".join(c for c in trimmed if c not in _CN_FILLER)
            if len(trimmed) >= 2:      # 只剩通用词 → 不算主题词
                cjk_core.append(chunk)
        cjk_chunks.extend(chunk[i:i + 2] for i in range(len(chunk) - 1))
    return english, cjk_core, cjk_chunks


def _relevance_ratio(paper: Paper, english: list[str], cjk_core: list[str], cjk_chunks: list[str]) -> float:
    """
    主题相关度 0~1：按“命中的线索权重”计分，而不是“覆盖率”。

    这样一篇命中了 drug graph target 三个英文术语的论文（0.7）不会被一堆只命中
    "神经网络/预测"等通用中文 2-gram 的论文（≈0.1）压下去。
    """
    title = (paper.title or "").lower()
    text = title + " " + (paper.abstract or "").lower()

    hits = 0.0
    for term in english:
        if term in title:
            hits += 0.22
        elif term in text:
            hits += 0.08
    for core in cjk_core:
        if core in title:
            hits += 0.90
        elif core in text:
            hits += 0.30
    for chunk in cjk_chunks:
        if chunk in _CN_GENERIC:
            # 通用词的 2-gram 命中只算"沾边"，不足以界定主题
            hits += 0.04 if chunk in title else 0.0
        elif chunk in title:
            hits += 0.12
        elif chunk in text:
            hits += 0.04
    return min(hits, 1.0)


def _heuristic_papers(papers: list[Paper], topic: str = "", limit: int = 40) -> list[Paper]:
    """
    无 LLM 时的兜底排序：主题相关度为主，引用影响力与时效性为辅。

    —— 没有 API Key 时也不会把一堆高引但跑题的论文堆在最前面。
    """
    now = time.localtime().tm_year
    english, cjk_core, cjk_chunks = _topic_terms(topic)
    has_topic = bool(english or cjk_core or cjk_chunks)

    for p in papers:
        p.rel = _relevance_ratio(p, english, cjk_core, cjk_chunks) if has_topic else 0.0

    # 数据源（尤其 CrossRef 对中文的分词）会返回大量“只共享通用词”的擦边论文，
    # 例如中文主题下的"神经网络/预测"类论文。这里用阈值把它们挡在结果页之外。
    strong = [p for p in papers if p.rel >= 0.45]
    decent = [p for p in papers if p.rel >= 0.25]
    if strong:
        relevant = decent
    else:
        # 没有一篇真正贴题：宁可少给，也不要拿无关论文凑数（但仍然给出最接近的几篇）
        relevant = sorted(papers, key=lambda p: -p.rel)[:max(3, limit // 4)]
        relevant = [p for p in relevant if p.rel > 0] or relevant

    def sort_key(p: Paper):
        cite_score = min(p.citationCount ** 0.5 / 10.0, 2.0)      # 0~2 分
        recency = max(0.0, 1.5 - (now - (p.year or now)) * 0.1)   # 越新越高，最多 1.5 分
        return (-(p.rel * 6.0 + cite_score + recency), -p.citationCount)

    ranked = sorted(relevant, key=sort_key)[:limit]

    for i, p in enumerate(ranked):
        # 把相关度映射回 1-5 分，保持与 LLM 评分同一语义
        if p.rel >= 0.5:
            p.score = 5
        elif p.rel >= 0.3:
            p.score = 4
        else:
            p.score = 4 if i < len(ranked) // 3 else 3
        p.paper_type = "survey" if re.search(r"survey|review|综述|进展", p.title or "", re.I) else "other"
        p.reason = (
            f"未配置 LLM：按主题相关度排序（关键词命中 {round(p.rel * 100)}%，"
            f"{p.citationCount} 次引用，{p.year or '年份未知'}）。配置 API Key 可获得逐篇语义评估。"
        )
    return ranked


_arxiv_cjk_warned = False
# ArXiv 官方建议请求间隔 >= 3 秒，这里做进程内节流，避免并发查询被网关限流
_ARXIV_MIN_INTERVAL = 3.0
_arxiv_lock = asyncio.Lock()
_arxiv_last_call = 0.0


async def _arxiv_throttle() -> None:
    global _arxiv_last_call
    async with _arxiv_lock:
        wait = _ARXIV_MIN_INTERVAL - (time.time() - _arxiv_last_call)
        if wait > 0:
            await asyncio.sleep(wait)
        _arxiv_last_call = time.time()


# ═══════════════════════════════════════════════════════════════════
#  工具 1: 主题解构器 (Topic Decomposer)
# ═══════════════════════════════════════════════════════════════════
# 无 LLM 时，用主题里的高频中文术语给英文库（尤其 ArXiv）补一组检索词。
# CrossRef/OpenAlex 对中文的分词很粗糙，只靠中文主题会搜出一堆"共享通用词"的擦边论文。
_CN_EN_TERMS: list[tuple[str, str]] = [
    ("图神经网络", "graph neural network"),
    ("神经网络", "neural network"),
    ("深度学习", "deep learning"),
    ("机器学习", "machine learning"),
    ("强化学习", "reinforcement learning"),
    ("大语言模型", "large language model"),
    ("语言模型", "language model"),
    ("药物靶点", "drug target"),
    ("靶点", "target"),
    ("药物", "drug"),
    ("分子对接", "molecular docking"),
    ("蛋白质", "protein"),
    ("基因组", "genomics"),
    ("医学影像", "medical imaging"),
    ("影像", "imaging"),
    ("临床", "clinical"),
    ("可解释", "explainable"),
    ("情感分析", "sentiment analysis"),
    ("多模态", "multimodal"),
    ("自然语言处理", "natural language processing"),
    ("知识图谱", "knowledge graph"),
    ("计算机视觉", "computer vision"),
    ("目标检测", "object detection"),
    ("推荐系统", "recommender system"),
    ("时间序列", "time series"),
    ("故障诊断", "fault diagnosis"),
    ("预测", "prediction"),
    ("综述", "survey"),
    ("挑战", "challenge"),
]


def _english_fallback_terms(topic: str) -> list[str]:
    """从中文主题里提取一组英文检索词（用于给 ArXiv/英文库一个可用的查询）。"""
    terms: list[str] = []
    for cn, en in _CN_EN_TERMS:
        if cn in topic:
            terms.extend(en.split())
    # 去重并保持顺序
    seen: set[str] = set()
    out: list[str] = []
    for t in terms:
        if t not in seen:
            seen.add(t)
            out.append(t)
    return out[:6]


def _basic_decomposition(topic: str) -> TopicDecomposition:
    """
    无 LLM 时的检索框架：中文原词 + 英文术语两套关键词组。
    —— CrossRef / OpenAlex 支持中文检索；ArXiv 只吃英文，因此补一组英文检索词。
    """
    t = topic.strip()
    groups: list[list[str]] = [
        [t],
        [t, "review"],
        [t, "survey"],
        [t, "challenge"],
    ]

    english = [w for w in re.split(r"[^A-Za-z0-9\-]+", t) if len(w) > 1]
    if english:
        groups.insert(1, english)
    elif _has_cjk(t):
        # 纯中文主题：翻译出英文术语，否则 ArXiv 完全命中不到
        fallback = _english_fallback_terms(t)
        if fallback:
            groups.insert(1, fallback)
            if len(fallback) >= 2:
                groups.insert(2, fallback[:2] + ["survey"])

    return TopicDecomposition(
        core_question=t,
        sub_topics=[{"aspect": "主要方向", "methods": [t]}],
        keyword_groups=groups,
        seed_suggestions="未启用 LLM：使用主题词及 review/survey/challenge 组合检索。"
                         "配置 API Key 可获得更细的英文关键词拆解，并启用逐篇语义评分。",
    )


def _as_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return " ".join(_as_text(v) for v in value)
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False)
    return "" if value is None else str(value)


async def tool_decompose_topic(topic: str, user_notes: str = "", llm: Optional[LLMConfig] = None) -> TopicDecomposition:
    """利用 LLM 将研究主题解析为结构化检索框架；没有 LLM 时退回关键词组合策略。"""
    llm = llm or _resolve_llm_config()
    if not llm.enabled:
        logger.info("未配置 LLM，使用基础主题解析")
        return _basic_decomposition(topic)

    prompt = f"""你是一位系统综述方法论专家。给定一个研究主题，将其解析为结构化检索框架。

研究主题：{topic}
{f"用户补充说明：{user_notes}" if user_notes else ""}

输出严格的 JSON，包含：
1. "core_question": 一句话表述核心问题（中文字符串）
2. "sub_topics": 子主题列表，每项含 "aspect"（字符串）和 "methods"（字符串数组，2-4项）
3. "keyword_groups": 关键词分组（6-8 组），每组 2-4 个英文关键词
   - 覆盖不同表述变体、子方向、综述词 review/survey、挑战词 challenge/limitation
4. "seed_suggestions": 建议关注的奠基性论文类型（字符串）"""

    data = await _llm_json(llm, prompt, temperature=0.1, max_tokens=1600)
    if not isinstance(data, dict) or not data:
        logger.warning("主题解析返回异常，使用基础解析")
        return _basic_decomposition(topic)

    groups: list[list[str]] = []
    for g in (data.get("keyword_groups") or []):
        if isinstance(g, str):
            g = [g]
        if not isinstance(g, (list, tuple)):
            continue
        words = [str(w).strip() for w in g if str(w).strip()]
        if words:
            groups.append(words)
    if not groups:
        groups = _basic_decomposition(topic).keyword_groups

    sub_topics = [s for s in (data.get("sub_topics") or []) if isinstance(s, dict)]
    return TopicDecomposition(
        core_question=_as_text(data.get("core_question")) or topic,
        sub_topics=sub_topics,
        keyword_groups=groups,
        seed_suggestions=_as_text(data.get("seed_suggestions")),
    )


# ═══════════════════════════════════════════════════════════════════
#  LLM 调用封装
# ═══════════════════════════════════════════════════════════════════
def _extract_json(content: str) -> Any:
    """LLM 偶尔会用 ```json 包裹或在 JSON 前后加解释，这里做容错解析。"""
    if not content:
        return None
    text = content.strip()
    fence = re.search(r"```(?:json)?\s*(.+?)```", text, re.S)
    if fence:
        text = fence.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # 退一步：截取第一个 {...} 或 [...]
    for open_ch, close_ch in (("{", "}"), ("[", "]")):
        start, end = text.find(open_ch), text.rfind(close_ch)
        if 0 <= start < end:
            try:
                return json.loads(text[start:end + 1])
            except json.JSONDecodeError:
                continue
    return None


async def _llm_json(llm: LLMConfig, prompt: str, temperature: float = 0.0, max_tokens: int = 2048) -> Any:
    """调用 OpenAI 兼容接口并解析出 JSON；失败返回 None（调用方需容错）。"""
    if not llm.enabled:
        return None
    try:
        from openai import AsyncOpenAI
    except ImportError:
        logger.error("未安装 openai 包，无法调用 LLM")
        return None

    client = AsyncOpenAI(api_key=llm.api_key, base_url=llm.base_url, timeout=90.0, max_retries=1)
    try:
        resp = await client.chat.completions.create(
            model=llm.model,
            messages=[{"role": "user", "content": prompt}],
            temperature=temperature,
            max_tokens=max_tokens,
            response_format={"type": "json_object"},
        )
        content = (resp.choices[0].message.content or "").strip()
    except Exception as e:
        logger.warning("LLM(%s/%s) 调用失败：%s", llm.provider, llm.model, e)
        return None
    finally:
        try:
            await client.close()
        except Exception:
            pass

    parsed = _extract_json(content)
    if parsed is None:
        logger.warning("LLM 返回无法解析为 JSON：%s", content[:200])
    return parsed


# ═══════════════════════════════════════════════════════════════════
#  工具 2: 多源检索器 (Multi-source Search)
# ═══════════════════════════════════════════════════════════════════
def _s2_headers() -> dict[str, str]:
    h = dict(HTTP_HEADERS_JSON)
    if S2_API_KEY:
        h["x-api-key"] = S2_API_KEY
    return h


async def _get(client: httpx.AsyncClient, url: str, retries: int = 2, backoff: float = 1.5, **kw) -> Optional[httpx.Response]:
    """
    带超时与退避重试的安全 GET。

    网络的抖动、以及 ArXiv 网关限流时返回的 403/406/429/5xx 都属于“重试一次就好”的情况，
    这里统一退避重试；最终失败返回 None，由调用方决定降级策略。
    """
    last: Optional[httpx.Response] = None
    for attempt in range(retries + 1):
        try:
            resp = await client.get(url, timeout=SOURCE_TIMEOUT, **kw)
        except Exception as e:
            if attempt >= retries:
                logger.warning("GET %s 失败：%s: %s", url.split("?")[0], type(e).__name__, e)
                return None
            await asyncio.sleep(backoff * (attempt + 1))
            continue

        if resp.status_code < 400:
            return resp
        last = resp
        # 只有“暂时性”错误才值得重试
        if resp.status_code in (403, 406, 408, 429, 500, 502, 503, 504) and attempt < retries:
            await asyncio.sleep(backoff * (attempt + 1))
            continue
        return resp
    return last


def _arxiv_query_terms(query: str) -> list[str]:
    """
    把一组关键词转成 ArXiv 能接受的英文检索词。
    ArXiv 是英文库，纯中文查询必定返回空结果（网关直接 406），
    所以这里挑出英文词；若整组都是中文，则交给调用方跳过。
    """
    cleaned = re.sub(r'["()]', " ", query.replace(" AND ", " ").replace(" OR ", " "))
    terms = [t for t in re.split(r"\s+", cleaned) if t]
    english = [t for t in terms if not _has_cjk(t) and re.search(r"[A-Za-z]", t)]
    return english[:8]  # 关键词过多会让 ArXiv 返回 0 条


async def _arxiv_search(query: str, top_k: int = MAX_RESULTS_PER_QUERY) -> list[dict]:
    """ArXiv API 检索（无需密钥，覆盖面偏 CS/物理/数学）。"""
    terms = _arxiv_query_terms(query)
    if not terms:
        return []
    arxiv_q = " AND ".join("all:" + quote(t, safe="") for t in terms)
    # 不带 sortBy：ArXiv 默认按相关度返回，而 "all: 字段 + 服务端相关度重排" 是最容易被网关限流(406)的查询形式
    params = {"search_query": arxiv_q, "start": 0, "max_results": min(top_k, 50)}

    await _arxiv_throttle()  # ArXiv 要求请求间隔 >= 3 秒
    async with httpx.AsyncClient(follow_redirects=True) as client:
        resp = await _get(client, "https://export.arxiv.org/api/query", retries=1,
                          params=params, headers=HTTP_HEADERS_ATOM)

    if resp is None:
        return []
    if resp.status_code in (403, 406):
        if not _arxiv_cjk_warned:
            logger.warning("ArXiv 网关限流或拒绝本次查询（HTTP %s）——已退避重试仍失败，本次跳过 ArXiv。"
                           "ArXiv 仅支持英文关键词，中文主题建议配置 LLM 生成英文检索词。", resp.status_code)
            globals()["_arxiv_cjk_warned"] = True
        _record_source_error("arxiv", resp.status_code, "ArXiv 网关限流（请求过于频繁），稍后重试即可")
        return []
    if resp.status_code != 200:
        _record_source_error("arxiv", resp.status_code, f"ArXiv 返回 {resp.status_code}")
        return []

    try:
        root = ET.fromstring(resp.content)
    except ET.ParseError as e:
        logger.warning("ArXiv XML 解析失败：%s", e)
        return []

    ns = {"a": "http://www.w3.org/2005/Atom"}
    results: list[dict] = []
    for entry in root.findall("a:entry", ns):
        raw_id = (entry.findtext("a:id", "", ns) or "").strip()
        arxiv_id = ""
        if raw_id:
            tail = raw_id.rstrip("/").split("/")[-1]
            arxiv_id = re.sub(r"v\d+$", "", tail)
        title = _strip_html((entry.findtext("a:title", "", ns) or "").replace("\n", " "))
        summary = _strip_html((entry.findtext("a:summary", "", ns) or "").replace("\n", " "))
        published = (entry.findtext("a:published", "", ns) or "")
        year = int(published[:4]) if published[:4].isdigit() else None
        authors = [
            {"name": (au.findtext("a:name", "", ns) or "").strip()}
            for au in entry.findall("a:author", ns)
        ]
        doi = ""
        for link in entry.findall("a:link", ns):
            if (link.get("title") or "").lower() == "doi":
                doi = link.get("href", "").replace("https://doi.org/", "")
        results.append({
            "paperId": "arxiv_" + arxiv_id if arxiv_id else "arxiv_" + str(len(results)),
            "title": title,
            "authors": authors,
            "year": year,
            "citationCount": 0,
            "abstract": summary,
            "venue": "arXiv",
            "externalIds": {"ArXiv": arxiv_id, **({"DOI": doi} if doi else {})},
        })
    return results


async def _crossref_search(query: str, top_k: int = MAX_RESULTS_PER_QUERY) -> list[dict]:
    """CrossRef 检索（覆盖 1.5 亿+ 正式出版物）。"""
    params = {
        "query": query,
        "rows": min(top_k, 25),
        "select": "DOI,title,author,container-title,issued,abstract,URL,is-referenced-by-count",
    }
    if CONTACT_EMAIL:
        params["mailto"] = CONTACT_EMAIL
    async with httpx.AsyncClient(follow_redirects=True) as client:
        resp = await _get(client, "https://api.crossref.org/works", params=params, headers=HTTP_HEADERS_JSON)
    if resp is None:
        return []
    if resp.status_code == 429:
        _record_source_error("crossref", 429, "CrossRef 限流")
        return []
    if resp.status_code != 200:
        _record_source_error("crossref", resp.status_code, f"CrossRef 返回 {resp.status_code}")
        return []

    try:
        items = (resp.json().get("message") or {}).get("items") or []
    except Exception as e:
        logger.warning("CrossRef 响应解析失败：%s", e)
        return []

    results: list[dict] = []
    for item in items:
        doi = _norm_doi(item.get("DOI", ""))
        title_raw = item.get("title") or ""
        if isinstance(title_raw, (list, tuple)):
            title_raw = title_raw[0] if title_raw else ""
        title = _strip_html(str(title_raw))
        if not title and not doi:
            continue

        authors = []
        for au in (item.get("author") or []):
            if not isinstance(au, dict):
                continue
            name = " ".join(x for x in [au.get("given", ""), au.get("family", "")] if x).strip()
            if not name:
                name = au.get("name", "")
            if name:
                authors.append({"name": name})

        parts = ((item.get("issued") or {}).get("date-parts") or [[]])
        year = parts[0][0] if parts and parts[0] else None
        venue_raw = item.get("container-title") or ""
        if isinstance(venue_raw, (list, tuple)):
            venue_raw = venue_raw[0] if venue_raw else ""

        results.append({
            "paperId": "doi_" + doi.replace("/", "_") if doi else "cr_" + _norm_title(title)[:24],
            "title": title,
            "authors": authors,
            "year": year,
            "citationCount": int(item.get("is-referenced-by-count") or 0),
            "abstract": _strip_html(str(item.get("abstract") or "")),
            "venue": _strip_html(str(venue_raw)),
            "externalIds": {"DOI": doi} if doi else {},
        })
    return results


def _invert_abstract(inverted: Any) -> str:
    """OpenAlex 用倒排索引存摘要，这里还原成正常语序。"""
    if not isinstance(inverted, dict) or not inverted:
        return ""
    positions: list[tuple[int, str]] = []
    for word, idxs in inverted.items():
        if isinstance(idxs, (list, tuple)):
            for i in idxs:
                if isinstance(i, int):
                    positions.append((i, word))
    positions.sort()
    return " ".join(w for _, w in positions)[:1500]


async def _openalex_search(query: str, top_k: int = MAX_RESULTS_PER_QUERY) -> list[dict]:
    """OpenAlex 检索（覆盖 2.5 亿+ 学术作品，带引用数）。"""
    params = {"search": query, "per_page": min(top_k, 25), "sort": "relevance_score:desc"}
    if CONTACT_EMAIL:
        params["mailto"] = CONTACT_EMAIL
    if OPENALEX_API_KEY:
        params["api_key"] = OPENALEX_API_KEY
    async with httpx.AsyncClient(follow_redirects=True) as client:
        resp = await _get(client, "https://api.openalex.org/works", params=params, headers=HTTP_HEADERS_JSON)
    if resp is None:
        return []
    if resp.status_code == 429:
        _record_source_error("openalex", 429, "OpenAlex 匿名每日额度已用尽（可配置 OPENALEX_API_KEY 或 CONTACT_EMAIL 获得独立配额）")
        return []
    if resp.status_code != 200:
        _record_source_error("openalex", resp.status_code, f"OpenAlex 返回 {resp.status_code}")
        return []

    try:
        items = resp.json().get("results") or []
    except Exception as e:
        logger.warning("OpenAlex 响应解析失败：%s", e)
        return []

    results: list[dict] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        oid = (item.get("id") or "").rsplit("/", 1)[-1]
        authors = [
            {"name": (au.get("author") or {}).get("display_name", "")}
            for au in (item.get("authorships") or [])
            if isinstance(au, dict) and (au.get("author") or {}).get("display_name")
        ]
        primary = item.get("primary_location") or {}
        source_info = primary.get("source") if isinstance(primary, dict) else None
        venue = (source_info or {}).get("display_name", "") if isinstance(source_info, dict) else ""
        doi = _norm_doi(item.get("doi") or "")
        results.append({
            "paperId": "oa_" + oid if oid else "oa_" + _norm_title(item.get("title") or "")[:24],
            "title": _strip_html(item.get("title") or item.get("display_name") or ""),
            "authors": authors,
            "year": item.get("publication_year"),
            "citationCount": int(item.get("cited_by_count") or 0),
            "abstract": _invert_abstract(item.get("abstract_inverted_index")),
            "venue": venue,
            "externalIds": {**({"OpenAlex": oid} if oid else {}), **({"DOI": doi} if doi else {})},
        })
    return results


async def _s2_search(query: str, top_k: int = MAX_RESULTS_PER_QUERY) -> list[dict]:
    """Semantic Scholar 检索（相关度最好，但匿名调用限流严重）。"""
    global _s2_disabled_until
    if time.time() < _s2_disabled_until:
        return []

    params = {
        "query": query,
        "limit": min(top_k, 100),
        "fields": "paperId,title,authors,year,citationCount,abstract,venue,externalIds",
    }
    async with httpx.AsyncClient(follow_redirects=True) as client:
        resp = await _get(client, f"{SEMANTIC_SCHOLAR_API}/paper/search", params=params, headers=_s2_headers())

    if resp is None:
        return []
    if resp.status_code == 429:
        _s2_disabled_until = time.time() + 120
        _record_source_error("s2", 429, "Semantic Scholar 限流（匿名额度很低，配置 S2_API_KEY 可解决）")
        logger.warning("Semantic Scholar 限流，暂停 120 秒后重试")
        return []
    if resp.status_code != 200:
        _record_source_error("s2", resp.status_code, f"Semantic Scholar 返回 {resp.status_code}")
        return []
    try:
        return resp.json().get("data") or []
    except Exception:
        return []


async def _s2_detail(paper_id: str, fields: list[str]) -> Optional[dict]:
    global _s2_disabled_until
    if time.time() < _s2_disabled_until:
        return None
    async with httpx.AsyncClient(follow_redirects=True) as client:
        resp = await _get(
            client, f"{SEMANTIC_SCHOLAR_API}/paper/{quote(paper_id, safe='')}",
            params={"fields": ",".join(fields)}, headers=_s2_headers(),
        )
    if resp is None:
        return None
    if resp.status_code == 429:
        _s2_disabled_until = time.time() + 120
        return None
    if resp.status_code != 200:
        return None
    try:
        return resp.json()
    except Exception:
        return None


async def _search_one_source(source: str, query: str, top_k: int) -> list[dict]:
    fn = {
        "arxiv": _arxiv_search,
        "crossref": _crossref_search,
        "openalex": _openalex_search,
        "s2": _s2_search,
    }[source]
    # ArXiv 有 3 秒节流 + 退避重试，给它更宽的预算
    budget = SOURCE_TIMEOUT * 2 + 20 if source == "arxiv" else SOURCE_TIMEOUT + 8
    try:
        # 双保险：即使底层库不遵守超时，也不会让整个任务卡死
        return await asyncio.wait_for(fn(query, top_k), timeout=budget)
    except asyncio.TimeoutError:
        logger.warning("%s 检索超时（query=%s）", source, query)
        return []
    except Exception as e:
        logger.warning("%s 检索异常：%s: %s", source, type(e).__name__, e)
        return []


async def tool_hybrid_search(
    keyword_groups: list[list[str]],
    top_k: int = MAX_RESULTS_PER_QUERY,
    sources: Optional[list[str]] = None,
) -> tuple[list[Paper], list[str]]:
    """
    多源并行检索：对每一组关键词同时查询所有数据源，按 DOI/ArXiv/标题去重合并。

    返回 (论文列表, 真正返回过数据的数据源名列表)。
    """
    sources = sources or ["arxiv", "crossref", "openalex", "s2"]
    queries: list[str] = []
    for group in (keyword_groups or [])[:MAX_KEYWORD_GROUPS]:
        if not group:
            continue
        words = [str(w).strip() for w in group if str(w).strip()]
        if not words:
            continue
        # 2 个以上词时用 AND 组合提高精确度，单个词直接用
        queries.append(" AND ".join(words) if len(words) >= 2 else words[0])
    if not queries:
        return [], []

    sem = asyncio.Semaphore(SEARCH_CONCURRENCY)
    per_source_count = {s: 0 for s in sources}
    # ArXiv 有 3 秒节流且容易被限流，只放行前 4 组关键词，其余额度让给其他数据源
    arxiv_budget = 4 if "arxiv" in sources else 0

    async def run(source: str, query: str):
        async with sem:
            rows = await _search_one_source(source, query, top_k)
        if rows:
            per_source_count[source] += len(rows)
        return source, rows

    jobs = []
    for q in queries:
        for s in sources:
            if s == "arxiv":
                if arxiv_budget <= 0:
                    continue
                arxiv_budget -= 1
            jobs.append(run(s, q))
    store: dict[str, Paper] = {}
    for coro in asyncio.as_completed(jobs):
        source, rows = await coro
        for d in rows:
            if isinstance(d, dict):
                _merge_into(store, d, source)

    used = [s for s, n in per_source_count.items() if n > 0]
    papers = sorted(store.values(), key=lambda p: (-p.citationCount, -(p.year or 0)))
    logger.info("检索完成：%d 组关键词 × %d 个数据源 → %d 篇去重后候选（来源：%s）",
                len(queries), len(sources), len(papers), ",".join(used) or "无")
    return papers, used


async def tool_expand_citations(seed_paper_ids: list[str], max_per: int = 20) -> list[Paper]:
    """引用扩展：获取种子论文的参考文献与引证文献（依赖 Semantic Scholar）。"""
    if not seed_paper_ids:
        return []
    result: dict[str, Paper] = {}
    fields = ["paperId", "title", "authors", "year", "citationCount", "abstract", "venue", "externalIds", "references", "citations"]
    for pid in seed_paper_ids[:5]:
        detail = await _s2_detail(pid, fields)
        if detail:
            for key in ("references", "citations"):
                for row in (detail.get(key) or [])[:max_per]:
                    if isinstance(row, dict) and row.get("paperId"):
                        _merge_into(result, row, "citation_expand")
        await asyncio.sleep(0.4)
    return list(result.values())


# ═══════════════════════════════════════════════════════════════════
#  工具 3: 相关性验证器 (Relevance Validator)
# ═══════════════════════════════════════════════════════════════════
async def tool_validate_relevance(
    papers: list[Paper], topic: str, llm: Optional[LLMConfig] = None, threshold: int = 4,
) -> list[Paper]:
    """LLM 批量打分，只保留 score >= threshold 的论文；无 LLM 时退化为主题相关度 + 引用影响力排序。"""
    if not papers:
        return []
    llm = llm or _resolve_llm_config()
    if not llm.enabled:
        logger.info("未配置 LLM，采用主题相关度 + 引用影响力启发式筛选")
        return _heuristic_papers(papers, topic)

    # 先按引用数取前 N 篇送给 LLM，避免候选过多导致耗时/费用失控
    candidates = sorted(papers, key=lambda p: -p.citationCount)[:LLM_MAX_PAPERS]
    validated: list[Paper] = []

    for i in range(0, len(candidates), LLM_BATCH_SIZE):
        batch = candidates[i:i + LLM_BATCH_SIZE]
        payload = json.dumps(
            [
                {
                    "paperId": p.paperId,
                    "title": p.title,
                    "abstract": (p.abstract or "")[:500],
                    "year": p.year,
                    "citationCount": p.citationCount,
                }
                for p in batch
            ],
            ensure_ascii=False,
        )
        prompt = f"""你是一位严苛的文献评审员。综述主题：【{topic}】

请评估下列论文与主题的相关性，并输出 JSON。

论文列表：
{payload}

评分规则（1-5 整数）：
- 5 = 直接解决核心问题，必引
- 4 = 高度相关，提供重要方法/数据/背景/理论支撑
- 3 = 部分相关，仅提及概念
- 2 = 边缘相关
- 1 = 无关

分类（type）：method | application | survey | theory | benchmark | other

只输出 JSON 对象，格式为 {{"results": [{{"paperId": "...", "score": 4, "reason": "具体中文理由", "type": "method"}}]}}。
必须为列表中的每一篇论文都给出评分。"""

        data = await _llm_json(llm, prompt, temperature=0.0, max_tokens=3000)
        score_map: dict[str, tuple[int, str, str]] = {}
        rows = data
        if isinstance(data, dict):
            for key in ("results", "papers", "scores", "data"):
                if key in data:
                    rows = data[key]
                    break
            else:
                rows = [data] if "score" in data else []
        for item in (rows or []):
            if isinstance(item, dict) and item.get("paperId") is not None and item.get("score") is not None:
                try:
                    score = int(float(item["score"]))
                except (TypeError, ValueError):
                    continue
                ptype = str(item.get("type") or item.get("paper_type") or "other").lower()
                if ptype not in {"method", "application", "survey", "theory", "benchmark", "other"}:
                    ptype = "other"
                score_map[str(item["paperId"])] = (score, str(item.get("reason") or ""), ptype)

        for p in batch:
            hit = score_map.get(p.paperId)
            if hit:
                p.score, p.reason, p.paper_type = hit
                if p.score >= threshold:
                    validated.append(p)
            elif not score_map:
                # 整批都没解析出来（如模型不支持 JSON 模式）→ 不敢丢，按启发式保留
                p.score, p.reason, p.paper_type = 3, "LLM 未返回该篇评分，默认保留", "other"
                validated.append(p)

        logger.info("LLM 打分进度：%d/%d，已通过 %d 篇", min(i + LLM_BATCH_SIZE, len(candidates)), len(candidates), len(validated))

    return validated


# ═══════════════════════════════════════════════════════════════════
#  工具 4: 缺口分析器 (Gap Analyzer)
# ═══════════════════════════════════════════════════════════════════
def _fmt_gap(item: Any) -> str:
    if isinstance(item, dict):
        text = item.get("recommendation") or item.get("suggestion") or item.get("text") or ""
        reason = item.get("reason") or item.get("why") or ""
        if text and reason:
            return f"{text}（{reason}）"
        return text or json.dumps(item, ensure_ascii=False)
    return str(item)


async def tool_gap_analyzer(
    validated_papers: list[Paper], topic: str, decomposition: TopicDecomposition, llm: Optional[LLMConfig] = None,
) -> list[str]:
    """分析文献覆盖缺口，给出补充检索建议。"""
    if not validated_papers:
        return ["未收集到有效论文：建议更换主题词，或检查网络能否访问 ArXiv / CrossRef / OpenAlex。"]

    llm = llm or _resolve_llm_config()
    if not llm.enabled:
        return _basic_gaps(validated_papers, topic)

    summary = "\n".join(
        f"- [{p.paper_type}] ({p.score}分) {p.title} ({p.year or 'n.d.'}) 引用{p.citationCount}"
        for p in validated_papers[:40]
    )
    aspects = json.dumps([str(s.get("aspect", "")) for s in decomposition.sub_topics], ensure_ascii=False)
    current_year = time.localtime().tm_year

    prompt = f"""基于已收集的 {len(validated_papers)} 篇文献，针对主题「{topic}」做覆盖缺口分析。

已覆盖子主题：{aspects}
代表文献：
{summary}

分析维度：1) 是否遗漏高引经典；2) 是否有子主题完全未覆盖；3) 是否缺少局限/负面结果；4) 是否缺少近两年进展（当前年份 {current_year}）；5) 是否缺少基准方法。

只输出 JSON 对象：{{"suggestions": ["搜索关键词: xxx — 补充理由", ...]}}
每条是完整中文句子，形如「搜索关键词: XAI medical imaging survey — 补充可解释AI在医学影像中的综述」，给出 3-6 条。"""

    data = await _llm_json(llm, prompt, temperature=0.2, max_tokens=1200)
    rows = data
    if isinstance(data, dict):
        for key in ("suggestions", "gaps", "recommendations", "results"):
            if key in data:
                rows = data[key]
                break
        else:
            rows = [data]
    if isinstance(rows, str):
        rows = [rows]
    if not isinstance(rows, (list, tuple)):
        return _basic_gaps(validated_papers, topic)
    out = [_fmt_gap(x) for x in rows if x]
    return out or _basic_gaps(validated_papers, topic)


def _basic_gaps(papers: list[Paper], topic: str) -> list[str]:
    """无 LLM 时的规则化缺口提示。"""
    now = time.localtime().tm_year
    tips: list[str] = []
    if not any((p.year or 0) >= now - 2 for p in papers):
        tips.append(f"搜索关键词: {topic} {now - 1} — 缺少近两年最新进展")
    if not any(p.paper_type == "survey" for p in papers):
        tips.append(f"搜索关键词: {topic} survey review — 缺少系统性综述以建立框架")
    if not any(p.citationCount >= 100 for p in papers):
        tips.append(f"搜索关键词: {topic} classic seminal — 缺少高引奠基性工作")
    if not any(re.search(r"challenge|limitation|风险|挑战", p.title, re.I) for p in papers):
        tips.append(f"搜索关键词: {topic} challenges limitations — 缺少局限性与开放问题讨论")
    return tips or [f"搜索关键词: {topic} benchmark dataset — 可进一步补充基准与数据集工作"]


# ═══════════════════════════════════════════════════════════════════
#  Agent 编排器 (Orchestrator)
# ═══════════════════════════════════════════════════════════════════
def _prune_tasks() -> None:
    """清理过期任务，避免内存无限增长。只回收已结束的任务，正在跑的一律不动。"""
    if len(tasks) < 200:
        return
    cutoff = time.time() - TASK_TTL_SECONDS
    for tid in [t for t, p in tasks.items()
                if p.status in ("completed", "error") and p.created_at < cutoff]:
        tasks.pop(tid, None)


async def run_literature_survey(
    task_id: str,
    topic: str,
    max_iters: int = 1,
    seed_ids: Optional[list[str]] = None,
    user_notes: str = "",
    extra_kw: Optional[list[str]] = None,
    llm: Optional[LLMConfig] = None,
) -> TaskProgress:
    """
    文献调研主流程：
      阶段 1 主题解析 → 阶段 2 多源检索 → 阶段 3 引文扩展(可选) → 阶段 4 相关性验证 → 阶段 5 缺口分析 → 完成
    """
    llm = llm or _resolve_llm_config()
    p = tasks[task_id]
    started = time.time()
    seed_ids = [s for s in (seed_ids or []) if s]
    extra_kw = [k for k in (extra_kw or []) if k]
    p.llm_enabled = llm.enabled

    def tick(pct: int, phase: str, message: str) -> None:
        p.progress_pct = pct
        p.phase = phase
        p.message = message
        p.elapsed_seconds = round(time.time() - started, 1)

    try:
        p.status = "running"
        p.topic = topic

        # ── 阶段 1：主题解析
        tick(5, "decompose", "正在解析主题，生成检索框架…")
        dec = await tool_decompose_topic(topic, user_notes, llm)
        if extra_kw:
            dec.keyword_groups.append(extra_kw)
        p.decomposition = dec
        logger.info("[%s] 阶段1 完成：%d 组关键词", task_id, len(dec.keyword_groups))

        all_papers: dict[str, Paper] = {}
        validated: list[Paper] = []
        used_sources: list[str] = []

        for it in range(max_iters):
            p.iteration = it + 1

            # ── 阶段 2：多源检索
            tick(15 + it * 20, "search", f"第 {it + 1}/{max_iters} 轮：正在并行检索 ArXiv / CrossRef / OpenAlex / Semantic Scholar…")
            papers, used = await tool_hybrid_search(dec.keyword_groups, MAX_RESULTS_PER_QUERY)
            for pp in papers:
                all_papers.setdefault(pp.paperId or _norm_title(pp.title), pp)
            for s in used:
                if s not in used_sources:
                    used_sources.append(s)
            p.sources_used = used_sources
            p.candidate_count = len(all_papers)
            p.source_warnings = _recent_source_errors()
            logger.info("[%s] 阶段2 完成：候选 %d 篇", task_id, len(all_papers))

            if not all_papers:
                tick(60, "search", "所有数据源都没返回结果，正在使用内置保底文献演示流程…")
                for d in FALLBACK_PAPERS:
                    _merge_into(all_papers, d, "offline_fallback")
                p.candidate_count = len(all_papers)
                p.sources_used = used_sources = used_sources + ["offline_fallback"]

            # ── 阶段 3：引文扩展（Semantic Scholar 可用时）
            if it == 0:
                tick(45, "expand", "正在扩展引用网络…")
                roots = seed_ids or [x.paperId for x in sorted(all_papers.values(), key=lambda x: -x.citationCount)[:3]]
                roots = [r for r in roots if r and not r.startswith(("oa_", "doi_", "cr_", "fallback_"))]
                if roots:
                    cited = await tool_expand_citations(roots, max_per=15)
                    for pp in cited:
                        all_papers.setdefault(pp.paperId or _norm_title(pp.title), pp)
                    p.candidate_count = len(all_papers)
                    logger.info("[%s] 阶段3 完成：扩展后候选 %d 篇", task_id, len(all_papers))
                else:
                    logger.info("[%s] 阶段3 跳过：没有可用于引文扩展的 Semantic Scholar ID", task_id)

            # ── 阶段 4：相关性验证
            tick(65, "validate", f"相关性验证中（{len(all_papers)} 篇候选）…")
            validated = await tool_validate_relevance(list(all_papers.values()), topic, llm, threshold=4)
            p.validated_count = len(validated)
            p.results = sorted(validated, key=lambda x: (-x.score, -x.citationCount))
            logger.info("[%s] 阶段4 完成：%d 篇通过筛选", task_id, len(validated))

            # 无 LLM 且没有一篇真正贴题时，明确告诉用户原因和改进办法，而不是默默给出一堆擦边结果
            hint: list[str] = []
            if not llm.enabled and validated:
                avg_rel = sum(x.rel for x in validated) / len(validated)
                if avg_rel < 0.3 or len(validated) <= 3:
                    hint.append("本次未找到高度贴题的文献：建议在左侧填入 DeepSeek/OpenAI API Key 启用语义筛选，"
                                "或把主题改写成英文关键词（如 graph neural network drug target prediction）后重试。")
                    p.message = (f"已收集 {len(validated)} 篇候选文献，但主题匹配度偏低"
                                 f"（平均 {round(avg_rel * 100)}%），建议配置 API Key 或改用英文主题。")

            # ── 阶段 5：缺口分析（最后一轮，或用结果驱动下一轮）
            tick(85, "gap", "正在分析文献覆盖缺口…")
            gaps = await tool_gap_analyzer(validated, topic, dec, llm)
            warn = [f"⚠️ {w}" for w in p.source_warnings]
            p.gap_suggestions = hint + warn + gaps
            if it < max_iters - 1:
                extra_queries: list[list[str]] = []
                for s in gaps[:4]:
                    kw = re.split(r"[—\-–:]", s.replace("搜索关键词:", "").replace("搜索关键词：", ""), maxsplit=1)[0].strip()
                    if kw:
                        extra_queries.append([kw])
                if not extra_queries:
                    logger.info("[%s] 没有生成新的检索建议，提前结束迭代", task_id)
                    break
                dec.keyword_groups = extra_queries  # 下一轮按缺口建议检索

        # ── 收尾
        final = sorted(validated, key=lambda x: (-x.score, -x.citationCount))
        p.results = final
        p.validated_count = len(final)
        p.status = "completed"
        tick(100, "final", f"调研完成：共筛选出 {len(final)} 篇高质量文献（候选 {p.candidate_count} 篇）。")
        logger.info("[%s] 全部完成：%d 篇，用时 %.1fs", task_id, len(final), time.time() - started)

    except asyncio.CancelledError:
        p.status = "error"
        p.error = "任务被取消"
        p.message = "任务被取消"
        raise
    except Exception as e:
        logger.exception("[%s] 任务失败：%s", task_id, e)
        p.status = "error"
        p.error = f"{type(e).__name__}: {e}"
        p.message = f"任务出错：{e}"
    finally:
        p.elapsed_seconds = round(time.time() - started, 1)

    return p


def _spawn(coro) -> None:
    """启动后台任务并持有强引用，避免被 GC 提前回收。"""
    task = asyncio.create_task(coro)
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)


# ═══════════════════════════════════════════════════════════════════
#  API 路由（必须在静态文件挂载之前注册）
# ═══════════════════════════════════════════════════════════════════
app = FastAPI(title="文献调研智能体", version="1.1.0")
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_credentials=False,
    allow_methods=["*"], allow_headers=["*"],
)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request, exc):  # pragma: no cover - 兜底
    logger.exception("未处理异常 %s: %s", request.url.path, exc)
    return JSONResponse(status_code=500, content={"detail": f"服务器内部错误: {type(exc).__name__}: {exc}"})


def _split_ids(raw: str) -> list[str]:
    return [x.strip() for x in (raw or "").split(",") if x.strip()]


@app.get("/api/health")
async def api_health():
    """健康检查（Render / Docker 探针使用）。"""
    llm = _resolve_llm_config()
    return {
        "status": "ok",
        "version": app.version,
        "llm_enabled": llm.enabled,
        "llm_provider": llm.provider if llm.enabled else "",
        "llm_model": llm.model if llm.enabled else "",
        "server_key_policy": "allow_anonymous" if ALLOW_SERVER_KEY_FOR_ANON else "self_key_only",
        "s2_key_configured": bool(S2_API_KEY),
        "active_tasks": _active_task_count(),
        "total_tasks": len(tasks),
    }


@app.get("/api/config")
async def api_config():
    """前端启动时读取：默认提供商/模型，以及服务端是否已内置 Key。"""
    llm = _resolve_llm_config()
    return {
        "default_provider": LLM_PROVIDER if LLM_PROVIDER in LLM_BASE_URLS else "openai",
        "default_model": llm.model,
        "server_key_configured": llm.enabled,
        # 公开部署时，服务器 Key 默认只对自带 Key 的请求生效
        "server_key_for_anonymous": ALLOW_SERVER_KEY_FOR_ANON,
        "rate_limit_per_minute": RATE_LIMIT_PER_MINUTE,
        "max_active_tasks": MAX_ACTIVE_TASKS,
        "providers": {
            "openai": {"label": "OpenAI", "models": ["gpt-4o-mini", "gpt-4o", "gpt-4-turbo"]},
            "deepseek": {"label": "DeepSeek", "models": ["deepseek-chat", "deepseek-reasoner"]},
        },
        "sources": [
            {"id": "arxiv", "label": "ArXiv", "note": "预印本，仅支持英文关键词"},
            {"id": "crossref", "label": "CrossRef", "note": "正式出版物元数据，覆盖最广"},
            {"id": "openalex", "label": "OpenAlex", "note": "综合库，带引用数"},
            {"id": "s2", "label": "Semantic Scholar", "note": "限流较严，失败自动跳过"},
        ],
        "recent_source_warnings": _recent_source_errors(),
        "polite_pool_configured": bool(CONTACT_EMAIL or OPENALEX_API_KEY),
    }


@app.post("/api/search")
async def api_search(
    request: Request,
    req: SearchRequest,
    x_llm_provider: str = Header(""),
    x_llm_model: str = Header(""),
    x_api_key: str = Header(""),
):
    """创建调研任务，立即返回 task_id，前端轮询 /api/status/{task_id}。"""
    topic = req.topic.strip()
    if not topic:
        raise HTTPException(400, "主题不能为空")
    if len(topic) > 500:
        raise HTTPException(400, "主题过长（最多 500 字）")

    await _guard(request, "search")
    _prune_tasks()
    # anon=True：调用方没带 Key 时，是否可用服务器 Key 由 ALLOW_SERVER_KEY_FOR_ANON 决定
    llm = _resolve_llm_config(x_llm_provider, x_llm_model, x_api_key, anon=not x_api_key.strip())
    task_id = uuid.uuid4().hex[:12]
    progress = TaskProgress(task_id=task_id, status="queued", topic=topic, message="任务已创建，等待处理…", llm_enabled=llm.enabled)
    tasks[task_id] = progress

    _spawn(run_literature_survey(
        task_id=task_id,
        topic=topic,
        max_iters=req.max_iterations,
        seed_ids=req.seed_paper_ids,
        user_notes=req.user_notes,
        llm=llm,
    ))
    logger.info("[%s] 新任务：%s（来自 %s，LLM=%s/%s）", task_id, topic, _client_ip(request),
                llm.provider if llm.enabled else "off", llm.model)
    return {"task_id": task_id, "status": "queued", "message": "任务已启动", "llm_enabled": llm.enabled}


@app.post("/api/refine")
async def api_refine(
    request: Request,
    req: RefineRequest,
    x_llm_provider: str = Header(""),
    x_llm_model: str = Header(""),
    x_api_key: str = Header(""),
):
    """基于已有任务结果做补充检索（新开一个任务，保留原结果）。"""
    if req.task_id not in tasks:
        raise HTTPException(404, "任务不存在")
    origin = tasks[req.task_id]
    if origin.status not in ("completed", "error"):
        raise HTTPException(400, "任务尚未结束，无法补充检索")

    await _guard(request, "refine")
    llm = _resolve_llm_config(x_llm_provider, x_llm_model, x_api_key, anon=not x_api_key.strip())
    topic = (origin.decomposition.core_question if origin.decomposition else "") or origin.topic or req.feedback
    task_id = uuid.uuid4().hex[:12]
    progress = TaskProgress(task_id=task_id, status="queued", topic=topic,
                            message=f"补充检索：{req.feedback[:50]}", llm_enabled=llm.enabled)
    tasks[task_id] = progress

    _spawn(run_literature_survey(
        task_id=task_id, topic=topic, max_iters=1,
        seed_ids=[], user_notes=req.feedback, extra_kw=req.new_keywords, llm=llm,
    ))
    return {"task_id": task_id, "status": "queued", "message": "补充检索已启动"}


@app.get("/api/status/{task_id}")
async def api_status(task_id: str):
    if task_id not in tasks:
        raise HTTPException(404, "任务不存在")
    return tasks[task_id]


@app.get("/api/results/{task_id}")
async def api_results(task_id: str):
    """只取最终结果（轻量，适合结果页刷新）。"""
    if task_id not in tasks:
        raise HTTPException(404, "任务不存在")
    p = tasks[task_id]
    if p.status != "completed":
        return {"status": p.status, "phase": p.phase, "message": p.message, "results": []}
    return {
        "status": "completed",
        "topic": p.topic,
        "total_count": len(p.results),
        "decomposition": p.decomposition.model_dump() if p.decomposition else None,
        "gap_suggestions": p.gap_suggestions,
        "papers": [pp.model_dump() for pp in p.results],
    }


def _bibtex(papers: list[Paper]) -> str:
    entries = []
    for pp in papers:
        key = re.sub(r"[^A-Za-z0-9]", "", (pp.authors[0].split()[-1] if pp.authors else "anon")) + str(pp.year or "nd") + pp.paperId[:6]
        authors = " and ".join(pp.authors[:10]) + (" and others" if len(pp.authors) > 10 else "")
        fields = [
            ("title", pp.title),
            ("author", authors),
            ("year", str(pp.year or "n.d.")),
            ("journal", pp.venue),
            ("doi", pp.externalIds.get("DOI", "")),
            ("url", pp.url),
        ]
        body = ",\n".join(f"  {k} = {{{v}}}" for k, v in fields if v)
        entries.append(f"@article{{{key},\n{body}\n}}")
    return "\n\n".join(entries)


def _markdown(papers: list[Paper], topic: str, gaps: list[str]) -> str:
    lines = [f"# 文献调研报告：{topic}", "", f"共 {len(papers)} 篇文献。", ""]
    for i, pp in enumerate(papers, 1):
        authors = ", ".join(pp.authors[:3]) + (" et al." if len(pp.authors) > 3 else "")
        lines.append(f"## {i}. {pp.title}")
        lines.append(f"- 作者：{authors or '未知'}")
        lines.append(f"- 年份：{pp.year or 'n.d.'}　引用：{pp.citationCount}　评分：{pp.score}　类型：{pp.paper_type}")
        if pp.venue:
            lines.append(f"- 来源：{pp.venue}")
        if pp.url:
            lines.append(f"- 链接：{pp.url}")
        if pp.reason:
            lines.append(f"- 入选理由：{pp.reason}")
        lines.append("")
    if gaps:
        lines += ["## 补充检索建议", ""] + [f"- {g}" for g in gaps]
    return "\n".join(lines)


@app.get("/api/export/{task_id}")
async def api_export(task_id: str, fmt: str = "json"):
    if task_id not in tasks:
        raise HTTPException(404, "任务不存在")
    p = tasks[task_id]
    fmt = (fmt or "json").lower()
    topic = (p.decomposition.core_question if p.decomposition else "") or p.topic

    if fmt == "bibtex":
        return {"format": "bibtex", "total_count": len(p.results), "content": _bibtex(p.results)}
    if fmt in ("markdown", "md"):
        return {"format": "markdown", "total_count": len(p.results), "content": _markdown(p.results, topic, p.gap_suggestions)}
    if fmt == "csv":
        rows = ["title,authors,year,citations,score,type,source,venue,url"]
        for pp in p.results:
            cells = [
                pp.title, "; ".join(pp.authors[:3]), str(pp.year or ""), str(pp.citationCount),
                str(pp.score), pp.paper_type, pp.source, pp.venue, pp.url,
            ]
            rows.append(",".join('"' + str(c).replace('"', '""') + '"' for c in cells))
        return {"format": "csv", "total_count": len(p.results), "content": "\n".join(rows)}

    return {
        "format": "json",
        "topic": topic,
        "total_count": len(p.results),
        "candidate_count": p.candidate_count,
        "sources_used": p.sources_used,
        "papers": [pp.model_dump() for pp in p.results],
        "decomposition": p.decomposition.model_dump() if p.decomposition else None,
        "gap_suggestions": p.gap_suggestions,
    }


@app.get("/api/paper/{paper_id}")
async def api_paper_detail(paper_id: str):
    fields = [
        "paperId", "title", "authors", "year", "citationCount", "abstract", "venue",
        "externalIds", "references", "citations", "tldr", "publicationTypes", "journal", "fieldsOfStudy",
    ]
    res = await _s2_detail(paper_id, fields)
    if not res:
        raise HTTPException(404, "论文未找到（Semantic Scholar 可能正在限流）")
    return res


@app.get("/api/lanip")
async def api_lanip():
    """返回本机局域网 IP，便于同一网络下的手机/平板访问。"""
    import socket
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
        finally:
            s.close()
        return {"ip": ip}
    except Exception:
        return {"ip": "unknown"}


@app.get("/api/debug_sources")
async def api_debug_sources(q: str = "graph neural network"):
    """逐个数据源自检，排查“搜不到结果”时非常有用。"""
    out: dict[str, Any] = {"topic": q, "contact_email": CONTACT_EMAIL or "(未配置)",
                           "openalex_key": bool(OPENALEX_API_KEY), "s2_key": bool(S2_API_KEY)}
    for name in ("arxiv", "crossref", "openalex", "s2"):
        t0 = time.time()
        rows = await _search_one_source(name, q, 5)
        err = _source_errors.get(name)
        out[name] = {
            "count": len(rows),
            "seconds": round(time.time() - t0, 2),
            "status": "ok" if rows else ("error" if err and time.time() - err[0] < 60 else "empty"),
            "note": err[1] if err and time.time() - err[0] < 600 else "",
            "sample": (rows[0].get("title", "")[:80] if rows else ""),
        }
    return out


# 静态文件挂载（必须放在所有 API 路由之后，否则会把 /api/* 一起吞掉）
static_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
if os.path.isdir(static_dir):
    @app.middleware("http")
    async def static_no_cache(request: Request, call_next):
        """
        前端三件套（html/css/js）要求浏览器每次回源校验。
        否则改了脚本、用户浏览器仍跑旧缓存，会出现"页面明明修好了却还是坏"的假象。
        """
        response = await call_next(request)
        path = request.url.path
        if path.endswith((".html", ".css", ".js")) or path in ("/", ""):
            response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
            response.headers["Pragma"] = "no-cache"
        return response

    app.mount("/", StaticFiles(directory=static_dir, html=True), name="static")
else:  # pragma: no cover
    logger.warning("未找到静态目录：%s，网页将无法访问", static_dir)


if __name__ == "__main__":
    import uvicorn

    # 云平台（Render / Railway / HF Spaces）通过 PORT 注入端口，本地默认 8765
    port = int(os.environ.get("PORT") or os.environ.get("APP_PORT") or 8765)
    host = os.environ.get("HOST", "0.0.0.0")
    logger.info("文献调研智能体启动中 → http://%s:%d/", "127.0.0.1" if host == "0.0.0.0" else host, port)
    uvicorn.run(app, host=host, port=port)
