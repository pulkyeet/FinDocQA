PY ?= python3

.PHONY: eval fetch chunk embed clean-results test delta delta-batch delta-no-llm web

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
