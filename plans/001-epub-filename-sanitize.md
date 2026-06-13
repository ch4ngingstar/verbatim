# Plan 001: Sanitize EPUB upload filename to prevent path traversal

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
- **Category**: security
- **Planned at**: commit `b1274d9`, 2026-06-13

## Why this matters

`POST /api/projects` accepts an EPUB upload and saves it using the client-supplied
filename without stripping directory components. Python's `Path /` operator resolves
`..` segments, so a filename like `../../evil.epub` writes the file outside the
intended `epubs/` subdirectory — potentially anywhere accessible to the process.
The fix is one character: use `Path(filename).name` to extract the bare filename,
discarding any path components the client supplied.

## Current state

**File**: `src/verbatim/api/app.py`

Relevant excerpt (lines 134–153):
```python
@app.post("/api/projects", status_code=201)
async def create_project(
    epub: UploadFile = File(...),
    sm: StateManager = Depends(get_sm),
) -> dict[str, Any]:
    if not (epub.filename or "").lower().endswith(".epub"):
        raise HTTPException(400, "Only .epub files are accepted.")
    content = await epub.read()
    if not content:
        raise HTTPException(400, "Uploaded EPUB is empty.")
    _epubs_dir().mkdir(parents=True, exist_ok=True)
    dest = _epubs_dir() / (epub.filename or "upload.epub")   # <-- BUG: line 145
    dest.write_bytes(content)
    parsed = await asyncio.to_thread(parse_epub, str(dest))
    project_id = sm.seed_project(parsed)
    ...
```

**Convention**: Existing validation in the same function uses `(epub.filename or "").lower().endswith(...)`.
No other location in the codebase concatenates user-supplied filenames with directory paths.

## Commands you will need

| Purpose    | Command                                                          | Expected on success    |
|------------|------------------------------------------------------------------|------------------------|
| Install    | `.\.venv\Scripts\pip install -e ".[dev]" -q`                    | exit 0                 |
| Tests      | `.\.venv\Scripts\python -m pytest tests/test_api.py -v`         | all pass               |
| Lint       | `.\.venv\Scripts\python -m ruff check src/verbatim/api/app.py`  | exit 0, no errors      |
| Typecheck  | `.\.venv\Scripts\python -m mypy src`                            | exit 0, no errors      |
| Full suite | `.\.venv\Scripts\python -m pytest -q`                           | 116+ passed            |

## Scope

**In scope** (the only file you should modify):
- `src/verbatim/api/app.py`

**Out of scope** (do NOT touch):
- Any other file. This is a one-line fix.

## Git workflow

- Branch: `advisor/001-epub-filename-sanitize`
- Commit message style (match repo): `fix: sanitize EPUB upload filename to prevent path traversal`
- Do NOT push or open a PR.

## Steps

### Step 1: Fix the filename sanitization

In `src/verbatim/api/app.py`, change line 145 from:

```python
    dest = _epubs_dir() / (epub.filename or "upload.epub")
```

to:

```python
    dest = _epubs_dir() / Path(epub.filename or "upload.epub").name
```

`Path("../../evil.epub").name` returns `"evil.epub"`, stripping all directory components.

**Verify**: `grep -n "epub.filename or" src/verbatim/api/app.py` should show the updated line containing `.name`.

### Step 2: Run the test suite

**Verify**: `.\.venv\Scripts\python -m pytest tests/test_api.py -v` → all existing tests pass (look for `PASSED` on every test line, no `FAILED`).

### Step 3: Run lint and typecheck

**Verify**: `.\.venv\Scripts\python -m ruff check src/verbatim/api/app.py` → exit 0, no output.
**Verify**: `.\.venv\Scripts\python -m mypy src` → `Success: no issues found`.

### Step 4: Commit

```powershell
git add src/verbatim/api/app.py
git commit -m "fix: sanitize EPUB upload filename to prevent path traversal"
```

## Test plan

No new test file needed — the existing `test_api.py::test_list_projects_empty` and
`test_api.py::test_get_project_ok` exercise the project creation path indirectly.

A regression assertion confirming `.name` is applied would be valuable but requires
a multipart upload fixture that's out of scope for this S-effort fix. Record in
NOTES if you add one; don't skip the commit if you don't.

## Done criteria

- [ ] `git diff HEAD -- src/verbatim/api/app.py` shows exactly the `.name` addition
- [ ] `.\.venv\Scripts\python -m ruff check src/verbatim/api/app.py` exits 0
- [ ] `.\.venv\Scripts\python -m mypy src` exits 0
- [ ] `.\.venv\Scripts\python -m pytest tests/test_api.py -q` exits 0
- [ ] No files outside `src/verbatim/api/app.py` are modified

## STOP conditions

Stop and report if:
- The code at line 145 doesn't match the excerpt above (drift).
- Adding `.name` changes any existing test output.
- Any STOP reveals the fix requires touching files outside scope.
