# Phase 2 / M1 — CSV/Excel Equipment Importer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bulk equipment import from CSV/XLSX with dry-run preview, per-row errors, and unrecognized columns captured in `Equipment.extra` JSONB (spec §7; closes #9).

**Architecture:** A pure parsing/validation/import module `apps/equipment/importer.py` (no HTTP concerns), driven by a three-step view flow (upload → preview stored in session → confirm). Import goes through `services.create_equipment` so every row is audit-logged.

**Tech Stack:** Django 5.2, openpyxl (new dep), pytest-django, HTMX-free plain forms (multi-step POST).

## Global Constraints

- Branch: `feature/equipment-importer`, cut fresh from up-to-date `main`. PR closes #9.
- Commit messages: single line (user preference).
- Run everything through uv: `uv run pytest`, `uv run python manage.py ...`, `uv add <pkg>`.
- Ruff: line length 88, rules E/F/I (`uv run ruff check . && uv run ruff format .` before each commit).
- All state changes go through service functions and are audit-logged; views stay thin.
- Page access: engineer + admin only (`RoleRequiredMixin` with `allowed_roles = (Roles.ENGINEER, Roles.ADMIN)`).
- Equipment is never deleted; importer only creates rows (no update mode — out of scope).
- Required import columns: `name`, `serial_number`, `department`. Recognized optional: `manufacturer`, `vendor`, `model_number`, `purchase_date`, `installation_date`, `is_critical_asset`. Everything else → `extra` JSONB.
- Dates are ISO `YYYY-MM-DD`. `is_critical_asset` accepts true/yes/1 (case-insensitive) as True, anything else False.

---

### Task 0: Branch

- [ ] **Step 1: Cut the branch**

```bash
git checkout main
git pull
git checkout -b feature/equipment-importer
```

---

### Task 1: File parsing (`parse_upload`)

**Files:**
- Create: `apps/equipment/importer.py`
- Test: `tests/test_importer.py`
- Modify: `pyproject.toml` (via `uv add openpyxl`)

**Interfaces:**
- Produces: `parse_upload(file_obj, filename) -> list[dict[str, str]]` — one dict per data row, keys are lower-cased/stripped header names, values are stripped strings ("" for empty cells). Raises `ImportFormatError` for unsupported extensions or empty/headerless files.
- Produces: `class ImportFormatError(Exception)`.

- [ ] **Step 1: Add openpyxl**

```bash
uv add "openpyxl~=3.1"
```

- [ ] **Step 2: Write the failing tests**

```python
# tests/test_importer.py
import io

import pytest
from openpyxl import Workbook

from apps.equipment.importer import ImportFormatError, parse_upload


def _csv(text: str) -> io.BytesIO:
    return io.BytesIO(text.encode("utf-8"))


def test_parse_csv_maps_headers_to_rows():
    f = _csv("Name,Serial_Number,department\nVentilator, SN-1 ,ICU\n")
    rows = parse_upload(f, "equip.csv")
    assert rows == [{"name": "Ventilator", "serial_number": "SN-1", "department": "ICU"}]


def test_parse_csv_empty_cells_become_empty_strings():
    f = _csv("name,serial_number,department,vendor\nX,SN-2,ICU,\n")
    assert parse_upload(f, "e.csv")[0]["vendor"] == ""


def test_parse_xlsx():
    wb = Workbook()
    ws = wb.active
    ws.append(["name", "serial_number", "department"])
    ws.append(["Pump", "SN-3", "ICU"])
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    rows = parse_upload(buf, "equip.xlsx")
    assert rows == [{"name": "Pump", "serial_number": "SN-3", "department": "ICU"}]


def test_parse_rejects_unknown_extension():
    with pytest.raises(ImportFormatError):
        parse_upload(_csv("x"), "equip.pdf")


def test_parse_rejects_file_without_rows():
    with pytest.raises(ImportFormatError):
        parse_upload(_csv(""), "equip.csv")
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/test_importer.py -v`
Expected: FAIL — `ModuleNotFoundError`/`ImportError` for `apps.equipment.importer`.

