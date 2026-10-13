# RRSRCH

**Evidence engine + site for regenerative research.**  
Live at [rrsrch.com](https://rrsrch.com). Research tool only — not medical advice.

This monorepo holds both halves of the product:

| Path | What |
|------|------|
| **`engine/`** | Local-first evidence engine (claim ledger, reader, skeptic, `rrsrch serve`) |
| **`rrsrch-react/`** | Site UI (Main \| Web \| Literature search) |
| **`server.js`** + **`api/`** | Express / Vercel API (web, literature, engine proxy) |

## Quick start — site

```bash
npm install
cd rrsrch-react && npm install && cd ..
# API (default :3001) + CRA proxy
PORT=3001 node server.js
# in another terminal:
cd rrsrch-react && npm start
```

Set in `.env` (never commit):

- `BRAVE_SEARCH_API_KEY` or `SERPER_API_KEY` — open web
- `RRSRCH_ENGINE_URL` — e.g. `http://127.0.0.1:8787` when the engine is serving
- Optional: `SEMANTIC_SCHOLAR_API_KEY`

## Quick start — engine

```bash
cd engine
uv sync
docker compose up -d          # Postgres + pgvector
uv run rrsrch serve --port 8787
```

See [`engine/README.md`](engine/README.md) for corpus, reader, skeptic, and the citation gate.

## Product shape

1. **Main** — holistic answer (gated ledger when the engine is connected)
2. **Web** — open web (Brave / Serper)
3. **Literature** — Europe PMC · OpenAlex · Semantic Scholar · ClinicalTrials.gov

Trust layers stay labeled. The ledger is not the same as open web or literature search.
