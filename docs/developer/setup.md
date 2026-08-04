# Setup & contributing

## Quick start

Requires [uv](https://docs.astral.sh/uv/) and Docker (for Postgres).

```bash
docker compose up -d db
uv sync
uv run python manage.py migrate
uv run python manage.py seed_demo   # optional demo data + accounts
uv run python manage.py runserver
```

## Checks

- Tests: `uv run pytest` (needs the database container running)
- Lint: `uv run ruff check .`
- Docs: `uv run mkdocs serve`

## Conventions

For coding conventions and the pull request process, see [CONTRIBUTING.md on GitHub](https://github.com/mhumzaarain/HEMDesk./blob/main/CONTRIBUTING.md).
