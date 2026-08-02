# Phase 2 / M2 — AI Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Configurable LLM backend (`ai` app), monthly management PDF report with LLM narrative, and two-number risk scoring with high-risk narratives (spec §2–§4; closes #7 and #8).

**Architecture:** New `apps/ai/` isolates everything LLM-dependent: an OpenAI-compatible `client.py` (httpx), `RiskScoringConfig`/`RiskAssessment` models, Procrastinate tasks. `apps/reports/` gains the `MonthlyReport` model, a `month_metrics` aggregator reusing `metrics.py`, and lazy WeasyPrint PDF rendering. Everything degrades gracefully with the LLM down: reports render "narrative unavailable", risk rows still get scores.

**Tech Stack:** Django 5.2, httpx + WeasyPrint (new deps), Procrastinate 3.5 periodic tasks, Chart.js dashboard already present.

## Global Constraints

- Branch: `feature/ai-foundation`, cut fresh from up-to-date `main`. PR closes #7 and #8.
- Commit messages: single line. Run everything through uv (`uv run pytest`, `uv add`). Ruff E/F/I, line length 88.
- **Numbers from SQL, words from the LLM.** The LLM never computes metrics, never changes workflow state; every LLM output lands in a nullable field treated as optional enrichment. LLM tests always fake the client — no model in CI.
- All LLM calls happen inside Procrastinate tasks. Batch tasks (report, risk) retry patiently; nothing user-facing blocks on the LLM.
- Risk scoring: score = completed work orders in the last 12 months (fixed window) × `points_per_repair` (default 1); `high_risk_threshold` (default 3); those two fields are the entire admin-editable config. Narratives only for devices at/above threshold.
- Roles: reports and risk UI are engineer + admin only.
- WeasyPrint imports must be lazy (inside functions) — Windows dev machines may lack GTK; tests monkeypatch the render function.
- `RiskAssessment` rows are append-only history; `MonthlyReport` is regenerated in place per month.

---

### Task 0: Branch

- [ ] **Step 1: Cut the branch**

```bash
git checkout main
git pull
git checkout -b feature/ai-foundation
```

---

### Task 1: `ai` app scaffold + LLM settings + client

**Files:**
- Create: `apps/ai/__init__.py`, `apps/ai/apps.py`, `apps/ai/models.py` (empty for now), `apps/ai/migrations/__init__.py`, `apps/ai/client.py`
- Modify: `config/settings/base.py` (LLM_* + MEDIA settings, INSTALLED_APPS), `.env.example`
- Test: `tests/test_llm_client.py`
- Modify: `pyproject.toml` via `uv add httpx`

**Interfaces:**
- Produces: `apps.ai.client.chat(messages, *, interactive=False, _transport=None) -> str` — POSTs `{base}/chat/completions`, returns `choices[0].message.content`. Raises `apps.ai.client.LLMUnavailable` on connection errors, timeouts, or non-2xx. `interactive=True` uses the short timeout and no internal retry; batch (default) retries once internally after a 2 s sleep. `_transport` is a test seam for `httpx.MockTransport`.
- Produces settings: `LLM_BASE_URL`, `LLM_API_KEY`, `LLM_MODEL`, `LLM_TIMEOUT_SECONDS`, `LLM_INTERACTIVE_TIMEOUT_SECONDS`, `LLM_EXTRA_BODY`, `MEDIA_URL`, `MEDIA_ROOT`.

- [ ] **Step 1: Add dependency and scaffold**

```bash
uv add "httpx~=0.28"
```

```python
# apps/ai/__init__.py
```

```python
# apps/ai/apps.py
from django.apps import AppConfig


class AiConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.ai"
```

```python
# apps/ai/models.py
```

```python
# apps/ai/migrations/__init__.py
```

In `config/settings/base.py`, add `"apps.ai",` to `INSTALLED_APPS` (after `"apps.maintenance",`), add `import json` at the top, and append:

```python
MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"

# --- LLM backend (any OpenAI-compatible endpoint: Ollama, vLLM, hospital API)
LLM_BASE_URL = os.environ.get("LLM_BASE_URL", "http://ollama:11434/v1")
LLM_API_KEY = os.environ.get("LLM_API_KEY", "")
LLM_MODEL = os.environ.get("LLM_MODEL", "llama3.2:3b")
LLM_TIMEOUT_SECONDS = float(os.environ.get("LLM_TIMEOUT_SECONDS", "120"))
LLM_INTERACTIVE_TIMEOUT_SECONDS = float(
    os.environ.get("LLM_INTERACTIVE_TIMEOUT_SECONDS", "30")
)
LLM_EXTRA_BODY = json.loads(os.environ.get("LLM_EXTRA_BODY", "{}"))
```

In `.env.example`, replace the stale `OLLAMA_MODEL=llama3.1:8b` block with:

```
# --- LLM backend (Phase 2) --------------------------------------------------
# Any OpenAI-compatible endpoint. Defaults target the bundled ollama container.
# Examples:
#   vLLM:          LLM_BASE_URL=http://vllm-host:8000/v1
#   hospital API:  LLM_BASE_URL=https://llm.hospital.example/v1  + LLM_API_KEY
LLM_BASE_URL=http://ollama:11434/v1
LLM_API_KEY=
LLM_MODEL=llama3.2:3b
LLM_TIMEOUT_SECONDS=120
LLM_INTERACTIVE_TIMEOUT_SECONDS=30
# Extra JSON merged into every request body, for backend quirks, e.g.
# {"chat_template_kwargs": {"enable_thinking": false}}
LLM_EXTRA_BODY={}
```

- [ ] **Step 2: Write the failing tests**

