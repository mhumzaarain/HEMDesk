# Phase 2 / M3 — Service Manuals + Engineer Assistant Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Service-manual upload with FTS-indexed chunks, and a device-scoped engineer assistant chat grounded in the manual, the device's history, and past similar repairs (spec §5–§6; closes #10 and #21).

**Architecture:** Three new `ai` models (`ServiceManual`, `ManualChunk` with a Postgres `SearchVectorField`, `AssistantMessage`), a background extraction/chunking task (pypdf), FTS retrieval helpers, and a prompt assembler. The chat is an HTMX-polling panel included on the work-order and equipment detail pages; the answering task uses the client's interactive (fail-fast) mode. **Depends on M2 (`feature/ai-foundation`) being merged to `main` first** — it consumes `apps/ai/client.py` and `apps/ai/tasks.py`.

**Tech Stack:** Django 5.2 + `django.contrib.postgres` (SearchVector/SearchQuery/SearchRank, GIN index), pypdf (new dep), Procrastinate, HTMX + Alpine.

## Global Constraints

- Branch: `feature/manuals-assistant`, cut fresh from up-to-date `main` **after M2 is merged**. PR closes #10 and #21.
- Commit messages: single line. uv for everything. Ruff E/F/I, 88 cols.
- Assistant is **engineer + admin only** — staff must never see the panel or reach the endpoints.
- The device is **never inferred from message text** — every chat message is scoped to an equipment id (and optionally a work order) taken from the page.
- Retrieval is Postgres FTS only (websearch first, OR-of-words fallback); the chunk store must stay upgradeable to a pgvector column later (i.e., chunks are rows with plain-text content — nothing format-exotic).
- Every assistant answer is displayed with the fixed app-rendered disclaimer: *"Advisory only — verify against the service manual before acting."* (template text, never LLM output).
- The assistant has no tools and cannot change workflow state; LLM failure must produce a visible "not available" assistant message, never a hang.
- Scanned/image-only PDFs (near-zero extracted text) are marked `failed` with an explanatory note; OCR is out of scope.
- Manual chunks are ~1,500 chars with ~200-char overlap, page ranges preserved.

---

### Task 0: Branch (after M2 merge)

- [ ] **Step 1: Confirm M2 is on main, then cut the branch**

```bash
git checkout main
git pull
python -c "import pathlib; assert pathlib.Path('apps/ai/client.py').exists(), 'M2 not merged yet'"
git checkout -b feature/manuals-assistant
```

---

### Task 1: Models — ServiceManual, ManualChunk, AssistantMessage

**Files:**
- Modify: `apps/ai/models.py`, `apps/ai/admin.py`, `config/settings/base.py` (add `"django.contrib.postgres",` to `INSTALLED_APPS`, above the app entries)
- Create: migration via `makemigrations`
- Test: `tests/test_manual_models.py`
- Modify: `pyproject.toml` via `uv add pypdf`

**Interfaces:**
- Produces: `ai.ServiceManual` — `manufacturer`, `model_number`, `title`, `file` (FileField `upload_to="manuals/"`), `uploaded_by` (User FK), `uploaded_at` (auto), `status` (`processing`/`ready`/`failed`, default `processing`), `status_note` (blank), `page_count` (default 0). Unique on (`manufacturer`, `model_number`). Classmethod `for_equipment(equipment) -> ServiceManual | None` (case-insensitive match on manufacturer + model_number, `ready` only).
- Produces: `ai.ManualChunk` — `manual` FK (`related_name="chunks"`, `on_delete=CASCADE` — chunks are derived data, deletable on re-upload), `text`, `page_start`, `page_end`, `search` (`SearchVectorField`, null) with `GinIndex(fields=["search"])`.
- Produces: `ai.AssistantMessage` — `equipment` FK (`related_name="assistant_messages"`), `work_order` FK (null/blank), `user` FK, `role` (`user`/`assistant`), `content`, `created_at` (auto). Ordering `["created_at"]`.

- [ ] **Step 1: Add dependency**

```bash
uv add "pypdf~=5.1"
```

- [ ] **Step 2: Write the failing tests**

```python
# tests/test_manual_models.py
import pytest

from apps.ai.models import AssistantMessage, ManualChunk, ServiceManual


@pytest.fixture
def manual(db, engineer):
    return ServiceManual.objects.create(
        manufacturer="Hamilton",
        model_number="C2",
        title="Hamilton C2 Service Manual",
        uploaded_by=engineer,
        status="ready",
    )


def test_for_equipment_matches_case_insensitively(manual, make_equipment):
    eq = make_equipment(manufacturer="HAMILTON", model_number="c2")
    assert ServiceManual.for_equipment(eq) == manual


def test_for_equipment_ignores_unready(manual, equipment):
    manual.status = "processing"
    manual.save()
    assert ServiceManual.for_equipment(equipment) is None


def test_unique_per_model(manual, engineer):
    with pytest.raises(Exception):
        ServiceManual.objects.create(
            manufacturer="Hamilton", model_number="C2",
            title="dupe", uploaded_by=engineer,
        )


def test_chunks_cascade_on_manual_delete(manual):
    ManualChunk.objects.create(manual=manual, text="x", page_start=1, page_end=1)
    manual.delete()
    assert ManualChunk.objects.count() == 0


def test_assistant_message_ordering(equipment, engineer, db):
    a = AssistantMessage.objects.create(
        equipment=equipment, user=engineer, role="user", content="first"
    )
    b = AssistantMessage.objects.create(
        equipment=equipment, user=engineer, role="assistant", content="second"
    )
    assert list(equipment.assistant_messages.all()) == [a, b]
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/test_manual_models.py -v`
Expected: FAIL — models missing.