- [ ] **Step 4: Implement**

```python
# apps/equipment/importer.py
"""Equipment bulk import: parse → validate (dry run) → import.

Pure functions; no HTTP concerns. Views feed files in and render the results.
"""

import csv
import io


class ImportFormatError(Exception):
    pass


def parse_upload(file_obj, filename) -> list[dict]:
    """Return one {header: cell} dict per data row. Headers lower-cased and
    stripped; values stringified and stripped ("" for empty cells)."""
    name = filename.lower()
    if name.endswith(".csv"):
        raw = file_obj.read().decode("utf-8-sig")
        table = list(csv.reader(io.StringIO(raw)))
    elif name.endswith(".xlsx"):
        from openpyxl import load_workbook

        ws = load_workbook(file_obj, read_only=True, data_only=True).active
        table = [list(row) for row in ws.iter_rows(values_only=True)]
    else:
        raise ImportFormatError("Only .csv and .xlsx files are supported.")

    table = [row for row in table if any(c not in (None, "") for c in row)]
    if len(table) < 2:
        raise ImportFormatError("File needs a header row and at least one data row.")

    headers = [str(h or "").strip().lower() for h in table[0]]
    rows = []
    for raw_row in table[1:]:
        cells = ["" if c is None else str(c).strip() for c in raw_row]
        cells += [""] * (len(headers) - len(cells))
        rows.append(dict(zip(headers, cells)))
    return rows
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_importer.py -v`
Expected: 5 PASS

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml uv.lock apps/equipment/importer.py tests/test_importer.py
git commit -m "feat: parse CSV/XLSX uploads for equipment import"
```

---

### Task 2: Row validation / dry run (`validate_rows`)

**Files:**
- Modify: `apps/equipment/importer.py`
- Test: `tests/test_importer.py`

**Interfaces:**
- Consumes: `parse_upload` row dicts from Task 1.
- Produces: `validate_rows(rows, create_missing_departments=False) -> list[RowResult]` where `RowResult` is a dataclass with: `line` (int, 2-based like the spreadsheet), `data` (cleaned field dict ready for `Equipment(**data)` minus department), `department_name` (str), `extra` (dict of unrecognized columns), `errors` (list[str]), and property `ok` (`not errors`). Duplicate serials (in-file and in-DB) and unknown departments produce errors; unknown departments are fine when `create_missing_departments=True`.

- [ ] **Step 1: Write the failing tests** (append to `tests/test_importer.py`)

```python
from apps.equipment.importer import validate_rows
from apps.equipment.models import Department, Equipment


def _row(**overrides):
    row = {"name": "Ventilator", "serial_number": "SN-10", "department": "ICU"}
    row.update(overrides)
    return row


def test_validate_ok_row(department):
    results = validate_rows([_row()])
    assert results[0].ok and results[0].line == 2
    assert results[0].data["name"] == "Ventilator"
    assert results[0].department_name == "ICU"


def test_validate_missing_required(department):
    results = validate_rows([_row(serial_number="")])
    assert not results[0].ok
    assert any("serial_number" in e for e in results[0].errors)


def test_validate_duplicate_serial_within_file(department):
    results = validate_rows([_row(), _row(name="Copy")])
    assert results[0].ok and not results[1].ok


def test_validate_duplicate_serial_in_db(equipment):
    results = validate_rows([_row(serial_number=equipment.serial_number)])
    assert any("already exists" in e for e in results[0].errors)


def test_validate_unknown_department_errors_unless_flag(db):
    assert not validate_rows([_row(department="Ghost")])[0].ok
    assert validate_rows([_row(department="Ghost")], create_missing_departments=True)[0].ok


def test_validate_bad_date(department):
    results = validate_rows([_row(purchase_date="31/12/2020")])
    assert any("purchase_date" in e for e in results[0].errors)


