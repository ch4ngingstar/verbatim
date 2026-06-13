# Verbatim Phase 1 — Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stand up the Verbatim repo with tooling, the profile-aware SQLite data layer, and the EPUB ingest stage (parser + profile-driven segmenter) — fully tested, no GPU required.

**Architecture:** Installable Python package `verbatim` under `src/`. A `StateManager` facade composed from three ops mixins (projects, chapters, casting) over one SQLite database keeps every file under 500 lines while preserving the proven Shadow Slave call surface. All stored file paths are **relative to a configured data root** (`VERBATIM_DATA_DIR`), never CWD-relative. The segmenter's Shadow-Slave-specific conventions ('single quotes' = thoughts, `[brackets]` = system lines) become per-project profile flags.

**Tech Stack:** Python 3.11, SQLite (WAL), ebooklib + BeautifulSoup + spaCy for ingest, pytest, ruff, mypy, GitHub Actions.

**Source repo for ports:** `C:\Users\alityan\OneDrive\Desktop\shaodw salve` (referred to below as `SHADOW`). Port = copy then modify as shown; never import from SHADOW.

**Spec:** `docs/superpowers/specs/2026-06-13-verbatim-design.md`

**Later phases (separate plans, not here):** Phase 2 Casting Director + profile-driven diarizer; Phase 3 TTS/assembler/M4B/orchestrator; Phase 4 FastAPI + checkpoints + SSE; Phase 5 Next.js UI.

---

### Task 1: Repo scaffold and tooling

**Files:**
- Create: `pyproject.toml`
- Create: `.gitignore`
- Create: `LICENSE`
- Create: `.env.example`
- Create: `README.md`
- Create: `src/verbatim/__init__.py`
- Create: `tests/__init__.py`

- [ ] **Step 1: Create `pyproject.toml`**

```toml
[project]
name = "verbatim"
version = "0.1.0"
description = "Turn any novel EPUB into a multi-voice audiobook with per-character voices and per-line emotion - fully local."
requires-python = ">=3.11"
license = { text = "MIT" }
dependencies = [
    "ebooklib>=0.18",
    "beautifulsoup4>=4.12",
    "spacy>=3.7",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "ruff>=0.4",
    "mypy>=1.10",
]

[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[tool.setuptools.packages.find]
where = ["src"]

[tool.ruff]
line-length = 100
src = ["src", "tests"]

[tool.ruff.lint]
select = ["E", "F", "I", "UP", "B"]

[tool.mypy]
python_version = "3.11"
disallow_untyped_defs = true
ignore_missing_imports = true

[tool.pytest.ini_options]
testpaths = ["tests"]
```

- [ ] **Step 2: Create `.gitignore`**

```gitignore
__pycache__/
*.py[cod]
.venv/
venv/
.env
data/
*.egg-info/
.mypy_cache/
.ruff_cache/
.pytest_cache/
node_modules/
.next/
```

- [ ] **Step 3: Create `LICENSE`** — standard MIT license text, copyright line:

```
MIT License

Copyright (c) 2026 ch4ngingstar
```

(followed by the unmodified standard MIT body.)

- [ ] **Step 4: Create `.env.example`**

```bash
# Root directory for all Verbatim data (DB, audio, voices, covers).
# All paths stored in the DB are RELATIVE to this directory.
VERBATIM_DATA_DIR=./data
```

- [ ] **Step 5: Create `README.md`** (stub — full README is a Phase 5 task)

```markdown
# Verbatim

Turn any novel EPUB into a multi-voice audiobook — per-character voices,
per-line emotional delivery — running entirely on your own GPU.

> Work in progress. See `docs/superpowers/specs/2026-06-13-verbatim-design.md`.
```

- [ ] **Step 6: Create empty package markers**

`src/verbatim/__init__.py`:

```python
"""Verbatim: any-novel EPUB -> multi-voice audiobook, fully local."""

__version__ = "0.1.0"
```

`tests/__init__.py`: empty file.

- [ ] **Step 7: Create venv, install, verify tooling runs**

Run (from repo root `C:\Users\alityan\OneDrive\Desktop\verbatim`):

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -e ".[dev]"
.\.venv\Scripts\python -m pytest
.\.venv\Scripts\python -m ruff check .
```

Expected: pip succeeds; pytest reports "no tests ran" (exit 5 is fine at this point); ruff reports no errors.

- [ ] **Step 8: Commit**

```powershell
git add -A; git commit -m "chore: scaffold package, tooling, license, env example"
```

---

### Task 2: Config module — data root and relative path discipline

Every file path stored in the DB is relative to the data root. This is the permanent fix for the Shadow Slave CWD bug class.

**Files:**
- Create: `src/verbatim/config.py`
- Test: `tests/test_config.py`

- [ ] **Step 1: Write the failing tests**

`tests/test_config.py`:

```python
from pathlib import Path

from verbatim import config


def test_data_root_from_env(tmp_path, monkeypatch):
    monkeypatch.setenv("VERBATIM_DATA_DIR", str(tmp_path / "mydata"))
    root = config.data_root()
    assert root == (tmp_path / "mydata").resolve()
    assert root.is_dir()  # created on demand


def test_data_root_default_is_cwd_data(tmp_path, monkeypatch):
    monkeypatch.delenv("VERBATIM_DATA_DIR", raising=False)
    monkeypatch.chdir(tmp_path)
    assert config.data_root() == (tmp_path / "data").resolve()


def test_roundtrip_relative_storage(tmp_path, monkeypatch):
    monkeypatch.setenv("VERBATIM_DATA_DIR", str(tmp_path))
    f = tmp_path / "voices" / "clip.wav"
    f.parent.mkdir()
    f.write_bytes(b"x")
    rel = config.to_stored(f)
    assert rel == "voices/clip.wav"  # forward slashes, no drive letter
    assert config.from_stored(rel) == f.resolve()


def test_to_stored_rejects_path_outside_root(tmp_path, monkeypatch):
    monkeypatch.setenv("VERBATIM_DATA_DIR", str(tmp_path / "root"))
    outside = tmp_path / "elsewhere" / "clip.wav"
    try:
        config.to_stored(outside)
        assert False, "expected ValueError"
    except ValueError:
        pass


def test_from_stored_passes_through_absolute(tmp_path, monkeypatch):
    monkeypatch.setenv("VERBATIM_DATA_DIR", str(tmp_path))
    p = (tmp_path / "x.wav").resolve()
    assert config.from_stored(str(p)) == p
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.\.venv\Scripts\python -m pytest tests/test_config.py -v`
Expected: FAIL — `ModuleNotFoundError`/`AttributeError` (config module not written).

- [ ] **Step 3: Write the implementation**

`src/verbatim/config.py`:

```python
"""Data-root configuration and the relative-path storage contract.

Every file path persisted in the DB is stored relative to data_root()
(forward slashes). This makes the DB portable and immune to CWD changes -
the bug class that bit the Shadow Slave pipeline repeatedly.
"""

import os
from pathlib import Path