- [ ] **Step 4: Implement** (append to `apps/ai/models.py`)

```python
from django.conf import settings as django_settings
from django.contrib.postgres.indexes import GinIndex
from django.contrib.postgres.search import SearchVectorField


class ManualStatus(models.TextChoices):
    PROCESSING = "processing", "Processing"
    READY = "ready", "Ready"
    FAILED = "failed", "Failed"


class ServiceManual(models.Model):
    """One manual per (manufacturer, model_number) — covers every unit of
    that model. Deliberately deletable/replaceable: it is reference material,
    not clinical history."""

    manufacturer = models.CharField(max_length=200)
    model_number = models.CharField(max_length=100)
    title = models.CharField(max_length=300)
    file = models.FileField(upload_to="manuals/")
    uploaded_by = models.ForeignKey(
        django_settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="manuals_uploaded",
    )
    uploaded_at = models.DateTimeField(auto_now_add=True)
    status = models.CharField(
        max_length=20, choices=ManualStatus.choices, default=ManualStatus.PROCESSING
    )
    status_note = models.CharField(max_length=300, blank=True)
    page_count = models.PositiveIntegerField(default=0)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["manufacturer", "model_number"], name="one_manual_per_model"
            )
        ]

    @classmethod
    def for_equipment(cls, equipment):
        return cls.objects.filter(
            manufacturer__iexact=equipment.manufacturer,
            model_number__iexact=equipment.model_number,
            status=ManualStatus.READY,
        ).first()

    def __str__(self):
        return f"{self.title} ({self.manufacturer} {self.model_number})"


class ManualChunk(models.Model):
    manual = models.ForeignKey(
        ServiceManual, on_delete=models.CASCADE, related_name="chunks"
    )
    text = models.TextField()
    page_start = models.PositiveIntegerField()
    page_end = models.PositiveIntegerField()
    search = SearchVectorField(null=True)

    class Meta:
        indexes = [GinIndex(fields=["search"])]


class AssistantRole(models.TextChoices):
    USER = "user", "User"
    ASSISTANT = "assistant", "Assistant"


class AssistantMessage(models.Model):
    """Device-scoped chat history, shared between engineers (spec §6)."""

    equipment = models.ForeignKey(
        Equipment, on_delete=models.PROTECT, related_name="assistant_messages"
    )
    work_order = models.ForeignKey(
        "maintenance.WorkOrder",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="assistant_messages",
    )
    user = models.ForeignKey(
        django_settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="assistant_messages",
    )
    role = models.CharField(max_length=10, choices=AssistantRole.choices)
    content = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]
```

Register `ServiceManual` in `apps/ai/admin.py` (list_display `title, manufacturer, model_number, status`) — read-only convenience; uploads happen in the app UI.

```bash
uv run python manage.py makemigrations ai
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_manual_models.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml uv.lock apps/ai config/settings/base.py tests/test_manual_models.py
git commit -m "feat: service manual, chunk, and assistant message models"
```

---

### Task 2: Extraction, chunking, and the process_manual task

**Files:**
- Create: `apps/ai/manuals.py`
- Modify: `apps/ai/tasks.py`
- Test: `tests/test_manual_processing.py`

**Interfaces:**
- Produces: `manuals.chunk_pages(pages: list[str], size=1500, overlap=200) -> list[tuple[str, int, int]]` — sliding-window chunks over the concatenated page texts; each tuple is `(chunk_text, page_start, page_end)` with 1-based page numbers.
- Produces: `manuals.extract_pages(file_obj) -> list[str]` — pypdf per-page text (thin wrapper, not unit-tested; tests monkeypatch it).
- Produces: `manuals.process(manual) -> None` — extracts, detects scanned PDFs (total text < 20 chars/page average → `failed`, note `"scanned/image-only PDF — text extraction unsupported"`), else replaces chunks (delete + bulk_create), fills `search` vectors via `SearchVector("text")` update, sets `page_count` and `status=ready`.
- Produces: `tasks.process_manual(manual_id)` — Procrastinate task (`retry=2`) calling `manuals.process`; marks `failed` with note `"processing error"` on unexpected exceptions (and re-raises).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_manual_processing.py
import pytest

from apps.ai import manuals
from apps.ai.models import ManualChunk, ManualStatus, ServiceManual


