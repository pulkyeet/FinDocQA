# Deploying FinDocQA Delta (static, Fly.io)

The web app serves **pre-built** change reports as static HTML. The report
pipeline (torch, chromadb, sentence-transformers, LLM calls) runs **offline**,
not in the deployed image. This keeps the image small (~200MB), needs no runtime
secrets, and has no cold-start model download.

## What ships

| Piece | Role |
|---|---|
| `Dockerfile` | Slim `python:3.11-slim` image; installs `requirements-web.txt` (FastAPI/uvicorn/jinja2/dotenv only), copies `src/` incl. baked `src/data/reports/*.html` |
| `requirements-web.txt` | Runtime deps only — **not** the full `requirements.txt` |
| `fly.toml` | Dockerfile build, no volume, no secrets, `min_machines_running = 0` (cold-starts on first hit) |
| `src/data/reports/*.html` | The baked reports (gitignored, but included in the Fly build context via `.dockerignore`) |

`/api/trigger` is intentionally inert in this deploy — it only reports readiness;
it does not run the pipeline (no pipeline deps in the image).

## 1. Build / refresh the reports (offline)

Reports must exist on disk before deploying — the Docker build copies them in.
Needs `OPENROUTER_API_KEY` in `src/.env`.

```bash
make delta-batch            # all 7 tickers -> src/data/reports/*.html + index.html
# or a single ticker:
make delta TICKER=MSFT YEARS=5
```

## 2. Smoke-test locally

```bash
make web                    # http://localhost:8000  (/, /report/MSFT)
```

## 3. Deploy

```bash
flyctl auth login           # once
flyctl deploy               # builds the Dockerfile image and ships it
```

Because reports are gitignored, deploy **from a checkout that has the built
reports on disk** (i.e. right after step 1). `flyctl deploy` tars the working
directory honoring `.dockerignore`, so the reports get baked into the image.

## Updating reports later

Rebuild (step 1) and redeploy (step 3). There is no volume and nothing to
migrate — each deploy is a fresh, self-contained image.

## Notes / trade-offs

- **No live generation.** Visitors get the 7 pre-built Mag-7 reports; other
  tickers show a "not published" page. To offer live generation you'd need the
  full image + a Fly volume + secrets + an async job runner (deferred).
- **Reproducibility.** Reports are not in git (data/ is gitignored). If you want
  a clone-and-deploy that doesn't require rebuilding, commit `src/data/reports/`
  or attach them to a release artifact.
