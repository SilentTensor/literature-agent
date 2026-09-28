FROM python:3.12-slim

WORKDIR /app

# 不在镜像里写死 PORT：让平台注入的 PORT 自然生效，本地默认 7860
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 7860

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import os,urllib.request;urllib.request.urlopen('http://127.0.0.1:'+os.environ.get('PORT','7860')+'/api/health',timeout=4)"

# 展开 ${PORT:-7860} 需要 shell，因此用 exec 形式显式调用 sh -c
CMD ["sh", "-c", "uvicorn app:app --host 0.0.0.0 --port ${PORT:-7860}"]