@pytest.fixture
def manual(db, engineer):
    return ServiceManual.objects.create(
        manufacturer="Hamilton", model_number="C2",
        title="C2 Manual", uploaded_by=engineer,
    )


def test_chunk_pages_windows_and_page_ranges():
    # 3 pages x 1000 chars; windows of 1500 stepping 1300 → 3 chunks at
    # offsets 0, 1300, 2600 covering pages (1,2), (2,3), (3,3).
    pages = ["A" * 1000, "B" * 1000, "C" * 1000]
    chunks = manuals.chunk_pages(pages, size=1500, overlap=200)
    assert [(start, end) for _, start, end in chunks] == [(1, 2), (2, 3), (3, 3)]
    assert len(chunks[0][0]) == 1500
    assert len(chunks[2][0]) == 400  # tail window


def test_chunk_pages_short_doc_single_chunk():
    chunks = manuals.chunk_pages(["short text"], size=1500, overlap=200)
    assert chunks == [("short text", 1, 1)]


def test_process_marks_scanned_pdf_failed(manual, monkeypatch):
    monkeypatch.setattr(manuals, "extract_pages", lambda f: ["", " ", ""])
    manuals.process(manual)
    manual.refresh_from_db()
    assert manual.status == ManualStatus.FAILED
    assert "scanned" in manual.status_note


def test_process_creates_searchable_chunks(manual, monkeypatch):
    page = "The NO OXYGEN alarm indicates a blocked O2 supply line. " * 40
    monkeypatch.setattr(manuals, "extract_pages", lambda f: [page, page])
    manuals.process(manual)
    manual.refresh_from_db()
    assert manual.status == ManualStatus.READY and manual.page_count == 2
    assert manual.chunks.count() >= 1
    assert manual.chunks.filter(search__isnull=False).count() == manual.chunks.count()


def test_process_replaces_old_chunks(manual, monkeypatch):
    monkeypatch.setattr(manuals, "extract_pages", lambda f: ["some text " * 50])
    manuals.process(manual)
    first_ids = set(manual.chunks.values_list("id", flat=True))
    manuals.process(manual)
    assert set(manual.chunks.values_list("id", flat=True)).isdisjoint(first_ids)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_manual_processing.py -v`
Expected: FAIL — `apps.ai.manuals` missing.

- [ ] **Step 3: Implement**

```python
# apps/ai/manuals.py
"""Service-manual extraction and FTS chunking (spec §5). Chunks are plain
text rows — an embedding column can be added later without redesign."""

from django.contrib.postgres.search import SearchVector

from .models import ManualChunk, ManualStatus

CHUNK_SIZE = 1500
CHUNK_OVERLAP = 200
MIN_CHARS_PER_PAGE = 20  # below this average → treat as scanned/image-only


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
        chunks.append((window, page_at(position), page_at(position + len(window) - 1)))
        if position + size >= len(full):
            break
        position += step
    return chunks


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
    manual.page_count = len(pages)
    manual.status = ManualStatus.READY
    manual.status_note = ""
    manual.save(update_fields=["status", "status_note", "page_count"])
```

Append to `apps/ai/tasks.py`:

```python
@app.task(name="ai.process_manual", retry=2)
def process_manual(manual_id):
    from . import manuals
    from .models import ManualStatus, ServiceManual

    manual = ServiceManual.objects.get(pk=manual_id)
    try:
        manuals.process(manual)
    except Exception:
        manual.status = ManualStatus.FAILED
        manual.status_note = "processing error"
        manual.save(update_fields=["status", "status_note"])
        raise
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_manual_processing.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add apps/ai tests/test_manual_processing.py
git commit -m "feat: manual extraction, chunking, and FTS indexing task"
```

---

### Task 3: Retrieval — manual sections and similar repairs

**Files:**
- Create: `apps/ai/retrieval.py`
- Test: `tests/test_retrieval.py`

**Interfaces:**
- Consumes: `ManualChunk.search` vectors (Task 2), `WorkOrder`/`Complaint`/`Remark` models.
- Produces: `retrieval.manual_sections(manual, query_text, k=5) -> list[ManualChunk]` — websearch-ranked; when the strict websearch matches nothing, falls back to OR-of-words.
- Produces: `retrieval.similar_repairs(equipment, query_text, k=3) -> list[dict]` — completed work orders on the same (manufacturer, model_number) whose complaint descriptions or remark texts match; each dict: `{"wo_id", "completed_at", "fault_category", "remarks": [str, ...], "complaints": [str, ...]}`. Most recent first.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_retrieval.py
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_retrieval.py -v`
Expected: FAIL — `apps.ai.retrieval` missing.

- [ ] **Step 3: Implement**

