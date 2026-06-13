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
        {"name": "Sunny", "aliases": ["Sunless"], "emotion_hint": "stoic", "importance": 10, "is_pov": True},
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
