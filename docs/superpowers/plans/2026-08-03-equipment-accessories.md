# Equipment Accessories Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Accessory inventory core — a catalog of accessory types with backup-stock counters (engineer/admin only) and individual accessory records fitted on equipment, per the approved spec `docs/superpowers/specs/2026-08-03-equipment-accessories-design.md`.

**Architecture:** Two new models in `apps.equipment` (`AccessoryType` catalog with `stock_qty` counter, `Accessory` fitted unit). All writes go through module-level service functions in `apps/equipment/services.py` that check roles, enforce business rules, and write `AuditLog` entries. Class-based views stay thin: validate a form, call a service, redirect with a flash message.

**Tech Stack:** Django 5.2, PostgreSQL, pytest-django, Tailwind-style utility CSS, ruff.

## Global Constraints

- Python interpreter: `.venv/Scripts/python.exe` (system python lacks the project deps). Run tests as `.venv/Scripts/python.exe -m pytest ...` from the repo root.
- Lint: `ruff` — line length 88, double quotes, isort import ordering. Check with `.venv/Scripts/python.exe -m ruff check apps tests`. Migrations are excluded from ruff.
- No hard deletes anywhere: new models subclass `NoDeleteModel` (from `apps.core.models`); admin classes return `False` from `has_delete_permission`.
- Every write goes through a service function: `@transaction.atomic`, role check via `_require_engineer_or_admin`, audit via `audit.record(actor, verb, obj, changes)`.
- Business-rule violations raise `AccessoryStateError` (a `DomainError` subclass); views catch `DomainError` → `messages.error(request, str(exc))`.
- Permission failures raise `django.core.exceptions.PermissionDenied` (renders as 403).
- The backup store (catalog page, stock counts) is engineer/admin only — including GET. Staff may see the fitted-accessories list on the equipment detail page but no stock numbers and no buttons.
- Commit messages: single line, conventional-commit style, suffixed `(#25)`.
- Templates live in the project-level `templates/` directory (not inside apps).
- URL names are global (no app namespace), e.g. `accessory_type_list`.

---

### Task 1: Models + migration

**Files:**
- Modify: `apps/equipment/models.py` (append after `StatusEvent`)
- Modify: `conftest.py` (add fixtures at end)
- Create: `apps/equipment/migrations/0004_*.py` (via makemigrations)
- Test: `tests/test_accessories.py` (new)

**Interfaces:**
- Consumes: `NoDeleteModel` from `apps.core.models`; `Equipment` from the same module.
- Produces: `AccessoryStatus` (TextChoices: WORKING="working", FAULTY="faulty", CONDEMNED="condemned"), `AccessoryType(name, equipment_name, stock_qty, notes, created_at, updated_at)` with unique (name, equipment_name), `Accessory(type FK→AccessoryType related_name="units", equipment FK→Equipment related_name="accessories", status, serial_number, condemned_at, notes, created_at, updated_at)`. Fixtures `accessory_type` and `fitted_accessory` in `conftest.py`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_accessories.py`:

```python
import pytest
from django.db.utils import IntegrityError

from apps.equipment.models import Accessory, AccessoryStatus, AccessoryType

pytestmark = pytest.mark.django_db


def test_accessory_type_defaults(accessory_type):
    assert accessory_type.stock_qty == 0
    assert str(accessory_type) == "ECG cable — Patient Monitor SVM 7523"


def test_accessory_type_duplicate_rejected(accessory_type):
    with pytest.raises(IntegrityError):
        AccessoryType.objects.create(
            name="ECG cable", equipment_name="Patient Monitor SVM 7523"
        )


def test_accessory_defaults(fitted_accessory):
    assert fitted_accessory.status == AccessoryStatus.WORKING
    assert fitted_accessory.condemned_at is None
    assert fitted_accessory.equipment.accessories.count() == 1
    assert fitted_accessory.type.units.count() == 1


def test_no_hard_delete(accessory_type, fitted_accessory):
    with pytest.raises(TypeError):
        fitted_accessory.delete()
    with pytest.raises(TypeError):
        Accessory.objects.all().delete()
    with pytest.raises(TypeError):
        accessory_type.delete()
```

Append to `conftest.py` (and add `Accessory`, `AccessoryType` to its existing `from apps.equipment.models import ...` line):

```python
@pytest.fixture
def accessory_type(db):
    return AccessoryType.objects.create(
        name="ECG cable", equipment_name="Patient Monitor SVM 7523"
    )


@pytest.fixture
def fitted_accessory(accessory_type, equipment):
    return Accessory.objects.create(type=accessory_type, equipment=equipment)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_accessories.py -v`
Expected: FAIL — `ImportError: cannot import name 'Accessory'`

- [ ] **Step 3: Add the models**

Append to `apps/equipment/models.py` (after the `StatusEvent` class):

```python
class AccessoryStatus(models.TextChoices):
    WORKING = "working", "Working"
    FAULTY = "faulty", "Faulty"
    CONDEMNED = "condemned", "Condemned"


class AccessoryType(NoDeleteModel):
    """Catalog entry: 'ECG cable for Patient Monitor SVM 7523'. Backup spares
    in the in-house store are a counter here, not individual records."""

    name = models.CharField(max_length=200)
    equipment_name = models.CharField(
        max_length=200, help_text="The device this accessory is for."
    )
    stock_qty = models.PositiveIntegerField(
        default=0, help_text="New backup units in the in-house store."
    )
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name", "equipment_name"]
        constraints = [
            models.UniqueConstraint(
                fields=["name", "equipment_name"],
                name="unique_accessory_type_per_equipment",
            )
        ]

    def __str__(self):
        return f"{self.name} — {self.equipment_name}"


class Accessory(NoDeleteModel):
    """One physical accessory fitted on an equipment. Condemned units are
    kept forever (no-delete convention)."""

    type = models.ForeignKey(
        AccessoryType, on_delete=models.PROTECT, related_name="units"
    )
    equipment = models.ForeignKey(
        Equipment, on_delete=models.PROTECT, related_name="accessories"
    )
    status = models.CharField(
        max_length=20, choices=AccessoryStatus.choices, default=AccessoryStatus.WORKING
    )
    serial_number = models.CharField(
        max_length=100, blank=True, help_text="Many accessories are not serialized."
    )
    condemned_at = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["type__name", "id"]
        verbose_name_plural = "accessories"

    def __str__(self):
        return f"{self.type.name} on {self.equipment.serial_number}"
```

- [ ] **Step 4: Generate the migration**

Run: `.venv/Scripts/python.exe manage.py makemigrations equipment`
Expected: creates `apps/equipment/migrations/0004_...py` with `Create model AccessoryType` and `Create model Accessory`.

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_accessories.py -v`
Expected: 4 passed

- [ ] **Step 6: Lint and commit**

```bash
.venv/Scripts/python.exe -m ruff check apps tests
git add apps/equipment/models.py apps/equipment/migrations conftest.py tests/test_accessories.py
git commit -m "feat: add accessory inventory models (#25)"
```

---

### Task 2: Catalog + stock services

**Files:**
- Modify: `apps/core/exceptions.py` (append)
- Modify: `apps/equipment/services.py` (imports + append)
- Test: `tests/test_accessories.py` (append)