```python
# apps/ai/retrieval.py
"""Postgres FTS retrieval for the assistant (spec §5-§6). The manual is
always pre-filtered to the device's model — FTS only finds sections within
one known manual, never the device itself."""

import re

from django.contrib.postgres.search import SearchQuery, SearchRank
from django.db.models import F, Q

from apps.maintenance.models import WorkOrder, WorkOrderStatus


def _queries(query_text):
    yield SearchQuery(query_text, search_type="websearch")
    words = re.findall(r"\w+", query_text)
    if len(words) > 1:
        yield SearchQuery(" OR ".join(words), search_type="websearch")


def manual_sections(manual, query_text, k=5):
    for query in _queries(query_text):
        rows = list(
            manual.chunks.filter(search=query)
            .annotate(rank=SearchRank(F("search"), query))
            .order_by("-rank")[:k]
        )
        if rows:
            return rows
    return []


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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_retrieval.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add apps/ai/retrieval.py tests/test_retrieval.py
git commit -m "feat: FTS retrieval for manual sections and similar repairs"
```

---

### Task 4: Prompt assembly + answer task

**Files:**
- Create: `apps/ai/assistant.py`
- Modify: `apps/ai/tasks.py`
- Test: `tests/test_assistant.py`

**Interfaces:**
- Consumes: `retrieval.manual_sections`, `retrieval.similar_repairs`, `ServiceManual.for_equipment`, `client.chat(..., interactive=True)`, `AssistantMessage`.
- Produces: `assistant.build_messages(equipment, work_order, question) -> list[dict]` — system prompt + one user message containing the context blocks (device card; work-order complaints/remarks when given; manual sections with page citations; similar repairs; last 10 chat turns) + the question.
- Produces: `assistant.answer(message_id) -> AssistantMessage` — loads the user `AssistantMessage`, builds the prompt, calls `client.chat(messages, interactive=True)`, saves and returns the assistant reply row. On `LLMUnavailable`, saves the fixed text `"The assistant is not available right now — please try again."` instead.
- Produces: `tasks.answer_assistant_chat(message_id)` — Procrastinate task (`retry=0` — fail-fast is handled inside), calls `assistant.answer`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_assistant.py
import pytest

from apps.ai import assistant, client
from apps.ai.models import AssistantMessage, ManualChunk, ServiceManual
from apps.maintenance.models import Complaint


@pytest.fixture
def manual(db, engineer):
    manual = ServiceManual.objects.create(
        manufacturer="Hamilton", model_number="C2",
        title="C2 Manual", uploaded_by=engineer, status="ready",
    )
    from django.contrib.postgres.search import SearchVector

    ManualChunk.objects.create(
        manual=manual, page_start=42, page_end=42,
        text="NO OXYGEN alarm: check the O2 supply line for blockage.",
    )
    manual.chunks.update(search=SearchVector("text"))
    return manual


def test_build_messages_includes_all_blocks(
    equipment, make_work_order, engineer, manual, db
):
    wo = make_work_order()
    Complaint.objects.create(
        equipment=equipment, reporter=engineer, work_order=wo,
        description="no oxygen error on screen",
    )
    messages = assistant.build_messages(equipment, wo, "what should I check?")
    user_block = messages[-1]["content"]
    assert "Hamilton" in user_block                      # device card
    assert "no oxygen error on screen" in user_block     # WO complaint context
    assert "p. 42" in user_block                         # manual citation
    assert messages[0]["role"] == "system"
    assert "advisory" in messages[0]["content"].lower()


def test_build_messages_without_manual_says_so(equipment, db):
    messages = assistant.build_messages(equipment, None, "hello?")
    assert "No service manual" in messages[-1]["content"]


def test_answer_saves_assistant_reply(equipment, engineer, monkeypatch, db):
    monkeypatch.setattr(client, "chat", lambda m, **kw: "Check the O2 line.")
    question = AssistantMessage.objects.create(
        equipment=equipment, user=engineer, role="user", content="no oxygen error"
    )
    reply = assistant.answer(question.id)
    assert reply.role == "assistant" and reply.content == "Check the O2 line."
    assert reply.equipment == equipment


def test_answer_failure_writes_unavailable_message(
    equipment, engineer, monkeypatch, db
):
    def _boom(m, **kw):
        raise client.LLMUnavailable("down")

    monkeypatch.setattr(client, "chat", _boom)
    question = AssistantMessage.objects.create(
        equipment=equipment, user=engineer, role="user", content="hi"
    )
    reply = assistant.answer(question.id)
    assert "not available" in reply.content


def test_answer_uses_interactive_mode(equipment, engineer, monkeypatch, db):
    seen = {}

    def _chat(messages, **kwargs):
        seen.update(kwargs)
        return "ok"

    monkeypatch.setattr(client, "chat", _chat)
    question = AssistantMessage.objects.create(
        equipment=equipment, user=engineer, role="user", content="hi"
    )
    assistant.answer(question.id)
    assert seen.get("interactive") is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_assistant.py -v`
Expected: FAIL — `apps.ai.assistant` missing.

- [ ] **Step 3: Implement**

```python
# apps/ai/assistant.py
"""Prompt assembly and answering for the engineer assistant (spec §6).
The device is never inferred from text — it always comes in as a model
instance from the page the chat lives on."""

from . import client, retrieval
from .models import AssistantMessage, AssistantRole, ServiceManual

