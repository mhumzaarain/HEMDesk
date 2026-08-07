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
