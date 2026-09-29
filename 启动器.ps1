# ===================================================================
#  文献调研智能体 — 桌面启动器（图形界面）
#
#  双击桌面快捷方式即可打开。功能：
#    · 查看服务是否在运行
#    · 一键启动 / 重启服务
#    · 查看并复制"公网地址"和"校园网地址"
#    · 一键在浏览器打开
#    · 查看最近日志
#
#  注意：本文件必须保存为 UTF-8 with BOM。
#  Windows PowerShell 5.1 会把没有 BOM 的 .ps1 当作系统 ANSI 码页(GBK)读取，
#  那样下面所有的中文都会变成乱码甚至导致解析失败。
# ===================================================================

Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
[System.Windows.Forms.Application]::EnableVisualStyles()

$ErrorActionPreference = "Continue"

$Root    = $PSScriptRoot
$Port    = "8765"
$UrlFile = Join-Path $Root "public-url.txt"
$LogDir  = Join-Path $Root "logs"
$AgentLog = Join-Path $LogDir "agent.log"

# ── 主题色 ─────────────────────────────────────────────────────────
$cBg      = [System.Drawing.Color]::FromArgb(245, 246, 248)
$cCard    = [System.Drawing.Color]::White
$cText    = [System.Drawing.Color]::FromArgb(26, 29, 35)
$cSub     = [System.Drawing.Color]::FromArgb(107, 114, 128)
$cPrimary = [System.Drawing.Color]::FromArgb(37, 99, 235)
$cGreen   = [System.Drawing.Color]::FromArgb(5, 150, 105)
$cRed     = [System.Drawing.Color]::FromArgb(220, 38, 38)
$cAmber   = [System.Drawing.Color]::FromArgb(217, 119, 6)
$cBorder  = [System.Drawing.Color]::FromArgb(229, 231, 235)

# ── 辅助函数 ───────────────────────────────────────────────────────
function Test-Service {
    try {
        $r = Invoke-RestMethod "http://127.0.0.1:$Port/api/health" -TimeoutSec 4
        return ($r.status -eq "ok")
    } catch { return $false }
}

function Get-LanIp {
    try {
        $ips = Get-NetIPAddress -AddressFamily IPv4 -ErrorAction Stop |
               Where-Object { $_.IPAddress -like "10.*" -or $_.IPAddress -like "192.168.*" -or $_.IPAddress -like "172.*" }
        if ($ips) { return ($ips | Select-Object -First 1).IPAddress }
    } catch { }
    return $null
}

function Get-PublicUrl {
    if (Test-Path $UrlFile) {
        $u = (Get-Content $UrlFile -Raw -ErrorAction SilentlyContinue).Trim()
        if ($u -match "^https?://") { return $u }
    }
    return $null
}

# ── 主窗口 ─────────────────────────────────────────────────────────
$form = New-Object System.Windows.Forms.Form
$form.Text = "文献调研智能体 — 启动器"
$form.Size = New-Object System.Drawing.Size(560, 620)
$form.StartPosition = "CenterScreen"
$form.BackColor = $cBg
$form.FormBorderStyle = "FixedSingle"
$form.MaximizeBox = $false
$form.Font = New-Object System.Drawing.Font("Microsoft YaHei UI", 9)

function New-Label($text, $x, $y, $w, $h, $size, $color, $bold) {
    $l = New-Object System.Windows.Forms.Label
    $l.Text = $text
    $l.Location = New-Object System.Drawing.Point($x, $y)
    $l.Size = New-Object System.Drawing.Size($w, $h)
    $style = if ($bold) { [System.Drawing.FontStyle]::Bold } else { [System.Drawing.FontStyle]::Regular }
    $l.Font = New-Object System.Drawing.Font("Microsoft YaHei UI", $size, $style)
    $l.ForeColor = $color
    $l.BackColor = [System.Drawing.Color]::Transparent
    return $l
}

function New-Button($text, $x, $y, $w, $h, $primary) {
    $b = New-Object System.Windows.Forms.Button
    $b.Text = $text
    $b.Location = New-Object System.Drawing.Point($x, $y)
    $b.Size = New-Object System.Drawing.Size($w, $h)
    $b.FlatStyle = "Flat"
    $b.FlatAppearance.BorderSize = if ($primary) { 0 } else { 1 }
    $b.FlatAppearance.BorderColor = $cBorder
    $b.BackColor = if ($primary) { $cPrimary } else { [System.Drawing.Color]::White }
    $b.ForeColor = if ($primary) { [System.Drawing.Color]::White } else { $cText }
    $b.Font = New-Object System.Drawing.Font("Microsoft YaHei UI", 9)
    $b.Cursor = [System.Windows.Forms.Cursors]::Hand
    return $b
}

