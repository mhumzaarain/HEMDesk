# Accessory Replacement & Work-Order Integration (Phases 2+3)

**Date:** 2026-08-03
**Issue:** #31 (follow-up to #25 / Phase 1, merged in PR #32)
**Status:** Approved by user

## Background

Phase 1 delivered the accessory inventory core: an `AccessoryType` catalog
with an audited backup-stock counter, and `Accessory` fitted units per
equipment (working / faulty / condemned, no hard deletes). This spec covers
the remaining two phases from issue #31 in one scope, because Phase 3's
core action *is* Phase 2's replace service with a work-order reference:

- **Replacement flow:** swap a faulty accessory for a backup in one action.
- **Metrics:** which equipment and which accessory types consume the most
  replacements; restock visibility.
- **Work-order integration:** accessory work is recorded on the work order
  it happened under.

## Key decisions (from design discussion)

- **Replacement and repair happen ONLY inside an active work order.** There
  is no standalone Replace button on the equipment page. Every swap has a
  WO trail. Phase 1's manual actions (attach, edit, condemn, adjust stock)
  are unchanged and remain available outside work orders.
- **Repaired vs replaced:** *repaired* = same physical unit fixed
  (faulty → working, no stock touched); *replaced* = old unit condemned
  forever, new unit fitted from backup stock (stock −1, refused at 0).
  Metrics count only `replaced` events — replacements consume stock and
  money, repairs don't.
- **Accessories become faulty only by engineer/admin action** (Phase 1 edit
  form, plus a new one-click "Mark faulty" on the WO card). Staff only
  report problems via complaints.
- **Low-stock flag triggers at store count exactly 0** — no per-type
  reorder-level field.
- **Metrics live on the equipment detail page (per-device summary) and a
  dashboard panel (hospital-wide, last 90 days).** No dedicated report page
  in this scope.
- **Complaint→accessory linkage is deferred** to a possible future issue.
- **History is recorded in a new append-only `AccessoryEvent` table**
  (mirroring the `StatusEvent` precedent), the single source for the WO
  display, the equipment summary, and the dashboard ranking.

## Data model (`apps.equipment`)

### AccessoryEvent (AppendOnlyModel)

| Field            | Type / rule                                                       |
| ---------------- | ----------------------------------------------------------------- |
| `kind`           | CharField, choices `AccessoryEventKind`: REPLACED="replaced", REPAIRED="repaired" |
| `work_order`     | FK → `maintenance.WorkOrder`, PROTECT, `related_name="accessory_events"` — always set |
| `equipment`      | FK → Equipment, PROTECT, `related_name="accessory_events"` (denormalized for fast per-device counting) |
| `accessory_type` | FK → AccessoryType, PROTECT, `related_name="events"`               |
| `old_accessory`  | FK → Accessory, PROTECT, `related_name="events_as_old"` — the unit condemned (replace) or fixed (repair) |
| `new_accessory`  | FK → Accessory, PROTECT, null/blank, `related_name="events_as_new"` — the fresh unit (replace only) |
| `actor`          | FK → user, PROTECT, `related_name="accessory_events"`              |
| `remark`         | TextField, blank                                                   |
| `created_at`     | auto_now_add; `ordering = ["-created_at"]`                         |

Append-only: no edits, no deletes (enforced by `AppendOnlyModel`).
Phase 1 models are unchanged.

## Services (`apps/equipment/services.py`)

Both `@transaction.atomic`, `_require_engineer_or_admin`, audited. Business
rules raise `AccessoryStateError`; views catch `DomainError` →
`messages.error`.

### `replace_accessory(accessory, actor, work_order, remark, serial_number="")`

One transaction, in order:
1. Guards: work order is active (`open`/`in_progress`); `accessory.equipment_id == work_order.equipment_id`; accessory not condemned.
2. Condemn the old unit (status=condemned, `condemned_at=now` — same effect as `condemn_accessory`, without requiring a separate call/audit duplication).
3. Lock the type row (`select_for_update`); require `stock_qty >= 1`; decrement; audit `accessory_type.stock_adjusted` (delta −1, reason `Replacement on WO #<id>`).
4. Create the new `Accessory` (same type, same equipment, status working, optional `serial_number`, blank notes).
5. Create `AccessoryEvent(kind=REPLACED, work_order, equipment, accessory_type, old_accessory, new_accessory, actor, remark)`.
6. Audit `accessory.replaced` on the event's old accessory with `{work_order, old, new, remark}`.
Returns the event. Stock-at-zero message: "No backup stock available — restock this type first."

### `repair_accessory(accessory, actor, work_order, remark)`

1. Guards: same WO-active and same-equipment checks; accessory not condemned; accessory status must be FAULTY ("Only faulty accessories can be repaired.").
2. Set status → WORKING (direct save, not via `update_accessory`, so the event and audit stay atomic and single-verbed).
3. Create `AccessoryEvent(kind=REPAIRED, ..., old_accessory=accessory, new_accessory=None)`.
4. Audit `accessory.repaired`.
Returns the event.

### Unchanged Phase 1 services

