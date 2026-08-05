🚧 Work in Progress: This repository is currently under development. Expect incomplete features, breaking changes, and ongoing updates

# Biomedical CMMS

Hospital Medical Equipment Management System — track medical equipment and
manage malfunction complaints and repairs. A complete, server-rendered
Django CMMS.

Everything related to hospital medical equipment lives here, in one place:

- **Equipment management** — a searchable registry of every device; register
  one at a time or bulk-import from Excel/CSV, edit, and condemn end-of-life
  equipment.
- **Accessory management** — accessory types and stock levels, attaching
  accessories to devices, and handling accessory faults and replacements.
- **Complaints & repairs** — ward staff lodge complaints, engineers work them
  through a live queue and work orders, and reporters confirm the fix.
- **Preventive maintenance** — PPM schedules per device with a due list so
  nothing gets missed.
- **Dashboard & reports** — 30-day KPIs, downtime and fault trends, and
  downloadable reports.

**📚 Full documentation:** https://mhumzaarain.github.io/HEMDesk/ (user guide + developer overview).

## Screenshots

![Home screen with role cards](docs/assets/landing-page.png)

![Dashboard with KPI tiles, charts, and panels](docs/assets/dashboard.png)

![Equipment Registry with live search and status filters](docs/assets/equipment-list.png)

![Complaint queue with Open WO / Close actions](docs/assets/complaint-queue.png)

<!-- screenshot: docs/assets/workorder-detail.png -->

## Stack

Django 5.2 · PostgreSQL · HTMX + Alpine.js + Chart.js + Tailwind ·
Procrastinate (Postgres task queue) · uv for dependency management.

## Local development

See the [setup guide](https://mhumzaarain.github.io/HEMDesk/developer/setup/) for prerequisites and contributing details.

```bash
docker compose up -d db          # start Postgres
uv sync                          # create .venv and install deps (incl. dev)
uv run python manage.py migrate
uv run python manage.py seed_demo   # optional: 90 days of demo data
uv run python manage.py runserver
```

## AI features (upcoming)

The app talks to any OpenAI-compatible LLM endpoint — pick one via `.env`:

| Setup | .env |
|---|---|
| Bundled Ollama container (default) | nothing to change |
| Own vLLM server | `LLM_BASE_URL=http://your-host:8000/v1`, `LLM_MODEL=...` |
| Hospital LLM gateway | `LLM_BASE_URL=https://llm.hospital.example/v1`, `LLM_API_KEY=...` |

Service-manual search and the assistant's past-repair context also use an
embedding backend, configured the same way via `EMBEDDING_BASE_URL` /
`EMBEDDING_MODEL` (e.g. a vLLM server serving `Qwen/Qwen3-Embedding-4B`).
`EMBEDDING_DIM` (default 768) is coupled to the database schema — changing it
requires a new migration and re-running `manage.py reembed_manuals`.

First start with the bundled container, pull the default models once:

    docker compose up -d ollama
    docker compose exec ollama ollama pull llama3.2:3b
    docker compose exec ollama ollama pull nomic-embed-text

Everything degrades gracefully with no LLM: reports generate without the
narrative, risk scores compute without explanations, and manual search falls
back to keyword-only without embeddings.

Privacy note: prompts include complaint and remark free-text, engineers'
assistant questions and chat history, service-manual excerpts, and device
details (serial number, department). Assistant questions are also sent to the
embedding endpoint. The default bundled Ollama runs locally, so nothing
leaves your deployment — but if you point `LLM_BASE_URL` or
`EMBEDDING_BASE_URL` at an external endpoint, all of that is sent there.

## Demo accounts & login

**All demo accounts share one password** — `demo1234` by default, overridable
via `DEMO_PASSWORD` in `.env` before running `seed_demo`; change it before any
real deployment.

| Username | Role | Sees |
| --- | --- | --- |
| `admin` | Admin | Everything, plus the Django admin at `/admin/` |
| `engineer1`, `engineer2`, `engineer3` | Engineer | Queue, work orders, dashboard, equipment |
| `staff1` … `staff10` | Staff | Lodge and view their own complaints |

## Full stack (Docker)

```bash
cp .env.example .env
docker compose up --build        # nginx :8080 -> gunicorn, worker, postgres
docker compose exec web python manage.py seed_demo
```

## Production: real user accounts

Demo accounts (`seed_demo` / `DEMO_PASSWORD`) are throwaway fixtures. Real
accounts are **never** stored in `.env` — they live in the database (passwords
hashed) and are created inside the app.

1. **Create the first admin** (one time), either:
   - Interactive (standard): `python manage.py createsuperuser` — prompts for
     the credentials; nothing is written to a file.
   - Automated/container: set `SUPERUSER_*` in your private `.env` (see
     `.env.example`) and run `python manage.py create_superuser`. It is
     idempotent — safe to run on every deploy; it skips if a superuser already
     exists or the variables are unset. Use `--force` to reset the password.
2. **Create every other user** via the Django admin at `/admin/` — set each
   person's username, role, employee ID, and an initial password.
3. **Each user changes their own password** at `/accounts/password_change/`
   (the "Change password" link in the top nav). Admins can also reset a
   password from `/admin/`.

So `.env` holds infrastructure config plus (optionally) the single bootstrap
admin password; all real people are managed in the app.

## Docs

**📚 Full documentation:** https://mhumzaarain.github.io/HEMDesk/

Internal design specs, implementation plans, and deferred-work notes are
intentionally kept out of `main` and live under `docs/superpowers/` and
`docs/FOLLOWUPS.md` on the `feature/accessory-replacement` branch
(maintainers only).

## License

Copyright (C) 2026 Muhammad Humza Arain

This project is licensed under the **GNU Affero General Public License v3.0**
(AGPL-3.0). You may use, modify, and distribute it under the terms of that
license; if you run a modified version as a network service, you must make the
complete corresponding source code available to its users. See the
[`LICENSE`](LICENSE) file for the full text.
