#!/usr/bin/env python3
"""Developer/operator CLI — one place for the docker and dev
workflows. Run `uv run cli.py --help` for the command list."""

import os
import secrets
import shutil
import subprocess
import sys
from datetime import date
from pathlib import Path

import typer

app = typer.Typer(
    context_settings={"help_option_names": ["-h", "--help"]},
    no_args_is_help=True,
)

ROOT = Path(__file__).resolve().parent
STACK_NAME = "hemdesk"
DEV_LAYERING = "-f docker-compose.yml -f docker-compose.dev.yml"
PROD_LAYERING = "-c docker-compose.yml -c docker-compose.prod.yml"


def _run(cmd: str, env: dict | None = None) -> None:
    """Every shell-out goes through here — tests fake it."""
    print(f"$ {cmd}")
    result = subprocess.run(
        cmd, shell=True, cwd=ROOT, env={**os.environ, **(env or {})}
    )
    if result.returncode:
        raise typer.Exit(result.returncode)


def _capture(cmd: str) -> str:
    """Captured shell-out (container lookups) — tests fake it."""
    result = subprocess.run(
        cmd, shell=True, cwd=ROOT, capture_output=True, text=True
    )
    return result.stdout.strip()


def read_env_file() -> dict[str, str]:
    env_path = ROOT / ".env"
    if not env_path.is_file():
        sys.exit("No .env file — run: uv run cli.py init-workspace")
    values: dict[str, str] = {}
    for line in env_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        values[key.strip()] = value.strip()
    return values


def environment() -> str:
    return read_env_file().get("ENVIRONMENT", "development")


def _dev_compose() -> str:
    return f"docker compose {DEV_LAYERING} -p {STACK_NAME}"


def _generate_secret(length: int = 50) -> str:
    chars = "abcdefghijklmnopqrstuvwxyz0123456789!@%^*(-_=+)"
    return "".join(secrets.choice(chars) for _ in range(length))


def _set_env_key(env_path: Path, key: str, value: str) -> None:
    lines = env_path.read_text(encoding="utf-8").splitlines()
    for i, line in enumerate(lines):
        if line.startswith(f"{key}="):
            lines[i] = f"{key}={value}"
            break
    else:
        lines.append(f"{key}={value}")
    env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


@app.command()
def init_workspace():
    """Create .env from .env.example with freshly generated secrets."""
    env_path = ROOT / ".env"
    if env_path.is_file():
        sys.exit(".env already exists — refusing to overwrite it.")
    shutil.copy(ROOT / ".env.example", env_path)
    _set_env_key(env_path, "ENVIRONMENT", "development")
    for key in ("SECRET_KEY", "POSTGRES_PASSWORD", "DEMO_PASSWORD"):
        _set_env_key(env_path, key, _generate_secret())
    print("Initialized .env with generated secrets.")


@app.command()
def compose_up(
    detach: bool = typer.Option(False, "--detach", "-d", help="Run in background"),
):
    """Start the development stack (hot-reloading runserver on :8000)."""
    if environment() == "production":
        sys.exit(
            "compose-up is development-only — this .env says "
            "ENVIRONMENT=production. Use stack-deploy."
        )
    _run(f"{_dev_compose()} up" + (" -d" if detach else ""))


@app.command()
def compose_down():
    """Stop the development stack."""
    if environment() == "production":
        sys.exit("compose-down is development-only. Use stack-rm.")
    _run(f"{_dev_compose()} down")


@app.command()
def compose_build():
    """Build the production images (also the pre-PR smoke build)."""
    environment()  # touch .env so the missing-file hint fires early
    _run(f"docker compose -f docker-compose.yml -p {STACK_NAME} build")


def _quoted_env_keys(values: dict[str, str]) -> list[str]:
    return [
        key
        for key, value in values.items()
        if value and (value[0] in "'\"" or value[-1] in "'\"")
    ]