SYSTEM_PROMPT = (
    "You are an advisory assistant for hospital biomedical engineers, helping "
    "troubleshoot one specific device. Ground every suggestion in the manual "
    "sections and repair history provided; cite manual page numbers when you "
    "use them. If the provided material does not cover the question, say so "
    "plainly. You cannot perform actions — only advise. Keep answers short "
    "and practical."
)

UNAVAILABLE_TEXT = "The assistant is not available right now — please try again."

HISTORY_TURNS = 10


def _device_card(equipment):
    return (
        f"Device: {equipment.name} — {equipment.manufacturer} "
        f"{equipment.model_number}, serial {equipment.serial_number}, "
        f"department {equipment.department.name}, status {equipment.status}"
    )


def _work_order_block(work_order):
    if work_order is None:
        return "No active work order context."
    complaints = "\n".join(
        f"- complaint: {c.description[:400]}" for c in work_order.complaints.all()
    )
    remarks = "\n".join(
        f"- remark ({r.kind}): {r.text[:400]}" for r in work_order.remarks.all()
    )
    return (
        f"Work order #{work_order.id} ({work_order.status}):\n"
        f"{complaints or '- no complaints attached'}\n"
        f"{remarks or '- no remarks yet'}"
    )


def _manual_block(equipment, question):
    manual = ServiceManual.for_equipment(equipment)
    if manual is None:
        return "No service manual is on file for this model."
    sections = retrieval.manual_sections(manual, question)
    if not sections:
        return f"No sections of '{manual.title}' matched the question."
    return "\n\n".join(
        f"Manual p. {s.page_start}"
        + (f"-{s.page_end}" if s.page_end != s.page_start else "")
        + f": {s.text[:800]}"
        for s in sections
    )


def _similar_repairs_block(equipment, question):
    rows = retrieval.similar_repairs(equipment, question)
    if not rows:
        return "No similar past repairs found for this model."
    lines = []
    for row in rows:
        lines.append(
            f"- WO #{row['wo_id']} ({row['fault_category'] or 'uncategorized'}): "
            f"complaints: {'; '.join(row['complaints'])[:300]} | "
            f"resolution remarks: {'; '.join(row['remarks'])[:300]}"
        )
    return "\n".join(lines)


def _history_block(equipment):
    turns = list(
        equipment.assistant_messages.order_by("-created_at")[:HISTORY_TURNS]
    )[::-1]
    return "\n".join(f"{m.role}: {m.content[:300]}" for m in turns) or "none"


def build_messages(equipment, work_order, question):
    context = (
        f"{_device_card(equipment)}\n\n"
        f"== Work-order context ==\n{_work_order_block(work_order)}\n\n"
        f"== Service manual sections ==\n{_manual_block(equipment, question)}\n\n"
        f"== Similar past repairs (same model) ==\n"
        f"{_similar_repairs_block(equipment, question)}\n\n"
        f"== Recent chat ==\n{_history_block(equipment)}\n\n"
        f"Engineer's question: {question}"
    )
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": context},
    ]


def answer(message_id) -> AssistantMessage:
    question = AssistantMessage.objects.select_related(
        "equipment__department", "work_order", "user"
    ).get(pk=message_id)
    messages = build_messages(
        question.equipment, question.work_order, question.content
    )
    try:
        content = client.chat(messages, interactive=True)
    except client.LLMUnavailable:
        content = UNAVAILABLE_TEXT
    return AssistantMessage.objects.create(
        equipment=question.equipment,
        work_order=question.work_order,
        user=question.user,
        role=AssistantRole.ASSISTANT,
        content=content,
    )
```

Append to `apps/ai/tasks.py`:

```python
@app.task(name="ai.answer_assistant_chat")
def answer_assistant_chat(message_id):
    from . import assistant

    assistant.answer(message_id)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_assistant.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add apps/ai tests/test_assistant.py
