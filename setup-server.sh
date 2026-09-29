#!/usr/bin/env bash
# ===================================================================
#  鏂囩尞璋冪爺鏅鸿兘浣?鈥?鏈嶅姟鍣ㄤ竴閿儴缃茶剼鏈?(Ubuntu / Debian)
#
#  鍦ㄤ竴涓┖鐧芥湇鍔″櫒涓婂畬鎴愶細
#    1. 瀹夎 Python 鐜渚濊禆
#    2. 鎷夊彇椤圭洰浠ｇ爜
#    3. 寤鸿櫄鎷熺幆澧?+ 瑁?Python 渚濊禆
#    4. 娉ㄥ唽 systemd 鏈嶅姟锛堝紑鏈鸿嚜鍚?+ 宕╂簝鑷剤锛?#    5. 鍚姩骞堕獙璇?#
#  鐢ㄦ硶锛堝湪鏈嶅姟鍣?SSH 绐楀彛閲屾墽琛岋級锛?#    bash setup-server.sh
#
#  鍙敤鐜鍙橀噺瑕嗙洊锛?#    REPO_URL    浠ｇ爜浠撳簱鍦板潃
#    APP_DIR     瀹夎鐩綍锛堥粯璁?/opt/literature-agent锛?#    APP_PORT    鐩戝惉绔彛锛堥粯璁?8765锛?# ===================================================================

set -euo pipefail

REPO_URL="${REPO_URL:-https://github.com/SilentTensor/literature-agent.git}"
APP_DIR="${APP_DIR:-/opt/literature-agent}"
APP_PORT="${APP_PORT:-8765}"
SERVICE="literature-agent"

# 鈹€鈹€ 杈撳嚭helper 鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€
info() { printf '\n\033[1;36m==> %s\033[0m\n' "$*"; }
ok()   { printf '    \033[1;32m鉁揬033[0m %s\n' "$*"; }
warn() { printf '    \033[1;33m!\033[0m %s\n' "$*"; }
die()  { printf '\n\033[1;31m鉁?%s\033[0m\n' "$*" >&2; exit 1; }

[ "$(id -u)" -eq 0 ] || die "璇风敤 root 杩愯锛堜綘鎴浘閲屽氨鏄?root锛岀洿鎺ヨ窇鍗冲彲锛?

info "1/6  瀹夎绯荤粺渚濊禆"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq python3 python3-venv python3-pip git curl ca-certificates >/dev/null
ok "python3 $(python3 --version 2>&1 | awk '{print $2}')"
ok "git $(git --version | awk '{print $3}')"

info "2/6  鎷夊彇浠ｇ爜鍒?$APP_DIR"
if [ -d "$APP_DIR/.git" ]; then
    cd "$APP_DIR"
    git fetch --all -q
    git reset --hard origin/main -q
    ok "宸叉洿鏂板埌鏈€鏂扮増鏈?
else
    rm -rf "$APP_DIR"
    # GitHub 鍦ㄥ浗鍐呮湇鍔″櫒涓婂彲鑳藉緢鎱紝澶辫触灏辨崲闀滃儚
    if git clone --depth 1 "$REPO_URL" "$APP_DIR" 2>/dev/null; then
        ok "浠?GitHub 鍏嬮殕鎴愬姛"
    else
        warn "GitHub 鐩磋繛澶辫触锛屾敼鐢ㄩ暅鍍?ghproxy.net"
        git clone --depth 1 "${REPO_URL/github.com/ghproxy.net\/https:\/\/github.com}" "$APP_DIR" \
            || die "浠ｇ爜涓嬭浇澶辫触锛岃妫€鏌ユ湇鍔″櫒缃戠粶"
        ok "浠庨暅鍍忓厠闅嗘垚鍔?
    fi
    cd "$APP_DIR"
fi

[ -f app.py ] || die "$APP_DIR 涓嬫壘涓嶅埌 app.py锛屼唬鐮佷笉瀹屾暣"
ok "浠ｇ爜灏辩华锛?(ls -1 | wc -l) 涓枃浠?

info "3/6  鍒涘缓 Python 铏氭嫙鐜"
if [ ! -x .venv/bin/python ]; then
    python3 -m venv .venv
    ok "铏氭嫙鐜宸插垱寤?
else
    ok "铏氭嫙鐜宸插瓨鍦?
