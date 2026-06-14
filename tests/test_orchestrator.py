"""Tests for PipelineOrchestrator — no GPU, no FFmpeg, no LLM required.

All collaborators (LLMDirector, TTSEngine, AudioAssembler) are replaced with
fakes injected via the constructor's *_cls arguments.
"""

import sys
import threading
import time
from pathlib import Path
from typing import Any

import pytest

VERBATIM_SRC = str(Path(__file__).parent.parent / "src")
if VERBATIM_SRC not in sys.path:
    sys.path.insert(0, VERBATIM_SRC)

from verbatim.db.manager import StateManager
from verbatim.pipeline.orchestrator import OrchestratorConfig, PipelineOrchestrator

# -- Fixtures -----------------------------------------------------------------

@pytest.fixture
def tmp_sm(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> StateManager:
    monkeypatch.setenv("VERBATIM_DATA_DIR", str(tmp_path / "data"))
    return StateManager(tmp_path / "test.db")


def _seed_project(sm: StateManager, n_chapters: int = 3) -> int:
    """Insert a project with n_chapters all set to 'pending'."""
    with sm.db.conn() as conn:
        conn.execute(
            "INSERT INTO projects (name, source_epub, total_chapters) VALUES (?, ?, ?)",
            ("TestBook", "book.epub", n_chapters),
        )
        pid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        for i in range(n_chapters):
            conn.execute(
                "INSERT INTO chapters (project_id, chapter_index, title, status) "
                "VALUES (?, ?, ?, 'pending')",
                (pid, i, f"Chapter {i + 1}"),
            )
            cid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
            conn.execute(
                "INSERT INTO chunks (chapter_id, chunk_index, text, word_count) "
                "VALUES (?, 0, 'Hello world.', 2)",
                (cid,),
            )
    return pid


# -- Fake collaborators -------------------------------------------------------

class FakeLLMDirector:
    """Fake LLMDirector: records calls, saves empty diarized lines."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self._sm: StateManager = kwargs.get("sm") or args[1]
        self._project_id: int = kwargs.get("project_id") or args[2]
        self.calls: list[int] = []

    def __enter__(self) -> "FakeLLMDirector":
        return self

    def __exit__(self, *_: Any) -> None:
        pass

    def process_chapter(self, chapter_id: int) -> int:
        self.calls.append(chapter_id)
        self._sm.save_diarized_lines(chapter_id, [])
        return 0


class FakeTTSEngine:
    """Fake TTSEngine: records calls, sets chapter to tts_done."""

    def __init__(self, sm: Any, project_id: Any, wav_dir: Any, cfg: Any = None) -> None:
        self._sm: StateManager = sm
        self.calls: list[int] = []

    def __enter__(self) -> "FakeTTSEngine":
        return self

    def __exit__(self, *_: Any) -> None:
        pass

    def process_chapter(self, chapter_id: int) -> int:
        self.calls.append(chapter_id)
        self._sm.mark_chapter_status(chapter_id, "tts_done")
        return 0


class FakeAssembler:
    """Fake AudioAssembler: writes a placeholder file and records calls."""

    def __init__(self, cfg: Any = None) -> None:
        self.calls: list[int] = []

    def assemble_chapter(self, lines: Any, output_path: Any, **kw: Any) -> Path:
        p = Path(str(output_path))
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"fake_mp3")
        self.calls.append(1)
        return p


def _make_orchestrator(
    project_id: int,
    sm: StateManager,
    tmp_path: Path,
    events: "list[dict] | None" = None,
    vram_check: bool = False,
    llm_cls: type = FakeLLMDirector,
    tts_cls: type = FakeTTSEngine,
    asm_cls: type = FakeAssembler,
) -> PipelineOrchestrator:
    cfg = OrchestratorConfig(
        llm_model_path="fake.gguf",
        tts_model_dir="fake/checkpoints",
        # Must be absolute paths inside data_root so config.to_stored() succeeds
        wav_output_dir=str(tmp_path / "data" / "audio"),
        mp3_output_dir=str(tmp_path / "data" / "output"),
        vram_check_enabled=vram_check,
    )
    ev: list[dict] = [] if events is None else events
    return PipelineOrchestrator(
        project_id=project_id,
        sm=sm,
        cfg=cfg,
        progress_callback=lambda e: ev.append(e),
        llm_director_cls=llm_cls,
        tts_engine_cls=tts_cls,
        assembler_cls=asm_cls,
    )


# -- Tests --------------------------------------------------------------------

def test_run_all_pending_chapters(tmp_sm: StateManager, tmp_path: Path) -> None:
    """A project with 3 pending chapters should complete all 3."""
    pid = _seed_project(tmp_sm, n_chapters=3)
    events: list[dict] = []
    orch = _make_orchestrator(pid, tmp_sm, tmp_path, events=events)

    result = orch.run()

    assert result["success"] == 3
    assert result["error"] == 0
    assert result["skipped"] == 0

    chapters = tmp_sm.get_all_chapters(pid)
    assert all(c["status"] == "complete" for c in chapters)

    event_types = [e["type"] for e in events]
    assert "pipeline_start" in event_types
    assert "pipeline_done" in event_types
    assert event_types.count("chapter_done") == 3


def test_run_skips_complete_chapters(tmp_sm: StateManager, tmp_path: Path) -> None:
    """Chapters already 'complete' must be skipped, not re-processed."""
    pid = _seed_project(tmp_sm, n_chapters=2)
    chapters = tmp_sm.get_all_chapters(pid)
    tmp_sm.mark_chapter_status(chapters[0]["id"], "complete")

    events: list[dict] = []
    orch = _make_orchestrator(pid, tmp_sm, tmp_path, events=events)
    result = orch.run()

    assert result["success"] == 1
    assert result["skipped"] == 1
    skip_events = [e for e in events if e["type"] == "chapter_skip"]
    assert len(skip_events) == 1


def test_resume_from_failed_tts_stage(tmp_sm: StateManager, tmp_path: Path) -> None:
    """A chapter with error_message=[failed_stage:synthesize] resumes from TTS, not diarize."""
    pid = _seed_project(tmp_sm, n_chapters=1)
    ch_id = tmp_sm.get_all_chapters(pid)[0]["id"]

    # Simulate a chapter that failed mid-TTS after diarization succeeded
    tmp_sm.save_diarized_lines(ch_id, [])
    tmp_sm.mark_chapter_status(
        ch_id, "error",
        error_message="[failed_stage:synthesize] GPU OOM",
    )

    llm_calls: list[int] = []

    class RecordingLLM(FakeLLMDirector):
        def process_chapter(self, chapter_id: int) -> int:
            llm_calls.append(chapter_id)
            return super().process_chapter(chapter_id)

    orch = _make_orchestrator(pid, tmp_sm, tmp_path, llm_cls=RecordingLLM)
    result = orch.run()

    assert result["success"] == 1
    assert llm_calls == [], "diarize must NOT be called when resume is from synthesize"
    assert tmp_sm.get_all_chapters(pid)[0]["status"] == "complete"


def test_resume_from_unknown_error_restarts_from_diarize(
    tmp_sm: StateManager, tmp_path: Path
) -> None:
    """A chapter with an error_message lacking [failed_stage:X] restarts from diarize."""
    pid = _seed_project(tmp_sm, n_chapters=1)
    ch_id = tmp_sm.get_all_chapters(pid)[0]["id"]

    tmp_sm.mark_chapter_status(ch_id, "error", error_message="unknown error, no tag")

    llm_calls: list[int] = []

    class RecordingLLM(FakeLLMDirector):
        def process_chapter(self, chapter_id: int) -> int:
            llm_calls.append(chapter_id)
            return super().process_chapter(chapter_id)

    orch = _make_orchestrator(pid, tmp_sm, tmp_path, llm_cls=RecordingLLM)
    result = orch.run()

    assert result["success"] == 1
    assert ch_id in llm_calls, "diarize MUST be called when failed_stage tag is absent"


def test_stop_halts_before_processing(tmp_sm: StateManager, tmp_path: Path) -> None:
    """Calling stop() before run() exits immediately with pipeline_stopped event."""
    pid = _seed_project(tmp_sm, n_chapters=3)
    events: list[dict] = []
    orch = _make_orchestrator(pid, tmp_sm, tmp_path, events=events)

    orch.stop()
    result = orch.run()

    assert result["success"] == 0
    assert result["skipped"] == 0
    stopped_events = [e for e in events if e["type"] == "pipeline_stopped"]
    assert len(stopped_events) == 1


def test_pause_and_resume(tmp_sm: StateManager, tmp_path: Path) -> None:
    """Pausing and then resuming allows all chapters to complete."""
    pid = _seed_project(tmp_sm, n_chapters=2)
    orch = _make_orchestrator(pid, tmp_sm, tmp_path)

    orch.pause()
    t = threading.Thread(target=orch.run)
    t.start()
    time.sleep(0.05)  # give thread time to block on pause
    orch.resume()
    t.join(timeout=10)

    assert not t.is_alive(), "pipeline thread did not complete within 10 seconds"
    chapters = tmp_sm.get_all_chapters(pid)
    assert all(c["status"] == "complete" for c in chapters)
