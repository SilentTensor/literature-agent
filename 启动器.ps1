# ===================================================================
#  文献调研智能体 — 桌面启动器（QQ 风格界面）
#
#  设计要点（借鉴 QQ / 现代 Windows 应用的视觉语言）：
#    · 顶部渐变头部 + 圆形图标
#    · 圆角卡片 + 柔和描边，替代系统默认的方框
#    · 扁平圆角按钮，主操作用品牌色填充
#    · 全局无衬线字体，分层级字号
#    · 状态用色点 + 文字，不弹窗打断
#
#  实现说明：WinForms 没有原生圆角/阴影，这里用 GraphicsPath +
#  抗锯齿自绘圆角矩形，把卡片和按钮做成可复用的小控件。
#  做不到 100% 像素级还原 QQ（那需要 WPF/Electron），但观感一致。
#
#  ⚠️ 本文件必须保存为 UTF-8 with BOM。
#  Windows PowerShell 5.1 把无 BOM 的 .ps1 当 GBK 读，中文会乱码。
# ===================================================================

Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
[System.Windows.Forms.Application]::EnableVisualStyles()
[System.Windows.Forms.Application]::SetCompatibleTextRenderingDefault($false)

$ErrorActionPreference = "Continue"

$Root     = $PSScriptRoot
$Port     = "8765"
$UrlFile  = Join-Path $Root "public-url.txt"
$LogDir   = Join-Path $Root "logs"
$AgentLog = Join-Path $LogDir "agent.log"

# ── 配色（QQ 风格：亮蓝主色 + 中性灰底 + 高对比文字）────────────────
$C = @{
    HeaderTop = [System.Drawing.Color]::FromArgb(18, 183, 245)
    HeaderBot = [System.Drawing.Color]::FromArgb(10, 140, 220)
    Bg        = [System.Drawing.Color]::FromArgb(240, 242, 245)
    Text      = [System.Drawing.Color]::FromArgb(32, 36, 44)
    Sub       = [System.Drawing.Color]::FromArgb(130, 138, 150)
    Green     = [System.Drawing.Color]::FromArgb(28, 175, 108)
    Red       = [System.Drawing.Color]::FromArgb(232, 76, 76)
    Hover     = [System.Drawing.Color]::FromArgb(247, 249, 252)
}