git commit -m "feat: assistant prompt assembly and fail-fast answer task"
```

---

### Task 5: Manuals UI — list + upload

**Files:**
- Create: `apps/ai/urls.py`, `apps/ai/views.py`, `templates/ai/manuals.html`
- Modify: `config/urls.py` (add `path("ai/", include("apps.ai.urls")),`), `templates/base.html` (engineer/admin sidebar link "Manuals" → `manual_list`), `templates/equipment/detail.html` (link to the device's manual file when `ServiceManual.for_equipment` matches)
- Test: `tests/test_manual_views.py`

**Interfaces:**
- Consumes: `ServiceManual`, `tasks.process_manual.defer`.
- Produces: URL `manual_list` (GET list / POST upload — fields `manufacturer`, `model_number`, `title`, `file`). Upload replaces an existing manual for the same (manufacturer, model_number) pair (update fields + delete old chunks via re-process) and defers `process_manual`. Engineer/admin only.
- Produces: equipment-detail context key `service_manual`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_manual_views.py
import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from apps.ai.models import ManualStatus, ServiceManual


@pytest.fixture
def engineer_client(client, engineer):
    client.force_login(engineer)
    return client


def _upload(client, **overrides):
    data = {
        "manufacturer": "Hamilton",
        "model_number": "C2",
        "title": "C2 Service Manual",
        "file": SimpleUploadedFile("manual.pdf", b"%PDF-1.4 fake"),
    }
    data.update(overrides)
    return client.post(reverse("manual_list"), data)


def test_staff_blocked(client, staff_user):
    client.force_login(staff_user)
    assert client.get(reverse("manual_list")).status_code == 403


def test_upload_creates_processing_manual_and_defers(
    engineer_client, monkeypatch, db
):
    deferred = []
    from apps.ai import tasks

    monkeypatch.setattr(
        tasks.process_manual, "defer", lambda **kw: deferred.append(kw)
    )
    response = _upload(engineer_client)
    assert response.status_code == 302
    manual = ServiceManual.objects.get()
    assert manual.status == ManualStatus.PROCESSING
    assert deferred == [{"manual_id": manual.id}]


def test_reupload_replaces_same_model(engineer_client, monkeypatch, db):
    from apps.ai import tasks

    monkeypatch.setattr(tasks.process_manual, "defer", lambda **kw: None)
    _upload(engineer_client)
    _upload(engineer_client, title="C2 Manual rev B")
    assert ServiceManual.objects.count() == 1
    assert ServiceManual.objects.get().title == "C2 Manual rev B"


def test_equipment_detail_links_ready_manual(
    engineer_client, equipment, engineer, db
):
    ServiceManual.objects.create(
        manufacturer="Hamilton", model_number="C2", title="C2 Manual",
        uploaded_by=engineer, status=ManualStatus.READY,
    )
    response = engineer_client.get(reverse("equipment_detail", args=[equipment.pk]))
    assert b"C2 Manual" in response.content
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_manual_views.py -v`
Expected: FAIL — `NoReverseMatch: manual_list`.

- [ ] **Step 3: Implement**

```python
# apps/ai/views.py
from django.contrib import messages
from django.shortcuts import redirect, render
from django.views.generic import View

from apps.accounts.mixins import RoleRequiredMixin
from apps.accounts.models import Roles

from .models import ManualStatus, ServiceManual

ENGINEER_ROLES = (Roles.ENGINEER, Roles.ADMIN)


class ManualListView(RoleRequiredMixin, View):
    allowed_roles = ENGINEER_ROLES

    def get(self, request):
        return render(
            request,
            "ai/manuals.html",
            {"manuals": ServiceManual.objects.order_by("manufacturer", "model_number")},
        )

    def post(self, request):
        from . import tasks

        manufacturer = request.POST.get("manufacturer", "").strip()
        model_number = request.POST.get("model_number", "").strip()
        title = request.POST.get("title", "").strip()
        upload = request.FILES.get("file")
        if not all([manufacturer, model_number, title, upload]):
            messages.error(request, "All fields including the PDF are required.")
            return redirect("manual_list")
        manual, _ = ServiceManual.objects.update_or_create(
            manufacturer__iexact=manufacturer,
            model_number__iexact=model_number,
            defaults={
                "manufacturer": manufacturer,
                "model_number": model_number,
                "title": title,
                "file": upload,
                "uploaded_by": request.user,
                "status": ManualStatus.PROCESSING,
                "status_note": "",
            },
        )
        tasks.process_manual.defer(manual_id=manual.id)
        messages.success(request, f"{title} uploaded — processing in background.")
        return redirect("manual_list")
```

(If `update_or_create` with `__iexact` lookups misbehaves on your Django version, do an explicit `filter(...).first()` then update-or-create by pk — the tests are the contract.)

```python
# apps/ai/urls.py
from django.urls import path

from . import views

urlpatterns = [
    path("manuals/", views.ManualListView.as_view(), name="manual_list"),
]
```

`templates/ai/manuals.html`:

```html
{% extends "base.html" %}
{% block content %}
<div class="max-w-3xl mx-auto">
  <h1 class="text-xl font-semibold mb-4">Service manuals</h1>
  <form method="post" enctype="multipart/form-data" class="card p-4 mb-6 grid gap-3">
    {% csrf_token %}
    <input class="input" name="manufacturer" placeholder="Manufacturer" required>
    <input class="input" name="model_number" placeholder="Model number" required>
    <input class="input" name="title" placeholder="Manual title" required>
    <input type="file" name="file" accept=".pdf" required>
    <button type="submit" class="btn btn-primary">Upload manual</button>
    <p class="text-sm text-muted">Text-based PDFs only — scanned/image-only manuals can't be indexed yet.</p>
  </form>
  <table class="w-full text-sm">
    <thead><tr><th>Title</th><th>Model</th><th>Status</th><th>Pages</th></tr></thead>
    <tbody>
      {% for m in manuals %}
      <tr>
        <td><a class="link" href="{{ m.file.url }}">{{ m.title }}</a></td>
        <td>{{ m.manufacturer }} {{ m.model_number }}</td>
        <td><span class="badge">{{ m.get_status_display }}</span>
            {% if m.status_note %}<span class="text-sm text-muted">{{ m.status_note }}</span>{% endif %}</td>
        <td>{{ m.page_count }}</td>
      </tr>
      {% empty %}
      <tr><td colspan="4" class="text-muted">No manuals uploaded yet.</td></tr>
      {% endfor %}
    </tbody>
  </table>
</div>
{% endblock %}
```

