# ---------- 构建前端 ----------
FROM node:22-alpine AS web
WORKDIR /app/frontend
COPY frontend/package.json ./
RUN npm install --registry=https://registry.npmmirror.com
COPY frontend/ ./
RUN npm run build

# ---------- 运行时 ----------
FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    TZ=Asia/Shanghai

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends tzdata curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt requirements-optional.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY backend ./backend
COPY config_example.yaml ./

COPY --from=web /app/frontend/dist ./frontend/dist

RUN mkdir -p data logs static/voice_cache static/qrcode_temp static/emoji_lib

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8000/api/system/health || exit 1

CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
