PY ?= python3

.PHONY: eval fetch chunk embed clean-results test delta delta-batch delta-no-llm \
        web rerender rerender-all narrate narrate-all clean-reports deploy

TICKER ?= AAPL
YEARS ?= 5

eval:
	cd src && $(PY) run_eval.py

fetch:
	cd src && $(PY) fetch.py

chunk:
	cd src && $(PY) chunk.py

embed:
	cd src && $(PY) embed.py

test:
	cd src && PYTHONPATH=. python3 -m unittest discover -s ../tests -v

clean-results:
	rm -f src/data/eval/results.csv src/data/eval/results_prev.csv

delta:
	cd src && $(PY) delta.py $(TICKER) --years $(YEARS)

delta-batch:
	cd src && $(PY) delta.py --all --years $(YEARS)

delta-no-llm:
	cd src && $(PY) delta.py $(TICKER) --years $(YEARS) --no-llm

web:
	cd src && uvicorn web.app:app --reload --port 8000

# Re-render HTML from persisted output — no LLM calls. For template/CSS changes.
rerender:
	cd src && $(PY) rerender.py $(TICKER)

rerender-all:
	cd src && $(PY) rerender.py --quiet

# Recompose chapter prose (~6 LLM calls/ticker), then render. For prompt changes.
narrate:
	cd src && $(PY) rerender.py $(TICKER) --narrate

narrate-all:
	cd src && $(PY) rerender.py --narrate --quiet

clean-reports:
	rm -f src/data/reports/*.html

# Deploy to Fly.io. Reports are baked into the image, so rerender first — a
# stale data/reports/ ships a stale site, and rerender costs no LLM calls.
# Fly builds remotely, so no local Docker daemon is required.
deploy: rerender-all
	flyctl deploy
