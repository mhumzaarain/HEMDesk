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
| `ai` | LLM integration — service manuals, the assistant, and risk scoring (see [The `ai` app](#the-ai-app) below) |

## Key patterns

- Business rules live in each app's `services.py` module, and those functions re-check the actor's role rather than trusting the caller.
- State changes are logged as append-only events — status events, remarks, accessory events, PPM records — instead of being overwritten in place.
- Role gating is enforced both at the view layer, via `RoleRequiredMixin`, and again inside the service functions.
- Engineer and admin are treated identically everywhere in the app itself; admin's only extra capability is the Django admin site.

## The `ai` app

The `ai` app wires an LLM and an embedding backend into service-manual
search, the engineer-facing assistant, and equipment risk scoring. Every
piece is designed to degrade gracefully — see the invariant at the end of
this section.

**LLM client** (`client.py`) talks OpenAI-compatible chat-completions over
plain `httpx`, no vendor SDK — so any endpoint that speaks the protocol
works: the bundled Ollama container, a self-hosted vLLM server, or a
hospital's own LLM gateway. Selected entirely through env vars: `LLM_BASE_URL`
(default `http://ollama:11434/v1`), `LLM_API_KEY`, `LLM_MODEL` (default
`llama3.2:3b`), `LLM_TIMEOUT_SECONDS` (120), `LLM_INTERACTIVE_TIMEOUT_SECONDS`
(30), and `LLM_EXTRA_BODY` (JSON merged into the request body). Interactive
calls (the assistant's chat) use the short timeout and fail fast with no
retry; batch calls (risk narratives, report generation) use the full timeout
plus one internal retry — Procrastinate's own task retries supply patience
beyond that.

**Embedding client** (`embeddings.py`) mirrors the chat client against
`/v1/embeddings`, selected via `EMBEDDING_BASE_URL` (default
`http://ollama:11434/v1`), `EMBEDDING_API_KEY`, `EMBEDDING_MODEL` (default
`nomic-embed-text`), `EMBEDDING_DIM` (default 768), `EMBEDDING_TIMEOUT_SECONDS`
(30), `EMBEDDING_BATCH_SIZE` (64), and separate query/document prefixes
(`EMBEDDING_QUERY_PREFIX` / `EMBEDDING_DOCUMENT_PREFIX`) that some embedding
models expect prepended to the input text. Every returned vector is
Matryoshka-truncated to exactly `EMBEDDING_DIM` floats and L2-normalized;
a model that natively returns a shorter vector than `EMBEDDING_DIM` is
rejected outright rather than padded. `EMBEDDING_DIM` is coupled to the
database schema (a `pgvector` column) — changing it needs a migration and a
`manage.py reembed_manuals` run.

**Manual pipeline** (`manuals.py`) extracts text per page from an uploaded
PDF, and rejects scanned/image-only PDFs (average characters per page below
a floor) rather than silently indexing near-empty chunks. Text is split into
overlapping sliding-window chunks (1500 chars, 200 overlap), each chunk gets
a Postgres full-text-search vector immediately, then the chunks are embedded
in `EMBEDDING_BATCH_SIZE` batches. If embedding fails, the manual is stamped
with an empty `embedding_model` and a `status_note` explaining it's
keyword-only for now; a chunk's `embedding_model` stamp — not just whether an
embedding exists — is what retrieval checks before trusting the vectors, so a
manual re-embedded under a different model doesn't mix stale and fresh
vectors.

**Hybrid retrieval** (`retrieval.py`, `fusion.py`) answers "which sections of
this manual are relevant" by running two retrievers in parallel — Postgres
FTS and cosine-distance vector search — each returning a top-20 candidate
pool, then fusing them with Reciprocal Rank Fusion (RRF, k=60) down to the
top 5. Vector search is skipped (falling back to FTS alone) whenever the
manual's `embedding_model` stamp is empty or doesn't match the currently
configured `EMBEDDING_MODEL` — the **stale-stamp gate** — or when the
embedding backend is unreachable at query time.

**Deterministic past-fix retrieval** (`retrieval.py: similar_repairs`) finds
prior repairs for the assistant's context: completed work orders scoped to
the same manufacturer and model (optionally narrowed to a fault category).
Up to 5 (`STUFF_LIMIT`) are "stuffed" into the prompt whole. When more than 5
candidates exist, FTS-matched work orders fill the seats first and the
remaining seats are padded with the most recent completed repairs — so the
query's wording influences *which* repairs are picked, never *how many*: the
result is always `min(5, total candidates)`, never fewer just because the
FTS query happened to match nothing.

**Risk scoring and report narratives** keep numbers and words on separate,
independently-verifiable paths. `services.py: compute_score` counts a
device's completed repairs in a fixed 12-month window and multiplies by a
configurable `points_per_repair` — pure SQL, no LLM involved, and reproducible
without one. Only once a device crosses `high_risk_threshold` does
`assess_equipment` ask the LLM for a narrative explanation, built from the
same recent complaints/remarks the score is based on; if the LLM is
unavailable the narrative is simply `None` and the score stands on its own.
Monthly report generation follows the same split — the KPIs and tables come
from SQL, an optional LLM-written summary sits alongside them.

**Graceful degradation is a design invariant, not a fallback bolted on
after the fact**: every LLM- or embedding-dependent feature has a defined,
useful behavior when its backend is unavailable. Manual search falls back to
keyword-only FTS. Risk scores compute and are usable without a narrative.
Monthly reports generate without the LLM summary. The assistant's chat is the
one exception that surfaces the failure directly to the user, by design — it
has nothing meaningful to answer with if the LLM is down.