def data_root() -> Path:
    """Absolute data directory from VERBATIM_DATA_DIR (default ./data). Created on demand."""
    root = Path(os.environ.get("VERBATIM_DATA_DIR", "data")).resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


def to_stored(path: "str | Path") -> str:
    """Convert an absolute path under the data root to its stored (relative, posix) form."""
    p = Path(path).resolve()
    try:
        return p.relative_to(data_root()).as_posix()
    except ValueError as exc:
        raise ValueError(
            f"Refusing to store path outside data root {data_root()}: {p}"
        ) from exc


def from_stored(stored: str) -> Path:
    """Resolve a stored path back to an absolute path. Absolute inputs pass through."""
    p = Path(stored)
    return p.resolve() if p.is_absolute() else (data_root() / p).resolve()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.\.venv\Scripts\python -m pytest tests/test_config.py -v`
Expected: 5 PASS.

- [ ] **Step 5: Commit**

```powershell
git add src/verbatim/config.py tests/test_config.py
git commit -m "feat: data-root config with relative-path storage contract"
```

---

### Task 3: Database schema

**Files:**
- Create: `src/verbatim/db/__init__.py`
- Create: `src/verbatim/db/schema.py`
- Test: `tests/test_schema.py`

- [ ] **Step 1: Write the failing test**

`tests/test_schema.py`:

```python
import sqlite3

from verbatim.db.schema import SCHEMA

EXPECTED_TABLES = {"projects", "chapters", "chunks", "lines", "characters", "voices"}


def test_schema_creates_all_tables(tmp_path):
    conn = sqlite3.connect(tmp_path / "t.db")
    conn.executescript(SCHEMA)
    rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    names = {r[0] for r in rows}
    assert EXPECTED_TABLES <= names


def test_schema_is_idempotent(tmp_path):
    conn = sqlite3.connect(tmp_path / "t.db")
    conn.executescript(SCHEMA)
    conn.executescript(SCHEMA)  # must not raise
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.\.venv\Scripts\python -m pytest tests/test_schema.py -v`
Expected: FAIL — `ModuleNotFoundError: verbatim.db`.

- [ ] **Step 3: Write the schema**

`src/verbatim/db/__init__.py`: empty file.

`src/verbatim/db/schema.py`:

```python
"""SQLite schema for Verbatim.

Differences from the Shadow Slave pipeline DB:
  * projects carries the Novel Profile (POV, thought convention, narrator notes).
  * characters is a first-class table (Shadow Slave hardcoded SPEAKER_ALIASES).
  * voices is a GLOBAL library keyed by voice name, not by speaker; casting
    happens via characters.voice_id per project.
  * All paths stored relative to the configured data root (see config.py).
"""

SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS projects (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT    NOT NULL UNIQUE,
    source_epub     TEXT    NOT NULL,
    cover_path      TEXT,
    total_chapters  INTEGER NOT NULL,
    -- Novel Profile -----------------------------------------------------
    pov_style          TEXT NOT NULL DEFAULT 'third',   -- 'first' | 'third'
    pov_characters     TEXT NOT NULL DEFAULT '[]',      -- JSON list of names
    thought_convention TEXT NOT NULL DEFAULT 'none',    -- 'none' | 'single_quotes'
    system_brackets    INTEGER NOT NULL DEFAULT 0,      -- [brackets] are system lines
    narrator_notes     TEXT NOT NULL DEFAULT '',
    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    updated_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);

CREATE TABLE IF NOT EXISTS chapters (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id    INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    chapter_index INTEGER NOT NULL,
    title         TEXT    NOT NULL,
    status        TEXT    NOT NULL DEFAULT 'pending',
    total_chunks  INTEGER NOT NULL DEFAULT 0,
    total_lines   INTEGER NOT NULL DEFAULT 0,
    output_audio_path      TEXT,
    output_file_size_bytes INTEGER,
    processing_seconds     REAL,
    error_message TEXT,
    created_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    updated_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    UNIQUE(project_id, chapter_index)
);

CREATE TABLE IF NOT EXISTS chunks (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    chapter_id    INTEGER NOT NULL REFERENCES chapters(id) ON DELETE CASCADE,
    chunk_index   INTEGER NOT NULL,
    text          TEXT    NOT NULL,
    word_count    INTEGER NOT NULL,
    UNIQUE(chapter_id, chunk_index)
);

CREATE TABLE IF NOT EXISTS lines (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    chapter_id    INTEGER NOT NULL REFERENCES chapters(id) ON DELETE CASCADE,
    line_index    INTEGER NOT NULL,
    speaker       TEXT    NOT NULL,
    text          TEXT    NOT NULL,
    emotion       TEXT    NOT NULL DEFAULT 'neutral',
    status        TEXT    NOT NULL DEFAULT 'pending',
    audio_path    TEXT,
    error_message TEXT,
    created_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    UNIQUE(chapter_id, line_index)
);

CREATE TABLE IF NOT EXISTS voices (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    name          TEXT    NOT NULL UNIQUE,
    path          TEXT    NOT NULL,
    tags          TEXT    NOT NULL DEFAULT '[]',
    created_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    updated_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);