**Interfaces:**
- Consumes: models from Task 1; existing `_require_engineer_or_admin`, `audit.record`.
- Produces: `AccessoryStateError(DomainError)`; services `create_accessory_type(actor, **fields) -> AccessoryType`, `update_accessory_type(accessory_type, actor, **fields) -> AccessoryType`, `adjust_stock(accessory_type, actor, delta, reason) -> AccessoryType`. Audit verbs: `accessory_type.created`, `accessory_type.updated`, `accessory_type.stock_adjusted`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_accessories.py` (extend the existing import block accordingly):

```python
from django.core.exceptions import PermissionDenied

from apps.core.exceptions import AccessoryStateError
from apps.core.models import AuditLog
from apps.equipment import services


def test_staff_cannot_create_type(staff_user):
    with pytest.raises(PermissionDenied):
        services.create_accessory_type(
            staff_user, name="ECG cable", equipment_name="Monitor X"
        )


def test_create_type_writes_audit(engineer):
    accessory_type = services.create_accessory_type(
        engineer, name="NIBP cuff", equipment_name="Patient Monitor SVM 7523"
    )
    assert accessory_type.pk is not None
    assert AuditLog.objects.filter(verb="accessory_type.created").exists()


def test_update_type_records_diff(accessory_type, engineer):
    services.update_accessory_type(
        accessory_type,
        engineer,
        name="ECG cable 5-lead",
        equipment_name=accessory_type.equipment_name,
        notes="",
    )
    entry = AuditLog.objects.get(verb="accessory_type.updated")
    assert entry.changes["name"]["new"] == "ECG cable 5-lead"


def test_staff_cannot_adjust_stock(accessory_type, staff_user):
    with pytest.raises(PermissionDenied):
        services.adjust_stock(accessory_type, staff_user, 1, "sneaky")


def test_adjust_stock_add_and_remove(accessory_type, engineer):
    services.adjust_stock(accessory_type, engineer, 5, "Received shipment")
    accessory_type.refresh_from_db()
    assert accessory_type.stock_qty == 5
    services.adjust_stock(accessory_type, engineer, -2, "Issued to ICU")
    accessory_type.refresh_from_db()
    assert accessory_type.stock_qty == 3
    entry = AuditLog.objects.filter(verb="accessory_type.stock_adjusted").last()
    assert entry.changes == {"delta": -2, "reason": "Issued to ICU", "stock_qty": 3}


def test_stock_cannot_go_negative(accessory_type, engineer):
    with pytest.raises(AccessoryStateError):
        services.adjust_stock(accessory_type, engineer, -1, "oops")
    accessory_type.refresh_from_db()
    assert accessory_type.stock_qty == 0


def test_zero_stock_delta_rejected(accessory_type, engineer):
    with pytest.raises(AccessoryStateError):
        services.adjust_stock(accessory_type, engineer, 0, "noop")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_accessories.py -v`
Expected: new tests FAIL — `ImportError: cannot import name 'AccessoryStateError'`

- [ ] **Step 3: Implement**

Append to `apps/core/exceptions.py`:

```python
class AccessoryStateError(DomainError):
    pass
```

In `apps/equipment/services.py`, change the two import lines:

```python
from apps.core.exceptions import AccessoryStateError, InvalidTransition

from .models import (
    Accessory,
    AccessoryStatus,
    AccessoryType,
    Equipment,
    EquipmentStatus,
    StatusEvent,
)
```

Append at the end of the file:

```python
@transaction.atomic
def create_accessory_type(actor, **fields):
    _require_engineer_or_admin(actor)
    accessory_type = AccessoryType.objects.create(**fields)
    audit.record(
        actor,
        "accessory_type.created",
        accessory_type,
        {"name": accessory_type.name, "equipment_name": accessory_type.equipment_name},
    )
    return accessory_type


@transaction.atomic
def update_accessory_type(accessory_type, actor, **fields):
    """Catalog fields only — stock_qty is changed exclusively by adjust_stock."""
    _require_engineer_or_admin(actor)
    changes = {}
    for name, value in fields.items():
        old = getattr(accessory_type, name)
        if old != value:
            changes[name] = {"old": str(old), "new": str(value)}
            setattr(accessory_type, name, value)
    if changes:
        accessory_type.save(update_fields=list(changes.keys()))
        audit.record(actor, "accessory_type.updated", accessory_type, changes)
    return accessory_type


@transaction.atomic
def adjust_stock(accessory_type, actor, delta, reason):
    _require_engineer_or_admin(actor)
    if delta == 0:
        raise AccessoryStateError("Stock adjustment cannot be zero.")
    locked = AccessoryType.objects.select_for_update().get(pk=accessory_type.pk)
    new_qty = locked.stock_qty + delta
    if new_qty < 0:
        raise AccessoryStateError("Stock cannot go below zero.")
    locked.stock_qty = new_qty
    locked.save(update_fields=["stock_qty"])
    audit.record(
        actor,
        "accessory_type.stock_adjusted",
        locked,
        {"delta": delta, "reason": reason, "stock_qty": new_qty},
    )
    return locked
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_accessories.py -v`
Expected: all pass

- [ ] **Step 5: Lint and commit**

```bash
.venv/Scripts/python.exe -m ruff check apps tests
git add apps/core/exceptions.py apps/equipment/services.py tests/test_accessories.py
git commit -m "feat: accessory type and stock services (#25)"
```

---

### Task 3: Attach / update / condemn services

**Files:**
- Modify: `apps/equipment/services.py` (append)
- Test: `tests/test_accessories.py` (append)

**Interfaces:**
- Consumes: Task 1 models, Task 2 error class and `adjust_stock` audit conventions.
- Produces: `attach_accessory(equipment, actor, accessory_type, from_stock, serial_number="", notes="") -> Accessory`, `update_accessory(accessory, actor, **fields) -> Accessory`, `condemn_accessory(accessory, actor, reason) -> Accessory`. Audit verbs: `accessory.attached`, `accessory.updated`, `accessory.condemned` (plus an `accessory_type.stock_adjusted` entry when `from_stock=True`).

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_accessories.py` (add `EquipmentStatus` to the models import):

