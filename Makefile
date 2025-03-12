.PHONY: download
download:
	uv run download.py

.PHONY: download-retry-failed
download-retry-failed:
	uv run download.py --retry-failed

.PHONY: install
install:
	uv sync
	uv pip install --reinstall .

.PHONY: run
run: install
	uv run --env-file .env jupyter lab 

.PHONY: run-debug
run-debug: install
	uv run --env-file .env jupyter lab --debug

.PHONY: format
format:
	uv run python -m black .