CREATE TABLE IF NOT EXISTS characters (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id    INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    name          TEXT    NOT NULL,
    aliases       TEXT    NOT NULL DEFAULT '[]',
    emotion_hint  TEXT    NOT NULL DEFAULT '',
    is_pov        INTEGER NOT NULL DEFAULT 0,
    status        TEXT    NOT NULL DEFAULT 'suggested',  -- cast | suggested | ignored
    voice_id      INTEGER REFERENCES voices(id) ON DELETE SET NULL,
    line_count    INTEGER NOT NULL DEFAULT 0,
    chapter_count INTEGER NOT NULL DEFAULT 0,
    created_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    updated_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    UNIQUE(project_id, name)
);
"""

CHAPTER_STATUSES = {"pending", "diarized", "tts_done", "assembled", "complete", "error"}
LINE_STATUSES = {"pending", "tts_done", "failed"}
CHARACTER_STATUSES = {"cast", "suggested", "ignored"}
THOUGHT_CONVENTIONS = {"none", "single_quotes"}
POV_STYLES = {"first", "third"}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.\.venv\Scripts\python -m pytest tests/test_schema.py -v`
Expected: 2 PASS.

- [ ] **Step 5: Commit**

```powershell
git add src/verbatim/db/ tests/test_schema.py
git commit -m "feat: profile-aware SQLite schema (projects, characters, global voices)"
```

---

### Task 4: StateManager core + project ops

The facade pattern: `StateManager(ProjectOps, ChapterOps, CastingOps)` in `manager.py`; each ops class is a mixin assuming `self._conn` exists. This keeps each file focused and under 500 lines while later phases port Shadow Slave modules against familiar method names.

**Files:**
- Create: `src/verbatim/db/base.py`
- Create: `src/verbatim/db/projects.py`
- Create: `src/verbatim/db/manager.py`
- Test: `tests/test_projects.py`

- [ ] **Step 1: Write the failing tests**

`tests/test_projects.py`:

```python
import pytest

from verbatim.db.manager import StateManager


@pytest.fixture
def sm(tmp_path):
    return StateManager(tmp_path / "t.db")


PARSED = {
    "source_epub": "mybook.epub",
    "total_chapters": 2,
    "chapters": [
        {"chapter_index": 0, "title": "One",
         "chunks": [{"chunk_index": 0, "text": "Hello world.", "word_count": 2}]},
        {"chapter_index": 1, "title": "Two",
         "chunks": [{"chunk_index": 0, "text": "Bye.", "word_count": 1}]},
    ],
}


def test_seed_project_creates_rows(sm):
    pid = sm.seed_project(PARSED)
    proj = sm.get_project_by_id(pid)
    assert proj["name"] == "mybook"
    assert proj["total_chapters"] == 2
    assert proj["thought_convention"] == "none"  # profile defaults exist
    assert len(sm.get_all_chapters(pid)) == 2


def test_seed_project_is_idempotent(sm):
    pid1 = sm.seed_project(PARSED)
    pid2 = sm.seed_project(PARSED)
    assert pid1 == pid2
    assert len(sm.list_projects()) == 1


def test_update_profile(sm):
    pid = sm.seed_project(PARSED)
    sm.update_profile(pid, pov_style="third", pov_characters=["Sunny"],
                      thought_convention="single_quotes", system_brackets=True,
                      narrator_notes="LitRPG with system messages.")
    proj = sm.get_project_by_id(pid)
    assert proj["pov_characters"] == ["Sunny"]       # JSON decoded on read
    assert proj["thought_convention"] == "single_quotes"
    assert proj["system_brackets"] == 1


def test_update_profile_rejects_bad_values(sm):
    pid = sm.seed_project(PARSED)
    with pytest.raises(ValueError):
        sm.update_profile(pid, thought_convention="telepathy")
    with pytest.raises(ValueError):
        sm.update_profile(pid, pov_style="second")
    with pytest.raises(ValueError):
        sm.update_profile(pid, favourite_color="red")  # unknown field
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.\.venv\Scripts\python -m pytest tests/test_projects.py -v`
Expected: FAIL — `ModuleNotFoundError: verbatim.db.manager`.

- [ ] **Step 3: Write `src/verbatim/db/base.py`**

```python
"""Shared SQLite plumbing for all ops mixins."""

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from verbatim.db.schema import SCHEMA


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class Database:
    """Owns the DB file. WAL mode lets FastAPI read while the pipeline writes."""

    def __init__(self, db_path: "str | Path"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self.conn() as c:
            c.executescript(SCHEMA)

    @contextmanager
    def conn(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
```

- [ ] **Step 4: Write `src/verbatim/db/projects.py`**

```python
"""Project + Novel Profile operations (mixin for StateManager)."""

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from verbatim.db.base import Database, now_iso
from verbatim.db.schema import POV_STYLES, THOUGHT_CONVENTIONS

# Profile fields and their validators / serializers.
_PROFILE_FIELDS: dict[str, Any] = {
    "pov_style": lambda v: v in POV_STYLES,
    "pov_characters": lambda v: isinstance(v, list),
    "thought_convention": lambda v: v in THOUGHT_CONVENTIONS,
    "system_brackets": lambda v: isinstance(v, bool | int),
    "narrator_notes": lambda v: isinstance(v, str),
    "cover_path": lambda v: v is None or isinstance(v, str),
}


def _decode_project(row: Any) -> dict:
    proj = dict(row)
    proj["pov_characters"] = json.loads(proj["pov_characters"])
    return proj


class ProjectOps:
    db: Database

    def seed_project(self, parsed_book: Any, force_reseed: bool = False) -> int:
        """Import a ParsedBook (dataclass or dict). Idempotent by project name."""
        book = asdict(parsed_book) if hasattr(parsed_book, "__dataclass_fields__") else parsed_book
        name = Path(book["source_epub"]).stem

        with self.db.conn() as conn:
            if not force_reseed:
                row = conn.execute("SELECT id FROM projects WHERE name=?", (name,)).fetchone()
                if row:
                    return int(row["id"])

            conn.execute(
                """INSERT INTO projects (name, source_epub, total_chapters, updated_at)
                   VALUES (?, ?, ?, ?)
                   ON CONFLICT(name) DO UPDATE SET
                     total_chapters=excluded.total_chapters, updated_at=excluded.updated_at""",
                (name, book["source_epub"], book["total_chapters"], now_iso()),
            )
            project_id = int(
                conn.execute("SELECT id FROM projects WHERE name=?", (name,)).fetchone()["id"]
            )
            for ch in book["chapters"]:
                conn.execute(
                    """INSERT INTO chapters
                         (project_id, chapter_index, title, total_chunks, status, updated_at)
                       VALUES (?, ?, ?, ?, 'pending', ?)
                       ON CONFLICT(project_id, chapter_index) DO NOTHING""",
                    (project_id, ch["chapter_index"], ch["title"], len(ch["chunks"]), now_iso()),
                )
                chapter_id = conn.execute(
                    "SELECT id FROM chapters WHERE project_id=? AND chapter_index=?",
                    (project_id, ch["chapter_index"]),
                ).fetchone()["id"]
                for ck in ch["chunks"]:
                    conn.execute(
                        """INSERT INTO chunks (chapter_id, chunk_index, text, word_count)
                           VALUES (?, ?, ?, ?)
                           ON CONFLICT(chapter_id, chunk_index) DO NOTHING""",
                        (chapter_id, ck["chunk_index"], ck["text"], ck["word_count"]),
                    )
        return project_id

    def get_project_by_id(self, project_id: int) -> "dict | None":
        with self.db.conn() as conn:
            row = conn.execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone()
            return _decode_project(row) if row else None

    def get_project(self, name: str) -> "dict | None":
        with self.db.conn() as conn:
            row = conn.execute("SELECT * FROM projects WHERE name=?", (name,)).fetchone()
            return _decode_project(row) if row else None

    def list_projects(self) -> list[dict]:
        with self.db.conn() as conn:
            rows = conn.execute("SELECT * FROM projects ORDER BY created_at DESC").fetchall()
            return [_decode_project(r) for r in rows]

    def update_profile(self, project_id: int, **fields: Any) -> None:
        """Update Novel Profile fields. Unknown fields or invalid values raise ValueError."""
        for key, value in fields.items():
            validate = _PROFILE_FIELDS.get(key)
            if validate is None:
                raise ValueError(f"Unknown profile field: '{key}'")
            if not validate(value):
                raise ValueError(f"Invalid value for profile field '{key}': {value!r}")

        sets, params = [], []
        for key, value in fields.items():
            sets.append(f"{key}=?")
            if key == "pov_characters":
                params.append(json.dumps(value))
            elif key == "system_brackets":
                params.append(int(value))
            else:
                params.append(value)
        params.extend([now_iso(), project_id])
        with self.db.conn() as conn:
            conn.execute(
                f"UPDATE projects SET {', '.join(sets)}, updated_at=? WHERE id=?", params
            )
```

- [ ] **Step 5: Write `src/verbatim/db/manager.py`** (chapter/casting mixins arrive in Tasks 5–6; start with projects only)

```python
"""StateManager facade - the single source of truth for all pipeline state.

