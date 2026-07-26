"""
文献调研智能体 (Literature Survey Agent)
========================================
基于 Semantic Scholar API + OpenAI LLM 的精准文献搜集系统。
工作流程：主题解析 → 多策略检索 → 引文扩展 → 相关性验证 → 缺口分析 → 迭代优化
项目背景：山东大学首届人工智能创新应用大赛 (https://aihub.sdu.edu.cn/aiic/)
"""

import asyncio
import json
import logging
import os
import uuid
from typing import Any, Optional

import httpx
from fastapi import FastAPI, HTTPException, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from openai import AsyncOpenAI
from pydantic import BaseModel, Field

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("literature_agent")

OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
LLM_MODEL = os.environ.get("LLM_MODEL", "gpt-4o")
S2_API_BASE = "https://api.semanticscholar.org/graph/v1"
S2_API_KEY = os.environ.get("S2_API_KEY", "")

# ── LLM 提供商配置（支持 OpenAI 和 DeepSeek）
LLM_PROVIDER = os.environ.get("LLM_PROVIDER", "openai").lower()
LLM_API_KEY = os.environ.get("LLM_API_KEY", "") or OPENAI_API_KEY

# OpenAI 兼容 API 端点
LLM_BASE_URLS = {
    "openai": "https://api.openai.com/v1",
    "deepseek": "https://api.deepseek.com",
}
_PROVIDER_MODEL_MAP = {
    "openai": ["gpt-4o", "gpt-4o-mini", "gpt-4-turbo", "gpt-3.5-turbo"],
    "deepseek": ["deepseek-chat", "deepseek-reasoner", "deepseek-v3"],
}


class SearchRequest(BaseModel):
    topic: str = Field(..., description="综述主题")
    max_iterations: int = Field(default=2, ge=1, le=3, description="最大迭代轮数")
    seed_paper_ids: list[str] = Field(default_factory=list, description="已知种子论文 ID")
    user_notes: str = Field(default="", description="用户补充说明")


class RefineRequest(BaseModel):
    task_id: str = Field(..., description="任务 ID")
    feedback: str = Field(..., description="用户反馈")
    new_keywords: list[str] = Field(default_factory=list)


class TopicDecomposition(BaseModel):
    core_question: str
    sub_topics: list[dict[str, Any]]
    keyword_groups: list[list[str]]
    seed_suggestions: str


class Paper(BaseModel):
    paperId: str
    title: str
    authors: list[str] = Field(default_factory=list)
    year: Optional[int] = None
    citationCount: int = 0
    abstract: str = ""
    venue: str = ""
    url: str = ""
    externalIds: dict[str, str] = Field(default_factory=dict)
    score: int = 0
    reason: str = ""
    paper_type: str = ""
    source: str = ""


class TaskProgress(BaseModel):
    status: str = "queued"
    phase: str = ""
    message: str = ""
    progress_pct: int = 0
    decomposition: Optional[TopicDecomposition] = None
    results: list[Paper] = Field(default_factory=list)
    validated_count: int = 0
    gap_suggestions: list[str] = Field(default_factory=list)
    iteration: int = 0
    error: str = ""


tasks: dict[str, TaskProgress] = {}
# S2 限流标志
_S2_RATE_LIMITED = False

app = FastAPI(title="文献调研智能体", version="1.0.0")
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_credentials=True,
    allow_methods=["*"], allow_headers=["*"],
)

def _get_llm_client(provider: str = "", model: str = "") -> Optional[AsyncOpenAI]:
    """根据提供商和模型创建 LLM 客户端 (支持 OpenAI / DeepSeek)
    如果没有 API Key, 返回 None, 工具函数会跳过 LLM 步骤"""
    prov = (provider or LLM_PROVIDER).lower()
    mdl = model or LLM_MODEL
    if not provider:
        for p, models in _PROVIDER_MODEL_MAP.items():
            if any(m in mdl.lower() for m in models):
                prov = p
                break
    base_url = LLM_BASE_URLS.get(prov, LLM_BASE_URLS["openai"])
    key = LLM_API_KEY or os.environ.get("LLM_API_KEY", "") or os.environ.get("OPENAI_API_KEY", "")
    if not key:
        logger.warning(f"未配置 LLM API Key, 跳过 LLM 增强步骤 (provider={prov})")
        return None
    return AsyncOpenAI(api_key=key, base_url=base_url)


def _s2_headers() -> dict[str, str]:
    h = {"User-Agent": "LiteratureSurveyAgent/1.0"}
    if S2_API_KEY:
        h["x-api-key"] = S2_API_KEY
    return h