fi
.venv/bin/python -m pip install --quiet --upgrade pip setuptools wheel
ok "pip $(.venv/bin/python -m pip --version | awk '{print $2}')"

info "4/6  瀹夎 Python 渚濊禆锛堢害 1-2 鍒嗛挓锛?
# 浼樺厛鍦ㄥ浗鍐呴暅鍍忚锛屽揩寰堝锛涘け璐ュ啀鐢ㄩ粯璁ゆ簮
if .venv/bin/python -m pip install --quiet -r requirements.txt \
      -i https://mirrors.aliyun.com/pypi/simple/ 2>/dev/null; then
    ok "渚濊禆瀹夎瀹屾垚锛堥樋閲屼簯闀滃儚锛?
else
    warn "闃块噷浜戦暅鍍忓け璐ワ紝鏀圭敤榛樿婧愰噸璇?
    .venv/bin/python -m pip install --quiet -r requirements.txt \
        || die "渚濊禆瀹夎澶辫触锛岃妫€鏌ユ湇鍔″櫒缃戠粶"
    ok "渚濊禆瀹夎瀹屾垚锛堥粯璁ゆ簮锛?
fi
.venv/bin/python -c "import fastapi, uvicorn, httpx" || die "鍏抽敭渚濊禆瀵煎叆澶辫触"
ok "渚濊禆鑷閫氳繃"

info "5/6  娉ㄥ唽绯荤粺鏈嶅姟锛堝紑鏈鸿嚜鍚?+ 宕╂簝鑷剤锛?
cat > /etc/systemd/system/${SERVICE}.service <<EOF
[Unit]
Description=Literature Survey Agent
Documentation=file://${APP_DIR}/README.md
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

mkdir -p "$APP_DIR/logs"
systemctl daemon-reload
systemctl enable ${SERVICE} >/dev/null 2>&1
systemctl restart ${SERVICE}
ok "鏈嶅姟宸叉敞鍐屽苟鍚姩"

info "6/6  楠岃瘉"
sleep 6
if systemctl is-active --quiet ${SERVICE}; then
    ok "鏈嶅姟杩涚▼杩愯涓?
else
    warn "鏈嶅姟鏈繍琛岋紝鏈€杩戞棩蹇楋細"
    journalctl -u ${SERVICE} -n 25 --no-pager || true
    die "鍚姩澶辫触"
fi

if curl -fsS --max-time 8 "http://127.0.0.1:${APP_PORT}/api/health" >/dev/null 2>&1; then
    ok "鍋ュ悍妫€鏌ラ€氳繃"
else
    warn "鍋ュ悍妫€鏌ユ湭閫氳繃锛屽彲鑳芥槸鍚姩杈冩參锛岀◢鍚庡彲鐢ㄤ笅闈㈠懡浠ゅ啀鐪嬶細"
    echo "      curl http://127.0.0.1:${APP_PORT}/api/health"
fi

PUB_IP="$(curl -fsS --max-time 8 https://api.ipify.org 2>/dev/null || echo '浣犵殑鍏綉IP')"

cat <<EOF

================================================================
 閮ㄧ讲瀹屾垚
================================================================

  鏈満璁块棶    : http://127.0.0.1:${APP_PORT}/
  鍏綉璁块棶    : http://${PUB_IP}:${APP_PORT}/

  甯哥敤鍛戒护
    鏌ョ湅鐘舵€? : systemctl status ${SERVICE}
    鏌ョ湅鏃ュ織  : journalctl -u ${SERVICE} -f
    閲嶅惎鏈嶅姟  : systemctl restart ${SERVICE}
    鍋滄鏈嶅姟  : systemctl stop ${SERVICE}
    鏇存柊浠ｇ爜  : cd ${APP_DIR} && git pull && systemctl restart ${SERVICE}

  鈿狅笍 杩橀渶瑕佸仛涓€姝ワ細鍦ㄩ樋閲屼簯鎺у埗鍙版斁閫氱鍙?${APP_PORT}
     鎺у埗鍙?鈫?杞婚噺搴旂敤鏈嶅姟鍣?ECS 鈫?闃茬伀澧?瀹夊叏缁?鈫?娣诲姞瑙勫垯
       鍗忚 TCP锛岀鍙?${APP_PORT}锛屾簮 0.0.0.0/0
     鍚﹀垯澶栭潰璁块棶涓嶄簡銆?
================================================================
EOF
