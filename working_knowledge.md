# Working Knowledge

> **Process this file FIRST before doing anything else.** It contains the
> operational habits and shortcuts that make this project fast. The agent
> should re-read it on every new session.

## Always-on habits

### 1. The `opencode serve` shortcut (cut eval cold start from ~5s to ~1s)

`opencode run` by default spawns a new process and loads the model each
call (3–5s cold start). For batch jobs (eval, any test sweep), start the
server once in a separate terminal and use `--attach`:

```bash
# Terminal A — leave running
opencode serve --port 4096

# Terminal B — your actual work
cd /home/pulkyeet/findocQA/FinDocQA
# (The agent should remind you to start the server in another
# terminal before running make eval or any test sweep.)
```

`opencode run` then accepts `--attach http://localhost:4096` and skips
the model load. Saves ~3–4s per LLM call. For the 448-call W2 eval this
shaves roughly 20–30 minutes off total runtime.

**If the agent is about to run `make eval` or any batch LLM test sweep,
it should pause and ask: "Is `opencode serve --port 4096` running in
another terminal? If not, start it there before I proceed."**

### 2. Data layer is gitignored

`data/raw/`, `data/chunks/`, `data/chroma/`, `data/eval/results.csv` are
all gitignored. Re-running `python fetch.py` / `chunk.py` / `embed.py`
rebuilds them from scratch (raw fetches are cached by file existence;
chunk/embed always overwrite). The raw layer is the single source of
truth for reproducibility (plan §2) — never edit a 10-K by hand.

### 3. All scripts run from `src/`

```bash
cd src
python fetch.py
python chunk.py
python embed.py
python -m eval.build_questions
python query.py "..." --strategy ... --model ... --rerank ...
make eval      # from repo root, runs `cd src && python run_eval.py`
```

The `Makefile` lives at the repo root and `cd src` for you.

## Key environment facts

- **Python**: 3.11.9 at `~/.pyenv/versions/3.11.9/`. No requirements.txt —
  read imports for deps (chromadb, sentence-transformers, beautifulsoup4,
  lxml, python-dotenv).
- **Models cached at**: `~/.cache/huggingface/` (HuggingFace download cache;
  first run downloads, subsequent runs are fast).
- **Auth**: `~/.local/share/opencode/auth.json` (shared opencode-go key).
  No env var, no `.env`. If it expires: `opencode auth login` (interactive).
- **HF rate-limit warning**: you'll see *"You are sending unauthenticated
  requests to the HF Hub. Please set a HF_TOKEN to enable higher rate
  limits."* on first model load. It still works without the token; the
  warning is informational. Set `HF_TOKEN` in your shell to silence it.

## Recurring gotchas

- **`opencode run` agent must be `chat`, not `build`.** The default
  `build` agent has bash/read/write tools and will try to call them
  instead of answering. Always `--agent chat`.
- **Chroma batch limit is 5461.** `embed.py` chunks `collection.add()`
  into ≤5000-row batches for this reason (see comment in `embed.py`).
- **E5 models need instruction prefixes.** E5 query strings need
  `"query: "` prefix, document strings need `"passage: "`. BGE does
  not. `embed.py` and `query.py` handle this via `doc_prefix()` /
  `query_prefix()` helpers. If you re-embed or re-query by hand,
  remember the prefix.
- **CrossEncoder reranker is `BAAI/bge-reranker-base`**, not the
  same as the BGE bi-encoder. Different model, loaded on demand in
  `rerank.py:Reranker`.
- **The collection name encodes strategy + model**, e.g.
  `sectionaware__bge-small`. Use `embed.collection_name(strategy, key)`
  to build it. Don't hardcode.
- **Retrieval sends top-5 to the LLM** (`TOP_K_FINAL = 5`) regardless
  of rerank toggle. The rerank toggle changes how those 5 are picked
  (cross-encoder rerank vs raw top-5 from bi-encoder) — it does NOT
  change the context size the LLM sees. This isolates the rerank
  effect.

## Quick verification commands

```bash
# Is the corpus complete? (all 7 filings cached)
ls data/raw/*_10k.html | wc -l   # expect 7

# Are the 4 Chroma collections built?
python -c "import chromadb; c=chromadb.PersistentClient('data/chroma'); print([x.name for x in c.list_collections()])"

# Is the eval set built and schema-valid?
wc -l data/eval/questions.jsonl   # expect 56
python -c "import json; qs=[json.loads(l) for l in open('data/eval/questions.jsonl')]; print(len(qs), 'questions')"

# Latest eval results
ls -lt data/eval/results.csv      # newest at top
head -1 data/eval/results.csv     # column names
```

## When the user asks for a test / verification

Always prefer the cheapest check first (retrieval-only via Python
embedding + chroma, no LLM). Only escalate to a full LLM call when the
user explicitly wants a generated answer. The LLM is the slow part.

If the user is about to run a **batch** LLM test (more than ~5 calls),
remind them: *"Start `opencode serve --port 4096` in a separate
terminal first — it'll cut per-call latency by ~4x."*