def _get_paper_url(d: dict, source: str = "") -> str:
    """根据来源返回论文的正确链接"""
    eid = d.get("externalIds", {}) or {}
    pid = d.get("paperId", "")
    if source == "keyword_search" and pid:
        if "arxiv_" in pid:
            return "https://arxiv.org/abs/" + pid.replace("arxiv_", "")
    if eid.get("DOI"):
        return "https://doi.org/" + eid["DOI"]
    if eid.get("ArXiv"):
        return "https://arxiv.org/abs/" + eid["ArXiv"]
    if pid:
        return "https://www.semanticscholar.org/paper/" + pid
    return ""

def _build_paper(d: dict, source: str = "") -> Paper:
    aa = [a.get("name", "Unknown") for a in d.get("authors", []) if isinstance(a, dict)]
    eid = {k: str(v) for k, v in (d.get("externalIds", {}) or {}).items()}

    url = _get_paper_url(d, source)
    return Paper(
        paperId=d.get("paperId", ""),
        title=d.get("title", ""),
        authors=aa,
        year=d.get("year"),
        citationCount=d.get("citationCount", 0) or 0,
        abstract=d.get("abstract", "") or "",
        venue=d.get("venue", "") or "",
        url=url,
        externalIds=eid,
        source=source,
    )


# ═══════════════════════════════════════════════════════════════════
#  工具 1: 主题解构器 (Topic Decomposer)
# ═══════════════════════════════════════════════════════════════════
async def tool_decompose_topic(topic: str, user_notes: str = "") -> TopicDecomposition:
    """利用 LLM 将研究主题解析为结构化检索框架"""
    client = _get_llm_client()
    if client is None:
        logger.info("No LLM client, using basic topic decomposition")
        return TopicDecomposition(
            core_question=topic,
            sub_topics=[{"aspect": "主要方向", "methods": []}],
            keyword_groups=[[topic], [topic, "review"], [topic, "survey"]],
            seed_suggestions="LLM 未配置，请设置 API Key 以获取智能主题解析",
        )
    prompt = f"""你是一位系统综述方法论专家。给定一个研究主题，将其解析为结构化检索框架。

研究主题：{topic}
{f"用户补充说明：{user_notes}" if user_notes else ""}

输出严格的 JSON，包含：
1. "core_question": 一句话表述核心问题
2. "sub_topics": 子主题列表，每项含 "aspect" 和 "methods"/"settings"
3. "keyword_groups": 关键词分组（至少 6 组），每组 2-4 个关键词
   - 覆盖不同表述变体、子方向、综述词 review/survey、挑战词 challenge/limitation
4. "seed_suggestions": 建议关注的奠基性论文类型"""

    try:
        resp = await client.chat.completions.create(
            model=LLM_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
            response_format={"type": "json_object"},
        )
        data = json.loads(resp.choices[0].message.content or "{}")
    except Exception as e:
        logger.warning(f"LLM API failed, using basic: {e}")
        return TopicDecomposition(
            core_question=topic,
            sub_topics=[{"aspect": "主要方向", "methods": []}],
            keyword_groups=[[topic], [topic, "review"], [topic, "survey"]],
            seed_suggestions="",
        )
    return TopicDecomposition(
        core_question=" ".join(data.get("core_question", "")) if isinstance(data.get("core_question"), list) else data.get("core_question", ""),
        sub_topics=data.get("sub_topics", []),
        keyword_groups=data.get("keyword_groups", [["default", topic]]),
        seed_suggestions=", ".join(data.get("seed_suggestions", "")) if isinstance(data.get("seed_suggestions"), list) else data.get("seed_suggestions", ""),
    )


# ═══════════════════════════════════════════════════════════════════
#  工具 2: 精准混合检索器 (Hybrid Search)
# ═══════════════════════════════════════════════════════════════════
async def _s2_search(query: str, top_k: int = 15, _retry: int = 0) -> list[dict]:
    global _S2_RATE_LIMITED
    if _S2_RATE_LIMITED:
        return []
    """通过 Semantic Scholar API 用关键词检索（带指数退避重试）"""
    params = {
        "query": query,
        "limit": min(top_k, 100),
        "fields": ",".join([
            "paperId", "title", "authors", "year",
            "citationCount", "abstract", "venue", "externalIds",
        ]),
    }
    async with httpx.AsyncClient(follow_redirects=True) as client:
        try:
            pass  # S2 直接请求，不延迟
            resp = await client.get(
                f"{S2_API_BASE}/paper/search",
                params=params, headers=_s2_headers(), timeout=5.0,
            )
            if resp.status_code == 200:
                return resp.json().get("data", [])
            if resp.status_code == 429:
                # 快速失败，给 ArXiv 留时间
                if _retry >= 1:
                    logger.warning(f"S2 429, fast-failing to ArXiv: {query}")
                    return []
                logger.warning(f"S2 429, retrying once: {query}")
                await asyncio.sleep(3)
                return await _s2_search(query, top_k, _retry=_retry + 1)
            logger.warning(f"S2 error {resp.status_code}: {query}")
            return []
        except Exception as e:
            logger.error(f"S2 fail: {e}")
            return []



