# Plan 003: Add voice DB lookup methods, batch list_projects progress, fix assembled status

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**:
> `git diff --stat b1274d9..HEAD -- src/verbatim/db/casting.py src/verbatim/db/chapters.py src/verbatim/api/app.py src/verbatim/pipeline/orchestrator.py`
> If any of those files changed since this plan was written, compare the
> "Current state" excerpts below against the live code before proceeding.
> On a mismatch, treat as a STOP condition.

## Status

- **Priority**: P2
- **Effort**: S
- **Risk**: LOW
- **Depends on**: none
- **Category**: tech-debt
- **Planned at**: commit `b1274d9`, 2026-06-13

## Why this matters

Three small but wrong patterns in the data layer:

1. **Two API endpoints load the entire voice library to find one voice by id or name.**
   `serve_voice_audio` (app.py:423) and `assign_character_voice` (app.py:344) each call
   `sm.list_voices()` and then `next(v for v in voices if v["id"/"name"] == target)`.
   The fix adds `get_voice_by_id` and `get_voice_by_name` to `CastingOps`.

2. **`list_projects` issues 1+N progress queries** — one per project.
   The fix adds `get_progress_batch` to `ChapterOps` that pulls all chapter counts
   in a single grouped SQL query.

3. **`_stage_assemble` marks a chapter `tts_done` (not `assembled`) after assembly.**
   The schema defines `assembled` as the post-assembly state, `_STAGES_FOR_STATUS`
   maps it to `[]`, and the resume logic depends on the status accurately reflecting
   the last completed stage. The current code sets `tts_done` (with the audio path),
   making `assembled` an unreachable, dead state. The fix is a one-word change.
   Note: since `_STAGES_FOR_STATUS["assembled"] = []`, a chapter stuck at `assembled`
   would be silently skipped on resume — so we must also ensure `_run_chapter`'s
   final `mark_chapter_status(ch_id, "complete")` covers that case.

## Current state

### Voice lookups in `src/verbatim/api/app.py`

`serve_voice_audio` (lines 418–431):
```python
@app.get("/api/voices/{voice_id}/audio")
async def serve_voice_audio(voice_id: int, sm: StateManager = Depends(get_sm)) -> FileResponse:
    voices = sm.list_voices()                                    # <-- loads all
    voice = next((v for v in voices if v["id"] == voice_id), None)  # <-- linear scan
    if voice is None:
        raise HTTPException(404, f"Voice {voice_id} not found.")
    ...
```

`assign_character_voice` (lines 337–356):
```python
    voices = sm.list_voices()                                       # <-- loads all
    voice = next((v for v in voices if v["name"] == req.voice_name), None)  # <-- linear scan
    if voice is None:
        raise HTTPException(404, f"Voice '{req.voice_name}' not found in library.")
```

### Voice list in `src/verbatim/db/casting.py`

`list_voices` (lines 106–115) already exists. No `get_voice_by_id` or `get_voice_by_name`.
The `add_voice` method shows the JSON decode pattern to follow:
```python
def list_voices(self) -> list[dict]:
    with self.db.conn() as conn:
        rows = conn.execute("SELECT * FROM voices ORDER BY name").fetchall()
    voices = []
    for r in rows:
        v = dict(r)
        v["tags"] = json.loads(v["tags"])
        voices.append(v)
    return voices
```

### `list_projects` N+1 in `src/verbatim/api/app.py` (lines 156–162)

```python
async def list_projects(sm: StateManager = Depends(get_sm)) -> dict[str, Any]:
    projects = sm.list_projects()
    for p in projects:
        progress = sm.get_progress(p["id"])   # <-- 1 query per project
        p["status"] = _project_status(progress, ...)
```

