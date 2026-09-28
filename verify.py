"""
文献调研智能体 — 端到端验收脚本
================================
覆盖：路由完整性、静态资源、前端 DOM 契约、真实检索、导出。

用法：
    python verify.py [base_url]        # 默认 http://127.0.0.1:8765
先启动服务： python app.py
"""
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request

# Windows 控制台默认是 GBK，直接 print("✅") 会抛 UnicodeEncodeError 并以非 0 退出，
# 让"全部通过"看起来像失败。这里强制 stdout/stderr 用 UTF-8。
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8765").rstrip("/")
ROOT = os.path.dirname(os.path.abspath(__file__))

passed, failed = [], []


def check(name, ok, detail=""):
    (passed if ok else failed).append(name)
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f"  — {detail}" if detail else ""))


def http(path, method="GET", body=None, timeout=120):
    req = urllib.request.Request(BASE + path, method=method)
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, data, timeout=timeout) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")


print(f"\n=== 1. 服务可达性  ({BASE}) ===")
try:
    status, text = http("/api/health", timeout=10)
    health = json.loads(text)
    check("GET /api/health 返回 200", status == 200, text[:80])
    check("health 含 status=ok", health.get("status") == "ok")
except Exception as e:
    print(f"  [FAIL] 服务无法访问：{e}")
    print("\n请先运行:  python app.py")
    sys.exit(1)

print("\n=== 2. 静态资源与前端文件 ===")
for path, needle in [
    ("/", "<!DOCTYPE html>"),
    ("/index.html", "文献调研智能体"),
    ("/style.css", "--primary"),
    ("/script.js", "startSearch"),
]:
    status, text = http(path, timeout=15)
    check(f"GET {path} 200 且内容正确", status == 200 and needle in text,
          f"status={status} len={len(text)}")

print("\n=== 3. 所有 API 路由可达（不被静态挂载吞掉）===")
status, text = http("/api/config", timeout=15)
check("GET /api/config", status == 200, text[:80])
status, text = http("/api/status/does-not-exist", timeout=15)
check("GET /api/status/<不存在> 返回 404 而不是被挂载吞掉", status == 404, f"status={status}")
status, text = http("/api/results/does-not-exist", timeout=15)
check("GET /api/results/<不存在> 可路由（原 404 挂载 bug）", status == 404, f"status={status}")
status, text = http("/api/debug_sources?q=electron", timeout=90)
check("GET /api/debug_sources 可路由（原被挂载吞掉）", status == 200, text[:120])

print("\n=== 4. 前端 DOM 契约：script.js 引用的 id 都存在于 index.html ===")
js = open(os.path.join(ROOT, "static", "script.js"), encoding="utf-8").read()
html = open(os.path.join(ROOT, "static", "index.html"), encoding="utf-8").read()
used_ids = set(re.findall(r'\$\("([A-Za-z0-9_-]+)"\)', js)) | set(re.findall(r'getElementById\("([A-Za-z0-9_-]+)"\)', js))
missing = sorted(i for i in used_ids if f'id="{i}"' not in html)
check(f"script.js 引用的 {len(used_ids)} 个 id 全部存在", not missing, "缺失: " + ", ".join(missing) if missing else "")
srv_status, srv_html = http("/", timeout=15)
served_missing = sorted(i for i in used_ids if f'id="{i}"' not in srv_html)
check("服务端实际返回的 HTML 与脚本一致", not served_missing, "缺失: " + ", ".join(served_missing) if served_missing else "")

css = open(os.path.join(ROOT, "static", "style.css"), encoding="utf-8").read()
# .paper-item / .filter-btn 等由脚本动态生成，只要求样式表里有定义
for cls in ["paper-item", "filter-btn", "phase", "progress-bar", "score-badge", "gap-list", "decomp-item"]:
    check(f"CSS 定义了 .{cls}", f".{cls}" in css)

print("\n=== 5. 真实检索流程（无 LLM 也应完成）===")
topic = "基于图神经网络的药物靶点预测"
status, text = http("/api/search", "POST", {"topic": topic, "max_iterations": 1}, timeout=60)
check("POST /api/search 返回 200", status == 200, text[:120])
task_id = json.loads(text).get("task_id") if status == 200 else None
check("返回 task_id", bool(task_id))