In `apps/equipment/views.py` `EquipmentDetailView.get_context_data`, inside the existing `is_engineer_or_admin` branch (added in M2 Task 4), add:

```python
            from apps.ai.models import ServiceManual

            ctx["service_manual"] = ServiceManual.for_equipment(self.object)
```

And in `templates/equipment/detail.html` show it (near the risk card):

```html
{% if service_manual %}
<p class="text-sm mt-2">
  Manual: <a class="link" href="{{ service_manual.file.url }}">{{ service_manual.title }}</a>
</p>
{% endif %}
```

Wire the app urls in `config/urls.py` and the "Manuals" sidebar link in `templates/base.html` (copy the Dashboard nav item markup).

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_manual_views.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add apps/ai config/urls.py templates/ai templates/base.html apps/equipment/views.py templates/equipment/detail.html tests/test_manual_views.py
git commit -m "feat: manual upload page with background processing"
```

---

### Task 6: Assistant panel UI — send + poll

**Files:**
- Modify: `apps/ai/views.py`, `apps/ai/urls.py`, `templates/equipment/detail.html`, `templates/maintenance/workorder_detail.html`
- Create: `templates/ai/_assistant_panel.html`, `templates/ai/_assistant_messages.html`
- Test: `tests/test_assistant_views.py`

**Interfaces:**
- Consumes: `AssistantMessage`, `tasks.answer_assistant_chat.defer`.
- Produces: URLs `assistant_messages` (GET, `<int:equipment_id>/`, optional `?wo=<id>`) rendering the messages partial, and `assistant_send` (POST, same path, field `content`) creating the user message, deferring the answer task, and returning the messages partial. Both engineer/admin only (403 for staff).
- Produces: panel include — `{% include "ai/_assistant_panel.html" with equipment=... work_order=... %}` (work_order optional).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_assistant_views.py
import pytest
from django.urls import reverse

from apps.ai.models import AssistantMessage


@pytest.fixture
def engineer_client(client, engineer):
    client.force_login(engineer)
    return client


def test_staff_blocked(client, staff_user, equipment):
    client.force_login(staff_user)
    url = reverse("assistant_messages", args=[equipment.pk])
    assert client.get(url).status_code == 403


def test_send_creates_message_and_defers(
    engineer_client, engineer, equipment, make_work_order, monkeypatch
):
    deferred = []
    from apps.ai import tasks

    monkeypatch.setattr(
        tasks.answer_assistant_chat, "defer", lambda **kw: deferred.append(kw)
    )
    wo = make_work_order()
    url = reverse("assistant_send", args=[equipment.pk]) + f"?wo={wo.pk}"
    response = engineer_client.post(url, {"content": "no oxygen error"})
    assert response.status_code == 200
    message = AssistantMessage.objects.get()
    assert message.role == "user" and message.work_order == wo
    assert deferred == [{"message_id": message.id}]
    assert b"no oxygen error" in response.content


def test_poll_shows_thinking_until_answer(engineer_client, engineer, equipment):
    AssistantMessage.objects.create(
        equipment=equipment, user=engineer, role="user", content="hi"
    )
    url = reverse("assistant_messages", args=[equipment.pk])
    assert b"thinking" in engineer_client.get(url).content.lower()
    AssistantMessage.objects.create(
        equipment=equipment, user=engineer, role="assistant", content="Answer."
    )
    body = engineer_client.get(url).content
    assert b"Answer." in body and b"Advisory only" in body
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_assistant_views.py -v`
Expected: FAIL — `NoReverseMatch: assistant_messages`.

- [ ] **Step 3: Implement views** (append to `apps/ai/views.py`)

```python
from django.shortcuts import get_object_or_404

from apps.equipment.models import Equipment
from apps.maintenance.models import WorkOrder

from .models import AssistantMessage, AssistantRole


def _assistant_context(request, equipment_id):
    equipment = get_object_or_404(Equipment, pk=equipment_id)
    work_order = None
    wo_id = request.GET.get("wo")
    if wo_id:
        work_order = get_object_or_404(WorkOrder, pk=wo_id, equipment=equipment)
    return {
        "equipment": equipment,
        "work_order": work_order,
        "chat_messages": equipment.assistant_messages.select_related("user"),
    }


class AssistantMessagesView(RoleRequiredMixin, View):
    allowed_roles = ENGINEER_ROLES

    def get(self, request, equipment_id):
        return render(
            request,
            "ai/_assistant_messages.html",
            _assistant_context(request, equipment_id),
        )


class AssistantSendView(RoleRequiredMixin, View):
    allowed_roles = ENGINEER_ROLES

    def post(self, request, equipment_id):
        from . import tasks

        context = _assistant_context(request, equipment_id)
        content = request.POST.get("content", "").strip()
        if content:
            message = AssistantMessage.objects.create(
                equipment=context["equipment"],
                work_order=context["work_order"],
                user=request.user,
                role=AssistantRole.USER,
                content=content,
            )
            tasks.answer_assistant_chat.defer(message_id=message.id)
        return render(request, "ai/_assistant_messages.html", context)
```