```python
def test_staff_cannot_attach(accessory_type, equipment, staff_user):
    with pytest.raises(PermissionDenied):
        services.attach_accessory(
            equipment, staff_user, accessory_type, from_stock=False
        )


def test_attach_from_stock_decrements(accessory_type, equipment, engineer):
    services.adjust_stock(accessory_type, engineer, 2, "Initial stock")
    accessory = services.attach_accessory(
        equipment, engineer, accessory_type, from_stock=True
    )
    accessory_type.refresh_from_db()
    assert accessory_type.stock_qty == 1
    assert accessory.equipment == equipment
    assert AuditLog.objects.filter(verb="accessory.attached").exists()


def test_attach_refused_when_stock_empty(accessory_type, equipment, engineer):
    with pytest.raises(AccessoryStateError):
        services.attach_accessory(
            equipment, engineer, accessory_type, from_stock=True
        )
    assert equipment.accessories.count() == 0


def test_attach_without_stock_keeps_counter(accessory_type, equipment, engineer):
    services.attach_accessory(equipment, engineer, accessory_type, from_stock=False)
    accessory_type.refresh_from_db()
    assert accessory_type.stock_qty == 0
    assert equipment.accessories.count() == 1


def test_attach_refused_on_condemned_equipment(
    accessory_type, make_equipment, engineer
):
    condemned = make_equipment(
        serial_number="SN-0009", status=EquipmentStatus.CONDEMNED
    )
    with pytest.raises(AccessoryStateError):
        services.attach_accessory(
            condemned, engineer, accessory_type, from_stock=False
        )


def test_update_accessory_diff_audited(fitted_accessory, engineer):
    services.update_accessory(
        fitted_accessory, engineer, status=AccessoryStatus.FAULTY, notes="No signal."
    )
    fitted_accessory.refresh_from_db()
    assert fitted_accessory.status == AccessoryStatus.FAULTY
    entry = AuditLog.objects.get(verb="accessory.updated")
    assert entry.changes["status"]["new"] == "faulty"


def test_condemn_accessory_stamps_and_locks(fitted_accessory, engineer):
    services.condemn_accessory(fitted_accessory, engineer, "Cable snapped")
    fitted_accessory.refresh_from_db()
    assert fitted_accessory.status == AccessoryStatus.CONDEMNED
    assert fitted_accessory.condemned_at is not None
    assert AuditLog.objects.filter(verb="accessory.condemned").exists()
    with pytest.raises(AccessoryStateError):
        services.update_accessory(fitted_accessory, engineer, notes="too late")
    with pytest.raises(AccessoryStateError):
        services.condemn_accessory(fitted_accessory, engineer, "again")


def test_update_refused_on_condemned_equipment(
    fitted_accessory, equipment, engineer
):
    equipment.status = EquipmentStatus.CONDEMNED
    equipment.save(update_fields=["status"])
    with pytest.raises(AccessoryStateError):
        services.update_accessory(fitted_accessory, engineer, notes="x")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_accessories.py -v`
Expected: new tests FAIL — `AttributeError: module ... has no attribute 'attach_accessory'`

- [ ] **Step 3: Implement**

Append to `apps/equipment/services.py`:

```python
@transaction.atomic
def attach_accessory(
    equipment, actor, accessory_type, from_stock, serial_number="", notes=""
):
    _require_engineer_or_admin(actor)
    equipment.refresh_from_db()
    if equipment.status == EquipmentStatus.CONDEMNED:
        raise AccessoryStateError("Cannot attach accessories to condemned equipment.")
    if from_stock:
        locked = AccessoryType.objects.select_for_update().get(pk=accessory_type.pk)
        if locked.stock_qty < 1:
            raise AccessoryStateError(
                "No backup stock available for this accessory type."
            )
        locked.stock_qty -= 1
        locked.save(update_fields=["stock_qty"])
        audit.record(
            actor,
            "accessory_type.stock_adjusted",
            locked,
            {
                "delta": -1,
                "reason": f"Attached to {equipment.serial_number}",
                "stock_qty": locked.stock_qty,
            },
        )
    accessory = Accessory.objects.create(
        type=accessory_type,
        equipment=equipment,
        serial_number=serial_number,
        notes=notes,
    )
    audit.record(
        actor,
        "accessory.attached",
        accessory,
        {
            "type": str(accessory_type),
            "equipment": equipment.serial_number,
            "from_stock": from_stock,
        },
    )
    return accessory


@transaction.atomic
def update_accessory(accessory, actor, **fields):
    _require_engineer_or_admin(actor)
    accessory.refresh_from_db()
    if accessory.status == AccessoryStatus.CONDEMNED:
        raise AccessoryStateError(
            "This accessory is condemned; it can no longer be edited."
        )
    accessory.equipment.refresh_from_db()
    if accessory.equipment.status == EquipmentStatus.CONDEMNED:
        raise AccessoryStateError("Cannot edit accessories of condemned equipment.")
    changes = {}
    for name, value in fields.items():
        old = getattr(accessory, name)
        if old != value:
            changes[name] = {"old": str(old), "new": str(value)}
            setattr(accessory, name, value)
    if changes:
        accessory.save(update_fields=list(changes.keys()))
        audit.record(actor, "accessory.updated", accessory, changes)
    return accessory


@transaction.atomic
def condemn_accessory(accessory, actor, reason):
    from django.utils import timezone

    _require_engineer_or_admin(actor)
    accessory.refresh_from_db()
    if accessory.status == AccessoryStatus.CONDEMNED:
        raise AccessoryStateError("This accessory is already condemned.")
    accessory.status = AccessoryStatus.CONDEMNED
    accessory.condemned_at = timezone.now()
    accessory.save(update_fields=["status", "condemned_at"])
    audit.record(actor, "accessory.condemned", accessory, {"reason": reason})
    return accessory
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_accessories.py -v`
Expected: all pass

- [ ] **Step 5: Lint and commit**

```bash
.venv/Scripts/python.exe -m ruff check apps tests
git add apps/equipment/services.py tests/test_accessories.py
git commit -m "feat: attach, update and condemn accessory services (#25)"
```

---

### Task 4: Forms + accessories catalog pages

**Files:**
- Modify: `apps/equipment/forms.py` (imports + append)
- Modify: `apps/equipment/views.py` (imports + append)
- Modify: `apps/equipment/urls.py` (append paths)
- Create: `templates/equipment/accessory_type_list.html`
- Create: `templates/equipment/accessory_form.html` (generic, reused by every accessory form view)
- Test: `tests/test_accessory_views.py` (new)

**Interfaces:**
- Consumes: Task 2 services; existing `RoleRequiredMixin`, `ENGINEER_ROLES`, `DomainError`, `INPUT` CSS constant in forms.py.
- Produces: forms `AccessoryTypeForm`, `StockAdjustForm` (fields: action add/remove, quantity ≥ 1, reason); URL names `accessory_type_list`, `accessory_type_create`, `accessory_type_edit`, `accessory_stock_adjust`; generic template `equipment/accessory_form.html` rendering context vars `form`, `form_title`, `form_subtitle`, `cancel_url` (Tasks 5 uses it too).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_accessory_views.py`:

```python
import pytest
from django.urls import reverse

from apps.equipment.models import AccessoryType

pytestmark = pytest.mark.django_db


def test_staff_cannot_see_catalog(client, staff_user):
    client.force_login(staff_user)
    assert client.get(reverse("accessory_type_list")).status_code == 403


def test_staff_cannot_open_catalog_write_pages(client, staff_user, accessory_type):
    client.force_login(staff_user)
    urls = [
        reverse("accessory_type_create"),
        reverse("accessory_type_edit", args=[accessory_type.pk]),
        reverse("accessory_stock_adjust", args=[accessory_type.pk]),
    ]
    for url in urls:
        assert client.get(url).status_code == 403


def test_engineer_sees_catalog_with_counts(
    client, engineer, accessory_type, fitted_accessory
):
    client.force_login(engineer)
    response = client.get(reverse("accessory_type_list"))
    assert response.status_code == 200
    assert b"ECG cable" in response.content
    assert b"In store: 0" in response.content
    assert b"Fitted: 1" in response.content