final = {}
if task_id:
    t0 = time.time()
    while time.time() - t0 < 300:
        time.sleep(2)
        status, text = http(f"/api/status/{task_id}", timeout=30)
        if status != 200:
            check("轮询 /api/status", False, f"status={status}")
            break
        final = json.loads(text)
        print(f"      {final['status']:9} {final['phase']:10} {final['progress_pct']:3}%  {final['message'][:64]}")
        if final["status"] in ("completed", "error"):
            break

    check("任务最终状态为 completed", final.get("status") == "completed", final.get("error", ""))
    check("返回论文数量 > 0", len(final.get("results") or []) > 0, f"{len(final.get('results') or [])} 篇")
    check("主题解析已回填", bool(final.get("decomposition", {}).get("core_question")))
    check("关键词分组 >= 3 组", len(final.get("decomposition", {}).get("keyword_groups") or []) >= 3)
    check("每篇结果都有标题与评分", all(p.get("title") and p.get("score") for p in (final.get("results") or [])))
    check("每篇结果都有可解释的入选理由", all(p.get("reason") for p in (final.get("results") or [])))
    used = final.get("sources_used") or []
    check("至少一个真实数据源返回了数据", bool(set(used) - {"offline_fallback"}), "sources=" + ",".join(used))
    check("结果按评分/引用排序", (final.get("results") or [{}])[0].get("score", 0) >= (final.get("results") or [{}])[-1].get("score", 0))
    print(f"      实际来源: {','.join(used)}")

print("\n=== 6. 导出功能 ===")
if task_id:
    for fmt, needle in [("json", "papers"), ("bibtex", "@article"), ("markdown", "# 文献调研报告"), ("csv", "title,authors")]:
        status, text = http(f"/api/export/{task_id}?fmt={fmt}", timeout=30)
        ok = status == 200 and needle in text
        check(f"导出 {fmt} 格式", ok, f"status={status}")

print("\n=== 7. 英文主题（数据源自检）===")
status, text = http("/api/debug_sources?q=graph%20neural%20network%20drug%20target", timeout=180)
if status == 200:
    srcs = json.loads(text)
    check("数据源 CrossRef 可用", srcs.get("crossref", {}).get("count", 0) > 0,
          f"count={srcs.get('crossref', {}).get('count')}")
    check("自检接口会如实上报数据源状态", all("status" in srcs.get(k, {}) for k in ("arxiv", "crossref", "openalex", "s2")))

    # ArXiv / OpenAlex / S2 都有上游限流（匿名共享额度），被限流时程序应正确降级并给出提示，
    # 这属于外部因素，不应判定为程序缺陷。
    for name in ("arxiv", "openalex", "s2"):
        info = srcs.get(name, {})
        if info.get("count", 0) > 0:
            check(f"数据源 {name} 可用", True, f"count={info.get('count')} {info.get('seconds')}s")
        else:
            print(f"  [WARN] 数据源 {name} 本次不可用：{info.get('note') or '上游限流/未配置密钥'}"
                  f"（已正确降级，不影响整体流程）")
else:
    check("GET /api/debug_sources", False, f"status={status}")

print("\n=== 8. 错误处理 ===")
status, text = http("/api/search", "POST", {"topic": "   "}, timeout=30)
check("空主题被拒绝 (422/400)", status in (400, 422), f"status={status}")
status, text = http("/api/nonexistent-endpoint", timeout=15)
check("未知 API 路径返回 404", status == 404, f"status={status}")

print("\n=== 9. 公开部署保护（限流 / 密钥策略）===")
status, text = http("/api/health", timeout=10)
h = json.loads(text) if status == 200 else {}
check("health 不上报模型细节（减少指纹）", not h.get("llm_model") or h.get("llm_enabled"),
      f"llm_model={h.get('llm_model')!r}")
check("health 声明服务器 Key 策略", h.get("server_key_policy") in ("self_key_only", "allow_anonymous"),
      str(h.get("server_key_policy")))
status, text = http("/api/config", timeout=10)
cfg = json.loads(text) if status == 200 else {}
check("默认不允许匿名使用服务器 Key", cfg.get("server_key_for_anonymous") is False,
      f"server_key_for_anonymous={cfg.get('server_key_for_anonymous')}")

# 连打同一个接口，超过每分钟上限后必须出现 429，否则公网部署会被刷爆
codes = []
for _ in range(16):
    st, _t = http("/api/search", "POST", {"topic": "rate limit probe"}, timeout=30)
    codes.append(st)
got_429 = 429 in codes
check("连续请求会触发 429 限流", got_429,
      f"状态码序列={codes}")
if got_429:
    print(f"      第 {codes.index(429) + 1} 次请求被限流（上限 {cfg.get('rate_limit_per_minute')} 次/分钟）")
    status, text = http("/api/search", "POST", {"topic": "rate limit probe"}, timeout=30)
    check("限流提示为中文可读文案", "频繁" in text or "已满" in text, text[:80])

total = len(passed) + len(failed)
print("\n" + "=" * 60)
print(f"结果：{len(passed)}/{total} 通过")
if failed:
    print("失败项：")
    for f in failed:
        print("  - " + f)
    sys.exit(1)
print("全部通过 ✅")
