# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this project is

Verbatim converts any novel EPUB into a multi-voice audiobook with per-character voices and per-line emotion, running entirely on a local GPU (~12 GB VRAM). It is a portfolio project; quality bar is professional.

## Commands

### Backend

```powershell
# Install (from repo root)
.\.venv\Scripts\pip install -e ".[dev]"
python -m spacy download en_core_web_sm

# Run all tests
.\.venv\Scripts\python -m pytest -v

# Run a single test file or test
.\.venv\Scripts\python -m pytest tests/test_api.py -v
.\.venv\Scripts\python -m pytest tests/test_projects.py::test_update_profile -v

# Lint + typecheck
.\.venv\Scripts\python -m ruff check .
.\.venv\Scripts\python -m mypy src

# Start backend server
cd src && uvicorn verbatim.api.app:app --port 8000 --reload
```

### Frontend (ui/)

```powershell
cd ui
npm install
npm run dev          # Next.js dev server at localhost:3000
npm run typecheck    # tsc --noEmit
npm test             # vitest run
```

### Start both together

```powershell
.\start.ps1          # opens two terminal windows
# Backend:  http://localhost:8000/api/health
# Frontend: http://localhost:3000
```

### Environment

Copy `.env.example` to `.env`. The `NEXT_PUBLIC_API_URL` line must also go in `ui/.env.local` — Next.js only reads files from its own directory.

`VERBATIM_DATA_DIR` controls where all runtime data lives (SQLite DB, audio files, voice clips, cover images). All paths stored in the DB are relative to this root — never absolute.

## Architecture

### Pipeline flow

```
EPUB parse → Casting Director (LLM) → [user review in UI] →
  per chapter: diarize (LLM) → TTS (IndexTTS2) → assemble (FFmpeg) → M4B
```

### VRAM constraint (critical)

The machine has ~12 GB VRAM. LLMDirector and TTSEngine are **never loaded simultaneously**. Each is a context manager: model loads in `__enter__`, explicitly `gc.collect()`'d and cache-cleared in `__exit__`. The orchestrator inserts an nvidia-smi barrier between the two stages. Any new GPU-using code must follow this same pattern.

### The Novel Profile

The central design idea. Every novel-specific constant that would otherwise be hardcoded is instead a per-project profile stored in `projects` DB rows:
- `pov_style` / `pov_characters` — who speaks inner thoughts
- `thought_convention` — `'single_quotes'` or `none`
- `system_brackets` — whether `[brackets]` are LitRPG system lines
- `narrator_notes` — free text fed to the diarizer prompt

The Casting Director (LLM, first N chapters) drafts the profile; the user edits it in Casting Studio before pipeline starts.

### StateManager

`src/verbatim/db/manager.py` is a single facade composed from three mixin classes:
- `ProjectOps` (`db/projects.py`) — projects, Novel Profile CRUD
- `ChapterOps` (`db/chapters.py`) — chapters, chunks, lines, progress, reset-to-pending
- `CastingOps` (`db/casting.py`) — characters per project + global voice library

All pipeline modules receive a `StateManager` instance. No module reads another module's files directly — all inter-module state flows through the DB.

### Path discipline

`config.py` provides `data_root()`, `to_stored(path)`, `from_stored(stored)`. Every file path that goes into the DB must pass through `to_stored()` first (produces posix-slash, data-root-relative strings). Retrieving it uses `from_stored()`. Violating this was a recurring bug in the predecessor project.

### Backend (`src/verbatim/`)

| Package | Purpose |
|---------|---------|
| `db/` | SQLite schema + StateManager facade |
| `ingest/` | `epub.py` (parser + cover extraction), `segmenter.py` (deterministic segment splitter) |
| `llm/` | `parsing.py` (stateless utilities), `prompts.py` (template builder), `director.py` (LLMDirector context manager) |
| `casting/` | `director.py` (CastingDirector — profile draft from first N chapters) |
| `tts/` | `engine.py` (TTSEngine), `emotion.py` (8-dim emotion vector), `voices.py` (voice map builder) |
| `audio/` | `assembler.py` (FFmpeg per-chapter MP3), `m4b.py` (full M4B with chapter markers) |
| `pipeline/` | `orchestrator.py` (sequences stages, emits SSE events, handles resume logic) |
| `api/` | `app.py` (FastAPI routes), `models.py` (Pydantic request/response models), `pipeline_manager.py` (singleton thread wrapper) |

### Frontend (`ui/`)

Next.js 15 / React 19 / TypeScript / Tailwind. Three views:
- `/` — **Library**: project cards, EPUB upload to create a project
- `/projects/[id]` — **Casting Studio** + **Command Deck** on the same page; tabs or sections for the cast list, voice library sidebar, and pipeline monitor
- SSE stream (`/api/events`) feeds live pipeline progress into the Command Deck

`ui/lib/api.ts` is the sole API client; `ui/lib/types.ts` holds shared TypeScript types. Components in `ui/components/`: `CastingStudio.tsx`, `ChapterQueue.tsx`, `CommandStrip.tsx`, `Toasts.tsx`.

### GPU-free testing

`llama_cpp` and IndexTTS2 are import-guarded (`try/except ImportError`). Tests monkeypatch `_call_llm` on LLMDirector / CastingDirector and `_synthesize` on TTSEngine. The `wav_silence(ms)` helper in `tts/emotion.py` produces minimal valid WAV bytes for audio path tests without any synthesis.

### Chapter status lifecycle

`pending → diarized → tts_done → assembled → complete` (+ `error`). The orchestrator's resume logic inspects the current status and skips already-completed stages. `reset_chapter_to_pending()` deletes line rows and their WAV files on disk before resetting.
