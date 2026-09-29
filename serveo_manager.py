"""
公网隧道管理器（serveo.net，SSH，无需注册）
==========================================

为什么用它：
  - localtunnel 会弹"输入 IP"的反滥用页面，手机打不开
  - Cloudflare 快速隧道会限流（429），而且地址每次重启都变
  - serveo 没有提示页，实测首页直接进程序，接口也正常

地址形如：
  https://<随机哈希>-109-122-3-150.serveousercontent.com
                         ^^^^^^^^^^^^^^^ 这部分是你的公网 IP，是固定的

也就是说地址的可变部分只有前面那一小段。每次重连后，
当前地址都会写进 public-url.txt，双击"打开我的公网网址.bat"即可看到。

用法:
    python serveo_manager.py [端口] [项目目录]
"""
import os
import re
import subprocess
import sys
import time
import urllib.request

PORT = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("PORT", "8765")
ROOT = sys.argv[2] if len(sys.argv) > 2 else os.path.dirname(os.path.abspath(__file__))

URL_FILE = os.path.join(ROOT, "public-url.txt")
LOG_FILE = os.path.join(ROOT, "logs", "tunnel.log")
RAW_LOG = os.path.join(ROOT, "logs", "serveo.log")

URL_RE = re.compile(r"(https://[a-z0-9][a-z0-9\-]*\.serveousercontent\.com)")

SSH_OPTS = [
    "-o", "StrictHostKeyChecking=no",
    "-o", "UserKnownHostsFile=NUL",
    "-o", "ServerAliveInterval=30",
    "-o", "ServerAliveCountMax=3",
    "-o", "ExitOnForwardFailure=yes",
    "-o", "ConnectTimeout=20",
    "-T",
]


def log(msg: str) -> None:
    line = time.strftime("%Y-%m-%d %H:%M:%S") + "  " + msg
    print(line, flush=True)
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass


def local_service_up() -> bool:
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
    except OSError as e:
        log(f"failed to write url file: {e}")


def find_ssh() -> str | None:
    from shutil import which
    for name in ("ssh.exe", "ssh"):
        p = which(name)
        if p:
            return p
    sysroot = os.environ.get("SystemRoot", r"C:\Windows")
    cand = os.path.join(sysroot, "System32", "OpenSSH", "ssh.exe")
    return cand if os.path.isfile(cand) else None


def main() -> int:
    os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)

    ssh = find_ssh()
    if not ssh:
        log("ERROR: ssh.exe not found. Windows 10+ ships it in System32\\OpenSSH.")
        return 1

    log("=" * 18 + f" serveo tunnel manager starting for port {PORT} " + "=" * 18)

    if not local_service_up():
        log("local service not responding - asking watchdog.ps1 to start it")
        wd = os.path.join(ROOT, "watchdog.ps1")
        if os.path.isfile(wd):
            try:
                subprocess.run(
                    ["powershell.exe", "-NoProfile", "-NonInteractive",
                     "-ExecutionPolicy", "Bypass", "-File", wd],
                    capture_output=True, timeout=180,
                )
            except Exception as e:
                log(f"watchdog call failed: {e}")
        for _ in range(10):
            if local_service_up():
                break
            time.sleep(3)

    attempt = 0
    failures = 0
    while True:
        attempt += 1
        log(f"starting serveo tunnel (attempt {attempt})")

        try:
            raw = open(RAW_LOG, "w", encoding="utf-8", errors="replace")
        except OSError:
            raw = None

        cmd = [ssh] + SSH_OPTS + ["-R", f"80:127.0.0.1:{PORT}", "serveo.net"]
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
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
            for line in proc.stdout:
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
                    if not got_url:
                        got_url = True
                        failures = 0
        except Exception as e:
            log(f"reading ssh output failed: {e}")
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

        # serveo 是 SSH 隧道，断了重连即可；但要退避，避免被判定为滥用
        if got_url:
            wait = 5
        else:
            failures += 1
            wait = min(15 * (2 ** min(failures - 1, 5)), 600)
            log(f"tunnel ended without a URL (failure #{failures})")

        log(f"next attempt in {wait} seconds ...")
        time.sleep(wait)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(0)
