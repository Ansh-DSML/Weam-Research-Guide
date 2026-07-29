# Weam Research Console — Architecture

Covers everything built across Phase 0 (durable backend), Phase 1 (history panel), and
Phase 2 (knowledge graph). Phase 3 is a plan only — see `PHASE_3_PLAN.md`.

## Why this exists

The original console (`Weam_Research_Console.html`) stored everything in browser
`localStorage`. That data could be — and was — wiped by browser data-clearing settings, disk
cleanup, or a long shutdown. Phases 0–2 replace that with a real backend, add a way to browse
every company on record, and grow a queryable knowledge graph from whatever's been entered —
even half-filled records — as research accumulates.

## Directory layout

```
weam-research-platform/
├── frontend/
│   └── Weam_Research_Console.html      unchanged UI/features; only its storage plumbing
│                                        talks to the backend now instead of localStorage
├── backend/
│   ├── app/
│   │   ├── main.py                     FastAPI app, middleware, serves the frontend at "/"
│   │   ├── config.py                   pydantic-settings (.env-driven)
│   │   ├── db.py                       SQLAlchemy engine/session
│   │   ├── models.py                   Company, Node, Edge
│   │   ├── schemas.py                  Pydantic request/response models
│   │   ├── crud.py                     Company CRUD (pure, no HTTP)
│   │   ├── graph_crud.py               Node/Edge CRUD — idempotent upsert (pure, no HTTP)
│   │   ├── graph_mapper.py             structured fields -> graph specs, no LLM, no cost
│   │   ├── graph_pipeline.py           orchestrator: mapper + extractor -> graph_crud
│   │   ├── extraction/
│   │   │   ├── base.py                 Extractor protocol + result dataclasses
│   │   │   ├── groq_extractor.py       real, hits the Groq API, key rotation
│   │   │   ├── fake_extractor.py       deterministic, offline — used by every test
│   │   │   └── null_extractor.py       used when no Groq keys are configured
│   │   ├── logging_config.py           structured JSON logging, request-id correlation
│   │   ├── middleware.py               request-id/timing + request body size limit
│   │   └── routers/
│   │       ├── health.py               GET /api/health
│   │       ├── companies.py            company CRUD + rename
│   │       └── graph.py                GET /api/companies/{id}/graph
│   ├── alembic/versions/               two migrations: companies table, then graph tables
│   ├── tests/                          16 files, 66 tests as of Phase 2
│   ├── docker-compose.yml
│   ├── requirements.txt
│   └── .env.example
└── logs/                               created automatically at runtime (gitignored)
```

## Data model

