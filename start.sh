#!/bin/bash

# 포트 설정 (Render는 기본적으로 10000 포트를 사용합니다)
APP_PORT=${PORT:-10000}

echo "🌐 Starting ReplyFlow All-in-One Server on port $APP_PORT..."
echo "ℹ️  (Mode: Single Worker for Free Tier Stability)"

# Gunicorn 실행 (메모리 절약을 위해 워커를 1개로 제한)
exec gunicorn app.main:app \
    --workers 1 \
    --worker-class uvicorn.workers.UvicornWorker \
    --bind 0.0.0.0:$APP_PORT \
    --timeout 120
