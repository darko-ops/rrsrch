#!/usr/bin/env bash
# Deploy this engine checkout to Spark: sync code, install deps, migrate, restart the API, (re)install the
# IndexNow timer.
# The reader keeps running (it picks up new code on its next restart); add --reader to restart it too.
set -euo pipefail
ENGINE="$(cd "$(dirname "$0")/../.." && pwd)"
rsync -rc --delete --exclude /.venv --exclude /data --exclude /evals --exclude __pycache__ --exclude .pytest_cache \
  "$ENGINE/" spark:rrsrch-engine/
ssh spark 'set -e; source $HOME/.local/bin/env; cd ~/rrsrch-engine && uv sync -q
  set -a; . ~/.config/rrsrch/engine.env; set +a
  .venv/bin/python -c "from rrsrch.ledger import db
with db.connect() as c: print(\"migrations:\", db.migrate(c) or \"up to date\")"
  systemctl --user restart rrsrch-serve.service
  install -m 644 deploy/spark/rrsrch-indexnow.service deploy/spark/rrsrch-indexnow.timer ~/.config/systemd/user/
  systemctl --user daemon-reload && systemctl --user enable -q --now rrsrch-indexnow.timer
  for i in $(seq 1 20); do curl -sf http://127.0.0.1:8787/v1/health && echo && break; sleep 1; done'
if [ "${1:-}" = "--reader" ]; then ssh spark 'systemctl --user restart rrsrch-reader.service && echo "reader restarted"'; fi
