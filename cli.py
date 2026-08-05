#!/usr/bin/env python3
"""Developer/operator CLI (RADIS-style) — one place for the docker and dev
workflows. Run `uv run cli.py --help` for the command list."""

import os
import secrets
import shutil
import subprocess
import sys
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
    chars = "abcdefghijklmnopqrstuvwxyz0123456789!@#$%^&*(-_=+)"
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


if __name__ == "__main__":
    app()
