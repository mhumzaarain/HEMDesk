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

## Two ways to run the app in development

Both serve the **same app against the same database** — the difference is
only where the Django process runs. You can switch between them any time.

### Option A — everything in Docker

```bash
uv run cli.py compose-up
```

Django (hot-reloading), the background worker, and Ollama all run as
containers; code edits reload automatically. App on <http://127.0.0.1:8000>.

**When to use it:** everyday development. One command, nothing else to
manage, and every feature works out of the box — background jobs, AI
assistant, model auto-download.

### Option B — Django on your machine, infrastructure in Docker

```bash
uv run cli.py compose-up -d db ollama   # just the infrastructure
uv run python manage.py migrate
uv run python manage.py seed_demo       # optional demo data + accounts
uv run python manage.py runserver
```

Same app, same URL, same data.

**When to use it:** when you want your IDE's debugger attached to the
Django process — breakpoints, step-through, profiling — or you're iterating
on something where running Python directly feels quicker.

Two things to know in this mode:

- Background jobs (assistant answers, report generation, manual indexing)
  are processed by the worker, which isn't running yet — start it in a
  second terminal when you need those features:
  `uv run python manage.py procrastinate worker`
- Model downloads still happen automatically: add `ollama-init` to the
  `compose-up` line (or run the full stack once) to pull the AI models.

## Checks

- Tests: `uv run cli.py test` (or `uv run pytest`; needs the database
  container running)
- Lint: `uv run cli.py lint`
- Format: `uv run cli.py format`
- Docs: `uv run mkdocs serve`

## Conventions

For coding conventions and the pull request process, see [CONTRIBUTING.md on GitHub](https://github.com/mhumzaarain/HEMDesk/blob/main/CONTRIBUTING.md).
