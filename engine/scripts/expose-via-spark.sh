#!/usr/bin/env bash
# Expose local Postgres ledger to the public web via Spark + Cloudflare quick tunnel.
# Prerequisites: docker postgres on Mac :5433, SSH Host spark, cloudflared on spark at /tmp/cloudflared
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# 1) reverse-tunnel Postgres to spark
pkill -f "ssh.*-R 5433:" 2>/dev/null || true
ssh -f -N -o ExitOnForwardFailure=yes -o ServerAliveInterval=30 -R 5433:127.0.0.1:5433 spark
# 2) serve on spark (engine checkout at ~/rrsrch-engine)
ssh spark 'source $HOME/.local/bin/env; fuser -k 8787/tcp 2>/dev/null; cd ~/rrsrch-engine;
  export RRSRCH_DATABASE_URL=postgresql://rrsrch:rrsrch@127.0.0.1:5433/rrsrch
  export RRSRCH_LLM_URL=http://127.0.0.1:11434/v1 RRSRCH_READER_MODEL=qwen3.8:27b-q4_K_M RRSRCH_CORS_ORIGIN=* PYTHONUNBUFFERED=1
  pkill -f "rrsrch serve" 2>/dev/null || true
  nohup uv run rrsrch serve --host 127.0.0.1 --port 8787 >/tmp/rrsrch-serve.log 2>&1 </dev/null &
  sleep 3; curl -sf http://127.0.0.1:8787/v1/health; echo
  pkill -f "/tmp/cloudflared tunnel" 2>/dev/null || true
  nohup /tmp/cloudflared tunnel --url http://127.0.0.1:8787 >/tmp/cf.log 2>&1 </dev/null &
  sleep 10; grep -oE "https://[a-z0-9-]+\\.trycloudflare\\.com" /tmp/cf.log | head -1'
