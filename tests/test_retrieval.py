import pytest
from django.utils import timezone

from apps.ai import manuals, retrieval
from apps.ai.models import ServiceManual
from apps.maintenance.models import Complaint, Remark, WorkOrderStatus


@pytest.fixture
def indexed_manual(db, engineer, monkeypatch):
    manual = ServiceManual.objects.create(
        manufacturer="Hamilton", model_number="C2",
        title="C2 Manual", uploaded_by=engineer,
    )
    pages = [
        "Chapter 1: routine cleaning and calibration schedules. " * 30,
        "NO OXYGEN alarm: check the O2 supply line for blockage. " * 30,
    ]
    monkeypatch.setattr(manuals, "extract_pages", lambda f: pages)
    manuals.process(manual)
    return manual


def test_manual_sections_finds_relevant_page(indexed_manual):
    sections = retrieval.manual_sections(indexed_manual, "no oxygen alarm")
    assert sections
    assert "NO OXYGEN" in sections[0].text


def test_manual_sections_or_fallback(indexed_manual):
    # websearch ANDs terms; this phrase only matches via the OR fallback
    sections = retrieval.manual_sections(indexed_manual, "oxygen gibberishword")
    assert sections and "O2" in sections[0].text


def test_similar_repairs_matches_same_model_history(
    equipment, make_equipment, make_work_order, engineer, db
):
    sibling = make_equipment(serial_number="SN-2")  # same Hamilton C2 model
    wo = make_work_order(
        eq=sibling, status=WorkOrderStatus.COMPLETED,
        repair_completed_at=timezone.now(), fault_category="electrical",
    )
    Complaint.objects.create(
        equipment=sibling, reporter=engineer, work_order=wo,
        description="ventilator shows no oxygen error",
    )
    Remark.objects.create(work_order=wo, author=engineer, text="replaced O2 cell")
    rows = retrieval.similar_repairs(equipment, "no oxygen error")
    assert rows and rows[0]["wo_id"] == wo.id
    assert "replaced O2 cell" in rows[0]["remarks"]


def test_similar_repairs_ignores_other_models(
    equipment, make_equipment, make_work_order, engineer, db
):
    other = make_equipment(serial_number="SN-3", model_number="G5")
    wo = make_work_order(
        eq=other, status=WorkOrderStatus.COMPLETED,
        repair_completed_at=timezone.now(),
    )
    Complaint.objects.create(
        equipment=other, reporter=engineer, work_order=wo,
        description="no oxygen error here too",
    )
    assert retrieval.similar_repairs(equipment, "no oxygen error") == []


@pytest.fixture
def hybrid_manual(indexed_manual, monkeypatch, settings):
    """indexed_manual with vectors planted so the 'NO OXYGEN' chunk is the
    semantic neighbor of the test query vector."""
    from django.conf import settings as django_settings

    dim = django_settings.EMBEDDING_DIM
    target = [1.0] + [0.0] * (dim - 1)
    other = [0.0, 1.0] + [0.0] * (dim - 2)
    for chunk in indexed_manual.chunks.all():
        chunk.embedding = target if "NO OXYGEN" in chunk.text else other
        chunk.save(update_fields=["embedding"])
    indexed_manual.embedding_model = django_settings.EMBEDDING_MODEL
    indexed_manual.save(update_fields=["embedding_model"])
    monkeypatch.setattr(
        retrieval.embeddings, "embed_query", lambda text, **kw: target
    )
    return indexed_manual


def test_hybrid_surfaces_semantic_only_hit(hybrid_manual):
    # No FTS overlap at all — only the planted vectors can find the chunk.
    sections = retrieval.manual_sections(hybrid_manual, "display blinking")
    assert sections
    assert "NO OXYGEN" in sections[0].text


def test_hybrid_falls_back_to_fts_on_outage(hybrid_manual, monkeypatch):
    from apps.ai.embeddings import EmbeddingUnavailable

    def down(text, **kw):
        raise EmbeddingUnavailable("down")

    monkeypatch.setattr(retrieval.embeddings, "embed_query", down)
    sections = retrieval.manual_sections(hybrid_manual, "no oxygen alarm")
    assert sections and "NO OXYGEN" in sections[0].text