def test_validate_good_optionals_and_extra(department):
    row = _row(
        purchase_date="2020-12-31",
        is_critical_asset="Yes",
        ward_notes="3rd floor",
    )
    r = validate_rows([row])[0]
    assert r.ok
    assert str(r.data["purchase_date"]) == "2020-12-31"
    assert r.data["is_critical_asset"] is True
    assert r.extra == {"ward_notes": "3rd floor"}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_importer.py -v`
Expected: new tests FAIL — `validate_rows` not defined.

- [ ] **Step 3: Implement** (append to `apps/equipment/importer.py`)

```python
from dataclasses import dataclass, field
from datetime import date, datetime

from .models import Department, Equipment

REQUIRED_COLUMNS = ("name", "serial_number", "department")
OPTIONAL_COLUMNS = (
    "manufacturer",
    "vendor",
    "model_number",
    "purchase_date",
    "installation_date",
    "is_critical_asset",
)
DATE_COLUMNS = ("purchase_date", "installation_date")
TRUTHY = {"true", "yes", "1"}


@dataclass
class RowResult:
    line: int
    data: dict = field(default_factory=dict)
    department_name: str = ""
    extra: dict = field(default_factory=dict)
    errors: list = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


def _parse_date(value: str) -> date:
    return datetime.strptime(value, "%Y-%m-%d").date()


def validate_rows(rows, create_missing_departments=False) -> list[RowResult]:
    """Dry run: per-row cleaning + errors. Never touches the database beyond
    reads. Line numbers are 2-based to match the spreadsheet."""
    existing_serials = set(
        Equipment.objects.values_list("serial_number", flat=True)
    )
    known_departments = set(Department.objects.values_list("name", flat=True))
    seen_serials: set[str] = set()
    results = []
    for index, row in enumerate(rows):
        result = RowResult(line=index + 2)
        for column in REQUIRED_COLUMNS:
            if not row.get(column, ""):
                result.errors.append(f"missing required column: {column}")
        serial = row.get("serial_number", "")
        if serial:
            if serial in seen_serials:
                result.errors.append(f"duplicate serial_number in file: {serial}")
            elif serial in existing_serials:
                result.errors.append(f"serial_number already exists: {serial}")
            seen_serials.add(serial)
        department = row.get("department", "")
        if (
            department
            and department not in known_departments
            and not create_missing_departments
        ):
            result.errors.append(f"unknown department: {department}")
        result.department_name = department

        for key, value in row.items():
            if key == "department":
                continue  # resolved to a Department FK at import time
            if key in DATE_COLUMNS:
                if value:
                    try:
                        result.data[key] = _parse_date(value)
                    except ValueError:
                        result.errors.append(f"bad {key} (want YYYY-MM-DD): {value}")
            elif key == "is_critical_asset":
                result.data[key] = value.lower() in TRUTHY
            elif key in REQUIRED_COLUMNS or key in OPTIONAL_COLUMNS:
                if value:
                    result.data[key] = value
            elif value:
                result.extra[key] = value
        results.append(result)
    return results
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_importer.py -v`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add apps/equipment/importer.py tests/test_importer.py
git commit -m "feat: dry-run validation for equipment import rows"
```

---

### Task 3: Import execution (`import_rows`)

**Files:**
- Modify: `apps/equipment/importer.py`
- Test: `tests/test_importer.py`

**Interfaces:**
- Consumes: `RowResult` list from Task 2; `apps.equipment.services.create_equipment(actor, **fields)` (existing — audit-logs each creation).
- Produces: `import_rows(actor, results, create_missing_departments=False) -> ImportSummary` — dataclass with `created` (int), `skipped` (list[RowResult] that had errors). Only `ok` rows import; runs in one transaction; departments auto-created when the flag is set. Role check inside (engineer/admin), consistent with the service layer.

- [ ] **Step 1: Write the failing tests** (append to `tests/test_importer.py`)