Composed from ops mixins so each concern stays in its own file:
  ProjectOps  - projects + Novel Profile
  ChapterOps  - chapters, chunks, lines, progress   (Task 5)
  CastingOps  - characters + global voice library   (Task 6)
"""

from pathlib import Path

from verbatim.db.base import Database
from verbatim.db.projects import ProjectOps


class StateManager(ProjectOps):
    def __init__(self, db_path: "str | Path"):
        self.db = Database(db_path)
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `.\.venv\Scripts\python -m pytest tests/test_projects.py -v`
Expected: 4 PASS.

- [ ] **Step 7: Commit**

```powershell
git add src/verbatim/db/ tests/test_projects.py
git commit -m "feat: StateManager facade with project seeding and Novel Profile ops"
```

---

### Task 5: Chapter, chunk, and line ops (Shadow Slave port)

Direct port of `SHADOW\src\state_manager.py` chapter/chunk/line/progress methods (lines 240–517 there), adapted to the mixin pattern and `config.from_stored` path resolution.

**Files:**
- Create: `src/verbatim/db/chapters.py`
- Modify: `src/verbatim/db/manager.py`
- Test: `tests/test_chapters.py`

- [ ] **Step 1: Write the failing tests**

`tests/test_chapters.py`:

```python
import pytest

from verbatim.db.manager import StateManager
from tests.test_projects import PARSED


@pytest.fixture
def sm(tmp_path, monkeypatch):
    monkeypatch.setenv("VERBATIM_DATA_DIR", str(tmp_path / "data"))
    return StateManager(tmp_path / "t.db")


@pytest.fixture
def seeded(sm):
    pid = sm.seed_project(PARSED)
    chapters = sm.get_all_chapters(pid)
    return sm, pid, chapters


def test_chunks_roundtrip(seeded):
    sm, pid, chapters = seeded
    chunks = sm.get_chunks_for_chapter(chapters[0]["id"])
    assert chunks[0]["text"] == "Hello world."


def test_status_lifecycle_and_validation(seeded):
    sm, pid, chapters = seeded
    cid = chapters[0]["id"]
    sm.mark_chapter_status(cid, "diarized")
    assert sm.get_chapters_by_status(pid, "diarized")[0]["id"] == cid
    with pytest.raises(ValueError):
        sm.mark_chapter_status(cid, "nonsense")


def test_diarized_lines_roundtrip(seeded):
    sm, pid, chapters = seeded
    cid = chapters[0]["id"]
    sm.save_diarized_lines(cid, [
        {"line_index": 0, "speaker": "Narrator", "text": "Hello", "emotion": "neutral"},
        {"line_index": 1, "speaker": "Anna", "text": "Hi!", "emotion": "happy"},
    ])
    assert sm.get_all_chapters(pid)[0]["status"] == "diarized"
    pending = sm.get_pending_tts_lines(cid)
    assert len(pending) == 2
    sm.mark_line_tts_done(pending[0]["id"], "audio/ch_0000/line_0000.wav")
    assert len(sm.get_pending_tts_lines(cid)) == 1
    sm.mark_line_failed(pending[1]["id"], "boom")
    progress = sm.get_line_progress(cid)
    assert progress == {"total": 2, "pending": 0, "tts_done": 1, "failed": 1, "pct_done": 50.0}


def test_get_progress_counts(seeded):
    sm, pid, chapters = seeded
    sm.mark_chapter_status(chapters[0]["id"], "complete")
    p = sm.get_progress(pid)
    assert p["total"] == 2 and p["complete"] == 1 and p["pct_complete"] == 50.0


def test_reset_chapter_deletes_line_audio(seeded, tmp_path):
    sm, pid, chapters = seeded
    cid = chapters[0]["id"]
    sm.save_diarized_lines(cid, [{"line_index": 0, "speaker": "N", "text": "x", "emotion": "neutral"}])
    line = sm.get_pending_tts_lines(cid)[0]
    from verbatim import config
    wav = config.data_root() / "audio" / "line.wav"
    wav.parent.mkdir(parents=True)
    wav.write_bytes(b"RIFF")
    sm.mark_line_tts_done(line["id"], "audio/line.wav")
    assert sm.reset_chapter_to_pending(cid)
    assert not wav.exists()
    assert sm.get_all_chapters(pid)[0]["status"] == "pending"
    assert sm.get_lines_for_chapter(cid) == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.\.venv\Scripts\python -m pytest tests/test_chapters.py -v`
Expected: FAIL — `AttributeError` (methods missing on StateManager).

- [ ] **Step 3: Write `src/verbatim/db/chapters.py`**

Port from `SHADOW\src\state_manager.py`. Full content:

```python
"""Chapter, chunk, line, and progress operations (mixin for StateManager).

Chapter status lifecycle: pending -> diarized -> tts_done -> assembled -> complete
                                                                       \\-> error
