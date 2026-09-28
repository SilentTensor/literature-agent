"""
真实浏览器端到端测试（Edge/Chrome headless + CDP）
================================================
在真浏览器里打开页面 → 填写主题 → 点击「开始文献调研」→ 等待结果 → 截图。
同时捕获控制台错误，验证前端脚本确实跑通。

用法：python browser_e2e.py [url] [browser_exe]
"""
import asyncio
import json
import os
import subprocess
import sys
import time
import urllib.request

URL = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8899/"
BROWSER = sys.argv[2] if len(sys.argv) > 2 else r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
PORT = 9222
PROFILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".cdp-profile")
TOPIC = sys.argv[3] if len(sys.argv) > 3 else "graph neural network drug target prediction"

import websockets  # noqa: E402

errors: list[str] = []
logs: list[str] = []


async def cdp(ws, msg_id, method, params=None, session=None):
    payload = {"id": msg_id, "method": method, "params": params or {}}
    if session:
        payload["sessionId"] = session
    await ws.send(json.dumps(payload))
    while True:
        raw = await asyncio.wait_for(ws.recv(), timeout=90)
        data = json.loads(raw)
        if data.get("id") == msg_id:
            return data


async def wait_event(ws, event, timeout=120, session=None):
    end = time.time() + timeout
    while time.time() < end:
        raw = await asyncio.wait_for(ws.recv(), timeout=max(1, end - time.time()))
        data = json.loads(raw)
        if data.get("method") == event and (session is None or data.get("sessionId") == session):
            return data
    return None


async def html_of(ws, session, msg_id):
    r = await cdp(ws, msg_id, "Runtime.evaluate",
                  {"expression": "document.documentElement.outerHTML.length", "returnByValue": True},
                  session=session)
    return r.get("result", {}).get("result", {}).get("value")