```python
from django.core.exceptions import PermissionDenied

from apps.core.models import AuditLog
from apps.equipment.importer import import_rows


def test_import_creates_valid_rows_and_skips_errors(engineer, department):
    results = validate_rows([_row(), _row(serial_number="")])
    summary = import_rows(engineer, results)
    assert summary.created == 1
    assert len(summary.skipped) == 1
    assert Equipment.objects.filter(serial_number="SN-10").exists()


def test_import_writes_audit_log(engineer, department):
    import_rows(engineer, validate_rows([_row()]))
    assert AuditLog.objects.filter(verb="equipment.created").count() == 1


def test_import_creates_missing_departments_when_flagged(engineer, db):
    results = validate_rows([_row(department="Ghost")], create_missing_departments=True)
    summary = import_rows(engineer, results, create_missing_departments=True)
    assert summary.created == 1
    assert Department.objects.filter(name="Ghost").exists()


def test_import_extra_columns_land_in_jsonb(engineer, department):
    results = validate_rows([_row(ward_notes="3rd floor")])
    import_rows(engineer, results)
    assert Equipment.objects.get(serial_number="SN-10").extra == {
        "ward_notes": "3rd floor"
    }


def test_import_rejects_staff(staff_user, department):
    with pytest.raises(PermissionDenied):
        import_rows(staff_user, validate_rows([_row()]))
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_importer.py -v`
Expected: new tests FAIL — `import_rows` not defined.

- [ ] **Step 3: Implement** (append to `apps/equipment/importer.py`)

```python
from django.core.exceptions import PermissionDenied
from django.db import transaction


@dataclass
class ImportSummary:
    created: int
    skipped: list


@transaction.atomic
def import_rows(actor, results, create_missing_departments=False) -> ImportSummary:
    from . import services

    if not actor.is_engineer_or_admin:
        raise PermissionDenied("Only engineers or admins may import equipment.")
    created = 0
    skipped = []
    for result in results:
        if not result.ok:
            skipped.append(result)
            continue
        if create_missing_departments:
            department, _ = Department.objects.get_or_create(
                name=result.department_name
            )
        else:
            department = Department.objects.get(name=result.department_name)
        services.create_equipment(
            actor,
            department=department,
            extra=result.extra,
            **result.data,
        )
        created += 1
    return ImportSummary(created=created, skipped=skipped)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_importer.py -v`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add apps/equipment/importer.py tests/test_importer.py
git commit -m "feat: execute equipment import through audited service layer"
```

---

### Task 4: Import views, templates, sample CSV

**Files:**
- Modify: `apps/equipment/views.py`, `apps/equipment/urls.py`, `templates/equipment/list.html` (add an "Import" button linking to `equipment_import` next to the existing "Add equipment" button — engineer/admin block already exists there)
- Create: `templates/equipment/import.html`, `templates/equipment/import_preview.html`, `static/samples/equipment_sample.csv`
- Test: `tests/test_importer_views.py`

**Interfaces:**
- Consumes: `parse_upload`, `validate_rows`, `import_rows`, `ImportFormatError` from Tasks 1–3.
- Produces: URLs `equipment_import` (GET form / POST preview) and `equipment_import_confirm` (POST). Parsed rows are stashed in `request.session["equipment_import"]` (JSON-safe: the raw parsed row dicts + flag) between preview and confirm; confirm re-validates before importing (cheap, and the DB may have changed).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_importer_views.py
import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from apps.equipment.models import Equipment

CSV = "name,serial_number,department,ward_notes\nVentilator,SN-77,ICU,3rd floor\n"


@pytest.fixture
def engineer_client(client, engineer):
    client.force_login(engineer)
    return client


def _upload(client, text=CSV, filename="equip.csv"):
    return client.post(
        reverse("equipment_import"),
        {"file": SimpleUploadedFile(filename, text.encode())},
    )


def test_staff_gets_403(client, staff_user):
    client.force_login(staff_user)
    assert client.get(reverse("equipment_import")).status_code == 403


def test_get_shows_form(engineer_client):
    response = engineer_client.get(reverse("equipment_import"))
    assert response.status_code == 200
    assert b"sample" in response.content.lower()


def test_preview_lists_rows_without_importing(engineer_client, department):
    response = _upload(engineer_client)
    assert response.status_code == 200
    assert b"SN-77" in response.content
    assert Equipment.objects.count() == 0


def test_confirm_imports_valid_rows(engineer_client, department):
    _upload(engineer_client)
    response = engineer_client.post(reverse("equipment_import_confirm"), follow=True)
    assert b"1 imported" in response.content
    assert Equipment.objects.get(serial_number="SN-77").extra == {
        "ward_notes": "3rd floor"
    }


def test_confirm_without_preview_redirects(engineer_client):
    response = engineer_client.post(reverse("equipment_import_confirm"))
    assert response.status_code == 302


def test_bad_file_shows_error(engineer_client):
    response = _upload(engineer_client, text="only-header")
    assert response.status_code == 200
    assert b"header row" in response.content
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_importer_views.py -v`
Expected: FAIL — `NoReverseMatch: equipment_import`.

