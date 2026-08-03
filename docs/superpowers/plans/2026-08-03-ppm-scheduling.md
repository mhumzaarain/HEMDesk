# PPM Scheduling Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Per-device planned preventive maintenance — schedules with an interval and next-due date, append-only completion records, a due/overdue list, and a dashboard compliance panel (spec: `docs/superpowers/specs/2026-08-03-ppm-scheduling-design.md`, issue #17).

**Architecture:** Two new models in `apps/maintenance` (`PPMSchedule` — one mutable schedule per device; `PPMRecord` — immutable completion log). Two service functions with audit. Three function views following the existing maintenance view style. Dashboard metrics derived live from `next_due` — no background task.

**Tech Stack:** Django 5.2 server-rendered, PostgreSQL 16, pytest + pytest-django, Tailwind design-system classes (`card`, `badge-*`, `btn-*`), Alpine.js for the one conditional form field.

## Global Constraints

- Run tests with `uv run pytest -q`; lint with `uv run ruff check .` (E/F/I, line-length 88). Both must pass before every commit.
- Commit messages are single-line imperative (e.g. `feat: PPM models (#17)`).
- All state changes go through service functions with `transaction.atomic` + `audit.record`; views never write models directly.
- No hard deletes anywhere — models extend `NoDeleteModel` / `AppendOnlyModel` from `apps.core.models`.
- Role gating: mutating views require engineer/admin via the `_require_engineer(user)` helper already in `apps/maintenance/views.py`.
- Templates use existing design-system classes only (`card`, `card-hover`, `badge-working`, `badge-repair`, `badge-danger`, `badge-info`, `badge-muted`, `btn-ghost btn-sm`, `btn-warn btn-sm`, `link`, form input class `INPUT` from `apps/maintenance/forms.py`).
- Dates: use `django.utils.timezone.localdate()` for "today", never `date.today()`.
- Do NOT commit `pyproject.toml` / `uv.lock` — they carry an unrelated local change.

---

### Task 1: Models, month arithmetic, migration, admin

**Files:**
- Modify: `apps/maintenance/models.py` (append at end; add imports at top)
- Modify: `apps/maintenance/admin.py` (append)
- Create: migration via `makemigrations`
- Test: `tests/test_ppm_models.py` (create)

**Interfaces:**
- Consumes: `NoDeleteModel`, `AppendOnlyModel` from `apps.core.models`; `Equipment` from `apps.equipment.models`.
- Produces (used by every later task):
  - `PPMInterval(models.TextChoices)`: `MONTHLY="monthly"`, `QUARTERLY="quarterly"`, `BIANNUAL="biannual"`, `ANNUAL="annual"`
  - `PPM_INTERVAL_MONTHS: dict[str, int]` — `{"monthly": 1, "quarterly": 3, "biannual": 6, "annual": 12}`
  - `PPMOutcome(models.TextChoices)`: `PASSED="passed"`, `PASSED_WITH_REMARKS="passed_with_remarks"`, `FAILED="failed"`
  - `add_months(d: datetime.date, months: int) -> datetime.date` (month-end clamped)
  - `PPMSchedule` — fields `equipment` (OneToOne, related_name `"ppm_schedule"`), `interval`, `next_due`, `active`, `created_at`; properties `interval_months`, `is_overdue`, `is_due_soon`
  - `PPMRecord` — fields `schedule` (FK, related_name `"records"`), `due_date`, `performed_at`, `outcome`, `remarks`, `engineers` (M2M), `recorded_by`, `work_order` (nullable FK), `created_at`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_ppm_models.py`:

```python
from datetime import date

import pytest

from apps.maintenance.models import (
    PPMInterval,
    PPMOutcome,
    PPMRecord,
    PPMSchedule,
    add_months,
)


def test_add_months_simple():
    assert add_months(date(2026, 1, 15), 1) == date(2026, 2, 15)
    assert add_months(date(2026, 3, 10), 3) == date(2026, 6, 10)


def test_add_months_clamps_to_month_end():
    assert add_months(date(2026, 1, 31), 1) == date(2026, 2, 28)
    assert add_months(date(2024, 1, 31), 1) == date(2024, 2, 29)  # leap year
    assert add_months(date(2026, 8, 31), 1) == date(2026, 9, 30)


def test_add_months_year_rollover():
    assert add_months(date(2026, 11, 5), 3) == date(2027, 2, 5)
    assert add_months(date(2026, 6, 1), 12) == date(2027, 6, 1)


@pytest.fixture
def schedule(equipment):
    return PPMSchedule.objects.create(
        equipment=equipment,
        interval=PPMInterval.QUARTERLY,
        next_due=date(2026, 9, 1),
    )


def test_schedule_defaults_and_interval_months(schedule):
    assert schedule.active is True
    assert schedule.interval_months == 3


def test_schedule_cannot_be_deleted(schedule):
    with pytest.raises(TypeError):
        schedule.delete()


def test_record_is_append_only(schedule, engineer):
    record = PPMRecord.objects.create(
        schedule=schedule,
        due_date=schedule.next_due,
        performed_at=date(2026, 8, 1),
        outcome=PPMOutcome.PASSED,
        recorded_by=engineer,
    )
    record.remarks = "edited"
    with pytest.raises(TypeError):
        record.save()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_ppm_models.py -v`
Expected: FAIL — `ImportError: cannot import name 'PPMInterval'`

- [ ] **Step 3: Add models to `apps/maintenance/models.py`**

At the top of the file, extend the imports (the file already imports `settings`, `models`, `AppendOnlyModel`, `NoDeleteModel`, `Equipment`):

```python
import calendar
from datetime import date, timedelta

from django.utils import timezone
```

Append at the end of the file:

```python
class PPMInterval(models.TextChoices):
    MONTHLY = "monthly", "Monthly"
    QUARTERLY = "quarterly", "Quarterly"
    BIANNUAL = "biannual", "Every 6 months"
    ANNUAL = "annual", "Annual"


PPM_INTERVAL_MONTHS = {
    PPMInterval.MONTHLY: 1,
    PPMInterval.QUARTERLY: 3,
    PPMInterval.BIANNUAL: 6,
    PPMInterval.ANNUAL: 12,
}

PPM_DUE_SOON_DAYS = 30


class PPMOutcome(models.TextChoices):
    PASSED = "passed", "Passed"
    PASSED_WITH_REMARKS = "passed_with_remarks", "Passed with remarks"
    FAILED = "failed", "Failed"


