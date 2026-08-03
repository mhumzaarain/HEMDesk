# Accessory Type Equipment-Name Suggestions Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The accessory-type form's "Equipment name" field suggests distinct name+manufacturer+model combinations from the registered equipment inventory (browser-native datalist), while still accepting free text — per `docs/superpowers/specs/2026-08-03-accessory-type-suggestions-design.md`.

**Architecture:** A tiny helper in `apps/equipment/views.py` builds the distinct combo strings; the type create/edit views pass them as `equipment_name_options`; the shared generic form template renders a `<datalist>` only when that key is present; the form widget points at the datalist via its `list` attribute. No model changes, no migration.

**Tech Stack:** Django 5.2, pytest-django, ruff.

## Global Constraints

- Branch: `feature/accessory-replacement` (commit directly on it).
- Python: `.venv/Scripts/python.exe` from the repo root for pytest/ruff.
- Lint: `.venv/Scripts/python.exe -m ruff check apps tests` must pass (88 cols, double quotes, isort).
- Suggestion string format: `name manufacturer model_number` joined with single spaces, blank parts skipped (matches the seed data's `equipment_name` values, e.g. "Patient Monitor Mindray uMEC 12").
- Free text NOT in the suggestions must remain valid input.
- Datalist id exactly `equipment-name-options`.
- Commit message: single line `feat: suggest equipment names on accessory type form (#31)`.

---

### Task 1: Datalist suggestions on the accessory-type form

**Files:**
- Modify: `apps/equipment/forms.py` (AccessoryTypeForm.__init__)
- Modify: `apps/equipment/views.py` (helper + AccessoryTypeCreateView/AccessoryTypeEditView contexts)
- Modify: `templates/equipment/accessory_form.html` (datalist block)
- Test: `tests/test_accessory_views.py` (append)

**Interfaces:**
- Consumes: `Equipment` model (fields `name`, `manufacturer`, `model_number`); existing `AccessoryTypeForm`, `AccessoryTypeCreateView` (inline context dicts in `get` and invalid-`post`), `AccessoryTypeEditView` (`_render` helper); generic template context contract (`form`, `form_title`, `form_subtitle`, `cancel_url`).
- Produces: module-level `_equipment_name_options() -> list[str]` in `apps/equipment/views.py`; optional context key `equipment_name_options` consumed by `templates/equipment/accessory_form.html`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_accessory_views.py`:

```python
def test_type_form_suggests_registered_equipment(client, engineer, equipment):
    client.force_login(engineer)
    content = client.get(reverse("accessory_type_create")).content.decode()
    assert 'list="equipment-name-options"' in content
    assert '<datalist id="equipment-name-options">' in content
    assert "Ventilator Hamilton C2" in content


def test_type_accepts_unlisted_equipment_name(client, engineer):
    client.force_login(engineer)
    response = client.post(
        reverse("accessory_type_create"),
        {
            "name": "ECG cable",
            "equipment_name": "Brand New Device X1",
            "notes": "",
        },
    )
    assert response.status_code == 302
    assert AccessoryType.objects.filter(
        equipment_name="Brand New Device X1"
    ).exists()
```

(The `equipment` fixture is a Ventilator / Hamilton / C2 — hence the expected suggestion string "Ventilator Hamilton C2". `AccessoryType` is already imported at the top of this test file.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_accessory_views.py::test_type_form_suggests_registered_equipment tests/test_accessory_views.py::test_type_accepts_unlisted_equipment_name -v`
Expected: `test_type_form_suggests_registered_equipment` FAILS on the missing `list=` attribute; `test_type_accepts_unlisted_equipment_name` may already pass (free text is the current behavior) — that is fine, it locks the behavior in.

- [ ] **Step 3: Implement**

1. In `apps/equipment/forms.py`, at the end of `AccessoryTypeForm.__init__` (after the `for field ...: setdefault("class", INPUT)` loop), add:

```python
        self.fields["equipment_name"].widget.attrs.setdefault(
            "list", "equipment-name-options"
        )
```

2. In `apps/equipment/views.py`, add a module-level helper directly above `class AccessoryTypeListView`:

```python
def _equipment_name_options():
    combos = (
        Equipment.objects.values_list("name", "manufacturer", "model_number")
        .distinct()
        .order_by("name", "manufacturer", "model_number")
    )
    return [" ".join(part for part in combo if part) for combo in combos]
```

3. Add `"equipment_name_options": _equipment_name_options(),` to the context dict of every render of the type form — three places:
   - `AccessoryTypeCreateView.get` (inline dict),
   - `AccessoryTypeCreateView.post` invalid-form branch (inline dict),
   - `AccessoryTypeEditView._render` (its dict).
   Do NOT add it to `AccessoryStockAdjustView` or any other view.

4. In `templates/equipment/accessory_form.html`, directly after the `{% for field in form %}...{% endfor %}` loop (before the buttons `<div>`), add:

```html
    {% if equipment_name_options %}
    <datalist id="equipment-name-options">
      {% for option in equipment_name_options %}<option value="{{ option }}"></option>{% endfor %}
    </datalist>
    {% endif %}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_accessory_views.py -v`
Expected: all pass (the whole file — the two new tests plus no regression in the Phase 1 view tests and the WO-page tests that share the generic template)

- [ ] **Step 5: Lint and commit**

```bash
.venv/Scripts/python.exe -m ruff check apps tests
git add apps/equipment/forms.py apps/equipment/views.py templates/equipment/accessory_form.html tests/test_accessory_views.py
git commit -m "feat: suggest equipment names on accessory type form (#31)"
```

---

## Final verification

- [ ] `.venv/Scripts/python.exe -m pytest tests/test_accessory_views.py tests/test_accessory_workorder_views.py -v` — all green (both consumers of the shared template).
- [ ] `.venv/Scripts/python.exe -m ruff check apps tests` — clean.