@app.command()
def stack_deploy():
    """Deploy the production stack to a single-node Docker Swarm."""
    values = read_env_file()
    if values.get("ENVIRONMENT", "development") != "production":
        sys.exit(
            "stack-deploy is production-only — set ENVIRONMENT=production in .env."
        )
    quoted = _quoted_env_keys(values)
    if quoted:
        sys.exit(
            "Quoted values in .env: " + ", ".join(quoted) + ". Swarm passes "
            "env values to containers verbatim (quotes included) — remove them."
        )
    if _capture("docker info --format {{.Swarm.LocalNodeState}}") != "active":
        sys.exit("Docker Swarm is not active on this node — run: docker swarm init")
    _run(
        f"docker stack deploy --detach {PROD_LAYERING} {STACK_NAME}",
        env=values,
    )


@app.command()
def stack_rm():
    """Remove the production stack."""
    _run(f"docker stack rm {STACK_NAME}")


def _find_container(service: str) -> str:
    if environment() == "production":
        sep = "_"
    else:
        sep = "-"
        if service == "web":
            service = "runserver"  # dev stack runs runserver instead of web
    found = _capture(
        f"docker ps -q -f name={STACK_NAME}{sep}{service} -f status=running"
    ).splitlines()
    if not found:
        sys.exit(f"No running {service} container found for stack {STACK_NAME}.")
    return found[0]


@app.command()
def shell():
    """Django shell inside the running web container."""
    _run(f"docker exec -it {_find_container('web')} python manage.py shell")


@app.command(
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True}
)
def manage(ctx: typer.Context):
    """Run a manage.py command inside the running web container."""
    _run(
        f"docker exec -it {_find_container('web')} python manage.py "
        f"{' '.join(ctx.args)}"
    )


@app.command()
def logs(service: str = typer.Argument("web", help="Service name")):
    """Tail a running service's logs."""
    _run(f"docker logs -f --tail 100 {_find_container(service)}")


@app.command()
def db_backup(file: str = typer.Argument(None, help="Target file (default backups/)")):
    """pg_dump the database (works in dev and prod)."""
    values = read_env_file()
    user = values.get("POSTGRES_USER", "cmms")
    database = values.get("POSTGRES_DB", "cmms")
    target = (
        Path(file)
        if file
        else ROOT / "backups" / f"hemdesk-{date.today():%Y-%m-%d}.dump"
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    container = _find_container("db")
    _run(
        f"docker exec {container} pg_dump -U {user} -Fc -f "
        f"/tmp/hemdesk-backup.dump {database}"
    )
    _run(f'docker cp {container}:/tmp/hemdesk-backup.dump "{target}"')
    _run(f"docker exec {container} rm /tmp/hemdesk-backup.dump")
    print(f"Backup written to {target}")


@app.command()
def db_restore(
    file: str,
    yes: bool = typer.Option(False, "--yes", help="Confirm replacing the database"),
):
    """Restore a pg_dump backup (DESTRUCTIVE — replaces current data)."""
    if not yes:
        sys.exit("db-restore replaces the current database. Re-run with --yes.")
    values = read_env_file()
    user = values.get("POSTGRES_USER", "cmms")
    database = values.get("POSTGRES_DB", "cmms")
    container = _find_container("db")
    _run(f'docker cp "{file}" {container}:/tmp/hemdesk-restore.dump')
    _run(
        f"docker exec {container} pg_restore --clean --if-exists "
        f"-U {user} -d {database} /tmp/hemdesk-restore.dump"
    )
    _run(f"docker exec {container} rm /tmp/hemdesk-restore.dump")


@app.command(
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True}
)
def test(ctx: typer.Context):
    """Run the test suite."""
    _run("uv run pytest" + (" " + " ".join(ctx.args) if ctx.args else ""))


@app.command()
def lint():
    """Ruff check."""
    _run("uv run ruff check .")


@app.command()
def format():
    """Ruff format + import sort."""
    _run("uv run ruff format .")
    _run("uv run ruff check . --fix --select I")


if __name__ == "__main__":
    app()
