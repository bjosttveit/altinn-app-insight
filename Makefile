.PHONY: download
download:
	uv run download.py

.PHONY: download-retry-failed
download-retry-failed:
	uv run download.py --retry-failed

.PHONY: run
run:
	# uv run jupyter lab ./notebooks --config="./.jupyter/lab/user-settings"
	uv run jupyter lab ./notebooks
