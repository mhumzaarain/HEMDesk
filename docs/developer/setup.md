# Setup & contributing

## Quick start

Requires [uv](https://docs.astral.sh/uv/) and Docker.

```bash
uv sync
uv run cli.py init-workspace   # creates .env with generated secrets
uv run cli.py compose-up       # db, ollama (models auto-pull), hot-reloading app on :8000
```

`init-workspace` refuses to run if `.env` already exists. `compose-up` starts
the whole dev stack in Docker — see [Deployment](deployment.md) for what's
running and how to work with it (restarting the worker, running commands
inside a container, and so on).

Prefer running Django directly on the host, against a Dockerized Postgres
only? That's still supported:

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml -p hemdesk up -d db
uv run python manage.py migrate
uv run python manage.py seed_demo   # optional demo data + accounts
uv run python manage.py runserver
```

## Checks

- Tests: `uv run cli.py test` (or `uv run pytest`; needs the database
  container running)
- Lint: `uv run cli.py lint`
- Format: `uv run cli.py format`
- Docs: `uv run mkdocs serve`

## Conventions

For coding conventions and the pull request process, see [CONTRIBUTING.md on GitHub](https://github.com/mhumzaarain/HEMDesk/blob/main/CONTRIBUTING.md).
