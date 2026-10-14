#!/bin/bash
# Nightly ledger backup: one compressed dump per day, kept for 14 days.
set -euo pipefail
DIR="$HOME/rrsrch-pg/backups"
mkdir -p "$DIR"
OUT="$DIR/rrsrch-$(date +%F).dump"
pg_dump -Fc --no-owner "postgresql://rrsrch:rrsrch@127.0.0.1:5434/rrsrch" > "$OUT.partial"
mv "$OUT.partial" "$OUT"
find "$DIR" -name "rrsrch-*.dump" -mtime +14 -delete
echo "$(date -Is) backup ok: $OUT ($(stat -c %s "$OUT") bytes)" >> "$DIR/backup.log"