`attach_accessory`, `update_accessory`, `condemn_accessory`,
`adjust_stock`, type services — all untouched. Manual condemn (without
replacement) remains valid for e.g. decommissioned add-ons.

### Metrics (query helpers in `apps/reports/metrics.py`, alongside the existing PPM metric helpers; the per-equipment summary is computed in `EquipmentDetailView.get_context_data`)

- Per equipment: count + per-type breakdown of `AccessoryEvent` with
  `kind=REPLACED` for that equipment (all-time).
- Dashboard: last-90-days `REPLACED` events grouped by equipment (top 5)
  and by accessory_type (top 5).
- Restock list: `AccessoryType.objects.filter(stock_qty=0)`.

## Views, URLs, templates

All new write views: `RoleRequiredMixin` + `ENGINEER_ROLES` (the WO detail
page is already engineer-only).

### Work-order detail page — Accessories card

- Card lists the WO's equipment's fitted accessories (name, serial, status
  badge). While the WO is active, per row:
  - **Mark faulty** (working units): one-click POST (small inline form),
    calls existing `update_accessory(status=FAULTY)`; row then shows Repair.
  - **Repair** (faulty units): opens remark form → `repair_accessory`.
  - **Replace…** (any non-condemned unit): opens form showing the type's
    current store count, with remark (required) + optional new-unit serial
    → `replace_accessory`.
- Below the list: this WO's `accessory_events`, newest first — e.g.
  "SpO2 probe **replaced** by Bilal — 'sensor dead'". Events remain visible
  on completed/cancelled WOs; the action buttons render only while active.
- URLs (equipment app, global names; `wo_pk` in the path both scopes the
  action to that WO and provides the redirect target back to its page):
  - `POST /equipment/accessories/<pk>/mark-faulty/<wo_pk>/` →
    `accessory_mark_faulty` — no page of its own; an inline form on the WO
    card POSTs here, the view calls the existing
    `update_accessory(status=FAULTY)` (a Phase 1 edit — no event row) and
    redirects back to the WO detail page.
  - `GET/POST /equipment/accessories/<pk>/repair/<wo_pk>/` → `accessory_repair`
  - `GET/POST /equipment/accessories/<pk>/replace/<wo_pk>/` → `accessory_replace`
  Both forms reuse the generic `equipment/accessory_form.html` template
  contract (`form`, `form_title`, `form_subtitle`, `cancel_url` back to the
  WO detail page).

### Equipment detail page

In the existing Accessories card header area, one summary line when the
device has ≥1 REPLACED event: "5 replaced all-time — 3× SpO2 probe,
2× ECG cable". Visible to all logged-in users (counts only, no stock).

### Dashboard (engineer/admin)

Panel "Accessory replacements — last 90 days": top 5 equipment (name,
serial link, count) and top 5 types (name, equipment_name, count). Empty
state: "No replacements recorded."

### Accessories catalog page

"Restock needed" strip above the list, showing zero-stock types with links
to their Adjust stock form. Hidden when no type is at zero.

### Admin

`AccessoryEvent` registered read-only (no add/change/delete), like
`StatusEventAdmin`.

## Error handling

- All guard violations → `AccessoryStateError` → red banner, nothing saved.
- Replace is all-or-nothing: condemn + stock decrement + new unit + event
  in one transaction, stock row locked.
- Staff on any of these URLs → 403.

## Seed data (`seed_demo`)

Extend the existing 90-day history loop (or a follow-up pass after it):
for ~9 of the completed seeded work orders on devices that have fitted
accessories, record accessory events through the real services —
~6 replacements, ~3 repairs — backdating `AccessoryEvent.created_at` (and
the affected accessories' `condemned_at`) with the existing `backdate`
helper to match their WO's timeframe. Choose counts so at least one
accessory type ends at `stock_qty = 0` (restock strip visible) and at
least two devices have ≥2 replacements (dashboard ranking visible).
Determinism rule from Phase 1 still applies: extra `random` draws must not
occur before existing seed blocks; the plan places this after the current
final block or uses deterministic choices.

## Tests

- **Services:** replace happy path asserts all five effects atomically
  (old condemned, new fitted, stock −1, event row, audit verbs); refusal
  matrix: stock 0, completed/cancelled WO, accessory from another
  equipment, condemned accessory, repair on non-faulty unit; staff
  `PermissionDenied`; event immutability (`AppendOnlyModel` save-again
  raises).
- **Views:** WO card renders buttons only while active (Mark faulty on
  working, Repair on faulty, Replace on both); mark-faulty flips and
  redirects back to the WO; replace/repair end-to-end through the UI;
  completed WO shows events without buttons; staff 403 on the three URLs;
  equipment summary line and dashboard panel show correct numbers;
  restock strip appears exactly when a type is at 0.
- **Seed:** event counts by kind, a zero-stock type exists, event
  timestamps spread over the history window.

## Out of scope

- Complaint→accessory linkage (deferred).
- Per-type reorder thresholds (flag is at 0 only).
- Dedicated reports page for accessory metrics.
- Any change to Phase 1 behavior.