"""

from verbatim import config
from verbatim.db.base import Database, now_iso
from verbatim.db.schema import CHAPTER_STATUSES


class ChapterOps:
    db: Database

    # -- Chapters ----------------------------------------------------------

    def get_all_chapters(self, project_id: int) -> list[dict]:
        with self.db.conn() as conn:
            rows = conn.execute(
                "SELECT * FROM chapters WHERE project_id=? ORDER BY chapter_index",
                (project_id,),
            ).fetchall()
            return [dict(r) for r in rows]

    def get_chapters_by_status(self, project_id: int, status: str) -> list[dict]:
        with self.db.conn() as conn:
            rows = conn.execute(
                "SELECT * FROM chapters WHERE project_id=? AND status=? ORDER BY chapter_index",
                (project_id, status),
            ).fetchall()
            return [dict(r) for r in rows]

    def mark_chapter_status(
        self,
        chapter_id: int,
        status: str,
        audio_path: "str | None" = None,
        error_message: "str | None" = None,
        file_size_bytes: "int | None" = None,
        processing_seconds: "float | None" = None,
    ) -> None:
        if status not in CHAPTER_STATUSES:
            raise ValueError(f"Invalid chapter status: '{status}'. Valid: {CHAPTER_STATUSES}")
        with self.db.conn() as conn:
            conn.execute(
                """UPDATE chapters
                   SET status=?, output_audio_path=COALESCE(?,output_audio_path),
                       output_file_size_bytes=COALESCE(?,output_file_size_bytes),
                       error_message=COALESCE(?,error_message),
                       processing_seconds=COALESCE(?,processing_seconds),
                       updated_at=?
                   WHERE id=?""",
                (status, audio_path, file_size_bytes, error_message,
                 processing_seconds, now_iso(), chapter_id),
            )

    def delete_chapter_audio(self, chapter_id: int) -> bool:
        with self.db.conn() as conn:
            n = conn.execute(
                """UPDATE chapters
                   SET output_audio_path=NULL, output_file_size_bytes=NULL, updated_at=?
                   WHERE id=?""",
                (now_iso(), chapter_id),
            ).rowcount
        return n > 0

    def reset_chapter_to_pending(self, chapter_id: int) -> bool:
        """Reset to pending, deleting all lines and their WAVs for a full re-run."""
        with self.db.conn() as conn:
            line_paths = [
                r["audio_path"] for r in conn.execute(
                    "SELECT audio_path FROM lines WHERE chapter_id=? AND audio_path IS NOT NULL",
                    (chapter_id,),
                ).fetchall()
            ]
            conn.execute("DELETE FROM lines WHERE chapter_id=?", (chapter_id,))
            n = conn.execute(
                """UPDATE chapters
                   SET status='pending', output_audio_path=NULL, output_file_size_bytes=NULL,
                       error_message=NULL, total_lines=0, processing_seconds=NULL, updated_at=?
                   WHERE id=?""",
                (now_iso(), chapter_id),
            ).rowcount
        for stored in line_paths:
            p = config.from_stored(stored)
            try:
                if p.exists():
                    p.unlink()
            except OSError:
                pass  # a locked file must not block the DB reset
        return n > 0

    # -- Chunks --------------------------------------------------------------

    def get_chunks_for_chapter(self, chapter_id: int) -> list[dict]:
        with self.db.conn() as conn:
            rows = conn.execute(
                """SELECT id, chapter_id, chunk_index, text, word_count
                   FROM chunks WHERE chapter_id=? ORDER BY chunk_index""",
                (chapter_id,),
            ).fetchall()
            return [dict(r) for r in rows]

    # -- Lines -----------------------------------------------------------------

    def save_diarized_lines(self, chapter_id: int, lines: list[dict]) -> None:
        with self.db.conn() as conn:
            conn.execute("DELETE FROM lines WHERE chapter_id=?", (chapter_id,))
            conn.executemany(
                """INSERT INTO lines (chapter_id, line_index, speaker, text, emotion)
                   VALUES (?, ?, ?, ?, ?)""",
                [
                    (chapter_id, ln["line_index"], ln["speaker"],
                     ln["text"], ln.get("emotion", "neutral"))
                    for ln in lines
                ],
            )
            conn.execute(
                "UPDATE chapters SET status='diarized', total_lines=?, updated_at=? WHERE id=?",
                (len(lines), now_iso(), chapter_id),
            )

    def get_pending_tts_lines(self, chapter_id: int) -> list[dict]:
        with self.db.conn() as conn:
            rows = conn.execute(
                """SELECT id, chapter_id, line_index, speaker, text, emotion
                   FROM lines WHERE chapter_id=? AND status='pending' ORDER BY line_index""",
                (chapter_id,),
            ).fetchall()
            return [dict(r) for r in rows]

    def get_lines_for_chapter(self, chapter_id: int) -> list[dict]:
        with self.db.conn() as conn:
            rows = conn.execute(
                """SELECT id, line_index, speaker, text, emotion, status, audio_path, error_message
                   FROM lines WHERE chapter_id=? ORDER BY line_index""",
                (chapter_id,),
            ).fetchall()
            return [dict(r) for r in rows]

    def mark_line_tts_done(self, line_id: int, audio_path: str) -> None:
        with self.db.conn() as conn:
            conn.execute(
                "UPDATE lines SET status='tts_done', audio_path=? WHERE id=?",
                (audio_path, line_id),
            )

    def mark_line_failed(self, line_id: int, error: str) -> None:
        with self.db.conn() as conn:
            conn.execute(
                "UPDATE lines SET status='failed', error_message=? WHERE id=?",
                (error, line_id),
            )

    # -- Progress -----------------------------------------------------------

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
            "total": total,
            "pending": counts.get("pending", 0),
            "diarized": counts.get("diarized", 0),
            "tts_done": counts.get("tts_done", 0),
            "assembled": counts.get("assembled", 0),
            "complete": complete,
            "error": counts.get("error", 0),
            "pct_complete": round(complete / total * 100, 1) if total else 0.0,
        }

    def get_line_progress(self, chapter_id: int) -> dict:
        with self.db.conn() as conn:
            rows = conn.execute(
                "SELECT status, COUNT(*) AS cnt FROM lines WHERE chapter_id=? GROUP BY status",
                (chapter_id,),
            ).fetchall()
        counts = {r["status"]: r["cnt"] for r in rows}
        total = sum(counts.values())
        done = counts.get("tts_done", 0)
        return {
            "total": total,
            "pending": counts.get("pending", 0),
            "tts_done": done,
            "failed": counts.get("failed", 0),
            "pct_done": round(done / total * 100, 1) if total else 0.0,
        }
```

- [ ] **Step 4: Add the mixin to the facade**

In `src/verbatim/db/manager.py`, change:

```python
from verbatim.db.chapters import ChapterOps
from verbatim.db.projects import ProjectOps


class StateManager(ProjectOps, ChapterOps):
```

(keep `__init__` unchanged; update the module docstring's Task 5 line to remove "(Task 5)").

- [ ] **Step 5: Run tests to verify they pass**

Run: `.\.venv\Scripts\python -m pytest tests/test_chapters.py tests/test_projects.py -v`
Expected: all PASS.

- [ ] **Step 6: Commit**

```powershell
git add src/verbatim/db/ tests/test_chapters.py
git commit -m "feat: chapter/chunk/line state ops ported from Shadow Slave pipeline"
```

---

### Task 6: Casting ops — characters and the global voice library

New code (no Shadow Slave equivalent — this replaces the hardcoded `SPEAKER_ALIASES`).

**Files:**
- Create: `src/verbatim/db/casting.py`
- Modify: `src/verbatim/db/manager.py`
- Test: `tests/test_casting.py`

- [ ] **Step 1: Write the failing tests**

`tests/test_casting.py`:

```python
import pytest

from verbatim.db.manager import StateManager
from tests.test_projects import PARSED


@pytest.fixture
def sm(tmp_path):
    return StateManager(tmp_path / "t.db")


@pytest.fixture
def pid(sm):
    return sm.seed_project(PARSED)


def test_character_upsert_and_ranking(sm, pid):
    sm.upsert_character(pid, "Sunny", aliases=["Lost From Light"], is_pov=True)
    sm.upsert_character(pid, "Nephis", aliases=["Changing Star"])
    sm.update_character_stats(pid, "Nephis", line_count=50, chapter_count=9)
    sm.update_character_stats(pid, "Sunny", line_count=120, chapter_count=10)
    chars = sm.list_characters(pid)
    assert [c["name"] for c in chars] == ["Sunny", "Nephis"]  # ranked by line_count desc
    assert chars[0]["aliases"] == ["Lost From Light"]
    assert chars[0]["is_pov"] == 1


def test_upsert_updates_existing(sm, pid):
    cid = sm.upsert_character(pid, "Sunny")
    cid2 = sm.upsert_character(pid, "Sunny", aliases=["Shadow"], emotion_hint="dry wit")
    assert cid == cid2
    chars = sm.list_characters(pid)
    assert len(chars) == 1
    assert chars[0]["aliases"] == ["Shadow"]


def test_character_status_validation(sm, pid):
    cid = sm.upsert_character(pid, "Jet")
    sm.set_character_status(cid, "cast")
    with pytest.raises(ValueError):
        sm.set_character_status(cid, "fired")


def test_voice_library_and_casting(sm, pid):
    vid = sm.add_voice("Deep Male", "voices/deep_male.wav", tags=["male", "deep"])
    assert sm.list_voices()[0]["tags"] == ["male", "deep"]
    cid = sm.upsert_character(pid, "Sunny")
    sm.assign_voice(cid, vid)
    chars = sm.list_characters(pid)
    assert chars[0]["voice_id"] == vid
    assert chars[0]["voice_path"] == "voices/deep_male.wav"  # joined for convenience
    assert sm.delete_voice(vid)
    assert sm.list_characters(pid)[0]["voice_id"] is None  # ON DELETE SET NULL


def test_alias_map_resolution(sm, pid):
    sm.upsert_character(pid, "Nephis", aliases=["Changing Star", "Neph"])
    amap = sm.get_alias_map(pid)
    assert amap["nephis"] == amap["changing star"] == amap["neph"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.\.venv\Scripts\python -m pytest tests/test_casting.py -v`
Expected: FAIL — `AttributeError: 'StateManager' object has no attribute 'upsert_character'`.

- [ ] **Step 3: Write `src/verbatim/db/casting.py`**

```python
"""Characters (per project) + global voice library (mixin for StateManager).

