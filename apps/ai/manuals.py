"""Service-manual extraction and FTS chunking (spec §5). Chunks are plain
text rows — an embedding column can be added later without redesign."""

import logging

from django.conf import settings
from django.contrib.postgres.search import SearchVector

from . import embeddings
from .models import ManualChunk, ManualStatus

CHUNK_SIZE = 1500
CHUNK_OVERLAP = 200
MIN_CHARS_PER_PAGE = 20  # below this average → treat as scanned/image-only

logger = logging.getLogger(__name__)


def extract_pages(file_field) -> list[str]:
    """Owns opening/closing the storage file — monkeypatched wholesale in
    tests so processing tests never need a real PDF on disk."""
    from pypdf import PdfReader

    file_field.open("rb")
    try:
        reader = PdfReader(file_field)
        return [(page.extract_text() or "") for page in reader.pages]
    finally:
        file_field.close()


def chunk_pages(pages, size=CHUNK_SIZE, overlap=CHUNK_OVERLAP):
    """Sliding windows over the concatenated pages; returns
    (text, page_start, page_end) with 1-based page numbers."""
    # page_offsets[i] = char offset where page i (0-based) starts
    full = ""
    page_offsets = []
    for page_text in pages:
        page_offsets.append(len(full))
        full += page_text
    if not full.strip():
        return []

    def page_at(offset):
        page = 1
        for i, start in enumerate(page_offsets):
            if offset >= start:
                page = i + 1
        return page

    chunks = []
    step = size - overlap
    position = 0
    while True:
        window = full[position : position + size]
        chunks.append(
            (window, page_at(position), page_at(position + len(window) - 1))
        )
        if position + size >= len(full):
            break
        position += step
    return chunks


def embed_chunks(manual) -> bool:
    """Fill every chunk's embedding in EMBEDDING_BATCH_SIZE batches.
    True on full success; False (vectors untouched/partial) on failure —
    retrieval treats the manual as keyword-only either way via the
    embedding_model stamp."""
    chunks = list(manual.chunks.order_by("id"))
    batch = settings.EMBEDDING_BATCH_SIZE
    try:
        for start in range(0, len(chunks), batch):
            group = chunks[start : start + batch]
            vectors = embeddings.embed_documents([c.text for c in group])
            for chunk, vector in zip(group, vectors):
                chunk.embedding = vector
            ManualChunk.objects.bulk_update(group, ["embedding"])
    except embeddings.EmbeddingUnavailable as exc:
        logger.warning("embedding failed for manual %s: %s", manual.pk, exc)
        return False
    return True


def embed_and_stamp(manual) -> bool:
    """embed_chunks + record the outcome on the instance (not saved)."""
    if embed_chunks(manual):
        manual.embedding_model = settings.EMBEDDING_MODEL
        manual.status_note = ""
        return True
    manual.embedding_model = ""
    manual.status_note = "embeddings unavailable — keyword search only"
    return False


def process(manual) -> None:
    pages = extract_pages(manual.file)
    total_chars = sum(len(p.strip()) for p in pages)
    if not pages or total_chars < MIN_CHARS_PER_PAGE * len(pages):
        manual.status = ManualStatus.FAILED
        manual.status_note = "scanned/image-only PDF — text extraction unsupported"
        manual.page_count = len(pages)
        manual.save(update_fields=["status", "status_note", "page_count"])
        return
    manual.chunks.all().delete()
    ManualChunk.objects.bulk_create(
        ManualChunk(manual=manual, text=text, page_start=start, page_end=end)
        for text, start, end in chunk_pages(pages)
    )
    manual.chunks.update(search=SearchVector("text"))
    embed_and_stamp(manual)
    manual.page_count = len(pages)
    manual.status = ManualStatus.READY
    manual.save(
        update_fields=["status", "status_note", "page_count", "embedding_model"]
    )
