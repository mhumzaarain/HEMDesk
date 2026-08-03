# Equipment Accessories — Phase 1: Accessory Inventory Core

**Date:** 2026-08-03
**Issue:** #25 (Equipment accessories: track accessories per device)
**Status:** Approved by user

## Background

Medical devices come with accessories that wear out and get replaced
independently of the parent device — for a patient monitor: ECG cable, SpO2
probe, NIBP cuff, IBP cable; for a ventilator: breathing circuits; for a
defibrillator: ECG cable. The hospital also keeps **new backup accessories in
an in-house store**. Today the app records none of this.

The full vision is delivered in three phases; this spec covers Phase 1 only:

1. **Phase 1 (this spec):** accessory inventory core — type catalog, backup
   stock counters, accessories fitted on equipment.
2. **Phase 2 (future issue):** one-click replacement flow (condemn fitted
   unit + attach a backup of the same type) and replacement metrics per
   equipment.
3. **Phase 3 (future issue):** accessory repair/replacement actions inside
   work orders.

## Key decisions (from design discussion)

- **Accessory types are a catalog.** "ECG cable for Patient Monitor SVM 7523"
  and "ECG cable for Nihon Kohden 8001" are different types. Types are
  defined once and reused, so store counts and equipment pages always agree.
- **Backup stock is a counter per type, not individual records.** Spares in
  the store are new and unused; there is nothing to track per unit. Only
  accessories fitted on an equipment are individual records with a condition.
- **The backup store is engineer/admin only.** Hospital staff never see the
  Accessories catalog page, stock counts, or any write buttons. Staff can see
  the list of accessories fitted on an equipment (helps them report faults
  accurately).
- **No hard delete.** A replaced or scrapped accessory is condemned and kept
  forever, matching the app-wide condemn convention.

## Data model (`apps.equipment`)

### AccessoryType (NoDeleteModel)

| Field            | Type / rule                                            |
| ---------------- | ------------------------------------------------------ |
| `name`           | CharField, required — e.g. "ECG cable"                 |
| `equipment_name` | CharField, required — e.g. "Patient Monitor SVM 7523"  |
| `stock_qty`      | PositiveIntegerField, default 0 — new backups in store |
| `notes`          | TextField, blank                                       |
| `created_at` / `updated_at` | auto timestamps                             |

- Unique together: (`name`, `equipment_name`) — no duplicate catalog entries.
- `stock_qty` is only changed through the audited adjust-stock service,
  never edited directly on a form.
- Ordering: `name`, `equipment_name`.

### Accessory (NoDeleteModel)

| Field           | Type / rule                                              |
| --------------- | -------------------------------------------------------- |
| `type`          | FK → AccessoryType, PROTECT, `related_name="units"`      |
| `equipment`     | FK → Equipment, PROTECT, `related_name="accessories"`    |
| `status`        | choices: working / faulty / condemned; default working   |
| `serial_number` | CharField, blank — many accessories are not serialized   |
| `condemned_at`  | DateTimeField, null — stamped on condemn (Phase 2 metric)|
| `notes`         | TextField, blank                                         |
| `created_at` / `updated_at` | auto timestamps                              |

New `AccessoryStatus` TextChoices class alongside `EquipmentStatus`.

## Services (`apps/equipment/services.py`)

All `@transaction.atomic`, engineer/admin gated via
`_require_engineer_or_admin`, audited via `audit.record`. Business-rule
failures raise `AccessoryStateError` (new `DomainError` subclass in
`apps.core.exceptions`); views catch `DomainError` and show
`messages.error`, per app convention.

| Service | Rules | Audit verb |
| --- | --- | --- |
| `create_accessory_type(actor, **fields)` | unique name+equipment_name (form/DB enforced) | `accessory_type.created` |
| `update_accessory_type(type, actor, **fields)` | name/equipment_name/notes only — never stock | `accessory_type.updated` (field diff) |
| `adjust_stock(type, actor, delta, reason)` | delta ≠ 0; resulting qty ≥ 0 else error; row locked with `select_for_update` | `accessory_type.stock_adjusted` (delta, reason, new qty) |
| `attach_accessory(equipment, actor, type, from_stock, serial_number="", notes="")` | refuse condemned equipment; if `from_stock`: stock_qty > 0 required, decrement atomically | `accessory.attached` (+ stock entry when from_stock) |
| `update_accessory(accessory, actor, **fields)` | status working↔faulty, serial, notes; refuse if accessory condemned or equipment condemned | `accessory.updated` (field diff) |
| `condemn_accessory(accessory, actor, reason)` | terminal; sets status=condemned + `condemned_at=now`; refuse if already condemned | `accessory.condemned` (reason) |

