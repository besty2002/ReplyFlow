#!/bin/bash

if [ "$SERVICE_TYPE" = "worker" ]; then
    echo "🚀 Starting Background Sync Bot..."
    python -m app.workers.sync_bot
else
    echo "🌐 Starting FastAPI Web Server..."
    # Gunicorn으로 실행 (생산성/안정성)
    exec gunicorn app.main:app --workers 4 --worker-class uvicorn.workers.UvicornWorker --bind 0.0.0.0:$PORT
fi