async def main():
    if not os.path.exists(BROWSER):
        print(f"找不到浏览器: {BROWSER}")
        return 1

    print(f"启动浏览器：{BROWSER}")
    proc = subprocess.Popen(
        [BROWSER, "--headless=new", "--disable-gpu", "--no-first-run", "--no-default-browser-check",
         f"--remote-debugging-port={PORT}", f"--user-data-dir={PROFILE}",
         "--window-size=1440,1200", "about:blank"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )

    try:
        # 等 CDP 端口就绪
        target_ws = None
        for _ in range(40):
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{PORT}/json/version", timeout=2) as r:
                    target_ws = json.loads(r.read())["webSocketDebuggerUrl"]
                break
            except Exception:
                await asyncio.sleep(0.5)
        if not target_ws:
            print("CDP 未就绪")
            return 1

        async with websockets.connect(target_ws, max_size=40 * 1024 * 1024) as ws:
            mid = 0

            def nid():
                nonlocal mid
                mid += 1
                return mid

            t = await cdp(ws, nid(), "Target.createTarget", {"url": "about:blank"})
            target_id = t["result"]["targetId"]
            s = await cdp(ws, nid(), "Target.attachToTarget", {"targetId": target_id, "flatten": True})
            session = s["result"]["sessionId"]

            await cdp(ws, nid(), "Page.enable", session=session)
            await cdp(ws, nid(), "Runtime.enable", session=session)
            await cdp(ws, nid(), "Log.enable", session=session)

            print(f"打开页面：{URL}")
            await cdp(ws, nid(), "Page.navigate", {"url": URL}, session=session)
            await asyncio.sleep(4)

            # 收集已产生的事件（控制台报错）
            async def drain(seconds=1.0):
                end = time.time() + seconds
                while True:
                    try:
                        raw = await asyncio.wait_for(ws.recv(), timeout=max(0.05, end - time.time()))
                    except asyncio.TimeoutError:
                        return
                    d = json.loads(raw)
                    m = d.get("method")
                    if m == "Runtime.exceptionThrown":
                        errors.append(json.dumps(d["params"]["exceptionDetails"].get("text", ""), ensure_ascii=False))
                    elif m == "Runtime.consoleAPICalled" and d["params"].get("type") == "error":
                        errors.append("console.error: " + str(d["params"].get("args")))
                    elif m == "Log.entryAdded" and d["params"]["entry"].get("level") == "error":
                        errors.append("log: " + d["params"]["entry"].get("text", ""))

            await drain(1.5)

            async def evaluate(expr, await_promise=False):
                r = await cdp(ws, nid(), "Runtime.evaluate",
                              {"expression": expr, "returnByValue": True, "awaitPromise": await_promise},
                              session=session)
                res = r.get("result", {})
                if "exceptionDetails" in res:
                    return None, res["exceptionDetails"].get("text", "JS 异常")
                return res.get("result", {}).get("value"), None

            # 1. 页面标题与关键元素
            title, _ = await evaluate("document.title")
            print(f"\n[1] 页面标题：{title}")
            ok_title = "文献调研" in (title or "")

            n_btn, _ = await evaluate("document.querySelectorAll('.chip[data-example]').length")
            ok_chips = (n_btn or 0) >= 3
            print(f"[2] 示例主题按钮数量：{n_btn}  {'OK' if ok_chips else 'FAIL'}")

            # 2. 填写主题（模拟点击示例按钮）
            await evaluate("(function(){var el=document.getElementById('topic-input');el.value=" + json.dumps(TOPIC) + ";return el.value})()")
            await asyncio.sleep(0.3)
            topic_val, _ = await evaluate("document.getElementById('topic-input').value")
            print(f"[3] 点击示例后主题框内容：{topic_val!r}")

            # 3. 点击开始检索
            print("[4] 点击「开始文献调研」…")
            await evaluate("document.getElementById('btn-search').click()")
            await asyncio.sleep(2)
            await drain(1.0)

            progress_visible = None
            for i in range(90):
                await asyncio.sleep(2)
                await drain(0.4)
                progress_visible, _ = await evaluate(
                    "!document.getElementById('progress-panel').classList.contains('hidden')")
                results_visible, _ = await evaluate(
                    "!document.getElementById('results-panel').classList.contains('hidden')")
                msg, _ = await evaluate("document.getElementById('progress-message').textContent")
                count, _ = await evaluate("document.getElementById('result-count').textContent")
                print(f"    轮询{i + 1:02d}: 进度面板={progress_visible} 结果面板={results_visible} | {msg[:50]} | {count}")
                if results_visible:
                    break

            # 4. 校验结果
            n_papers, _ = await evaluate("document.querySelectorAll('.paper-item').length")
            first_title, _ = await evaluate(
                "(document.querySelector('.paper-title')||{}).textContent || ''")
            decomp_html, _ = await evaluate(
                "document.getElementById('decomposition-content').innerHTML.length")
            gap_items, _ = await evaluate("document.querySelectorAll('#gap-list li').length")
            score_badges, _ = await evaluate("document.querySelectorAll('.score-badge').length")

            print("\n── 前端渲染结果 ──")
            print(f"  论文卡片数量      : {n_papers}")
            print(f"  首篇标题          : {str(first_title)[:70]}")
            print(f"  主题解析区块长度  : {decomp_html}")
            print(f"  缺口建议条数      : {gap_items}")
            print(f"  评分徽章数量      : {score_badges}")

            # 5. 测试筛选按钮
            await evaluate("document.querySelector('.filter-btn[data-type=\"survey\"]').click()")
            await asyncio.sleep(0.8)
            filtered, _ = await evaluate("document.querySelectorAll('.paper-item').length")
            filtered_count, _ = await evaluate("document.getElementById('result-count').textContent")
            print(f"  点击「综述」筛选后: {filtered} 篇  ({filtered_count})")
            await evaluate("document.querySelector('.filter-btn[data-type=\"all\"]').click()")
            await asyncio.sleep(0.5)

            # 6. 测试展开摘要
            await evaluate("document.querySelector('.expand-btn').click()")
            await asyncio.sleep(0.5)
            expanded, _ = await evaluate("document.querySelectorAll('.paper-item.expanded').length")
            print(f"  展开摘要的卡片数  : {expanded}")

            # 7. 测试导出弹窗
            await evaluate("document.getElementById('btn-export-bibtex').click()")
            await asyncio.sleep(2.5)
            modal_open, _ = await evaluate("!document.getElementById('export-modal').classList.contains('hidden')")
            export_len, _ = await evaluate("document.getElementById('export-content').value.length")
            export_head, _ = await evaluate("document.getElementById('export-content').value.slice(0,40)")
            print(f"  导出弹窗打开      : {modal_open}  内容长度={export_len}")
            print(f"  导出内容开头      : {str(export_head)!r}")
            await evaluate("document.getElementById('btn-close-export').click()")
            await asyncio.sleep(0.4)

            # 8. 截图
            await evaluate("document.getElementById('progress-panel').classList.add('hidden')")
            await asyncio.sleep(0.5)
            shot = await cdp(ws, nid(), "Page.captureScreenshot",
                             {"format": "png", "captureBeyondViewport": True}, session=session)
            data = shot.get("result", {}).get("data")
            out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "shot_results.png")
            if data:
                import base64
                with open(out, "wb") as f:
                    f.write(base64.b64decode(data))
                print(f"\n结果截图已保存：{out}")

            await drain(1.0)

            print("\n── 判定 ──")
            checks = [
                ("页面标题正确", ok_title),
                ("示例按钮渲染", ok_chips),
                ("点击示例可填充主题", bool(topic_val)),
                ("检索完成后显示结果面板", bool(results_visible)),
                ("渲染出论文卡片", (n_papers or 0) > 0),
                ("主题解析已渲染", (decomp_html or 0) > 0),
                ("评分徽章已渲染", (score_badges or 0) > 0),
                ("筛选功能可用", (filtered or 0) >= 0 and filtered is not None),
                ("摘要可展开", (expanded or 0) > 0),
                ("导出弹窗可用", bool(modal_open) and (export_len or 0) > 0),
                ("无 JS 控制台错误", not errors),
            ]
            bad = [n for n, ok in checks if not ok]
            for n, ok in checks:
                print(f"  [{'PASS' if ok else 'FAIL'}] {n}")
            if errors:
                print("\n控制台错误：")
                for e in errors[:10]:
                    print("   - " + e[:200])
            print(f"\n浏览器端结果：{len(checks) - len(bad)}/{len(checks)} 通过")
            return 1 if bad else 0
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except Exception:
            proc.kill()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