## Views, URLs, templates

Class-based views in `apps/equipment/views.py`, following the existing
pattern (read = `LoginRequiredMixin`, write = `RoleRequiredMixin` with
`ENGINEER_ROLES`).

### Accessories catalog page — engineer/admin only (including GET)

- `GET /equipment/accessories/` → `accessory_type_list`: every type with
  name, equipment name, **in store: N**, count of units currently fitted
  (non-condemned). Buttons: Add type, Edit, +/− Adjust stock.
- `GET/POST /equipment/accessories/types/new/` → `accessory_type_create`
- `GET/POST /equipment/accessories/types/<pk>/edit/` → `accessory_type_edit`
- `GET/POST /equipment/accessories/types/<pk>/stock/` → `accessory_stock_adjust`
  (form: delta as add/remove + quantity, reason)

### Equipment detail page — fitted accessories card

- Card listing this equipment's accessories: type name, serial (if any),
  status badge (working=green, faulty=amber, condemned=red), notes.
- Visible to all logged-in users (staff included). No stock numbers shown.
- Engineer/admin extra actions (hidden when the equipment is condemned):
  - **Attach accessory** → `GET/POST /equipment/<pk>/accessories/attach/`
    (`accessory_attach`): choose type, optional serial, notes, and a
    "take from backup stock" checkbox (checked by default; unchecked is for
    cataloging accessories already fitted today).
  - **Edit** → `GET/POST /equipment/accessories/<pk>/edit/` (`accessory_edit`)
    — hidden for condemned accessories.
  - **Condemn…** → `GET/POST /equipment/accessories/<pk>/condemn/`
    (`accessory_condemn`): reason form, mirrors equipment condemn page.

### Navigation

"Accessories" sidebar link (Operations section) wrapped in the existing
engineer/admin template check; new route names added to the sidebar active
highlighting for both the Accessories item and the Equipment item
(accessory_attach/edit/condemn keep Equipment highlighted; catalog routes
highlight Accessories).

### Admin

Register both models: no delete permission; `AccessoryType.stock_qty` and
`Accessory.status`/`condemned_at` read-only (service-managed).

## Error handling

- Rule violations (stock at 0, condemned equipment/accessory, delta below
  zero) → `AccessoryStateError` → red message banner, nothing saved.
- Duplicate type → form validation error on the create form.
- Staff on engineer-only URLs → 403.
- Stock decrement + accessory creation happen in one transaction; stock row
  is locked during adjustment so concurrent edits cannot corrupt the count.

## Seed data (`seed_demo`)

- Types: ECG cable / SpO2 probe / IBP probe / NIBP cuff for "Patient Monitor
  Mindray uMEC 12"; Ventilator circuit for "Ventilator Hamilton C2"; ECG
  cable for "Defibrillator Zoll R Series". Store counts 2–5 each.
- Every seeded patient monitor gets its four accessories fitted; ventilators
  and defibrillators get theirs. One SpO2 probe is seeded faulty (with a
  note) so the amber badge is visible out of the box.
- Seeding must not consume `random` before the existing history loop (keeps
  the demo world reproducible) — use deterministic values or seed at the end.

## Tests (`tests/test_accessories.py` + seed test update)

- **Model:** hard delete raises (instance + queryset); defaults.
- **Services:** staff blocked everywhere (`PermissionDenied`); audit entries
  written per verb; stock cannot go negative; attach `from_stock` decrements
  and is refused at 0; attach refused on condemned equipment; update refused
  on condemned accessory/equipment; condemn stamps `condemned_at`; duplicate
  type rejected.
- **Views:** staff 403 on catalog page and all write URLs; staff sees fitted
  list (no "Attach accessory" button) on equipment detail; engineer completes
  the full flow: create type → adjust stock → attach (stock drops) → edit →
  condemn through the UI.
- **Seed:** `test_seed_demo` asserts types, stock counts, fitted accessories,
  and at least one faulty accessory exist.

## Out of scope (future issues)

- Replacement flow (condemn + attach from stock as one action) and
  "replacements per equipment" metrics — Phase 2.
- Accessory actions inside work orders — Phase 3.
- Linking complaints to a specific accessory.
- Accessory import via CSV/XLSX.