async def tool_hybrid_search(keyword_groups: list[list[str]], top_k: int = 8) -> list[Paper]:
    """快速多源搜索（跳过 S2，ArXiv + CrossRef + OpenAlex 并行）"""
    all_papers: dict[str, Paper] = {}
    tasks = []
    query = ""
    if keyword_groups and keyword_groups[0]:
        group = keyword_groups[0]
        query = " AND ".join(group) if len(group) >= 2 else group[0]
    
    if query:
        tasks.append(_search_arxiv_and_add(query, top_k, all_papers))
        tasks.append(_search_crossref_and_add(query, top_k, all_papers))
        tasks.append(_search_openalex_and_add(query, top_k, all_papers))
        await asyncio.gather(*tasks)
    
    return list(all_papers.values())


async def _search_arxiv_and_add(query: str, top_k: int, papers: dict):
    """ArXiv 搜索并添加到结果"""
    try:
        results = await _arxiv_search(query, top_k)
        for d in results:
            pid = d.get("paperId", "")
            if pid: papers.setdefault(pid, _build_paper(d, "arxiv"))
    except Exception as e:
        logger.warning(f"ArXiv search fail: {e}")


async def _search_crossref_and_add(query: str, top_k: int, papers: dict):
    """CrossRef 搜索并添加到结果"""
    try:
        results = await _crossref_search(query, top_k)
        for d in results:
            pid = d.get("paperId", "")
            if pid: papers.setdefault(pid, _build_paper(d, "crossref"))
    except Exception as e:
        logger.warning(f"CrossRef search fail: {e}")


async def _search_openalex_and_add(query: str, top_k: int, papers: dict):
    """OpenAlex 搜索并添加到结果"""
    try:
        results = await _openalex_search(query, top_k)
        for d in results:
            pid = d.get("paperId", "")
            if pid: papers.setdefault(pid, _build_paper(d, "openalex"))
    except Exception as e:
        logger.warning(f"OpenAlex search fail: {e}")





async def tool_expand_citations(
    seed_paper_ids: list[str], max_per: int = 20
) -> list[Paper]:
    """引用扩展：获取种子论文的参考文献和引证文献"""
    if not seed_paper_ids:
        return []
    result: dict[str, Paper] = {}
    flds = ["paperId", "title", "authors", "year", "citationCount",
            "abstract", "venue", "externalIds"]

    for pid in seed_paper_ids:
        detail = await _s2_detail(pid, flds + ["references", "citations"])
        if not detail:
            continue
        for ref in (detail.get("references") or [])[:max_per]:
            if isinstance(ref, dict) and ref.get("paperId"):
                result[ref["paperId"]] = _build_paper(ref, "citation_expand")
        for cit in (detail.get("citations") or [])[:max_per]:
            if isinstance(cit, dict) and cit.get("paperId"):
                result[cit["paperId"]] = _build_paper(cit, "citation_expand")
        await asyncio.sleep(0.5)

    return list(result.values())

