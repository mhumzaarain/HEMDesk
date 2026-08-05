# Deployment

HEMDesk ships with a small `cli.py` wrapper around Docker
Compose and Docker Swarm — one place for the dev and operator workflows. Run
`uv run cli.py --help` for the full command list.

| | Development | Production |
| --- | --- | --- |
| Web server | Django `runserver`, hot-reloading | nginx :8080 → gunicorn |
| Orchestrator | `docker compose` (`uv run cli.py compose-up`) | Docker Swarm, single node (`uv run cli.py stack-deploy`) |
| App port | `:8000` | `:8080` |
| Database port | published on `:5432` (dev override) | not published |

## Development

```bash
uv run cli.py init-workspace   # one time: creates .env with generated secrets
uv run cli.py compose-up       # -d to run detached
```

This starts `db`, `ollama` (+ a one-shot `ollama-init` that pulls the chat and
embedding models), and `runserver` on hot-reloading `:8000`. The `worker`
service (Procrastinate) does **not** autoreload — after changing
background-task code, restart it:

```bash
uv run cli.py restart worker
```

`compose-down` stops the stack. Running Django directly on the host (against
a Dockerized Postgres) is still a valid alternative — see
[Setup & contributing](setup.md).

## Production (single node)

Production runs on Docker Swarm rather than plain Compose, so the same
compose files describe both a local dev stack and a deployable stack. One
node is all the current setup supports.

**One-time setup:**

```bash
docker swarm init
```

Set `ENVIRONMENT=production` in `.env` (this is what makes `cli.py` refuse
`compose-up`/`compose-down` and require Swarm instead).

Also set `ALLOWED_HOSTS` and `CSRF_TRUSTED_ORIGINS` in `.env` for the
hostname users will actually browse to. `CSRF_TRUSTED_ORIGINS` needs the
scheme and port, e.g. `http://cmms.hospital.local:8080` — the localhost
defaults only work for local testing.

**Deploy:**

```bash
uv run cli.py compose-build   # build the production images
uv run cli.py stack-deploy    # deploy to the swarm
```

`stack-deploy` refuses to run unless `ENVIRONMENT=production`, checks that no
`.env` value is quoted (Swarm passes env values to containers verbatim,
quotes included, so a quoted value would end up literally in the app), and
checks that Swarm is active on the node before deploying.

**Env values are baked in at deploy time**, not read live from `.env` by the
running containers — Swarm bakes the values passed to `docker stack deploy`
into the service specs. After editing `.env`, re-run `stack-deploy` to pick
the changes up.

**Upgrades:**

```bash
git pull
uv run cli.py compose-build
uv run cli.py stack-deploy
```

> Swarm configs are immutable — if `nginx.conf` changed since the last
> deploy, `stack-deploy` will fail to update it in place. Run
> `uv run cli.py stack-rm` first, then `stack-deploy`.

If any manuals show keyword search only, run the backfill once:

```bash
uv run cli.py manage reembed_manuals
```

**Operating the stack:**

```bash
uv run cli.py logs web          # tail a service's logs (default: web)
uv run cli.py shell             # Django shell in the running web container
uv run cli.py manage <args>     # any manage.py command, e.g. createsuperuser
uv run cli.py db-backup         # pg_dump to backups/hemdesk-<date>.dump
uv run cli.py db-restore FILE --yes   # DESTRUCTIVE — replaces current data
uv run cli.py stack-rm          # remove the stack
```

The production database port is deliberately not published — the dev
override (`docker-compose.dev.yml`) adds `5432:5432` for local tooling; the
base file, which production deploys unmodified, does not expose it.

TLS termination is the operator's responsibility; nginx serves plain HTTP on `:8080`.
