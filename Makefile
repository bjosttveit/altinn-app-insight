.PHONY: download
download:
	uv run download.py

.PHONY: download-retry-failed
download-retry-failed:
	uv run download.py --retry-failed

.PHONY: install
install:
	uv sync

.PHONY: build
build: install
	uv pip install --reinstall .

.PHONY: run
run: build
	uv run --env-file .env jupyter lab 

.PHONY: run-debug
run-debug: build
	uv run --env-file .env jupyter lab --debug

.PHONY: format
format:
	uvx black .

.PHONY: clear
clear:
	uv run clear_state.py