`get_progress` in `src/verbatim/db/chapters.py` (lines 55–73):
```python
def get_progress(self, project_id: int) -> dict:
    with self.db.conn() as conn:
        rows = conn.execute(
            "SELECT status, COUNT(*) AS cnt FROM chapters WHERE project_id=? GROUP BY status",
            (project_id,),
        ).fetchall()
    counts = {r["status"]: r["cnt"] for r in rows}
    total = sum(counts.values())
    complete = counts.get("complete", 0)
    return {
        "total": total, "pending": counts.get("pending", 0), "diarized": ...,
        "tts_done": ..., "assembled": ..., "complete": complete, "error": ...,
        "pct_complete": round(complete / total * 100, 1) if total else 0.0,
    }
```

### Assembled status in `src/verbatim/pipeline/orchestrator.py`

`_stage_assemble` (lines 272–298):
```python
    def _stage_assemble(self, chapter_id: int, chapter: dict[str, Any]) -> None:
        ...
        stored = config.to_stored(out)
        file_size = out.stat().st_size if out.exists() else None
        self._sm.mark_chapter_status(chapter_id, "tts_done",      # <-- should be "assembled"
                                     audio_path=stored,
                                     file_size_bytes=file_size)
        self._emit("stage_done", ...)
```

`_STAGES_FOR_STATUS` (lines 42–48) — `assembled: []` means no stages to run (correct for resume skip-to-complete behavior):
```python
_STAGES_FOR_STATUS: dict[str, list[str]] = {
    "pending":   _ALL_STAGES,
    "diarized":  _ALL_STAGES[1:],
    "tts_done":  _ALL_STAGES[2:],
    "assembled": [],
    "complete":  [],
}
```

`_run_chapter` (lines 205–228) calls `mark_chapter_status(ch_id, "complete", ...)` after all stages — this correctly transitions `assembled → complete`. No change needed there.

## Commands you will need

| Purpose    | Command                                                             | Expected on success  |
|------------|---------------------------------------------------------------------|----------------------|
| Install    | `.\.venv\Scripts\pip install -e ".[dev]" -q`                       | exit 0               |
| Tests      | `.\.venv\Scripts\python -m pytest tests/ -v`                       | all pass             |
| Lint       | `.\.venv\Scripts\python -m ruff check src/`                        | exit 0               |
| Typecheck  | `.\.venv\Scripts\python -m mypy src`                               | exit 0               |
| Full suite | `.\.venv\Scripts\python -m pytest -q`                              | 116+ passed          |

## Scope

**In scope**:
- `src/verbatim/db/casting.py` (add `get_voice_by_id`, `get_voice_by_name`)
- `src/verbatim/db/chapters.py` (add `get_progress_batch`)
- `src/verbatim/api/app.py` (use new methods)
- `src/verbatim/pipeline/orchestrator.py` (change `"tts_done"` → `"assembled"` in `_stage_assemble`)
- `tests/test_casting.py` (add tests for new voice methods)

**Out of scope** (do NOT touch):
- `src/verbatim/db/manager.py` — `StateManager` inherits everything; no change needed
- `src/verbatim/db/schema.py` — schema already defines `assembled` correctly
- `src/verbatim/db/base.py`
- Any UI file

## Git workflow

- Branch: `advisor/003-db-voice-methods-assembled`
- Commit message: `feat: add voice lookup methods, batch progress query, fix assembled status`
- Do NOT push or open a PR.

## Steps

### Step 1: Add `get_voice_by_id` and `get_voice_by_name` to `CastingOps`

In `src/verbatim/db/casting.py`, after the `list_voices` method (around line 115), add:

```python
def get_voice_by_id(self, voice_id: int) -> "dict | None":
    with self.db.conn() as conn:
        row = conn.execute("SELECT * FROM voices WHERE id=?", (voice_id,)).fetchone()
    if row is None:
        return None
    v = dict(row)
    v["tags"] = json.loads(v["tags"])
    return v

def get_voice_by_name(self, name: str) -> "dict | None":
    with self.db.conn() as conn:
        row = conn.execute("SELECT * FROM voices WHERE name=?", (name,)).fetchone()
    if row is None:
        return None
    v = dict(row)
    v["tags"] = json.loads(v["tags"])
    return v
```

