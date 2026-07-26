# Deploying Delta (static reports, Fly.io)

The web app serves **pre-built** change reports as static HTML. The report
pipeline (torch, chromadb, sentence-transformers, LLM calls) runs **offline**,
never in the deployed image. That keeps the image small (~200MB), needs no
runtime secrets, and means no cold-start model download.

There is **no live generation path in production, by design.** Visitors get the
tickers you have already built; anything else renders a "not published" page.

## TL;DR

```bash
make deploy
```

That runs `rerender-all` (rebuilds every report's HTML from persisted output — no
LLM calls) and then `flyctl deploy`. One-time setup and the reasoning are below.

## What ships

| Piece | Role |
|---|---|
| `Dockerfile` | Slim `python:3.11-slim`; installs `requirements-web.txt`, copies `src/` including the baked `src/data/reports/*.html` |
| `requirements-web.txt` | Runtime deps only (fastapi, uvicorn, jinja2, python-dotenv) — **not** the full `requirements.txt` |
| `fly.toml` | Dockerfile build, `[[vm]]` pinned to 256mb, always-on, no volume, no secrets |
| `.dockerignore` | Drops raw/chunks/chroma/eval/diffs **and `*_variant*.html`** |
| `src/data/reports/*.html` | The baked reports (gitignored, but included in the Fly build context) |

`/api/trigger` is intentionally inert — it reports readiness and returns `501`
for anything unbuilt. Nothing in the templates calls it.

**A/B variants are excluded on purpose.** `app.py` mounts the whole reports
directory at `/reports`, so anything shipped there is publicly fetchable.
`rerender.py --no-item8 --suffix _variantB` output is a local analysis artifact,
so `.dockerignore` drops `src/data/reports/*_variant*.html`. That line sits
*after* the `!src/data/reports/` negation because last match wins.

## The cost invariant — read before editing `fly.toml`

Fly has **no free tier**, but it **does not collect invoices under $5/mo**. This
deploy is built to sit under that line:

| Item | Cost |
|---|---|
| `shared-cpu-1x` / `256mb`, running 24/7 | ~$2.02/mo |
| Outbound transfer (7 reports ≈ 200KB each) | pennies |
| Rootfs (only billed while stopped) | ~$0 |
| **Total** | **~$2/mo → under $5 → not collected** |

Three rules follow, and breaking any one of them starts a real bill:

1. **Keep `[[vm]]` pinned to `256mb`.** Without that block `fly launch` defaults
   to 1GB — $5.92/mo, which crosses the threshold and bills *in full*, not the
   excess. 256mb is ample: the runtime is uvicorn + FastAPI + Jinja2 serving
   pre-built HTML, and idles around 60–90MB.
2. **Never attach a volume, Postgres, or Redis.** Volumes bill regardless of
   machine state. Decline these if `fly launch` offers them.
3. **`min_machines_running = 1` with `auto_stop_machines = false` is
   deliberate.** Always-on is free at this size, so scale-to-zero would buy
   nothing and put a multi-second cold start in front of the first visitor.

Caveat worth knowing: the sub-$5 non-collection is a Fly *policy*, not a
contractual free tier, and it's per-org per-month. Confirm on your first invoice
rather than assuming $0 forever.

## One-time setup

```bash
curl -L https://fly.io/install.sh | sh
```

```bash
flyctl auth login
```

A card is required (Fly may place a pre-auth hold under $10). Don't use prepaid
credits — those have a $25 minimum. On the first `fly deploy`, accept app
creation and **decline** any Postgres/Redis offer.

App names are a global namespace on Fly. `fly.toml` uses `delta-findocqa`
because plain `delta` is long taken; change it if that one is unavailable too.

## Refreshing reports

Reports live in the image, so a stale `src/data/reports/` ships a stale site.
`make deploy` guards against that by rerendering first. Pick the cheapest step
that covers what changed:

| Changed | Command | LLM cost |
|---|---|---|
| Template / CSS | `make rerender-all` | none |
| Narrative prompts | `make narrate-all` | ~6 calls/ticker |
| Adding a ticker or year | `make delta TICKER=X YEARS=5` | full stage 7 |

Then `make deploy`. `rerender.py` rebuilds `index.html` from whichever
`{ticker}.html` files exist, so the index self-corrects — you never hand-edit it.

Adding a ticker means running the pipeline locally and redeploying. There is no
volume and nothing to migrate: each deploy is a fresh, self-contained image.

## Local verification

```bash
make web
```

Serves at `http://localhost:8000` with `--reload`. Note this runs against your
**full** dev environment, so it will not catch a missing entry in
`requirements-web.txt`.

To verify the *deployed* dependency set — the failure mode that actually breaks a
deploy — build a throwaway venv from `requirements-web.txt` alone and run the
container's exact command. Docker Desktop's WSL integration is off on this
machine, and Fly builds remotely anyway, so this is the practical substitute:

```bash
python3 -m venv /tmp/webvenv && /tmp/webvenv/bin/pip install -r requirements-web.txt
```

```bash
cd src && env -u PYTHONPATH /tmp/webvenv/bin/python -m uvicorn web.app:app --port 8011
```

Then check `/`, `/report/AAPL`, `/report/BOGUS` (should be 404), and
`/static/css/tokens.css`. Two things make this work and are easy to break:

- **`config.py` must stay import-light.** It currently needs only `os` +
  `dotenv`. If anything in the `web` import chain reaches a pipeline dependency,
  the container dies on boot while `make web` stays perfectly green.
- **No `PYTHONPATH` is set in the Dockerfile.** It works because uvicorn inserts
  its `--app-dir` (default `.`) into `sys.path`, and `WORKDIR` is `/app/src`.
  Hence `env -u PYTHONPATH` above — otherwise your shell's value masks the bug.

## Notes / trade-offs

- **No live generation.** Offering it would need the full image, a Fly volume,
  runtime secrets, and an async job runner — all deferred, and all of which
  would break the cost invariant above.
- **Reproducibility.** Reports are not in git (`src/data/` is gitignored), so
  deploy from a checkout that has them built on disk. `flyctl deploy` tars the
  working directory honoring `.dockerignore`. A CI-based deploy would ship an
  empty reports directory unless you commit `src/data/reports/` or attach it as
  a release artifact.
