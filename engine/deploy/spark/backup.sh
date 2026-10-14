#!/bin/bash
# Ledger backup, every 6 hours from cron (see README.md). Each run:
#
#   1. dumps the ledger (pg_dump, custom format)
#   2. proves the dump restores: restores it into a scratch database, checks every table came back with no more
#      rows than the live one holds, and verifies the audit hash chain on the restored copy
#   3. encrypts it to the backup public key (gpg; the private key is NOT on this machine) and uploads it to
#      Cloudflare R2, when ~/.config/rrsrch/r2.env and the public key are present
#   4. keeps 14 days of local dumps, and writes ~/rrsrch-pg/backups/status.json, which GET /v1/health reports
#      and the site's monitor alerts on
#
# A failed step leaves status.json saying which one, with the last good times intact, and exits non-zero.
set -euo pipefail
umask 077
export PGOPTIONS="--client-min-messages=warning"

DIR="$HOME/rrsrch-pg/backups"
CONF="$HOME/.config/rrsrch"
DB="postgresql://rrsrch:rrsrch@127.0.0.1:5434"
LIVE="$DB/rrsrch"
SCRATCH_NAME="rrsrch_restorecheck"
ENGINE="$HOME/rrsrch-engine"
STATUS="$DIR/status.json"
mkdir -p "$DIR"
exec 9>"$DIR/.lock"
flock -n 9 || { echo "$(date -Is) another backup is running" >> "$DIR/backup.log"; exit 0; }

STAMP="$(date +%Y-%m-%dT%H%M)"
OUT="$DIR/rrsrch-$STAMP.dump"
STEP="start"

status() {   # status <ok|failed> [error]: merge into status.json, keeping earlier good times
  local prev='{}'
  [ -f "$STATUS" ] && prev="$(cat "$STATUS")"
  jq -n --argjson prev "$prev" --arg state "$1" --arg error "${2:-}" --arg step "$STEP" --arg at "$(date -Is)" \
        --arg dump "$(basename "$OUT")" --arg size "$(stat -c %s "$OUT" 2>/dev/null || echo 0)" \
        --arg verified "${VERIFIED_AT:-}" --arg offsite "${OFFSITE_AT:-}" --arg offsite_state "${OFFSITE_STATE:-}" \
        --arg rows "${ROWS:-0}" '
    $prev + {last_run_at: $at, last_state: $state, last_step: $step, last_error: $error}
    + (if $state == "ok" then {last_ok_at: $at, last_dump: $dump, last_dump_bytes: ($size|tonumber),
                               last_rows: ($rows|tonumber)} else {} end)
    + (if $verified != "" then {last_verified_at: $verified} else {} end)
    + (if $offsite != "" then {last_offsite_at: $offsite} else {} end)
    + (if $offsite_state != "" then {offsite: $offsite_state} else {} end)' > "$STATUS.tmp"
  mv "$STATUS.tmp" "$STATUS"
}
fail() {
  trap - ERR
  psql -q "$DB/postgres" -c "DROP DATABASE IF EXISTS $SCRATCH_NAME WITH (FORCE)" >/dev/null 2>&1 || true
  rm -f "$OUT.gpg" "$OUT.partial"
  status failed "$1"
  echo "$(date -Is) backup FAILED at $STEP: $1" >> "$DIR/backup.log"
  exit 1
}
trap 'fail "unexpected error (line $LINENO)"' ERR

# 1. dump
STEP="dump"
pg_dump -Fc --no-owner "$LIVE" > "$OUT.partial"
mv "$OUT.partial" "$OUT"

# 2. restore into scratch and check it
STEP="restore-check"
psql -q "$DB/postgres" -c "DROP DATABASE IF EXISTS $SCRATCH_NAME WITH (FORCE)" -c "CREATE DATABASE $SCRATCH_NAME"
pg_restore --no-owner --exit-on-error -d "$DB/$SCRATCH_NAME" "$OUT" 2>"$DIR/.restore.err" \
  || fail "pg_restore failed: $(head -c 300 "$DIR/.restore.err")"
TABLES_SQL="SELECT tablename FROM pg_tables WHERE schemaname = 'public' ORDER BY 1"
ROWS=0
for t in $(psql -At "$LIVE" -c "$TABLES_SQL"); do
  restored=$(psql -At "$DB/$SCRATCH_NAME" -c "SELECT count(*) FROM \"$t\"" 2>/dev/null) \
    || fail "table $t is missing from the restored copy"
  live=$(psql -At "$LIVE" -c "SELECT count(*) FROM \"$t\"")
  [ "$restored" -le "$live" ] || fail "table $t restored $restored rows but the live ledger has $live"
  ROWS=$((ROWS + restored))
done
[ "$ROWS" -gt 0 ] || fail "the restored copy is empty"
CHAIN=$(RRSRCH_DATABASE_URL="$DB/$SCRATCH_NAME" "$ENGINE/.venv/bin/python" -c "
from rrsrch.ledger import db
from rrsrch.trust import audit
with db.connect() as c:
    print(len(audit.verify(c)))" 2>"$DIR/.chain.err") || fail "audit check crashed: $(head -c 300 "$DIR/.chain.err")"
[ "$CHAIN" = "0" ] || fail "the restored audit chain has $CHAIN problems"
psql -q "$DB/postgres" -c "DROP DATABASE IF EXISTS $SCRATCH_NAME WITH (FORCE)"
VERIFIED_AT="$(date -Is)"

# 3. encrypt and upload off-site, when configured
STEP="offsite"
OFFSITE_STATE="not configured"
if [ -f "$CONF/r2.env" ] && [ -f "$CONF/backup-pubkey.asc" ]; then
  # shellcheck disable=SC1091
  . "$CONF/r2.env"                                    # R2_ACCOUNT_ID, R2_BUCKET, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY
  export GNUPGHOME="$CONF/gnupg"
  mkdir -p "$GNUPGHOME"
  gpg --batch --quiet --import "$CONF/backup-pubkey.asc" 2>/dev/null
  RECIPIENT=$(gpg --batch --with-colons --import-options show-only --import "$CONF/backup-pubkey.asc" \
              | awk -F: '/^fpr:/ {print $10; exit}')
  gpg --batch --yes --trust-model always --encrypt --recipient "$RECIPIENT" --output "$OUT.gpg" "$OUT"
  KEY="ledger/$(date +%Y/%m)/rrsrch-$STAMP.dump.gpg"
  code=$(curl -sS -o "$DIR/.upload.out" -w '%{http_code}' --max-time 300 \
    --aws-sigv4 "aws:amz:auto:s3" --user "$R2_ACCESS_KEY_ID:$R2_SECRET_ACCESS_KEY" \
    -H "x-amz-content-sha256: UNSIGNED-PAYLOAD" -H "Content-Type: application/octet-stream" \
    --upload-file "$OUT.gpg" "https://$R2_ACCOUNT_ID.r2.cloudflarestorage.com/$R2_BUCKET/$KEY") \
    || fail "upload to R2 could not connect"
  rm -f "$OUT.gpg"
  [ "$code" = "200" ] || fail "R2 refused the upload (HTTP $code): $(head -c 300 "$DIR/.upload.out")"
  OFFSITE_AT="$(date -Is)"
  OFFSITE_STATE="r2:$R2_BUCKET"
fi

# 4. local retention and status
STEP="done"
find "$DIR" -name "rrsrch-*.dump" -mtime +14 -delete
status ok
echo "$(date -Is) backup ok: $OUT ($(stat -c %s "$OUT") bytes, $ROWS rows verified, offsite: $OFFSITE_STATE)" >> "$DIR/backup.log"