Add to `apps/ai/urls.py` urlpatterns:

```python
    path(
        "assistant/<int:equipment_id>/",
        views.AssistantMessagesView.as_view(),
        name="assistant_messages",
    ),
    path(
        "assistant/<int:equipment_id>/send/",
        views.AssistantSendView.as_view(),
        name="assistant_send",
    ),
```

`templates/ai/_assistant_messages.html`:

```html
<div id="assistant-thread" class="space-y-3">
  {% for m in chat_messages %}
    {% if m.role == "user" %}
      <div class="chat-bubble chat-user">
        <span class="text-xs text-muted">{{ m.user.get_full_name|default:m.user.username }}</span>
        <p>{{ m.content }}</p>
      </div>
    {% else %}
      <div class="chat-bubble chat-assistant">
        <p>{{ m.content|linebreaksbr }}</p>
        <p class="text-xs text-muted mt-1">Advisory only — verify against the service manual before acting.</p>
      </div>
    {% endif %}
  {% empty %}
    <p class="text-sm text-muted">Ask about this device — the assistant answers from its service manual and repair history.</p>
  {% endfor %}
  {% if chat_messages.last.role == "user" %}
    <div class="chat-bubble chat-assistant text-muted">Thinking…</div>
  {% endif %}
</div>
```

`templates/ai/_assistant_panel.html`:

```html
{% if user.is_engineer_or_admin %}
<div class="card p-4 mt-4" x-data="{ open: false }">
  <button type="button" class="flex items-center gap-2 font-semibold w-full"
          @click="open = !open">
    <span>Assistant</span>
    <span class="text-xs text-muted" x-text="open ? 'hide' : 'show'"></span>
  </button>
  <div x-show="open" x-cloak class="mt-3">
    <div
      hx-get="{% url 'assistant_messages' equipment.pk %}{% if work_order %}?wo={{ work_order.pk }}{% endif %}"
      hx-trigger="load, every 3s"
      hx-target="this"
      hx-swap="innerHTML">
    </div>
    <form class="mt-3 flex gap-2"
          hx-post="{% url 'assistant_send' equipment.pk %}{% if work_order %}?wo={{ work_order.pk }}{% endif %}"
          hx-target="previous div"
          hx-swap="innerHTML"
          hx-on::after-request="this.reset()">
      {% csrf_token %}
      <input class="input flex-1" name="content" placeholder="e.g. no oxygen error — what should I check?" required>
      <button type="submit" class="btn btn-primary">Ask</button>
    </form>
  </div>
</div>
{% endif %}
```

(Match the project's real chat-bubble/card/input classes to the Clinical Sky design system; if `chat-bubble` classes don't exist yet, style with the existing card + muted utilities. The `hx-target="previous div"` selector must resolve to the polling container — adjust to an explicit `hx-target="#assistant-box"` wrapper id if flaky.)

Include the panel at the bottom of the main content block in `templates/equipment/detail.html`:

```html
{% include "ai/_assistant_panel.html" with equipment=equipment %}
```

(where `equipment` is that template's object context variable — check its actual name, e.g. `object`.)

And in `templates/maintenance/workorder_detail.html`, below the remarks section:

```html
{% include "ai/_assistant_panel.html" with equipment=wo.equipment work_order=wo %}
```

(again matching the template's actual context variable for the work order.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_assistant_views.py -v`
Expected: PASS

- [ ] **Step 5: Full suite + lint, commit**

Run: `uv run pytest && uv run ruff check . && uv run ruff format .`
Expected: all green.

```bash
git add apps/ai templates/ai templates/equipment/detail.html templates/maintenance/workorder_detail.html tests/test_assistant_views.py
git commit -m "feat: assistant chat panel on equipment and work order pages"
```

---

### Task 7: PR

- [ ] **Step 1: Push and open the PR**

```bash
git push -u origin feature/manuals-assistant
gh pr create --title "Service manuals + engineer assistant chat" --body "Service manual upload per (manufacturer, model) with pypdf extraction and Postgres-FTS-indexed chunks (scanned PDFs rejected with a clear note), plus a device-scoped engineer assistant panel on the work-order and equipment pages. Answers are grounded in manual sections (cited by page), the device's history, and past similar repairs on the same model; fail-fast on LLM outage; fixed advisory disclaimer. Spec: docs/superpowers/specs/2026-07-18-phase2-ai-and-adoption-design.md §5–§6.

Closes #10
Closes #21

🤖 Generated with [Claude Code](https://claude.com/claude-code)"
```