# ═══════════════════════════════════════════════════════════════════
#  工具 4: 严格相关性验证器 (Relevance Validator)
# ═══════════════════════════════════════════════════════════════════
async def tool_validate_relevance(
    papers: list[Paper], topic: str, threshold: int = 4
) -> list[Paper]:
    """LLM 批量评分，只保留 >= threshold 的高质量论文"""
    if not papers:
        return []

    client = _get_llm_client()
    if client is None:
        # 无 LLM 时：按引用数排序，保留前 50%
        logger.info("No LLM client, using citation-based filtering")
        sorted_papers = sorted(papers, key=lambda p: -p.citationCount)
        cutoff = max(len(sorted_papers) // 2, 10)
        for p in sorted_papers[:cutoff]:
            p.score = 3
            p.reason = "基于引用数自动选取（未使用 LLM 评分）"
            p.paper_type = "other"
        return sorted_papers[:cutoff]
    validated: list[Paper] = []

    for i in range(0, len(papers), 25):
        batch = papers[i : i + 25]
        paper_list = json.dumps(
            [{"paperId": p.paperId, "title": p.title,
              "abstract": (p.abstract or "")[:500],
              "year": p.year, "citationCount": p.citationCount}
             for p in batch],
            ensure_ascii=False,
        )

        prompt = f"""你是一位严苛的文献评审员。根据综述主题：
【{topic}】

评估以下论文列表。为每篇论文评分（1-5）并提供分类。

论文列表：
{paper_list}

评分规则：
- 5 = 直接解决核心问题，方法/结论高度一致，必引
- 4 = 高度相关，提供重要方法/数据/背景/理论支撑
- 3 = 部分相关，仅提及概念但不深入
- 2 = 边缘相关
- 1 = 无关

分类：method | application | survey | theory | benchmark | other

输出 JSON 数组，每项包含：paperId, score（整数）, reason（具体中文理由）, type（类型）
严格：仅当论文主要目标与主题明确一致时才给 4-5 分。"""

        try:
            resp = await client.chat.completions.create(
                model=LLM_MODEL,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.0,
                response_format={"type": "json_object"},
            )
            content = resp.choices[0].message.content or "[]"
        except Exception as e:
            logger.warning(f"LLM validation failed, using defaults: {e}")
            for p in batch:
                p.score = 3
                p.reason = "LLM 不可用，默认保留"
                p.paper_type = "other"
                validated.append(p)
            continue

        try:
            scores = json.loads(content)
            if isinstance(scores, dict):
                for k in ("results", "papers", "scores", "data"):
                    if k in scores: scores = scores[k]; break
            if isinstance(scores, dict) and "score" in scores:
                scores = [scores]
        except json.JSONDecodeError:
            continue

        score_map = {}
        for item in (scores or []):
            if isinstance(item, dict) and "paperId" in item and "score" in item:
                score_map[item["paperId"]] = (
                    int(item["score"]), item.get("reason", ""), item.get("type", "other"),
                )

        for p in batch:
            if p.paperId in score_map:
                p.score, p.reason, p.paper_type = score_map[p.paperId]
                if p.score >= threshold:
                    validated.append(p)

        await asyncio.sleep(0.5)

    return validated


# ═══════════════════════════════════════════════════════════════════
#  工具 5: 缺口分析器 (Gap Analyzer)
# ═══════════════════════════════════════════════════════════════════

def _fmt_gap(s):
    """格式化缺口建议：支持 dict 和 string"""
    if isinstance(s, dict):
        rec = s.get("recommendation", s.get("suggestion", s.get("text", "")))
        reason = s.get("reason", "")
        if rec and reason: return f"{rec}（{reason}）"
        return rec or str(s)
    return str(s)

async def tool_gap_analyzer(
    validated_papers: list[Paper], topic: str, decomposition: TopicDecomposition
) -> list[str]:
    """分析文献覆盖缺口，生成补充搜索建议"""
    if not validated_papers:
        return ["未收集到有效论文，建议扩大关键词范围"]

    client = _get_llm_client()
    if client is None:
        logger.info("No LLM client, skipping gap analysis")
        return []
    summary = "\n".join(
        f"- [{p.paper_type}] ({p.score}分) {p.title} ({p.year}) 引{p.citationCount}"
        for p in validated_papers[:40]
    )
    subs = json.dumps([s.get("aspect", "") for s in decomposition.sub_topics], ensure_ascii=False)

    prompt = f"""基于当前已收集的 {len(validated_papers)} 篇文献，针对 "{topic}" 分析缺口。

已覆盖子主题：{subs}
代表文献（前40篇）：
{summary}

分析维度：
1. 是否遗漏高引早期经典？
2. 是否有子主题完全未覆盖？
3. 是否缺少负面结果/局限性讨论？
4. 是否缺少近2年最新进展？
5. 是否缺少关键基准方法？

输出 JSON 字符串数组，每条是一个完整的中文搜索建议句（包含推荐关键词和理由，用一句话表达）。示例：["搜索关键词: XAI medical imaging survey — 补充可解释AI在医学影像中的综述论文", "搜索关键词: LLM clinical decision support limitation — 获取LLM临床决策中的局限性讨论"]"""

    try:
        resp = await client.chat.completions.create(
            model=LLM_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2,
            response_format={"type": "json_object"},
        )
        content = resp.choices[0].message.content or "[]"
    except Exception as e:
        logger.warning(f"LLM gap analysis failed, skipping: {e}")
        return []
    try:
        sug = json.loads(content)
        if isinstance(sug, dict):
            for k in ("suggestions", "gaps", "recommendations", "results"):
                if k in sug: sug = sug[k]; break
        if isinstance(sug, str): sug = [sug]
        return [_fmt_gap(s) for s in (sug or []) if s]
    except json.JSONDecodeError:
        return []


# ═══════════════════════════════════════════════════════════════════
#  Agent 编排器 (Orchestrator)
# ═══════════════════════════════════════════════════════════════════
async def simplified_survey(
    task_id: str, topic: str, max_iters: int = 2,
    seed_ids: Optional[list[str]] = None,
    user_notes: str = "",
    extra_kw: Optional[list[str]] = None,
    llm_provider: str = "",
    llm_model: str = "",
) -> TaskProgress:
    """简化的文献调研流程（跳过复杂的迭代和引用扩展）"""
    global LLM_PROVIDER, LLM_MODEL
    if llm_provider:
        LLM_PROVIDER = llm_provider
    if llm_model:
        LLM_MODEL = llm_model
    p = tasks[task_id]
    
    try:
        p.status, p.phase = "running", "decompose"
        p.message = "正在解析主题..."
        p.progress_pct = 5
        logger.info(f"[{task_id}] Simplified survey for '{topic}'")
        
        dec = await tool_decompose_topic(topic, user_notes)
        p.decomposition = dec
        p.progress_pct = 20
        
        p.phase = "search"
        p.message = "正在搜索多个数据库..."
        kw_papers = await tool_hybrid_search(dec.keyword_groups, 15)
        all_papers = {pp.paperId: pp for pp in kw_papers if pp.paperId}
        p.progress_pct = 60
        
        p.phase = "validate"
        p.message = f"相关性验证中（{len(all_papers)} 篇候选）..."
        validated = await tool_validate_relevance(list(all_papers.values()), topic, threshold=4)
        p.validated_count = len(validated)
        p.progress_pct = 85
        
        p.phase = "gap"
        p.gap_suggestions = await tool_gap_analyzer(validated, topic, dec)
        
        # Final
        p.phase = "final"
        p.progress_pct = 100
        p.status = "completed"
        validated.sort(key=lambda x: (-x.score, -x.citationCount))
        p.results = validated
        p.message = f"调研完成！共找到 {len(validated)} 篇高质量文献。"
        logger.info(f"[{task_id}] Complete: {len(validated)} papers")
        
    except Exception as e:
        logger.exception(f"[{task_id}] Error: {e}")
        p.status = "error"
        p.error = str(e)
        p.message = f"任务出错：{e}"
    
    return p


async def run_literature_survey(
    task_id: str, topic: str, max_iters: int = 2,
    seed_ids: Optional[list[str]] = None,
    user_notes: str = "",
    extra_kw: Optional[list[str]] = None,
    llm_provider: str = "",
    llm_model: str = "",
) -> TaskProgress:
    """完整的文献调研四阶段 Agent 循环"""
    global LLM_PROVIDER, LLM_MODEL
    if llm_provider:
        LLM_PROVIDER = llm_provider
    if llm_model:
        LLM_MODEL = llm_model
    p = tasks[task_id]
    seed_ids = seed_ids or []
    extra_kw = extra_kw or []

    try:
        # 阶段 1: 主题解析
        p.status, p.phase = "running", "decompose"
        p.message = "正在解析主题，生成检索框架..."
        p.progress_pct = 5
        logger.info(f"[{task_id}] Phase 1: decompose '{topic}'")

        dec = await tool_decompose_topic(topic, user_notes)
        p.decomposition = dec
        if extra_kw:
            dec.keyword_groups.append(extra_kw)

        all_papers: dict[str, Paper] = {}

        for it in range(max_iters):
            p.iteration = it + 1
            p.message = f"第 {it+1} 轮搜索中..."

            # 阶段 2: 多策略检索
            p.phase = "search"
            p.progress_pct = 10 + it * 30
            kw_papers = await tool_hybrid_search(dec.keyword_groups, 15)
            for pp in kw_papers:
                if pp.paperId: all_papers[pp.paperId] = pp

            p.message = f"关键词搜索完成，已获取 {len(kw_papers)} 篇论文"

            # 引用扩展
            p.phase = "expand"
            p.message = "正在扩展引用网络..."
            if it == 0 and not seed_ids:
                top = sorted(kw_papers,
                    key=lambda x: x.citationCount if x.score == 0 else x.score * 100 + x.citationCount,
                    reverse=True)[:3]
                seed_ids = [x.paperId for x in top if x.paperId]
            if seed_ids:
                cited = await tool_expand_citations(seed_ids)
                for pp in cited:
                    if pp.paperId: all_papers[pp.paperId] = pp

            # 缺口补充搜索（第二轮起）
            if it > 0 and p.gap_suggestions:
                extra = []
                for s in p.gap_suggestions:
                    kw = s.replace("搜索关键词:", "").replace("搜索关键词：", "").split("—")[0].strip()
                    if kw: extra.append([kw])
                if extra:
                    for pp in await tool_hybrid_search(extra, 10):
                        if pp.paperId: all_papers[pp.paperId] = pp

            cands = list(all_papers.values())
            p.message = f"共收集 {len(cands)} 篇候选，正在进行相关性验证..."

            # 阶段 3: 相关性验证
            p.phase = "validate"
            validated = await tool_validate_relevance(cands, topic)
            p.validated_count = len(validated)
            p.message = f"验证完成，{len(validated)} 篇通过筛选"

            # 阶段 4: 缺口分析
            if it < max_iters - 1 and validated:
                p.phase = "gap"
                p.message = "正在进行文献覆盖缺口分析..."
                p.progress_pct = 70 + it * 10
                gaps = await tool_gap_analyzer(validated, topic, dec)
                p.gap_suggestions = gaps
                if not gaps:
                    break
                seed_ids = [p.paperId for p in sorted(validated, key=lambda x: -x.score)[:3] if p.paperId]
            elif it >= max_iters - 1:
                p.gap_suggestions = await tool_gap_analyzer(validated, topic, dec)

        # 最终整理
        p.phase = "final"
        p.progress_pct = 100
        p.status = "completed"
        final = list({px.paperId: px for px in (await tool_validate_relevance(list(all_papers.values()), topic))}.values())
        final.sort(key=lambda x: (-x.score, -x.citationCount))
        p.results = final
        p.message = f"调研完成！共找到 {len(final)} 篇高质量文献。（{max_iters} 轮迭代）"
        logger.info(f"[{task_id}] Complete: {len(final)} papers")

    except Exception as e:
        logger.exception(f"[{task_id}] Error: {e}")
        p.status, p.error = "error", str(e)
        p.message = f"任务出错：{e}"

    return p


# ═══════════════════════════════════════════════════════════════════
#  API 路由
# ═══════════════════════════════════════════════════════════════════
@app.post("/api/search")
@app.post("/api/search")
async def api_search(req: SearchRequest, x_llm_provider: str = Header(""), x_llm_model: str = Header(""), x_api_key: str = Header("")):
    global LLM_API_KEY
    if x_api_key:
        LLM_API_KEY = x_api_key
    task_id = uuid.uuid4().hex[:12]
    tasks[task_id] = TaskProgress(status="queued", message="任务已创建，等待处理...")
    asyncio.create_task(
        simplified_survey(
            task_id=task_id, topic=req.topic, max_iters=req.max_iterations,
            seed_ids=req.seed_paper_ids, user_notes=req.user_notes,
            llm_provider=x_llm_provider, llm_model=x_llm_model,
        )
    )
    return {"task_id": task_id, "status": "queued", "message": "任务已启动"}

@app.get("/api/status/{task_id}")
async def api_status(task_id: str):
    if task_id not in tasks:
        raise HTTPException(404, "任务不存在")
    return tasks[task_id]


@app.post("/api/refine")
async def api_refine(req: RefineRequest, x_llm_provider: str = Header(""), x_llm_model: str = Header(""), x_api_key: str = Header("")):
    if req.task_id not in tasks:
        raise HTTPException(404, "任务不存在")
    orig = tasks[req.task_id]
    if orig.status != "completed":
        raise HTTPException(400, "只能对已完成的任务进行补充搜索")

    tid = uuid.uuid4().hex[:12]
    global LLM_API_KEY
    if x_api_key:
        LLM_API_KEY = x_api_key
    tasks[tid] = TaskProgress(status="queued", message=f"补充搜索：{req.feedback}")
    core_q = orig.decomposition.core_question if orig.decomposition else req.feedback
    asyncio.create_task(run_literature_survey(tid, core_q, 1, user_notes=req.feedback, extra_kw=req.new_keywords, llm_provider=x_llm_provider, llm_model=x_llm_model))
    return {"task_id": tid, "status": "queued"}


@app.get("/api/export/{task_id}")
async def api_export(task_id: str, fmt: str = "json"):
    if task_id not in tasks:
        raise HTTPException(404, "任务不存在")
    p = tasks[task_id]

    if fmt == "bibtex":
        entries = []
        for pp in p.results:
            key = f"{pp.paper_type}_{pp.year}_{pp.paperId[:8]}" if pp.year else f"paper_{pp.paperId[:8]}"
            aa = " and ".join(pp.authors[:5])
            if len(pp.authors) > 5: aa += " and others"
            entries.append(
                f"""@article{{{key},
  title = {{{pp.title}}},
  author = {{{aa}}},
  year = {{{pp.year or "n.d."}}},
  venue = {{{pp.venue}}},
  url = {{{pp.url}}},
  score = {{{pp.score}}}
}}"""
            )
        return {"format": "bibtex", "content": "\n\n".join(entries)}

    return {
        "topic": p.decomposition.core_question if p.decomposition else "",
        "total_count": len(p.results),
        "papers": [
            {"title": pp.title, "authors": pp.authors, "year": pp.year,
             "citationCount": pp.citationCount, "score": pp.score,
             "reason": pp.reason, "type": pp.paper_type, "url": pp.url,
             "abstract": (pp.abstract or "")[:300], "venue": pp.venue}
            for pp in p.results
        ],
        "decomposition": p.decomposition.model_dump() if p.decomposition else None,
        "gap_suggestions": p.gap_suggestions,
    }


@app.get("/api/paper/{paper_id}")
async def api_paper_detail(paper_id: str):
    res = await _s2_detail(paper_id, [
        "paperId","title","authors","year","citationCount",
        "abstract","venue","externalIds","references","citations",
        "tldr","publicationTypes","journal","fieldsOfStudy",
    ])
    if not res:
        raise HTTPException(404, "论文未找到")
    return res

@app.get("/api/lanip")
async def api_lanip():
    """返回本机局域网 IP 地址"""
    import socket
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return {"ip": ip}
    except Exception:
        return {"ip": "unknown"}



# 静态文件挂载（必须在路由之后）
static_dir = os.path.join(os.path.dirname(__file__), "static")

@app.get("/api/test_search")
async def api_test_search(q: str = "test"):
    """完整管道调试"""
    try:
        # Step 1: decompose
        dec = await tool_decompose_topic(q, "")
        kg = dec.keyword_groups
        
        # Step 2: search
        papers = await tool_hybrid_search(kg, 15, topic=q)
        s2 = len(papers)
        
        # Step 3: validate
        validated = await tool_validate_relevance(papers, q, threshold=4)
        s3 = len(validated)
        
        return {
            "keyword_groups": len(kg),
            "search_results": s2,
            "after_validation": s3,
            "sources": {},
            "sample": [{"title": p.title[:50] if p.title else "(empty)", "source": p.source} for p in papers[:5]]
        }
    except Exception as e:
        import traceback
        return {"error": str(e), "traceback": traceback.format_exc()}


@app.get("/api/debug_sources")
async def api_debug_sources(q: str = "流体力学"):
    """测试各数据源返回数量"""
    import asyncio
    results = {}
    results["arxiv"] = len(await _arxiv_search(q, 5))
    results["crossref"] = len(await _crossref_search(q, 5))
    results["openalex"] = len(await _openalex_search(q, 5))
    results["topic"] = q
    return results

app.mount("/", StaticFiles(directory=static_dir, html=True), name="static")



async def _arxiv_search(query: str, top_k: int = 12) -> list[dict]:
    """通过 ArXiv API 检索（无速率限制，作为 S2 的备用）"""
    import xml.etree.ElementTree as ET
    # 清理查询词：去掉布尔运算符和引号，转成空格分隔
    terms = query.replace(" AND ", " ").replace('"', "").replace(" OR ", " ").strip().split()
    # ArXiv: all:word1 AND all:word2 AND ... 使用显式 AND
    arxiv_q = " AND ".join("all:" + t for t in terms)
    params = {"search_query": arxiv_q, "start": "0", "max_results": str(min(top_k, 50))}
    async with httpx.AsyncClient(follow_redirects=True) as client:
        try:
            resp = await client.get("https://export.arxiv.org/api/query", params=params, timeout=15.0)
            if resp.status_code != 200:
                return []
            root = ET.fromstring(resp.content)
            ns = {"a": "http://www.w3.org/2005/Atom", "arxiv": "http://arxiv.org/schemas/atom"}
            results = []
            for entry in root.findall("a:entry", ns):
                pid = ""
                title = ""
                authors = []
                year = None
                abstract = ""
                eid = entry.find("a:id", ns)
                if eid is not None:
                    pid = "arxiv_" + eid.text.split("/")[-1].split("v")[0]
                t = entry.find("a:title", ns)
                if t is not None:
                    title = t.text.replace("\n", " ").strip() if t.text else ""
                for au in entry.findall("a:author", ns):
                    n = au.find("a:name", ns)
                    if n is not None:
                        authors.append({"name": n.text})
                p = entry.find("a:published", ns)
                if p is not None and p.text:
                    year = int(p.text[:4])
                s = entry.find("a:summary", ns)
                if s is not None:
                    abstract = s.text.replace("\n", " ").strip()[:500] if s.text else ""
                results.append({
                    "paperId": pid, "title": title, "authors": authors,
                    "year": year, "citationCount": 0, "abstract": abstract,
                    "venue": "arXiv", "externalIds": {},
                })
            return results
        except Exception as e:
            logger.error(f"ArXiv fail: {e}")
            return []


async def _crossref_search(query: str, top_k: int = 8) -> list[dict]:
    """通过 CrossRef API 检索（免费、覆盖 2 亿+论文）"""
    params = {"query": query, "select": "DOI,title,author,container-title,issued,abstract,URL", "rows": min(top_k, 20)}
    async with httpx.AsyncClient(follow_redirects=True) as client:
        try:
            resp = await client.get("https://api.crossref.org/works", params=params, timeout=10.0)
            if resp.status_code != 200:
                return []
            data = resp.json()
            items = data.get("message", {}).get("items", [])
            results = []
            for item in items:
                doi = item.get("DOI", "")
                title = (item.get("title") or [""])[0] if isinstance(item.get("title"), (list, tuple)) else (item.get("title") or "")
                authors_list = []
                for au in (item.get("author") or []):
                    if "family" in au:
                        authors_list.append({"name": au["family"] + (" " + au.get("given", "") if au.get("given") else "")})
                pub_info = item.get("issued", {}).get("date-parts", [[]])
                year = pub_info[0][0] if pub_info and pub_info[0] else None
                abstract = (item.get("abstract") or "")[:500]
                venue = (item.get("container-title") or [""])[0]
                results.append({
                    "paperId": "doi_" + doi.replace("/", "_").replace(".", "_") if doi else "cr_" + str(hash(title))[:8],
                    "title": title,
                    "authors": authors_list,
                    "year": year,
                    "citationCount": 0,
                    "abstract": abstract.replace("\n", " ").replace("<jats:p>", "").replace("</jats:p>", "")[:500],
                    "venue": venue,
                    "paperId": "doi_" + doi.replace("/", "_").replace(".", "_") if doi else "cr_" + str((item.get("title") or [""])[0]).__hash__() % 1000000,
                    "externalIds": {"DOI": doi} if doi else {},
                })
            return results
        except Exception as e:
            logger.error(f"CrossRef fail: {e}")
            return []



async def _openalex_search(query: str, top_k: int = 8) -> list[dict]:
    """通过 OpenAlex API 检索（免费、覆盖 2.5 亿+学术作品）"""
    params = {"search": query, "per_page": min(top_k, 25), "sort": "relevance_score:desc"}
    async with httpx.AsyncClient(follow_redirects=True) as client:
        try:
            resp = await client.get("https://api.openalex.org/works", params=params, timeout=10.0)
            if resp.status_code != 200:
                return []
            data = resp.json()
            items = data.get("results", [])
            results = []
            for item in items:
                oid = item.get("id", "").split("/")[-1] if item.get("id") else ""
                authors_list = []
                for au in (item.get("authorships") or []):
                    if au.get("author", {}).get("display_name"):
                        authors_list.append({"name": au["author"]["display_name"]})
                results.append({
                    "paperId": "oa_" + oid if oid else "oa_" + str(hash(item.get("title", "")))[:8],
                    "title": item.get("title", ""),
                    "authors": authors_list,
                    "year": item.get("publication_year"),
                    "citationCount": item.get("cited_by_count", 0) or 0,
                    "abstract": (item.get("abstract_inverted_index") and " ".join(list(item["abstract_inverted_index"].keys())[:80]) or "")[:500],
                    "venue": item.get("primary_location") is not None and isinstance(item.get("primary_location"), dict) and isinstance(item["primary_location"].get("source"), dict) and item["primary_location"]["source"].get("display_name", "") or "",
                    "externalIds": {"OpenAlex": oid, "DOI": (item.get("doi") or "").replace("https://doi.org/", "")} if oid else {},
                })
            return results
        except Exception as e:
            logger.error(f"OpenAlex fail: {e}")
            return []






@app.get("/api/fast_search")
async def api_fast_search(q: str = "流体力学"):
    """同步调试搜索"""
    try:
        dec = await tool_decompose_topic(q, "")
        papers = await tool_hybrid_search(dec.keyword_groups, 15, topic=q)
        s2 = len(papers)
        all_p = {pp.paperId: pp for pp in papers if pp.paperId}
        validated = await tool_validate_relevance(list(all_p.values()), q, threshold=4)
        return {
            "keyword_groups": len(dec.keyword_groups),
            "search_results": s2,
            "after_dict": len(all_p),
            "after_validation": len(validated),
            "sample": [{"title": p.title[:50] if p.title else "(空)", "source": p.source} for p in validated[:5]]
        }
    except Exception as e:
        import traceback
        return {"error": str(e), "traceback": traceback.format_exc()}



@app.get("/api/results/{task_id}")
async def api_results(task_id: str):
    if task_id not in tasks:
        raise HTTPException(404, "任务不存在")
    p = tasks[task_id]
    if p.status != "completed":
        return {"status": p.status, "phase": p.phase, "message": p.message, "results": []}
    validated = p.results or []
    return {
        "status": "completed",
        "total_count": len(validated),
        "decomposition": p.decomposition.model_dump() if p.decomposition else None,
        "gap_suggestions": p.gap_suggestions,
        "papers": [{
            "title": pp.title, "authors": pp.authors, "year": pp.year,
            "citationCount": pp.citationCount, "score": pp.score,
            "reason": pp.reason, "type": pp.paper_type, "url": pp.url,
            "source": pp.source
        } for pp in validated]
    }


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8765))
    logger.info(f"Starting on http://0.0.0.0:{port}")
    uvicorn.run(app, host="0.0.0.0", port=port)































