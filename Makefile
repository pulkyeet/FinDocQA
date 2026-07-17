PY ?= python3

.PHONY: eval fetch chunk embed clean-results test

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
