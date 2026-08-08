# HEMDesk — Biomedical CMMS

HEMDesk is a hospital medical-equipment management system. It keeps a record of
every device, takes malfunction complaints through to a confirmed repair, keeps
preventive maintenance on schedule, and reports on all of it — with a built-in
AI assistant that answers from your hospital's own manuals and repair history.

## What it does

- **Equipment registry** — a searchable record of every device, registered one
  at a time or bulk-imported from Excel or CSV.
- **Accessories & stock** — accessory types, stock levels, faults, and
  replacements.
- **Complaints & repairs** — staff lodge complaints, engineers work them
  through a queue and work orders, and the reporter confirms the fix.
- **Preventive maintenance** — PPM schedules per device, with a due list.
- **Dashboard & reports** — 30-day KPIs and trends, plus monthly PDF reports.
- **AI assistant** — troubleshooting answers grounded in your service manuals
  and past repairs.

## How the AI works

Upload a service manual and it is indexed in overlapping sections, each
tagged with the pages it covers. When an engineer asks a question about a
device, the assistant searches that model's manual two ways at once — by
keyword and by meaning — so it finds the right section even when the
engineer's words differ from the manual's. It quotes those sections with
page numbers.

It also looks up how your team repaired the same model before, and includes
what worked. See [asking the assistant](ai/assistant.md) and
[service manuals](ai/manuals.md).

## Roles

| Role | What they do |
| --- | --- |
| Staff | Report equipment faults, track their own complaints, browse the registry |
| Biomedical Engineer | Work the complaint queue and repairs, manage equipment, accessories and PPM, read the dashboard and reports |
| Admin | Everything an engineer does, plus the Django admin for user/department management |

## Where to start

- [Getting Started — logging in & roles](getting-started/logging-in.md)
- [Equipment — browse & search the registry](equipment/browse-and-search.md)
- [Complaints & Repairs — lodge a complaint](complaints/lodge.md)
- [Preventive Maintenance — completing due PPMs](ppm/completing.md)
- [Dashboard & Reports — reading the dashboard](dashboard-reports/dashboard.md)
- [AI Assistant — asking the assistant](ai/assistant.md)
- [Administration — managing user accounts](admin/user-accounts.md)
- [Administration — departments & reference data](admin/reference-data.md)
- [Developer — architecture overview](developer/architecture.md)
- [Developer — deployment guide](developer/deployment.md)