# 标题
$form.Controls.Add((New-Label "文献调研智能体" 24 18 400 30 16 $cText $true))
$form.Controls.Add((New-Label "Literature Survey Agent" 24 48 400 20 9 $cSub $false))

# ── 状态卡片 ───────────────────────────────────────────────────────
$card = New-Object System.Windows.Forms.Panel
$card.Location = New-Object System.Drawing.Point(20, 80)
$card.Size = New-Object System.Drawing.Size(505, 92)
$card.BackColor = $cCard
$card.BorderStyle = "FixedSingle"
$form.Controls.Add($card)

$dot = New-Label "●" 18 16 24 24 14 $cSub $false
$card.Controls.Add($dot)
$lblState = New-Label "正在检查…" 44 18 380 24 11 $cText $true
$card.Controls.Add($lblState)
$lblDetail = New-Label "" 44 44 440 32 8.5 $cSub $false
$card.Controls.Add($lblDetail)

# ── 地址卡片 ───────────────────────────────────────────────────────
$addrCard = New-Object System.Windows.Forms.Panel
$addrCard.Location = New-Object System.Drawing.Point(20, 184)
$addrCard.Size = New-Object System.Drawing.Size(505, 190)
$addrCard.BackColor = $cCard
$addrCard.BorderStyle = "FixedSingle"
$form.Controls.Add($addrCard)

$addrCard.Controls.Add((New-Label "分享给别人的地址" 18 14 300 22 10 $cText $true))

# 校园网地址
$addrCard.Controls.Add((New-Label "同一校园网 WiFi" 18 48 160 20 9 $cSub $false))
$txtLan = New-Object System.Windows.Forms.TextBox
$txtLan.Location = New-Object System.Drawing.Point(18, 70)
$txtLan.Size = New-Object System.Drawing.Size(330, 26)
$txtLan.ReadOnly = $true
$txtLan.BackColor = $cBg
$txtLan.BorderStyle = "FixedSingle"
$addrCard.Controls.Add($txtLan)

$btnOpenLan = New-Button "打开" 356 69 62 28 $false
$btnCopyLan = New-Button "复制" 424 69 62 28 $false
$addrCard.Controls.Add($btnOpenLan)
$addrCard.Controls.Add($btnCopyLan)

# 公网地址
$addrCard.Controls.Add((New-Label "任何网络（4G／外地）" 18 108 220 20 9 $cSub $false))
$txtPub = New-Object System.Windows.Forms.TextBox
$txtPub.Location = New-Object System.Drawing.Point(18, 130)
$txtPub.Size = New-Object System.Drawing.Size(330, 26)
$txtPub.ReadOnly = $true
$txtPub.BackColor = $cBg
$txtPub.BorderStyle = "FixedSingle"
$addrCard.Controls.Add($txtPub)

$btnOpenPub = New-Button "打开" 356 129 62 28 $false
$btnCopyPub = New-Button "复制" 424 129 62 28 $false
$addrCard.Controls.Add($btnOpenPub)
$addrCard.Controls.Add($btnCopyPub)

# ── 操作按钮 ───────────────────────────────────────────────────────
$btnStart = New-Button "启动 / 重启服务" 20 390 160 38 $true
$btnLocal = New-Button "在本机打开程序" 188 390 160 38 $false
$btnRefresh = New-Button "刷新状态" 356 390 169 38 $false
$form.Controls.Add($btnStart)
$form.Controls.Add($btnLocal)
$form.Controls.Add($btnRefresh)

# ── 日志区 ─────────────────────────────────────────────────────────
$form.Controls.Add((New-Label "最近日志" 20 440 200 22 9 $cSub $false))
$txtLog = New-Object System.Windows.Forms.TextBox
$txtLog.Location = New-Object System.Drawing.Point(20, 464)
$txtLog.Size = New-Object System.Drawing.Size(505, 100)
$txtLog.Multiline = $true
$txtLog.ReadOnly = $true
$txtLog.ScrollBars = "Vertical"
$txtLog.BackColor = [System.Drawing.Color]::FromArgb(250, 250, 251)
$txtLog.Font = New-Object System.Drawing.Font("Consolas", 8)
$txtLog.BorderStyle = "FixedSingle"
$form.Controls.Add($txtLog)

