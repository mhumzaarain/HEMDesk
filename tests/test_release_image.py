"""The published-image contract: compose, .env.example, and the release workflow.

Text assertions on purpose — these files are read by Docker and GitHub, not by
Python, and the strings here are the ones operators type into .env.
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
IMAGE = "ghcr.io/mhumzaarain/hemdesk"


def read(name):
    return (ROOT / name).read_text(encoding="utf-8")


def test_web_and_worker_run_the_published_image():
    compose = read("docker-compose.yml")
    assert compose.count(f"image: {IMAGE}:${{IMAGE_TAG:-latest}}") == 2


def test_web_and_worker_can_still_build_locally():
    # Swarm ignores build:, but it keeps compose-build working on a node that
    # cannot reach the registry.
    assert read("docker-compose.yml").count("build: .") == 2


def test_env_example_defaults_the_image_tag():
    assert "IMAGE_TAG=latest" in read(".env.example")


def test_release_workflow_publishes_on_version_tags():
    workflow = read(".github/workflows/release.yml")
    assert 'tags: ["v*"]' in workflow


def test_release_workflow_can_write_packages():
    # The run's automatic GITHUB_TOKEN needs this; no stored token exists.
    assert "packages: write" in read(".github/workflows/release.yml")


def test_release_workflow_builds_the_documented_image_for_amd64():
    workflow = read(".github/workflows/release.yml")
    assert f"images: {IMAGE}" in workflow
    assert "platforms: linux/amd64" in workflow
