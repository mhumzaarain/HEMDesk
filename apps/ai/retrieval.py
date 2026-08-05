"""Postgres FTS retrieval for the assistant (spec §5-§6). The manual is
always pre-filtered to the device's model — FTS only finds sections within
one known manual, never the device itself."""

import logging
import re

from django.conf import settings
from django.contrib.postgres.search import SearchQuery, SearchRank
from django.db.models import F, Q
from pgvector.django import CosineDistance

from apps.maintenance.models import WorkOrder, WorkOrderStatus

from . import embeddings
from .fusion import rrf_fuse

logger = logging.getLogger(__name__)

CANDIDATES = 20  # per-retriever pool feeding RRF


def _queries(query_text):
    yield SearchQuery(query_text, search_type="websearch")
    words = re.findall(r"\w+", query_text)
    if len(words) > 1:
        yield SearchQuery(" OR ".join(words), search_type="websearch")


def _fts_sections(manual, query_text, k):
    for query in _queries(query_text):
        rows = list(
            manual.chunks.filter(search=query)
            .annotate(rank=SearchRank(F("search"), query))
            .order_by("-rank")[:k]
        )
        if rows:
            return rows
    return []


def _vector_sections(manual, query_text, k):
    """Ranked chunks by cosine distance, or None when hybrid is unavailable
    (no/stale vectors, backend down) — caller then uses FTS alone."""
    if not manual.embedding_model or (
        manual.embedding_model != settings.EMBEDDING_MODEL
    ):
        return None
    try:
        query_vector = embeddings.embed_query(query_text)
    except embeddings.EmbeddingUnavailable as exc:
        logger.warning("embedding backend unavailable, using FTS only: %s", exc)
        return None
    return list(
        manual.chunks.exclude(embedding__isnull=True)
        .order_by(CosineDistance("embedding", query_vector))[:k]
    )


def manual_sections(manual, query_text, k=5):
    fts_rows = _fts_sections(manual, query_text, CANDIDATES)
    vec_rows = _vector_sections(manual, query_text, CANDIDATES)
    if vec_rows is None:
        return fts_rows[:k]
    by_id = {c.id: c for c in fts_rows}
    by_id.update({c.id: c for c in vec_rows})
    fused = rrf_fuse(
        {c.id: rank for rank, c in enumerate(vec_rows, 1)},
        {c.id: rank for rank, c in enumerate(fts_rows, 1)},
    )
    return [by_id[cid] for cid, _ in fused[:k]]


def similar_repairs(equipment, query_text, k=3):
    for query in _queries(query_text):
        work_orders = (
            WorkOrder.objects.filter(
                status=WorkOrderStatus.COMPLETED,
                equipment__manufacturer__iexact=equipment.manufacturer,
                equipment__model_number__iexact=equipment.model_number,
            )
            .filter(
                Q(complaints__description__search=query)
                | Q(remarks__text__search=query)
            )
            .distinct()
            .order_by("-repair_completed_at")
            .prefetch_related("complaints", "remarks")[:k]
        )
        rows = [
            {
                "wo_id": wo.id,
                "completed_at": wo.repair_completed_at,
                "fault_category": wo.get_fault_category_display()
                if wo.fault_category
                else "",
                "remarks": [r.text for r in wo.remarks.all()],
                "complaints": [c.description for c in wo.complaints.all()],
            }
            for wo in work_orders
        ]
        if rows:
            return rows
    return []