- [ ] **Step 3: Implement views** (append to `apps/equipment/views.py`)

```python
from . import importer

SESSION_KEY = "equipment_import"


class EquipmentImportView(RoleRequiredMixin, View):
    allowed_roles = ENGINEER_ROLES
    template_name = "equipment/import.html"

    def get(self, request):
        return render(request, self.template_name)

    def post(self, request):
        upload = request.FILES.get("file")
        create_missing = bool(request.POST.get("create_missing_departments"))
        if not upload:
            messages.error(request, "Choose a .csv or .xlsx file first.")
            return render(request, self.template_name)
        try:
            rows = importer.parse_upload(upload, upload.name)
        except importer.ImportFormatError as exc:
            messages.error(request, str(exc))
            return render(request, self.template_name)
        request.session[SESSION_KEY] = {
            "rows": rows,
            "create_missing_departments": create_missing,
        }
        results = importer.validate_rows(
            rows, create_missing_departments=create_missing
        )
        return render(
            request,
            "equipment/import_preview.html",
            {
                "results": results,
                "ok_count": sum(1 for r in results if r.ok),
                "error_count": sum(1 for r in results if not r.ok),
                "create_missing_departments": create_missing,
            },
        )


class EquipmentImportConfirmView(RoleRequiredMixin, View):
    allowed_roles = ENGINEER_ROLES

    def post(self, request):
        stash = request.session.pop(SESSION_KEY, None)
        if not stash:
            messages.error(request, "Nothing to import — upload a file first.")
            return redirect("equipment_import")
        create_missing = stash["create_missing_departments"]
        results = importer.validate_rows(
            stash["rows"], create_missing_departments=create_missing
        )
        summary = importer.import_rows(
            request.user, results, create_missing_departments=create_missing
        )
        messages.success(
            request,
            f"{summary.created} imported, {len(summary.skipped)} skipped.",
        )
        if summary.skipped:
            details = "; ".join(
                f"line {r.line}: {', '.join(r.errors)}" for r in summary.skipped
            )
            messages.warning(request, f"Skipped — {details}")
        return redirect("equipment_list")
```

- [ ] **Step 4: URLs** (add to `apps/equipment/urls.py` urlpatterns)

```python
    path("import/", views.EquipmentImportView.as_view(), name="equipment_import"),
    path(
        "import/confirm/",
        views.EquipmentImportConfirmView.as_view(),
        name="equipment_import_confirm",
    ),
```

- [ ] **Step 5: Templates and sample file**

In `templates/equipment/list.html`, add an "Import" link (`href="{% url 'equipment_import' %}"`) next to the existing "Add equipment" button, inside the same engineer/admin-gated block, styled like its neighbor.

`templates/equipment/import.html` — follow the form-card pattern used by `templates/equipment/form.html` (same wrapper classes; look at that file and copy its card/header structure). Body:

```html
{% extends "base.html" %}
{% block content %}
<div class="max-w-2xl mx-auto">
  <h1 class="text-xl font-semibold mb-4">Import equipment</h1>
  <form method="post" enctype="multipart/form-data" class="card p-6 space-y-4">
    {% csrf_token %}
    <input type="file" name="file" accept=".csv,.xlsx" required>
    <label class="flex items-center gap-2">
      <input type="checkbox" name="create_missing_departments" value="1">
      Create missing departments
    </label>
    <p class="text-sm text-muted">
      Need the format? Download the
      <a href="{% static 'samples/equipment_sample.csv' %}" class="link">sample CSV</a>.
      Required columns: name, serial_number, department.
    </p>
    <button type="submit" class="btn btn-primary">Preview import</button>
  </form>
</div>
{% endblock %}
```

(Add `{% load static %}` after `{% extends %}`. Reuse the project's actual button/card classes from `templates/equipment/form.html` — the class names above are indicative; matching the existing design system is the requirement.)

`templates/equipment/import_preview.html`:

```html
{% extends "base.html" %}
{% block content %}
<div class="max-w-4xl mx-auto">
  <h1 class="text-xl font-semibold mb-2">Import preview</h1>
  <p class="mb-4">{{ ok_count }} row(s) will be created; {{ error_count }} have errors and will be skipped.</p>
  <table class="w-full text-sm">
    <thead><tr><th>Line</th><th>Serial</th><th>Name</th><th>Department</th><th>Extra columns</th><th>Status</th></tr></thead>
    <tbody>
      {% for r in results %}
      <tr>
        <td>{{ r.line }}</td>
        <td>{{ r.data.serial_number }}</td>
        <td>{{ r.data.name }}</td>
        <td>{{ r.department_name }}</td>
        <td>{{ r.extra }}</td>
        <td>
          {% if r.ok %}<span class="badge badge-success">create</span>
          {% else %}<span class="badge badge-danger">{{ r.errors|join:"; " }}</span>{% endif %}
        </td>
      </tr>
      {% endfor %}
    </tbody>
  </table>
  <form method="post" action="{% url 'equipment_import_confirm' %}" class="mt-4 flex gap-2">
    {% csrf_token %}
    <button type="submit" class="btn btn-primary" {% if not ok_count %}disabled{% endif %}>
      Import {{ ok_count }} row(s)
    </button>
    <a href="{% url 'equipment_import' %}" class="btn">Start over</a>
  </form>
</div>
{% endblock %}
```

`static/samples/equipment_sample.csv`:

```csv
name,serial_number,department,manufacturer,vendor,model_number,purchase_date,installation_date,is_critical_asset
Ventilator,SN-0100,ICU,Hamilton,MedServe Ltd,C2,2021-03-15,2021-04-01,yes
Infusion Pump,SN-0101,ICU,B. Braun,,Perfusor Space,2022-01-10,,no
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest tests/test_importer_views.py tests/test_importer.py -v`
Expected: all PASS

- [ ] **Step 7: Full suite + lint, then commit**

Run: `uv run pytest && uv run ruff check . && uv run ruff format .`
Expected: all green.

```bash
git add apps/equipment/views.py apps/equipment/urls.py templates/equipment/import.html templates/equipment/import_preview.html static/samples/equipment_sample.csv templates/equipment/list.html tests/test_importer_views.py
git commit -m "feat: equipment import UI with dry-run preview and confirm"
```

---

### Task 5: PR

- [ ] **Step 1: Push and open the PR**

```bash
git push -u origin feature/equipment-importer
gh pr create --title "CSV/Excel equipment importer" --body "Bulk equipment import with dry-run preview, per-row errors, optional department auto-create, and unrecognized columns captured in Equipment.extra JSONB. Spec: docs/superpowers/specs/2026-07-18-phase2-ai-and-adoption-design.md §7.

Closes #9

🤖 Generated with [Claude Code](https://claude.com/claude-code)"
```
