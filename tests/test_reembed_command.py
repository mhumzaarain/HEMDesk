import pytest
from django.core.management import call_command

from apps.ai import manuals
from apps.ai.models import ManualStatus, ServiceManual


@pytest.fixture
def ready_manual(db, engineer, monkeypatch):
    manual = ServiceManual.objects.create(
        manufacturer="Hamilton", model_number="C2",
        title="C2 Manual", uploaded_by=engineer,
    )
    monkeypatch.setattr(manuals, "extract_pages", lambda f: ["words " * 200])
    # Build chunks without vectors: simulate an upload while backend was down.
    from apps.ai.embeddings import EmbeddingUnavailable

    def down(texts, **kw):
        raise EmbeddingUnavailable("down")

    monkeypatch.setattr(manuals.embeddings, "embed_documents", down)
    manuals.process(manual)
    manual.refresh_from_db()
    assert manual.embedding_model == ""
    return manual


def _fake_vectors(texts, **kwargs):
    from django.conf import settings

    return [[1.0] + [0.0] * (settings.EMBEDDING_DIM - 1) for _ in texts]


def test_reembed_fills_vectors_and_stamps(ready_manual, monkeypatch, settings):
    monkeypatch.setattr(manuals.embeddings, "embed_documents", _fake_vectors)
    call_command("reembed_manuals")
    ready_manual.refresh_from_db()
    assert ready_manual.embedding_model == settings.EMBEDDING_MODEL
    assert ready_manual.status_note == ""
    assert not ready_manual.chunks.filter(embedding__isnull=True).exists()


def test_reembed_reports_failure_and_continues(ready_manual, monkeypatch, engineer):
    from apps.ai.embeddings import EmbeddingUnavailable

    other = ServiceManual.objects.create(
        manufacturer="Mindray", model_number="uMEC12",
        title="uMEC Manual", uploaded_by=engineer,
    )
    monkeypatch.setattr(manuals, "extract_pages", lambda f: ["words " * 200])
    # Create chunks for other so embedding will be attempted
    def down(texts, **kw):
        raise EmbeddingUnavailable("down")

    monkeypatch.setattr(manuals.embeddings, "embed_documents", down)
    manuals.process(other)
    other.refresh_from_db()

    # Now patch again for the actual command test
    def down(texts, **kw):
        raise EmbeddingUnavailable("down")

    monkeypatch.setattr(manuals.embeddings, "embed_documents", down)
    with pytest.raises(SystemExit):
        call_command("reembed_manuals")
    ready_manual.refresh_from_db()
    assert ready_manual.embedding_model == ""
    assert ready_manual.status_note == (
        "embeddings unavailable — keyword search only"
    )
    other.refresh_from_db()
    assert other.embedding_model == ""


def test_reembed_skips_non_ready_manuals(db, engineer, monkeypatch):
    ServiceManual.objects.create(
        manufacturer="Draeger", model_number="V500",
        title="V500 Manual", uploaded_by=engineer,
        status=ManualStatus.FAILED,
    )
    monkeypatch.setattr(
        manuals.embeddings,
        "embed_documents",
        lambda texts, **kw: pytest.fail("must not embed failed manuals"),
    )
    call_command("reembed_manuals")