```python
# tests/test_llm_client.py
import httpx
import pytest

from apps.ai import client


def _transport(handler):
    return httpx.MockTransport(handler)


def _ok_response(request):
    return httpx.Response(
        200,
        json={"choices": [{"message": {"role": "assistant", "content": "Hello."}}]},
    )


def test_chat_returns_content():
    reply = client.chat(
        [{"role": "user", "content": "hi"}], _transport=_transport(_ok_response)
    )
    assert reply == "Hello."


def test_chat_sends_model_and_extra_body(settings):
    settings.LLM_MODEL = "test-model"
    settings.LLM_EXTRA_BODY = {"chat_template_kwargs": {"enable_thinking": False}}
    captured = {}

    def handler(request):
        import json

        captured.update(json.loads(request.content))
        return _ok_response(request)

    client.chat([{"role": "user", "content": "hi"}], _transport=_transport(handler))
    assert captured["model"] == "test-model"
    assert captured["chat_template_kwargs"] == {"enable_thinking": False}


def test_chat_sends_bearer_only_when_key_set(settings):
    settings.LLM_API_KEY = "sk-abc"
    seen = {}

    def handler(request):
        seen["auth"] = request.headers.get("authorization")
        return _ok_response(request)

    client.chat([{"role": "user", "content": "hi"}], _transport=_transport(handler))
    assert seen["auth"] == "Bearer sk-abc"


def test_chat_raises_llm_unavailable_on_http_error():
    def handler(request):
        return httpx.Response(500, json={"error": "boom"})

    with pytest.raises(client.LLMUnavailable):
        client.chat(
            [{"role": "user", "content": "hi"}],
            interactive=True,
            _transport=_transport(handler),
        )


def test_batch_chat_retries_once_then_succeeds(monkeypatch):
    monkeypatch.setattr(client.time, "sleep", lambda s: None)
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(500)
        return _ok_response(request)

    reply = client.chat(
        [{"role": "user", "content": "hi"}], _transport=_transport(handler)
    )
    assert reply == "Hello." and calls["n"] == 2
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/test_llm_client.py -v`
Expected: FAIL — `apps.ai.client` has no `chat`.

- [ ] **Step 4: Implement**

```python
# apps/ai/client.py
"""OpenAI-compatible chat-completions client. The only place the app talks
to an LLM. Works against Ollama (/v1), vLLM, or any hospital gateway that
speaks the protocol — selected purely by env vars (spec §2)."""

import time

import httpx
from django.conf import settings


class LLMUnavailable(Exception):
    pass


def chat(messages, *, interactive=False, _transport=None) -> str:
    """One chat-completion round trip; returns the assistant text.

    interactive=True → short timeout, no retry (fail fast for the UI).
    Batch (default)  → full timeout, one internal retry with a short pause;
    Procrastinate-level retries on the task supply the patience beyond that.
    """
    timeout = (
        settings.LLM_INTERACTIVE_TIMEOUT_SECONDS
        if interactive
        else settings.LLM_TIMEOUT_SECONDS
    )
    body = {"model": settings.LLM_MODEL, "messages": messages}
    body.update(settings.LLM_EXTRA_BODY)
    headers = {}
    if settings.LLM_API_KEY:
        headers["Authorization"] = f"Bearer {settings.LLM_API_KEY}"

    attempts = 1 if interactive else 2
    last_error = None
    for attempt in range(attempts):
        if attempt:
            time.sleep(2)
        try:
            with httpx.Client(
                base_url=settings.LLM_BASE_URL,
                timeout=timeout,
                transport=_transport,
            ) as http:
                response = http.post("/chat/completions", json=body, headers=headers)
            response.raise_for_status()
            return response.json()["choices"][0]["message"]["content"]
        except (httpx.HTTPError, KeyError, IndexError, ValueError) as exc:
            last_error = exc
    raise LLMUnavailable(str(last_error))
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_llm_client.py -v`
Expected: 5 PASS

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml uv.lock apps/ai config/settings/base.py .env.example tests/test_llm_client.py
git commit -m "feat: ai app with configurable OpenAI-compatible LLM client"
```

---

### Task 2: Risk models — config singleton + assessments

**Files:**
- Modify: `apps/ai/models.py`
- Create: `apps/ai/admin.py`, migrations via `makemigrations`
- Test: `tests/test_risk_models.py`

**Interfaces:**
- Produces: `ai.RiskScoringConfig` — fields `points_per_repair` (PositiveIntegerField, default 1), `high_risk_threshold` (PositiveIntegerField, default 3); classmethod `get() -> RiskScoringConfig` returning the pk=1 singleton (get_or_create).
- Produces: `ai.RiskAssessment(AppendOnlyModel)` — `equipment` FK (`related_name="risk_assessments"`), `score` (IntegerField), `factors` (JSONField), `narrative` (TextField, null), `generated_at` (auto_now_add). Ordering `-generated_at`.
- Produces: `RISK_WINDOW_MONTHS = 12` module constant (the fixed, non-configurable window).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_risk_models.py
import pytest

from apps.ai.models import RiskAssessment, RiskScoringConfig


def test_config_singleton_defaults(db):
    config = RiskScoringConfig.get()
    assert (config.points_per_repair, config.high_risk_threshold) == (1, 3)
    assert RiskScoringConfig.get().pk == config.pk


def test_assessment_is_append_only(equipment, db):
    assessment = RiskAssessment.objects.create(
        equipment=equipment, score=2, factors={"repairs": 2}
    )
    assessment.score = 5
    with pytest.raises(TypeError):
        assessment.save()
    with pytest.raises(TypeError):
        assessment.delete()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_risk_models.py -v`
Expected: FAIL — models don't exist.

- [ ] **Step 3: Implement models and admin**

```python
# apps/ai/models.py
from django.db import models

from apps.core.models import AppendOnlyModel
from apps.equipment.models import Equipment

RISK_WINDOW_MONTHS = 12  # fixed design constant — deliberately not in config


class RiskScoringConfig(models.Model):
    """Singleton. Exactly two admin-editable numbers (spec §4)."""

    points_per_repair = models.PositiveIntegerField(default=1)
    high_risk_threshold = models.PositiveIntegerField(default=3)

    class Meta:
        verbose_name = "risk scoring configuration"

    @classmethod
    def get(cls) -> "RiskScoringConfig":
        config, _ = cls.objects.get_or_create(pk=1)
        return config

    def __str__(self):
        return (
            f"{self.points_per_repair} point(s)/repair, "
            f"high-risk at {self.high_risk_threshold}"
        )


class RiskAssessment(AppendOnlyModel):
    equipment = models.ForeignKey(
        Equipment, on_delete=models.PROTECT, related_name="risk_assessments"
    )
    score = models.IntegerField()
    factors = models.JSONField(default=dict)
    narrative = models.TextField(null=True, blank=True)
    generated_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-generated_at"]

    def __str__(self):
        return f"{self.equipment} score={self.score} @ {self.generated_at:%Y-%m-%d}"
```

