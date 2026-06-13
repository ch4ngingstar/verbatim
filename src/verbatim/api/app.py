"""Verbatim FastAPI backend.

Run:
    uvicorn verbatim.api.app:app --port 8000 --reload

Endpoints:
  GET  /api/health
  POST /api/projects                          create project (parse EPUB)
  GET  /api/projects                          list all projects
  GET  /api/projects/{project_id}             project detail + progress
  PATCH /api/projects/{project_id}/profile    update Novel Profile
  POST /api/pipeline/start                    start pipeline
  POST /api/pipeline/pause                    pause between chapters
  POST /api/pipeline/resume                   resume after pause
  POST /api/pipeline/stop                     stop after current chapter
  GET  /api/pipeline/status                   current status + last event
  GET  /api/chapters/{project_id}             chapter list
  POST /api/chapters/{chapter_id}/reset       reset to pending
  GET  /api/characters/{project_id}           character list
  POST /api/characters/{project_id}           upsert a character
  PATCH /api/characters/{character_id}/voice  assign a library voice
  GET  /api/voices                            voice library list
  POST /api/voices                            add voice (path)
  POST /api/voices/upload                     add voice (file upload)
  DELETE /api/voices/{voice_id}               remove voice from library
  GET  /api/voices/{voice_id}/audio           stream reference clip
  GET  /api/audio/{chapter_id}                stream chapter MP3
  POST /api/export/m4b                        export full M4B
  GET  /api/events                            SSE progress stream
"""

import asyncio
import json
import re
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse

from verbatim import config
from verbatim.api.models import (
    CharacterUpsert,
    CharacterVoiceAssign,
    M4BExportRequest,
    NovelProfileUpdate,
    PipelineStart,
    ProjectCreate,
    VoiceAdd,
)
from verbatim.api.pipeline_manager import PipelineManager
from verbatim.db.manager import StateManager
from verbatim.ingest.epub import parse_epub
from verbatim.pipeline.orchestrator import OrchestratorConfig


# Use callables so that VERBATIM_DATA_DIR changes (e.g. in tests) are honoured.
def _voices_dir() -> Path:
    return config.data_root() / "voices"


def _mp3_dir() -> Path:
    return config.data_root() / "output"


def _m4b_dir() -> Path:
    return config.data_root() / "m4b"
_ALLOWED_VOICE_EXTS = {".wav", ".mp3", ".flac", ".ogg"}
_VOICE_MEDIA_TYPES = {
    ".wav": "audio/wav",
    ".mp3": "audio/mpeg",
    ".flac": "audio/flac",
    ".ogg": "audio/ogg",
}


@asynccontextmanager
async def lifespan(app: FastAPI) -> Any:
    db_path = config.data_root() / "verbatim.db"
    app.state.sm = StateManager(db_path)
    app.state.manager = PipelineManager()
    app.state.manager.set_loop(asyncio.get_running_loop())
    yield


