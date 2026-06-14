"""FastAPI endpoint tests — no GPU, no FFmpeg, no real EPUB required.

Uses TestClient with dependency_overrides for StateManager and PipelineManager.
"""

import sys
from pathlib import Path

import pytest

VERBATIM_SRC = str(Path(__file__).parent.parent / "src")
if VERBATIM_SRC not in sys.path:
    sys.path.insert(0, VERBATIM_SRC)

from fastapi.testclient import TestClient

from verbatim.api.app import app, get_manager, get_sm
from verbatim.api.pipeline_manager import PipelineManager
from verbatim.db.manager import StateManager
from verbatim.tts.emotion import wav_silence

# -- Test fixtures ------------------------------------------------------------

@pytest.fixture
def tmp_sm(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> StateManager:
    monkeypatch.setenv("VERBATIM_DATA_DIR", str(tmp_path / "data"))
    return StateManager(tmp_path / "test.db")


@pytest.fixture
def client(tmp_sm: StateManager) -> TestClient:
    mgr = PipelineManager()

    app.dependency_overrides[get_sm] = lambda: tmp_sm
    app.dependency_overrides[get_manager] = lambda: mgr
    yield TestClient(app)
    app.dependency_overrides.clear()


# -- Helpers ------------------------------------------------------------------

def _seed_project(sm: StateManager, tmp_path: Path) -> int:
    """Insert a minimal project directly into the DB and return its id."""
    with sm.db.conn() as conn:
        conn.execute(
            "INSERT INTO projects (name, source_epub, total_chapters) "
            "VALUES ('TestBook', 'book.epub', 1)"
        )
        pid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.execute(
            "INSERT INTO chapters (project_id, chapter_index, title, status) "
            "VALUES (?, 0, 'Chapter 1', 'complete')",
            (pid,),
        )
    return pid


# -- Health -------------------------------------------------------------------

def test_health(client: TestClient) -> None:
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


# -- Projects -----------------------------------------------------------------

def test_list_projects_empty(client: TestClient) -> None:
    r = client.get("/api/projects")
    assert r.status_code == 200
    assert r.json()["projects"] == []


def test_get_project_not_found(client: TestClient) -> None:
    r = client.get("/api/projects/999")
    assert r.status_code == 404


def test_get_project_ok(tmp_path: Path, client: TestClient, tmp_sm: StateManager) -> None:
    pid = _seed_project(tmp_sm, tmp_path)
    r = client.get(f"/api/projects/{pid}")
    assert r.status_code == 200
    data = r.json()
    assert data["project"]["name"] == "TestBook"


def test_update_novel_profile(tmp_path: Path, client: TestClient, tmp_sm: StateManager) -> None:
    pid = _seed_project(tmp_sm, tmp_path)
    r = client.patch(f"/api/projects/{pid}/profile", json={"pov_style": "first"})
    assert r.status_code == 200
    assert r.json()["project"]["pov_style"] == "first"


def test_update_profile_no_fields(tmp_path: Path, client: TestClient, tmp_sm: StateManager) -> None:
    pid = _seed_project(tmp_sm, tmp_path)
    r = client.patch(f"/api/projects/{pid}/profile", json={})
    assert r.status_code == 400


# -- Pipeline -----------------------------------------------------------------

def test_start_pipeline_project_not_found(client: TestClient) -> None:
    r = client.post("/api/pipeline/start", json={
        "project_id": 999,
        "llm_model_path": "models/q.gguf",
    })
    assert r.status_code == 404


def test_pipeline_status_idle(client: TestClient) -> None:
    r = client.get("/api/pipeline/status")
    assert r.status_code == 200
    assert r.json()["state"] == "idle"


def test_pipeline_pause_resume_stop_no_error(client: TestClient) -> None:
    for endpoint in ("/api/pipeline/pause", "/api/pipeline/resume", "/api/pipeline/stop"):
        r = client.post(endpoint)
        assert r.status_code == 200


# -- Chapters -----------------------------------------------------------------

def test_list_chapters(tmp_path: Path, client: TestClient, tmp_sm: StateManager) -> None:
    pid = _seed_project(tmp_sm, tmp_path)
    r = client.get(f"/api/chapters/{pid}")
    assert r.status_code == 200
    data = r.json()
    assert data["total"] == 1


def test_list_chapters_empty(client: TestClient) -> None:
    r = client.get("/api/chapters/999")
    assert r.status_code == 200
    assert r.json()["total"] == 0


def test_reset_chapter_not_found(client: TestClient) -> None:
    r = client.post("/api/chapters/999/reset")
    assert r.status_code == 404


# -- Characters ---------------------------------------------------------------

def test_list_characters_empty(tmp_path: Path, client: TestClient, tmp_sm: StateManager) -> None:
    pid = _seed_project(tmp_sm, tmp_path)
    r = client.get(f"/api/characters/{pid}")
    assert r.status_code == 200
    assert r.json()["total"] == 0


def test_upsert_character(tmp_path: Path, client: TestClient, tmp_sm: StateManager) -> None:
    pid = _seed_project(tmp_sm, tmp_path)
    r = client.post(f"/api/characters/{pid}", json={
        "name": "Sunny", "aliases": ["Sunless King"], "status": "cast"
    })
    assert r.status_code == 201
    assert r.json()["character"]["name"] == "Sunny"


# -- Voices -------------------------------------------------------------------

def test_list_voices_empty(client: TestClient) -> None:
    r = client.get("/api/voices")
    assert r.status_code == 200
    assert r.json()["voices"] == []


def test_add_voice_missing_file(client: TestClient) -> None:
    r = client.post("/api/voices", json={"name": "Sunny", "path": "/nonexistent/file.wav"})
    assert r.status_code == 400


def test_upload_voice(
    tmp_path: Path, client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_sm: StateManager
) -> None:
    monkeypatch.setenv("VERBATIM_DATA_DIR", str(tmp_path / "data"))
    wav_bytes = wav_silence(100)
    r = client.post(
        "/api/voices/upload",
        data={"name": "TestSpeaker"},
        files={"file": ("test.wav", wav_bytes, "audio/wav")},
    )
    assert r.status_code == 201
    body = r.json()
    assert body["name"] == "TestSpeaker"
    assert body["voice_id"] > 0


def test_upload_voice_empty_name(client: TestClient) -> None:
    r = client.post(
        "/api/voices/upload",
        data={"name": ""},
        files={"file": ("test.wav", b"data", "audio/wav")},
    )
    # FastAPI/Starlette may return 400 (our guard) or 422 (empty string coerces to "")
    assert r.status_code in (400, 422)


def test_upload_voice_bad_ext(client: TestClient) -> None:
    r = client.post(
        "/api/voices/upload",
        data={"name": "Speaker"},
        files={"file": ("test.txt", b"data", "text/plain")},
    )
    assert r.status_code == 400


def test_delete_voice_not_found(client: TestClient) -> None:
    r = client.delete("/api/voices/9999")
    assert r.status_code == 404


def test_add_and_delete_voice(
    tmp_path: Path, client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_sm: StateManager
) -> None:
    monkeypatch.setenv("VERBATIM_DATA_DIR", str(tmp_path / "data"))
    voice_file = tmp_path / "data" / "voices" / "test.wav"
    voice_file.parent.mkdir(parents=True, exist_ok=True)
    voice_file.write_bytes(wav_silence(100))

    import verbatim.config as cfg
    stored = cfg.to_stored(voice_file)
    r = client.post("/api/voices", json={"name": "DeleteMe", "path": stored})
    assert r.status_code == 201
    vid = r.json()["voice_id"]

    r2 = client.delete(f"/api/voices/{vid}")
    assert r2.status_code == 200
    assert r2.json()["deleted"] == vid


# -- Analyze (CastingDirector) ------------------------------------------------

import json as _json

from verbatim.casting.director import CastingDirector

FAKE_CAST_RESPONSE = {
    "pov_style": "third",
    "thought_convention": "single_quotes",
    "narrator_notes": "LitRPG world",
    "characters": [
        {"name": "Sunny", "aliases": ["Sunless"], "emotion_hint": "stoic", "importance": 10,
         "is_pov": True},
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
        return _json.dumps(FAKE_CAST_RESPONSE)

    monkeypatch.setattr(CastingDirector, "_call_llm", fake_call_llm)
    # Suppress model load if llama_cpp absent
    monkeypatch.setattr(CastingDirector, "__enter__", lambda self: self)
    monkeypatch.setattr(CastingDirector, "__exit__", lambda self, *_: None)

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


# -- M4B export ---------------------------------------------------------------

import verbatim.audio.m4b as _m4b_mod  # noqa: E402
from verbatim.audio.m4b import M4BExporter  # noqa: E402


def _seed_project_with_audio(sm: StateManager, tmp_path: Path) -> int:
    """Seed a project with one completed chapter that has audio on disk."""
    import verbatim.config as cfg
    audio_dir = cfg.data_root() / "output"
    audio_dir.mkdir(parents=True, exist_ok=True)
    fake_mp3 = audio_dir / "ch_0001.mp3"
    fake_mp3.write_bytes(b"ID3FAKE")
    stored = cfg.to_stored(fake_mp3)
    with sm.db.conn() as conn:
        conn.execute(
            "INSERT INTO projects (name, source_epub, total_chapters) "
            "VALUES ('AudioBook', 'book.epub', 1)"
        )
        pid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.execute(
            "INSERT INTO chapters (project_id, chapter_index, title, status, output_audio_path) "
            "VALUES (?, 0, 'Chapter 1', 'complete', ?)",
            (pid, stored),
        )
    return pid


def test_export_m4b_project_not_found(client: TestClient) -> None:
    r = client.post("/api/export/m4b", json={"project_id": 9999})
    assert r.status_code == 404


def test_export_m4b_no_complete_chapters(
    tmp_path: Path, client: TestClient, tmp_sm: StateManager
) -> None:
    # _seed_project inserts a chapter with status='complete' but NULL output_audio_path.
    # The route filters on both status AND output_audio_path being set, so this → 409.
    pid = _seed_project(tmp_sm, tmp_path)
    r = client.post("/api/export/m4b", json={"project_id": pid})
    assert r.status_code == 409


def test_export_m4b_ok(
    tmp_path: Path,
    client: TestClient,
    tmp_sm: StateManager,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import verbatim.config as cfg

    pid = _seed_project(tmp_sm, tmp_path)

    # Plant a fake audio file under the data root so to_stored() works
    audio_dir = cfg.data_root() / "output"
    audio_dir.mkdir(parents=True, exist_ok=True)
    fake_mp3 = audio_dir / "ch_0001.mp3"
    fake_mp3.write_bytes(b"ID3FAKE")
    stored = cfg.to_stored(fake_mp3)

    # Mark the seeded chapter complete with a valid audio path
    with tmp_sm.db.conn() as conn:
        conn.execute(
            "UPDATE chapters SET status='complete', output_audio_path=? WHERE project_id=?",
            (stored, pid),
        )

    # Patch M4BExporter.export to skip actual FFmpeg and return a real file
    def fake_export(
        self: M4BExporter,
        chapter_mp3s: list,
        output_path: object,
        book_title: str = "",
        author: str = "",
        cover_path: object = None,
    ) -> Path:
        out = tmp_path / "out.m4b"
        out.write_bytes(b"ftyp")
        return out

    monkeypatch.setattr(M4BExporter, "export", fake_export)

    r = client.post("/api/export/m4b", json={"project_id": pid})
    assert r.status_code == 200
    body = r.json()
    assert "path" in body
    assert body.get("size_bytes", 0) > 0


def test_export_m4b_sanitizes_filename(
    tmp_path: Path,
    client: TestClient,
    tmp_sm: StateManager,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Path traversal in output_filename must be stripped to basename only."""
    import verbatim.config as cfg

    pid = _seed_project_with_audio(tmp_sm, tmp_path)

    monkeypatch.setattr(_m4b_mod, "_probe_duration_ms", lambda path, ffprobe_bin="ffprobe": 0)

    def fake_export(
        self: M4BExporter,
        chapter_mp3s: list,
        output_path: object,
        book_title: str = "",
        author: str = "",
        cover_path: object = None,
    ) -> Path:
        out = Path(str(output_path))
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(b"ftyp")
        return out

    monkeypatch.setattr(M4BExporter, "export", fake_export)

    r = client.post(
        "/api/export/m4b",
        json={"project_id": pid, "output_filename": "../../evil.m4b"},
    )
    assert r.status_code == 200
    returned_path = Path(r.json()["path"])
    m4b_dir = cfg.data_root() / "m4b"
    assert returned_path.parent == m4b_dir, (
        f"output escaped m4b dir: {returned_path}"
    )
    assert returned_path.name == "evil.m4b"


def test_export_m4b_uses_audio_duration(
    tmp_path: Path,
    client: TestClient,
    tmp_sm: StateManager,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """duration_ms must come from ffprobe, not processing_seconds."""
    probe_calls: list[int] = []

    def fake_probe(path: object, ffprobe_bin: str = "ffprobe") -> int:
        probe_calls.append(1)
        return 42_000

    monkeypatch.setattr(_m4b_mod, "_probe_duration_ms", fake_probe)

    captured: list[dict] = []

    def fake_export(
        self: M4BExporter,
        chapter_mp3s: list,
        output_path: object,
        book_title: str = "",
        author: str = "",
        cover_path: object = None,
    ) -> Path:
        captured.extend(chapter_mp3s)
        out = Path(str(output_path))
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(b"ftyp")
        return out

    monkeypatch.setattr(M4BExporter, "export", fake_export)

    pid = _seed_project_with_audio(tmp_sm, tmp_path)
    r = client.post("/api/export/m4b", json={"project_id": pid})
    assert r.status_code == 200
    assert len(probe_calls) > 0, "ffprobe was never called"
    assert all(ch["duration_ms"] == 42_000 for ch in captured)


# -- Upload size limits -------------------------------------------------------

def test_upload_epub_too_large(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """EPUB uploads exceeding the size limit must return 413."""
    import verbatim.api.app as app_mod
    monkeypatch.setattr(app_mod, "_MAX_EPUB_BYTES", 500)
    big = b"x" * 501
    r = client.post(
        "/api/projects",
        files={"epub": ("big.epub", big, "application/epub+zip")},
    )
    assert r.status_code == 413


def test_upload_voice_too_large(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Voice uploads exceeding the size limit must return 413."""
    import verbatim.api.app as app_mod
    monkeypatch.setattr(app_mod, "_MAX_VOICE_BYTES", 500)
    big = b"x" * 501
    r = client.post(
        "/api/voices/upload",
        data={"name": "testvoice"},
        files={"file": ("big.wav", big, "audio/wav")},
    )
    assert r.status_code == 413
