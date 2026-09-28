# 文献调研智能体 (Literature Survey Agent)

输入一个研究主题，自动在多个学术数据库里并行检索，再由 LLM（可选）逐篇评估相关性、
指出覆盖缺口，并支持导出 JSON / BibTeX / Markdown / CSV。

> 项目背景：山东大学首届人工智能创新应用大赛（https://aihub.sdu.edu.cn/aiic/）

## 功能

- **多源并行检索**：ArXiv、CrossRef、OpenAlex、Semantic Scholar 同时查询，按 DOI / ArXiv ID / 标题去重合并
- **主题解析**：把主题拆成 6-8 组关键词；没有 LLM 时自动给出「中文原词 + 英文术语」两套检索词
- **相关性验证**：有 LLM 时逐篇打分（1-5）并给出中文入选理由；无 LLM 时按主题相关度 + 引用影响力排序
- **引文扩展**：可基于种子论文扩展参考文献 / 引证文献
- **缺口分析**：提示遗漏的子方向、经典文献、最新进展，并给出下一轮检索关键词
- **补充检索**：对已有结果追加方向，不必从头再来
- **四种导出格式**：JSON / BibTeX / Markdown / CSV
- **局域网分享**：同一 WiFi 下的手机可直接访问

## 快速开始

```bash
pip install -r requirements.txt
python app.py
```

打开 http://localhost:8765/ 即可。**不配置任何 API Key 也能用**（走启发式筛选）。

### 配置 LLM（推荐，显著提升结果质量）

三种方式任选其一：

```bash
# 方式 1：环境变量
export LLM_PROVIDER=deepseek          # openai 或 deepseek
export LLM_API_KEY=sk-xxxxxx
export LLM_MODEL=deepseek-chat         # 可选，默认按 provider 选择
python app.py
```

方式 2：启动后在网页左侧「API Key」里临时填写（只存在浏览器本地，随请求头发给后端，不写盘）。

方式 3：Render 部署时在环境变量里配置 `LLM_API_KEY`。

> 中文主题**强烈建议配置 LLM**：CrossRef/OpenAlex 对中文的分词很粗糙，没有 LLM 时很难判断
> 中文论文是否真正切题；也可以直接把主题写成英文（如 `graph neural network drug target prediction`），
> 这样即使没有 Key，检索质量也很好。

### 可选环境变量

