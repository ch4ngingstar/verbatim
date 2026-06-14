"""GPU-free tests for TTSEngine.

_synthesize is monkeypatched to return silent WAV bytes.
No GPU, no IndexTTS2, no torch required.
"""

import sys
from pathlib import Path
from typing import Any

import pytest

VERBATIM_SRC = str(Path(__file__).parent.parent / "src")
if VERBATIM_SRC not in sys.path:
    sys.path.insert(0, VERBATIM_SRC)

from verbatim.db.manager import StateManager
from verbatim.tts.emotion import wav_silence

# -- Helpers ------------------------------------------------------------------

def _make_sm(tmp_path: Path) -> "tuple[StateManager, int, int]":
    """Return (sm, project_id, chapter_id) seeded with 2 pending TTS lines."""
    sm = StateManager(tmp_path / "test.db")
    with sm.db.conn() as conn:
        conn.execute(
            "INSERT INTO projects (name, source_epub, total_chapters) "
            "VALUES ('TestBook', 'book.epub', 1)"
        )
        pid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.execute(
            "INSERT INTO chapters (project_id, chapter_index, title, status, total_lines) "
            "VALUES (?, 0, 'Chapter 1', 'diarized', 2)",
            (pid,),
        )
        cid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.executemany(
            "INSERT INTO lines (chapter_id, line_index, speaker, text, emotion, status) "
            "VALUES (?, ?, ?, ?, ?, 'pending')",
            [
                (cid, 0, "Sunny", "Hello world.", "neutral"),
                (cid, 1, "Narration", "He walked away.", "sad"),
            ],
        )
    return sm, pid, cid


def _register_default_voice(sm: StateManager, tmp_path: Path, monkeypatch: Any) -> None:
    """Register a _default voice accessible via get_project_voice_map."""
    monkeypatch.setenv("VERBATIM_DATA_DIR", str(tmp_path / "data"))
    import verbatim.config as cfg
    voice_file = tmp_path / "data" / "voices" / "default.wav"
    voice_file.parent.mkdir(parents=True, exist_ok=True)
    voice_file.write_bytes(wav_silence(100))
    sm.add_voice("_default", cfg.to_stored(voice_file))


def _fake_synthesize(text: str, ref_path: Path, emo_vec: Any, emo_alpha: float) -> bytes:
    return wav_silence(50)


# -- Tests --------------------------------------------------------------------

def test_process_chapter_basic(tmp_path, monkeypatch):
    """process_chapter synthesises pending lines and marks chapter tts_done."""
    sm, pid, cid = _make_sm(tmp_path)
    _register_default_voice(sm, tmp_path, monkeypatch)

    from verbatim.tts.engine import TTSEngine

    wav_dir = tmp_path / "data" / "audio"
    engine = TTSEngine(sm, pid, wav_dir)
    engine._synthesize = _fake_synthesize

    with engine:
        n = engine.process_chapter(cid)

    assert n == 2
    chapter = next(c for c in sm.get_all_chapters(pid) if c["id"] == cid)
    assert chapter["status"] == "tts_done"


def test_process_chapter_no_voice_skips_line(tmp_path, monkeypatch):
    """Lines with no resolvable voice are skipped (not failed)."""
    monkeypatch.setenv("VERBATIM_DATA_DIR", str(tmp_path / "data"))
    sm, pid, cid = _make_sm(tmp_path)
    # No voices registered — all lines should be skipped

    from verbatim.tts.engine import TTSEngine

    wav_dir = tmp_path / "data" / "audio"
    engine = TTSEngine(sm, pid, wav_dir)
    engine._synthesize = _fake_synthesize

    with engine:
        n = engine.process_chapter(cid)

    assert n == 0


def test_process_chapter_writes_wav_files(tmp_path, monkeypatch):
    """process_chapter creates WAV files on disk for each synthesised line."""
    sm, pid, cid = _make_sm(tmp_path)
    _register_default_voice(sm, tmp_path, monkeypatch)

    from verbatim.tts.engine import TTSEngine

    wav_dir = tmp_path / "data" / "audio"
    engine = TTSEngine(sm, pid, wav_dir)
    engine._synthesize = _fake_synthesize

    with engine:
        engine.process_chapter(cid)

    ch_dir = wav_dir / f"ch_{cid:04d}"
    wavs = sorted(ch_dir.glob("*.wav"))
    assert len(wavs) == 2


def test_process_chapter_no_lines_returns_zero(tmp_path, monkeypatch):
    """No pending lines → returns 0, no error."""
    sm, pid, cid = _make_sm(tmp_path)
    _register_default_voice(sm, tmp_path, monkeypatch)
    # Mark all lines done
    with sm.db.conn() as conn:
        conn.execute("UPDATE lines SET status='tts_done' WHERE chapter_id=?", (cid,))

    from verbatim.tts.engine import TTSEngine

    wav_dir = tmp_path / "data" / "audio"
    engine = TTSEngine(sm, pid, wav_dir)
    engine._synthesize = _fake_synthesize

    with engine:
        n = engine.process_chapter(cid)

    assert n == 0


def test_engine_raises_outside_context(tmp_path, monkeypatch):
    """Calling process_chapter outside a context manager raises RuntimeError."""
    monkeypatch.setenv("VERBATIM_DATA_DIR", str(tmp_path / "data"))
    sm, pid, cid = _make_sm(tmp_path)

    from verbatim.tts.engine import TTSEngine

    engine = TTSEngine(sm, pid, tmp_path / "audio")
    # No _synthesize injected, no __enter__ called → must raise
    with pytest.raises(RuntimeError, match="context manager"):
        engine.process_chapter(cid)


def test_partial_failure_marks_chapter_error(tmp_path, monkeypatch):
    """When some lines fail synthesis, chapter status is set to 'error'."""
    sm, pid, cid = _make_sm(tmp_path)
    _register_default_voice(sm, tmp_path, monkeypatch)

    from verbatim.tts.engine import TTSEngine

    call_count = [0]

    def _sometimes_fail(text: str, ref_path: Path, emo_vec: Any, emo_alpha: float) -> bytes:
        call_count[0] += 1
        if call_count[0] > 1:
            raise RuntimeError("boom")
        return wav_silence(50)

    wav_dir = tmp_path / "data" / "audio"
    engine = TTSEngine(sm, pid, wav_dir)
    engine._synthesize = _sometimes_fail

    with engine:
        engine.process_chapter(cid)

    chapter = next(c for c in sm.get_all_chapters(pid) if c["id"] == cid)
    assert chapter["status"] == "error"
    assert "failed_stage:tts" in (chapter.get("error_message") or "")


def test_unload_calls_gc_collect(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """_unload_model must call gc.collect() to release VRAM references promptly."""
    import sys
    import unittest.mock as mock

    import verbatim.tts.engine as engine_mod
    from verbatim.tts.engine import TTSEngine

    fake_torch = mock.MagicMock()
    monkeypatch.setitem(sys.modules, "torch", fake_torch)

    sm = StateManager(tmp_path / "test.db")
    engine = TTSEngine(sm, 1, tmp_path / "audio")
    engine._tts = object()  # non-None so the inner block runs

    with mock.patch.object(engine_mod, "gc") as mock_gc:
        engine._unload_model()
    mock_gc.collect.assert_called_once()
