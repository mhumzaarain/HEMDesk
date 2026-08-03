# Architecture overview

HEMDesk is a server-rendered Django 5.2 application. Pages are rendered by Django views and templates; HTMX handles partial updates (the complaint queue, dashboard cards, and similar live bits) without a client-side framework. Alpine.js provides small interactive sprinkles in templates, and Tailwind CSS handles styling. Chart.js renders the charts on the dashboard.

PostgreSQL is the database. Background work — monthly report generation and other scheduled tasks — runs through Procrastinate, a Postgres-backed task queue, so there's no separate broker to run. Monthly report PDFs are rendered with WeasyPrint.

## Apps

| App | Responsibility |
| --- | --- |
| `accounts` | Custom `User` model with `role` and `employee_id`, plus the role-based mixins views use for access control |
| `core` | Shared building blocks (append-only/no-delete model bases, audit log) and the `seed_demo` management command |
| `equipment` | The equipment registry, status transitions, accessories, and the Excel/CSV importer |
| `maintenance` | Complaints, work orders, and preventive maintenance (PPM) |
| `reports` | The dashboard and monthly PDF reports |
| `ai` | LLM integration — feature in progress, not documented yet |

## Key patterns

- Business rules live in each app's `services.py` module, and those functions re-check the actor's role rather than trusting the caller.
- State changes are logged as append-only events — status events, remarks, accessory events, PPM records — instead of being overwritten in place.
- Role gating is enforced both at the view layer, via `RoleRequiredMixin`, and again inside the service functions.
- Engineer and admin are treated identically everywhere in the app itself; admin's only extra capability is the Django admin site.