# ── UI 控件（C# 定义，见 ui_controls.ps1）────────────────────────────
# 不能在这里用 PowerShell 的 class 继承 WinForms 控件：解析阶段类型还不存在。
. (Join-Path $PSScriptRoot "ui_controls.ps1")
# ── 数据读取 ───────────────────────────────────────────────────────
function Test-Service {
    try { return ((Invoke-RestMethod "http://127.0.0.1:$Port/api/health" -TimeoutSec 4).status -eq "ok") }
    catch { return $false }
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
function Get-TunnelText {
    if (Get-Process cloudflared -ErrorAction SilentlyContinue) { return "隧道：Cloudflare" }
    if (Get-Process ssh -ErrorAction SilentlyContinue) { return "隧道：serveo" }
    return "隧道：未运行"
}

# ── 主窗体 ─────────────────────────────────────────────────────────
$W = 520; $H = 664
$form = New-Object System.Windows.Forms.Form
$form.Text = "文献调研智能体"
$form.ClientSize = New-Object System.Drawing.Size($W, $H)
$form.StartPosition = "CenterScreen"
$form.BackColor = $C.Bg
$form.FormBorderStyle = "FixedSingle"
$form.MaximizeBox = $false
$form.Font = New-Object System.Drawing.Font("Microsoft YaHei UI", 9)

# ── 渐变头部 ───────────────────────────────────────────────────────
$header = New-Object CardPanel
$header.Radius = 0
$header.UseGradient = $true
$header.GradTop = $C.HeaderTop
$header.GradBot = $C.HeaderBot
$header.Stroke = [System.Drawing.Color]::Transparent
$header.Location = New-Object System.Drawing.Point(0, 0)
$header.Size = New-Object System.Drawing.Size($W, 102)
$form.Controls.Add($header)

$logo = New-Object System.Windows.Forms.Label
$logo.Text = "文"
$logo.Font = New-Object System.Drawing.Font("Microsoft YaHei UI", 20, [System.Drawing.FontStyle]::Bold)
$logo.ForeColor = [System.Drawing.Color]::White
$logo.BackColor = [System.Drawing.Color]::FromArgb(60, 255, 255, 255)
$logo.Location = New-Object System.Drawing.Point(22, 24)
$logo.Size = New-Object System.Drawing.Size(56, 56)
$logo.TextAlign = "MiddleCenter"
$header.Controls.Add($logo)

$title = New-Object System.Windows.Forms.Label
$title.Text = "文献调研智能体"
$title.Font = New-Object System.Drawing.Font("Microsoft YaHei UI", 15, [System.Drawing.FontStyle]::Bold)
$title.ForeColor = [System.Drawing.Color]::White
$title.BackColor = [System.Drawing.Color]::Transparent
$title.Location = New-Object System.Drawing.Point(90, 28)
$title.Size = New-Object System.Drawing.Size(300, 30)
$header.Controls.Add($title)

$subtitle = New-Object System.Windows.Forms.Label
$subtitle.Text = "Literature Survey Agent"
$subtitle.Font = New-Object System.Drawing.Font("Segoe UI", 8.5)
$subtitle.ForeColor = [System.Drawing.Color]::FromArgb(210, 238, 255)
$subtitle.BackColor = [System.Drawing.Color]::Transparent
$subtitle.Location = New-Object System.Drawing.Point(92, 58)
$subtitle.Size = New-Object System.Drawing.Size(300, 20)
$header.Controls.Add($subtitle)

# 头部右侧状态胶囊
$pill = New-Object CardPanel
$pill.Radius = 14
$pill.Fill = [System.Drawing.Color]::FromArgb(72, 255, 255, 255)
$pill.Stroke = [System.Drawing.Color]::Transparent
$pill.Location = New-Object System.Drawing.Point(392, 34)
$pill.Size = New-Object System.Drawing.Size(108, 30)
$header.Controls.Add($pill)

$pillDot = New-Object StatusDot
$pillDot.Location = New-Object System.Drawing.Point(8, 9)
$pillDot.Size = New-Object System.Drawing.Size(12, 12)
$pillDot.DotColor = $C.Sub
$pill.Controls.Add($pillDot)

$pillText = New-Object System.Windows.Forms.Label
$pillText.Text = "检测中"
$pillText.Font = New-Object System.Drawing.Font("Microsoft YaHei UI", 8.5)
$pillText.ForeColor = [System.Drawing.Color]::White
$pillText.BackColor = [System.Drawing.Color]::Transparent
$pillText.Location = New-Object System.Drawing.Point(24, 6)
$pillText.Size = New-Object System.Drawing.Size(80, 18)
$pill.Controls.Add($pillText)

# ── 状态卡片 ───────────────────────────────────────────────────────
$cardStatus = New-Object CardPanel
$cardStatus.Location = New-Object System.Drawing.Point(18, 118)
$cardStatus.Size = New-Object System.Drawing.Size(484, 76)
$form.Controls.Add($cardStatus)

$stTitle = New-Object System.Windows.Forms.Label
$stTitle.Text = "服务状态"
$stTitle.Font = New-Object System.Drawing.Font("Microsoft YaHei UI", 8.5)
$stTitle.ForeColor = $C.Sub
$stTitle.BackColor = [System.Drawing.Color]::Transparent
$stTitle.Location = New-Object System.Drawing.Point(18, 10)
$stTitle.Size = New-Object System.Drawing.Size(200, 18)
$cardStatus.Controls.Add($stTitle)

$stMain = New-Object System.Windows.Forms.Label
$stMain.Text = "正在检查…"
$stMain.Font = New-Object System.Drawing.Font("Microsoft YaHei UI", 12, [System.Drawing.FontStyle]::Bold)
$stMain.ForeColor = $C.Text
$stMain.BackColor = [System.Drawing.Color]::Transparent
$stMain.Location = New-Object System.Drawing.Point(18, 30)
$stMain.Size = New-Object System.Drawing.Size(280, 28)
$cardStatus.Controls.Add($stMain)

$stInfo = New-Object System.Windows.Forms.Label
$stInfo.Text = ""
$stInfo.Font = New-Object System.Drawing.Font("Microsoft YaHei UI", 8.5)
$stInfo.ForeColor = $C.Sub
$stInfo.BackColor = [System.Drawing.Color]::Transparent
$stInfo.Location = New-Object System.Drawing.Point(250, 36)
$stInfo.Size = New-Object System.Drawing.Size(216, 20)
$stInfo.TextAlign = "MiddleRight"
$cardStatus.Controls.Add($stInfo)

# ── 地址卡片 ───────────────────────────────────────────────────────
$cardAddr = New-Object CardPanel
$cardAddr.Location = New-Object System.Drawing.Point(18, 204)
$cardAddr.Size = New-Object System.Drawing.Size(484, 206)
$form.Controls.Add($cardAddr)

$addrTitle = New-Object System.Windows.Forms.Label
$addrTitle.Text = "分享给别人的地址"
$addrTitle.Font = New-Object System.Drawing.Font("Microsoft YaHei UI", 8.5)
$addrTitle.ForeColor = $C.Sub
$addrTitle.BackColor = [System.Drawing.Color]::Transparent
$addrTitle.Location = New-Object System.Drawing.Point(18, 10)
$addrTitle.Size = New-Object System.Drawing.Size(240, 18)
$cardAddr.Controls.Add($addrTitle)

function New-AddrRow($parent, $labelText, $y) {
    $lab = New-Object System.Windows.Forms.Label
    $lab.Text = $labelText
    $lab.Font = New-Object System.Drawing.Font("Microsoft YaHei UI", 9)
    $lab.ForeColor = $C.Text
    $lab.BackColor = [System.Drawing.Color]::Transparent
    $lab.Location = New-Object System.Drawing.Point(18, $y)
    $lab.Size = New-Object System.Drawing.Size(320, 20)
    $parent.Controls.Add($lab)

    $box = New-Object System.Windows.Forms.TextBox
    $box.Location = New-Object System.Drawing.Point(18, ($y + 22))
    $box.Size = New-Object System.Drawing.Size(320, 26)
    $box.ReadOnly = $true
    $box.BorderStyle = "FixedSingle"
    $box.BackColor = [System.Drawing.Color]::FromArgb(247, 249, 252)
    $box.ForeColor = $C.Text
    $box.Font = New-Object System.Drawing.Font("Consolas", 8.5)
    $parent.Controls.Add($box)

    $bOpen = New-Object FlatButton
    $bOpen.Text = "打开"
    $bOpen.Outlined = $true
    $bOpen.Normal = [System.Drawing.Color]::White
    $bOpen.HoverColor = $C.Hover
    $bOpen.Location = New-Object System.Drawing.Point(346, ($y + 21))
    $bOpen.Size = New-Object System.Drawing.Size(56, 28)
    $parent.Controls.Add($bOpen)

    $bCopy = New-Object FlatButton
    $bCopy.Text = "复制"
    $bCopy.Outlined = $true
    $bCopy.Normal = [System.Drawing.Color]::White
    $bCopy.HoverColor = $C.Hover
    $bCopy.Location = New-Object System.Drawing.Point(408, ($y + 21))
    $bCopy.Size = New-Object System.Drawing.Size(56, 28)
    $parent.Controls.Add($bCopy)

    return @{ Box = $box; Open = $bOpen; Copy = $bCopy }
}

$rowLan = New-AddrRow $cardAddr "同一校园网 WiFi（最快）" 38
$rowPub = New-AddrRow $cardAddr "任何网络：4G / 外地" 116

# ── 操作按钮 ───────────────────────────────────────────────────────
$btnStart = New-Object FlatButton
$btnStart.Text = "启动 / 重启服务"
$btnStart.Normal = $C.HeaderTop
$btnStart.HoverColor = [System.Drawing.Color]::FromArgb(28, 168, 232)
$btnStart.DownColor = [System.Drawing.Color]::FromArgb(8, 130, 205)
$btnStart.TextColor = [System.Drawing.Color]::White
$btnStart.Font = New-Object System.Drawing.Font("Microsoft YaHei UI", 10, [System.Drawing.FontStyle]::Bold)
$btnStart.Location = New-Object System.Drawing.Point(18, 424)
$btnStart.Size = New-Object System.Drawing.Size(232, 42)
$form.Controls.Add($btnStart)

$btnLocal = New-Object FlatButton
$btnLocal.Text = "在本机打开程序"
$btnLocal.Outlined = $true
$btnLocal.Normal = [System.Drawing.Color]::White
$btnLocal.HoverColor = $C.Hover
$btnLocal.Location = New-Object System.Drawing.Point(262, 424)
$btnLocal.Size = New-Object System.Drawing.Size(240, 42)
$form.Controls.Add($btnLocal)

# ── 日志卡片 ───────────────────────────────────────────────────────
$cardLog = New-Object CardPanel
$cardLog.Location = New-Object System.Drawing.Point(18, 480)
$cardLog.Size = New-Object System.Drawing.Size(484, 164)
$form.Controls.Add($cardLog)

$logTitle = New-Object System.Windows.Forms.Label
$logTitle.Text = "最近日志"
$logTitle.Font = New-Object System.Drawing.Font("Microsoft YaHei UI", 8.5)
$logTitle.ForeColor = $C.Sub
$logTitle.BackColor = [System.Drawing.Color]::Transparent
$logTitle.Location = New-Object System.Drawing.Point(18, 8)
$logTitle.Size = New-Object System.Drawing.Size(200, 18)
$cardLog.Controls.Add($logTitle)

$lnkRefresh = New-Object System.Windows.Forms.LinkLabel
$lnkRefresh.Text = "刷新状态"
$lnkRefresh.Font = New-Object System.Drawing.Font("Microsoft YaHei UI", 8.5)
$lnkRefresh.LinkColor = $C.HeaderBot
$lnkRefresh.ActiveLinkColor = $C.HeaderTop
$lnkRefresh.BackColor = [System.Drawing.Color]::Transparent
$lnkRefresh.Location = New-Object System.Drawing.Point(394, 8)
$lnkRefresh.Size = New-Object System.Drawing.Size(72, 18)
$lnkRefresh.TextAlign = "MiddleRight"
$cardLog.Controls.Add($lnkRefresh)

$txtLog = New-Object System.Windows.Forms.TextBox
$txtLog.Location = New-Object System.Drawing.Point(18, 32)
$txtLog.Size = New-Object System.Drawing.Size(448, 118)
$txtLog.Multiline = $true
$txtLog.ReadOnly = $true
$txtLog.ScrollBars = "Vertical"
$txtLog.BorderStyle = "FixedSingle"
$txtLog.BackColor = [System.Drawing.Color]::FromArgb(250, 251, 253)
$txtLog.ForeColor = [System.Drawing.Color]::FromArgb(90, 98, 110)
$txtLog.Font = New-Object System.Drawing.Font("Consolas", 8)
$cardLog.Controls.Add($txtLog)

# ── 刷新逻辑 ───────────────────────────────────────────────────────
function Refresh-All {
    $alive = Test-Service

    if ($alive) {
        $pillDot.DotColor = $C.Green
        $pillText.Text = "运行中"
        $stMain.Text = "服务正在运行"
        $stMain.ForeColor = $C.Green
    } else {
        $pillDot.DotColor = $C.Red
        $pillText.Text = "已停止"
        $stMain.Text = "服务没有运行"
        $stMain.ForeColor = $C.Red
    }
    $pillDot.Invalidate()

    $stInfo.Text = Get-TunnelText

    $lan = Get-LanIp
    if ($lan) { $rowLan.Box.Text = "http://${lan}:$Port/" }
    else { $rowLan.Box.Text = "（未检测到局域网地址）" }

    $pub = Get-PublicUrl
    if ($pub) { $rowPub.Box.Text = $pub }
    else { $rowPub.Box.Text = "（暂无，隧道可能被限流）" }

    if (Test-Path $AgentLog) {
        $tail = Get-Content $AgentLog -Tail 6 -Encoding UTF8 -ErrorAction SilentlyContinue
        $txtLog.Text = ($tail -join "`r`n")
        $txtLog.SelectionStart = $txtLog.Text.Length
        $txtLog.ScrollToCaret()
    } else { $txtLog.Text = "（暂无日志）" }
}

# ── 事件 ───────────────────────────────────────────────────────────
$btnStart.Add_Click({
    $btnStart.Enabled = $false
    $btnStart.Text = "启动中…"
    $btnStart.Invalidate()
    foreach ($t in @("LiteratureSurveyAgent", "LiteratureSurveyAgentWatchdog", "LiteratureSurveyAgentTunnel")) {
        Start-ScheduledTask -TaskName $t -ErrorAction SilentlyContinue
    }
    for ($i = 0; $i -lt 20; $i++) {
        Start-Sleep -Milliseconds 1500
        if (Test-Service) { break }
    }
    $btnStart.Text = "启动 / 重启服务"
    $btnStart.Enabled = $true
    $btnStart.Invalidate()
    Refresh-All
})

$btnLocal.Add_Click({ Start-Process "http://localhost:$Port/" })
$lnkRefresh.Add_LinkClicked({ Refresh-All })

$rowLan.Open.Add_Click({ if ($rowLan.Box.Text -match "^http") { Start-Process $rowLan.Box.Text } })
$rowLan.Copy.Add_Click({
    if ($rowLan.Box.Text -match "^http") {
        [System.Windows.Forms.Clipboard]::SetText($rowLan.Box.Text)
        $rowLan.Copy.Text = "已复制"; $rowLan.Copy.Invalidate()
        Start-Sleep -Milliseconds 800
        $rowLan.Copy.Text = "复制"; $rowLan.Copy.Invalidate()
    }
})
$rowPub.Open.Add_Click({ if ($rowPub.Box.Text -match "^http") { Start-Process $rowPub.Box.Text } })
$rowPub.Copy.Add_Click({
    if ($rowPub.Box.Text -match "^http") {
        [System.Windows.Forms.Clipboard]::SetText($rowPub.Box.Text)
        $rowPub.Copy.Text = "已复制"; $rowPub.Copy.Invalidate()
        Start-Sleep -Milliseconds 800
        $rowPub.Copy.Text = "复制"; $rowPub.Copy.Invalidate()
    }
})

$timer = New-Object System.Windows.Forms.Timer
$timer.Interval = 10000
$timer.Add_Tick({ Refresh-All })
$timer.Start()

$form.Add_Shown({ Refresh-All })

[void]$form.ShowDialog()
$form.Dispose()