def test_engineer_creates_type(client, engineer):
    client.force_login(engineer)
    response = client.post(
        reverse("accessory_type_create"),
        {
            "name": "SpO2 probe",
            "equipment_name": "Patient Monitor SVM 7523",
            "notes": "",
        },
    )
    assert response.status_code == 302
    assert AccessoryType.objects.filter(name="SpO2 probe").exists()


def test_duplicate_type_shows_form_error(client, engineer, accessory_type):
    client.force_login(engineer)
    response = client.post(
        reverse("accessory_type_create"),
        {
            "name": "ECG cable",
            "equipment_name": "Patient Monitor SVM 7523",
            "notes": "",
        },
    )
    assert response.status_code == 200
    assert AccessoryType.objects.count() == 1


def test_engineer_edits_type(client, engineer, accessory_type):
    client.force_login(engineer)
    response = client.post(
        reverse("accessory_type_edit", args=[accessory_type.pk]),
        {
            "name": "ECG cable 5-lead",
            "equipment_name": "Patient Monitor SVM 7523",
            "notes": "",
        },
    )
    assert response.status_code == 302
    accessory_type.refresh_from_db()
    assert accessory_type.name == "ECG cable 5-lead"


def test_engineer_adjusts_stock_via_view(client, engineer, accessory_type):
    client.force_login(engineer)
    response = client.post(
        reverse("accessory_stock_adjust", args=[accessory_type.pk]),
        {"action": "add", "quantity": 5, "reason": "Received shipment"},
    )
    assert response.status_code == 302
    accessory_type.refresh_from_db()
    assert accessory_type.stock_qty == 5