| 变量 | 默认 | 作用 |
| --- | --- | --- |
| `LLM_PROVIDER` / `LLM_API_KEY` / `LLM_MODEL` | — | LLM 配置，见上 |
| `ALLOW_SERVER_KEY_FOR_ANON` | `0` | **公开部署必读**：是否允许匿名访客使用服务器上的 `LLM_API_KEY`。默认 `0`（不用），避免公网被人白嫖额度 |
| `S2_API_KEY` | — | Semantic Scholar 密钥，解决其严重限流（[免费申请](https://www.semanticscholar.org/product/api)） |
| `OPENALEX_API_KEY` | — | OpenAlex 密钥，避免与全球用户共享匿名额度 |
| `CONTACT_EMAIL` | — | 填邮箱即进入 CrossRef / OpenAlex「礼貌池」，配额更宽裕（**强烈建议公开部署时填写**） |
| `RATE_LIMIT_PER_MINUTE` | `12` | 每个 IP 每分钟可创建的任务数 |
| `MAX_ACTIVE_TASKS` | `6` | 全局同时进行的调研任务上限 |
| `PORT` / `HOST` | `8765` / `0.0.0.0` | 监听端口与地址 |
| `SOURCE_TIMEOUT` | `12` | 单个数据源超时秒数 |
| `LOG_FILE` | — | 指定后日志同时写入该文件（UTF-8） |

## 让别人也能用：三条路

### 路线 A：公网部署（推荐，别人打开链接就能用）

仓库已含 `render.yaml`，推送到 GitHub 后在 [Render](https://render.com) 新建 Blueprint 即可：

1. 把项目推到一个 GitHub 仓库（`.gitignore` 已排除 `.venv/`、`logs/`、密钥）
2. Render → New → Blueprint → 选中该仓库
3. 按提示填环境变量（都会显示成待填项）：
   - `CONTACT_EMAIL`：**建议填**，进「礼貌池」，明显减少 429
   - `LLM_API_KEY`：**想清楚再填**（见下方安全说明）
   - `S2_API_KEY` / `OPENALEX_API_KEY`：可选，进一步提额度
4. 部署完成后拿到形如 `https://literature-agent-xxx.onrender.com` 的公网地址

**⚠️ 关于服务器端 API Key（重要）**

本服务默认是「访客自带 Key」模式：`/api/search` 收到的请求若不带 `X-API-Key` 头，
**不会**动用服务器上的 `LLM_API_KEY`，只走启发式排序、不产生任何费用。

如果你确实想让所有访客共用你的 Key，需要显式设置 `ALLOW_SERVER_KEY_FOR_ANON=1` ——
此时任何匿名访客都能通过你的服务器调用 LLM，**账单记在你头上**。公网环境不建议这么做，
除非你已经加了访问控制。

其他已内置的保护：每 IP 每分钟 12 次、全局最多 6 个并发任务（超出返回 429 并给出中文提示）。

**Free 套餐的注意点**：Render 免费实例闲置 15 分钟会休眠，下次访问有约 30 秒冷启动；
且**重启会清空所有任务状态**（任务是存在内存里的）。给别人长期用建议升到付费套餐。

### 路线 B：Docker（自己的服务器 / NAS）

```bash
docker build -t literature-agent .
docker run -d --name literature-agent --restart unless-stopped \
  -p 7860:7860 \
  -e CONTACT_EMAIL=you@example.com \
  literature-agent
```

`--restart unless-stopped` 就是 Docker 场景下的「随系统常驻」。

### 路线 C：本机运行 + 局域网分享（Windows，已配好）

同一 WiFi 下的手机/平板可直接访问 `http://<你的局域网IP>:8765/`，页面左下角会显示该地址。

项目里已包含一套 Windows 常驻方案：

| 文件 | 作用 |
| --- | --- |
| `watchdog.ps1` | **看门狗**：每 5 分钟探测 `/api/health`，不通就自动拉起服务（注册为计划任务） |
| `run-agent.ps1` | 实际启动脚本：用自带 `.venv` 跑 `app.py`，日志写 `logs/agent.log` |
| `run-agent-hidden.vbs` | 无窗口启动器，避免弹出黑色终端窗口 |

一键注册（普通权限即可，不需要管理员）：

```powershell
cd <项目目录>
# 服务本体：登录即启动
$dir = $PWD.Path
$a = New-ScheduledTaskAction -Execute "wscript.exe" -Argument "`"$dir\run-agent-hidden.vbs`"" -WorkingDirectory $dir
$t = New-ScheduledTaskTrigger -AtLogOn -User "$env:COMPUTERNAME\$env:USERNAME"
$p = New-ScheduledTaskPrincipal -UserId "$env:COMPUTERNAME\$env:USERNAME" -LogonType Interactive -RunLevel Limited
$s = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -Hidden
Register-ScheduledTask -TaskName "LiteratureSurveyAgent" -Action $a -Trigger $t -Principal $p -Settings $s

# 看门狗：每 5 分钟巡检一次
$a2 = New-ScheduledTaskAction -Execute "powershell.exe" -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$dir\watchdog.ps1`"" -WorkingDirectory $dir
$t2 = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(2) -RepetitionInterval (New-TimeSpan -Minutes 5) -RepetitionDuration (New-TimeSpan -Days 3650)
Register-ScheduledTask -TaskName "LiteratureSurveyAgentWatchdog" -Action $a2 -Trigger $t2 -Principal $p -Settings $s
```

管理命令：

```powershell
Get-ScheduledTask LiteratureSurveyAgent* | Select TaskName,State   # 查看状态
Start-ScheduledTask LiteratureSurveyAgent                          # 手动启动
Stop-ScheduledTask  LiteratureSurveyAgent; Stop-ScheduledTask LiteratureSurveyAgentWatchdog
Unregister-ScheduledTask LiteratureSurveyAgent,LiteratureSurveyAgentWatchdog -Confirm:$false   # 卸载
Get-Content .\logs\agent.log -Tail 30 -Encoding UTF8               # 看服务日志
```

> **局域网访问需要在防火墙放通 8765**（需管理员权限的 PowerShell 执行一次）：
> ```powershell
> New-NetFirewallRule -DisplayName "Literature Agent 8765" -Direction Inbound -Protocol TCP -LocalPort 8765 -Action Allow
> ```
> 注意当前网络若被标记为「公用网络」，Windows 默认会拦截入站连接，加规则后即可。

## 部署

**Docker**

```bash
docker build -t literature-agent .
docker run -p 7860:7860 -e LLM_API_KEY=sk-xxx literature-agent
```

**Render**：仓库已含 `render.yaml`，连接仓库后一键部署，按提示填 `LLM_API_KEY` 即可。

**Dev Container**：`.devcontainer/devcontainer.json` 会在容器启动后自动跑在 8765 端口。

## API

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `POST` | `/api/search` | 创建调研任务，返回 `task_id` |
| `GET` | `/api/status/{task_id}` | 轮询进度与结果（前端每 1.2 秒一次） |
| `GET` | `/api/results/{task_id}` | 只取最终结果 |
| `POST` | `/api/refine` | 基于已有任务补充检索 |
| `GET` | `/api/export/{task_id}?fmt=json\|bibtex\|markdown\|csv` | 导出 |
| `GET` | `/api/paper/{paper_id}` | Semantic Scholar 论文详情 |
| `GET` | `/api/debug_sources?q=...` | **排查「搜不到结果」时先用这个**，逐个数据源自检 |
| `GET` | `/api/health` | 健康检查（探针用） |
| `GET` | `/api/config` | 前端启动配置 |
| `GET` | `/api/lanip` | 本机局域网 IP |

可选请求头：`X-API-Key`、`X-LLM-Provider`、`X-LLM-Model`。

## 自检与测试

```bash
python app.py                              # 终端 A（默认 8765）
python verify.py                           # 终端 B：接口 / 前端契约 / 检索 / 导出 / 限流 共 42 项
python verify.py http://127.0.0.1:7860     # 指定其他地址（例如 Docker 容器）
```

真浏览器端到端测试（需要本机装有 Edge 或 Chrome）：

```bash
pip install -r requirements-dev.txt        # 额外需要 websockets
python browser_e2e.py http://127.0.0.1:8765
python browser_e2e.py http://127.0.0.1:8765 "" "graph neural network drug target"
```

`verify.py` 会校验「静态文件挂载是否吞掉了 API 路由」「前端脚本引用的元素 id 是否都存在」
「限流是否真的生效」这类结构性问题。

## 常见问题

**页面能打开，但一篇文献都搜不到？**
先访问 `/api/debug_sources?q=你的主题` 看是哪个数据源不通。常见原因：
- 中文主题 + 没配 LLM → CrossRef 返回大量不切题的论文，程序会主动过滤，只剩很少结果（属预期行为）
- ArXiv / OpenAlex / Semantic Scholar 报 429 → 匿名额度被限流，配 `S2_API_KEY` / `OPENALEX_API_KEY` / `CONTACT_EMAIL` 或稍后重试
- 服务器无法访问外网 → 需要放通 `export.arxiv.org`、`api.crossref.org`、`api.openalex.org`、`api.semanticscholar.org`

**任务卡在某个阶段不动？**
前端 10 分钟会报超时。每个数据源都有独立超时与退避重试，境外接口慢时属正常，可调大 `SOURCE_TIMEOUT`。

## 技术栈

- **后端**：Python 3.10+ / FastAPI / Uvicorn / httpx（全异步）
- **检索**：ArXiv Atom API、CrossRef、OpenAlex、Semantic Scholar Graph API
- **LLM**：OpenAI 兼容接口（OpenAI / DeepSeek）
- **前端**：原生 HTML + CSS + JavaScript，无构建步骤、无外部依赖

## 项目结构

```
app.py                     后端全部逻辑（数据源、LLM、编排、限流、API）
static/index.html          页面结构
static/style.css           样式
static/script.js           前端交互（轮询、渲染、筛选、导出）
requirements.txt           运行依赖
verify.py                  接口级全链路自检（42 项）
browser_e2e.py             真浏览器端到端测试（需 requirements-dev.txt）
render.yaml                Render 一键部署配置
Dockerfile / .dockerignore Docker 镜像
watchdog.ps1               Windows 看门狗（计划任务，每 5 分钟巡检）
run-agent.ps1              实际启动脚本（写 logs/agent.log）
run-agent-hidden.vbs       无窗口启动器
```
