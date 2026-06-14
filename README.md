# Verbatim

Turn any novel EPUB into a multi-voice audiobook with per-character voices and per-line emotion — running entirely on a local GPU (~12 GB VRAM).

## How it works

```
EPUB parse → Casting Director (LLM) → [user review in UI] →
  per chapter: diarize (LLM) → TTS (IndexTTS) → assemble (FFmpeg) → M4B
```

A local LLM reads the first few chapters to draft a **Novel Profile** — who the POV characters are, what thought convention the author uses, whether system brackets mean LitRPG status windows. You review and edit the cast in a browser UI, assign reference voice clips, then kick off the pipeline. Each line is synthesised with a per-character voice and an 8-dimensional emotion vector blended from the text. Chapters are assembled into MP3s and packaged into a single M4B with chapter markers.

The LLM and TTS model are never loaded at the same time. Each is a context manager that loads on entry and explicitly frees VRAM on exit.

## Requirements

- Python 3.11+
- Node.js 18+
- FFmpeg on PATH
- NVIDIA GPU with ~12 GB VRAM
- [IndexTTS](https://github.com/index-labs/IndexTTS) checkpoints
- A GGUF-format LLM (e.g. Mistral 7B, Llama 3 8B) for diarization and casting

## Installation

```powershell
# 1. Clone
git clone https://github.com/ch4ngingstar/verbatim.git
cd verbatim

# 2. Backend
python -m venv .venv
.\.venv\Scripts\pip install -e ".[dev]"
python -m spacy download en_core_web_sm

# 3. Frontend
cd ui
npm install
cd ..
```

Place IndexTTS checkpoints under `index-tts/checkpoints/` (the directory should contain `config.yaml`).

## Quick start

```powershell
.\start.ps1
```

This creates `.env` and `ui/.env.local` on first run, starts the backend on port 8000 and the frontend on port 3000, and opens the browser automatically.

Or start each server manually:

```powershell
# Backend
cd src
uvicorn verbatim.api.app:app --port 8000 --reload

# Frontend (separate terminal)
cd ui
npm run dev
```

## Configuration

Copy `.env.example` to `.env`. The only required variables are:

| Variable | Default | Description |
|---|---|---|
| `VERBATIM_DATA_DIR` | `./data` | Where the SQLite DB, audio files, voice clips, and covers are stored |
| `NEXT_PUBLIC_API_URL` | `http://localhost:8000` | Backend URL (must also go in `ui/.env.local`) |

All file paths stored in the database are relative to `VERBATIM_DATA_DIR`, so the data directory is portable.

## Usage

1. Open `http://localhost:3000`
2. Upload an EPUB — the book is parsed and appears in the library
3. Click the project → **Casting Studio** tab
4. Click **Analyze** to run the Casting Director (LLM) on the first few chapters
5. Review the Novel Profile and character list, assign voice clips from the library
6. Switch to the **Command Deck** tab, provide your model paths, and click **Start**
7. Watch progress live via SSE; download the finished M4B when complete

## Development

```powershell
# Run all tests (124, GPU-free)
.\.venv\Scripts\python -m pytest -v

# Lint + typecheck
.\.venv\Scripts\python -m ruff check .
.\.venv\Scripts\python -m mypy src

# Frontend type check + tests
cd ui
npm run typecheck
npm test
```

Tests monkeypatch `_call_llm` on the LLM director and `_synthesize` on the TTS engine so no GPU or model files are needed.

## API

The FastAPI backend exposes a REST API at `http://localhost:8000`:

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/health` | Health check |
| `POST` | `/api/projects` | Upload EPUB, create project |
| `GET` | `/api/projects` | List all projects |
| `GET` | `/api/projects/{id}` | Project detail + progress |
| `PATCH` | `/api/projects/{id}/profile` | Update Novel Profile |
| `POST` | `/api/projects/{id}/analyze` | Run Casting Director |
| `POST` | `/api/pipeline/start` | Start the pipeline |
| `POST` | `/api/pipeline/pause` | Pause after current chapter |
| `POST` | `/api/pipeline/resume` | Resume |
| `POST` | `/api/pipeline/stop` | Stop after current chapter |
| `GET` | `/api/pipeline/status` | Current pipeline state |
| `GET` | `/api/chapters/{project_id}` | Chapter list |
| `POST` | `/api/chapters/{id}/reset` | Reset chapter to pending |
| `GET` | `/api/characters/{project_id}` | Character list |
| `POST` | `/api/characters/{project_id}` | Upsert character |
| `PATCH` | `/api/characters/{id}/voice` | Assign voice to character |
| `GET` | `/api/voices` | Voice library |
| `POST` | `/api/voices/upload` | Upload reference clip |
| `DELETE` | `/api/voices/{id}` | Remove voice |
| `GET` | `/api/audio/{chapter_id}` | Stream chapter MP3 |
| `POST` | `/api/export/m4b` | Export full M4B |
| `GET` | `/api/events` | SSE progress stream |

Interactive docs: `http://localhost:8000/docs`

## Project structure

```
src/verbatim/
  db/          SQLite schema + StateManager facade
  ingest/      EPUB parser, cover extraction, segmenter
  llm/         LLMDirector context manager, prompt templates
  casting/     CastingDirector — drafts Novel Profile from first N chapters
  tts/         TTSEngine, emotion vectors, voice map builder
  audio/       FFmpeg chapter assembler, M4B exporter
  pipeline/    Orchestrator — sequences stages, emits SSE events
  api/         FastAPI routes, Pydantic models, pipeline thread wrapper
ui/
  app/         Next.js pages (library, project/casting/command deck)
  components/  CastingStudio, ChapterQueue, CommandStrip, Toasts
  lib/         api.ts (sole API client), types.ts
```

## License

MIT
