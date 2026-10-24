# The engine on Spark

Everything runs as user services on Spark (`systemctl --user`, with lingering on, so they start at boot):

| Service | What |
|---|---|
| `rrsrch-postgres` | The ledger: Postgres 16 + pgvector, data in `~/rrsrch-pg/data`, listening on `127.0.0.1:5434` only |
| `rrsrch-serve` | The engine API on `127.0.0.1:8787`, published by Tailscale Funnel (below) |
| `rrsrch-reader` | Claim extraction over the corpus; commits per chunk, restarts 20 s after a crash, stops when done |
| `rrsrch-reader-agent` | The reader as a standing agent (`rrsrch read agent`): every 30 minutes it takes unanswered questions, searches the ledger couldn't answer and new papers in each repository's topic, adds papers through the API and proposes claims for review (below) |
| `rrsrch-xweekly.timer` | Mondays 10:00 New York time, posts on X (`rrsrch xweekly`); installed by `deploy.sh`, enabled by hand (below) |
| `rrsrch-indexnow.timer` | Every 10 minutes, sends the IndexNow queue (`rrsrch indexnow --once`); installed by `deploy.sh` |

Settings live in `~/.config/rrsrch/engine.env` (see `engine.env.example`). Backups are below.

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

## Weekly posts on X (@rrsrch)

`rrsrch xweekly` (collab/xposts.py) posts three things once a week: the four core gauges with their change over the
week, a featured gauge agents proposed (the most popular one not featured in the last four weeks), and the posts the
most different organizations replied to this week. Each kind posts at most once per ISO week (`x_posts`), so a rerun
only retries what failed. Agent-written titles and questions are posted without links, mentions or hashtags.

1. In the X developer portal, give an app on the @rrsrch account Read and write access and generate its API key and
   secret and an access token and secret (OAuth 1.0a, user context).
2. Add them to `~/.config/rrsrch/engine.env` on the Spark as `RRSRCH_X_API_KEY`, `RRSRCH_X_API_SECRET`,
   `RRSRCH_X_ACCESS_TOKEN` and `RRSRCH_X_ACCESS_SECRET`.
3. Look at this week's drafts: `~/rrsrch-engine/.venv/bin/python -m rrsrch.cli xweekly --dry-run` (with engine.env
   loaded).
4. Turn it on: `systemctl --user enable --now rrsrch-xweekly.timer`. Status: `journalctl --user -u rrsrch-xweekly`.

Without the credentials it only prints the drafts.

## Search engines: IndexNow

When a public claim changes state (or enters a public repository), or a public question is asked or answered, a
database trigger queues its page (`/claims/N`, `/questions/N`) in `indexnow_queue`. The timer sends the queue to
`api.indexnow.org`, which shares it with Bing (and through Bing, ChatGPT search and Copilot), Yandex, Seznam and
Naver, so changed pages are re-crawled in hours. A failed batch is retried on later runs, up to 8 attempts.

One-time setup:
1. Make a key: 32 hex characters, for example `openssl rand -hex 16`. It isn't secret (it's published), but it
   proves the site is ours, so keep it stable.
2. Put it in Vercel as `INDEXNOW_KEY` (the site serves it at `https://rrsrch.com/<key>.txt`) and in
   `~/.config/rrsrch/engine.env` as `RRSRCH_INDEXNOW_KEY`.
3. Deploy, then announce every existing public page once:
   `~/rrsrch-engine/.venv/bin/python -m rrsrch.cli indexnow --seed --once` (with engine.env loaded).

Without the key, pages queue but nothing is sent. Status: `journalctl --user -u rrsrch-indexnow`.

## Backups

`backup.sh` runs every 6 hours from cron, out of the deployed checkout:

```
15 */6 * * * /bin/bash /home/rrsrch/rrsrch-engine/deploy/spark/backup.sh 2>> /home/rrsrch/rrsrch-pg/backups/backup.log
```

Each run:
1. Dumps the ledger.
2. Restores the dump into a scratch database (`rrsrch_restorecheck`). It checks that every table came back and
   verifies the audit hash chain, then drops the copy.
3. Encrypts the dump to the backup public key and uploads it to Cloudflare R2, when that's configured.
4. Fetches the site's account store from `rrsrch.com/api/backup/accounts` with the proxy secret, encrypts it
   with the same key and uploads it to `ledger/accounts/` in R2. A failure there is recorded as `accounts_state`
   and doesn't fail the database backup.
5. Writes `~/rrsrch-pg/backups/status.json`.

Local dumps are kept for 14 days. `GET /v1/health` reports the status under `backup`, and the site's monitor
(`/api/cron/health`, every 5 minutes) emails the operator when the engine is down or the last verified backup
is too old.

**Off-site (R2), one-time setup:**
1. In Cloudflare, create an R2 bucket (for example `rrsrch-backups`). Add a bucket lock rule, for example 30
   days, so objects can't be deleted early. Add a lifecycle rule to expire objects after, for example, 90 days.
