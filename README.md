# Altinn app insight

Query Altinn app configurations in tt02 and prod

## Requirements

- [uv](https://github.com/astral-sh/uv)
  - Mac: `brew install uv`
  - Others: See [installing uv](https://github.com/astral-sh/uv?tab=readme-ov-file#installation).

## Getting started

1. Clone the repo: `git clone --depth 1 https://github.com/bjosttveit/altinn-app-insight.git`
2. Copy the `keys.template.json` and name it `keys.json`
3. Go to <https://altinn.studio/repos/user/settings/applications> and generate a token with permissions `repository`: `Read`. Add the key to the `keys.json` file
    - Optionally generate tokens in other studio environments like `dev` and `staging`
4. Run `make download` or `uv run download.py` to download deployed apps locally
5. Run `make run` or `uv run --env-file .env jupyter lab` to launch JupyterLab