This is the data layer that replaces Shadow Slave's hardcoded SPEAKER_ALIASES:
aliases live on character rows; voice clips live in a shared library and are
cast per project via characters.voice_id.
"""

import json

from verbatim.db.base import Database, now_iso
from verbatim.db.schema import CHARACTER_STATUSES


class CastingOps:
    db: Database

    # -- Characters --------------------------------------------------------

    def upsert_character(
        self,
        project_id: int,
        name: str,
        aliases: "list[str] | None" = None,
        emotion_hint: str = "",
        is_pov: bool = False,
        status: str = "suggested",
    ) -> int:
        if status not in CHARACTER_STATUSES:
            raise ValueError(f"Invalid character status: '{status}'. Valid: {CHARACTER_STATUSES}")
        with self.db.conn() as conn:
            conn.execute(
                """INSERT INTO characters
                     (project_id, name, aliases, emotion_hint, is_pov, status, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(project_id, name) DO UPDATE SET
                     aliases=excluded.aliases, emotion_hint=excluded.emotion_hint,
                     is_pov=excluded.is_pov, updated_at=excluded.updated_at""",
                (project_id, name, json.dumps(aliases or []), emotion_hint,
                 int(is_pov), status, now_iso()),
            )
            return int(conn.execute(
                "SELECT id FROM characters WHERE project_id=? AND name=?",
                (project_id, name),
            ).fetchone()["id"])

    def list_characters(self, project_id: int) -> list[dict]:
        """Characters ranked by importance (line_count desc), voice path joined in."""
        with self.db.conn() as conn:
            rows = conn.execute(
                """SELECT c.*, v.path AS voice_path, v.name AS voice_name
                   FROM characters c LEFT JOIN voices v ON v.id = c.voice_id
                   WHERE c.project_id=?
                   ORDER BY c.line_count DESC, c.name""",
                (project_id,),
            ).fetchall()
        chars = []
        for r in rows:
            c = dict(r)
            c["aliases"] = json.loads(c["aliases"])
            chars.append(c)
        return chars

    def set_character_status(self, character_id: int, status: str) -> None:
        if status not in CHARACTER_STATUSES:
            raise ValueError(f"Invalid character status: '{status}'. Valid: {CHARACTER_STATUSES}")
        with self.db.conn() as conn:
            conn.execute(
                "UPDATE characters SET status=?, updated_at=? WHERE id=?",
                (status, now_iso(), character_id),
            )

    def update_character_stats(
        self, project_id: int, name: str, line_count: int, chapter_count: int
    ) -> None:
        with self.db.conn() as conn:
            conn.execute(
                """UPDATE characters SET line_count=?, chapter_count=?, updated_at=?
                   WHERE project_id=? AND name=?""",
                (line_count, chapter_count, now_iso(), project_id, name),
            )

    def assign_voice(self, character_id: int, voice_id: "int | None") -> None:
        with self.db.conn() as conn:
            conn.execute(
                "UPDATE characters SET voice_id=?, updated_at=? WHERE id=?",
                (voice_id, now_iso(), character_id),
            )

    def get_alias_map(self, project_id: int) -> dict[str, int]:
        """{lowercased name-or-alias: character_id} for speaker resolution."""
        amap: dict[str, int] = {}
        for c in self.list_characters(project_id):
            amap[c["name"].lower()] = c["id"]
            for alias in c["aliases"]:
                amap[alias.lower()] = c["id"]
        return amap

    # -- Global voice library -------------------------------------------------

    def add_voice(self, name: str, path: str, tags: "list[str] | None" = None) -> int:
        """Register a voice clip. `path` must be in stored (data-root-relative) form."""
        with self.db.conn() as conn:
            conn.execute(
                """INSERT INTO voices (name, path, tags, updated_at) VALUES (?, ?, ?, ?)
                   ON CONFLICT(name) DO UPDATE SET
                     path=excluded.path, tags=excluded.tags, updated_at=excluded.updated_at""",
                (name, path, json.dumps(tags or []), now_iso()),
            )
            return int(conn.execute(
                "SELECT id FROM voices WHERE name=?", (name,)
            ).fetchone()["id"])

    def list_voices(self) -> list[dict]:
        with self.db.conn() as conn:
            rows = conn.execute("SELECT * FROM voices ORDER BY name").fetchall()
        voices = []
        for r in rows:
            v = dict(r)
            v["tags"] = json.loads(v["tags"])
            voices.append(v)
        return voices

    def delete_voice(self, voice_id: int) -> bool:
        with self.db.conn() as conn:
            return conn.execute("DELETE FROM voices WHERE id=?", (voice_id,)).rowcount > 0
```

- [ ] **Step 4: Add the mixin to the facade**

In `src/verbatim/db/manager.py`:

```python
from verbatim.db.casting import CastingOps
from verbatim.db.chapters import ChapterOps
from verbatim.db.projects import ProjectOps


class StateManager(ProjectOps, ChapterOps, CastingOps):
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.\.venv\Scripts\python -m pytest tests/test_casting.py -v`
Expected: 5 PASS.

- [ ] **Step 6: Commit**

```powershell
git add src/verbatim/db/ tests/test_casting.py
git commit -m "feat: character casting ops + global voice library (replaces SPEAKER_ALIASES)"
```

---

### Task 7: EPUB parser port with cover extraction

Port of `SHADOW\src\epub_parser.py` — logic unchanged (it is already novel-agnostic), plus `extract_cover()` which the Library UI needs.

**Files:**
- Create: `src/verbatim/ingest/__init__.py`
- Create: `src/verbatim/ingest/epub.py`
- Test: `tests/test_epub.py`

- [ ] **Step 1: Write the failing tests** (the fixture builds a real EPUB with ebooklib — proven Shadow Slave test pattern; no network, no GPU)

`tests/test_epub.py`:

```python
import pytest
from ebooklib import epub as eb

from verbatim.ingest.epub import extract_cover, parse_epub


@pytest.fixture
def sample_epub(tmp_path):
    book = eb.EpubBook()
    book.set_identifier("test-id")
    book.set_title("Test Book")
    book.set_language("en")
    book.set_cover("cover.jpg", b"\xff\xd8\xff\xe0FAKEJPEG")

    chapters = []
    for i, (title, body) in enumerate([
        ("Chapter One", "<p>Anna walked in.</p><p>“Hello,” she said.</p>"),
        ("Table of Contents", "<p>1. Chapter One</p>"),
        ("Chapter Two", "<p>The end came quickly. " + "word " * 700 + "</p>"),
    ]):
        ch = eb.EpubHtml(title=title, file_name=f"ch{i}.xhtml", lang="en")
        ch.content = f"<h1>{title}</h1>{body}"
        book.add_item(ch)
        chapters.append(ch)

    book.toc = chapters
    book.add_item(eb.EpubNcx())
    book.add_item(eb.EpubNav())
    book.spine = ["nav", *chapters]
    path = tmp_path / "test.epub"
    eb.write_epub(str(path), book)
    return path


def test_parse_skips_boilerplate_and_indexes_chapters(sample_epub):
    parsed = parse_epub(sample_epub)
    titles = [c.title for c in parsed.chapters]
    assert titles == ["Chapter One", "Chapter Two"]
    assert parsed.total_chapters == 2
    assert parsed.chapters[0].chapter_index == 0
    assert parsed.chapters[1].chapter_index == 1


def test_chunks_respect_word_bounds(sample_epub):
    parsed = parse_epub(sample_epub)
    long_chapter = parsed.chapters[1]
    assert len(long_chapter.chunks) >= 2          # 700+ words must split
    for chunk in long_chapter.chunks:
        assert chunk.word_count <= 650            # CHUNK_MAX_WORDS


def test_parse_missing_file_raises():
    with pytest.raises(FileNotFoundError):
        parse_epub("does/not/exist.epub")


def test_extract_cover(sample_epub, tmp_path):
    out = extract_cover(sample_epub, tmp_path / "covers")
    assert out is not None
    assert out.exists()
    assert out.read_bytes().startswith(b"\xff\xd8")


def test_extract_cover_none_when_absent(tmp_path):
    book = eb.EpubBook()
    book.set_identifier("x")
    book.set_title("No Cover")
    book.set_language("en")
    ch = eb.EpubHtml(title="One", file_name="c.xhtml", lang="en")
    ch.content = "<h1>One</h1><p>text</p>"
    book.add_item(ch)
    book.add_item(eb.EpubNcx())
    book.add_item(eb.EpubNav())
    book.spine = [ch]
    path = tmp_path / "nocover.epub"
    eb.write_epub(str(path), book)
    assert extract_cover(path, tmp_path / "covers") is None
```

- [ ] **Step 2: Install the spaCy model, run tests to verify they fail**

Run:

```powershell
.\.venv\Scripts\python -m spacy download en_core_web_sm
.\.venv\Scripts\python -m pytest tests/test_epub.py -v
```

Expected: FAIL — `ModuleNotFoundError: verbatim.ingest`.

- [ ] **Step 3: Write the implementation**

`src/verbatim/ingest/__init__.py`: empty file.

`src/verbatim/ingest/epub.py` — copy `SHADOW\src\epub_parser.py` verbatim, then apply exactly these changes:

1. Remove the CLI block at the bottom (`if __name__ == "__main__":` and below) and the `import sys`.
2. Replace `print(...)` calls with module-level `logging`: add `import logging` and `log = logging.getLogger(__name__)` near the imports; change each `print(f"[parser] ...")` to `log.info("...")` with the same message minus the `[parser] ` prefix.
3. Update the module docstring first line to `"""EPUB parser + text chunker (M1)."""` (keep the JSON contract documentation).
4. Append this new function at the end of the file:

```python
def extract_cover(epub_path: "str | Path", out_dir: "str | Path") -> "Path | None":
    """Extract the cover image to out_dir. Returns the written path, or None if no cover."""
    epub_path = Path(epub_path)
    if not epub_path.exists():
        raise FileNotFoundError(f"EPUB not found: {epub_path}")
    book = epub.read_epub(str(epub_path))

    cover_item = next(iter(book.get_items_of_type(ebooklib.ITEM_COVER)), None)
    if cover_item is None:
        # Fallback: some EPUBs mark the cover as a plain image named "cover"
        cover_item = next(
            (i for i in book.get_items_of_type(ebooklib.ITEM_IMAGE)
             if "cover" in i.get_name().lower()),
            None,
        )
    if cover_item is None:
        return None

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    suffix = Path(cover_item.get_name()).suffix or ".jpg"
    out_path = out_dir / f"{epub_path.stem}{suffix}"
    out_path.write_bytes(cover_item.get_content())
    return out_path
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.\.venv\Scripts\python -m pytest tests/test_epub.py -v`
Expected: 5 PASS.

- [ ] **Step 5: Commit**

```powershell
git add src/verbatim/ingest/ tests/test_epub.py
git commit -m "feat: EPUB parser port with cover extraction"
```

---

### Task 8: Profile-driven segmenter port

Port of `SHADOW\src\segmenter.py`. The two Shadow-Slave-specific behaviours become opt-in flags sourced from the Novel Profile: `single_quote_thoughts` (profile `thought_convention == 'single_quotes'`) and `bracket_system_lines` (profile `system_brackets`).

**Files:**
- Create: `src/verbatim/ingest/segmenter.py`
- Test: `tests/test_segmenter.py`

- [ ] **Step 1: Write the failing tests**

`tests/test_segmenter.py`:

```python
from verbatim.ingest.segmenter import SegmenterConfig, segment_chunk

DEFAULT = SegmenterConfig()
SHADOW_LIKE = SegmenterConfig(single_quote_thoughts=True, bracket_system_lines=True)


def kinds(segs):
    return [s["kind"] for s in segs]


def texts(segs):
    return [s["text"] for s in segs]


def test_dialogue_split_always_on():
    segs = segment_chunk('Anna smiled. "Hello there." She left.', DEFAULT)
    assert kinds(segs) == ["prose", "dialogue", "prose"]
    assert texts(segs) == ["Anna smiled.", "Hello there.", "She left."]


def test_unbalanced_quote_falls_back_to_prose():
    segs = segment_chunk('He said "never mind.', DEFAULT)
    assert kinds(segs) == ["prose"]


def test_thoughts_off_by_default():
    segs = segment_chunk("'Why me?' Sunny wondered.", DEFAULT)
    assert kinds(segs) == ["prose"]


def test_thoughts_on_with_profile_flag():
    segs = segment_chunk("'Why me?' Sunny wondered.", SHADOW_LIKE)
    assert kinds(segs) == ["thought", "prose"]
    assert texts(segs)[0] == "Why me?"


def test_contractions_never_trigger_thoughts():
    segs = segment_chunk("It was Sunny's turn, and he won't run.", SHADOW_LIKE)
    assert kinds(segs) == ["prose"]


def test_system_brackets_off_by_default():
    segs = segment_chunk("[Quest Complete]", DEFAULT)
    assert kinds(segs) == ["prose"]


def test_system_brackets_on_with_profile_flag():
    segs = segment_chunk("[Quest Complete] [Reward: Shadow Essence]", SHADOW_LIKE)
    assert kinds(segs) == ["system", "system"]
    assert texts(segs) == ["[Quest Complete]", "[Reward: Shadow Essence]"]


def test_indices_are_sequential():
    segs = segment_chunk('A. "B." C.\n\n"D."', DEFAULT)
    assert [s["index"] for s in segs] == list(range(len(segs)))


def test_empty_input():
    assert segment_chunk("", DEFAULT) == []
    assert segment_chunk(None, DEFAULT) == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.\.venv\Scripts\python -m pytest tests/test_segmenter.py -v`
Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 3: Write the implementation**

`src/verbatim/ingest/segmenter.py` — copy `SHADOW\src\segmenter.py` verbatim, then apply exactly these changes:

1. Replace the module docstring with:

```python
"""Deterministic text segmenter (pass 1 of the two-pass diarizer).

Splits chunk text into ordered segments BEFORE the LLM sees it, so the LLM
only labels segments (speaker + emotion) and never reproduces text. Word loss
is structurally impossible: every character of input lands in exactly one
segment, in order.

Segment kinds:
  dialogue -- a double-quoted span (straight or curly), outer quotes stripped.
              Always detected.
  thought  -- a 'single-quoted' inner-monologue span. Only when the project's
              Novel Profile sets thought_convention='single_quotes'.
  system   -- a [bracketed] notification paragraph (LitRPG system messages).
              Only when the profile sets system_brackets.
  prose    -- everything else: narration, actions, attribution tails.

Robustness rules:
  * A paragraph with an unbalanced double quote falls back to one prose
    segment -- never guess at span boundaries.
  * Thought spans tolerate internal contractions (I'll, won't, Sunny's).
"""
```

2. Add after the imports (`import re` stays):

```python
from dataclasses import dataclass


@dataclass(frozen=True)
class SegmenterConfig:
    """Derived from the project's Novel Profile."""
    single_quote_thoughts: bool = False
    bracket_system_lines: bool = False
```

3. Change the `segment_chunk` signature and paragraph loop to honour the config. Replace the whole `segment_chunk` function with:

```python
def segment_chunk(text: "str | None", config: SegmenterConfig) -> "list[dict]":
    """Split chunk text into ordered segments for LLM labeling.

    Returns [{"index": int, "kind": str, "text": str}]. Paragraphs are
    '\\n\\n'-separated (epub parser contract). Empty input yields [].
    """
    segments: list[dict] = []

    def add(kind: str, seg_text: str) -> None:
        segments.append({"index": len(segments), "kind": kind, "text": seg_text})

    for para in re.split(r"\n\s*\n", text or ""):
        para = para.strip()
        if not para:
            continue

        if config.bracket_system_lines and _SYSTEM_PARA_RE.match(para):
            for span in _BRACKET_SPAN_RE.findall(para):
                add(KIND_SYSTEM, span)
            continue

        for kind, part_text in _split_quoted_paragraph(para):
            if kind == KIND_PROSE and config.single_quote_thoughts:
                for sub_kind, sub_text in _split_thought_parts(part_text):
                    add(sub_kind, sub_text)
            else:
                add(kind, part_text)

    return segments
```

Everything else (`_QUOTE_PAIRS`, `_SYSTEM_PARA_RE`, `_BRACKET_SPAN_RE`, `_THOUGHT_SPAN_RE`, `KIND_*`, `_split_quoted_paragraph`, `_split_thought_parts`) is copied unchanged from SHADOW.

- [ ] **Step 4: Run tests to verify they pass**

Run: `.\.venv\Scripts\python -m pytest tests/test_segmenter.py -v`
Expected: 9 PASS.

- [ ] **Step 5: Commit**

```powershell
git add src/verbatim/ingest/segmenter.py tests/test_segmenter.py
git commit -m "feat: profile-driven segmenter - thought/system detection now opt-in flags"
```

---

### Task 9: Lint, typecheck, CI workflow

**Files:**
- Create: `.github/workflows/ci.yml`

- [ ] **Step 1: Run ruff and mypy locally; fix anything they flag**

Run:

```powershell
.\.venv\Scripts\python -m ruff check .
.\.venv\Scripts\python -m mypy src
```

Expected: both clean. If ruff flags import order or mypy flags a missing annotation, fix it in place (these are mechanical fixes — the plan's code is annotated, but ports may carry minor issues).

- [ ] **Step 2: Create `.github/workflows/ci.yml`**

```yaml
name: CI

on:
  push:
    branches: [master, main]
  pull_request:

jobs:
  backend:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
          cache: pip
      - name: Install
        run: |
          pip install -e ".[dev]"
          python -m spacy download en_core_web_sm
      - name: Lint
        run: ruff check .
      - name: Typecheck
        run: mypy src
      - name: Test
        run: pytest -v
```

(The UI job is added in Phase 5 when `ui/` exists.)

- [ ] **Step 3: Run the full suite one last time**

Run: `.\.venv\Scripts\python -m pytest -v`
Expected: all tests from Tasks 2–8 PASS (≈30 tests).

- [ ] **Step 4: Commit**

```powershell
git add .github/ ; git add -A
git commit -m "ci: backend workflow - ruff, mypy, pytest"
```

---

## Self-review notes

- **Spec coverage (Phase 1 scope):** data model with profile fields/characters/voices ✅ (Tasks 3–6); relative-path discipline ✅ (Task 2, used in Task 5 reset); module-split rule ✅ (mixin decomposition, every file well under 500 lines); EPUB-only ingest + cover for Library UI ✅ (Task 7); profile-driven segmenter generalization ✅ (Task 8); CI/typed/MIT/.env.example portfolio polish ✅ (Tasks 1, 9). Casting Director LLM, diarizer, TTS, M4B, API, UI are explicitly later phases.
- **Type consistency check:** `StateManager(db_path)` constructor used in all test fixtures; mixins reference `self.db: Database` consistently; `from_stored`/`to_stored` names match between Task 2 and Task 5; `SegmenterConfig` field names match between Task 8 steps.
- **Voice paths:** `add_voice` documents that callers pass stored-form paths; the API layer (Phase 4) will call `config.to_stored` at the upload boundary.
