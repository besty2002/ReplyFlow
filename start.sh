#!/bin/bash

echo "🌐 Starting ReplyFlow All-in-One Server..."
echo "ℹ️  (FastAPI Web + Background Sync Bot)"

# Gunicorn으로 실행 (4개의 워커 사용)
exec gunicorn app.main:app \
    --workers 4 \
    --worker-class uvicorn.workers.UvicornWorker \
    --bind 0.0.0.0:$PORT