```python
# apps/ai/admin.py
from django.contrib import admin

from .models import RiskScoringConfig


@admin.register(RiskScoringConfig)
class RiskScoringConfigAdmin(admin.ModelAdmin):
    list_display = ("points_per_repair", "high_risk_threshold")
    actions = ["recompute_now"]

    def has_add_permission(self, request):
        return not RiskScoringConfig.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False

    @admin.action(description="Recompute risk scores now")
    def recompute_now(self, request, queryset):
        from .tasks import compute_risk_scores

        compute_risk_scores.defer()
        self.message_user(request, "Risk recomputation queued.")
```

(The `recompute_now` action references `tasks.compute_risk_scores` which arrives in Task 3 — the lazy import inside the method means admin loads fine meanwhile; the action just can't be used until Task 3 lands.)

```bash
uv run python manage.py makemigrations ai
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_risk_models.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add apps/ai tests/test_risk_models.py
git commit -m "feat: risk scoring config singleton and append-only assessments"
```

---

### Task 3: Risk computation service + weekly task

**Files:**
- Create: `apps/ai/services.py`, `apps/ai/prompts.py`, `apps/ai/tasks.py`
- Test: `tests/test_risk_scoring.py`

**Interfaces:**
- Consumes: `client.chat` (Task 1), models (Task 2), `WorkOrder`/`WorkOrderStatus` from `apps.maintenance.models`.
- Produces: `services.compute_score(equipment, config, now) -> tuple[int, dict]` — factors dict: `{"repairs_in_window": int, "window_months": 12, "points_per_repair": int, "high_risk_threshold": int}`.
- Produces: `services.assess_equipment(equipment, config, now) -> RiskAssessment` — computes score; calls the LLM for a narrative **only when** `score >= config.high_risk_threshold` (narrative stays `None` otherwise or when `LLMUnavailable`); inserts and returns the row.
- Produces: `services.latest_assessment(equipment) -> RiskAssessment | None` and `services.high_risk_devices(limit=10) -> list[RiskAssessment]` (latest assessment per non-condemned device, filtered to `score >= threshold`, highest first).
- Produces: `tasks.compute_risk_scores` — Procrastinate task, weekly periodic (cron `0 3 * * 1`), loops all non-condemned equipment calling `assess_equipment`.
- Produces: `prompts.risk_narrative_prompt(equipment, factors, recent_complaints, recent_remarks) -> list[dict]` (chat messages).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_risk_scoring.py
from datetime import timedelta

import pytest
from django.utils import timezone

from apps.ai import client, services
from apps.ai.models import RiskAssessment, RiskScoringConfig
from apps.maintenance.models import WorkOrderStatus


@pytest.fixture
def fake_llm(monkeypatch):
    calls = []

    def _chat(messages, **kwargs):
        calls.append(messages)
        return "Narrative text."

    monkeypatch.setattr(client, "chat", _chat)
    return calls


def _completed_wo(make_work_order, when):
    wo = make_work_order(
        status=WorkOrderStatus.COMPLETED, repair_completed_at=when
    )
    return wo


def test_score_counts_completed_repairs_in_window(
    equipment, make_work_order, db
):
    now = timezone.now()
    _completed_wo(make_work_order, now - timedelta(days=30))
    _completed_wo(make_work_order, now - timedelta(days=60))
    _completed_wo(make_work_order, now - timedelta(days=400))  # outside window
    config = RiskScoringConfig.get()
    score, factors = services.compute_score(equipment, config, now)
    assert score == 2
    assert factors["repairs_in_window"] == 2
    assert factors["window_months"] == 12


def test_points_per_repair_multiplies(equipment, make_work_order, db):
    now = timezone.now()
    _completed_wo(make_work_order, now - timedelta(days=10))
    config = RiskScoringConfig.get()
    config.points_per_repair = 5
    config.save()
    score, _ = services.compute_score(equipment, config, now)
    assert score == 5


def test_narrative_only_at_or_above_threshold(
    equipment, make_work_order, fake_llm, db
):
    now = timezone.now()
    for days in (10, 20, 40):
        _completed_wo(make_work_order, now - timedelta(days=days))
    assessment = services.assess_equipment(equipment, RiskScoringConfig.get(), now)
    assert assessment.score == 3
    assert assessment.narrative == "Narrative text."


def test_no_narrative_below_threshold(equipment, make_work_order, fake_llm, db):
    now = timezone.now()
    _completed_wo(make_work_order, now - timedelta(days=10))
    assessment = services.assess_equipment(equipment, RiskScoringConfig.get(), now)
    assert assessment.score == 1
    assert assessment.narrative is None
    assert fake_llm == []


def test_llm_failure_still_records_score(
    equipment, make_work_order, monkeypatch, db
):
    def _boom(messages, **kwargs):
        raise client.LLMUnavailable("down")

    monkeypatch.setattr(client, "chat", _boom)
    now = timezone.now()
    for days in (5, 15, 25):
        _completed_wo(make_work_order, now - timedelta(days=days))
    assessment = services.assess_equipment(equipment, RiskScoringConfig.get(), now)
    assert assessment.score == 3 and assessment.narrative is None


def test_high_risk_devices_lists_latest_per_device(
    make_equipment, make_work_order, fake_llm, db
):
    now = timezone.now()
    hot = make_equipment(serial_number="SN-HOT")
    cold = make_equipment(serial_number="SN-COLD")
    for days in (5, 15, 25):
        make_work_order(
            eq=hot, status=WorkOrderStatus.COMPLETED,
            repair_completed_at=now - timedelta(days=days),
        )
    config = RiskScoringConfig.get()
    services.assess_equipment(hot, config, now)
    services.assess_equipment(cold, config, now)
    rows = services.high_risk_devices()
    assert [a.equipment for a in rows] == [hot]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_risk_scoring.py -v`
Expected: FAIL — `apps.ai.services` missing.

- [ ] **Step 3: Implement**

```python
# apps/ai/prompts.py
"""Prompt builders. Words come from the LLM; every number in a prompt was
computed in SQL first (spec design rule)."""


def risk_narrative_prompt(equipment, factors, recent_complaints, recent_remarks):
    complaint_lines = "\n".join(
        f"- {c.created_at:%Y-%m-%d}: {c.description[:300]}" for c in recent_complaints
    ) or "- none on record in the window"
    remark_lines = "\n".join(
        f"- {r.created_at:%Y-%m-%d} ({r.kind}): {r.text[:300]}" for r in recent_remarks
    ) or "- none on record in the window"
    return [
        {
            "role": "system",
            "content": (
                "You are a biomedical maintenance analyst. Write a short, plain "
                "paragraph (3-5 sentences) explaining why this device is "
                "high-risk, quoting concrete complaint or remark snippets. Do "
                "not invent numbers; use only the facts given."
            ),
        },
        {
            "role": "user",
            "content": (
                f"Device: {equipment}\n"
                f"Completed repairs in the last {factors['window_months']} months: "
                f"{factors['repairs_in_window']}\n"
                f"Risk score: {factors['repairs_in_window'] * factors['points_per_repair']} "
                f"(threshold {factors['high_risk_threshold']})\n\n"
                f"Recent complaints:\n{complaint_lines}\n\n"
                f"Recent repair remarks:\n{remark_lines}"
            ),
        },
    ]
```

```python
# apps/ai/services.py
from datetime import timedelta

from apps.equipment.models import Equipment, EquipmentStatus
from apps.maintenance.models import Complaint, Remark, WorkOrder, WorkOrderStatus

from . import client, prompts
from .models import RISK_WINDOW_MONTHS, RiskAssessment, RiskScoringConfig


def _window_start(now):
    return now - timedelta(days=RISK_WINDOW_MONTHS * 30)


def compute_score(equipment, config, now):
    repairs = WorkOrder.objects.filter(
        equipment=equipment,
        status=WorkOrderStatus.COMPLETED,
        repair_completed_at__gte=_window_start(now),
    ).count()
    factors = {
        "repairs_in_window": repairs,
        "window_months": RISK_WINDOW_MONTHS,
        "points_per_repair": config.points_per_repair,
        "high_risk_threshold": config.high_risk_threshold,
    }
    return repairs * config.points_per_repair, factors


def assess_equipment(equipment, config, now) -> RiskAssessment:
    score, factors = compute_score(equipment, config, now)
    narrative = None
    if score >= config.high_risk_threshold:
        recent_complaints = Complaint.objects.filter(
            equipment=equipment, created_at__gte=_window_start(now)
        ).order_by("-created_at")[:5]
        recent_remarks = Remark.objects.filter(
            work_order__equipment=equipment, created_at__gte=_window_start(now)
        ).order_by("-created_at")[:5]
        try:
            narrative = client.chat(
                prompts.risk_narrative_prompt(
                    equipment, factors, recent_complaints, recent_remarks
                )
            )
        except client.LLMUnavailable:
            narrative = None
    return RiskAssessment.objects.create(
        equipment=equipment, score=score, factors=factors, narrative=narrative
    )


def latest_assessment(equipment):
    return equipment.risk_assessments.order_by("-generated_at").first()


def high_risk_devices(limit=10):
    rows = []
    for equipment in Equipment.objects.exclude(status=EquipmentStatus.CONDEMNED):
        assessment = latest_assessment(equipment)
        if (
            assessment
            and assessment.score
            >= assessment.factors.get("high_risk_threshold", 0)
        ):
            rows.append(assessment)
    rows.sort(key=lambda a: -a.score)
    return rows[:limit]
```

(`high_risk_devices` is a per-device loop — fine at hospital fleet scale, hundreds of devices; revisit with a window-function query only if it ever shows up in profiling.)

```python
# apps/ai/tasks.py
"""All Procrastinate tasks that touch the LLM live in this app (spec §2)."""

from procrastinate.contrib.django import app


@app.periodic(cron="0 3 * * 1")
@app.task(name="ai.compute_risk_scores", retry=3)
def compute_risk_scores(timestamp=None):
    from django.utils import timezone

    from apps.equipment.models import Equipment, EquipmentStatus

    from .models import RiskScoringConfig
    from .services import assess_equipment

    now = timezone.now()
    config = RiskScoringConfig.get()
    for equipment in Equipment.objects.exclude(status=EquipmentStatus.CONDEMNED):
        assess_equipment(equipment, config, now)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_risk_scoring.py -v`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add apps/ai tests/test_risk_scoring.py
git commit -m "feat: weekly risk scoring task with high-risk LLM narratives"
```

---

### Task 4: Risk UI — equipment detail + dashboard widget

**Files:**
- Modify: `apps/equipment/views.py` (`EquipmentDetailView.get_context_data`), `templates/equipment/detail.html`, `apps/reports/views.py` (`dashboard`), `templates/reports/dashboard.html`
- Test: `tests/test_risk_views.py`

**Interfaces:**
- Consumes: `apps.ai.services.latest_assessment`, `high_risk_devices` (Task 3).
- Produces: context keys `risk_assessment` (equipment detail, engineer/admin only) and `high_risk` (dashboard).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_risk_views.py
import pytest
from django.urls import reverse

from apps.ai.models import RiskAssessment


@pytest.fixture
def assessment(equipment):
    return RiskAssessment.objects.create(
        equipment=equipment,
        score=4,
        factors={"repairs_in_window": 4, "window_months": 12,
                 "points_per_repair": 1, "high_risk_threshold": 3},
        narrative="Breaks a lot.",
    )


def test_equipment_detail_shows_risk_to_engineer(client, engineer, assessment, equipment):
    client.force_login(engineer)
    response = client.get(reverse("equipment_detail", args=[equipment.pk]))
    assert b"High risk" in response.content
    assert b"Breaks a lot." in response.content


def test_equipment_detail_hides_risk_from_staff(client, staff_user, assessment, equipment):
    client.force_login(staff_user)
    response = client.get(reverse("equipment_detail", args=[equipment.pk]))
    assert b"High risk" not in response.content


def test_dashboard_lists_high_risk_devices(client, engineer, assessment):
    client.force_login(engineer)
    response = client.get(reverse("dashboard"))
    assert assessment.equipment.serial_number.encode() in response.content
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_risk_views.py -v`
Expected: FAIL — no risk context/markup yet.

- [ ] **Step 3: Implement**

In `apps/equipment/views.py`, extend `EquipmentDetailView.get_context_data` (add the method if the view doesn't override it yet):

```python
    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        if self.request.user.is_engineer_or_admin:
            from apps.ai import services as ai_services

            ctx["risk_assessment"] = ai_services.latest_assessment(self.object)
        return ctx
```

In `templates/equipment/detail.html`, inside the existing engineer/admin-only area (mirror however the template gates the Edit/Condemn buttons), add a risk card:

```html
{% if risk_assessment %}
<div class="card p-4 mt-4">
  <div class="flex items-center gap-2">
    <h2 class="font-semibold">Risk</h2>
    <span class="badge">score {{ risk_assessment.score }}</span>
    {% if risk_assessment.score >= risk_assessment.factors.high_risk_threshold %}
      <span class="badge badge-danger">High risk</span>
    {% endif %}
  </div>
  <p class="text-sm text-muted">
    {{ risk_assessment.factors.repairs_in_window }} repair(s) in the last
    {{ risk_assessment.factors.window_months }} months ·
    updated {{ risk_assessment.generated_at|date:"Y-m-d" }}
  </p>
  {% if risk_assessment.narrative %}
    <p class="mt-2">{{ risk_assessment.narrative }}</p>
  {% endif %}
</div>
{% endif %}
```

(Match the actual card/badge classes used elsewhere in `detail.html` — the design system is already there; reuse it.)

In `apps/reports/views.py` `dashboard`, add to the context:

```python
    from apps.ai import services as ai_services
    context["high_risk"] = ai_services.high_risk_devices()
```

In `templates/reports/dashboard.html`, add a "High-risk devices" card alongside the existing list cards (e.g. next to "delayed repairs"), following the same card markup as its neighbors:

```html
<div class="card p-4">
  <h2 class="font-semibold mb-2">High-risk devices</h2>
  {% for a in high_risk %}
    <a href="{% url 'equipment_detail' a.equipment_id %}" class="flex justify-between py-1">
      <span>{{ a.equipment }}</span>
      <span class="badge badge-danger">{{ a.score }}</span>
    </a>
  {% empty %}
    <p class="text-sm text-muted">No devices above the risk threshold.</p>
  {% endfor %}
</div>
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_risk_views.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add apps/equipment/views.py templates/equipment/detail.html apps/reports/views.py templates/reports/dashboard.html tests/test_risk_views.py
git commit -m "feat: risk badge on equipment detail and dashboard widget"
```

---

### Task 5: MonthlyReport model + month metrics aggregation

**Files:**
- Create: `apps/reports/models.py` content (file exists, currently empty of models), migration via `makemigrations`
- Modify: `apps/reports/metrics.py` (add `month_metrics`)
- Test: `tests/test_monthly_report.py`

**Interfaces:**
- Produces: `reports.MonthlyReport` — `month` (DateField, unique, always the 1st), `status` (choices `pending/generating/ready/failed`, default `pending`), `metrics` (JSONField default dict), `narrative` (TextField null), `pdf` (FileField `upload_to="reports/"`, blank), `generated_at` (DateTimeField null), `requested_by` (User FK, null — null means scheduled run).
- Produces: `metrics.month_metrics(month: date) -> dict` — JSON-serializable aggregate of the calendar month: keys `month` (`"YYYY-MM"`), `downtime_by_department`, `complaints_per_department`, `most_complained_devices`, `fault_category_counts`, `repairs_completed`, `open_workorders` (point-in-time count at generation), `delayed_repairs`, `per_engineer_resolved`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_monthly_report.py
from datetime import date, timedelta

import pytest
from django.utils import timezone

from apps.maintenance.models import WorkOrderStatus
from apps.reports import metrics
from apps.reports.models import MonthlyReport


def test_month_metrics_is_json_serializable(db, make_work_order):
    import json

    now = timezone.now()
    make_work_order(
        status=WorkOrderStatus.COMPLETED,
        repair_completed_at=now,
        fault_category="electrical",
    )
    month = date(now.year, now.month, 1)
    data = metrics.month_metrics(month)
    json.dumps(data)  # must not raise
    assert data["repairs_completed"] == 1
    assert data["month"] == f"{now:%Y-%m}"


def test_monthly_report_unique_per_month(db):
    MonthlyReport.objects.create(month=date(2026, 6, 1))
    with pytest.raises(Exception):
        MonthlyReport.objects.create(month=date(2026, 6, 1))
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_monthly_report.py -v`
Expected: FAIL — no `MonthlyReport`, no `month_metrics`.

- [ ] **Step 3: Implement**

```python
# apps/reports/models.py
from django.conf import settings
from django.db import models


class ReportStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    GENERATING = "generating", "Generating"
    READY = "ready", "Ready"
    FAILED = "failed", "Failed"


class MonthlyReport(models.Model):
    month = models.DateField(unique=True, help_text="First day of the month.")
    status = models.CharField(
        max_length=20, choices=ReportStatus.choices, default=ReportStatus.PENDING
    )
    metrics = models.JSONField(default=dict, blank=True)
    narrative = models.TextField(null=True, blank=True)
    pdf = models.FileField(upload_to="reports/", blank=True)
    generated_at = models.DateTimeField(null=True, blank=True)
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="reports_requested",
    )

    class Meta:
        ordering = ["-month"]

    def __str__(self):
        return f"Monthly report {self.month:%Y-%m} ({self.status})"
```

Append to `apps/reports/metrics.py`:

```python
def month_metrics(month):
    """All aggregates for one calendar month, JSON-serializable (spec §3).
    `month` is the first day of the month."""
    import calendar
    from datetime import datetime, timedelta

    from django.utils import timezone as tz

    start = tz.make_aware(datetime(month.year, month.month, 1))
    last_day = calendar.monthrange(month.year, month.month)[1]
    end = tz.make_aware(datetime(month.year, month.month, last_day)) + timedelta(
        days=1
    )
    downtime = critical_downtime_by_department(start, end)
    return {
        "month": f"{month:%Y-%m}",
        "downtime_by_department": {k: round(v, 1) for k, v in downtime.items()},
        "complaints_per_department": complaints_per_department(start, end),
        "most_complained_devices": most_complained_devices(start, end),
        "fault_category_counts": fault_category_counts(start, end),
        "repairs_completed": repairs_completed_count(start, end),
        "open_workorders": open_workorders_count(),
        "delayed_repairs": delayed_repairs(start, end),
        "per_engineer_resolved": per_engineer_resolved(start, end),
    }
```

```bash
uv run python manage.py makemigrations reports
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_monthly_report.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add apps/reports tests/test_monthly_report.py
git commit -m "feat: MonthlyReport model and month_metrics aggregation"
```

---

### Task 6: PDF rendering + report generation task

**Files:**
- Create: `apps/reports/pdf.py`, `templates/reports/pdf/monthly.html`
- Modify: `apps/ai/tasks.py`, `apps/ai/prompts.py`
- Test: `tests/test_report_generation.py`
- Modify: `pyproject.toml` via `uv add weasyprint`, `Dockerfile` (system libs)

**Interfaces:**
- Consumes: `month_metrics`, `MonthlyReport` (Task 5), `client.chat` (Task 1).
- Produces: `pdf.render_monthly_pdf(report) -> bytes` — renders `templates/reports/pdf/monthly.html` and converts via WeasyPrint (imported lazily inside the function).
- Produces: `tasks.generate_monthly_report(month_iso: str, requested_by_id: int | None = None)` — Procrastinate task, also periodic (cron `0 4 1 * *` → generates the *previous* month). Upserts the `MonthlyReport` for the month, sets `generating` → computes metrics → LLM narrative (`None` + still `ready` when `LLMUnavailable`) → renders PDF → saves file, `status=ready`, `generated_at=now`. On unexpected exception sets `status=failed` and re-raises (Procrastinate retries).
- Produces: `prompts.report_narrative_prompt(metrics_dict) -> list[dict]`.

- [ ] **Step 1: Add dependency + system libs**

```bash
uv add "weasyprint~=63.0"
```

In `Dockerfile`, before the `COPY pyproject.toml uv.lock ./` line, add WeasyPrint's runtime libraries:

```dockerfile
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz0b libharfbuzz-subset0 \
    && rm -rf /var/lib/apt/lists/*
```

- [ ] **Step 2: Write the failing tests**

```python
# tests/test_report_generation.py
from datetime import date

import pytest

from apps.ai import client, tasks
from apps.reports.models import MonthlyReport, ReportStatus


@pytest.fixture
def fake_pdf(monkeypatch):
    from apps.reports import pdf

    monkeypatch.setattr(pdf, "render_monthly_pdf", lambda report: b"%PDF-fake")


@pytest.fixture
def fake_llm(monkeypatch):
    monkeypatch.setattr(client, "chat", lambda messages, **kw: "Executive summary.")


def test_generate_creates_ready_report(db, fake_pdf, fake_llm):
    tasks.generate_monthly_report.func("2026-06")
    report = MonthlyReport.objects.get(month=date(2026, 6, 1))
    assert report.status == ReportStatus.READY
    assert report.narrative == "Executive summary."
    assert report.metrics["month"] == "2026-06"
    assert report.pdf.read() == b"%PDF-fake"


def test_generate_without_llm_still_ready(db, fake_pdf, monkeypatch):
    def _boom(messages, **kw):
        raise client.LLMUnavailable("down")

    monkeypatch.setattr(client, "chat", _boom)
    tasks.generate_monthly_report.func("2026-06")
    report = MonthlyReport.objects.get(month=date(2026, 6, 1))
    assert report.status == ReportStatus.READY and report.narrative is None


def test_generate_is_rerunnable(db, fake_pdf, fake_llm):
    tasks.generate_monthly_report.func("2026-06")
    tasks.generate_monthly_report.func("2026-06")
    assert MonthlyReport.objects.filter(month=date(2026, 6, 1)).count() == 1
```

(`.func(...)` calls the undecorated task body synchronously — the standard Procrastinate testing pattern; if the installed Procrastinate version spells it differently, check `procrastinate` docs for "testing tasks" and use that accessor.)

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/test_report_generation.py -v`
Expected: FAIL — no `generate_monthly_report` / `pdf` module.

- [ ] **Step 4: Implement**

```python
# apps/reports/pdf.py
"""PDF rendering. WeasyPrint imports stay inside the function: Windows dev
machines without GTK can still run everything else; tests monkeypatch this."""

from django.template.loader import render_to_string


def render_monthly_pdf(report) -> bytes:
    from weasyprint import HTML

    html = render_to_string(
        "reports/pdf/monthly.html", {"report": report, "m": report.metrics}
    )
    return HTML(string=html).write_pdf()
```

`templates/reports/pdf/monthly.html` (standalone print HTML — no base.html):

```html
<!doctype html>
<html>
<head>
<meta charset="utf-8">
<style>
  body { font-family: sans-serif; font-size: 12px; color: #111; }
  h1 { font-size: 20px; } h2 { font-size: 15px; margin-top: 18px; }
  table { width: 100%; border-collapse: collapse; margin-top: 6px; }
  th, td { border: 1px solid #ccc; padding: 4px 6px; text-align: left; }
  .muted { color: #666; }
</style>
</head>
<body>
  <h1>Monthly Maintenance Report — {{ m.month }}</h1>

  <h2>Executive summary</h2>
  {% if report.narrative %}<p>{{ report.narrative }}</p>
  {% else %}<p class="muted">Narrative unavailable (LLM offline at generation time).</p>{% endif %}

  <h2>Repairs completed</h2><p>{{ m.repairs_completed }}</p>

  <h2>Work orders still open (at generation time)</h2><p>{{ m.open_workorders }}</p>

  <h2>Critical-asset downtime (hours, by department)</h2>
  <table>{% for dept, hours in m.downtime_by_department.items %}
    <tr><td>{{ dept }}</td><td>{{ hours }}</td></tr>
  {% empty %}<tr><td class="muted" colspan="2">No downtime recorded.</td></tr>{% endfor %}</table>

  <h2>Complaints per department</h2>
  <table>{% for dept, n in m.complaints_per_department.items %}
    <tr><td>{{ dept }}</td><td>{{ n }}</td></tr>
  {% empty %}<tr><td class="muted" colspan="2">None.</td></tr>{% endfor %}</table>

  <h2>Most-complained devices</h2>
  <table>{% for row in m.most_complained_devices %}
    <tr><td>{{ row.0 }}</td><td>{{ row.1 }}</td></tr>
  {% empty %}<tr><td class="muted" colspan="2">None.</td></tr>{% endfor %}</table>

  <h2>Fault categories</h2>
  <table>{% for label, n in m.fault_category_counts.items %}
    <tr><td>{{ label }}</td><td>{{ n }}</td></tr>
  {% empty %}<tr><td class="muted" colspan="2">None.</td></tr>{% endfor %}</table>

  <h2>Delayed repairs</h2>
  <table>{% for d in m.delayed_repairs %}
    <tr><td>WO #{{ d.wo_id }}</td><td>{{ d.equipment }}</td><td>{{ d.latest_delay_note }}</td></tr>
  {% empty %}<tr><td class="muted" colspan="3">None flagged.</td></tr>{% endfor %}</table>

  <h2>Per-engineer resolved complaints</h2>
  <table>{% for e in m.per_engineer_resolved %}
    <tr><td>{{ e.name }} ({{ e.employee_id }})</td><td>{{ e.resolved_count }}</td></tr>
  {% empty %}<tr><td class="muted" colspan="2">None.</td></tr>{% endfor %}</table>
</body>
</html>
```

Append to `apps/ai/prompts.py`:

```python
def report_narrative_prompt(m):
    return [
        {
            "role": "system",
            "content": (
                "You are writing the executive summary of a hospital biomedical "
                "maintenance monthly report for management. 5-8 sentences, plain "
                "language, no bullet lists. Use only the numbers provided — "
                "never invent or recompute figures."
            ),
        },
        {
            "role": "user",
            "content": (
                f"Month: {m['month']}\n"
                f"Repairs completed: {m['repairs_completed']}\n"
                f"Critical-asset downtime hours by department: {m['downtime_by_department']}\n"
                f"Complaints per department: {m['complaints_per_department']}\n"
                f"Most complained devices: {m['most_complained_devices']}\n"
                f"Fault categories: {m['fault_category_counts']}\n"
                f"Delayed repairs: {[d['latest_delay_note'] for d in m['delayed_repairs']]}\n"
            ),
        },
    ]
```

Append to `apps/ai/tasks.py`:

```python
@app.periodic(cron="0 4 1 * *")
@app.task(name="ai.generate_monthly_report_scheduled", retry=3)
def generate_monthly_report_scheduled(timestamp=None):
    """On the 1st, generate last month's report."""
    from datetime import date, timedelta

    first_of_this_month = date.today().replace(day=1)
    previous = (first_of_this_month - timedelta(days=1)).replace(day=1)
    generate_monthly_report.defer(month_iso=f"{previous:%Y-%m}")


@app.task(name="ai.generate_monthly_report", retry=3)
def generate_monthly_report(month_iso, requested_by_id=None):
    from datetime import datetime

    from django.core.files.base import ContentFile
    from django.utils import timezone

    from apps.reports import metrics, pdf
    from apps.reports.models import MonthlyReport, ReportStatus

    from . import client, prompts

    month = datetime.strptime(month_iso, "%Y-%m").date()
    report, _ = MonthlyReport.objects.get_or_create(month=month)
    report.status = ReportStatus.GENERATING
    report.requested_by_id = requested_by_id
    report.save(update_fields=["status", "requested_by"])
    try:
        report.metrics = metrics.month_metrics(month)
        try:
            report.narrative = client.chat(
                prompts.report_narrative_prompt(report.metrics)
            )
        except client.LLMUnavailable:
            report.narrative = None
        report.pdf.save(
            f"monthly-{month_iso}.pdf",
            ContentFile(pdf.render_monthly_pdf(report)),
            save=False,
        )
        report.status = ReportStatus.READY
        report.generated_at = timezone.now()
        report.save()
    except Exception:
        report.status = ReportStatus.FAILED
        report.save(update_fields=["status"])
        raise
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_report_generation.py -v`
Expected: 3 PASS

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml uv.lock Dockerfile apps/reports apps/ai templates/reports/pdf tests/test_report_generation.py
git commit -m "feat: monthly report generation task with PDF and LLM narrative"
```

---

### Task 7: Reports UI — list, generate now, download

**Files:**
- Modify: `apps/reports/views.py`, `apps/reports/urls.py`, `templates/base.html` (sidebar link "Reports" in the engineer/admin nav block, next to the Dashboard link)
- Create: `templates/reports/report_list.html`
- Test: `tests/test_report_views.py`

**Interfaces:**
- Consumes: `MonthlyReport`, `tasks.generate_monthly_report.defer`.
- Produces: URLs `report_list` (GET), `report_generate` (POST, form field `month` = `YYYY-MM`), `report_download` (GET pk). All engineer/admin only. Download streams the stored PDF via `FileResponse` (role check enforced — no direct MEDIA serving).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_report_views.py
from datetime import date

import pytest
from django.core.files.base import ContentFile
from django.urls import reverse

from apps.reports.models import MonthlyReport, ReportStatus


@pytest.fixture
def ready_report(db):
    report = MonthlyReport.objects.create(
        month=date(2026, 6, 1), status=ReportStatus.READY
    )
    report.pdf.save("monthly-2026-06.pdf", ContentFile(b"%PDF-fake"))
    return report


def test_staff_blocked(client, staff_user):
    client.force_login(staff_user)
    assert client.get(reverse("report_list")).status_code == 403


def test_list_shows_reports(client, engineer, ready_report):
    client.force_login(engineer)
    response = client.get(reverse("report_list"))
    assert b"2026-06" in response.content


def test_generate_defers_task(client, engineer, monkeypatch, db):
    deferred = {}

    from apps.ai import tasks

    monkeypatch.setattr(
        tasks.generate_monthly_report, "defer", lambda **kw: deferred.update(kw)
    )
    client.force_login(engineer)
    response = client.post(reverse("report_generate"), {"month": "2026-06"})
    assert response.status_code == 302
    assert deferred == {"month_iso": "2026-06", "requested_by_id": engineer.id}


def test_download_streams_pdf(client, engineer, ready_report):
    client.force_login(engineer)
    response = client.get(reverse("report_download", args=[ready_report.pk]))
    assert response["Content-Type"] == "application/pdf"
    assert b"".join(response.streaming_content) == b"%PDF-fake"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_report_views.py -v`
Expected: FAIL — `NoReverseMatch: report_list`.

- [ ] **Step 3: Implement**

Append to `apps/reports/views.py`:

```python
import re

from django.http import FileResponse, Http404
from django.shortcuts import redirect

from .models import MonthlyReport


def _require_engineer_or_admin(user):
    if not user.is_engineer_or_admin:
        raise PermissionDenied


@login_required
def report_list(request):
    _require_engineer_or_admin(request.user)
    return render(
        request,
        "reports/report_list.html",
        {"reports": MonthlyReport.objects.all()},
    )


@login_required
def report_generate(request):
    _require_engineer_or_admin(request.user)
    from django.contrib import messages

    from apps.ai import tasks

    month = request.POST.get("month", "")
    if not re.fullmatch(r"\d{4}-\d{2}", month):
        messages.error(request, "Pick a month first.")
        return redirect("report_list")
    tasks.generate_monthly_report.defer(
        month_iso=month, requested_by_id=request.user.id
    )
    messages.success(request, f"Report for {month} queued — refresh in a minute.")
    return redirect("report_list")


@login_required
def report_download(request, pk):
    _require_engineer_or_admin(request.user)
    report = get_object_or_404(MonthlyReport, pk=pk)
    if not report.pdf:
        raise Http404
    return FileResponse(
        report.pdf.open("rb"),
        as_attachment=True,
        filename=f"monthly-{report.month:%Y-%m}.pdf",
        content_type="application/pdf",
    )
```

Append to `apps/reports/urls.py` urlpatterns:

```python
    path("reports/", views.report_list, name="report_list"),
    path("reports/generate/", views.report_generate, name="report_generate"),
    path("reports/<int:pk>/download/", views.report_download, name="report_download"),
```

`templates/reports/report_list.html`:

```html
{% extends "base.html" %}
{% block content %}
<div class="max-w-3xl mx-auto">
  <div class="flex items-center justify-between mb-4">
    <h1 class="text-xl font-semibold">Monthly reports</h1>
    <form method="post" action="{% url 'report_generate' %}" class="flex gap-2">
      {% csrf_token %}
      <input type="month" name="month" required class="input">
      <button type="submit" class="btn btn-primary">Generate now</button>
    </form>
  </div>
  <table class="w-full text-sm">
    <thead><tr><th>Month</th><th>Status</th><th>Generated</th><th></th></tr></thead>
    <tbody>
      {% for r in reports %}
      <tr>
        <td>{{ r.month|date:"Y-m" }}</td>
        <td><span class="badge">{{ r.get_status_display }}</span></td>
        <td>{{ r.generated_at|date:"Y-m-d H:i"|default:"—" }}</td>
        <td>{% if r.pdf %}<a class="link" href="{% url 'report_download' r.pk %}">Download PDF</a>{% endif %}</td>
      </tr>
      {% empty %}
      <tr><td colspan="4" class="text-muted">No reports yet — generate one above.</td></tr>
      {% endfor %}
    </tbody>
  </table>
</div>
{% endblock %}
```

Add a "Reports" link to the engineer/admin section of the sidebar in `templates/base.html`, pointing at `{% url 'report_list' %}` — copy the exact markup of the existing Dashboard nav item.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_report_views.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add apps/reports templates/reports/report_list.html templates/base.html tests/test_report_views.py
git commit -m "feat: reports page with generate-now and PDF download"
```

---

### Task 8: docker-compose ollama service + docs

**Files:**
- Modify: `docker-compose.yml`, `README.md`

- [ ] **Step 1: Add the ollama service and media volume**

In `docker-compose.yml`: add to `services:`

```yaml
  ollama:
    image: ollama/ollama:latest
    volumes:
      - ollama:/root/.ollama
```

Add `media:/app/media` to the `volumes:` lists of **web** and **worker** (reports PDFs must be visible to both), and add `ollama:` and `media:` under the top-level `volumes:` key.

- [ ] **Step 2: README**

Add an "AI features (Phase 2)" section to `README.md`, after the existing quick-start:

```markdown
## AI features (Phase 2)

The app talks to any OpenAI-compatible LLM endpoint — pick one via `.env`:

| Setup | .env |
|---|---|
| Bundled Ollama container (default) | nothing to change |
| Own vLLM server | `LLM_BASE_URL=http://your-host:8000/v1`, `LLM_MODEL=...` |
| Hospital LLM gateway | `LLM_BASE_URL=https://llm.hospital.example/v1`, `LLM_API_KEY=...` |

First start with the bundled container, pull the default model once:

    docker compose up -d ollama
    docker compose exec ollama ollama pull llama3.2:3b

Everything degrades gracefully with no LLM: reports generate without the
narrative, risk scores compute without explanations.
```

- [ ] **Step 3: Verify compose config parses, full suite, lint**

Run: `docker compose config >/dev/null && uv run pytest && uv run ruff check .`
Expected: all green.

- [ ] **Step 4: Commit**

```bash
git add docker-compose.yml README.md
git commit -m "feat: bundled ollama compose service and LLM setup docs"
```

---

### Task 9: PR

- [ ] **Step 1: Push and open the PR**

```bash
git push -u origin feature/ai-foundation
gh pr create --title "AI foundation: LLM backend, monthly PDF report, risk scoring" --body "Adds the ai app (OpenAI-compatible client configurable via env — Ollama/vLLM/hospital gateway), monthly management report (SQL metrics + LLM narrative + WeasyPrint PDF, scheduled + on-demand), and two-number admin-configurable risk scoring with high-risk narratives, surfaced on equipment detail and the dashboard. Spec: docs/superpowers/specs/2026-07-18-phase2-ai-and-adoption-design.md §2–§4.

Closes #7
Closes #8

🤖 Generated with [Claude Code](https://claude.com/claude-code)"
```
