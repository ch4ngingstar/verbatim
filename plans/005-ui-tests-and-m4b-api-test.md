# Plan 005: Add UI component tests (CastingStudio, ChapterQueue) and M4B API test

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**:
> `git diff --stat b1274d9..HEAD -- ui/components/CastingStudio.tsx ui/components/ChapterQueue.tsx ui/hooks/useSSE.ts tests/test_api.py`
> If any of those files changed since this plan was written, compare the
> "Current state" excerpts below against the live code before proceeding.
> On a mismatch, treat as a STOP condition.

## Status

- **Priority**: P2
- **Effort**: M
- **Risk**: LOW
- **Depends on**: none
- **Category**: tests
- **Planned at**: commit `b1274d9`, 2026-06-13

## Why this matters

The codebase has 116 passing backend Python tests but zero UI test files.
Vitest and `@testing-library/react` are installed (`ui/package.json`) but never used.
For a portfolio project, this is a visible gap. The three highest-value targets:

1. **CastingStudio** — loads characters and voices, handles uploads and assignments.
   The most complex component in the app and the one most likely to break.
2. **ChapterQueue** — renders status badges and triggers chapter resets.
3. **M4B export API endpoint** — the only major backend route with no test.

## Current state

### vitest configuration

`ui/package.json` scripts:
```json
"test": "vitest run",
"test:watch": "vitest"
```

There is **no `vitest.config.ts`** — vitest's zero-config mode applies. That means:
- Vitest auto-discovers `*.test.tsx` and `*.spec.tsx` files anywhere in `ui/`
  (excluding `node_modules`).
- The jsdom environment must be declared per-file with `// @vitest-environment jsdom`
  OR in a `vitest.config.ts`. Create a `vitest.config.ts` (see Step 1) to set jsdom
  globally — simpler than per-file annotations.
- React 19 + `@testing-library/react` v16 works without a custom renderer setup in
  vitest's zero-config mode; `render`, `screen`, `userEvent` are available as-is.

### CastingStudio component (read before testing)

`ui/components/CastingStudio.tsx` — key behavior:
- On mount: fetches characters and voices in parallel (`Promise.all([listCharacters, listVoices])`).
- Renders each character with its name, status badge, and a voice-select dropdown.
- "Confirm" button calls `upsertCharacter(projectId, { name, status: 'cast' })`.
- Voice upload form calls `uploadVoice(name, file)`.
- All API calls are imported from `@/lib/api`.

### ChapterQueue component

`ui/components/ChapterQueue.tsx` — renders a chapter list with status badges.
Import it and read its props before writing tests.

### M4B export in `tests/test_api.py`

`POST /api/export/m4b` — the endpoint logic:
1. Checks the project exists (404 if not).
2. Filters chapters where `status == "complete"` AND `output_audio_path` is set.
3. Raises 409 if no complete chapters.
4. Calls `M4BExporter().export(...)` in a thread.
5. Returns `{"path": str, "size_bytes": int}`.

`M4BExporter` lives at `src/verbatim/audio/m4b.py`. Tests should monkeypatch it.

## Commands you will need

| Purpose        | Command                                                              | Expected on success      |
|----------------|----------------------------------------------------------------------|--------------------------|
| UI install     | `cd ui && npm install`                                               | exit 0                   |
| UI typecheck   | `cd ui && npm run typecheck`                                         | exit 0, no TS errors     |
| UI tests       | `cd ui && npm test`                                                  | all pass                 |
| Backend tests  | `.\.venv\Scripts\python -m pytest tests/test_api.py -v`             | all pass                 |
| Full backend   | `.\.venv\Scripts\python -m pytest -q`                               | 116+ passed              |
| Lint (backend) | `.\.venv\Scripts\python -m ruff check src/`                         | exit 0                   |
| Typecheck (be) | `.\.venv\Scripts\python -m mypy src`                                | exit 0                   |

## Scope

**In scope**:
- `ui/vitest.config.ts` (create — global jsdom config)
- `ui/components/CastingStudio.test.tsx` (create)
- `ui/components/ChapterQueue.test.tsx` (create)
- `tests/test_api.py` (add M4B tests at the end)

**Out of scope** (do NOT touch):
- `ui/components/CastingStudio.tsx` — do not modify source to make tests easier
- `ui/components/ChapterQueue.tsx` — same
- `ui/lib/api.ts` — mock it in tests, don't modify it
- Any Python source file

## Git workflow

- Branch: `advisor/005-ui-tests`
- Commit message: `test: add UI component tests and M4B export API test`
- Do NOT push or open a PR.