def test_stale_embedding_model_uses_fts_only(hybrid_manual, monkeypatch):
    hybrid_manual.embedding_model = "some-old-model"
    hybrid_manual.save(update_fields=["embedding_model"])

    def explode(text, **kw):
        raise AssertionError("embed_query must not be called for stale vectors")

    monkeypatch.setattr(retrieval.embeddings, "embed_query", explode)
    sections = retrieval.manual_sections(hybrid_manual, "no oxygen alarm")
    assert sections and "NO OXYGEN" in sections[0].text


def test_unembedded_manual_uses_fts_only(indexed_manual, monkeypatch):
    def explode(text, **kw):
        raise AssertionError("embed_query must not be called")

    monkeypatch.setattr(retrieval.embeddings, "embed_query", explode)
    sections = retrieval.manual_sections(indexed_manual, "no oxygen alarm")
    assert sections and "NO OXYGEN" in sections[0].text


def _completed_wo(make_equipment, make_work_order, engineer, serial, description,
                  category="electrical", model_number="C2"):
    from apps.maintenance.models import Complaint, Remark

    device = make_equipment(serial_number=serial, model_number=model_number)
    wo = make_work_order(
        eq=device, status=WorkOrderStatus.COMPLETED,
        repair_completed_at=timezone.now(), fault_category=category,
    )
    Complaint.objects.create(
        equipment=device, reporter=engineer, work_order=wo,
        description=description,
    )
    Remark.objects.create(work_order=wo, author=engineer, text=f"fix for {serial}")
    return wo


def test_small_history_is_stuffed_without_wording_match(
    equipment, make_equipment, make_work_order, engineer, db
):
    for i in range(3):
        _completed_wo(make_equipment, make_work_order, engineer,
                      f"SN-S{i}", "totally unrelated wording")
    rows = retrieval.similar_repairs(equipment, "display blinking gibberish")
    assert len(rows) == 3  # previously FTS would return []


def test_fault_category_filters_candidates(
    equipment, make_equipment, make_work_order, engineer, db
):
    match = _completed_wo(make_equipment, make_work_order, engineer,
                          "SN-C1", "screen issue", category="display_monitor")
    _completed_wo(make_equipment, make_work_order, engineer,
                  "SN-C2", "power issue", category="battery_power")
    rows = retrieval.similar_repairs(
        equipment, "anything", fault_category="display_monitor"
    )
    assert [r["wo_id"] for r in rows] == [match.id]


def test_current_work_order_is_excluded(
    equipment, make_equipment, make_work_order, engineer, db
):
    own = _completed_wo(make_equipment, make_work_order, engineer,
                        "SN-E1", "own complaint")
    rows = retrieval.similar_repairs(equipment, "x", exclude_wo_id=own.id)
    assert own.id not in [r["wo_id"] for r in rows]


def test_large_history_ranks_by_fts(
    equipment, make_equipment, make_work_order, engineer, db
):
    for i in range(6):
        _completed_wo(make_equipment, make_work_order, engineer,
                      f"SN-L{i}", "routine battery swap")
    hit = _completed_wo(make_equipment, make_work_order, engineer,
                        "SN-HIT", "ventilator shows no oxygen error")
    rows = retrieval.similar_repairs(equipment, "no oxygen error")
    assert rows[0]["wo_id"] == hit.id
    assert len(rows) <= 5


def test_large_history_falls_back_to_most_recent(
    equipment, make_equipment, make_work_order, engineer, db
):
    for i in range(7):
        _completed_wo(make_equipment, make_work_order, engineer,
                      f"SN-R{i}", "routine battery swap")
    rows = retrieval.similar_repairs(equipment, "zzz nomatch qqq")
    assert len(rows) == 5


def test_thin_fts_match_is_padded_with_recent(
    equipment, make_equipment, make_work_order, engineer, db
):
    # 6 unrelated repairs + 1 keyword hit: the hit must not shrink the
    # context — remaining seats are filled by the most recent repairs.
    for i in range(6):
        _completed_wo(make_equipment, make_work_order, engineer,
                      f"SN-P{i}", "routine battery swap")
    hit = _completed_wo(make_equipment, make_work_order, engineer,
                        "SN-PHIT", "ventilator shows no oxygen error")
    rows = retrieval.similar_repairs(equipment, "no oxygen error")
    ids = [r["wo_id"] for r in rows]
    assert hit.id in ids
    assert len(rows) == 5
