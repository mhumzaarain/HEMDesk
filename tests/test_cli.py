"""CLI tests — _run/_capture are faked; no docker required."""

import pytest
from typer.testing import CliRunner

import cli

runner = CliRunner()


@pytest.fixture
def calls(monkeypatch):
    made = []
    monkeypatch.setattr(cli, "_run", lambda cmd, env=None: made.append((cmd, env)))
    return made


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "ROOT", tmp_path)
    (tmp_path / ".env.example").write_text(
        "ENVIRONMENT=development\nSECRET_KEY=change-me\n"
        "POSTGRES_PASSWORD=cmms\nDEMO_PASSWORD=demo1234\n",
        encoding="utf-8",
    )
    return tmp_path


def set_env(workspace, mode="development", extra=""):
    (workspace / ".env").write_text(f"ENVIRONMENT={mode}\n{extra}", encoding="utf-8")


def test_init_workspace_generates_distinct_secrets(workspace, calls):
    result = runner.invoke(cli.app, ["init-workspace"])
    assert result.exit_code == 0
    content = (workspace / ".env").read_text()
    values = dict(
        line.split("=", 1) for line in content.strip().splitlines() if "=" in line
    )
    assert values["SECRET_KEY"] != "change-me"
    assert values["POSTGRES_PASSWORD"] != "cmms"
    assert values["DEMO_PASSWORD"] != "demo1234"
    secrets_set = {
        values["SECRET_KEY"],
        values["POSTGRES_PASSWORD"],
        values["DEMO_PASSWORD"],
    }
    assert len(secrets_set) == 3
    assert values["ENVIRONMENT"] == "development"


def test_init_workspace_refuses_to_overwrite(workspace):
    set_env(workspace)
    result = runner.invoke(cli.app, ["init-workspace"])
    assert result.exit_code != 0


def test_compose_up_builds_dev_layering(workspace, calls):
    set_env(workspace)
    result = runner.invoke(cli.app, ["compose-up", "-d"])
    assert result.exit_code == 0
    expected_cmd = (
        "docker compose -f docker-compose.yml "
        "-f docker-compose.dev.yml -p hemdesk up -d"
    )
    assert calls == [(expected_cmd, None)]


def test_compose_up_refuses_in_production(workspace, calls):
    set_env(workspace, mode="production")
    result = runner.invoke(cli.app, ["compose-up"])
    assert result.exit_code != 0
    assert calls == []


def test_compose_down_uses_dev_layering(workspace, calls):
    set_env(workspace)
    runner.invoke(cli.app, ["compose-down"])
    assert calls[0][0].endswith("-p hemdesk down")


def test_compose_build_uses_base_only(workspace, calls):
    set_env(workspace)
    runner.invoke(cli.app, ["compose-build"])
    assert calls == [("docker compose -f docker-compose.yml -p hemdesk build", None)]


def test_missing_env_file_gives_hint(workspace, calls):
    result = runner.invoke(cli.app, ["compose-up"])
    assert result.exit_code != 0
    assert "init-workspace" in result.output