## Steps

### Step 1: Create `ui/vitest.config.ts`

```typescript
import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'
import path from 'path'

export default defineConfig({
  plugins: [react()],
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./vitest.setup.ts'],
  },
  resolve: {
    alias: {
      '@': path.resolve(__dirname, '.'),
    },
  },
})
```

Then create `ui/vitest.setup.ts`:

```typescript
import '@testing-library/jest-dom'
```

**Verify**: `cd ui && npm run typecheck` still exits 0 (vitest.config.ts must not introduce TS errors).

### Step 2: Write `ui/components/CastingStudio.test.tsx`

Read `ui/components/CastingStudio.tsx` and `ui/lib/api.ts` fully before writing.
Mock `@/lib/api` in the test file. Here is a template — adjust imports and rendered
text to match the actual component:

```tsx
import { render, screen, waitFor, fireEvent } from '@testing-library/react'
import { vi, describe, it, expect, beforeEach } from 'vitest'
import { CastingStudio } from './CastingStudio'
import type { Character, Voice } from '@/lib/types'

// Mock the entire api module
vi.mock('@/lib/api', () => ({
  listCharacters: vi.fn(),
  listVoices: vi.fn(),
  upsertCharacter: vi.fn(),
  uploadVoice: vi.fn(),
  deleteVoice: vi.fn(),
  assignVoice: vi.fn(),
}))

// import the mocked functions so tests can configure them
import * as api from '@/lib/api'

const MOCK_CHARS: Character[] = [
  { id: 1, project_id: 1, name: 'Sunny', aliases: [], emotion_hint: '', is_pov: true, status: 'suggested' },
  { id: 2, project_id: 1, name: 'Nephis', aliases: [], emotion_hint: '', is_pov: false, status: 'cast' },
]
const MOCK_VOICES: Voice[] = [
  { id: 1, name: 'Deep Male', path: 'voices/deep.wav', created_at: '2026-01-01T00:00:00Z' },
]

beforeEach(() => {
  vi.mocked(api.listCharacters).mockResolvedValue(MOCK_CHARS)
  vi.mocked(api.listVoices).mockResolvedValue(MOCK_VOICES)
  vi.mocked(api.upsertCharacter).mockResolvedValue(MOCK_CHARS[0])
  vi.mocked(api.uploadVoice).mockResolvedValue(MOCK_VOICES[0])
  vi.mocked(api.deleteVoice).mockResolvedValue(undefined)
  vi.mocked(api.assignVoice).mockResolvedValue(MOCK_CHARS[0])
})

describe('CastingStudio', () => {
  it('renders character names after loading', async () => {
    render(<CastingStudio projectId={1} />)
    await waitFor(() => {
      expect(screen.getByText('Sunny')).toBeInTheDocument()
      expect(screen.getByText('Nephis')).toBeInTheDocument()
    })
  })

  it('calls listCharacters and listVoices on mount', async () => {
    render(<CastingStudio projectId={1} />)
    await waitFor(() => {
      expect(api.listCharacters).toHaveBeenCalledWith(1)
      expect(api.listVoices).toHaveBeenCalled()
    })
  })

  it('shows voice library entries', async () => {
    render(<CastingStudio projectId={1} />)
    await waitFor(() => {
      expect(screen.getByText('Deep Male')).toBeInTheDocument()
    })
  })
})
```

**Important**: Look at the actual component to see what text it renders. If character
names appear in a different element or with different wrapper text, adjust the query.
If `CastingStudio` is a named export, import as `{ CastingStudio }`; if default, import
as `import CastingStudio from './CastingStudio'`.

**Verify**: `cd ui && npm test -- CastingStudio` → 3 tests pass.

### Step 3: Write `ui/components/ChapterQueue.test.tsx`

Read `ui/components/ChapterQueue.tsx` before writing. Write tests that:
1. Render chapter items from props (or mock API calls if it fetches internally).
2. Assert status badge text or class for a known status.
3. (If the component has a reset button) mock `resetChapter` and assert it's called.

Follow the same mock pattern as Step 2. Keep it to 3–5 focused tests.

**Verify**: `cd ui && npm test -- ChapterQueue` → tests pass.

### Step 4: Run all UI tests together

**Verify**: `cd ui && npm test` → all tests pass with no errors.
**Verify**: `cd ui && npm run typecheck` → exit 0.

### Step 5: Add M4B export tests to `tests/test_api.py`

Read `src/verbatim/audio/m4b.py` to understand `M4BExporter.export`'s signature
before writing the monkeypatch.

Add to `tests/test_api.py`:

```python
from verbatim.audio.m4b import M4BExporter


def test_export_m4b_no_complete_chapters(
    tmp_path: Path, client: TestClient, tmp_sm: StateManager
) -> None:
    pid = _seed_project(tmp_sm, tmp_path)
    # The seeded chapter has status 'complete' but no output_audio_path
    r = client.post("/api/export/m4b", json={"project_id": pid})
    assert r.status_code == 409


def test_export_m4b_project_not_found(client: TestClient) -> None:
    r = client.post("/api/export/m4b", json={"project_id": 9999})
    assert r.status_code == 404


def test_export_m4b_ok(
    tmp_path: Path,
    client: TestClient,
    tmp_sm: StateManager,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("VERBATIM_DATA_DIR", str(tmp_path / "data"))
    pid = _seed_project(tmp_sm, tmp_path)

    # Plant a fake MP3 and set chapter to complete with audio path
    mp3_dir = tmp_path / "data" / "output"
    mp3_dir.mkdir(parents=True, exist_ok=True)
    fake_mp3 = mp3_dir / "ch_0001.mp3"
    fake_mp3.write_bytes(b"ID3FAKE")

    import verbatim.config as cfg
    stored = cfg.to_stored(fake_mp3)
    with tmp_sm.db.conn() as conn:
        conn.execute(
            "UPDATE chapters SET status='complete', output_audio_path=? WHERE project_id=?",
            (stored, pid),
        )

    # Monkeypatch M4BExporter.export so no FFmpeg is needed
    fake_m4b = tmp_path / "data" / "m4b" / "TestBook.m4b"
    fake_m4b.parent.mkdir(parents=True, exist_ok=True)
    fake_m4b.write_bytes(b"ftyp")

    def fake_export(self: M4BExporter, chapter_data: list, output_path: Path, **kw: object) -> Path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"ftyp")
        return output_path

    monkeypatch.setattr(M4BExporter, "export", fake_export)

    r = client.post("/api/export/m4b", json={"project_id": pid})
    assert r.status_code == 200
    body = r.json()
    assert "path" in body
    assert body["size_bytes"] > 0
```

**Verify**: `.\.venv\Scripts\python -m pytest tests/test_api.py -k "m4b" -v` → 3 new tests pass.

### Step 6: Run full backend suite

**Verify**: `.\.venv\Scripts\python -m pytest -q` → 119+ passed (116 + 3 new).

### Step 7: Commit

```powershell
git add ui/vitest.config.ts ui/vitest.setup.ts `
        ui/components/CastingStudio.test.tsx `
        ui/components/ChapterQueue.test.tsx `
        tests/test_api.py
git commit -m "test: add UI component tests and M4B export API test"
```

## Done criteria

- [ ] `ui/vitest.config.ts` exists and sets environment to jsdom
- [ ] `ui/vitest.setup.ts` imports `@testing-library/jest-dom`
- [ ] `ui/components/CastingStudio.test.tsx` exists with ≥3 tests
- [ ] `ui/components/ChapterQueue.test.tsx` exists with ≥3 tests
- [ ] `cd ui && npm test` exits 0, all new tests pass
- [ ] `cd ui && npm run typecheck` exits 0
- [ ] 3 new M4B tests in `tests/test_api.py` pass
- [ ] `.\.venv\Scripts\python -m pytest -q` → 119+ passed

## STOP conditions

Stop and report if:
- `CastingStudio` uses internal state or context that makes `vi.mock('@/lib/api')` insufficient to isolate it — report what the dependency is.
- `ChapterQueue` requires a context provider (e.g. Router) — add `MemoryRouterProvider` or similar wrapper from the installed dependencies.
- `@testing-library/react` render throws for React 19 compatibility — report the error; a known fix is adding `{ wrapper: React.StrictMode }` to render options.
- `M4BExporter.export` signature doesn't match the monkeypatch (different parameter names) — adjust to match the actual signature read from `src/verbatim/audio/m4b.py`.
- `vitest.config.ts` path alias `@` resolution fails because `tsconfig.json` uses a different base — adjust the `resolve.alias` to match `ui/tsconfig.json`.

## Maintenance notes

- When new components are added, add test files alongside them in `ui/components/`.
- The `vi.mock('@/lib/api')` approach tests the component in isolation; E2E tests (Playwright) would be needed to test the API integration end-to-end. That's out of scope for now.
- GitHub Actions CI (`.github/workflows/ci.yml`) currently has only a backend job. A UI job running `cd ui && npm run typecheck && npm test` should be added once these tests are green.
