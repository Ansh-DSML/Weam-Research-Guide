# Backend internals

For first-time setup after cloning, see the **root `README.md`**; for the full system design
see the root `ARCHITECTURE.md`. This file only covers backend-specific details once it's
running.

## Tests

```
venv/Scripts/python -m pytest                                       # full suite (~25s, 66 tests)
venv/Scripts/python -m pytest tests/test_restart_durability.py -v   # Phase 0 acceptance gate alone
venv/Scripts/python -m pytest tests/test_phase2_acceptance.py -v    # Phase 2 acceptance gate alone
```

`test_restart_durability.py` is the literal regression test for the original bug: it stops
and restarts the real Postgres container mid-test and asserts the data survives, then does
the same for a backend process restart. It needs Docker and port 8010 free; if a previous
interrupted run left something on that port, it fails fast with the exact command to clear it
rather than hanging (see the comment on `_free_port_from_leftover_process` for why it doesn't
try to auto-remediate that itself — an earlier version did, via a spawned `powershell.exe`
process, and that alone added several minutes of latency per run on this dev machine, almost
certainly from endpoint security software intercepting new process creation).

## Notes on design choices

- **Surrogate `id` as the real key**: every company row has a Postgres serial `id`; all
  mutating endpoints key off it, not the raw name, so names with slashes/unicode/whitespace
  can't break routing.
- **"Last open company" stays client-side only** (`localStorage`), not synced to the server —
  it's a convenience pointer, not research data, so it doesn't need server durability.
- **No server-side completion-percentage endpoint**: the frontend's `SECTIONS` checklist
  config (~680 lines) is the only source of truth for "how many checks exist"; porting it to
  Python would just create a second copy to keep in sync. The history panel computes
  completion % client-side from data the app already has in memory after boot.
- **`connect_timeout=2` on the DB engine** (`app/db.py`): without it, a dead/unreachable
  Postgres can hang a connection attempt on the OS-level TCP timeout instead of failing fast,
  which would make `/api/health` useless as a "is the DB actually down" signal.
- **`ensure_company_node` keys on `company_id` alone**, not `(company_id, type, name)` like
  every other node — otherwise renaming a company would silently create a second, stale
  Company node under the old name instead of renaming the existing one.
- **Entity resolution in `graph_pipeline._apply_text_extraction`**: before creating a
  text-extracted entity, it checks whether a node with that exact name already exists (usually
  from `graph_mapper.py`) and reuses its established type. Otherwise the same real-world entity
  (e.g. the decision-maker's name, once as a structured `Person` node and again as a plain
  text mention) ends up as two nodes that only differ by type.
- **`graph_pipeline.get_default_session_factory` / `get_default_extractor` are FastAPI
  dependencies, not plain function calls** — this is what lets tests override them (via
  `app.dependency_overrides`, exactly like `get_session`) so background graph extraction never
  touches the real dev database or the real Groq API during a test run.