**Verify**: `.\.venv\Scripts\python -c "from verbatim.db.casting import CastingOps; print('ok')"` → `ok`.

### Step 2: Add `get_progress_batch` to `ChapterOps`

In `src/verbatim/db/chapters.py`, after the `get_progress` method, add:

```python
def get_progress_batch(self, project_ids: list[int]) -> "dict[int, dict]":
    """Return {project_id: progress_dict} for multiple projects in one query."""
    if not project_ids:
        return {}
    placeholders = ",".join("?" * len(project_ids))
    with self.db.conn() as conn:
        rows = conn.execute(
            f"SELECT project_id, status, COUNT(*) AS cnt FROM chapters "
            f"WHERE project_id IN ({placeholders}) GROUP BY project_id, status",
            project_ids,
        ).fetchall()
    result: dict[int, dict] = {pid: {
        "total": 0, "pending": 0, "diarized": 0, "tts_done": 0,
        "assembled": 0, "complete": 0, "error": 0, "pct_complete": 0.0,
    } for pid in project_ids}
    for row in rows:
        pid, status, cnt = row["project_id"], row["status"], row["cnt"]
        if pid in result:
            result[pid][status] = cnt
            result[pid]["total"] += cnt
    for pid, counts in result.items():
        total = counts["total"]
        complete = counts.get("complete", 0)
        counts["pct_complete"] = round(complete / total * 100, 1) if total else 0.0
    return result
```

**Verify**: `.\.venv\Scripts\python -c "from verbatim.db.chapters import ChapterOps; print('ok')"` → `ok`.

### Step 3: Update `serve_voice_audio` in `app.py`

Replace the full-list scan with `get_voice_by_id`:

```python
@app.get("/api/voices/{voice_id}/audio")
async def serve_voice_audio(
    voice_id: int,
    sm: StateManager = Depends(get_sm),
) -> FileResponse:
    voice = sm.get_voice_by_id(voice_id)
    if voice is None:
        raise HTTPException(404, f"Voice {voice_id} not found.")
    p = config.from_stored(voice["path"])
    if not p.exists():
        raise HTTPException(404, f"Reference clip missing on disk: {voice['path']}")
    media_type = _VOICE_MEDIA_TYPES.get(p.suffix.lower(), "application/octet-stream")
    return FileResponse(str(p), media_type=media_type, filename=p.name)
```

**Verify**: `grep -n "list_voices" src/verbatim/api/app.py` should NOT show a call inside `serve_voice_audio`.

### Step 4: Update `assign_character_voice` in `app.py`

Replace the full-list scan with `get_voice_by_name`:

```python
    voice = sm.get_voice_by_name(req.voice_name)
    if voice is None:
        raise HTTPException(404, f"Voice '{req.voice_name}' not found in library.")
    sm.assign_voice(character_id, voice["id"])
```

Remove the `voices = sm.list_voices()` and `voice = next(...)` lines that previously preceded this block.

**Verify**: `grep -n "sm.list_voices" src/verbatim/api/app.py` returns only the explicit `list_voices` endpoint itself (line ~362), not the voice-lookup call sites.

### Step 5: Update `list_projects` to use `get_progress_batch`

In `app.py`, change `list_projects` from:
```python
    projects = sm.list_projects()
    for p in projects:
        progress = sm.get_progress(p["id"])
        p["status"] = _project_status(progress, ...)
```
to:
```python
    projects = sm.list_projects()
    pids = [p["id"] for p in projects]
    batch = sm.get_progress_batch(pids)
    for p in projects:
        progress = batch.get(p["id"], {"total": 0, "complete": 0, "error": 0})
        p["status"] = _project_status(progress, ...)
```

Note: if Plan 002 has been applied, `_project_status` takes 3 arguments. If not, it takes 1.
Apply whatever signature `_project_status` has in the live code; don't change the signature here.

