# Plan 004: Wire CastingDirector to the API (POST /api/projects/{id}/analyze)

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**:
> `git diff --stat b1274d9..HEAD -- src/verbatim/api/app.py src/verbatim/casting/director.py src/verbatim/api/models.py`
> If any of those files changed since this plan was written, compare the
> "Current state" excerpts below against the live code before proceeding.
> On a mismatch, treat as a STOP condition.

## Status

- **Priority**: P2
- **Effort**: M
- **Risk**: LOW
- **Depends on**: none
- **Category**: direction
- **Planned at**: commit `b1274d9`, 2026-06-13

## Why this matters

`CastingDirector` (`src/verbatim/casting/director.py`) is fully implemented: it reads
the first N chapters of a project's text from the DB, sends them to the local LLM,
and writes a draft Novel Profile + character list back to the DB. The design spec
(section 3.1) calls this the first step after EPUB parsing: "LLM reads the first ~10
chapters → produces draft Novel Profile → user reviews in Casting Studio UI."

Currently, there is no API endpoint to trigger it. The Casting Studio shows only
characters the user manually types in. Without this route, the central differentiating
feature of Verbatim — auto-discovering the cast from the text — is unreachable from
the UI.

This plan adds `POST /api/projects/{project_id}/analyze`, which runs `CastingDirector`
in a background thread (matching the pipeline's pattern) and returns the resulting
characters and profile updates. The endpoint is synchronous in the simple case
(awaited in the request cycle); if a novel is large the call takes tens of seconds,
which is acceptable for a local single-user tool.

## Current state

### CastingDirector API (read before implementing)

`src/verbatim/casting/director.py` — key public interface:

```python
class CastingDirector:
    def __init__(
        self,
        model_path: "str | Path",
        sm: StateManager,
        project_id: int,
        cfg: "dict[str, Any] | None" = None,
    ): ...

    def __enter__(self) -> "CastingDirector": ...   # loads model
    def __exit__(self, ...): ...                     # unloads model

    def run(self) -> dict[str, Any]:
        """Run analysis. Returns {"profile_updates": {...}, "characters": [...]}."""
```

`run()` returns a dict with at least:
- `"profile_updates"`: dict of fields matching `NovelProfileUpdate` schema
- `"characters"`: list of `{"name": str, "aliases": [...], "emotion_hint": str, "is_pov": bool}`

The constructor's `cfg` dict accepts `"n_gpu_layers": int` and `"n_ctx": int`.

### Existing GPU context-manager pattern (to follow)

The diarizer is the reference pattern (`src/verbatim/llm/director.py`):
```python
with LLMDirector(model_path, sm, project_id=pid, cfg=cfg) as d:
    d.process_chapter(chapter_id)
```

`CastingDirector` uses the same pattern.

### Existing model in `src/verbatim/api/models.py`

The `PipelineStart` model shows the `llm_model_path` field pattern:
```python
class PipelineStart(BaseModel):
    project_id:     int
    llm_model_path: str
    ...
    llm_n_gpu_layers: int = -1
```

### Test pattern (GPU-free, from `tests/test_casting_director.py`)

The existing test monkeypatches `_call_llm` on the director:
```python
def test_run_writes_characters(tmp_path, monkeypatch):
    ...
    def fake_llm(self, prompt: str) -> str:
        return json.dumps(FAKE_RESPONSE)
    monkeypatch.setattr(CastingDirector, "_call_llm", fake_llm)
    with CastingDirector("nonexistent.gguf", sm, project_id=pid) as cd:
        result = cd.run()
    assert result["characters"]
```

### Existing routes in `app.py` (understand structure before adding)

All pipeline routes follow the pattern:
```python
@app.post("/api/pipeline/start")
async def start_pipeline(req: PipelineStart, sm: ..., mgr: ...) -> dict:
    project = sm.get_project_by_id(req.project_id)
    if not project:
        raise HTTPException(404, ...)
    ...
    return {"status": "started", ...}
```

New route goes at the end of the `# -- Projects` block (after `update_novel_profile`).

## Commands you will need

| Purpose    | Command                                                           | Expected on success  |
|------------|-------------------------------------------------------------------|----------------------|
| Install    | `.\.venv\Scripts\pip install -e ".[dev]" -q`                     | exit 0               |
| Tests      | `.\.venv\Scripts\python -m pytest tests/ -v`                     | all pass             |
| New tests  | `.\.venv\Scripts\python -m pytest tests/test_api.py -k analyze`  | new tests pass       |
| Lint       | `.\.venv\Scripts\python -m ruff check src/`                      | exit 0               |
| Typecheck  | `.\.venv\Scripts\python -m mypy src`                             | exit 0               |
| Full suite | `.\.venv\Scripts\python -m pytest -q`                            | 116+ passed          |

## Scope

**In scope**:
- `src/verbatim/api/models.py` (add `CastingAnalyzeRequest`)
- `src/verbatim/api/app.py` (add `POST /api/projects/{id}/analyze` endpoint)
- `tests/test_api.py` (add tests for the new endpoint)

**Out of scope** (do NOT touch):
- `src/verbatim/casting/director.py` — fully working, no changes needed
- `src/verbatim/api/pipeline_manager.py` — the casting analysis is synchronous (awaited in the request), not threaded
- Any UI file

## Git workflow

- Branch: `advisor/004-casting-director-api`
- Commit message: `feat: POST /api/projects/{id}/analyze triggers CastingDirector`
- Do NOT push or open a PR.

## Steps

### Step 1: Add `CastingAnalyzeRequest` to `models.py`

In `src/verbatim/api/models.py`, add after the `NovelProfileUpdate` class:

```python
class CastingAnalyzeRequest(BaseModel):
    llm_model_path:   str
    n_chapters:       int = 10    # how many chapters to sample
    llm_n_gpu_layers: int = -1
```

**Verify**: `.\.venv\Scripts\python -c "from verbatim.api.models import CastingAnalyzeRequest; print('ok')"` → `ok`.

### Step 2: Add the import in `app.py`

`CastingDirector` is not yet imported in `app.py`. At the top of `app.py`, the imports
block ends with:
```python
from verbatim.pipeline.orchestrator import OrchestratorConfig
```

Add after that line:
```python
from verbatim.casting.director import CastingDirector
```

Also add `CastingAnalyzeRequest` to the `from verbatim.api.models import (...)` block.

**Verify**: `.\.venv\Scripts\python -c "from verbatim.api.app import app; print('ok')"` → `ok`.

### Step 3: Add the `POST /api/projects/{project_id}/analyze` endpoint

Add this endpoint in `app.py` inside the `# -- Projects` section, immediately after
the `update_novel_profile` endpoint (around line 193):

```python
@app.post("/api/projects/{project_id}/analyze", status_code=200)
async def analyze_project(
    project_id: int,
    req: CastingAnalyzeRequest,
    sm: StateManager = Depends(get_sm),
) -> dict[str, Any]:
    """Run CastingDirector on the first N chapters and return the draft profile + cast."""
    project = sm.get_project_by_id(project_id)
    if not project:
        raise HTTPException(404, f"Project {project_id} not found.")

    if not req.llm_model_path:
        raise HTTPException(400, "llm_model_path is required.")

    cfg = {"n_gpu_layers": req.llm_n_gpu_layers, "n_chapters": req.n_chapters}

    def _run_analysis() -> dict[str, Any]:
        with CastingDirector(req.llm_model_path, sm, project_id, cfg=cfg) as cd:
            return cd.run()

    try:
        result = await asyncio.to_thread(_run_analysis)
    except FileNotFoundError as exc:
        raise HTTPException(400, str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(503, str(exc)) from exc

    return {
        "project_id": project_id,
        "profile_updates": result.get("profile_updates", {}),
        "characters": result.get("characters", []),
    }
```

Key design decisions:
- `asyncio.to_thread` offloads the blocking GPU call to a thread pool, keeping the
  event loop responsive (matches the `parse_epub` and M4B export patterns in app.py).
- `FileNotFoundError` → 400 (model file missing — user config error).
- `RuntimeError` → 503 (llama_cpp not installed — environment not ready).
- No progress streaming needed — this is a one-shot LLM call, not a multi-chapter pipeline.

**Verify**: `.\.venv\Scripts\python -c "from verbatim.api.app import app; routes = [r.path for r in app.routes]; assert '/api/projects/{project_id}/analyze' in routes, routes; print('ok')"` → `ok`.

### Step 4: Add tests for the new endpoint in `tests/test_api.py`

Add the following tests to `tests/test_api.py`. Import `CastingDirector` at the top
of the file alongside existing imports. The test monkeypatches `CastingDirector._call_llm`
following the same pattern as `tests/test_casting_director.py`.

```python
import json
from verbatim.casting.director import CastingDirector

FAKE_CAST_RESPONSE = {
    "pov_style": "third",
    "thought_convention": "single_quotes",
    "narrator_notes": "LitRPG world",
    "characters": [
        {"name": "Sunny", "aliases": ["Sunless"], "emotion_hint": "stoic", "importance": 10, "is_pov": True},
        {"name": "Nephis", "aliases": [], "emotion_hint": "cold", "importance": 7, "is_pov": False},
    ],
}


def test_analyze_project_not_found(client: TestClient) -> None:
    r = client.post("/api/projects/999/analyze", json={
        "llm_model_path": "models/fake.gguf",
    })
    assert r.status_code == 404


def test_analyze_project_missing_model_path(
    tmp_path: Path, client: TestClient, tmp_sm: StateManager
) -> None:
    pid = _seed_project(tmp_sm, tmp_path)
    r = client.post(f"/api/projects/{pid}/analyze", json={"llm_model_path": ""})
    assert r.status_code == 400


def test_analyze_project_ok(
    tmp_path: Path,
    client: TestClient,
    tmp_sm: StateManager,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pid = _seed_project(tmp_sm, tmp_path)

    def fake_call_llm(self: CastingDirector, prompt: str) -> str:
        return json.dumps(FAKE_CAST_RESPONSE)

    monkeypatch.setattr(CastingDirector, "_call_llm", fake_call_llm)

    r = client.post(f"/api/projects/{pid}/analyze", json={
        "llm_model_path": "models/fake.gguf",
        "n_chapters": 3,
    })
    assert r.status_code == 200
    body = r.json()
    assert "characters" in body
    assert "profile_updates" in body
    names = [c["name"] for c in body["characters"]]
    assert "Sunny" in names
    # Characters should now be in the DB
    chars = tmp_sm.list_characters(pid)
    assert any(c["name"] == "Sunny" for c in chars)
```

Note on the monkeypatch: `CastingDirector.__enter__` will try to load a model if
`_call_llm` is not set and `_LLAMA_AVAILABLE` is True. But `_call_llm` is called
inside `run()`, and monkeypatching it bypasses the LLM call entirely. `__enter__`
still runs — check `src/verbatim/casting/director.py` `__enter__` to see if it
early-returns when `_LLAMA_AVAILABLE` is False (which it will be in the test
environment since llama_cpp is not installed). If `__enter__` raises `RuntimeError`
when llama_cpp is absent, add a second monkeypatch:

```python
monkeypatch.setattr(CastingDirector, "__enter__", lambda self: self)
monkeypatch.setattr(CastingDirector, "__exit__", lambda self, *_: None)
```

**Check the actual `__enter__` code in `src/verbatim/casting/director.py`** and adjust
the monkeypatch accordingly.

**Verify**: `.\.venv\Scripts\python -m pytest tests/test_api.py -k analyze -v` → 3 new tests pass.

### Step 5: Run full suite, lint, typecheck

**Verify**: `.\.venv\Scripts\python -m pytest -q` → 119+ passed.
**Verify**: `.\.venv\Scripts\python -m ruff check src/` → exit 0.
**Verify**: `.\.venv\Scripts\python -m mypy src` → `Success: no issues found`.

### Step 6: Commit

```powershell
git add src/verbatim/api/app.py src/verbatim/api/models.py tests/test_api.py
git commit -m "feat: POST /api/projects/{id}/analyze triggers CastingDirector"
```

## Test plan

New tests in `tests/test_api.py`:
- `test_analyze_project_not_found` — 404 on bad project id
- `test_analyze_project_missing_model_path` — 400 on empty model path
- `test_analyze_project_ok` — monkeypatched LLM returns fake cast; assert response shape and DB state

Pattern follows `tests/test_casting_director.py` for monkeypatching and `tests/test_api.py::test_upsert_character` for the client fixture.

## Done criteria

- [ ] `POST /api/projects/{project_id}/analyze` route exists (`app.routes`)
- [ ] `CastingAnalyzeRequest` model exists in `models.py`
- [ ] `CastingDirector` is imported in `app.py`
- [ ] `asyncio.to_thread` is used for the blocking call
- [ ] 3 new tests in `test_api.py` pass
- [ ] `.\.venv\Scripts\python -m pytest -q` → 119+ passed
- [ ] `.\.venv\Scripts\python -m ruff check src/` exits 0
- [ ] `.\.venv\Scripts\python -m mypy src` exits 0

## STOP conditions

Stop and report if:
- `CastingDirector.run()` does not return `{"profile_updates": ..., "characters": ...}` — inspect the actual return value and adjust the endpoint's response construction.
- `CastingDirector.__enter__` raises when `llama_cpp` is absent and the monkeypatch approach doesn't suppress it — report what `__enter__` actually does and propose an alternative mock strategy.
- `mypy` errors on the `CastingDirector` type (e.g., missing stub) — add `# type: ignore[misc]` at the import line and explain in NOTES.
- The `_run_analysis` closure inside `asyncio.to_thread` can't access `sm` or `project_id` — it's a standard closure, this shouldn't happen, but STOP if it does.

## Maintenance notes

- When the UI gains a "Analyze" button in Casting Studio, it should call this endpoint with the LLM model path from a settings field.
- If analysis becomes long-running enough to need progress streaming, the pattern is to track an in-progress flag on the `PipelineManager` (or a separate `AnalysisManager`) and stream events via SSE — don't try to stream from the sync thread.
