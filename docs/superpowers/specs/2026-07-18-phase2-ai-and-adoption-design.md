# Phase 2 — AI + Adoption: Design Specification

**Date:** 2026-07-18
**Status:** Approved design, pre-implementation
**Parent spec:** `2026-07-17-biomedical-cmms-design.md` (all Phase 1 rules remain in force)

Phase 2 adds the AI layer and adoption features to the working Phase 1 CMMS:
a configurable LLM backend, the monthly PDF management report, weekly risk
scoring, service-manual-grounded engineer assistant chat, and the CSV/Excel
equipment importer.

**Unchanged design rule:** numbers come from SQL, words come from the LLM.
The LLM never computes metrics and never changes workflow state; every LLM
output lands in a nullable field the UI treats as optional enrichment. Core
workflow never blocks on the LLM.

---

## 1. Scope

| # | Feature | Milestone |
|---|---|---|
| 1 | CSV/Excel equipment importer | M1 |
| 2 | Configurable LLM backend (`ai` app) | M2 |
| 3 | Monthly management report (SQL + narrative → PDF) | M2 |
| 4 | Risk scoring (admin-configurable weights) + narrative | M2 |
| 5 | Service manual upload + extraction + FTS chunks | M3 |
| 6 | Engineer assistant chat (work order + equipment pages) | M3 |

**Structure decision:** one spec (this document), one implementation plan
sequenced as three independently mergeable milestones. The app is fully
functional after each milestone lands.

Changes vs. the parent spec's Phase 2 sketch:
- Device-history chat pulled forward from Phase 3 and merged into the
  engineer assistant (one chat feature, not two).
- Service manuals + troubleshooting grounding are new (not in parent spec).
- LLM backend generalized from "local Ollama only" to any OpenAI-compatible
  endpoint chosen by the hospital.
- Risk scoring weights become admin-editable instead of hard-coded.

## 2. LLM backend (`apps/ai/`)

One client class speaking the OpenAI-compatible chat-completions protocol via
`httpx` (no vendor SDK; only `/chat/completions` is used). Works unchanged
against Ollama (`/v1`), vLLM, or a hospital's own OpenAI-compatible gateway.

Environment variables:

| Variable | Default | Meaning |
|---|---|---|
| `LLM_BASE_URL` | `http://ollama:11434/v1` | Any OpenAI-compatible endpoint |
| `LLM_API_KEY` | empty | Sent as `Authorization: Bearer` only if non-empty |
| `LLM_MODEL` | `llama3.2:3b` | Model name as the backend knows it |
| `LLM_TIMEOUT_SECONDS` | `120` | Per-request timeout |
| `LLM_EXTRA_BODY` | `{}` | JSON merged into every request body, for backend quirks (e.g. `{"chat_template_kwargs": {"enable_thinking": false}}` for Qwen-style models on vLLM) |

- docker-compose gains an `ollama` service with a named model volume so the
  clone-and-run demo works out of the box; it is the default backend, not a
  dependency. First-start model pull is documented in the README.
- Every LLM call runs inside a Procrastinate task with retry/backoff. On
  persistent failure the dependent feature shows "not available" and nothing
  else is affected.
- Two retry budgets (pattern borrowed from openradx/RADIS): **batch** tasks
  (monthly report, risk scoring) retry patiently with exponential backoff;
  the **interactive** assistant-chat task fails fast (short timeout, one
  retry) so an engineer sees "assistant not available — try again" instead
  of a minutes-long thinking bubble.
- The `ai` app isolates all LLM-dependent code; the system is fully
  functional with the backend down or unconfigured.

## 3. Monthly management report (`apps/reports/`)

**Model — `reports.MonthlyReport`:** `month` (date, first of month, unique),
`status` (`pending` / `generating` / `ready` / `failed`), `metrics` JSONB
(SQL-computed aggregates), `narrative` (LLM text, nullable), `pdf` (file),
`generated_at`, `requested_by` (nullable — null for scheduled runs).

**Task — `generate_monthly_report(month)`:**
1. Compute the month's aggregates in SQL, reusing `reports/metrics.py`:
   critical-asset downtime (with month-boundary proration), complaints per
   department, most-complained devices, fault-category counts, repairs
   completed, currently open work orders, delay-annotated repairs with
   reasons, per-engineer activity.
