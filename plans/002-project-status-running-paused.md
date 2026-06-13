# Plan 002: Fix project status to reflect active pipeline state (running/paused)

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**: `git diff --stat b1274d9..HEAD -- src/verbatim/api/app.py`
> If that file changed since this plan was written, compare the "Current state"
> excerpts below against the live code before proceeding. On a mismatch, treat
> as a STOP condition.

## Status

- **Priority**: P1
- **Effort**: S
- **Risk**: LOW
- **Depends on**: none
- **Category**: bug
- **Planned at**: commit `b1274d9`, 2026-06-13

## Why this matters

The TypeScript UI defines `ProjectStatus = 'idle' | 'running' | 'paused' | 'complete' | 'error'`
and renders status dots accordingly (running = animated pulse, paused = amber dot).
The backend helper `_project_status()` only looks at chapter counts — it has no knowledge
of whether the pipeline manager is actively running. During a live pipeline run, every
project is reported as `"idle"` to the Library page. The running/paused dots never show.

The fix: inject `PipelineManager` into the project GET/LIST endpoints and consult its
state when the project matches the actively-running one.

## Current state

**File**: `src/verbatim/api/app.py`

`_project_status` (lines 75–83):
```python
def _project_status(progress: dict[str, Any]) -> str:
    """Compute a summary project status from chapter progress counts."""
    if progress["total"] == 0:
        return "idle"
    if progress["error"] > 0:
        return "error"
    if progress["complete"] == progress["total"]:
        return "complete"
    return "idle"
```

`get_project` endpoint (lines 165–175) — calls `_project_status(progress)` with no manager:
```python
@app.get("/api/projects/{project_id}")
async def get_project(
    project_id: int,
    sm: StateManager = Depends(get_sm),
) -> dict[str, Any]:
    project = sm.get_project_by_id(project_id)
    if not project:
        raise HTTPException(404, f"Project {project_id} not found.")
    progress = sm.get_progress(project_id)
    project["status"] = _project_status(progress)
    return {"project": project}
```

`list_projects` endpoint (lines 156–162):
```python
@app.get("/api/projects")
async def list_projects(sm: StateManager = Depends(get_sm)) -> dict[str, Any]:
    projects = sm.list_projects()
    for p in projects:
        progress = sm.get_progress(p["id"])
        p["status"] = _project_status(progress)
    return {"projects": projects}
```

`PipelineManager.get_status()` (pipeline_manager.py, lines 101–113) already exposes
`state` ("idle" | "running" | "paused") and `project_id`:
```python
def get_status(self) -> dict[str, Any]:
    _state_map = {"idle": "idle", "running": "running", "paused": "paused",
                  "stopping": "stopping", "stopped": "idle", "complete": "idle",
                  "error": "idle"}
    state = _state_map.get(self.status, "idle")
    events = list(self.orchestrator.events) if self.orchestrator else []
    return {
        "state":      state,
        "project_id": self.project_id if state != "idle" else None,
        "last_event": events[-1] if events else None,
    }
```

`get_manager` dependency (lines 121–122) is already defined and used in pipeline endpoints:
```python
def get_manager() -> PipelineManager:
    return app.state.manager
```

## Commands you will need

| Purpose    | Command                                                          | Expected on success    |
|------------|------------------------------------------------------------------|------------------------|
| Install    | `.\.venv\Scripts\pip install -e ".[dev]" -q`                    | exit 0                 |
| Tests      | `.\.venv\Scripts\python -m pytest tests/test_api.py -v`         | all pass               |
| Lint       | `.\.venv\Scripts\python -m ruff check src/verbatim/api/app.py`  | exit 0, no errors      |
| Typecheck  | `.\.venv\Scripts\python -m mypy src`                            | exit 0                 |
| Full suite | `.\.venv\Scripts\python -m pytest -q`                           | 116+ passed            |

## Scope

**In scope** (the only file you should modify):
- `src/verbatim/api/app.py`

**Out of scope** (do NOT touch):
- `src/verbatim/api/pipeline_manager.py` — already correct
- `ui/lib/types.ts` — already has the right types
- Any test file — existing tests already pass; update if a test breaks

## Git workflow

- Branch: `advisor/002-project-status-running-paused`
- Commit message: `fix: project GET/LIST endpoints reflect pipeline running/paused state`
- Do NOT push or open a PR.

## Steps

### Step 1: Update `_project_status` to accept optional pipeline state

Change the function signature and body to:

```python
def _project_status(
    progress: dict[str, Any],
    project_id: int = 0,
    mgr_status: "dict[str, Any] | None" = None,
) -> str:
    """Compute project status, factoring in active pipeline state."""
    if progress["total"] == 0:
        return "idle"
    if progress["error"] > 0:
        return "error"
    if progress["complete"] == progress["total"]:
        return "complete"
    if mgr_status and mgr_status.get("project_id") == project_id:
        state = mgr_status.get("state", "idle")
        if state in ("running", "paused"):
            return state
    return "idle"
```

**Verify**: `grep -n "def _project_status" src/verbatim/api/app.py` shows the updated signature.

### Step 2: Update `get_project` to inject the manager and pass its status

Change the endpoint from:

```python
@app.get("/api/projects/{project_id}")
async def get_project(
    project_id: int,
    sm: StateManager = Depends(get_sm),
) -> dict[str, Any]:
    project = sm.get_project_by_id(project_id)
    if not project:
        raise HTTPException(404, f"Project {project_id} not found.")
    progress = sm.get_progress(project_id)
    project["status"] = _project_status(progress)
    return {"project": project}
```

to:

```python
@app.get("/api/projects/{project_id}")
async def get_project(
    project_id: int,
    sm: StateManager = Depends(get_sm),
    mgr: PipelineManager = Depends(get_manager),
) -> dict[str, Any]:
    project = sm.get_project_by_id(project_id)
    if not project:
        raise HTTPException(404, f"Project {project_id} not found.")
    progress = sm.get_progress(project_id)
    project["status"] = _project_status(progress, project_id, mgr.get_status())
    return {"project": project}
```

**Verify**: `grep -A 10 "async def get_project" src/verbatim/api/app.py` shows `mgr: PipelineManager = Depends(get_manager)`.

### Step 3: Update `list_projects` to inject the manager and pass its status

Change from:

```python
@app.get("/api/projects")
async def list_projects(sm: StateManager = Depends(get_sm)) -> dict[str, Any]:
    projects = sm.list_projects()
    for p in projects:
        progress = sm.get_progress(p["id"])
        p["status"] = _project_status(progress)
    return {"projects": projects}
```

to:

```python
@app.get("/api/projects")
async def list_projects(
    sm: StateManager = Depends(get_sm),
    mgr: PipelineManager = Depends(get_manager),
) -> dict[str, Any]:
    projects = sm.list_projects()
    mgr_status = mgr.get_status()
    for p in projects:
        progress = sm.get_progress(p["id"])
        p["status"] = _project_status(progress, p["id"], mgr_status)
    return {"projects": projects}
```

Note: `mgr.get_status()` is called **once** outside the loop (not once per project).

**Verify**: `grep -A 8 "async def list_projects" src/verbatim/api/app.py` shows both the `mgr` parameter and `mgr_status` called outside the loop.

### Step 4: Update `create_project` similarly

The `create_project` endpoint also calls `_project_status(progress)` (line ~152).
Change it to pass `project_id` and `mgr.get_status()`:

Find the `create_project` endpoint. It currently ends with:
```python
    if project:
        project["status"] = _project_status(progress)
    return {"project": project}
```

Update to:
```python
    if project:
        project["status"] = _project_status(progress, project_id, mgr.get_status())
    return {"project": project}
```

And add `mgr: PipelineManager = Depends(get_manager)` to the function signature.

**Verify**: `grep -n "_project_status" src/verbatim/api/app.py` returns exactly 3 lines (create_project, get_project, list_projects) and all three pass `project_id` and `mgr.get_status()`.

Also verify `update_novel_profile` — it also calls `_project_status`. Apply the same pattern there too. There should be exactly 4 call sites total; update all of them.

### Step 5: Run the test suite

**Verify**: `.\.venv\Scripts\python -m pytest tests/test_api.py -v` → all existing tests pass.

If any test fails because it no longer matches `_project_status`'s old signature, update the test call sites (only in `tests/test_api.py`). The fix must not change observable behavior for tests that don't have the pipeline running.

### Step 6: Lint and typecheck

**Verify**: `.\.venv\Scripts\python -m ruff check src/verbatim/api/app.py` → exit 0.
**Verify**: `.\.venv\Scripts\python -m mypy src` → `Success: no issues found`.

### Step 7: Commit

```powershell
git add src/verbatim/api/app.py
git commit -m "fix: project GET/LIST endpoints reflect pipeline running/paused state"
```

## Test plan

No new test file needed for this fix. The existing `test_api.py::test_get_project_ok`
and `test_api.py::test_list_projects_empty` exercise these endpoints with the pipeline
idle, which is the common case. A running-pipeline test would require mocking
`PipelineManager.get_status()` — add one to `test_api.py` if time permits, but don't
block the commit on it. The structural fix (injecting manager into all project endpoints)
is the critical deliverable.

Model the existing `client` fixture in `tests/test_api.py` which shows how
`dependency_overrides` work for injecting test doubles.

## Done criteria

- [ ] `_project_status` has the new 3-parameter signature
- [ ] All 4 call sites in `app.py` pass `project_id` and `mgr.get_status()`
- [ ] All 4 endpoint functions have `mgr: PipelineManager = Depends(get_manager)` 
- [ ] `.\.venv\Scripts\python -m ruff check src/verbatim/api/app.py` exits 0
- [ ] `.\.venv\Scripts\python -m mypy src` exits 0
- [ ] `.\.venv\Scripts\python -m pytest tests/test_api.py -q` all pass
- [ ] Only `src/verbatim/api/app.py` is modified (and `tests/test_api.py` only if a test broke)

## STOP conditions

Stop and report if:
- The function signatures in app.py don't match the excerpts (drift).
- There are more or fewer than 4 call sites of `_project_status` (unexpected usage).
- `mypy` reports an error on the `mgr_status` dict access that isn't fixable with the `dict[str, Any]` type.
- A test fails in a way that isn't explained by the signature change.