# ── 刷新逻辑 ───────────────────────────────────────────────────────
function Refresh-All {
    # 服务状态
    $alive = Test-Service
    if ($alive) {
        $dot.ForeColor = $cGreen
        $lblState.Text = "服务正在运行"
        $lblState.ForeColor = $cText
    } else {
        $dot.ForeColor = $cRed
        $lblState.Text = "服务没有运行"
        $lblState.ForeColor = $cRed
    }

    # 地址
    $lan = Get-LanIp
    if ($lan) {
        $txtLan.Text = "http://${lan}:$Port/"
    } else {
        $txtLan.Text = "（没检测到局域网地址）"
    }

    $pub = Get-PublicUrl
    if ($pub) {
        $txtPub.Text = $pub
    } else {
        $txtPub.Text = "（暂无，公网隧道可能被限流或未启动）"
    }

    # 详情
    $cf = Get-Process cloudflared -ErrorAction SilentlyContinue
    $sshTunnel = Get-Process ssh -ErrorAction SilentlyContinue
    $tunnelDesc = if ($cf) { "Cloudflare 隧道运行中" }
                  elseif ($sshTunnel) { "serveo 隧道运行中" }
                  else { "隧道未运行" }
    $lblDetail.Text = "本机程序端口 $Port　|　$tunnelDesc`r`n每 1 分钟自动检查，挂掉会自动重启"

    # 日志
    if (Test-Path $AgentLog) {
        $tail = Get-Content $AgentLog -Tail 8 -Encoding UTF8 -ErrorAction SilentlyContinue
        $txtLog.Text = ($tail -join "`r`n")
        $txtLog.SelectionStart = $txtLog.Text.Length
        $txtLog.ScrollToCaret()
    } else {
        $txtLog.Text = "（暂无日志）"
    }
}

# ── 事件 ───────────────────────────────────────────────────────────
$btnRefresh.Add_Click({ Refresh-All })

$btnStart.Add_Click({
    $btnStart.Enabled = $false
    $btnStart.Text = "启动中…"
    try {
        # 用计划任务启动，和看门狗保持一致（走 .venv、会写日志）
        Start-ScheduledTask -TaskName "LiteratureSurveyAgent" -ErrorAction SilentlyContinue
        Start-ScheduledTask -TaskName "LiteratureSurveyAgentWatchdog" -ErrorAction SilentlyContinue
        Start-ScheduledTask -TaskName "LiteratureSurveyAgentTunnel" -ErrorAction SilentlyContinue
        for ($i = 0; $i -lt 20; $i++) {
            Start-Sleep -Milliseconds 1500
            if (Test-Service) { break }
        }
    } catch { }
    $btnStart.Enabled = $true
    $btnStart.Text = "启动 / 重启服务"
    Refresh-All
})

$btnLocal.Add_Click({
    Start-Process "http://localhost:$Port/"
})

$btnOpenLan.Add_Click({
    $u = $txtLan.Text
    if ($u -match "^http") { Start-Process $u }
})

$btnCopyLan.Add_Click({
    $u = $txtLan.Text
    if ($u -match "^http") {
        [System.Windows.Forms.Clipboard]::SetText($u)
        $btnCopyLan.Text = "已复制"
        $btnCopyLan.Refresh()
        Start-Sleep -Milliseconds 900
        $btnCopyLan.Text = "复制"
    }
})

$btnOpenPub.Add_Click({
    $u = $txtPub.Text
    if ($u -match "^http") { Start-Process $u }
})

$btnCopyPub.Add_Click({
    $u = $txtPub.Text
    if ($u -match "^http") {
        [System.Windows.Forms.Clipboard]::SetText($u)
        $btnCopyPub.Text = "已复制"
        $btnCopyPub.Refresh()
        Start-Sleep -Milliseconds 900
        $btnCopyPub.Text = "复制"
    }
})

# 每 10 秒自动刷新状态
$timer = New-Object System.Windows.Forms.Timer
$timer.Interval = 10000
$timer.Add_Tick({ Refresh-All })
$timer.Start()

$form.Add_Shown({ Refresh-All })

[void]$form.ShowDialog()
$form.Dispose()
