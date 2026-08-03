# PPM (Planned Preventive Maintenance) Scheduling — Design

**Date:** 2026-08-03
**Issue:** #17
**Branch:** `feature/ppm-scheduling`

## Goal

Add proactive, recurring preventive-maintenance scheduling per device — distinct
from the reactive complaint → work-order pipeline. Engineers define a PPM
schedule on the devices that need one, see what is due or overdue, record each
performed PPM as an immutable log entry, and route a failed PPM straight into
the existing repair workflow.

## Decisions (settled during brainstorming)

| Question | Decision |
|---|---|
| Interval defined per device or per equipment type | **Per device** — no equipment-type model exists; two identical devices may need different intervals |
| What a performed PPM captures | **Simple record** — date, engineers, outcome (passed / passed with remarks / failed), free-text remarks; structured checklists deferred |
| Failed PPM behaviour | **Offer to open a work order** — engineer opts in at completion time; record links to the resulting work order |
| Reminders | **In-app only** — due list, dashboard panel, equipment-detail badge; email deferred to issue #12 |
| Next-due calculation | **From performed date** ("floating"): `next_due = performed_at + interval` |
| Coverage | **Opt-in per device** — devices without a schedule simply don't appear in due lists; a coverage nudge shows how many devices lack one |
| PPM vs WorkOrder modelling | **Separate models** — `WorkOrder` keeps meaning "repair"; no type-conditional logic in existing metrics, constraints, or status transitions |

## Data model (in `apps/maintenance`)

PPM lives in the maintenance app alongside complaints and work orders — no new
Django app.

### `PPMSchedule(NoDeleteModel)` — one per device, mutable, never deleted

| Field | Type | Notes |
|---|---|---|
| `equipment` | OneToOne → `Equipment`, PROTECT | one schedule per device |
| `interval` | CharField choices | `monthly` (1), `quarterly` (3), `biannual` (6), `annual` (12) months |
| `next_due` | DateField | advanced on completion |
| `active` | BooleanField, default True | deactivate instead of delete |
| `created_at` | DateTimeField auto_now_add | |

### `PPMRecord(AppendOnlyModel)` — immutable completion log

| Field | Type | Notes |
|---|---|---|
| `schedule` | FK → `PPMSchedule`, PROTECT, `related_name="records"` | |
| `due_date` | DateField | snapshot of `schedule.next_due` at completion — enables on-time reporting later |
| `performed_at` | DateField | backfillable; never in the future |
| `outcome` | CharField choices | `passed` / `passed_with_remarks` / `failed` |
| `remarks` | TextField, blank | |
| `engineers` | M2M → User | who performed it (mirrors `WorkOrder.participants`) |
| `recorded_by` | FK → User, PROTECT | |
| `work_order` | FK → `WorkOrder`, null, PROTECT | set only when a failed PPM opens a repair; set at creation because the record is append-only |
| `created_at` | DateTimeField auto_now_add | |

### Date math

A small `add_months(date, n)` helper with month-end clamping
(Jan 31 + 1 month → Feb 28). No new dependency.

## Services (`maintenance/services.py` — `transaction.atomic` + audit, engineer/admin required)

### `set_ppm_schedule(equipment, actor, interval, next_due, active=True) -> PPMSchedule`

- Create or update the device's schedule (reactivation goes through the same call).
- Rejects condemned equipment.
- Audit verb: `ppm.schedule_set` (changes: interval, next_due, active).

### `complete_ppm(schedule, actor, outcome, performed_at, engineers=(), remarks="", open_wo=False) -> PPMRecord`

- Validates: schedule active, equipment not condemned, `performed_at` not in the
  future, outcome valid, **no active work order on the device** — if one exists,
  raises `WorkOrderStateError` naming it ("This equipment is under repair
  (WO #12) — complete or cancel it first"). The schedule stays due; the PPM is
  recorded after the repair closes. This also makes the
  failed-PPM-while-a-WO-already-exists edge case unreachable.
- Creates the `PPMRecord`, snapshotting `due_date = schedule.next_due`.
- Advances `schedule.next_due = add_months(performed_at, interval_months)`.
- `open_wo=True` requires `outcome=failed` (otherwise `ValueError`): calls the existing
  `open_work_order(equipment, actor)` in the same transaction and links the
  record before saving. (The no-active-work-order validation above guarantees
  this call cannot hit the one-active-work-order constraint.)
- Adds `actor` to `engineers` implicitly (like `start_repair` does with participants).
- Audit verb: `ppm.completed` (changes: outcome, performed_at, work_order pk or null).

## Views, URLs, templates (existing role-gating patterns)

| URL | View | Access |
|---|---|---|
| `/ppm/` | PPM due list: **Overdue** (`next_due < today`) and **Due soon** (next 30 days) sections; department filter; active schedules on non-condemned equipment only; "N devices have no PPM schedule" coverage nudge | engineer/admin |
| `/equipment/<pk>/ppm/schedule` | Set/edit schedule form (interval, next_due, active) | engineer/admin |
| `/ppm/<schedule_pk>/complete` | Record-a-PPM form (performed_at, outcome, engineers, remarks, conditional "Open a work order" checkbox shown via Alpine.js when outcome = failed) | engineer/admin |

- **Equipment detail**: PPM panel beside repair history — interval, next due
  with overdue / due-soon / OK badge, record history (outcome + linked WO), and
  Set schedule / Record PPM buttons. Staff see the panel read-only, no buttons.
- **Home**: one additional engineer card linking to `/ppm/`.
- Templates use the design-system classes (`card`, `btn btn-primary`, `badge`, …).

## Dashboard

Two metric functions in `reports/metrics.py` (pure SQL, matching existing
style):

- `ppm_due_counts()` → overdue count + due-in-next-30-days count.
- `ppm_overdue_by_department()` → overdue schedules grouped by department.

Rendered as a "PPM compliance" panel on the existing engineer dashboard.
**No Procrastinate task** — due/overdue is derived live from `next_due` vs
today; nothing to precompute. When issue #12 lands SMTP, an email digest reuses
the same querysets.

## Error handling

- Service validation errors (`WorkOrderStateError`, `ValueError`) surface as
  form/messages errors in views — same pattern as work-order views.
- `PPMRecord` immutability is enforced by `AppendOnlyModel.save()`; schedules
  and records are protected from deletion by `NoDeleteModel`.
- Condemned equipment: schedules are excluded from due lists by filtering on
  equipment status (no coupling into the condemn service).

## Testing

- `tests/test_ppm_services.py` — schedule create / update / reactivate;
  condemned rejection; completion advances next-due including month-end
  clamping; future `performed_at` rejected; failed + `open_wo` creates a linked
  work order atomically; active-work-order conflict leaves nothing written;
  append-only enforcement; audit entries recorded.
- `tests/test_ppm_views.py` — role gating (staff blocked from actions, allowed
  read-only detail panel); due-list buckets and department filter; completion
  flow through the view including the open-work-order checkbox; equipment
  detail panel rendering.
- `seed_demo` gains a handful of schedules (some overdue, some due soon) and
  past records so the demo shows the feature.

## Out of scope (deliberate)

- Structured checklist templates and per-item results.
- Email/SMS reminders (issue #12).
- Equipment types / type-level default intervals.
- PPM calendar view.