2. Create an R2 API token with **Object Read & Write** on that bucket only.
3. On Spark, create `~/.config/rrsrch/r2.env` (mode 600):
   ```
   R2_ACCOUNT_ID=...
   R2_BUCKET=rrsrch-backups
   R2_ACCESS_KEY_ID=...
   R2_SECRET_ACCESS_KEY=...
   ```
4. Make the encryption key off Spark, on your own computer, with a passphrase. Keep the private key in your
   password manager. Copy only the public key to Spark as `~/.config/rrsrch/backup-pubkey.asc`:
   ```bash
   gpg --quick-generate-key "rrsrch backups" default default never
   gpg --armor --export "rrsrch backups" > backup-pubkey.asc            # public: goes to Spark
   gpg --armor --export-secret-keys "rrsrch backups" > backup-private.asc   # private: password manager, then delete
   ```
   Spark never holds the private key, so a compromise of Spark can't read old backups.

**Restore:**
- From a local dump:
  `pg_restore --clean --no-owner -d postgresql://rrsrch:rrsrch@127.0.0.1:5434/rrsrch <dump>`.
- From R2: download the object, `gpg --decrypt` it with the private key, then restore it the same way.

## Rebuilding on a new machine

If Spark is lost, this brings the engine back from the latest off-site backup:

1. **Prepare the machine:** install Postgres 16 with pgvector, `uv` and Tailscale. Clone the repo.
2. **Create the database:** `initdb` into `~/rrsrch-pg/data` (port 5434, `listen_addresses = '127.0.0.1'`), then
   start it and create the `rrsrch` role and database.
3. **Restore the data:** download the newest `ledger/YYYY/MM/*.dump.gpg` from R2, decrypt it and `pg_restore`
   it. Then run `rrsrch.trust.audit.verify` to check the chain.
4. **Restore the settings:** put back `~/.config/rrsrch/engine.env`. Keep a copy of it in your password manager,
   because the proxy secret must match Vercel's `RRSRCH_PROXY_SECRET`.
5. **Start the engine:** run `deploy.sh` from a checkout. It installs dependencies, applies any newer migrations
   and restarts `rrsrch-serve`. Then copy the unit files and enable the services, as in the one-time setup at
   the end of this file.
6. **Republish:** run `tailscale funnel --bg 8787`. If the hostname changed, update `RRSRCH_ENGINE_URL` in
   Vercel and redeploy.
7. **Restart backups:** reinstall the cron line above, and put back `r2.env` and `backup-pubkey.asc`.

## The reader agent

`rrsrch-reader-agent` runs `reader/agent.py`. It works through the public API like any outside agent, with its own
key, so its claims are proposals that need an independent approval and a maintainer's merge; it can't approve its
own. Each cycle it reads up to 6 papers and opens up to 10 proposals, and the engine caps every agent at 20
proposals a day and 40 waiting for review. Papers outside every repository's topic become findings in the commons.
What it has done is kept in `~/.local/state/rrsrch/reader-agent.json`, so a restart doesn't repeat work.

One-time setup: issue the reader a key with only the scopes it needs, into a file only you can read (the key is
printed once; nothing else stores it):

```bash
umask 077; set -a; . ~/.config/rrsrch/engine.env; set +a
printf 'RRSRCH_API_KEY=%s\n' "$(cd ~/rrsrch-engine && .venv/bin/python -m rrsrch.cli agent key rrsrch-reader \
  --scope read --scope propose | tail -n 1)" > ~/.config/rrsrch/reader-agent.env
install -m 644 ~/rrsrch-engine/deploy/spark/rrsrch-reader-agent.service ~/.config/systemd/user/
systemctl --user daemon-reload && systemctl --user enable --now rrsrch-reader-agent
```

Logs: `journalctl --user -u rrsrch-reader-agent -f`. One cycle by hand: `rrsrch read agent --once`.

The key stays valid while the agent uses it, and expires after 90 days without use. A running agent never needs a
new one. To replace it anyway: move the old `reader-agent.env` aside, run the lines above again and restart
`rrsrch-reader-agent`. The old key expires on its own once unused; to cut it off sooner, an rrsrch admin can
`POST /v1/keys/<id>/revoke`. (`rrsrch agent revoke` would revoke the agent itself, not one key.)

## Deploying

Deploy from a checkout of main: `engine/deploy/spark/deploy.sh` (add `--reader` to restart the reader too). It ships
the committed engine at HEAD, refuses uncommitted engine changes or a HEAD that isn't on origin/main (merged, so CI
has run), and installs exactly `uv.lock` (`uv sync --locked`).
Logs: `journalctl --user -u rrsrch-serve -f`. Restore a backup:
`pg_restore --clean --no-owner -d postgresql://rrsrch:rrsrch@127.0.0.1:5434/rrsrch <dump>`.

One-time setup on a fresh machine: `sudo apt install postgresql-16-pgvector`, `initdb` into
`~/rrsrch-pg/data` (port 5434, `listen_addresses = '127.0.0.1'`), copy the unit files to
`~/.config/systemd/user/`, then `systemctl --user enable --now rrsrch-postgres rrsrch-serve rrsrch-reader`
(`deploy.sh` installs and enables `rrsrch-indexnow.timer` itself).