**Verify**: `grep -A 8 "async def list_projects" src/verbatim/api/app.py` shows `get_progress_batch` and no `get_progress` call inside the per-project loop.

### Step 6: Fix `assembled` status in `_stage_assemble`

In `src/verbatim/pipeline/orchestrator.py`, change line ~293:

```python
        self._sm.mark_chapter_status(chapter_id, "tts_done",
                                     audio_path=stored,
                                     file_size_bytes=file_size)
```

to:

```python
        self._sm.mark_chapter_status(chapter_id, "assembled",
                                     audio_path=stored,
                                     file_size_bytes=file_size)
```

This makes the state machine correct: `tts_done → assembled → complete`.
`_run_chapter` already calls `mark_chapter_status(ch_id, "complete")` after all stages,
which transitions `assembled → complete`. No further changes needed in the orchestrator.

**Verify**: `grep -n '"assembled"' src/verbatim/pipeline/orchestrator.py` shows the status being set in `_stage_assemble`.

### Step 7: Add tests for the new voice methods

In `tests/test_casting.py`, add after the last existing test:

```python
def test_get_voice_by_id(sm, pid):
    vid = sm.add_voice("TestVoice", "voices/test.wav", tags=["test"])
    v = sm.get_voice_by_id(vid)
    assert v is not None
    assert v["name"] == "TestVoice"
    assert v["tags"] == ["test"]
    assert sm.get_voice_by_id(99999) is None


def test_get_voice_by_name(sm, pid):
    sm.add_voice("NamedVoice", "voices/named.wav")
    v = sm.get_voice_by_name("NamedVoice")
    assert v is not None
    assert v["name"] == "NamedVoice"
    assert sm.get_voice_by_name("no-such-voice") is None
```

(The `sm` and `pid` fixtures are already defined in `tests/test_casting.py`.)

**Verify**: `.\.venv\Scripts\python -m pytest tests/test_casting.py -v` → all tests pass, including 2 new ones.

### Step 8: Run full suite, lint, typecheck

**Verify**: `.\.venv\Scripts\python -m pytest -q` → 118+ passed (116 existing + 2 new).
**Verify**: `.\.venv\Scripts\python -m ruff check src/` → exit 0.
**Verify**: `.\.venv\Scripts\python -m mypy src` → `Success: no issues found`.

### Step 9: Commit

```powershell
git add src/verbatim/db/casting.py src/verbatim/db/chapters.py `
        src/verbatim/api/app.py src/verbatim/pipeline/orchestrator.py `
        tests/test_casting.py
git commit -m "feat: add voice lookup methods, batch progress query, fix assembled status"
```

## Test plan

New tests in `tests/test_casting.py`: `test_get_voice_by_id`, `test_get_voice_by_name`.
Pattern to follow: the existing `test_voice_library_and_casting` test in the same file.

## Done criteria

- [ ] `sm.get_voice_by_id(id)` and `sm.get_voice_by_name(name)` exist and return `dict | None`
- [ ] `sm.get_progress_batch([...])` exists in `ChapterOps`
- [ ] `serve_voice_audio` no longer calls `list_voices`
- [ ] `assign_character_voice` no longer calls `list_voices`
- [ ] `list_projects` uses `get_progress_batch` with one call outside the loop
- [ ] `_stage_assemble` sets status `"assembled"` not `"tts_done"`
- [ ] `.\.venv\Scripts\python -m pytest -q` → 118+ passed
- [ ] `.\.venv\Scripts\python -m ruff check src/` → exit 0
- [ ] `.\.venv\Scripts\python -m mypy src` → exit 0

## STOP conditions

Stop and report if:
- Any code excerpt above doesn't match the live file (drift since b1274d9).
- `get_progress_batch` SQL query causes a test failure due to SQLite parameter binding (adjust placeholder format).
- The `assembled` status change causes any existing test to fail (it shouldn't — no test checks the intermediate assembled state).
- `mypy` reports an error on the new method signatures.
