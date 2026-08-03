# Accessory Replacement & WO Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** One-action accessory replacement/repair recorded on work orders (append-only `AccessoryEvent`), replacement metrics on the equipment page and dashboard, and restock visibility — per the approved spec `docs/superpowers/specs/2026-08-03-accessory-replacement-design.md` (issue #31).

**Architecture:** A new append-only `AccessoryEvent` model (mirroring `StatusEvent`) is the single record of every replace/repair, always tied to a work order. Two new service functions own the writes; the WO detail page gains an Accessories card with Mark faulty / Repair / Replace actions; metrics are plain ORM queries in `apps/reports/metrics.py`.

**Tech Stack:** Django 5.2, PostgreSQL, pytest-django, Tailwind-style utility CSS, ruff.

## Global Constraints

- Branch: `feature/accessory-replacement` (already created; commit directly on it).
- Python: `.venv/Scripts/python.exe` from the repo root for everything (pytest, manage.py, ruff).
- Lint: `.venv/Scripts/python.exe -m ruff check apps tests` must pass (88 cols, double quotes, isort; migrations excluded).
- Replacement/repair happens ONLY inside an ACTIVE work order (`WorkOrder.is_active`); violations raise `AccessoryStateError` (from `apps.core.exceptions`); views catch `DomainError` → `messages.error(request, str(exc))`.
- All writes through services: `@transaction.atomic`, `_require_engineer_or_admin`, `audit.record`. Audit verbs exactly: `accessory.replaced`, `accessory.repaired`, plus `accessory_type.stock_adjusted` (delta −1, reason `Replacement on WO #<id>`) on each replacement.
- Stock-at-zero replace message exactly: `No backup stock available — restock this type first.`
- `AccessoryEvent` is append-only (`AppendOnlyModel` — saving with a pk or deleting raises `TypeError`).
- Phase 1 behavior unchanged: `attach_accessory`, `update_accessory`, `condemn_accessory`, `adjust_stock`, type services, and all Phase 1 pages stay as they are.
- New write views: `RoleRequiredMixin` with `allowed_roles = ENGINEER_ROLES` (defined at top of `apps/equipment/views.py`).
- URL names exactly: `accessory_mark_faulty`, `accessory_repair`, `accessory_replace` (all take accessory `pk` + `wo_pk`).
- Commit messages: single line, suffixed `(#31)`, exact texts given per task.
- Templates live in project-level `templates/`; reuse the generic `equipment/accessory_form.html` (context contract: `form`, `form_title`, `form_subtitle`, `cancel_url`).
- Seed determinism: the new seed block goes at the END of `seed_demo.Command.handle` (after the PPM block, before the summary write) — random draws there cannot shift the earlier seeded world.

---

### Task 1: AccessoryEvent model + migration + admin

**Files:**
- Modify: `apps/equipment/models.py` (append at end)
- Modify: `apps/equipment/admin.py` (import + append)
- Create: `apps/equipment/migrations/0005_*.py` (via makemigrations)
- Test: `tests/test_accessory_replacement.py` (new)

**Interfaces:**
- Consumes: `AppendOnlyModel` (apps.core.models), `Equipment`, `AccessoryType`, `Accessory` (same module), `maintenance.WorkOrder` (string FK ref, same pattern as `StatusEvent.work_order`), conftest fixtures `accessory_type`, `fitted_accessory`, `make_work_order`, `engineer`.
- Produces: `AccessoryEventKind` (TextChoices: REPLACED="replaced", REPAIRED="repaired") and `AccessoryEvent` with fields `kind`, `work_order` (related_name="accessory_events"), `equipment` (related_name="accessory_events"), `accessory_type` (related_name="events"), `old_accessory` (related_name="events_as_old"), `new_accessory` (nullable, related_name="events_as_new"), `actor`, `remark`, `created_at`; `Meta.ordering = ["-created_at"]`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_accessory_replacement.py`:

```python
import pytest

from apps.equipment.models import AccessoryEvent, AccessoryEventKind

pytestmark = pytest.mark.django_db


def test_accessory_event_append_only(fitted_accessory, engineer, make_work_order):
    wo = make_work_order()
    event = AccessoryEvent.objects.create(
        kind=AccessoryEventKind.REPAIRED,
        work_order=wo,
        equipment=fitted_accessory.equipment,
        accessory_type=fitted_accessory.type,
        old_accessory=fitted_accessory,
        actor=engineer,
    )
    assert event.new_accessory is None
    with pytest.raises(TypeError):
        event.save()
    with pytest.raises(TypeError):
        event.delete()
    with pytest.raises(TypeError):
        AccessoryEvent.objects.all().delete()


def test_accessory_event_related_names(fitted_accessory, engineer, make_work_order):
    wo = make_work_order()
    AccessoryEvent.objects.create(
        kind=AccessoryEventKind.REPAIRED,
        work_order=wo,
        equipment=fitted_accessory.equipment,
        accessory_type=fitted_accessory.type,
        old_accessory=fitted_accessory,
        actor=engineer,
    )
    assert wo.accessory_events.count() == 1
    assert fitted_accessory.equipment.accessory_events.count() == 1
    assert fitted_accessory.type.events.count() == 1
    assert fitted_accessory.events_as_old.count() == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_accessory_replacement.py -v`
Expected: FAIL — `ImportError: cannot import name 'AccessoryEvent'`

- [ ] **Step 3: Add the model**

Append at the end of `apps/equipment/models.py`:

```python
class AccessoryEventKind(models.TextChoices):
    REPLACED = "replaced", "Replaced"
    REPAIRED = "repaired", "Repaired"


