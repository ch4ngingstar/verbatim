# Verbatim — Design Specification

**Date:** 2026-06-13
**Status:** Approved (brainstorm completed in prior session; this document is the canonical spec)
**Origin:** Generalization of the Shadow Slave audiobook pipeline (`shaodw salve` repo) into a portfolio-grade, any-novel tool.

## 1. What Verbatim is

A self-hosted web app that turns **any novel EPUB** into a **multi-voice audiobook** — per-character voices, per-line emotional delivery — running entirely on a local GPU. No cloud services, no API keys for synthesis.

It is a CV/portfolio project: the quality bar is "professional, modern, the best it can be." Repo name: `verbatim`. License: MIT. Public on GitHub.

### Non-goals (explicitly refused scope)

- Multi-user / auth / hosting for others
- Cloud TTS backends
- Web scraping or txt ingestion — **EPUB only**
- Streaming synthesis (chapters are batch-rendered)

## 2. Core architectural idea: the Novel Profile

The Shadow Slave pipeline works because of hardcoded knowledge: a cast list, `SPEAKER_ALIASES`, emotion hints, the POV character (Sunny), and the convention that 'single quotes' mark inner monologue. **Verbatim replaces every piece of that hardcoded knowledge with a per-project Novel Profile stored in SQLite.**

Profile contents:

- POV style (first/third person, single/multi POV) and POV character(s)
- Thought-quote convention (e.g. 'single quotes' = inner monologue, *italics* = thoughts, none)
- Narrator notes (free text fed to the diarizer prompt)
- The cast: characters with canonical names, aliases, emotion hints, importance stats, and voice assignments

## 3. Pipeline (modules)

```
EPUB parse → Casting Director (NEW) → [user review] → per chapter:
    diarize (LLM, profile-driven) → TTS (IndexTTS2, emotion vector) → assemble (FFmpeg)
→ M4B export with chapter markers
```

Same VRAM-juggle orchestration as Shadow Slave (~12 GB constraint): LLM and TTS are never resident simultaneously; context managers + nvidia-smi barrier between stages.

### 3.1 Casting Director (new stage)

After EPUB parse, before any synthesis:

1. LLM reads the first ~10 chapters.
2. Produces a draft Novel Profile: characters **ranked by importance** (line count, chapter spread), suggested aliases, POV detection, thought-convention detection.
3. User reviews in the Casting Studio UI: merge duplicates, rename, ignore, assign voices.

Auto-discover + user edit was chosen over fully-auto and fully-manual.

### 3.2 Cast review checkpoints (every ~25 chapters)

- Pure SQL over diarization stats already collected — **no extra LLM passes**.
- Batched digest card pushed via SSE: e.g. "Jet is now the 4th most active speaker (34 lines across 12 chapters) — add to cast?"
- Accept → pick a voice → one-click re-render of affected chapters (reuses the DELETE audio + redo machinery).
- **Advisory and non-blocking**: the pipeline never stalls waiting for the user. Uncast speakers fall back to `_default`.

### 3.3 Diarizer

Port diarizer v2 (two-pass, label-only, grammar-locked) unchanged in design. Changes:

- Prompt becomes a **template with profile fill-ins** (cast list, aliases, POV character, thought convention, narrator notes).
- The Sunny inner-monologue guard generalizes to a **POV-character guard** driven by the profile.
- `SPEAKER_ALIASES` constant dies; aliases load from `characters.aliases` per project.

### 3.4 TTS

IndexTTS2 zero-shot cloning with the 8-dim emotion vector per line (`[happy, angry, sad, afraid, disgust, melancholic, surprised, calm]`), as proven in Shadow Slave. One clean neutral clip per character suffices.

### 3.5 Output

- Per-chapter MP3s (as today), plus
- **M4B export with chapter markers** via FFmpeg (v1 feature — top value/effort ratio for an audiobook tool).

## 4. Data model

- `projects` — one per novel; embeds profile fields (POV style, thought convention, narrator notes).
- `characters` — project_id, canonical name, aliases (JSON), emotion hint, POV flag, importance stats, status (`cast` / `suggested` / `ignored`), voice assignment.
- `voices` — **global library** shared across projects: name, file path, tags. Upload once, cast in any project. Voice paths stored **relative to the configured data/ root** (CWD-independence; this was a real bug scar in Shadow Slave).
- Chapters/lines tables ported from Shadow Slave state manager (status lifecycle `pending → diarized → tts_done → assembled → complete`, error stage tracking, resume logic).

## 5. Tech stack (unchanged from Shadow Slave)

- **Backend:** Python 3.11, FastAPI, SQLite, llama-cpp-python (Qwen3-14B Q4_K_M GGUF), IndexTTS2 in-process, FFmpeg.
- **Frontend:** Next.js 15, React 19, TypeScript, Tailwind CSS. Zen-Tech dark theme carried over.
- **Strategy:** copy proven modules from the Shadow Slave repo (segmenter, tts engine, assembler, state_manager, orchestrator, UI components) and rewrite the novel-specific parts as profile-driven. Fresh git history; Shadow Slave repo stays untouched.

### Module split requirement

Oversized Shadow Slave modules are split during the port:

- `tts_engine.py` → `tts/engine.py` + `tts/voices.py` + `tts/emotion.py`
- `llm_director.py` → equivalent split (prompting / parsing / orchestration)
- All files stay under 500 lines.

### Engine adapter seam (v1)

Thin `TTSAdapter` and `DiarizerLLM` interfaces with a single implementation each (IndexTTS2, llama-cpp). Not pluggability theater — just a seam so the portfolio README can honestly say "engine-agnostic core."

## 6. UI — three views (Zen-Tech dark theme)

1. **Library** — project cards with EPUB cover art and progress rings; create project = upload EPUB.
2. **Casting Studio** — ranked cast list, alias chips, voice library sidebar, **voice preview ▶** (synthesizes one real line of that character's dialogue with the candidate voice), digest cards from checkpoints.
3. **Command Deck** — ported pipeline monitor (status cards, chapter strip mini-map, SSE live events).

## 7. v1 feature list

1. Novel Profile architecture + Casting Director + Casting Studio UI
2. Cast review checkpoints (advisory, SQL-only)
3. Global voice library + per-project casting + voice preview
4. Profile-driven diarizer v2 port
5. IndexTTS2 synthesis with emotion vectors
6. M4B export with chapter markers
7. TTSAdapter / DiarizerLLM seams
8. Command Deck pipeline monitor

### v1.1 roadmap headliner (NOT v1)

Built-in player with karaoke-style synced transcript (per-line highlight + speaker avatar).

## 8. Portfolio polish requirements

- GitHub Actions CI: `ruff` + `mypy` + `pytest` (backend); `tsc --noEmit` + `vitest` (UI)
- Typed Python throughout
- GPU-free tests: monkeypatch `_call_llm` / `_synthesize` (proven Shadow Slave pattern)
- README: architecture diagram, casting-UI GIF, audio demo, honest "12 GB VRAM, sequential model juggling" note
- MIT license, `.env.example`, no absolute paths anywhere

## 9. Hard constraints (inherited)

1. ~12 GB VRAM → LLM and TTS strictly sequential, barrier-enforced
2. Iterative generation: chapters resumable at any stage; redo machinery per chapter
3. All inter-module state flows through the state manager (SQLite) — no module-to-module reads
4. Pipeline must keep working with zero user interaction after casting (checkpoints advisory)
