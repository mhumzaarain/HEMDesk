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


def test_generated_secrets_avoid_compose_metacharacters():
    for _ in range(20):
        secret = cli._generate_secret()
        assert len(secret) == 50
        assert "$" not in secret and "#" not in secret and "&" not in secret


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


@pytest.fixture
def swarm_active(monkeypatch):
    monkeypatch.setattr(cli, "_capture", lambda cmd: "active")


def test_stack_deploy_passes_env_and_layers_prod(workspace, calls, swarm_active):
    set_env(workspace, mode="production", extra="LLM_MODEL=llama3.2:3b\n")
    result = runner.invoke(cli.app, ["stack-deploy"])
    assert result.exit_code == 0
    cmd, env = calls[0]
    assert cmd == (
        "docker stack deploy --detach "
        "-c docker-compose.yml -c docker-compose.prod.yml hemdesk"
    )
    assert env["LLM_MODEL"] == "llama3.2:3b"
    assert env["ENVIRONMENT"] == "production"


def test_stack_deploy_refuses_in_development(workspace, calls, swarm_active):
    set_env(workspace, mode="development")
    result = runner.invoke(cli.app, ["stack-deploy"])
    assert result.exit_code != 0
    assert calls == []


def test_stack_deploy_rejects_quoted_env_values(workspace, calls, swarm_active):
    set_env(workspace, mode="production", extra='SECRET_KEY="quoted"\n')
    result = runner.invoke(cli.app, ["stack-deploy"])
    assert result.exit_code != 0
    assert "SECRET_KEY" in result.output
    assert calls == []


def test_stack_deploy_requires_active_swarm(workspace, calls, monkeypatch):
    set_env(workspace, mode="production")
    monkeypatch.setattr(cli, "_capture", lambda cmd: "inactive")
    result = runner.invoke(cli.app, ["stack-deploy"])
    assert result.exit_code != 0
    assert "swarm init" in result.output


def test_stack_rm(workspace, calls):
    set_env(workspace, mode="production")
    runner.invoke(cli.app, ["stack-rm"])
    assert calls == [("docker stack rm hemdesk", None)]


@pytest.fixture
def container(monkeypatch):
    seen = {}

    def fake_capture(cmd):
        seen["lookup"] = cmd
        return "abc123"

    monkeypatch.setattr(cli, "_capture", fake_capture)
    return seen


def test_find_container_uses_dev_separator(workspace, container):
    set_env(workspace, mode="development")
    assert cli._find_container("db") == "abc123"
    assert "name=hemdesk-db" in container["lookup"]


def test_find_container_uses_prod_separator(workspace, container):
    set_env(workspace, mode="production")
    cli._find_container("db")
    assert "name=hemdesk_db" in container["lookup"]


def test_find_container_dev_web_looks_up_runserver(workspace, container):
    set_env(workspace, mode="development")
    cli._find_container("web")
    assert "name=hemdesk-runserver" in container["lookup"]


def test_find_container_prod_web_looks_up_web(workspace, container):
    set_env(workspace, mode="production")
    cli._find_container("web")
    assert "name=hemdesk_web" in container["lookup"]


def test_find_container_exits_when_absent(workspace, monkeypatch):
    set_env(workspace)
    monkeypatch.setattr(cli, "_capture", lambda cmd: "")
    with pytest.raises(SystemExit):
        cli._find_container("db")


def test_manage_passthrough(workspace, calls, container):
    set_env(workspace)
    runner.invoke(cli.app, ["manage", "seed_demo"])
    assert calls == [("docker exec -it abc123 python manage.py seed_demo", None)]


def test_manage_passthrough_with_flags(workspace, calls, container):
    set_env(workspace)
    result = runner.invoke(cli.app, ["manage", "migrate", "--noinput"])
    assert result.exit_code == 0
    assert "migrate --noinput" in calls[0][0]


def test_db_backup_dumps_and_copies(workspace, calls, container):
    set_env(workspace, extra="POSTGRES_USER=cmms\nPOSTGRES_DB=cmms\n")
    result = runner.invoke(cli.app, ["db-backup"])
    assert result.exit_code == 0
    cmds = [c for c, _ in calls]
    assert cmds[0] == (
        "docker exec abc123 pg_dump -U cmms -Fc -f /tmp/hemdesk-backup.dump cmms"
    )
    assert cmds[1].startswith("docker cp abc123:/tmp/hemdesk-backup.dump")
    assert cmds[2] == "docker exec abc123 rm /tmp/hemdesk-backup.dump"


def test_db_restore_requires_confirmation(workspace, calls, container):
    set_env(workspace)
    result = runner.invoke(cli.app, ["db-restore", "some.dump"])
    assert result.exit_code != 0
    assert calls == []


def test_db_restore_with_yes(workspace, calls, container, tmp_path):
    set_env(workspace, extra="POSTGRES_USER=cmms\nPOSTGRES_DB=cmms\n")
    dump = tmp_path / "some.dump"
    dump.write_bytes(b"x")
    result = runner.invoke(cli.app, ["db-restore", str(dump), "--yes"])
    assert result.exit_code == 0
    assert "pg_restore --clean --if-exists -U cmms -d cmms" in calls[1][0]


def test_tool_wrappers(workspace, calls):
    set_env(workspace)
    runner.invoke(cli.app, ["test"])
    runner.invoke(cli.app, ["lint"])
    runner.invoke(cli.app, ["format"])
    cmds = [c for c, _ in calls]
    assert "uv run pytest" in cmds[0]
    assert cmds[1] == "uv run ruff check ."
    assert cmds[2] == "uv run ruff format ."


def test_test_passthrough_with_args(workspace, calls):
    set_env(workspace)
    result = runner.invoke(cli.app, ["test", "-k", "foo"])
    assert result.exit_code == 0
    assert calls[0][0] == "uv run pytest -k foo"
