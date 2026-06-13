import pytest

from tests.test_projects import PARSED
from verbatim.db.manager import StateManager


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
    sm.save_diarized_lines(
        cid, [{"line_index": 0, "speaker": "N", "text": "x", "emotion": "neutral"}]
    )
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