def add_months(d: date, months: int) -> date:
    """d + months, clamping to the last day of the target month
    (Jan 31 + 1 month -> Feb 28/29)."""
    month_index = d.month - 1 + months
    year = d.year + month_index // 12
    month = month_index % 12 + 1
    day = min(d.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


class PPMSchedule(NoDeleteModel):
    equipment = models.OneToOneField(
        Equipment, on_delete=models.PROTECT, related_name="ppm_schedule"
    )
    interval = models.CharField(max_length=20, choices=PPMInterval.choices)
    next_due = models.DateField()
    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["next_due"]

    @property
    def interval_months(self) -> int:
        return PPM_INTERVAL_MONTHS[self.interval]

    @property
    def is_overdue(self) -> bool:
        return self.next_due < timezone.localdate()

    @property
    def is_due_soon(self) -> bool:
        today = timezone.localdate()
        return today <= self.next_due <= today + timedelta(days=PPM_DUE_SOON_DAYS)

    def __str__(self):
        return f"PPM {self.get_interval_display()} — {self.equipment}"


class PPMRecord(AppendOnlyModel):
    schedule = models.ForeignKey(
        PPMSchedule, on_delete=models.PROTECT, related_name="records"
    )
    due_date = models.DateField(
        help_text="Snapshot of the schedule's next_due when this PPM was recorded."
    )
    performed_at = models.DateField()
    outcome = models.CharField(max_length=30, choices=PPMOutcome.choices)
    remarks = models.TextField(blank=True)
    engineers = models.ManyToManyField(
        settings.AUTH_USER_MODEL, blank=True, related_name="ppm_records"
    )
    recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="ppm_records_recorded",
    )
    work_order = models.ForeignKey(
        WorkOrder,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="ppm_records",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-performed_at", "-created_at"]

    def __str__(self):
        return f"PPM on {self.performed_at} — {self.schedule.equipment}"
```

- [ ] **Step 4: Make the migration**

Run: `uv run python manage.py makemigrations maintenance`
Expected: one new migration creating `PPMSchedule` and `PPMRecord`.

- [ ] **Step 5: Register in admin**

Append to `apps/maintenance/admin.py` (add `PPMRecord, PPMSchedule` to the existing `from .models import ...`):

```python
@admin.register(PPMSchedule)
class PPMScheduleAdmin(admin.ModelAdmin):
    list_display = ("id", "equipment", "interval", "next_due", "active")
    list_filter = ("interval", "active")
    readonly_fields = [f.name for f in PPMSchedule._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(PPMRecord)
class PPMRecordAdmin(admin.ModelAdmin):
    list_display = ("id", "schedule", "performed_at", "outcome", "recorded_by")
    list_filter = ("outcome",)
    readonly_fields = [f.name for f in PPMRecord._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest tests/test_ppm_models.py -v`
Expected: all PASS. Then `uv run pytest -q` (whole suite) and `uv run ruff check .` — clean.

- [ ] **Step 7: Commit**

```bash
git add apps/maintenance/models.py apps/maintenance/admin.py apps/maintenance/migrations tests/test_ppm_models.py
git commit -m "feat: PPM schedule and record models (#17)"
```

---

### Task 2: Services — `set_ppm_schedule` and `complete_ppm`

**Files:**
- Modify: `apps/maintenance/services.py` (append; extend imports)
- Test: `tests/test_ppm_services.py` (create)

**Interfaces:**
- Consumes: Task 1 models; `_require_engineer_or_admin` from `apps.equipment.services`; `open_work_order` (already in this module); `WorkOrderStateError` from `apps.core.exceptions`; `audit` from `apps.core`.
- Produces:
  - `set_ppm_schedule(equipment, actor, interval, next_due, active=True) -> PPMSchedule`
  - `complete_ppm(schedule, actor, outcome, performed_at, engineers=(), remarks="", open_wo=False) -> PPMRecord`
  - Audit verbs: `"ppm.schedule_set"`, `"ppm.completed"`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_ppm_services.py`:

```python
from datetime import date, timedelta

import pytest
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import PermissionDenied
from django.utils import timezone

from apps.core.exceptions import WorkOrderStateError
from apps.core.models import AuditLog
from apps.equipment.models import EquipmentStatus
from apps.maintenance import services
from apps.maintenance.models import (
    PPMInterval,
    PPMOutcome,
    PPMRecord,
    PPMSchedule,
    WorkOrderStatus,
    add_months,
)


@pytest.fixture
def schedule(equipment, engineer):
    return services.set_ppm_schedule(
        equipment, engineer, PPMInterval.QUARTERLY, timezone.localdate()
    )


class TestSetPPMSchedule:
    def test_creates_schedule_with_audit(self, equipment, engineer):
        due = timezone.localdate() + timedelta(days=10)
        schedule = services.set_ppm_schedule(
            equipment, engineer, PPMInterval.MONTHLY, due
        )
        assert schedule.interval == PPMInterval.MONTHLY
        assert schedule.next_due == due
        assert schedule.active is True
        log = AuditLog.objects.get(verb="ppm.schedule_set")
        assert log.actor == engineer
        assert log.object_id == str(schedule.pk)

    def test_updates_existing_schedule_in_place(self, schedule, engineer):
        due = timezone.localdate() + timedelta(days=5)
        updated = services.set_ppm_schedule(
            schedule.equipment, engineer, PPMInterval.ANNUAL, due, active=False
        )
        assert updated.pk == schedule.pk
        assert updated.interval == PPMInterval.ANNUAL
        assert updated.active is False
        assert PPMSchedule.objects.count() == 1

    def test_staff_cannot_set_schedule(self, equipment, staff_user):
        with pytest.raises(PermissionDenied):
            services.set_ppm_schedule(
                equipment, staff_user, PPMInterval.MONTHLY, timezone.localdate()
            )

    def test_rejects_condemned_equipment(self, equipment, engineer):
        equipment.status = EquipmentStatus.CONDEMNED
        equipment.save(update_fields=["status"])
        with pytest.raises(WorkOrderStateError):
            services.set_ppm_schedule(
                equipment, engineer, PPMInterval.MONTHLY, timezone.localdate()
            )

    def test_rejects_bad_interval(self, equipment, engineer):
        with pytest.raises(ValueError):
            services.set_ppm_schedule(
                equipment, engineer, "weekly", timezone.localdate()
            )


class TestCompletePPM:
    def test_records_and_advances_next_due(self, schedule, engineer):
        performed = timezone.localdate() - timedelta(days=2)
        old_due = schedule.next_due
        record = services.complete_ppm(
            schedule, engineer, PPMOutcome.PASSED, performed, remarks="All good."
        )
        schedule.refresh_from_db()
        assert record.due_date == old_due
        assert record.performed_at == performed
        assert record.work_order is None
        assert engineer in record.engineers.all()
        # quarterly: +3 months from the performed date, not from old_due
        assert schedule.next_due == add_months(performed, 3)
        assert schedule.next_due != add_months(old_due, 3) or performed == old_due
        log = AuditLog.objects.get(verb="ppm.completed")
        assert log.actor == engineer

    def test_extra_engineers_are_recorded(self, schedule, engineer, engineer2):
        record = services.complete_ppm(
            schedule,
            engineer,
            PPMOutcome.PASSED,
            timezone.localdate(),
            engineers=[engineer2],
        )
        assert set(record.engineers.all()) == {engineer, engineer2}

    def test_rejects_future_performed_at(self, schedule, engineer):
        with pytest.raises(ValueError):
            services.complete_ppm(
                schedule,
                engineer,
                PPMOutcome.PASSED,
                timezone.localdate() + timedelta(days=1),
            )

    def test_rejects_inactive_schedule(self, schedule, engineer):
        PPMSchedule.objects.filter(pk=schedule.pk).update(active=False)
        schedule.refresh_from_db()
        with pytest.raises(WorkOrderStateError):
            services.complete_ppm(
                schedule, engineer, PPMOutcome.PASSED, timezone.localdate()
            )

    def test_rejects_bad_outcome(self, schedule, engineer):
        with pytest.raises(ValueError):
            services.complete_ppm(schedule, engineer, "ok", timezone.localdate())

    def test_staff_cannot_complete(self, schedule, staff_user):
        with pytest.raises(PermissionDenied):
            services.complete_ppm(
                schedule, staff_user, PPMOutcome.PASSED, timezone.localdate()
            )

    def test_blocked_while_work_order_active(self, schedule, engineer):
        wo = services.open_work_order(schedule.equipment, engineer)
        with pytest.raises(WorkOrderStateError) as exc:
            services.complete_ppm(
                schedule, engineer, PPMOutcome.PASSED, timezone.localdate()
            )
        assert f"WO #{wo.pk}" in str(exc.value)
        assert PPMRecord.objects.count() == 0

    def test_open_wo_requires_failed_outcome(self, schedule, engineer):
        with pytest.raises(ValueError):
            services.complete_ppm(
                schedule,
                engineer,
                PPMOutcome.PASSED,
                timezone.localdate(),
                open_wo=True,
            )

    def test_failed_with_open_wo_creates_linked_work_order(self, schedule, engineer):
        record = services.complete_ppm(
            schedule,
            engineer,
            PPMOutcome.FAILED,
            timezone.localdate(),
            open_wo=True,
            remarks="Leakage current above limit.",
        )
        assert record.work_order is not None
        assert record.work_order.status == WorkOrderStatus.OPEN
        assert record.work_order.equipment == schedule.equipment

    def test_failed_without_open_wo_records_only(self, schedule, engineer):
        record = services.complete_ppm(
            schedule, engineer, PPMOutcome.FAILED, timezone.localdate()
        )
        assert record.work_order is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_ppm_services.py -v`
Expected: FAIL — `AttributeError: module ... has no attribute 'set_ppm_schedule'`

- [ ] **Step 3: Implement the services**

In `apps/maintenance/services.py`, extend the `from .models import (...)` block with `PPMInterval`, `PPMOutcome`, `PPMRecord`, `PPMSchedule`, `add_months`. Append at the end of the file:

```python
@transaction.atomic
def set_ppm_schedule(equipment, actor, interval, next_due, active=True) -> PPMSchedule:
    _require_engineer_or_admin(actor)
    equipment.refresh_from_db()
    if equipment.status == EquipmentStatus.CONDEMNED:
        raise WorkOrderStateError("Cannot schedule PPM for condemned equipment.")
    if interval not in PPMInterval.values:
        raise ValueError("A valid PPM interval is required.")
    schedule, _created = PPMSchedule.objects.update_or_create(
        equipment=equipment,
        defaults={"interval": interval, "next_due": next_due, "active": active},
    )
    audit.record(
        actor,
        "ppm.schedule_set",
        schedule,
        {"interval": interval, "next_due": str(next_due), "active": active},
    )
    return schedule


@transaction.atomic
def complete_ppm(
    schedule, actor, outcome, performed_at, engineers=(), remarks="", open_wo=False
) -> PPMRecord:
    _require_engineer_or_admin(actor)
    if not schedule.active:
        raise WorkOrderStateError("This PPM schedule is inactive.")
    equipment = schedule.equipment
    equipment.refresh_from_db()
    if equipment.status == EquipmentStatus.CONDEMNED:
        raise WorkOrderStateError("This equipment is condemned.")
    if outcome not in PPMOutcome.values:
        raise ValueError("A valid PPM outcome is required.")
    if performed_at > timezone.localdate():
        raise ValueError("The performed date cannot be in the future.")
    if open_wo and outcome != PPMOutcome.FAILED:
        raise ValueError("A work order can only be opened for a failed PPM.")
    active_wo = equipment.work_orders.filter(
        status__in=ACTIVE_WORKORDER_STATUSES
    ).first()
    if active_wo:
        raise WorkOrderStateError(
            f"This equipment is under repair (WO #{active_wo.pk}) — "
            "complete or cancel it first."
        )
    work_order = open_work_order(equipment, actor) if open_wo else None
    record = PPMRecord.objects.create(
        schedule=schedule,
        due_date=schedule.next_due,
        performed_at=performed_at,
        outcome=outcome,
        remarks=remarks,
        recorded_by=actor,
        work_order=work_order,
    )
    record.engineers.add(actor, *engineers)
    schedule.next_due = add_months(performed_at, schedule.interval_months)
    schedule.save(update_fields=["next_due"])
    audit.record(
        actor,
        "ppm.completed",
        record,
        {
            "outcome": outcome,
            "performed_at": str(performed_at),
            "work_order": work_order.pk if work_order else None,
        },
    )
    return record
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_ppm_services.py tests/test_ppm_models.py -v`
Expected: all PASS. Then `uv run pytest -q` and `uv run ruff check .` — clean.

- [ ] **Step 5: Commit**

```bash
git add apps/maintenance/services.py tests/test_ppm_services.py
git commit -m "feat: PPM schedule and completion services (#17)"
```

---

### Task 3: Schedule form view + equipment-detail PPM panel

**Files:**
- Modify: `apps/maintenance/forms.py` (append)
- Modify: `apps/maintenance/views.py` (append)
- Modify: `apps/maintenance/urls.py` (append)
- Create: `templates/maintenance/ppm_schedule_form.html`
- Modify: `apps/equipment/views.py` (EquipmentDetailView.get_context_data)
- Modify: `templates/equipment/detail.html` (insert PPM panel)
- Test: `tests/test_ppm_views.py` (create)

**Interfaces:**
- Consumes: `set_ppm_schedule` (Task 2), `PPMInterval` (Task 1), `INPUT` css constant + `_require_engineer` helper (both already in maintenance app).
- Produces:
  - Form `PPMScheduleForm` (fields: `interval`, `next_due`, `active`)
  - View `ppm_schedule_edit(request, equipment_pk)`, URL name `"ppm_schedule_edit"` at `maintenance/ppm/schedule/<equipment_pk>/`
  - Equipment-detail context keys: `ppm_schedule` (schedule or None), `ppm_records` (iterable)
  - Template block in `detail.html` that Task 4's "Record PPM" button and Task 5's due list link back to (URL names `"ppm_complete"`, `"ppm_due_list"` — those views arrive in Tasks 4–5, so in THIS task the panel only renders the schedule info and the Set/Edit schedule button; the Record PPM button is added in Task 4).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_ppm_views.py`:

```python
from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.maintenance import services
from apps.maintenance.models import PPMInterval, PPMSchedule


@pytest.fixture
def schedule(equipment, engineer):
    return services.set_ppm_schedule(
        equipment, engineer, PPMInterval.QUARTERLY, timezone.localdate()
    )


class TestScheduleEditView:
    def test_get_renders_form(self, client, engineer, equipment):
        client.force_login(engineer)
        resp = client.get(reverse("ppm_schedule_edit", args=[equipment.pk]))
        assert resp.status_code == 200
        assert b"interval" in resp.content

    def test_post_creates_schedule(self, client, engineer, equipment):
        client.force_login(engineer)
        due = timezone.localdate() + timedelta(days=14)
        resp = client.post(
            reverse("ppm_schedule_edit", args=[equipment.pk]),
            {"interval": "monthly", "next_due": due.isoformat(), "active": "on"},
        )
        assert resp.status_code == 302
        schedule = PPMSchedule.objects.get(equipment=equipment)
        assert schedule.interval == PPMInterval.MONTHLY
        assert schedule.next_due == due

    def test_staff_blocked(self, client, staff_user, equipment):
        client.force_login(staff_user)
        resp = client.get(reverse("ppm_schedule_edit", args=[equipment.pk]))
        assert resp.status_code == 403


class TestEquipmentDetailPanel:
    def test_detail_shows_schedule(self, client, engineer, schedule):
        client.force_login(engineer)
        resp = client.get(
            reverse("equipment_detail", args=[schedule.equipment.pk])
        )
        assert resp.status_code == 200
        assert b"Preventive Maintenance" in resp.content
        assert b"Quarterly" in resp.content

    def test_detail_without_schedule_offers_setup(self, client, engineer, equipment):
        client.force_login(engineer)
        resp = client.get(reverse("equipment_detail", args=[equipment.pk]))
        assert b"No PPM schedule" in resp.content
        assert b"Set schedule" in resp.content

    def test_staff_sees_panel_without_buttons(self, client, staff_user, schedule):
        client.force_login(staff_user)
        resp = client.get(
            reverse("equipment_detail", args=[schedule.equipment.pk])
        )
        assert b"Preventive Maintenance" in resp.content
        assert b"Set schedule" not in resp.content
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_ppm_views.py -v`
Expected: FAIL — `NoReverseMatch: Reverse for 'ppm_schedule_edit' not found`

- [ ] **Step 3: Add the form**

Append to `apps/maintenance/forms.py` (add `PPMInterval` to the `.models` import):

```python
class PPMScheduleForm(forms.Form):
    interval = forms.ChoiceField(
        choices=PPMInterval.choices,
        widget=forms.Select(attrs={"class": INPUT}),
    )
    next_due = forms.DateField(
        widget=forms.DateInput(attrs={"type": "date", "class": INPUT})
    )
    active = forms.BooleanField(required=False, initial=True)
```

- [ ] **Step 4: Add view and URL**

Append to `apps/maintenance/views.py` (add `PPMScheduleForm` to the `.forms` import):

```python
@login_required
def ppm_schedule_edit(request, equipment_pk):
    _require_engineer(request.user)
    equipment = get_object_or_404(Equipment, pk=equipment_pk)
    schedule = getattr(equipment, "ppm_schedule", None)
    initial = (
        {
            "interval": schedule.interval,
            "next_due": schedule.next_due,
            "active": schedule.active,
        }
        if schedule
        else None
    )
    form = PPMScheduleForm(request.POST or None, initial=initial)
    if request.method == "POST" and form.is_valid():
        try:
            services.set_ppm_schedule(
                equipment,
                request.user,
                form.cleaned_data["interval"],
                form.cleaned_data["next_due"],
                active=form.cleaned_data["active"],
            )
        except (DomainError, ValueError) as exc:
            messages.error(request, str(exc))
        else:
            messages.success(request, "PPM schedule saved.")
        return redirect("equipment_detail", pk=equipment_pk)
    return render(
        request,
        "maintenance/ppm_schedule_form.html",
        {"equipment": equipment, "form": form, "schedule": schedule},
    )
```

Append to `apps/maintenance/urls.py` urlpatterns:

```python
path(
    "ppm/schedule/<int:equipment_pk>/",
    views.ppm_schedule_edit,
    name="ppm_schedule_edit",
),
```

- [ ] **Step 5: Create the template**

Create `templates/maintenance/ppm_schedule_form.html`:

```html
{% extends "base.html" %}
{% block title %}PPM schedule — {{ equipment.name }}{% endblock %}
{% block page_title %}PPM schedule{% endblock %}
{% block content %}
<div class="mx-auto max-w-lg">
  <h1 class="text-2xl font-bold">{% if schedule %}Edit{% else %}Set{% endif %} PPM schedule</h1>
  <p class="mt-1 text-sm text-slate-500 dark:text-slate-400">
    {{ equipment.name }} {{ equipment.model_number }} · {{ equipment.serial_number }}
  </p>
  <form method="post" class="card mt-5 space-y-4 p-5">
    {% csrf_token %}
    <div>
      <label class="mb-1 block text-sm font-medium">Interval</label>
      {{ form.interval }}
      {{ form.interval.errors }}
    </div>
    <div>
      <label class="mb-1 block text-sm font-medium">Next due</label>
      {{ form.next_due }}
      {{ form.next_due.errors }}
    </div>
    <label class="flex items-center gap-2 text-sm">
      {{ form.active }} Active
      <span class="text-slate-500 dark:text-slate-400">— untick to pause this schedule</span>
    </label>
    <div class="flex gap-2 border-t border-slate-100 pt-4 dark:border-slate-800">
      <button class="btn-warn btn-sm">Save schedule</button>
      <a href="{% url 'equipment_detail' equipment.pk %}" class="btn-ghost btn-sm">Cancel</a>
    </div>
  </form>
</div>
{% endblock %}
```

- [ ] **Step 6: Equipment detail — context and panel**

In `apps/equipment/views.py`, inside `EquipmentDetailView.get_context_data`, after the `ctx["completed_repair_count"] = ...` line add:

```python
schedule = getattr(eq, "ppm_schedule", None)
ctx["ppm_schedule"] = schedule
ctx["ppm_records"] = (
    schedule.records.select_related("work_order").prefetch_related("engineers")
    if schedule
    else []
)
```

In `templates/equipment/detail.html`, insert this card between the Work Orders card (`</div>` closing `card mt-6 p-5`) and the `{% include "ai/_assistant_panel.html" ... %}` line:

```html
<div class="card mt-6 p-5">
  <div class="mb-3 flex flex-wrap items-center gap-2">
    <h2 class="font-semibold">Preventive Maintenance</h2>
    {% if ppm_schedule and ppm_schedule.active %}
      {% if ppm_schedule.is_overdue %}<span class="badge-danger">Overdue</span>
      {% elif ppm_schedule.is_due_soon %}<span class="badge-repair">Due soon</span>
      {% else %}<span class="badge-working">On track</span>{% endif %}
    {% elif ppm_schedule %}<span class="badge-muted">Inactive</span>{% endif %}
    {% if can_engineer and equipment.status != 'condemned' %}
    <span class="ml-auto flex gap-2">
      <a href="{% url 'ppm_schedule_edit' equipment.pk %}" class="btn-ghost btn-sm">
        {% if ppm_schedule %}Edit schedule{% else %}Set schedule{% endif %}</a>
    </span>
    {% endif %}
  </div>
  {% if ppm_schedule %}
  <p class="text-sm text-slate-500 dark:text-slate-400">
    {{ ppm_schedule.get_interval_display }} · next due {{ ppm_schedule.next_due }}
  </p>
  <div class="mt-3 space-y-3">
    {% for rec in ppm_records %}
    <div class="flex flex-wrap items-center gap-2 rounded-lg border border-slate-100 px-4 py-3 text-sm dark:border-slate-800">
      <span class="font-medium">{{ rec.performed_at }}</span>
      {% if rec.outcome == 'passed' %}<span class="badge-working">{{ rec.get_outcome_display }}</span>
      {% elif rec.outcome == 'failed' %}<span class="badge-danger">{{ rec.get_outcome_display }}</span>
      {% else %}<span class="badge-info">{{ rec.get_outcome_display }}</span>{% endif %}
      {% if rec.work_order_id %}
        {% if can_engineer %}<a class="link" href="{% url 'workorder_detail' rec.work_order_id %}">WO #{{ rec.work_order_id }}</a>
        {% else %}<span>WO #{{ rec.work_order_id }}</span>{% endif %}
      {% endif %}
      {% if rec.remarks %}<span class="text-slate-500 dark:text-slate-400">“{{ rec.remarks }}”</span>{% endif %}
      <span class="ml-auto text-slate-500 dark:text-slate-400">
        by {% for e in rec.engineers.all %}{{ e.get_full_name|default:e.username }}{% if not forloop.last %}, {% endif %}{% endfor %}
      </span>
    </div>
    {% empty %}<p class="text-sm text-slate-500 dark:text-slate-400">No PPMs recorded yet.</p>{% endfor %}
  </div>
  {% else %}
  <p class="text-sm text-slate-500 dark:text-slate-400">No PPM schedule for this device.</p>
  {% endif %}
</div>
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `uv run pytest tests/test_ppm_views.py -v`
Expected: all PASS. Then `uv run pytest -q` and `uv run ruff check .` — clean.

- [ ] **Step 8: Commit**

```bash
git add apps/maintenance/forms.py apps/maintenance/views.py apps/maintenance/urls.py templates/maintenance/ppm_schedule_form.html apps/equipment/views.py templates/equipment/detail.html tests/test_ppm_views.py
git commit -m "feat: PPM schedule form and equipment detail panel (#17)"
```

---

### Task 4: Record-a-PPM view with failed→work-order flow

**Files:**
- Modify: `apps/maintenance/forms.py` (append)
- Modify: `apps/maintenance/views.py` (append)
- Modify: `apps/maintenance/urls.py` (append)
- Create: `templates/maintenance/ppm_complete.html`
- Modify: `templates/equipment/detail.html` (add Record PPM button)
- Test: `tests/test_ppm_views.py` (append)

**Interfaces:**
- Consumes: `complete_ppm` (Task 2), `PPMOutcome` (Task 1), `PPMSchedule`, detail-panel block (Task 3).
- Produces: form `PPMCompleteForm` (fields `performed_at`, `outcome`, `engineers`, `remarks`, `open_work_order`); view `ppm_complete(request, schedule_pk)`, URL name `"ppm_complete"` at `maintenance/ppm/<schedule_pk>/complete/`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_ppm_views.py`:

```python
class TestPPMCompleteView:
    def test_get_renders_form(self, client, engineer, schedule):
        client.force_login(engineer)
        resp = client.get(reverse("ppm_complete", args=[schedule.pk]))
        assert resp.status_code == 200
        assert b"outcome" in resp.content

    def test_post_passed_records_and_redirects(self, client, engineer, schedule):
        client.force_login(engineer)
        resp = client.post(
            reverse("ppm_complete", args=[schedule.pk]),
            {
                "performed_at": timezone.localdate().isoformat(),
                "outcome": "passed",
                "remarks": "Battery and alarms OK.",
            },
        )
        assert resp.status_code == 302
        record = schedule.records.get()
        assert record.outcome == "passed"
        schedule.refresh_from_db()
        assert schedule.next_due > timezone.localdate()

    def test_post_failed_with_open_wo_links_work_order(
        self, client, engineer, schedule
    ):
        client.force_login(engineer)
        resp = client.post(
            reverse("ppm_complete", args=[schedule.pk]),
            {
                "performed_at": timezone.localdate().isoformat(),
                "outcome": "failed",
                "open_work_order": "on",
            },
        )
        assert resp.status_code == 302
        record = schedule.records.get()
        assert record.work_order is not None

    def test_open_wo_with_passed_outcome_rejected_by_form(
        self, client, engineer, schedule
    ):
        client.force_login(engineer)
        resp = client.post(
            reverse("ppm_complete", args=[schedule.pk]),
            {
                "performed_at": timezone.localdate().isoformat(),
                "outcome": "passed",
                "open_work_order": "on",
            },
        )
        assert resp.status_code == 200  # re-rendered with form error
        assert schedule.records.count() == 0

    def test_blocked_when_wo_active_shows_error(
        self, client, engineer, schedule, make_work_order
    ):
        make_work_order(eq=schedule.equipment)
        client.force_login(engineer)
        resp = client.post(
            reverse("ppm_complete", args=[schedule.pk]),
            {
                "performed_at": timezone.localdate().isoformat(),
                "outcome": "passed",
            },
            follow=True,
        )
        assert b"under repair" in resp.content
        assert schedule.records.count() == 0

    def test_staff_blocked(self, client, staff_user, schedule):
        client.force_login(staff_user)
        resp = client.get(reverse("ppm_complete", args=[schedule.pk]))
        assert resp.status_code == 403
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_ppm_views.py -v -k Complete`
Expected: FAIL — `NoReverseMatch: Reverse for 'ppm_complete' not found`

- [ ] **Step 3: Add the form**

Append to `apps/maintenance/forms.py` (add `PPMOutcome` to the `.models` import; `get_user_model` and `Roles` are already imported):

```python
class PPMCompleteForm(forms.Form):
    performed_at = forms.DateField(
        widget=forms.DateInput(attrs={"type": "date", "class": INPUT})
    )
    outcome = forms.ChoiceField(
        choices=PPMOutcome.choices, widget=forms.RadioSelect
    )
    engineers = forms.ModelMultipleChoiceField(
        queryset=get_user_model().objects.filter(
            role__in=[Roles.ENGINEER, Roles.ADMIN], is_active=True
        ),
        required=False,
        widget=forms.CheckboxSelectMultiple,
        help_text="Tick every engineer who performed this PPM.",
    )
    remarks = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={"rows": 3, "class": INPUT}),
    )
    open_work_order = forms.BooleanField(required=False)

    def clean(self):
        data = super().clean()
        if data.get("open_work_order") and data.get("outcome") != PPMOutcome.FAILED:
            raise forms.ValidationError(
                "A work order can only be opened when the PPM failed."
            )
        return data
```

- [ ] **Step 4: Add view and URL**

Append to `apps/maintenance/views.py` (add `PPMCompleteForm` to the `.forms` import and `PPMSchedule` to the `.models` import; also `from django.utils import timezone` at the top):

```python
@login_required
def ppm_complete(request, schedule_pk):
    _require_engineer(request.user)
    schedule = get_object_or_404(
        PPMSchedule.objects.select_related("equipment"), pk=schedule_pk
    )
    form = PPMCompleteForm(
        request.POST or None, initial={"performed_at": timezone.localdate()}
    )
    if request.method == "POST" and form.is_valid():
        try:
            services.complete_ppm(
                schedule,
                request.user,
                form.cleaned_data["outcome"],
                form.cleaned_data["performed_at"],
                engineers=form.cleaned_data["engineers"],
                remarks=form.cleaned_data["remarks"],
                open_wo=form.cleaned_data["open_work_order"],
            )
        except (DomainError, ValueError) as exc:
            messages.error(request, str(exc))
        else:
            messages.success(request, "PPM recorded.")
        return redirect("equipment_detail", pk=schedule.equipment_id)
    return render(
        request,
        "maintenance/ppm_complete.html",
        {"schedule": schedule, "form": form},
    )
```

Append to `apps/maintenance/urls.py` urlpatterns:

```python
path("ppm/<int:schedule_pk>/complete/", views.ppm_complete, name="ppm_complete"),
```

- [ ] **Step 5: Create the template**

Create `templates/maintenance/ppm_complete.html` (Alpine.js `x-data`/`x-show` reveals the work-order checkbox only for a failed outcome):

```html
{% extends "base.html" %}
{% block title %}Record PPM — {{ schedule.equipment.name }}{% endblock %}
{% block page_title %}Record PPM{% endblock %}
{% block content %}
<div class="mx-auto max-w-lg">
  <h1 class="text-2xl font-bold">Record PPM</h1>
  <p class="mt-1 text-sm text-slate-500 dark:text-slate-400">
    {{ schedule.equipment.name }} {{ schedule.equipment.model_number }} ·
    {{ schedule.equipment.serial_number }} ·
    {{ schedule.get_interval_display }} · due {{ schedule.next_due }}
  </p>
  {% if form.non_field_errors %}
  <div class="mt-4 rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-800 dark:border-red-500/30 dark:bg-red-500/10 dark:text-red-300">
    {{ form.non_field_errors }}
  </div>
  {% endif %}
  <form method="post" class="card mt-5 space-y-4 p-5"
        x-data="{ outcome: '{{ form.outcome.value|default:'' }}' }">
    {% csrf_token %}
    <div>
      <label class="mb-1 block text-sm font-medium">Date performed</label>
      {{ form.performed_at }}
      {{ form.performed_at.errors }}
    </div>
    <div>
      <label class="mb-1 block text-sm font-medium">Outcome</label>
      <div class="space-y-1.5 text-sm">
        {% for radio in form.outcome %}
        <label class="flex items-center gap-2">
          <input type="radio" name="{{ radio.data.name }}" value="{{ radio.data.value }}"
                 x-model="outcome" {% if radio.data.selected %}checked{% endif %}>
          {{ radio.choice_label }}
        </label>
        {% endfor %}
      </div>
      {{ form.outcome.errors }}
    </div>
    <div x-show="outcome === 'failed'" x-cloak
         class="rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm dark:border-amber-500/30 dark:bg-amber-500/10">
      <label class="flex items-center gap-2">
        {{ form.open_work_order }} Open a work order for this fault
      </label>
    </div>
    <div>
      <label class="mb-1 block text-sm font-medium">Engineers</label>
      <div class="text-sm">{{ form.engineers }}</div>
      <p class="mt-1 text-xs text-slate-500 dark:text-slate-400">{{ form.engineers.help_text }}</p>
    </div>
    <div>
      <label class="mb-1 block text-sm font-medium">Remarks</label>
      {{ form.remarks }}
    </div>
    <div class="flex gap-2 border-t border-slate-100 pt-4 dark:border-slate-800">
      <button class="btn-warn btn-sm">Record PPM</button>
      <a href="{% url 'equipment_detail' schedule.equipment_id %}" class="btn-ghost btn-sm">Cancel</a>
    </div>
  </form>
</div>
{% endblock %}
```

- [ ] **Step 6: Add the Record PPM button to the detail panel**

In `templates/equipment/detail.html`, inside the `<span class="ml-auto flex gap-2">` added in Task 3, after the Set/Edit schedule link add:

```html
{% if ppm_schedule and ppm_schedule.active %}
<a href="{% url 'ppm_complete' ppm_schedule.pk %}" class="btn-warn btn-sm">Record PPM</a>
{% endif %}
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `uv run pytest tests/test_ppm_views.py -v`
Expected: all PASS. Then `uv run pytest -q` and `uv run ruff check .` — clean.

- [ ] **Step 8: Commit**

```bash
git add apps/maintenance/forms.py apps/maintenance/views.py apps/maintenance/urls.py templates/maintenance/ppm_complete.html templates/equipment/detail.html tests/test_ppm_views.py
git commit -m "feat: record-PPM flow with failed-to-work-order handoff (#17)"
```

---

### Task 5: PPM due list + home card

**Files:**
- Modify: `apps/maintenance/views.py` (append)
- Modify: `apps/maintenance/urls.py` (append)
- Create: `templates/maintenance/ppm_due_list.html`
- Modify: `templates/home.html` (engineer card)
- Test: `tests/test_ppm_views.py` (append)

**Interfaces:**
- Consumes: `PPMSchedule`, `PPM_DUE_SOON_DAYS` (Task 1); `Department` from `apps.equipment.models`; `EquipmentStatus`.
- Produces: view `ppm_due_list(request)`, URL name `"ppm_due_list"` at `maintenance/ppm/`; context keys `overdue`, `due_soon`, `departments`, `selected_department`, `unscheduled_count`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_ppm_views.py` (module already imports `services`, `PPMInterval`, `timezone`, `timedelta`, `reverse`):

```python
class TestDueListView:
    @pytest.fixture
    def three_schedules(self, make_equipment, engineer, department2):
        today = timezone.localdate()
        overdue_eq = make_equipment(serial_number="SN-PPM-1")
        soon_eq = make_equipment(serial_number="SN-PPM-2", department=department2)
        later_eq = make_equipment(serial_number="SN-PPM-3")
        s1 = services.set_ppm_schedule(
            overdue_eq, engineer, PPMInterval.MONTHLY, today - timedelta(days=5)
        )
        s2 = services.set_ppm_schedule(
            soon_eq, engineer, PPMInterval.MONTHLY, today + timedelta(days=10)
        )
        s3 = services.set_ppm_schedule(
            later_eq, engineer, PPMInterval.ANNUAL, today + timedelta(days=200)
        )
        return s1, s2, s3

    def test_buckets(self, client, engineer, three_schedules):
        client.force_login(engineer)
        resp = client.get(reverse("ppm_due_list"))
        assert resp.status_code == 200
        overdue = [s.pk for s in resp.context["overdue"]]
        due_soon = [s.pk for s in resp.context["due_soon"]]
        s1, s2, s3 = three_schedules
        assert overdue == [s1.pk]
        assert due_soon == [s2.pk]
        assert s3.pk not in overdue + due_soon

    def test_department_filter(self, client, engineer, three_schedules, department2):
        client.force_login(engineer)
        resp = client.get(
            reverse("ppm_due_list"), {"department": str(department2.pk)}
        )
        s1, s2, s3 = three_schedules
        assert [s.pk for s in resp.context["due_soon"]] == [s2.pk]
        assert list(resp.context["overdue"]) == []

    def test_inactive_schedules_hidden(self, client, engineer, three_schedules):
        s1, _, _ = three_schedules
        services.set_ppm_schedule(
            s1.equipment, engineer, s1.interval, s1.next_due, active=False
        )
        client.force_login(engineer)
        resp = client.get(reverse("ppm_due_list"))
        assert list(resp.context["overdue"]) == []

    def test_unscheduled_count(self, client, engineer, three_schedules, equipment):
        # `equipment` fixture device has no schedule
        client.force_login(engineer)
        resp = client.get(reverse("ppm_due_list"))
        assert resp.context["unscheduled_count"] == 1

    def test_staff_blocked(self, client, staff_user):
        client.force_login(staff_user)
        assert client.get(reverse("ppm_due_list")).status_code == 403
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_ppm_views.py -v -k DueList`
Expected: FAIL — `NoReverseMatch: Reverse for 'ppm_due_list' not found`

- [ ] **Step 3: Add view and URL**

Append to `apps/maintenance/views.py` (extend imports: `from datetime import timedelta`; add `PPM_DUE_SOON_DAYS`, `PPMSchedule` to the `.models` import — `PPMSchedule` was added in Task 4; add `Department`, `EquipmentStatus` to the `apps.equipment.models` import; add `Q` usage stays as is):

```python
@login_required
def ppm_due_list(request):
    _require_engineer(request.user)
    today = timezone.localdate()
    qs = (
        PPMSchedule.objects.filter(active=True)
        .exclude(equipment__status=EquipmentStatus.CONDEMNED)
        .select_related("equipment__department")
        .order_by("next_due")
    )
    selected_department = request.GET.get("department", "")
    if selected_department:
        qs = qs.filter(equipment__department_id=selected_department)
    unscheduled_count = (
        Equipment.objects.exclude(status=EquipmentStatus.CONDEMNED)
        .filter(Q(ppm_schedule__isnull=True) | Q(ppm_schedule__active=False))
        .count()
    )
    return render(
        request,
        "maintenance/ppm_due_list.html",
        {
            "overdue": qs.filter(next_due__lt=today),
            "due_soon": qs.filter(
                next_due__gte=today,
                next_due__lte=today + timedelta(days=PPM_DUE_SOON_DAYS),
            ),
            "departments": Department.objects.all(),
            "selected_department": selected_department,
            "unscheduled_count": unscheduled_count,
        },
    )
```

Append to `apps/maintenance/urls.py` urlpatterns:

```python
path("ppm/", views.ppm_due_list, name="ppm_due_list"),
```

- [ ] **Step 4: Create the template**

Create `templates/maintenance/ppm_due_list.html`:

```html
{% extends "base.html" %}
{% block title %}PPM due{% endblock %}
{% block page_title %}PPM{% endblock %}
{% block content %}
<div class="mb-5 flex flex-wrap items-center justify-between gap-3">
  <div>
    <h1 class="text-2xl font-bold">Planned Preventive Maintenance</h1>
    <p class="mt-1 text-sm text-slate-500 dark:text-slate-400">
      Overdue and upcoming PPMs (next 30 days).
      {% if unscheduled_count %}{{ unscheduled_count }} device{{ unscheduled_count|pluralize }} without an active PPM schedule.{% endif %}
    </p>
  </div>
  <form method="get" class="flex items-center gap-2 text-sm">
    <select name="department" class="rounded border border-slate-300 px-2 py-1.5">
      <option value="">All departments</option>
      {% for d in departments %}
      <option value="{{ d.pk }}" {% if selected_department == d.pk|stringformat:"s" %}selected{% endif %}>{{ d.name }}</option>
      {% endfor %}
    </select>
    <button class="btn-ghost btn-sm">Filter</button>
  </form>
</div>
<div class="card p-5">
  <h2 class="mb-3 font-semibold">Overdue <span class="badge-danger">{{ overdue|length }}</span></h2>
  <div class="space-y-3">
    {% for s in overdue %}
    <div class="flex flex-wrap items-center gap-2 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm dark:border-red-500/30 dark:bg-red-500/10">
      <a class="link" href="{% url 'equipment_detail' s.equipment_id %}">{{ s.equipment }}</a>
      <span class="text-slate-500 dark:text-slate-400">{{ s.equipment.department }}</span>
      <span class="badge-muted">{{ s.get_interval_display }}</span>
      <span class="ml-auto font-medium text-red-700 dark:text-red-300">due {{ s.next_due }}</span>
      <a href="{% url 'ppm_complete' s.pk %}" class="btn-warn btn-sm">Record PPM</a>
    </div>
    {% empty %}<p class="text-sm text-slate-500 dark:text-slate-400">Nothing overdue. 🎉</p>{% endfor %}
  </div>
</div>
<div class="card mt-6 p-5">
  <h2 class="mb-3 font-semibold">Due soon <span class="badge-repair">{{ due_soon|length }}</span></h2>
  <div class="space-y-3">
    {% for s in due_soon %}
    <div class="flex flex-wrap items-center gap-2 rounded-lg border border-slate-100 px-4 py-3 text-sm dark:border-slate-800">
      <a class="link" href="{% url 'equipment_detail' s.equipment_id %}">{{ s.equipment }}</a>
      <span class="text-slate-500 dark:text-slate-400">{{ s.equipment.department }}</span>
      <span class="badge-muted">{{ s.get_interval_display }}</span>
      <span class="ml-auto text-slate-500 dark:text-slate-400">due {{ s.next_due }}</span>
      <a href="{% url 'ppm_complete' s.pk %}" class="btn-warn btn-sm">Record PPM</a>
    </div>
    {% empty %}<p class="text-sm text-slate-500 dark:text-slate-400">Nothing due in the next 30 days.</p>{% endfor %}
  </div>
</div>
{% endblock %}
```

- [ ] **Step 5: Add the home card**

In `templates/home.html`, inside the `{% if user.is_engineer_or_admin %}` block, after the Dashboard card `</a>` add:

```html
<a href="{% url 'ppm_due_list' %}" class="card card-hover group p-5">
  <span class="flex size-10 items-center justify-center rounded-lg bg-teal-100 text-teal-700 transition group-hover:scale-105 dark:bg-teal-500/15 dark:text-teal-300">
    <svg class="size-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M8 2v4"/><path d="M16 2v4"/><rect width="18" height="18" x="3" y="4" rx="2"/><path d="M3 10h18"/><path d="m9 16 2 2 4-4"/></svg>
  </span>
  <h2 class="mt-3 font-semibold">PPM schedule</h2>
  <p class="mt-1 text-sm text-slate-500 dark:text-slate-400">Planned preventive maintenance — what's due and what's overdue.</p>
</a>
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest tests/test_ppm_views.py -v`
Expected: all PASS. Then `uv run pytest -q` and `uv run ruff check .` — clean.

- [ ] **Step 7: Commit**

```bash
git add apps/maintenance/views.py apps/maintenance/urls.py templates/maintenance/ppm_due_list.html templates/home.html tests/test_ppm_views.py
git commit -m "feat: PPM due list with department filter and home card (#17)"
```

---

### Task 6: Dashboard metrics + PPM compliance panel

**Files:**
- Modify: `apps/reports/metrics.py` (append)
- Modify: `apps/reports/views.py` (dashboard context)
- Modify: `templates/reports/dashboard.html` (panel)
- Test: `tests/test_ppm_metrics.py` (create)

**Interfaces:**
- Consumes: `PPMSchedule`, `PPM_DUE_SOON_DAYS` (Task 1); URL name `"ppm_due_list"` (Task 5).
- Produces: `ppm_due_counts() -> dict` with keys `"overdue"`, `"due_soon"` (ints); `ppm_overdue_by_department() -> dict[str, int]`; dashboard context keys `ppm` and `ppm_overdue_depts`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_ppm_metrics.py`:

```python
from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.maintenance import services
from apps.maintenance.models import PPMInterval
from apps.reports import metrics


@pytest.fixture
def schedules(make_equipment, engineer, department, department2):
    today = timezone.localdate()
    a = make_equipment(serial_number="SN-M-1")  # department (ICU)
    b = make_equipment(serial_number="SN-M-2", department=department2)
    c = make_equipment(serial_number="SN-M-3", department=department2)
    services.set_ppm_schedule(
        a, engineer, PPMInterval.MONTHLY, today - timedelta(days=3)
    )
    services.set_ppm_schedule(
        b, engineer, PPMInterval.MONTHLY, today - timedelta(days=1)
    )
    services.set_ppm_schedule(
        c, engineer, PPMInterval.MONTHLY, today + timedelta(days=7)
    )


def test_ppm_due_counts(schedules):
    counts = metrics.ppm_due_counts()
    assert counts == {"overdue": 2, "due_soon": 1}


def test_ppm_due_counts_empty(db):
    assert metrics.ppm_due_counts() == {"overdue": 0, "due_soon": 0}


def test_ppm_overdue_by_department(schedules):
    rows = metrics.ppm_overdue_by_department()
    assert rows == {"ICU": 1, "Radiology": 1}


def test_dashboard_includes_ppm_panel(client, admin_user, schedules):
    client.force_login(admin_user)
    resp = client.get(reverse("dashboard"))
    assert resp.status_code == 200
    assert b"PPM compliance" in resp.content
    assert resp.context["ppm"] == {"overdue": 2, "due_soon": 1}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_ppm_metrics.py -v`
Expected: FAIL — `AttributeError: module ... has no attribute 'ppm_due_counts'`

- [ ] **Step 3: Add the metric functions**

Append to `apps/reports/metrics.py` (extend imports at top: `from datetime import timedelta`, `from django.utils import timezone`, and add `PPM_DUE_SOON_DAYS, PPMSchedule` to the `apps.maintenance.models` import):

```python
def _active_ppm_schedules():
    return PPMSchedule.objects.filter(active=True).exclude(
        equipment__status=EquipmentStatus.CONDEMNED
    )


def ppm_due_counts():
    today = timezone.localdate()
    qs = _active_ppm_schedules()
    return {
        "overdue": qs.filter(next_due__lt=today).count(),
        "due_soon": qs.filter(
            next_due__gte=today,
            next_due__lte=today + timedelta(days=PPM_DUE_SOON_DAYS),
        ).count(),
    }


def ppm_overdue_by_department():
    rows = (
        _active_ppm_schedules()
        .filter(next_due__lt=timezone.localdate())
        .values("equipment__department__name")
        .annotate(n=Count("id"))
        .order_by("-n")
    )
    return {r["equipment__department__name"]: r["n"] for r in rows}
```

- [ ] **Step 4: Wire into the dashboard view**

In `apps/reports/views.py` `dashboard()`, add to the `context` dict:

```python
"ppm": metrics.ppm_due_counts(),
"ppm_overdue_depts": metrics.ppm_overdue_by_department(),
```

- [ ] **Step 5: Add the panel to the dashboard template**

In `templates/reports/dashboard.html`, inside the `<div class="mt-6 grid gap-6 md:grid-cols-2">` grid, after the "High-risk devices" card add:

```html
<div class="card p-5">
  <h2 class="mb-3 font-semibold">PPM compliance</h2>
  <div class="flex gap-8">
    <div>
      <span class="text-3xl font-bold tabular-nums {% if ppm.overdue %}text-red-600 dark:text-red-400{% endif %}">{{ ppm.overdue }}</span>
      <p class="mt-1 text-sm text-slate-500 dark:text-slate-400">Overdue</p>
    </div>
    <div>
      <span class="text-3xl font-bold tabular-nums">{{ ppm.due_soon }}</span>
      <p class="mt-1 text-sm text-slate-500 dark:text-slate-400">Due in 30 days</p>
    </div>
  </div>
  {% if ppm_overdue_depts %}
  <ul class="mt-3 space-y-1 text-sm">
    {% for dept, n in ppm_overdue_depts.items %}
    <li class="flex justify-between"><span>{{ dept }}</span><span class="badge-danger">{{ n }}</span></li>
    {% endfor %}
  </ul>
  {% endif %}
  <a class="link mt-3 inline-block text-sm" href="{% url 'ppm_due_list' %}">Open PPM due list →</a>
</div>
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest tests/test_ppm_metrics.py -v`
Expected: all PASS. Then `uv run pytest -q` and `uv run ruff check .` — clean.

- [ ] **Step 7: Commit**

```bash
git add apps/reports/metrics.py apps/reports/views.py templates/reports/dashboard.html tests/test_ppm_metrics.py
git commit -m "feat: PPM compliance metrics and dashboard panel (#17)"
```

---

### Task 7: Demo data + full verification

**Files:**
- Modify: `apps/core/management/commands/seed_demo.py`

**Interfaces:**
- Consumes: `set_ppm_schedule`, `complete_ppm` (Task 2); `PPMInterval`, `PPMOutcome`, `PPMSchedule`, `PPMRecord` (Task 1).

- [ ] **Step 1: Extend seed_demo**

In `apps/core/management/commands/seed_demo.py`:

Extend the maintenance imports:

```python
from apps.maintenance.models import (
    Complaint,
    FaultCategory,
    PPMInterval,
    PPMOutcome,
    PPMRecord,
    PPMSchedule,
    WorkOrder,
)
from apps.maintenance.services import (
    add_remark,
    complete_ppm,
    complete_work_order,
    lodge_complaint,
    open_work_order,
    set_ppm_schedule,
    start_repair,
)
```

Insert this block after the condemned-devices loop and before the final `self.stdout.write`:

```python
# PPM schedules for ~15 devices; past completions give a natural
# mix of overdue / due-soon / on-track next_due dates.
ppm_pool = [d for d in devices if d.status == "working"]
for device in random.sample(ppm_pool, min(15, len(ppm_pool))):
    device.refresh_from_db()
    if device.status != "working":
        continue
    engineer = random.choice(engineers)
    interval = random.choice(
        [PPMInterval.MONTHLY, PPMInterval.QUARTERLY, PPMInterval.BIANNUAL]
    )
    schedule = set_ppm_schedule(
        device,
        engineer,
        interval,
        now.date() + timedelta(days=random.randint(-30, 45)),
    )
    if random.random() < 0.6:
        performed = now.date() - timedelta(days=random.randint(20, 100))
        complete_ppm(
            schedule,
            engineer,
            random.choice(
                [PPMOutcome.PASSED, PPMOutcome.PASSED, PPMOutcome.PASSED_WITH_REMARKS]
            ),
            performed,
            remarks="Routine PPM completed.",
        )
```

Update the final summary write to include PPM counts:

```python
self.stdout.write(
    self.style.SUCCESS(
        f"Seeded {Equipment.objects.count()} devices, "
        f"{Complaint.objects.count()} complaints, "
        f"{WorkOrder.objects.count()} work orders, "
        f"{PPMSchedule.objects.count()} PPM schedules, "
        f"{PPMRecord.objects.count()} PPM records. "
        f"Logins: admin, engineer1, staff1 — password: {demo_password}"
    )
)
```

- [ ] **Step 2: Verify the seed runs**

Run against a scratch database (never the dev one):

```bash
uv run python manage.py migrate
uv run pytest -q
uv run ruff check .
```

(The seed path itself is exercised by running `seed_demo` only if a clean DB is available; if the dev DB has data, the command refuses safely by design — do not wipe anything. The pytest suite is the required gate.)

- [ ] **Step 3: Commit**

```bash
git add apps/core/management/commands/seed_demo.py
git commit -m "feat: seed demo PPM schedules and records (#17)"
```

---

## Final whole-branch checks (controller)

- [ ] `uv run pytest -q` — entire suite green.
- [ ] `uv run ruff check .` — clean.
- [ ] `git log --oneline main..` — one commit per task, single-line messages.
- [ ] Push branch, open PR titled `feat: PPM scheduling (#17)` with `Closes #17` in the body. The user merges their own PRs — do not merge.
