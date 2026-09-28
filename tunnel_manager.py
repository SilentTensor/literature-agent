"""
公网隧道管理器（Cloudflare 快速隧道）
=====================================
用 Cloudflare 的免账号隧道把本机服务发布到公网。

为什么不用 localtunnel：它会给访客弹一个"输入 IP 才能继续"的反滥用页面，
手机根本没法正常打开。Cloudflare 的快速隧道没有这个页面。

为什么用 Python 写：PowerShell 捕获子进程输出的事件回调在 Windows 上不可靠，
实测两次都拿不到 URL。Python 的 subprocess + 逐行读取稳定得多。

用法:
    python tunnel_manager.py [端口] [项目目录]

它会：
  1. 确认本机服务在跑（不在就跑 watchdog.ps1）
  2. 启动 cloudflared，实时读取输出
  3. 解析出 https://xxx.trycloudflare.com 写入 public-url.txt
  4. 进程退出后自动重连（每 8 秒）
"""
import os
import re
import subprocess
import sys
import time

PORT = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("PORT", "8765")
ROOT = sys.argv[2] if len(sys.argv) > 2 else os.path.dirname(os.path.abspath(__file__))

URL_FILE = os.path.join(ROOT, "public-url.txt")
LOG_FILE = os.path.join(ROOT, "logs", "tunnel.log")
RAW_LOG = os.path.join(ROOT, "logs", "cloudflared.log")

URL_RE = re.compile(r"(https://[a-z0-9][a-z0-9\-]*\.trycloudflare\.com)")


def log(msg: str) -> None:
    line = time.strftime("%Y-%m-%d %H:%M:%S") + "  " + msg
    print(line, flush=True)
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass


def find_cloudflared() -> str | None:
    for cand in (
        os.path.join(os.environ.get("ProgramFiles", ""), "cloudflared", "cloudflared.exe"),
        os.path.join(os.environ.get("ProgramFiles(x86)", ""), "cloudflared", "cloudflared.exe"),
        os.path.join(os.environ.get("LOCALAPPDATA", ""), "cloudflared", "cloudflared.exe"),
    ):
        if cand and os.path.isfile(cand):
            return cand
    from shutil import which
    return which("cloudflared")


def local_service_up() -> bool:
    import urllib.request
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{PORT}/api/health", timeout=6) as r:
            return r.status == 200
    except Exception:
        return False


def publish(url: str) -> None:
    try:
        current = ""
        if os.path.isfile(URL_FILE):
            with open(URL_FILE, encoding="utf-8") as f:
                current = f.read().strip()
        if current != url:
            with open(URL_FILE, "w", encoding="utf-8") as f:
                f.write(url + "\n")
            log(f"public url: {url}")
            log("share this address - it works from any network, no interstitial page")
    except OSError as e:
        log(f"failed to write url file: {e}")


def main() -> int:
    os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)

    cf = find_cloudflared()
    if not cf:
        log("ERROR: cloudflared not found. Install with:  winget install Cloudflare.cloudflared")
        return 1

    log("=" * 20 + f" tunnel manager starting for port {PORT} " + "=" * 20)

    if not local_service_up():
        log("local service not responding - asking watchdog.ps1 to start it")
        wd = os.path.join(ROOT, "watchdog.ps1")
        if os.path.isfile(wd):
            subprocess.run(
                ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", wd],
                capture_output=True, timeout=180,
            )
        for _ in range(10):
            if local_service_up():
                break
            time.sleep(3)

    attempt = 0
    while True:
        attempt += 1
        log(f"starting cloudflared quick tunnel (attempt {attempt})")

        try:
            raw = open(RAW_LOG, "w", encoding="utf-8", errors="replace")
        except OSError:
            raw = None

        proc = subprocess.Popen(
            [cf, "tunnel", "--url", f"http://127.0.0.1:{PORT}", "--no-autoupdate"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,          # cloudflared 把日志都写 stdout/stderr
            stdin=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            cwd=ROOT,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )

        got_url = False
        try:
            for line in proc.stdout:          # 逐行读，实时
                line = line.rstrip()
                if raw:
                    try:
                        raw.write(line + "\n")
                        raw.flush()
                    except OSError:
                        pass
                m = URL_RE.search(line)
                if m:
                    publish(m.group(1))
                    got_url = True
                elif "ERR" in line or "error" in line.lower():
                    log("cloudflared: " + line[:160])
        except Exception as e:
            log(f"reading cloudflared output failed: {e}")
        finally:
            if raw:
                try:
                    raw.close()
                except OSError:
                    pass
            try:
                proc.terminate()
                proc.wait(timeout=10)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass

        if not got_url:
            log("cloudflared exited without producing a URL")
        log("reconnecting in 8 seconds ...")
        time.sleep(8)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(0)