app = FastAPI(title="Verbatim Audiobook Pipeline", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# -- Dependencies -------------------------------------------------------------

def get_sm() -> StateManager:
    return app.state.sm  # type: ignore[no-any-return]


def get_manager() -> PipelineManager:
    return app.state.manager  # type: ignore[no-any-return]


# -- Health -------------------------------------------------------------------

@app.get("/api/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


# -- Projects -----------------------------------------------------------------

@app.post("/api/projects", status_code=201)
async def create_project(
    req: ProjectCreate,
    sm: StateManager = Depends(get_sm),
) -> dict[str, Any]:
    epub_path = Path(req.epub_path)
    if not epub_path.exists():
        raise HTTPException(400, f"EPUB not found: {req.epub_path}")

    parsed = await asyncio.to_thread(parse_epub, req.epub_path)
    project_id = sm.seed_project(parsed)
    project = sm.get_project_by_id(project_id)
    return {"project_id": project_id, "project": project,
            "progress": sm.get_progress(project_id)}


@app.get("/api/projects")
async def list_projects(sm: StateManager = Depends(get_sm)) -> dict[str, Any]:
    projects = sm.list_projects()
    for p in projects:
        p["progress"] = sm.get_progress(p["id"])
    return {"projects": projects}


@app.get("/api/projects/{project_id}")
async def get_project(
    project_id: int,
    sm: StateManager = Depends(get_sm),
) -> dict[str, Any]:
    project = sm.get_project_by_id(project_id)
    if not project:
        raise HTTPException(404, f"Project {project_id} not found.")
    return {"project": project, "progress": sm.get_progress(project_id)}


@app.patch("/api/projects/{project_id}/profile")
async def update_novel_profile(
    project_id: int,
    req: NovelProfileUpdate,
    sm: StateManager = Depends(get_sm),
) -> dict[str, Any]:
    updates = req.model_dump(exclude_none=True)
    if not updates:
        raise HTTPException(400, "No fields provided to update.")
    sm.update_profile(project_id, **updates)
    project = sm.get_project_by_id(project_id)
    if not project:
        raise HTTPException(404, f"Project {project_id} not found.")
    return {"project": project}


# -- Pipeline -----------------------------------------------------------------

@app.post("/api/pipeline/start")
async def start_pipeline(
    req: PipelineStart,
    sm: StateManager = Depends(get_sm),
    mgr: PipelineManager = Depends(get_manager),
) -> dict[str, Any]:
    project = sm.get_project_by_id(req.project_id)
    if not project:
        raise HTTPException(404, f"Project {req.project_id} not found.")

    cfg = OrchestratorConfig(
        llm_model_path=req.llm_model_path,
        tts_model_dir=req.tts_model_dir,
        wav_output_dir=str(config.data_root() / "audio"),
        mp3_output_dir=str(_mp3_dir()),
        llm_n_gpu_layers=req.llm_n_gpu_layers,
        tts_num_beams=req.tts_num_beams,
        vram_check_enabled=req.vram_check_enabled,
        chapter_range=tuple(req.chapter_range) if req.chapter_range else None,
    )
    try:
        mgr.start(req.project_id, sm, cfg)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return {"status": "started", "project_id": req.project_id}


@app.post("/api/pipeline/pause")
async def pause_pipeline(mgr: PipelineManager = Depends(get_manager)) -> dict[str, str]:
    mgr.pause()
    return {"status": mgr.status}


@app.post("/api/pipeline/resume")
async def resume_pipeline(mgr: PipelineManager = Depends(get_manager)) -> dict[str, str]:
    mgr.resume()
    return {"status": mgr.status}


@app.post("/api/pipeline/stop")
async def stop_pipeline(mgr: PipelineManager = Depends(get_manager)) -> dict[str, str]:
    mgr.stop()
    return {"status": mgr.status}


@app.get("/api/pipeline/status")
async def pipeline_status(mgr: PipelineManager = Depends(get_manager)) -> dict[str, Any]:
    return mgr.get_status()


# -- Chapters -----------------------------------------------------------------

@app.get("/api/chapters/{project_id}")
async def list_chapters(
    project_id: int,
    sm: StateManager = Depends(get_sm),
) -> dict[str, Any]:
    chapters = sm.get_all_chapters(project_id)
    return {"chapters": chapters, "total": len(chapters)}


@app.post("/api/chapters/{chapter_id}/reset")
async def reset_chapter(
    chapter_id: int,
    sm: StateManager = Depends(get_sm),
) -> dict[str, Any]:
    with sm.db.conn() as conn:
        row = conn.execute(
            "SELECT output_audio_path FROM chapters WHERE id=?", (chapter_id,)
        ).fetchone()
    if not row:
        raise HTTPException(404, "Chapter not found.")
    ok = sm.reset_chapter_to_pending(chapter_id)
    if not ok:
        raise HTTPException(404, "Chapter not found.")
    if row["output_audio_path"]:
        p = config.from_stored(row["output_audio_path"])
        if p.exists():
            try:
                p.unlink()
            except OSError:
                pass
    return {"reset": chapter_id}


# -- Characters / Casting -----------------------------------------------------

@app.get("/api/characters/{project_id}")
async def list_characters(
    project_id: int,
    sm: StateManager = Depends(get_sm),
) -> dict[str, Any]:
    chars = sm.list_characters(project_id)
    return {"characters": chars, "total": len(chars)}


@app.post("/api/characters/{project_id}", status_code=201)
async def upsert_character(
    project_id: int,
    req: CharacterUpsert,
    sm: StateManager = Depends(get_sm),
) -> dict[str, Any]:
    char_id = sm.upsert_character(
        project_id=project_id,
        name=req.name.strip(),
        aliases=req.aliases,
        emotion_hint=req.emotion_hint,
        is_pov=req.is_pov,
        status=req.status,
    )
    return {"character_id": char_id}


@app.patch("/api/characters/{character_id}/voice")
async def assign_character_voice(
    character_id: int,
    req: CharacterVoiceAssign,
    sm: StateManager = Depends(get_sm),
) -> dict[str, Any]:
    voices = sm.list_voices()
    voice = next((v for v in voices if v["name"] == req.voice_name), None)
    if voice is None:
        raise HTTPException(404, f"Voice '{req.voice_name}' not found in library.")
    sm.assign_voice(character_id, voice["id"])
    return {"character_id": character_id, "voice_name": req.voice_name}


# -- Voice library ------------------------------------------------------------

@app.get("/api/voices")
async def list_voices(sm: StateManager = Depends(get_sm)) -> dict[str, Any]:
    return {"voices": sm.list_voices()}


@app.post("/api/voices", status_code=201)
async def add_voice(
    req: VoiceAdd,
    sm: StateManager = Depends(get_sm),
) -> dict[str, Any]:
    p = config.from_stored(req.path) if not Path(req.path).is_absolute() else Path(req.path)
    if not p.exists():
        raise HTTPException(400, f"Audio file not found: {req.path}")
    stored = config.to_stored(p)
    voice_id = sm.add_voice(req.name, stored, tags=req.tags)
    return {"voice_id": voice_id, "name": req.name, "path": stored}


@app.post("/api/voices/upload", status_code=201)
async def upload_voice(
    name: str = Form(...),
    file: UploadFile = File(...),
    sm: StateManager = Depends(get_sm),
) -> dict[str, Any]:
    name = name.strip()
    if not name:
        raise HTTPException(400, "Voice name is required.")
    slug = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
    if not slug:
        raise HTTPException(400, f"Voice name '{name}' has no usable characters.")
    ext = Path(file.filename or "").suffix.lower() or ".wav"
    if ext not in _ALLOWED_VOICE_EXTS:
        raise HTTPException(
            400, f"Unsupported format '{ext}'. Allowed: {', '.join(sorted(_ALLOWED_VOICE_EXTS))}"
        )
    content = await file.read()
    if not content:
        raise HTTPException(400, "Uploaded file is empty.")
    _voices_dir().mkdir(parents=True, exist_ok=True)
    dest = _voices_dir() / f"{slug}{ext}"
    dest.write_bytes(content)
    stored = config.to_stored(dest)
    voice_id = sm.add_voice(name, stored)
    return {"voice_id": voice_id, "name": name, "path": stored}


@app.delete("/api/voices/{voice_id}")
async def delete_voice(
    voice_id: int,
    sm: StateManager = Depends(get_sm),
) -> dict[str, Any]:
    ok = sm.delete_voice(voice_id)
    if not ok:
        raise HTTPException(404, f"Voice {voice_id} not found.")
    return {"deleted": voice_id}


@app.get("/api/voices/{voice_id}/audio")
async def serve_voice_audio(
    voice_id: int,
    sm: StateManager = Depends(get_sm),
) -> FileResponse:
    voices = sm.list_voices()
    voice = next((v for v in voices if v["id"] == voice_id), None)
    if voice is None:
        raise HTTPException(404, f"Voice {voice_id} not found.")
    p = config.from_stored(voice["path"])
    if not p.exists():
        raise HTTPException(404, f"Reference clip missing on disk: {voice['path']}")
    media_type = _VOICE_MEDIA_TYPES.get(p.suffix.lower(), "application/octet-stream")
    return FileResponse(str(p), media_type=media_type, filename=p.name)


# -- Audio serving ------------------------------------------------------------

@app.get("/api/audio/{chapter_id}")
async def serve_audio(
    chapter_id: int,
    sm: StateManager = Depends(get_sm),
) -> FileResponse:
    with sm.db.conn() as conn:
        row = conn.execute(
            "SELECT output_audio_path FROM chapters WHERE id=?", (chapter_id,)
        ).fetchone()
    if row and row["output_audio_path"]:
        p = config.from_stored(row["output_audio_path"])
        if p.exists():
            return FileResponse(
                str(p),
                media_type="audio/mpeg" if p.suffix == ".mp3" else "audio/wav",
                filename=p.name,
            )
    raise HTTPException(404, f"Audio for chapter {chapter_id} not yet generated.")


# -- M4B export ---------------------------------------------------------------

@app.post("/api/export/m4b")
async def export_m4b(
    req: M4BExportRequest,
    sm: StateManager = Depends(get_sm),
) -> dict[str, Any]:
    from verbatim.audio.m4b import M4BExporter

    project = sm.get_project_by_id(req.project_id)
    if not project:
        raise HTTPException(404, f"Project {req.project_id} not found.")

    chapters = sm.get_all_chapters(req.project_id)
    complete = [c for c in chapters if c["status"] == "complete" and c.get("output_audio_path")]
    if not complete:
        raise HTTPException(409, "No completed chapters to export.")

    chapter_data: list[dict[str, Any]] = []
    for ch in complete:
        p = config.from_stored(ch["output_audio_path"])
        if not p.exists():
            continue
        chapter_data.append({
            "audio_path": str(p),
            "title": ch.get("title", ""),
            "duration_ms": int((ch.get("processing_seconds") or 0) * 1000),
        })

    if not chapter_data:
        raise HTTPException(409, "No completed audio files found on disk.")

    filename = req.output_filename or f"{project['name']}.m4b"
    _m4b_dir().mkdir(parents=True, exist_ok=True)
    output_path = _m4b_dir() / filename

    def _export() -> Path:
        exp = M4BExporter()
        return exp.export(chapter_data, output_path,
                          book_title=project["name"], author=req.author)

    out = await asyncio.to_thread(_export)
    return {"path": str(out), "size_bytes": out.stat().st_size}


# -- SSE event stream ---------------------------------------------------------

@app.get("/api/events")
async def event_stream(
    request: Request,
    mgr: PipelineManager = Depends(get_manager),
) -> StreamingResponse:
    q = mgr.subscribe()

    async def generator() -> Any:
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    event = await asyncio.wait_for(q.get(), timeout=1.0)
                    yield f"data: {json.dumps(event)}\n\n"
                    if event.get("type") in ("pipeline_done", "pipeline_error", "pipeline_stopped"):
                        break
                except TimeoutError:
                    yield ": ping\n\n"
        finally:
            mgr.unsubscribe(q)

    return StreamingResponse(
        generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )
