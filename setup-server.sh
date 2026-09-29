#!/usr/bin/env bash
# ===================================================================
#  Literature Survey Agent - one-shot server deployment (Ubuntu/Debian)
#
#  What it does on a fresh server:
#    1. install system packages (python3, venv, pip, git, curl)
#    2. fetch the project code
#    3. create a virtualenv and install Python dependencies
#    4. register a systemd service (auto-start on boot, auto-restart)
#    5. start it and verify with a health check
#
#  Usage (paste into the server SSH console):
#      bash setup-server.sh
#
#  Overridable via environment variables:
#      REPO_URL    git repository          (default: GitHub)
#      APP_DIR     install directory       (default: /opt/literature-agent)
#      APP_PORT    listening port          (default: 8765)
#
#  NOTE: this file is intentionally ASCII-only. Non-ASCII text written
#  into shell scripts tends to come out as mojibake, because the editing
#  environment and the console rarely agree on the encoding.
# ===================================================================

set -euo pipefail

REPO_URL="${REPO_URL:-https://github.com/SilentTensor/literature-agent.git}"
APP_DIR="${APP_DIR:-/opt/literature-agent}"
APP_PORT="${APP_PORT:-8765}"
SERVICE="literature-agent"

info() { printf '\n\033[1;36m==> %s\033[0m\n' "$*"; }
ok()   { printf '    \033[1;32m[ok]\033[0m %s\n' "$*"; }
warn() { printf '    \033[1;33m[!]\033[0m %s\n' "$*"; }
die()  { printf '\n\033[1;31m[FAIL] %s\033[0m\n' "$*" >&2; exit 1; }

[ "$(id -u)" -eq 0 ] || die "Run this as root."

# ---------------------------------------------------------------- 1
info "1/6  Installing system packages"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq python3 python3-venv python3-pip git curl ca-certificates >/dev/null
ok "python3 $(python3 --version 2>&1 | awk '{print $2}')"
ok "git $(git --version | awk '{print $3}')"

# ---------------------------------------------------------------- 2
info "2/6  Fetching code into $APP_DIR"
if [ -d "$APP_DIR/.git" ]; then
    cd "$APP_DIR"
    git fetch --all -q
    git reset --hard origin/main -q
    ok "repository updated"
else
    rm -rf "$APP_DIR"
    # GitHub can be slow or unreachable from mainland servers; fall back
    # to a public mirror before giving up.
    if git clone --depth 1 "$REPO_URL" "$APP_DIR" 2>/dev/null; then
        ok "cloned from GitHub"
    else
        warn "direct clone failed, retrying via mirror"
        MIRROR="${REPO_URL/github.com/ghproxy.net\/https:\/\/github.com}"
        git clone --depth 1 "$MIRROR" "$APP_DIR" || die "code download failed - check server network"
        ok "cloned from mirror"
    fi
    cd "$APP_DIR"
fi
[ -f app.py ] || die "app.py not found in $APP_DIR - code is incomplete"
ok "code ready ($(ls -1 | wc -l) entries)"

# ---------------------------------------------------------------- 3
info "3/6  Creating virtualenv"
if [ ! -x .venv/bin/python ]; then
    python3 -m venv .venv
    ok "virtualenv created"
else
    ok "virtualenv already present"
fi
.venv/bin/python -m pip install --quiet --upgrade pip setuptools wheel
ok "pip $(.venv/bin/python -m pip --version | awk '{print $2}')"

# ---------------------------------------------------------------- 4
info "4/6  Installing Python dependencies (1-2 minutes)"
if .venv/bin/python -m pip install --quiet -r requirements.txt \
      -i https://mirrors.aliyun.com/pypi/simple/ 2>/dev/null; then
    ok "installed via Aliyun mirror"
else
    warn "mirror failed, retrying with default index"
    .venv/bin/python -m pip install --quiet -r requirements.txt \
        || die "dependency install failed - check server network"
    ok "installed via default index"
fi
.venv/bin/python -c "import fastapi, uvicorn, httpx" || die "key dependencies failed to import"
ok "import self-check passed"

# ---------------------------------------------------------------- 5
info "5/6  Registering systemd service"
mkdir -p "$APP_DIR/logs"
cat > /etc/systemd/system/${SERVICE}.service <<EOF
[Unit]
Description=Literature Survey Agent
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=${APP_DIR}
Environment=PORT=${APP_PORT}
Environment=HOST=0.0.0.0
Environment=PYTHONUNBUFFERED=1
Environment=LOG_FILE=${APP_DIR}/logs/agent.log
ExecStart=${APP_DIR}/.venv/bin/python ${APP_DIR}/app.py
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable "$SERVICE" >/dev/null 2>&1
systemctl restart "$SERVICE"
ok "service enabled and started"

# ---------------------------------------------------------------- 6
info "6/6  Verifying"
sleep 6
systemctl is-active --quiet "$SERVICE" || {
    warn "service is not running, last log lines:"
    journalctl -u "$SERVICE" -n 30 --no-pager || true
    die "startup failed"
}
ok "process is running"

if curl -fsS --max-time 8 "http://127.0.0.1:${APP_PORT}/api/health" >/dev/null 2>&1; then
    ok "health check passed"
else
    warn "health check did not pass yet; try again in a moment:"
    echo "      curl http://127.0.0.1:${APP_PORT}/api/health"
fi

PUB_IP="$(curl -fsS --max-time 8 https://api.ipify.org 2>/dev/null || echo 'YOUR_PUBLIC_IP')"

cat <<EOF

================================================================
 DEPLOYMENT FINISHED
================================================================

  local   : http://127.0.0.1:${APP_PORT}/
  public  : http://${PUB_IP}:${APP_PORT}/

  commands
    status  : systemctl status ${SERVICE}
    logs    : journalctl -u ${SERVICE} -f
    restart : systemctl restart ${SERVICE}
    stop    : systemctl stop ${SERVICE}
    update  : cd ${APP_DIR} && git pull && systemctl restart ${SERVICE}

  STILL REQUIRED: open port ${APP_PORT} in the Alibaba Cloud console
    Console -> Firewall / Security Group -> Add rule
      protocol TCP, port ${APP_PORT}, source 0.0.0.0/0
    Without this, nobody outside can reach it.

================================================================
EOF
