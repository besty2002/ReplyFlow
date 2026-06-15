#!/bin/bash

echo "Starting ReplyFlow one-shot sync..."
exec python -m app.workers.sync_once