2. LLM writes an executive-summary narrative from those numbers.
3. WeasyPrint renders metrics tables + narrative to a PDF stored on disk.

If the LLM is unavailable, the report still generates with tables only and a
visible "narrative unavailable" note — numbers never wait for words.

**Triggers:** periodic on the 1st of each month (for the previous month), and
a "Generate now" button (regenerates and replaces that month's report).
**UI:** a Reports page (engineer + admin) listing months with status and PDF
download links.

## 4. Risk scoring

**Config — `ai.RiskScoringConfig`:** singleton row, edited only in Django
admin (admin role), seeded with defaults by migration. Exactly two numbers:

| Field | Default | Meaning |
|---|---|---|
| `points_per_repair` | 1 | Points earned per completed work order |
| `high_risk_threshold` | 3 | Score at or above this marks the device high-risk |

Score = completed work orders in the window × `points_per_repair`. The
counting window is a fixed design constant of the last 12 months (rolling) —
not admin-configurable, kept out of the config to preserve the two-number
simplicity. Pure SQL arithmetic; no caps, no clamping, no recency or
repeat-fault terms. The LLM never influences the number.

**Task — `compute_risk_scores`:** weekly periodic over all non-condemned
equipment. Per device: count repairs and compute the score in SQL → insert
`ai.RiskAssessment` row (`equipment`, `score`, `factors` JSONB — repair
count, window, and the config values used, so historical scores stay
explainable after changes — `narrative` nullable, `generated_at`). New row
per run; history preserved. Config changes take effect on the next run;
admins can trigger an immediate recompute via an admin action.

**Narratives only for high-risk devices:** the LLM writes an explanatory
paragraph (which may quote actual complaint/remark snippets) only for
devices at or above `high_risk_threshold`; all other devices get
`narrative = null`. This bounds LLM load on large fleets and matches what
the badge highlights.

**UI (engineer + admin):** on the equipment detail page, the latest score
with a **"High risk" badge when score ≥ threshold**, plus the narrative and
repair count; on the dashboard, a "high-risk devices" widget listing devices
at or above the threshold, highest score first (top 10).

## 5. Service manuals

**Models:**
- `ai.ServiceManual`: `manufacturer`, `model_number`, `title`, `file` (PDF),
  `uploaded_by`, `uploaded_at`, `status` (`processing` / `ready` / `failed`),
  `status_note`, `page_count`. Unique per (`manufacturer`, `model_number`);
  one manual covers every equipment unit sharing that pair. Re-upload
  replaces the manual and its chunks.
- `ai.ManualChunk`: `manual` FK, `text` (~1,500 chars, ~200-char overlap
  between consecutive chunks),
  `page_start`, `page_end`, plus a Postgres full-text `SearchVectorField`
  with a GIN index.

**Flow:** engineer/admin uploads via a Manuals page (list + upload form) →
Procrastinate task extracts text with `pypdf`, chunks it, builds search
vectors → `ready`. If extraction yields almost no text (scanned/image-only
PDF), the manual is marked `failed` with note "scanned/image-only PDF — text
extraction unsupported" (OCR is out of scope). Equipment detail links to the
matching manual when one exists.

**Retrieval decision:** Postgres FTS (`websearch_to_tsquery`), not
embeddings. The manual is always pre-filtered to the device's model, so
retrieval only finds sections *within* one known manual — the case where
keyword search over error-message-structured text performs well. The chunk
store is designed so an embedding column (pgvector) can be added later
without redesign if retrieval quality disappoints.

## 6. Engineer assistant chat

**Access:** engineer + admin only. Staff never see it.

**Placement:** an "Assistant" panel, collapsed by default, on (a) the work
order detail page below complaints/remarks, and (b) the equipment detail
page. Same widget; always scoped to a specific device — the device is never
inferred from message text. This feature also covers the parent spec's
Phase 3 "device-history chat".

**Model — `ai.AssistantMessage`:** `equipment` FK, `work_order` FK
(nullable), `user` FK, `role` (`user` / `assistant`), `content`,
`created_at`. History is per device and visible to all engineers (a
colleague's earlier session is useful context). Supersedes the parent spec's
`DeviceChatMessage`.

**Flow (HTMX polling):** engineer sends message → saved as `role=user` →
`answer_assistant_chat` task assembles the prompt and calls the LLM → panel
polls a partial every ~2 s showing a "thinking…" bubble until the
`role=assistant` row lands. On persistent LLM failure the bubble becomes
"assistant not available".

**Prompt assembly** (system prompt frames an advisory biomedical assistant
and instructs it to say when the manual does not cover something):
1. **Device card** — name, manufacturer, model, status, department.
2. **Work-order context** (when opened from a WO) — attached complaint texts
   and remarks, so symptoms are known before the engineer types.
3. **Manual sections** — top 5 `ManualChunk` FTS matches for the engineer's
   message + complaint text, restricted to this model's manual, cited with
   page numbers ("Manual p. 142: …").
4. **Past similar repairs** — top 3 completed work orders on the same
   manufacturer + model whose complaint/remark text matches the symptoms
   (FTS), with fault category and closing remarks.
5. Recent chat turns for this device (bounded window).

Every assistant answer is displayed with a fixed, app-rendered (not
LLM-generated) disclaimer: *"Advisory only — verify against the service
manual before acting."* The assistant has no tools and cannot change any
workflow state.

## 7. CSV/Excel importer (`apps/equipment/`)

**Access:** engineer + admin, from the equipment registry page.

**Flow:**
1. Upload `.csv` or `.xlsx` (openpyxl).
2. **Dry-run preview:** parsed rows in a table, each marked `create` or
   `error` (duplicate serial within the file or against the DB, missing
   required field, unknown department). Recognized columns map to Equipment
   fields; unrecognized columns are shown as headed to `extra` JSONB.
   Checkbox: "create missing departments" (off by default).
3. **Confirm:** imports valid rows only; result banner "N imported, M
   skipped" with the skipped rows and reasons listed. Errors never block the
   valid rows.

Required columns: `name`, `serial_number`, `department`. Recognized optional
columns: `manufacturer`, `vendor`, `model_number`, `purchase_date`,
`installation_date`, `is_critical_asset`. All imports are audit-logged; a
downloadable sample CSV documents the expected headers. No AI involvement.

## 8. Milestones

| Milestone | Contents | Branch (from `main`) | Closes issues | Merge gate |
|---|---|---|---|---|
| **M1 — Importer** | §7 | `feature/equipment-importer` | #9 | Import flow works end-to-end; tests green |
| **M2 — AI foundation** | §2 + §3 + §4, ollama compose service | `feature/ai-foundation` | #7, #8 | Report PDF and risk scores generate with real backend; graceful degradation proven with backend down |
| **M3 — Manuals + assistant** | §5 + §6 | `feature/manuals-assistant` | #10, #21 | Upload → chunks → grounded chat answers with page citations |

Each milestone is an independently mergeable PR on a fresh branch cut from
the then-current `main`; the app works after each. PR descriptions use
`Closes #N` so merging closes the linked issues. Design-update comments were
posted on #7 (backend generalization, two-number scoring) and #10 (pulled
into Phase 2, expanded into the assistant).

## 9. Testing

pytest + pytest-django; all LLM tests use a faked client (no model in CI).
Priority order:
1. Importer validation rules (duplicates, missing fields, department
   handling, `extra` JSONB overflow, valid-rows-import-despite-errors).
2. Risk score arithmetic against a seeded config (12-month window edges,
   points-per-repair multiplication, threshold boundary at exactly-equal
   score) and config-change behavior (next run uses new values).
3. Report generation with LLM up vs. down (narrative present vs. "narrative
   unavailable"; metrics identical either way).
4. Manual pipeline: extraction, chunking, scanned-PDF failure path, FTS
   retrieval returns the planted chunk.
5. Assistant: role access (staff blocked), prompt assembly includes the four
   context blocks, HTMX polling states, LLM-failure state.
6. View access control for every new page per role.

## 10. Out of scope (unchanged or deferred)

- Embeddings / pgvector / RAG beyond FTS (upgrade path reserved, §5).
- OCR for scanned manuals.
- Fault-category suggestion on the completion form (discussed, not selected).
- Live/streaming chat, websockets — HTMX polling only.
- SMTP notifications, nightly backup task, demo-mode refinements — Phase 3.
- LLM triage, duplicate detection, MTTR, SLA — permanently rejected (parent
  spec §9).
