#!/usr/bin/env bash
# Deploy this engine checkout to Spark: sync code, install deps, migrate, restart the API, (re)install the
# IndexNow and daily benchmarks timers, and install (not enable) the weekly X timer.
# The reader keeps running (it picks up new code on its next restart); add --reader to restart it too.
# Only committed code that is already on origin/main ships (CI runs there); local edits never do.
set -euo pipefail
ENGINE="$(cd "$(dirname "$0")/../.." && pwd)"
REPO="$(git -C "$ENGINE" rev-parse --show-toplevel)"
if [ -n "$(git -C "$REPO" status --porcelain -- engine)" ]; then
  echo "engine/ has uncommitted changes; commit them and merge to main first" >&2; exit 1
fi
git -C "$REPO" fetch -q origin main
if ! git -C "$REPO" merge-base --is-ancestor HEAD origin/main; then
  echo "HEAD is not on origin/main; deploy only what has been merged (and passed CI)" >&2; exit 1
fi
EXPORT="$(mktemp -d)"
trap 'rm -rf "$EXPORT"' EXIT
git -C "$REPO" archive HEAD engine | tar -x -C "$EXPORT"
echo "deploying $(git -C "$REPO" rev-parse --short HEAD)"
rsync -rc --delete --exclude /.venv --exclude /data --exclude /evals --exclude __pycache__ --exclude .pytest_cache \
  "$EXPORT/engine/" spark:rrsrch-engine/
ssh spark 'set -e; source $HOME/.local/bin/env; cd ~/rrsrch-engine && uv sync -q --locked
  set -a; . ~/.config/rrsrch/engine.env; set +a
  .venv/bin/python -c "from rrsrch.ledger import db
with db.connect() as c: print(\"migrations:\", db.migrate(c) or \"up to date\")"
  systemctl --user restart rrsrch-serve.service
  install -m 644 deploy/spark/rrsrch-indexnow.service deploy/spark/rrsrch-indexnow.timer ~/.config/systemd/user/
  install -m 644 deploy/spark/rrsrch-xweekly.service deploy/spark/rrsrch-xweekly.timer ~/.config/systemd/user/
  install -m 644 deploy/spark/rrsrch-benchmarks.service deploy/spark/rrsrch-benchmarks.timer ~/.config/systemd/user/
  systemctl --user daemon-reload && systemctl --user enable -q --now rrsrch-indexnow.timer rrsrch-benchmarks.timer
  for i in $(seq 1 20); do curl -sf http://127.0.0.1:8787/v1/health && echo && break; sleep 1; done'
if [ "${1:-}" = "--reader" ]; then ssh spark 'systemctl --user restart rrsrch-reader.service && echo "reader restarted"'; fi
