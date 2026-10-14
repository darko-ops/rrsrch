# The engine on Spark

Everything runs as user services on Spark (`systemctl --user`, with lingering on, so they start at boot):

| Service | What |
|---|---|
| `rrsrch-postgres` | The ledger: Postgres 16 + pgvector, data in `~/rrsrch-pg/data`, listening on `127.0.0.1:5434` only |
| `rrsrch-serve` | The engine API on `127.0.0.1:8787`, published by Tailscale Funnel (below) |
| `rrsrch-reader` | Claim extraction over the corpus; commits per chunk, restarts 20 s after a crash, stops when done |

Settings live in `~/.config/rrsrch/engine.env` (see `engine.env.example`). `backup.sh` runs nightly from
cron at 03:15 and keeps 14 days of dumps in `~/rrsrch-pg/backups`.

## Public address: Tailscale Funnel

The API is published at `https://spark-31f4.taila96be2.ts.net` by Tailscale Funnel. That's the only thing
exposed: the ledger (5434) and SSH stay on the machine or the tailnet. The site's `RRSRCH_ENGINE_URL` (Vercel,
production) points there, and MCP clients can use it as `RRSRCH_API_URL`. Funnel's configuration is kept by
`tailscaled`, so it survives reboots.

```bash
tailscale funnel --bg 8787          # publish (once; persists)
tailscale funnel status             # what's public
tailscale funnel --https=443 off    # unpublish
```

One-time setup: install Tailscale, `sudo tailscale up --operator=rrsrch`, enable HTTPS certificates and
Funnel for the tailnet in the admin console.

## Deploying

Deploy from a checkout: `engine/deploy/spark/deploy.sh` (add `--reader` to restart the reader too).
Logs: `journalctl --user -u rrsrch-serve -f`. Restore a backup:
`pg_restore --clean --no-owner -d postgresql://rrsrch:rrsrch@127.0.0.1:5434/rrsrch <dump>`.

One-time setup on a fresh machine: `sudo apt install postgresql-16-pgvector`, `initdb` into
`~/rrsrch-pg/data` (port 5434, `listen_addresses = '127.0.0.1'`), copy the unit files to
`~/.config/systemd/user/`, then `systemctl --user enable --now rrsrch-postgres rrsrch-serve rrsrch-reader`.
