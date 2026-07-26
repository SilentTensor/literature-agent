# 文献调研智能体 (Literature Survey Agent)

基于 Semantic Scholar API + OpenAI/DeepSeek LLM 的精准文献搜集系统。

## 数据源
- **ArXiv** — 开放获取论文（~200万篇）
- **CrossRef** — 期刊论文元数据（2亿+）
- **OpenAlex** — 综合学术数据库（2.5亿+）
- **PubMed** — 生物医学文献
- **DOAJ** — 开放获取期刊

## 功能
- 多源并行检索
- LLM 智能主题解析与相关性评分
- 缺口分析
- 分批呈现论文
- 5 阶段进度显示
- 局域网分享

## 快速部署

[![Deploy to Render](https://render.com/images/deploy/docker.svg)](https://render.com/deploy?repo=https://github.com/SilentTensor/literature-agent)

### 方式一：Render 一键部署
1. 点击上方按钮
2. 连接 GitHub 仓库
3. 等待自动部署（约 2-3 分钟）

### 方式二：本地运行
```bash
pip install -r requirements.txt
# 可选：设置 LLM API Key
export LLM_API_KEY="sk-your-key"
export LLM_PROVIDER="deepseek"  # 或 openai
python app.py
```

访问 http://localhost:8765/

## 技术栈
- **后端**: Python + FastAPI + Uvicorn
- **搜索**: httpx (异步 HTTP)
- **LLM**: OpenAI / DeepSeek API
- **前端**: 原生 JavaScript (ES5 兼容)
