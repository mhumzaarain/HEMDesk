# Setup & contributing

## Quick start

Requires [uv](https://docs.astral.sh/uv/) and Docker.

**Step 1 — set up and start the app.** In your first terminal:

```bash
uv sync
uv run cli.py init-workspace   # creates .env with generated secrets
uv run cli.py compose-up       # db, ollama (models auto-pull), app on :8000
```

Leave this running. It stays in the foreground and prints the app's logs.

**Step 2 — create the accounts.** The stack is up but has no users yet, so
nobody can log in. Open a **second terminal** and run:

```bash
uv run cli.py manage seed_demo
```

**Step 3 — log in.** Open <http://127.0.0.1:8000> and sign in as **`admin`**.

**The password is in your `.env` file, on the `DEMO_PASSWORD` line.**
`init-workspace` generates a random one, so open `.env` and copy it. To use a
password you pick yourself, edit `DEMO_PASSWORD` in `.env` *before* step 2.

`init-workspace` refuses to run if `.env` already exists. `compose-up` starts
the whole dev stack in Docker — see [Deployment](deployment.md) for what's
running and how to work with it (restarting the worker, running commands
inside a container, and so on).

## The demo accounts

`seed_demo` creates a full demo world — equipment, complaints, work orders,
PPM schedules — plus these accounts, which all share the `DEMO_PASSWORD` from
your `.env`:

| Username | Role | What it's for |
| --- | --- | --- |
| `admin` | Admin | The whole app, plus the Django admin at `/admin/` |
| `engineer1`, `engineer2`, `engineer3` | Biomedical Engineer | Queue, work orders, dashboard |
| `staff1` … `staff10` | Staff | Lodging and tracking their own complaints |

Log in as `admin` to see every sidebar link; the others are there so you can
check how each role's view differs.

!!! note
    `seed_demo` refuses to run if any equipment already exists, so it is a
    one-shot on a fresh database rather than something you re-run. To start
    over, delete the data and seed again:

    ```bash
    docker compose -f docker-compose.yml -f docker-compose.dev.yml -p hemdesk down -v
    uv run cli.py compose-up
    uv run cli.py manage seed_demo
    ```

These accounts are for development only — their password is shared and
well known, so never run `seed_demo` on a real deployment. Production creates
its admin a different way; see
[Deployment](deployment.md#create-the-first-admin-account).

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
uv run python manage.py seed_demo       # demo data + accounts (needed to log in)
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