class AccessoryEvent(AppendOnlyModel):
    """One replace/repair of an accessory, always under a work order.
    The single source for the WO log, per-equipment counts and the
    dashboard ranking."""

    kind = models.CharField(max_length=20, choices=AccessoryEventKind.choices)
    work_order = models.ForeignKey(
        "maintenance.WorkOrder",
        on_delete=models.PROTECT,
        related_name="accessory_events",
    )
    equipment = models.ForeignKey(
        Equipment, on_delete=models.PROTECT, related_name="accessory_events"
    )
    accessory_type = models.ForeignKey(
        AccessoryType, on_delete=models.PROTECT, related_name="events"
    )
    old_accessory = models.ForeignKey(
        Accessory, on_delete=models.PROTECT, related_name="events_as_old"
    )
    new_accessory = models.ForeignKey(
        Accessory,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="events_as_new",
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="accessory_events",
    )
    remark = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return (
            f"{self.get_kind_display()} {self.accessory_type.name} "
            f"(WO #{self.work_order_id})"
        )
```

- [ ] **Step 4: Register in admin**

In `apps/equipment/admin.py`, extend the models import to include `AccessoryEvent` and append:

```python
@admin.register(AccessoryEvent)
class AccessoryEventAdmin(admin.ModelAdmin):
    list_display = (
        "created_at",
        "kind",
        "accessory_type",
        "equipment",
        "work_order",
        "actor",
    )
    readonly_fields = [f.name for f in AccessoryEvent._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
```

- [ ] **Step 5: Generate the migration**

Run: `.venv/Scripts/python.exe manage.py makemigrations equipment`
Expected: creates `apps/equipment/migrations/0005_accessoryeventkind... / 0005_accessoryevent.py` with `Create model AccessoryEvent`.

- [ ] **Step 6: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_accessory_replacement.py -v`
Expected: 2 passed

- [ ] **Step 7: Lint and commit**

```bash
.venv/Scripts/python.exe -m ruff check apps tests
git add apps/equipment/models.py apps/equipment/admin.py apps/equipment/migrations tests/test_accessory_replacement.py
git commit -m "feat: add accessory event model (#31)"
```

---

### Task 2: replace_accessory + repair_accessory services

**Files:**
- Modify: `apps/equipment/services.py` (imports + append)
- Test: `tests/test_accessory_replacement.py` (append)

**Interfaces:**
- Consumes: Task 1 model; existing `_require_engineer_or_admin`, `audit.record`, `AccessoryStateError`, `Accessory`, `AccessoryStatus`, `AccessoryType`; `WorkOrder.is_active` property.
- Produces: `replace_accessory(accessory, actor, work_order, remark, serial_number="") -> AccessoryEvent` and `repair_accessory(accessory, actor, work_order, remark) -> AccessoryEvent`. Audit verbs `accessory.replaced`, `accessory.repaired`; replacement also writes `accessory_type.stock_adjusted`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_accessory_replacement.py` (extend the import block accordingly):

```python
from django.core.exceptions import PermissionDenied

from apps.core.exceptions import AccessoryStateError
from apps.core.models import AuditLog
from apps.equipment import services
from apps.equipment.models import AccessoryStatus
from apps.maintenance.models import WorkOrderStatus


def test_replace_swaps_unit_stock_and_event(
    accessory_type, fitted_accessory, equipment, engineer, make_work_order
):
    services.adjust_stock(accessory_type, engineer, 2, "Initial stock")
    wo = make_work_order()
    event = services.replace_accessory(
        fitted_accessory, engineer, wo, remark="sensor dead", serial_number="ACC-9"
    )
    fitted_accessory.refresh_from_db()
    accessory_type.refresh_from_db()
    assert fitted_accessory.status == AccessoryStatus.CONDEMNED
    assert fitted_accessory.condemned_at is not None
    assert accessory_type.stock_qty == 1
    new = equipment.accessories.exclude(pk=fitted_accessory.pk).get()
    assert new.status == AccessoryStatus.WORKING
    assert new.serial_number == "ACC-9"
    assert event.kind == AccessoryEventKind.REPLACED
    assert event.old_accessory == fitted_accessory
    assert event.new_accessory == new
    assert event.work_order == wo
    assert AuditLog.objects.filter(verb="accessory.replaced").exists()
    stock_entry = (
        AuditLog.objects.filter(verb="accessory_type.stock_adjusted")
        .order_by("created_at")
        .last()
    )
    assert stock_entry.changes["reason"] == f"Replacement on WO #{wo.pk}"


def test_replace_refused_without_stock(
    fitted_accessory, equipment, engineer, make_work_order
):
    wo = make_work_order()
    with pytest.raises(AccessoryStateError):
        services.replace_accessory(fitted_accessory, engineer, wo, remark="dead")
    fitted_accessory.refresh_from_db()
    assert fitted_accessory.status == AccessoryStatus.WORKING
    assert equipment.accessories.count() == 1
    assert AccessoryEvent.objects.count() == 0


def test_replace_refused_on_inactive_workorder(
    accessory_type, fitted_accessory, engineer, make_work_order
):
    services.adjust_stock(accessory_type, engineer, 1, "Initial stock")
    wo = make_work_order(status=WorkOrderStatus.COMPLETED)
    with pytest.raises(AccessoryStateError):
        services.replace_accessory(fitted_accessory, engineer, wo, remark="dead")


def test_replace_refused_for_other_equipment(
    accessory_type, fitted_accessory, engineer, make_equipment, make_work_order
):
    services.adjust_stock(accessory_type, engineer, 1, "Initial stock")
    other = make_equipment(serial_number="SN-0002")
    wo = make_work_order(eq=other)
    with pytest.raises(AccessoryStateError):
        services.replace_accessory(fitted_accessory, engineer, wo, remark="dead")


def test_replace_refused_when_condemned(
    accessory_type, fitted_accessory, engineer, make_work_order
):
    services.adjust_stock(accessory_type, engineer, 1, "Initial stock")
    services.condemn_accessory(fitted_accessory, engineer, "scrapped")
    wo = make_work_order()
    with pytest.raises(AccessoryStateError):
        services.replace_accessory(fitted_accessory, engineer, wo, remark="dead")


def test_staff_cannot_replace_or_repair(
    fitted_accessory, staff_user, make_work_order
):
    wo = make_work_order()
    with pytest.raises(PermissionDenied):
        services.replace_accessory(fitted_accessory, staff_user, wo, remark="x")
    with pytest.raises(PermissionDenied):
        services.repair_accessory(fitted_accessory, staff_user, wo, remark="x")


def test_repair_flips_faulty_and_logs_event(
    fitted_accessory, engineer, make_work_order
):
    services.update_accessory(
        fitted_accessory, engineer, status=AccessoryStatus.FAULTY
    )
    wo = make_work_order()
    event = services.repair_accessory(
        fitted_accessory, engineer, wo, remark="re-soldered connector"
    )
    fitted_accessory.refresh_from_db()
    assert fitted_accessory.status == AccessoryStatus.WORKING
    assert event.kind == AccessoryEventKind.REPAIRED
    assert event.new_accessory is None
    assert AuditLog.objects.filter(verb="accessory.repaired").exists()


def test_repair_requires_faulty(fitted_accessory, engineer, make_work_order):
    wo = make_work_order()
    with pytest.raises(AccessoryStateError):
        services.repair_accessory(fitted_accessory, engineer, wo, remark="x")


def test_repair_refused_on_inactive_workorder(
    fitted_accessory, engineer, make_work_order
):
    services.update_accessory(
        fitted_accessory, engineer, status=AccessoryStatus.FAULTY
    )
    wo = make_work_order(status=WorkOrderStatus.CANCELLED)
    with pytest.raises(AccessoryStateError):
        services.repair_accessory(fitted_accessory, engineer, wo, remark="x")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_accessory_replacement.py -v`
Expected: new tests FAIL — `AttributeError: ... no attribute 'replace_accessory'`

- [ ] **Step 3: Implement**

In `apps/equipment/services.py`, extend the models import with `AccessoryEvent, AccessoryEventKind` (keep alphabetical order inside the parenthesized block). Append at the end of the file:

```python
def _require_accessory_on_active_workorder(accessory, work_order):
    if not work_order.is_active:
        raise AccessoryStateError(
            "Accessory work can only be recorded on an active work order."
        )
    if accessory.equipment_id != work_order.equipment_id:
        raise AccessoryStateError(
            "This accessory belongs to a different equipment."
        )


@transaction.atomic
def replace_accessory(accessory, actor, work_order, remark, serial_number=""):
    from django.utils import timezone

    _require_engineer_or_admin(actor)
    accessory.refresh_from_db()
    _require_accessory_on_active_workorder(accessory, work_order)
    if accessory.status == AccessoryStatus.CONDEMNED:
        raise AccessoryStateError("This accessory is already condemned.")
    locked_type = AccessoryType.objects.select_for_update().get(
        pk=accessory.type_id
    )
    if locked_type.stock_qty < 1:
        raise AccessoryStateError(
            "No backup stock available — restock this type first."
        )
    accessory.status = AccessoryStatus.CONDEMNED
    accessory.condemned_at = timezone.now()
    accessory.save(update_fields=["status", "condemned_at"])
    locked_type.stock_qty -= 1
    locked_type.save(update_fields=["stock_qty"])
    audit.record(
        actor,
        "accessory_type.stock_adjusted",
        locked_type,
        {
            "delta": -1,
            "reason": f"Replacement on WO #{work_order.pk}",
            "stock_qty": locked_type.stock_qty,
        },
    )
    new_accessory = Accessory.objects.create(
        type_id=accessory.type_id,
        equipment_id=accessory.equipment_id,
        serial_number=serial_number,
    )
    event = AccessoryEvent.objects.create(
        kind=AccessoryEventKind.REPLACED,
        work_order=work_order,
        equipment_id=accessory.equipment_id,
        accessory_type_id=accessory.type_id,
        old_accessory=accessory,
        new_accessory=new_accessory,
        actor=actor,
        remark=remark,
    )
    audit.record(
        actor,
        "accessory.replaced",
        accessory,
        {
            "work_order": work_order.pk,
            "old": accessory.pk,
            "new": new_accessory.pk,
            "remark": remark,
        },
    )
    return event


@transaction.atomic
def repair_accessory(accessory, actor, work_order, remark):
    _require_engineer_or_admin(actor)
    accessory.refresh_from_db()
    _require_accessory_on_active_workorder(accessory, work_order)
    if accessory.status == AccessoryStatus.CONDEMNED:
        raise AccessoryStateError("This accessory is condemned.")
    if accessory.status != AccessoryStatus.FAULTY:
        raise AccessoryStateError("Only faulty accessories can be repaired.")
    accessory.status = AccessoryStatus.WORKING
    accessory.save(update_fields=["status"])
    event = AccessoryEvent.objects.create(
        kind=AccessoryEventKind.REPAIRED,
        work_order=work_order,
        equipment_id=accessory.equipment_id,
        accessory_type_id=accessory.type_id,
        old_accessory=accessory,
        actor=actor,
        remark=remark,
    )
    audit.record(
        actor,
        "accessory.repaired",
        accessory,
        {"work_order": work_order.pk, "remark": remark},
    )
    return event
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_accessory_replacement.py -v`
Expected: all pass

- [ ] **Step 5: Lint and commit**

```bash
.venv/Scripts/python.exe -m ruff check apps tests
git add apps/equipment/services.py tests/test_accessory_replacement.py
git commit -m "feat: replace and repair accessory services (#31)"
```

---

### Task 3: Work-order page accessory actions

**Files:**
- Modify: `apps/equipment/forms.py` (append)
- Modify: `apps/equipment/views.py` (imports + append)
- Modify: `apps/equipment/urls.py` (append)
- Modify: `apps/maintenance/views.py` (workorder_detail context, two lines)
- Modify: `templates/maintenance/workorder_detail.html` (insert card)
- Modify: `templates/base.html` (Queue link active-name list)
- Test: `tests/test_accessory_workorder_views.py` (new)

**Interfaces:**
- Consumes: Task 2 services; generic template `equipment/accessory_form.html` (context: `form`, `form_title`, `form_subtitle`, `cancel_url`); existing `update_accessory` service (mark faulty); `RoleRequiredMixin`, `ENGINEER_ROLES`, `DomainError`; WO detail context vars `wo`, `can_engineer`.
- Produces: forms `AccessoryReplaceForm` (remark required, serial_number optional), `AccessoryRepairForm` (remark required); URL names `accessory_mark_faulty` (POST only), `accessory_repair`, `accessory_replace` — all `accessories/<int:pk>/<action>/<int:wo_pk>/`; WO context keys `accessories`, `accessory_events`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_accessory_workorder_views.py`:

```python
import pytest
from django.urls import reverse

from apps.equipment import services
from apps.equipment.models import (
    AccessoryEvent,
    AccessoryEventKind,
    AccessoryStatus,
)
from apps.maintenance.models import WorkOrderStatus

pytestmark = pytest.mark.django_db


def test_staff_403_on_wo_accessory_urls(
    client, staff_user, fitted_accessory, make_work_order
):
    wo = make_work_order()
    client.force_login(staff_user)
    post_url = reverse(
        "accessory_mark_faulty", args=[fitted_accessory.pk, wo.pk]
    )
    assert client.post(post_url).status_code == 403
    for name in ("accessory_repair", "accessory_replace"):
        url = reverse(name, args=[fitted_accessory.pk, wo.pk])
        assert client.get(url).status_code == 403


def test_wo_page_shows_buttons_only_while_active(
    client, engineer, fitted_accessory, make_work_order
):
    wo = make_work_order()
    client.force_login(engineer)
    content = client.get(
        reverse("workorder_detail", args=[wo.pk])
    ).content.decode()
    assert "Mark faulty" in content
    assert "Replace…" in content
    done = make_work_order(status=WorkOrderStatus.COMPLETED)
    content = client.get(
        reverse("workorder_detail", args=[done.pk])
    ).content.decode()
    assert "Mark faulty" not in content
    assert "Replace…" not in content


def test_mark_faulty_then_repair_button_appears(
    client, engineer, fitted_accessory, make_work_order
):
    wo = make_work_order()
    client.force_login(engineer)
    response = client.post(
        reverse("accessory_mark_faulty", args=[fitted_accessory.pk, wo.pk])
    )
    assert response.status_code == 302
    fitted_accessory.refresh_from_db()
    assert fitted_accessory.status == AccessoryStatus.FAULTY
    content = client.get(
        reverse("workorder_detail", args=[wo.pk])
    ).content.decode()
    assert ">Repair<" in content


def test_replace_via_ui(
    client, engineer, accessory_type, fitted_accessory, equipment, make_work_order
):
    services.adjust_stock(accessory_type, engineer, 1, "Initial stock")
    wo = make_work_order()
    client.force_login(engineer)
    url = reverse("accessory_replace", args=[fitted_accessory.pk, wo.pk])
    assert client.get(url).status_code == 200
    response = client.post(url, {"remark": "sensor dead", "serial_number": "A-9"})
    assert response.status_code == 302
    accessory_type.refresh_from_db()
    assert accessory_type.stock_qty == 0
    assert equipment.accessories.count() == 2
    event = AccessoryEvent.objects.get(kind=AccessoryEventKind.REPLACED)
    assert event.work_order_id == wo.pk
    content = client.get(
        reverse("workorder_detail", args=[wo.pk])
    ).content.decode()
    assert "sensor dead" in content


def test_replace_without_stock_shows_error(
    client, engineer, fitted_accessory, make_work_order
):
    wo = make_work_order()
    client.force_login(engineer)
    response = client.post(
        reverse("accessory_replace", args=[fitted_accessory.pk, wo.pk]),
        {"remark": "dead", "serial_number": ""},
        follow=True,
    )
    assert b"No backup stock available" in response.content
    assert AccessoryEvent.objects.count() == 0


def test_repair_via_ui(client, engineer, fitted_accessory, make_work_order):
    services.update_accessory(
        fitted_accessory, engineer, status=AccessoryStatus.FAULTY
    )
    wo = make_work_order()
    client.force_login(engineer)
    response = client.post(
        reverse("accessory_repair", args=[fitted_accessory.pk, wo.pk]),
        {"remark": "re-soldered connector"},
    )
    assert response.status_code == 302
    fitted_accessory.refresh_from_db()
    assert fitted_accessory.status == AccessoryStatus.WORKING
    assert (
        AccessoryEvent.objects.filter(kind=AccessoryEventKind.REPAIRED).count()
        == 1
    )
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_accessory_workorder_views.py -v`
Expected: FAIL — `NoReverseMatch: Reverse for 'accessory_mark_faulty' not found`

- [ ] **Step 3: Implement forms**

Append to `apps/equipment/forms.py`:

```python
class AccessoryReplaceForm(forms.Form):
    remark = forms.CharField(
        label="Reason",
        widget=forms.Textarea(attrs={"rows": 3, "class": INPUT}),
    )
    serial_number = forms.CharField(
        required=False,
        help_text="Serial of the new unit; leave blank if not serialized.",
        widget=forms.TextInput(attrs={"class": INPUT}),
    )


class AccessoryRepairForm(forms.Form):
    remark = forms.CharField(
        label="What was done",
        widget=forms.Textarea(attrs={"rows": 3, "class": INPUT}),
    )
```

- [ ] **Step 4: Implement views and URLs**

In `apps/equipment/views.py`:
- Add `from apps.maintenance.models import WorkOrder` after the `apps.core.exceptions` import (isort: apps.accounts → apps.core → apps.maintenance).
- Extend the `.forms` import with `AccessoryRepairForm, AccessoryReplaceForm` (keep the parenthesized block alphabetical).

Append the views:

```python
class AccessoryMarkFaultyView(RoleRequiredMixin, View):
    allowed_roles = ENGINEER_ROLES

    def post(self, request, pk, wo_pk):
        accessory = get_object_or_404(Accessory, pk=pk)
        get_object_or_404(WorkOrder, pk=wo_pk)
        try:
            services.update_accessory(
                accessory, request.user, status=AccessoryStatus.FAULTY
            )
        except DomainError as exc:
            messages.error(request, str(exc))
        else:
            messages.success(request, "Accessory marked faulty.")
        return redirect("workorder_detail", pk=wo_pk)


class AccessoryRepairView(RoleRequiredMixin, View):
    allowed_roles = ENGINEER_ROLES

    def _render(self, request, form, accessory, work_order):
        return render(
            request,
            "equipment/accessory_form.html",
            {
                "form": form,
                "form_title": f"Repair {accessory.type.name}",
                "form_subtitle": f"WO #{work_order.pk} · {accessory.equipment}",
                "cancel_url": reverse("workorder_detail", args=[work_order.pk]),
            },
        )

    def get(self, request, pk, wo_pk):
        accessory = get_object_or_404(
            Accessory.objects.select_related("type", "equipment"), pk=pk
        )
        work_order = get_object_or_404(WorkOrder, pk=wo_pk)
        return self._render(request, AccessoryRepairForm(), accessory, work_order)

    def post(self, request, pk, wo_pk):
        accessory = get_object_or_404(
            Accessory.objects.select_related("type", "equipment"), pk=pk
        )
        work_order = get_object_or_404(WorkOrder, pk=wo_pk)
        form = AccessoryRepairForm(request.POST)
        if not form.is_valid():
            return self._render(request, form, accessory, work_order)
        try:
            services.repair_accessory(
                accessory, request.user, work_order, form.cleaned_data["remark"]
            )
        except DomainError as exc:
            messages.error(request, str(exc))
        else:
            messages.success(request, "Accessory repaired.")
        return redirect("workorder_detail", pk=wo_pk)


class AccessoryReplaceView(RoleRequiredMixin, View):
    allowed_roles = ENGINEER_ROLES

    def _render(self, request, form, accessory, work_order):
        return render(
            request,
            "equipment/accessory_form.html",
            {
                "form": form,
                "form_title": f"Replace {accessory.type.name}",
                "form_subtitle": (
                    f"WO #{work_order.pk} · in store: "
                    f"{accessory.type.stock_qty}"
                ),
                "cancel_url": reverse("workorder_detail", args=[work_order.pk]),
            },
        )

    def get(self, request, pk, wo_pk):
        accessory = get_object_or_404(
            Accessory.objects.select_related("type", "equipment"), pk=pk
        )
        work_order = get_object_or_404(WorkOrder, pk=wo_pk)
        return self._render(request, AccessoryReplaceForm(), accessory, work_order)

    def post(self, request, pk, wo_pk):
        accessory = get_object_or_404(
            Accessory.objects.select_related("type", "equipment"), pk=pk
        )
        work_order = get_object_or_404(WorkOrder, pk=wo_pk)
        form = AccessoryReplaceForm(request.POST)
        if not form.is_valid():
            return self._render(request, form, accessory, work_order)
        try:
            services.replace_accessory(
                accessory,
                request.user,
                work_order,
                remark=form.cleaned_data["remark"],
                serial_number=form.cleaned_data["serial_number"],
            )
        except DomainError as exc:
            messages.error(request, str(exc))
        else:
            messages.success(request, "Accessory replaced from backup stock.")
        return redirect("workorder_detail", pk=wo_pk)
```

Append to `urlpatterns` in `apps/equipment/urls.py`:

```python
    path(
        "accessories/<int:pk>/mark-faulty/<int:wo_pk>/",
        views.AccessoryMarkFaultyView.as_view(),
        name="accessory_mark_faulty",
    ),
    path(
        "accessories/<int:pk>/repair/<int:wo_pk>/",
        views.AccessoryRepairView.as_view(),
        name="accessory_repair",
    ),
    path(
        "accessories/<int:pk>/replace/<int:wo_pk>/",
        views.AccessoryReplaceView.as_view(),
        name="accessory_replace",
    ),
```

- [ ] **Step 5: WO detail context + template card**

In `apps/maintenance/views.py`, in `workorder_detail`'s render context (after the `"can_engineer": ...` line), add:

```python
            "accessories": wo.equipment.accessories.select_related("type"),
            "accessory_events": wo.accessory_events.select_related(
                "accessory_type", "actor"
            ),
```

In `templates/maintenance/workorder_detail.html`, insert this card between the Remarks card's closing `</div>` and the `{% include "ai/_assistant_panel.html" ... %}` line:

```html
<div class="card mt-6 p-5">
  <h2 class="mb-3 font-semibold">Accessories</h2>
  <div class="space-y-3 text-sm">
    {% for acc in accessories %}
    <div class="flex flex-wrap items-center gap-2 rounded-lg border border-slate-100 px-4 py-3 dark:border-slate-800">
      <span class="font-medium">{{ acc.type.name }}</span>
      {% if acc.serial_number %}<span class="font-mono text-slate-500 dark:text-slate-400">{{ acc.serial_number }}</span>{% endif %}
      {% if acc.status == 'working' %}<span class="badge-working">{{ acc.get_status_display }}</span>
      {% elif acc.status == 'faulty' %}<span class="badge-repair">{{ acc.get_status_display }}</span>
      {% else %}<span class="badge-danger">{{ acc.get_status_display }}</span>{% endif %}
      {% if can_engineer and wo.is_active and acc.status != 'condemned' %}
      <span class="ml-auto flex gap-2">
        {% if acc.status == 'working' %}
        <form method="post" action="{% url 'accessory_mark_faulty' acc.pk wo.pk %}">{% csrf_token %}
          <button class="btn-ghost btn-sm">Mark faulty</button>
        </form>
        {% endif %}
        {% if acc.status == 'faulty' %}
        <a href="{% url 'accessory_repair' acc.pk wo.pk %}" class="btn-success btn-sm">Repair</a>
        {% endif %}
        <a href="{% url 'accessory_replace' acc.pk wo.pk %}" class="btn-warn btn-sm">Replace…</a>
      </span>
      {% endif %}
    </div>
    {% empty %}<p class="text-slate-500 dark:text-slate-400">No accessories recorded for this equipment.</p>{% endfor %}
  </div>
  <div class="mt-4 border-t border-slate-100 pt-4 dark:border-slate-800">
    <h3 class="mb-2 text-sm font-medium text-slate-500 dark:text-slate-400">Done under this work order</h3>
    <ul class="space-y-2 text-sm">
      {% for ev in accessory_events %}
      <li class="rounded-lg bg-slate-50 p-3 dark:bg-slate-800/60">
        <span class="font-medium">{{ ev.accessory_type.name }}</span>
        {% if ev.kind == 'replaced' %}<span class="badge-repair">Replaced</span>
        {% else %}<span class="badge-working">Repaired</span>{% endif %}
        <span class="text-slate-500 dark:text-slate-400">by {{ ev.actor }} · {{ ev.created_at }}</span>
        {% if ev.remark %}<div class="mt-0.5 text-slate-600 dark:text-slate-300">“{{ ev.remark }}”</div>{% endif %}
      </li>
      {% empty %}<li class="text-slate-500 dark:text-slate-400">Nothing yet.</li>{% endfor %}
    </ul>
  </div>
</div>
```

In `templates/base.html`, extend the Queue link's active list from
`'complaint_queue complaint_close workorder_detail workorder_complete'` to
`'complaint_queue complaint_close workorder_detail workorder_complete accessory_repair accessory_replace'`.

- [ ] **Step 6: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_accessory_workorder_views.py tests/test_accessory_replacement.py -v`
Expected: all pass

- [ ] **Step 7: Lint and commit**

```bash
.venv/Scripts/python.exe -m ruff check apps tests
git add apps/equipment/forms.py apps/equipment/views.py apps/equipment/urls.py apps/maintenance/views.py templates/maintenance/workorder_detail.html templates/base.html tests/test_accessory_workorder_views.py
git commit -m "feat: work order accessory actions (#31)"
```

---

### Task 4: Metrics, equipment summary, dashboard panel, restock strip

**Files:**
- Modify: `apps/reports/metrics.py` (imports + append)
- Modify: `apps/reports/views.py` (dashboard context)
- Modify: `templates/reports/dashboard.html` (new panel)
- Modify: `apps/equipment/views.py` (`EquipmentDetailView` context + `AccessoryTypeListView` context)
- Modify: `templates/equipment/detail.html` (summary line)
- Modify: `templates/equipment/accessory_type_list.html` (restock strip)
- Test: `tests/test_accessory_metrics.py` (new)

**Interfaces:**
- Consumes: `AccessoryEvent`, `AccessoryEventKind`, `AccessoryType` (Task 1), `replace_accessory` (Task 2).
- Produces: `metrics.accessory_replacements_by_equipment(window_start, window_end, limit=5)` → list of `{"equipment_id", "label", "n"}`; `metrics.accessory_replacements_by_type(window_start, window_end, limit=5)` → list of `{"label", "n"}`; dashboard context keys `acc_repl_equipment`, `acc_repl_types`; equipment-detail context keys `accessory_replaced_total`, `accessory_replaced_breakdown`; catalog context key `restock`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_accessory_metrics.py`:

```python
from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.equipment import services
from apps.reports import metrics

pytestmark = pytest.mark.django_db


@pytest.fixture
def replacement_event(accessory_type, fitted_accessory, engineer, make_work_order):
    services.adjust_stock(accessory_type, engineer, 1, "Initial stock")
    wo = make_work_order()
    return services.replace_accessory(
        fitted_accessory, engineer, wo, remark="worn"
    )


def test_replacements_by_equipment_and_type(replacement_event, equipment):
    end = timezone.now() + timedelta(minutes=1)
    start = end - timedelta(days=90)
    by_eq = metrics.accessory_replacements_by_equipment(start, end)
    assert by_eq[0]["equipment_id"] == equipment.pk
    assert by_eq[0]["n"] == 1
    assert equipment.serial_number in by_eq[0]["label"]
    by_type = metrics.accessory_replacements_by_type(start, end)
    assert by_type[0]["n"] == 1
    assert "ECG cable" in by_type[0]["label"]


def test_window_excludes_old_events(replacement_event):
    end = timezone.now() - timedelta(days=365)
    start = end - timedelta(days=90)
    assert metrics.accessory_replacements_by_equipment(start, end) == []
    assert metrics.accessory_replacements_by_type(start, end) == []


def test_dashboard_panel_renders(client, engineer, replacement_event):
    client.force_login(engineer)
    content = client.get(reverse("dashboard")).content.decode()
    assert "Accessory replacements" in content
    assert "ECG cable" in content


def test_equipment_summary_line(client, engineer, replacement_event, equipment):
    client.force_login(engineer)
    content = client.get(
        reverse("equipment_detail", args=[equipment.pk])
    ).content.decode()
    assert "1 replaced all-time" in content
    assert "1× ECG cable" in content


def test_restock_strip_appears_only_at_zero(client, engineer, accessory_type):
    client.force_login(engineer)
    content = client.get(reverse("accessory_type_list")).content.decode()
    assert "Restock needed" in content
    services.adjust_stock(accessory_type, engineer, 3, "Received shipment")
    content = client.get(reverse("accessory_type_list")).content.decode()
    assert "Restock needed" not in content
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_accessory_metrics.py -v`
Expected: FAIL — `AttributeError: module ... has no attribute 'accessory_replacements_by_equipment'`

- [ ] **Step 3: Implement metrics**

In `apps/reports/metrics.py`, change the equipment import to:

```python
from apps.equipment.models import (
    AccessoryEvent,
    AccessoryEventKind,
    Equipment,
    EquipmentStatus,
)
```

Append at the end of the file:

```python
def accessory_replacements_by_equipment(window_start, window_end, limit=5):
    rows = (
        AccessoryEvent.objects.filter(
            kind=AccessoryEventKind.REPLACED,
            created_at__range=(window_start, window_end),
        )
        .values("equipment_id", "equipment__name", "equipment__serial_number")
        .annotate(n=Count("id"))
        .order_by("-n")[:limit]
    )
    return [
        {
            "equipment_id": r["equipment_id"],
            "label": f"{r['equipment__name']} ({r['equipment__serial_number']})",
            "n": r["n"],
        }
        for r in rows
    ]


def accessory_replacements_by_type(window_start, window_end, limit=5):
    rows = (
        AccessoryEvent.objects.filter(
            kind=AccessoryEventKind.REPLACED,
            created_at__range=(window_start, window_end),
        )
        .values("accessory_type__name", "accessory_type__equipment_name")
        .annotate(n=Count("id"))
        .order_by("-n")[:limit]
    )
    return [
        {
            "label": (
                f"{r['accessory_type__name']} — "
                f"{r['accessory_type__equipment_name']}"
            ),
            "n": r["n"],
        }
        for r in rows
    ]
```

- [ ] **Step 4: Dashboard view + panel**

In `apps/reports/views.py`, in `dashboard`, after the `prev_start = ...` line add:

```python
    acc_window_start = window_end - timedelta(days=90)
```

and add to the `context` dict:

```python
        "acc_repl_equipment": metrics.accessory_replacements_by_equipment(
            acc_window_start, window_end
        ),
        "acc_repl_types": metrics.accessory_replacements_by_type(
            acc_window_start, window_end
        ),
```

In `templates/reports/dashboard.html`, after the "PPM compliance" card's closing `</div>` (line ~146, inside the same grid), add:

```html
  <div class="card p-5">
    <h2 class="mb-3 font-semibold">Accessory replacements <span class="text-sm font-normal text-slate-500 dark:text-slate-400">· last 90 days</span></h2>
    {% if acc_repl_equipment %}
    <p class="mb-1 text-xs font-medium text-slate-500 dark:text-slate-400">Top equipment</p>
    <ul class="mb-3 space-y-1 text-sm">
      {% for row in acc_repl_equipment %}
      <li class="flex justify-between gap-2">
        <a class="link" href="{% url 'equipment_detail' row.equipment_id %}">{{ row.label }}</a>
        <span class="badge-info">{{ row.n }}</span>
      </li>
      {% endfor %}
    </ul>
    <p class="mb-1 text-xs font-medium text-slate-500 dark:text-slate-400">Top accessory types</p>
    <ul class="space-y-1 text-sm">
      {% for row in acc_repl_types %}
      <li class="flex justify-between gap-2"><span>{{ row.label }}</span><span class="badge-info">{{ row.n }}</span></li>
      {% endfor %}
    </ul>
    <a class="link mt-3 inline-block text-sm" href="{% url 'accessory_type_list' %}">Open accessory inventory →</a>
    {% else %}
    <p class="text-sm text-slate-500 dark:text-slate-400">No replacements recorded.</p>
    {% endif %}
  </div>
```

- [ ] **Step 5: Equipment summary line + restock strip**

In `apps/equipment/views.py`:
- Extend the models import with `AccessoryEventKind`.
- The `Count` import already exists from Task 4 of Phase 1 (`from django.db.models import Count, Q`).
- In `EquipmentDetailView.get_context_data`, after the `ctx["accessories"] = ...` line, add:

```python
        replaced_breakdown = list(
            eq.accessory_events.filter(kind=AccessoryEventKind.REPLACED)
            .values("accessory_type__name")
            .annotate(n=Count("id"))
            .order_by("-n")
        )
        ctx["accessory_replaced_total"] = sum(r["n"] for r in replaced_breakdown)
        ctx["accessory_replaced_breakdown"] = replaced_breakdown
```

- In `AccessoryTypeListView`, add:

```python
    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["restock"] = AccessoryType.objects.filter(stock_qty=0)
        return ctx
```

In `templates/equipment/detail.html`, inside the Accessories card, directly after the header `</div>` (the one holding the "Accessories" h2 and Attach button), add:

```html
  {% if accessory_replaced_total %}
  <p class="mb-3 text-sm text-slate-500 dark:text-slate-400">
    {{ accessory_replaced_total }} replaced all-time —
    {% for row in accessory_replaced_breakdown %}{{ row.n }}× {{ row.accessory_type__name }}{% if not forloop.last %}, {% endif %}{% endfor %}
  </p>
  {% endif %}
```

In `templates/equipment/accessory_type_list.html`, directly after `{% block content %}` (before the header div), add:

```html
{% if restock %}
<div class="card mb-6 border border-red-200 bg-red-50 p-5 dark:border-red-500/30 dark:bg-red-500/10">
  <h2 class="mb-2 font-semibold text-red-800 dark:text-red-300">Restock needed</h2>
  <ul class="space-y-1 text-sm">
    {% for type in restock %}
    <li class="flex flex-wrap items-center gap-2">
      <span>{{ type.name }} — {{ type.equipment_name }}</span>
      <a href="{% url 'accessory_stock_adjust' type.pk %}" class="link ml-auto">Adjust stock →</a>
    </li>
    {% endfor %}
  </ul>
</div>
{% endif %}
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_accessory_metrics.py tests/test_accessory_views.py -v`
Expected: all pass (the Phase 1 view tests must not regress)

- [ ] **Step 7: Lint and commit**

```bash
.venv/Scripts/python.exe -m ruff check apps tests
git add apps/reports/metrics.py apps/reports/views.py templates/reports/dashboard.html apps/equipment/views.py templates/equipment/detail.html templates/equipment/accessory_type_list.html tests/test_accessory_metrics.py
git commit -m "feat: accessory replacement metrics and restock visibility (#31)"
```

---

### Task 5: Seed data

**Files:**
- Modify: `apps/core/management/commands/seed_demo.py`
- Test: `tests/test_seed_demo.py`

**Interfaces:**
- Consumes: Task 2 services; existing seed variables `devices`, `engineers`, `admin`, helper `backdate`.
- Produces: seeded `AccessoryEvent` history (~6 replacements, ~3 repairs backdated to their WOs) and at least one zero-stock type.

**IMPORTANT context:** the seeded history loop completes every WO, but `replace_accessory`/`repair_accessory` require an ACTIVE WO. The seed block therefore flips one completed WO to `in_progress`, records the event through the real service, then flips it back — one WO at a time, so the `one_active_workorder_per_equipment` constraint can't trip (no other active WOs exist at that point in the seed). The block goes at the very END of `handle` (after the PPM block, before the summary write) — random draws there cannot shift the earlier world. Also: pick only WORKING accessories, never the pre-seeded faulty SpO2 probe, so the existing `faulty count == 1` assertion still holds.

- [ ] **Step 1: Update the seed test (failing first)**

In `tests/test_seed_demo.py`:
- Extend the equipment models import with `AccessoryEvent, AccessoryEventKind` (keep alphabetical).
- Add `from django.utils import timezone` to the imports.
- REPLACE the existing line `assert not AccessoryType.objects.filter(stock_qty=0).exists()` with the new assertions below (the restock-strip demo deliberately leaves one type at zero now):

```python
    assert AccessoryType.objects.filter(stock_qty=0).exists()
    assert (
        AccessoryEvent.objects.filter(kind=AccessoryEventKind.REPLACED).count()
        >= 4
    )
    assert (
        AccessoryEvent.objects.filter(kind=AccessoryEventKind.REPAIRED).count()
        >= 2
    )
    oldest = AccessoryEvent.objects.order_by("created_at").first()
    assert (timezone.now() - oldest.created_at).days >= 10
```

Keep `assert Accessory.objects.filter(status=AccessoryStatus.FAULTY).count() == 1` unchanged.

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_seed_demo.py::test_seed_demo_builds_world -v`
Expected: FAIL — `assert AccessoryType.objects.filter(stock_qty=0).exists()` (no zero-stock type yet). Note: seed tests take minutes.

- [ ] **Step 3: Implement seeding**

In `apps/core/management/commands/seed_demo.py`:

1. Extend the equipment models import with `AccessoryEvent, EquipmentStatus` and the equipment services import with `repair_accessory, replace_accessory` (both blocks stay alphabetical). Extend the maintenance models import with `WorkOrderStatus`.

2. At the END of `handle`, after the PPM block and before `self.stdout.write(...)`, insert:

```python
        # accessory replacement / repair history on completed work orders.
        # Placed last on purpose: random draws here cannot shift the earlier
        # seeded world. Services require an ACTIVE work order, so each chosen
        # completed WO is flipped to in_progress, the event is recorded
        # through the real service, and the WO is flipped back (one at a
        # time — no other active WOs exist here, so the one-active-WO
        # constraint cannot trip). Only WORKING accessories are picked, so
        # the single pre-seeded faulty SpO2 probe stays the only faulty one.
        completed_pool = list(
            WorkOrder.objects.filter(
                status=WorkOrderStatus.COMPLETED,
                equipment__accessories__isnull=False,
            )
            .exclude(equipment__status=EquipmentStatus.CONDEMNED)
            .distinct()
            .order_by("opened_at")
        )
        replaced = repaired = 0
        for wo in completed_pool:
            if replaced >= 6 and repaired >= 3:
                break
            accessory = (
                wo.equipment.accessories.filter(status=AccessoryStatus.WORKING)
                .select_related("type")
                .order_by("id")
                .first()
            )
            if accessory is None:
                continue
            engineer = random.choice(engineers)
            WorkOrder.objects.filter(pk=wo.pk).update(
                status=WorkOrderStatus.IN_PROGRESS
            )
            wo.refresh_from_db()
            event = None
            if replaced < 6 and accessory.type.stock_qty > 0:
                event = replace_accessory(
                    accessory,
                    engineer,
                    wo,
                    remark="Worn out; replaced from backup stock.",
                )
                replaced += 1
                backdate(
                    Accessory, accessory.pk, condemned_at=wo.repair_completed_at
                )
            elif repaired < 3:
                update_accessory(
                    accessory, engineer, status=AccessoryStatus.FAULTY
                )
                event = repair_accessory(
                    accessory, engineer, wo, remark="Connector re-soldered."
                )
                repaired += 1
            WorkOrder.objects.filter(pk=wo.pk).update(
                status=WorkOrderStatus.COMPLETED
            )
            if event is not None:
                backdate(
                    AccessoryEvent, event.pk, created_at=wo.repair_completed_at
                )

        # make the restock strip visible out of the box: one type at zero
        low_type = (
            AccessoryType.objects.filter(stock_qty__gt=0).order_by("id").first()
        )
        if low_type is not None:
            adjust_stock(
                low_type, admin, -low_type.stock_qty, "Issued to wards as spares"
            )
```

3. Extend the summary write — after the `f"{Accessory.objects.count()} accessories, "` line add:

```python
                f"{AccessoryEvent.objects.count()} accessory events, "
```

- [ ] **Step 4: Run the seed tests**

Run: `.venv/Scripts/python.exe -m pytest tests/test_seed_demo.py -v`
Expected: both pass. If a pre-existing assertion fails, the block is misplaced (it must be the LAST thing before the summary write) — fix the placement, never the old assertions (except the one deliberate stock_qty=0 flip in Step 1).

- [ ] **Step 5: Full suite, lint, commit**

```bash
.venv/Scripts/python.exe -m pytest
.venv/Scripts/python.exe -m ruff check apps tests
git add apps/core/management/commands/seed_demo.py tests/test_seed_demo.py
git commit -m "feat: seed accessory replacement history (#31)"
```

---

## Final verification (after all tasks)

- [ ] Full test suite green: `.venv/Scripts/python.exe -m pytest`
- [ ] `.venv/Scripts/python.exe -m ruff check apps tests` clean
- [ ] `.venv/Scripts/python.exe manage.py makemigrations --check --dry-run` — no missing migrations
- [ ] Push `feature/accessory-replacement` and open a PR against `main` referencing #31