def test_stock_remove_below_zero_shows_error(client, engineer, accessory_type):
    client.force_login(engineer)
    response = client.post(
        reverse("accessory_stock_adjust", args=[accessory_type.pk]),
        {"action": "remove", "quantity": 1, "reason": "oops"},
        follow=True,
    )
    accessory_type.refresh_from_db()
    assert accessory_type.stock_qty == 0
    assert b"Stock cannot go below zero." in response.content
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_accessory_views.py -v`
Expected: FAIL — `NoReverseMatch: Reverse for 'accessory_type_list' not found`

- [ ] **Step 3: Implement forms**

In `apps/equipment/forms.py`, change the models import to `from .models import Accessory, AccessoryStatus, AccessoryType, Equipment` (the `Accessory`/`AccessoryStatus` names are used in Task 5's forms, added in the same file — see below; add all now so this import line is final). Append:

```python
class AccessoryTypeForm(forms.ModelForm):
    class Meta:
        model = AccessoryType
        fields = ["name", "equipment_name", "notes"]
        widgets = {"notes": forms.Textarea(attrs={"rows": 3})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.setdefault("class", INPUT)


class StockAdjustForm(forms.Form):
    ACTIONS = (("add", "Add to stock"), ("remove", "Remove from stock"))

    action = forms.ChoiceField(
        choices=ACTIONS, widget=forms.Select(attrs={"class": INPUT})
    )
    quantity = forms.IntegerField(
        min_value=1, widget=forms.NumberInput(attrs={"class": INPUT})
    )
    reason = forms.CharField(widget=forms.TextInput(attrs={"class": INPUT}))
```

- [ ] **Step 4: Implement views**

In `apps/equipment/views.py`:
- Add to the django imports: `from django.db.models import Count, Q` (the `Q` import already exists — extend that line to `from django.db.models import Count, Q`).
- Extend the forms import to `from .forms import AccessoryTypeForm, CondemnForm, EquipmentForm, StockAdjustForm` (Task 5 adds two more names to this line).
- Extend the models import to `from .models import AccessoryStatus, AccessoryType, Equipment, EquipmentStatus` (Task 5 adds `Accessory`).
- Add `from django.views.generic import DetailView, ListView, View` — already present, no change.

Append the views:

```python
class AccessoryTypeListView(RoleRequiredMixin, ListView):
    allowed_roles = ENGINEER_ROLES
    template_name = "equipment/accessory_type_list.html"

    def get_queryset(self):
        return AccessoryType.objects.annotate(
            fitted_count=Count(
                "units", filter=~Q(units__status=AccessoryStatus.CONDEMNED)
            )
        )


class AccessoryTypeCreateView(RoleRequiredMixin, View):
    allowed_roles = ENGINEER_ROLES

    def get(self, request):
        return render(
            request,
            "equipment/accessory_form.html",
            {
                "form": AccessoryTypeForm(),
                "form_title": "Add accessory type",
                "form_subtitle": "Define a catalog entry once; reuse it everywhere.",
                "cancel_url": reverse("accessory_type_list"),
            },
        )

    def post(self, request):
        form = AccessoryTypeForm(request.POST)
        if not form.is_valid():
            return render(
                request,
                "equipment/accessory_form.html",
                {
                    "form": form,
                    "form_title": "Add accessory type",
                    "form_subtitle": "Define a catalog entry once; reuse it everywhere.",
                    "cancel_url": reverse("accessory_type_list"),
                },
            )
        services.create_accessory_type(request.user, **form.cleaned_data)
        messages.success(request, "Accessory type added.")
        return redirect("accessory_type_list")


class AccessoryTypeEditView(RoleRequiredMixin, View):
    allowed_roles = ENGINEER_ROLES

    def _render(self, request, form, accessory_type):
        return render(
            request,
            "equipment/accessory_form.html",
            {
                "form": form,
                "form_title": f"Edit {accessory_type.name}",
                "form_subtitle": accessory_type.equipment_name,
                "cancel_url": reverse("accessory_type_list"),
            },
        )

    def get(self, request, pk):
        accessory_type = get_object_or_404(AccessoryType, pk=pk)
        return self._render(
            request, AccessoryTypeForm(instance=accessory_type), accessory_type
        )

    def post(self, request, pk):
        accessory_type = get_object_or_404(AccessoryType, pk=pk)
        form = AccessoryTypeForm(request.POST, instance=accessory_type)
        if not form.is_valid():
            return self._render(request, form, accessory_type)
        fresh = AccessoryType.objects.get(pk=pk)
        services.update_accessory_type(fresh, request.user, **form.cleaned_data)
        messages.success(request, "Accessory type updated.")
        return redirect("accessory_type_list")


class AccessoryStockAdjustView(RoleRequiredMixin, View):
    allowed_roles = ENGINEER_ROLES

    def _render(self, request, form, accessory_type):
        return render(
            request,
            "equipment/accessory_form.html",
            {
                "form": form,
                "form_title": f"Adjust stock — {accessory_type.name}",
                "form_subtitle": (
                    f"{accessory_type.equipment_name} · currently in store: "
                    f"{accessory_type.stock_qty}"
                ),
                "cancel_url": reverse("accessory_type_list"),
            },
        )

    def get(self, request, pk):
        accessory_type = get_object_or_404(AccessoryType, pk=pk)
        return self._render(request, StockAdjustForm(), accessory_type)

    def post(self, request, pk):
        accessory_type = get_object_or_404(AccessoryType, pk=pk)
        form = StockAdjustForm(request.POST)
        if not form.is_valid():
            return self._render(request, form, accessory_type)
        delta = form.cleaned_data["quantity"]
        if form.cleaned_data["action"] == "remove":
            delta = -delta
        try:
            services.adjust_stock(
                accessory_type, request.user, delta, form.cleaned_data["reason"]
            )
        except DomainError as exc:
            messages.error(request, str(exc))
        else:
            messages.success(request, "Stock updated.")
        return redirect("accessory_type_list")
```

Also add `from django.urls import reverse` to the imports of `apps/equipment/views.py`.

- [ ] **Step 5: Wire URLs**

Append to `urlpatterns` in `apps/equipment/urls.py` (before the closing bracket; no conflict with `<int:pk>/` because that converter only matches digits):

```python
    path(
        "accessories/",
        views.AccessoryTypeListView.as_view(),
        name="accessory_type_list",
    ),
    path(
        "accessories/types/new/",
        views.AccessoryTypeCreateView.as_view(),
        name="accessory_type_create",
    ),
    path(
        "accessories/types/<int:pk>/edit/",
        views.AccessoryTypeEditView.as_view(),
        name="accessory_type_edit",
    ),
    path(
        "accessories/types/<int:pk>/stock/",
        views.AccessoryStockAdjustView.as_view(),
        name="accessory_stock_adjust",
    ),
```

- [ ] **Step 6: Create templates**

Create `templates/equipment/accessory_type_list.html`:

```html
{% extends "base.html" %}
{% block title %}Accessories{% endblock %}
{% block page_title %}Accessories{% endblock %}
{% block content %}
<div class="mb-5 flex flex-wrap items-center justify-between gap-3">
  <div>
    <h1 class="text-2xl font-bold">Accessory inventory</h1>
    <p class="mt-0.5 text-sm text-slate-500 dark:text-slate-400">Catalog of accessory types and backup store counts.</p>
  </div>
  <a href="{% url 'accessory_type_create' %}" class="btn-primary">Add type</a>
</div>
<div class="card p-5">
  <div class="space-y-3">
    {% for type in object_list %}
    <div class="flex flex-wrap items-center gap-2 rounded-lg border border-slate-100 px-4 py-3 text-sm dark:border-slate-800">
      <span class="font-medium">{{ type.name }}</span>
      <span class="text-slate-500 dark:text-slate-400">{{ type.equipment_name }}</span>
      {% if type.stock_qty == 0 %}<span class="badge-danger">In store: 0</span>
      {% else %}<span class="badge-working">In store: {{ type.stock_qty }}</span>{% endif %}
      <span class="badge-info">Fitted: {{ type.fitted_count }}</span>
      {% if type.notes %}<span class="text-slate-500 dark:text-slate-400">“{{ type.notes }}”</span>{% endif %}
      <span class="ml-auto flex gap-2">
        <a href="{% url 'accessory_stock_adjust' type.pk %}" class="btn-ghost btn-sm">Adjust stock</a>
        <a href="{% url 'accessory_type_edit' type.pk %}" class="btn-ghost btn-sm">Edit</a>
      </span>
    </div>
    {% empty %}<p class="text-sm text-slate-500 dark:text-slate-400">No accessory types yet. Add the first one.</p>{% endfor %}
  </div>
</div>
{% endblock %}
```

Create `templates/equipment/accessory_form.html` (generic — also used by Task 5's attach/edit views):

```html
{% extends "base.html" %}
{% block title %}{{ form_title }}{% endblock %}
{% block page_title %}Accessories{% endblock %}
{% block content %}
<div class="card mx-auto max-w-xl p-6">
  <h1 class="text-xl font-bold">{{ form_title }}</h1>
  {% if form_subtitle %}
  <p class="mt-1 text-sm text-slate-500 dark:text-slate-400">{{ form_subtitle }}</p>
  {% endif %}
  <form method="post" class="mt-5 space-y-4">
    {% csrf_token %}
    {% for error in form.non_field_errors %}
    <p class="text-sm text-red-700 dark:text-red-400">{{ error }}</p>
    {% endfor %}
    {% for field in form %}
    <div>
      <label class="mb-1 block text-sm font-medium" for="{{ field.id_for_label }}">{{ field.label }}</label>
      {{ field }}
      {% if field.help_text %}<p class="mt-1 text-xs text-slate-500 dark:text-slate-400">{{ field.help_text }}</p>{% endif %}
      {% for error in field.errors %}<p class="mt-1 text-sm text-red-700 dark:text-red-400">{{ error }}</p>{% endfor %}
    </div>
    {% endfor %}
    <div class="flex justify-end gap-2 border-t border-slate-100 pt-4 dark:border-slate-800">
      <a href="{{ cancel_url }}" class="btn-ghost">Cancel</a>
      <button class="btn-primary">Save</button>
    </div>
  </form>
</div>
{% endblock %}
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_accessory_views.py -v`
Expected: all pass

- [ ] **Step 8: Lint and commit**

```bash
.venv/Scripts/python.exe -m ruff check apps tests
git add apps/equipment/forms.py apps/equipment/views.py apps/equipment/urls.py templates/equipment/accessory_type_list.html templates/equipment/accessory_form.html tests/test_accessory_views.py
git commit -m "feat: accessories catalog page with stock adjustments (#25)"
```

---

### Task 5: Equipment detail integration (attach / edit / condemn)

**Files:**
- Modify: `apps/equipment/forms.py` (append)
- Modify: `apps/equipment/views.py` (append + one context line in `EquipmentDetailView`)
- Modify: `apps/equipment/urls.py` (append paths)
- Modify: `templates/equipment/detail.html` (insert card)
- Create: `templates/equipment/accessory_condemn.html`
- Test: `tests/test_accessory_views.py` (append)

**Interfaces:**
- Consumes: Task 3 services, Task 4 generic template `equipment/accessory_form.html` and its context contract (`form`, `form_title`, `form_subtitle`, `cancel_url`).
- Produces: forms `AccessoryAttachForm` (fields: accessory_type, serial_number, from_stock, notes), `AccessoryEditForm` (status limited to working/faulty, serial_number, notes), `AccessoryCondemnForm` (reason); URL names `accessory_attach` (arg: equipment pk), `accessory_edit`, `accessory_condemn` (arg: accessory pk); `EquipmentDetailView` context key `accessories`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_accessory_views.py` (extend imports with `from apps.equipment.models import Accessory, AccessoryStatus, AccessoryType`):

```python
def test_staff_sees_fitted_list_but_no_buttons(
    client, staff_user, equipment, fitted_accessory
):
    client.force_login(staff_user)
    response = client.get(reverse("equipment_detail", args=[equipment.pk]))
    assert response.status_code == 200
    assert b"ECG cable" in response.content
    assert b"Attach accessory" not in response.content


def test_staff_cannot_open_accessory_write_pages(
    client, staff_user, equipment, fitted_accessory
):
    client.force_login(staff_user)
    urls = [
        reverse("accessory_attach", args=[equipment.pk]),
        reverse("accessory_edit", args=[fitted_accessory.pk]),
        reverse("accessory_condemn", args=[fitted_accessory.pk]),
    ]
    for url in urls:
        assert client.get(url).status_code == 403


def test_engineer_attaches_via_view(client, engineer, equipment, accessory_type):
    from apps.equipment import services

    services.adjust_stock(accessory_type, engineer, 1, "Initial stock")
    client.force_login(engineer)
    response = client.post(
        reverse("accessory_attach", args=[equipment.pk]),
        {
            "accessory_type": accessory_type.pk,
            "serial_number": "ACC-77",
            "from_stock": "on",
            "notes": "",
        },
    )
    assert response.status_code == 302
    accessory_type.refresh_from_db()
    assert accessory_type.stock_qty == 0
    assert equipment.accessories.filter(serial_number="ACC-77").exists()


def test_attach_at_zero_stock_shows_error(
    client, engineer, equipment, accessory_type
):
    client.force_login(engineer)
    response = client.post(
        reverse("accessory_attach", args=[equipment.pk]),
        {
            "accessory_type": accessory_type.pk,
            "serial_number": "",
            "from_stock": "on",
            "notes": "",
        },
        follow=True,
    )
    assert b"No backup stock available" in response.content
    assert equipment.accessories.count() == 0


def test_engineer_edits_accessory_via_view(client, engineer, fitted_accessory):
    client.force_login(engineer)
    response = client.post(
        reverse("accessory_edit", args=[fitted_accessory.pk]),
        {"status": "faulty", "serial_number": "", "notes": "Cracked housing."},
    )
    assert response.status_code == 302
    fitted_accessory.refresh_from_db()
    assert fitted_accessory.status == AccessoryStatus.FAULTY


def test_edit_form_rejects_condemned_status(client, engineer, fitted_accessory):
    client.force_login(engineer)
    response = client.post(
        reverse("accessory_edit", args=[fitted_accessory.pk]),
        {"status": "condemned", "serial_number": "", "notes": ""},
    )
    assert response.status_code == 200
    fitted_accessory.refresh_from_db()
    assert fitted_accessory.status == AccessoryStatus.WORKING


def test_engineer_condemns_accessory_via_view(client, engineer, fitted_accessory):
    client.force_login(engineer)
    response = client.post(
        reverse("accessory_condemn", args=[fitted_accessory.pk]),
        {"reason": "Cable snapped"},
    )
    assert response.status_code == 302
    fitted_accessory.refresh_from_db()
    assert fitted_accessory.status == AccessoryStatus.CONDEMNED
    assert fitted_accessory.condemned_at is not None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_accessory_views.py -v`
Expected: new tests FAIL — `NoReverseMatch: Reverse for 'accessory_attach' not found`

- [ ] **Step 3: Implement forms**

Append to `apps/equipment/forms.py`:

```python
class AccessoryAttachForm(forms.Form):
    accessory_type = forms.ModelChoiceField(
        queryset=AccessoryType.objects.all(),
        label="Accessory type",
        widget=forms.Select(attrs={"class": INPUT}),
    )
    serial_number = forms.CharField(
        required=False,
        help_text="Leave blank for non-serialized accessories.",
        widget=forms.TextInput(attrs={"class": INPUT}),
    )
    from_stock = forms.BooleanField(
        required=False,
        initial=True,
        label="Take from backup stock",
        help_text="Untick when cataloging an accessory that is already fitted.",
    )
    notes = forms.CharField(
        required=False, widget=forms.Textarea(attrs={"rows": 3, "class": INPUT})
    )


class AccessoryEditForm(forms.ModelForm):
    class Meta:
        model = Accessory
        fields = ["status", "serial_number", "notes"]
        widgets = {"notes": forms.Textarea(attrs={"rows": 3})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Condemning is a separate, deliberate action with its own page.
        self.fields["status"].choices = [
            (AccessoryStatus.WORKING, "Working"),
            (AccessoryStatus.FAULTY, "Faulty"),
        ]
        for field in self.fields.values():
            field.widget.attrs.setdefault("class", INPUT)


class AccessoryCondemnForm(forms.Form):
    reason = forms.CharField(widget=forms.Textarea(attrs={"rows": 3, "class": INPUT}))
```

- [ ] **Step 4: Implement views and context**

In `apps/equipment/views.py`, extend the imports: forms line becomes `from .forms import (AccessoryAttachForm, AccessoryCondemnForm, AccessoryEditForm, AccessoryTypeForm, CondemnForm, EquipmentForm, StockAdjustForm)` (wrap in parentheses, one name per line, isort style); models line gains `Accessory`.

In `EquipmentDetailView.get_context_data`, after the `ctx["open_complaints"] = ...` line, add:

```python
        ctx["accessories"] = eq.accessories.select_related("type")
```

Append the views:

```python
class AccessoryAttachView(RoleRequiredMixin, View):
    allowed_roles = ENGINEER_ROLES

    def _render(self, request, form, equipment):
        return render(
            request,
            "equipment/accessory_form.html",
            {
                "form": form,
                "form_title": "Attach accessory",
                "form_subtitle": (
                    f"{equipment.name} {equipment.model_number} · "
                    f"{equipment.serial_number}"
                ),
                "cancel_url": reverse("equipment_detail", args=[equipment.pk]),
            },
        )

    def get(self, request, pk):
        equipment = get_object_or_404(Equipment, pk=pk)
        return self._render(request, AccessoryAttachForm(), equipment)

    def post(self, request, pk):
        equipment = get_object_or_404(Equipment, pk=pk)
        form = AccessoryAttachForm(request.POST)
        if not form.is_valid():
            return self._render(request, form, equipment)
        try:
            services.attach_accessory(
                equipment,
                request.user,
                form.cleaned_data["accessory_type"],
                from_stock=form.cleaned_data["from_stock"],
                serial_number=form.cleaned_data["serial_number"],
                notes=form.cleaned_data["notes"],
            )
        except DomainError as exc:
            messages.error(request, str(exc))
        else:
            messages.success(request, "Accessory attached.")
        return redirect("equipment_detail", pk=pk)


class AccessoryEditView(RoleRequiredMixin, View):
    allowed_roles = ENGINEER_ROLES

    def _render(self, request, form, accessory):
        return render(
            request,
            "equipment/accessory_form.html",
            {
                "form": form,
                "form_title": f"Edit {accessory.type.name}",
                "form_subtitle": (
                    f"On {accessory.equipment.name} "
                    f"{accessory.equipment.serial_number}"
                ),
                "cancel_url": reverse(
                    "equipment_detail", args=[accessory.equipment_id]
                ),
            },
        )

    def get(self, request, pk):
        accessory = get_object_or_404(
            Accessory.objects.select_related("type", "equipment"), pk=pk
        )
        return self._render(request, AccessoryEditForm(instance=accessory), accessory)

    def post(self, request, pk):
        accessory = get_object_or_404(
            Accessory.objects.select_related("type", "equipment"), pk=pk
        )
        form = AccessoryEditForm(request.POST, instance=accessory)
        if not form.is_valid():
            return self._render(request, form, accessory)
        fresh = Accessory.objects.get(pk=pk)
        try:
            services.update_accessory(fresh, request.user, **form.cleaned_data)
        except DomainError as exc:
            messages.error(request, str(exc))
        else:
            messages.success(request, "Accessory updated.")
        return redirect("equipment_detail", pk=accessory.equipment_id)


class AccessoryCondemnView(RoleRequiredMixin, View):
    allowed_roles = ENGINEER_ROLES

    def get(self, request, pk):
        accessory = get_object_or_404(
            Accessory.objects.select_related("type", "equipment"), pk=pk
        )
        return render(
            request,
            "equipment/accessory_condemn.html",
            {"accessory": accessory, "form": AccessoryCondemnForm()},
        )

    def post(self, request, pk):
        accessory = get_object_or_404(
            Accessory.objects.select_related("type", "equipment"), pk=pk
        )
        form = AccessoryCondemnForm(request.POST)
        if not form.is_valid():
            return render(
                request,
                "equipment/accessory_condemn.html",
                {"accessory": accessory, "form": form},
            )
        try:
            services.condemn_accessory(
                accessory, request.user, form.cleaned_data["reason"]
            )
        except DomainError as exc:
            messages.error(request, str(exc))
        else:
            messages.success(request, "Accessory condemned. Its record is preserved.")
        return redirect("equipment_detail", pk=accessory.equipment_id)
```

- [ ] **Step 5: Wire URLs**

Append to `urlpatterns` in `apps/equipment/urls.py`:

```python
    path(
        "<int:pk>/accessories/attach/",
        views.AccessoryAttachView.as_view(),
        name="accessory_attach",
    ),
    path(
        "accessories/<int:pk>/edit/",
        views.AccessoryEditView.as_view(),
        name="accessory_edit",
    ),
    path(
        "accessories/<int:pk>/condemn/",
        views.AccessoryCondemnView.as_view(),
        name="accessory_condemn",
    ),
```

- [ ] **Step 6: Templates**

In `templates/equipment/detail.html`, insert this card between the Work Orders card (ends with the `</div>` after `No repairs recorded.`) and the Preventive Maintenance card:

```html
<div class="card mt-6 p-5">
  <div class="mb-3 flex flex-wrap items-center gap-2">
    <h2 class="font-semibold">Accessories</h2>
    {% if can_engineer and equipment.status != 'condemned' %}
    <span class="ml-auto">
      <a href="{% url 'accessory_attach' equipment.pk %}" class="btn-ghost btn-sm">Attach accessory</a>
    </span>
    {% endif %}
  </div>
  <div class="space-y-3">
    {% for acc in accessories %}
    <div class="flex flex-wrap items-center gap-2 rounded-lg border border-slate-100 px-4 py-3 text-sm dark:border-slate-800">
      <span class="font-medium">{{ acc.type.name }}</span>
      {% if acc.serial_number %}<span class="font-mono text-slate-500 dark:text-slate-400">{{ acc.serial_number }}</span>{% endif %}
      {% if acc.status == 'working' %}<span class="badge-working">{{ acc.get_status_display }}</span>
      {% elif acc.status == 'faulty' %}<span class="badge-repair">{{ acc.get_status_display }}</span>
      {% else %}<span class="badge-danger">{{ acc.get_status_display }}</span>{% endif %}
      {% if acc.notes %}<span class="text-slate-500 dark:text-slate-400">“{{ acc.notes }}”</span>{% endif %}
      {% if can_engineer and equipment.status != 'condemned' and acc.status != 'condemned' %}
      <span class="ml-auto flex gap-2">
        <a href="{% url 'accessory_edit' acc.pk %}" class="btn-ghost btn-sm">Edit</a>
        <a href="{% url 'accessory_condemn' acc.pk %}" class="btn-danger btn-sm">Condemn…</a>
      </span>
      {% endif %}
    </div>
    {% empty %}<p class="text-sm text-slate-500 dark:text-slate-400">No accessories recorded.</p>{% endfor %}
  </div>
</div>
```

Create `templates/equipment/accessory_condemn.html`:

```html
{% extends "base.html" %}
{% block title %}Condemn accessory{% endblock %}
{% block page_title %}Accessories{% endblock %}
{% block content %}
<div class="card mx-auto max-w-xl overflow-hidden">
  <div class="border-b border-red-200 bg-red-50 px-6 py-4 dark:border-red-500/30 dark:bg-red-500/10">
    <h1 class="text-xl font-bold text-red-800 dark:text-red-300">Condemn accessory</h1>
    <p class="mt-1 text-sm text-red-700/80 dark:text-red-300/80">This cannot be undone.</p>
  </div>
  <div class="p-6">
    <p class="mb-5 text-sm text-slate-600 dark:text-slate-300">
      {{ accessory.type.name }} on {{ accessory.equipment.name }}
      {{ accessory.equipment.serial_number }} will be permanently retired.
      Its record is preserved forever.
    </p>
    <form method="post" class="space-y-4">
      {% csrf_token %}
      {% for field in form %}
      <div>
        <label class="mb-1 block text-sm font-medium" for="{{ field.id_for_label }}">{{ field.label }}</label>
        {{ field }}
        {% for error in field.errors %}<p class="mt-1 text-sm text-red-700 dark:text-red-400">{{ error }}</p>{% endfor %}
      </div>
      {% endfor %}
      <div class="flex justify-end gap-2 border-t border-slate-100 pt-4 dark:border-slate-800">
        <a href="{% url 'equipment_detail' accessory.equipment_id %}" class="btn-ghost">Cancel</a>
        <button class="btn-danger">Condemn permanently</button>
      </div>
    </form>
  </div>
</div>
{% endblock %}
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_accessory_views.py tests/test_accessories.py -v`
Expected: all pass

- [ ] **Step 8: Lint and commit**

```bash
.venv/Scripts/python.exe -m ruff check apps tests
git add apps/equipment/forms.py apps/equipment/views.py apps/equipment/urls.py templates/equipment/detail.html templates/equipment/accessory_condemn.html tests/test_accessory_views.py
git commit -m "feat: equipment detail accessories section (#25)"
```

---

### Task 6: Navigation + admin

**Files:**
- Modify: `templates/base.html` (nav item + active-name lists)
- Modify: `apps/equipment/admin.py`
- Test: `tests/test_accessory_views.py` (append)

**Interfaces:**
- Consumes: URL names from Tasks 4–5; `user.is_engineer_or_admin` template property.
- Produces: engineer-only "Accessories" sidebar link; both models registered in Django admin with delete disabled.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_accessory_views.py`:

```python
def test_nav_shows_accessories_link_to_engineer_only(client, engineer, staff_user):
    client.force_login(engineer)
    assert b'href="/equipment/accessories/"' in client.get("/").content
    client.force_login(staff_user)
    assert b'href="/equipment/accessories/"' not in client.get("/").content
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_accessory_views.py::test_nav_shows_accessories_link_to_engineer_only -v`
Expected: FAIL on the engineer assertion (link not present)

- [ ] **Step 3: Implement**

In `templates/base.html`:

1. Directly after the Equipment `</a>` (the link whose active list names `equipment_list ...`), add:

```html
      {% if user.is_engineer_or_admin %}
      <a href="{% url 'accessory_type_list' %}"
         class="nav-link {% if active in 'accessory_type_list accessory_type_create accessory_type_edit accessory_stock_adjust' %}nav-link-active{% endif %}">
        <svg class="size-4 shrink-0" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 22v-9"/><path d="M15.17 2.21a1.67 1.67 0 0 1 1.63 0L21 4.57a1.93 1.93 0 0 1 0 3.36L8.82 14.79a1.655 1.655 0 0 1-1.64 0L3 12.43a1.93 1.93 0 0 1 0-3.36z"/><path d="M20 13v3.87a2.06 2.06 0 0 1-1.11 1.83l-6 3.08a1.93 1.93 0 0 1-1.78 0l-6-3.08A2.06 2.06 0 0 1 4 16.87V13"/></svg>
        Accessories
      </a>
      {% endif %}
```

2. Change the Equipment link's active list from
   `'equipment_list equipment_detail equipment_create equipment_edit equipment_condemn'` to
   `'equipment_list equipment_detail equipment_create equipment_edit equipment_condemn accessory_attach accessory_edit accessory_condemn'`
   (the three fitted-accessory pages are reached from an equipment page, so Equipment stays highlighted there).

In `apps/equipment/admin.py`, extend the models import to `from .models import Accessory, AccessoryType, Department, Equipment, StatusEvent` and append:

```python
@admin.register(AccessoryType)
class AccessoryTypeAdmin(admin.ModelAdmin):
    list_display = ("name", "equipment_name", "stock_qty")
    search_fields = ("name", "equipment_name")
    readonly_fields = ("stock_qty",)

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Accessory)
class AccessoryAdmin(admin.ModelAdmin):
    list_display = ("type", "equipment", "status", "serial_number")
    list_filter = ("status",)
    search_fields = (
        "type__name",
        "serial_number",
        "equipment__serial_number",
        "equipment__name",
    )
    readonly_fields = ("status", "condemned_at")

    def has_delete_permission(self, request, obj=None):
        return False
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_accessory_views.py -v`
Expected: all pass

- [ ] **Step 5: Lint and commit**

```bash
.venv/Scripts/python.exe -m ruff check apps tests
git add templates/base.html apps/equipment/admin.py tests/test_accessory_views.py
git commit -m "feat: accessories nav link and admin registration (#25)"
```

---

### Task 7: Seed data

**Files:**
- Modify: `apps/core/management/commands/seed_demo.py`
- Test: `tests/test_seed_demo.py`

**Interfaces:**
- Consumes: services from Tasks 2–3.
- Produces: 6 seeded accessory types with stock, fitted accessories on every patient monitor / ventilator / defibrillator, exactly one faulty SpO2 probe.

**CRITICAL:** the seeding block must not call `random` — the command sets `random.seed(42)` and any extra draw would shift the entire seeded history that follows. The block below is fully deterministic; place it exactly where stated.

- [ ] **Step 1: Extend the seed test (failing first)**

In `tests/test_seed_demo.py`, extend the equipment import to:

```python
from apps.equipment.models import (
    Accessory,
    AccessoryStatus,
    AccessoryType,
    Equipment,
    EquipmentStatus,
    StatusEvent,
)
```

and add to `test_seed_demo_builds_world` (after the `Complaint.objects.count()` assert):

```python
    assert AccessoryType.objects.count() == 6
    assert not AccessoryType.objects.filter(stock_qty=0).exists()
    assert Accessory.objects.count() >= 10
    assert Accessory.objects.filter(status=AccessoryStatus.FAULTY).count() == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_seed_demo.py::test_seed_demo_builds_world -v`
Expected: FAIL — `assert 0 == 6`

- [ ] **Step 3: Implement seeding**

In `apps/core/management/commands/seed_demo.py`:

1. Change the equipment imports to:

```python
from apps.equipment.models import (
    Accessory,
    AccessoryStatus,
    AccessoryType,
    Department,
    Equipment,
    StatusEvent,
)
from apps.equipment.services import (
    adjust_stock,
    attach_accessory,
    condemn_equipment,
    create_accessory_type,
    update_accessory,
)
```

2. Add a module-level constant after `DELAY_TEXTS`:

```python
ACCESSORY_TYPES = [
    ("ECG cable", "Patient Monitor Mindray uMEC 12", 4),
    ("SpO2 probe", "Patient Monitor Mindray uMEC 12", 3),
    ("IBP probe", "Patient Monitor Mindray uMEC 12", 2),
    ("NIBP cuff", "Patient Monitor Mindray uMEC 12", 5),
    ("Ventilator circuit", "Ventilator Hamilton C2", 5),
    ("ECG cable", "Defibrillator Zoll R Series", 2),
]
```

3. In `handle`, immediately after the device-creation loop (after the `devices.append(...)` loop ends, before the `# ~90 days of complaint -> repair history` comment), insert:

```python
        # accessory catalog, backup stock and fitted units. Deterministic on
        # purpose: consuming `random` here would shift the seeded history.
        type_by_key = {}
        for type_name, equipment_name, qty in ACCESSORY_TYPES:
            accessory_type = create_accessory_type(
                admin, name=type_name, equipment_name=equipment_name
            )
            adjust_stock(accessory_type, admin, qty, "Initial store stock")
            type_by_key[(type_name, equipment_name)] = accessory_type

        faulty_seeded = False
        for device in devices:
            for type_name, equipment_name, _qty in ACCESSORY_TYPES:
                if not equipment_name.startswith(device.name):
                    continue
                accessory = attach_accessory(
                    device,
                    admin,
                    type_by_key[(type_name, equipment_name)],
                    from_stock=False,
                )
                if not faulty_seeded and type_name == "SpO2 probe":
                    update_accessory(
                        accessory,
                        admin,
                        status=AccessoryStatus.FAULTY,
                        notes="Intermittent readings; replacement requested.",
                    )
                    faulty_seeded = True
```

4. Extend the final summary write — after the `f"Seeded {Equipment.objects.count()} devices, "` line, add:

```python
                f"{AccessoryType.objects.count()} accessory types, "
                f"{Accessory.objects.count()} accessories, "
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_seed_demo.py -v`
Expected: both seed tests pass (the existing history/condemn/PPM assertions must still hold — if any pre-existing assertion breaks, the seeding block consumed randomness or is misplaced; fix the placement, do not touch the old assertions)

- [ ] **Step 5: Full suite, lint, commit**

```bash
.venv/Scripts/python.exe -m pytest
.venv/Scripts/python.exe -m ruff check apps tests
git add apps/core/management/commands/seed_demo.py tests/test_seed_demo.py
git commit -m "feat: seed demo accessory inventory (#25)"
```

---

## Final verification (after all tasks)

- [ ] Run the full test suite: `.venv/Scripts/python.exe -m pytest` — all green.
- [ ] Run `.venv/Scripts/python.exe -m ruff check apps tests` — clean.
- [ ] Run `.venv/Scripts/python.exe manage.py makemigrations --check --dry-run` — no missing migrations.
- [ ] Push the branch and open a PR against `main` referencing #25 (Phase 2/3 tracked in #31).