**`companies`** — one row per company: `id` (surrogate PK — every endpoint keys off this, never
the raw name, so slashes/unicode/whitespace in a name can't break routing), `name` (unique),
`meta`/`checks`/`notes`/`buckets`/`dm` (JSONB, mirroring the frontend's in-memory shape 1:1),
`last_extracted_text_hash` (sha256 of the concatenated free-text fields — lets the graph
pipeline skip re-running the paid LLM extraction when nothing textual actually changed).

**`nodes`** — `id`, `company_id` (FK, cascade delete), `type` (`Company` | `Person` | `Theme` |
`Location` | `Tool` | `Competitor` | `Other`), `name`, `attrs` (JSONB), `source_refs` (JSONB
array — where this entity came from). Unique on `(company_id, type, name)` **except** the
`Company` node, which is unique on `company_id` alone (see "Entity resolution" below).

**`edges`** — `id`, `company_id` (FK, cascade), `src_id`/`dst_id` (FK to `nodes`, cascade),
`rel_type` (`WORKS_AT` | `HAS_CATEGORY` | `LOCATED_IN` | `TOUCHES_AREA` | `MENTIONS` |
`USES_TOOL` | `COMPETES_WITH`), `attrs`, `source_refs`. Unique on
`(company_id, src_id, dst_id, rel_type)`.

The two `UNIQUE` constraints are what make the graph idempotent: re-running extraction on
unchanged or overlapping data **updates** existing rows (merges `attrs`, appends new
`source_refs`) instead of duplicating. This is the mechanism behind "the graph grows, even
from half information, and never duplicates."

## API surface

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/health` | liveness + DB connectivity (503 if DB unreachable) |
| GET | `/api/companies` | list all companies (full docs — used to boot the frontend's in-memory store and the history panel) |
| POST | `/api/companies` | create (`{name, meta?, checks?, notes?, buckets?, dm?}`) → 201 + id; 409 on duplicate name |
| PUT | `/api/companies/{id}` | full-field replace; 404 if unknown |
| POST | `/api/companies/{id}/rename` | `{new_name}`; 409 on collision, 404 if unknown |
| GET | `/api/companies/{id}/graph` | `{nodes: [...], edges: [...]}`; 404 if unknown |

Create/update/rename all schedule graph extraction as a FastAPI `BackgroundTask` — the HTTP
response returns immediately; extraction happens right after, using its own DB session.

## The graph extraction pipeline (`graph_pipeline.run_graph_extraction`)

On every company create/update/rename:

1. **Ensure the Company node** (`graph_crud.ensure_company_node`) — exactly one per
   `company_id`, keyed on `company_id` alone (not name), so a rename updates it in place
   instead of creating a stale duplicate under the old name.
2. **Always run the structured-field mapper** (`graph_mapper.map_structured_fields`) — zero
   cost, zero network: `meta.category` → Theme node + `HAS_CATEGORY` edge, `meta.country` →
   Location node + `LOCATED_IN` edge, `dm.name`/`dm.title` → Person node + `WORKS_AT` edge,
   each distinct group with a ticked check → Theme node + `TOUCHES_AREA` edge.
3. **Conditionally run the text extractor** — only if the free-text fields (`meta.notes`,
   every value in `notes`, every bucket entry's `text`) have changed since
   `last_extracted_text_hash`. A checkbox toggle or a rename doesn't burn an API call.
4. **Entity resolution**: before creating a text-extracted entity, check whether a node with
   that exact name already exists (typically from the mapper) — if so, reuse its established
   type instead of creating a second node that only differs by type (e.g. the decision-maker's
   name showing up again in free text must resolve to the same `Person` node, not spawn an
   `Other` duplicate).
5. Every extracted entity gets a `MENTIONS` edge back to the Company node, so nothing is an
   orphaned island in the graph.
6. **Finding-tag provenance**: bucket entries carry a FACT/ASSUMPTION/HYPOTHESIS tag (the
   console's finding classification). When an extracted entity's name appears in a tagged
   entry's text, that tag is recorded on the node (and its `MENTIONS` edge) as
   `attrs.finding_tags` — a heuristic substring match, not precise span attribution. Tags union
   across saves rather than overwrite, same idempotency guarantee as the rest of the graph.
   Entities that only ever show up in untagged text (`meta.notes`, `notes`) simply have no
   `finding_tags` key.
7. **Failure isolation**: any exception anywhere in this pipeline is caught and logged — it
   must never look like a failed save to the user, because the save already committed before
   this background step runs.

### Extraction provider (Groq)

`app/extraction/groq_extractor.py` calls Groq's OpenAI-compatible chat completions endpoint
(`https://api.groq.com/openai/v1/chat/completions`, JSON-mode response) with a strict schema
prompt. Configured via `.env`:

- `GROQ_API_KEYS` — comma-separated, works with however many keys you provide. On a
  401/403/429/5xx or a network-level error, the next key is tried. If every key fails,
  extraction is skipped for that save (logged, never raised) — it's additive enrichment on
  top of a save that already succeeded, not a core feature that can block anything.
- `GROQ_MODEL` — documented default in `.env.example`; change it there if it's stale.
- If `GROQ_API_KEYS` is unset, the app uses `NullExtractor` (always empty result) — the graph
  still gets fully populated from structured fields at zero cost; only free-text extraction is
  skipped. **The app must and does work correctly with zero API keys configured.**

Automated tests never call the real Groq API: `FakeExtractor` (deterministic Title-Case-phrase
matching) is dependency-injected in `tests/conftest.py`'s `api_client` fixture, and
`test_extraction_groq.py` exercises the real `GroqExtractor` against a mocked HTTP transport
(`respx`) — key rotation, malformed responses, truncation, and the empty-text short-circuit are
all verified without any network call.

## Logging & tracing

Structured JSON lines (`app/logging_config.py`) to stdout and a rotating file
(`logs/app.log`), with a `request_id` (uuid4, via `contextvar`) attached to every log line
emitted during a request — `middleware.py` assigns it and logs one `request_completed` summary
line per request (method/path/status/duration_ms). **Never logged**: company notes, bucket
text, or extracted entity/relation names — only ids, types, and counts, since all of that can
contain confidential research findings.

## Testing

```
cd backend
venv\Scripts\python -m pytest -v          # ~66 tests, ~25s, no real network/API calls
```

`test_restart_durability.py` is the Phase 0 acceptance gate — it actually stops/starts the real
Postgres container mid-test (discovered by the port it publishes, so it works whether you
started it via `docker compose` or the manual `docker run` fallback) and proves the data
survives. `test_phase2_acceptance.py` is the Phase 2 gate — grows a graph from a half-filled
company across multiple saves and proves nothing duplicates.

## Key design decisions (and why)

- **Postgres-native graph (nodes/edges tables), not a separate graph database.** One database
  to operate, transactionally consistent with the company data it's derived from. Revisit only
  if cross-company multi-hop graph queries start needing real Cypher.
- **Surrogate `id` as the only key mutating endpoints accept**, never the raw name — sidesteps
  an entire class of routing bugs from special characters in company names.
- **No server-side completion-percentage endpoint** (Phase 1): the frontend's `SECTIONS`
  checklist config (~680 lines) is the only source of truth for "how many checks exist";
  porting it to Python would just create a second copy to keep in sync. The history panel
  computes completion % client-side from data already in memory after boot.
- **`connect_timeout=2` on the DB engine**: without it, a dead Postgres hangs a connection
  attempt on the OS-level TCP timeout instead of failing fast, which would make `/api/health`
  useless as a "is the DB actually down" signal.
- **Extraction is a `BackgroundTask` with its own DB session**, not inline in the request: the
  request-scoped session may already be closed by the time a background task runs, and saves
  must stay fast regardless of LLM latency.
