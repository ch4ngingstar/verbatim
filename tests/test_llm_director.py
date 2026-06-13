import json
from pathlib import Path

import pytest

from verbatim.db.manager import StateManager
from verbatim.llm.director import LLMDirector
from verbatim.llm.parsing import EMOTION_VOCAB, SYSTEM_SPEAKER


def _lj(*labels):
    return json.dumps({"labels": [{"i": i, "speaker": s, "emotion": e} for i, s, e in labels]})


def _seed(sm: StateManager, chunks: list[str], pov: str = "Alice",
          thought_conv: str = "single_quotes", system_brackets: bool = False) -> tuple[int, int]:
    pid = sm.seed_project({
        "source_epub": "test.epub",
        "total_chapters": 1,
        "chapters": [{"chapter_index": 0, "title": "Ch 1", "chunks": [
            {"chunk_index": i, "text": t, "word_count": len(t.split())}
            for i, t in enumerate(chunks)
        ]}],
    })
    sm.update_profile(
        pid, pov_style="third", pov_characters=[pov],
        thought_convention=thought_conv, system_brackets=system_brackets,
        narrator_notes="Test novel.",
    )
    sm.upsert_character(pid, pov, is_pov=True, status="cast",
                        emotion_hint="cold, stoic")
    sm.upsert_character(pid, "Bob", status="cast")
    ch_id = sm.get_all_chapters(pid)[0]["id"]
    return pid, ch_id


def _make_director(sm: StateManager, pid: int, mock_fn) -> LLMDirector:
    d = LLMDirector(Path("fake.gguf"), sm, project_id=pid)
    d._setup_from_profile()
    d._llm = object()  # truthy sentinel — bypasses "not loaded" guard
    d._call_llm = mock_fn
    return d


@pytest.fixture
def sm(tmp_path):
    return StateManager(tmp_path / "t.db")


# -- Profile loading -----------------------------------------------------------

def test_setup_loads_pov_character(sm):
    pid, _ = _seed(sm, ["text."], pov="Zara")
    d = _make_director(sm, pid, lambda t, temperature=0.2: "")
    assert d._pov_character == "Zara"


def test_setup_loads_cast_speakers(sm):
    pid, _ = _seed(sm, ["text."])
    d = _make_director(sm, pid, lambda t, temperature=0.2: "")
    assert "Alice" in d._allowed
    assert "Bob" in d._allowed
    assert "Narrator" in d._allowed
    assert "Unknown" in d._allowed


def test_setup_builds_segmenter_config(sm):
    pid, _ = _seed(sm, ["text."], thought_conv="single_quotes", system_brackets=False)
    d = _make_director(sm, pid, lambda t, temperature=0.2: "")
    assert d._segmenter_config.single_quote_thoughts is True
    assert d._segmenter_config.bracket_system_lines is False


def test_setup_no_pov_character_fallback(sm):
    pid = sm.seed_project({"source_epub": "t.epub", "total_chapters": 1,
                           "chapters": [{"chapter_index": 0, "title": "C",
                                         "chunks": [{"chunk_index": 0, "text": "x.", "word_count": 1}]}]})
    # Don't set pov_characters -> defaults to []
    d = LLMDirector(Path("fake.gguf"), sm, project_id=pid)
    d._setup_from_profile()
    assert d._pov_character == "Narrator"


# -- Prose enforcement (POV-character guard) -----------------------------------

def test_prose_first_person_pov_kept(sm):
    pid, _ = _seed(sm, ["Why me? I never asked for this."])
    d = _make_director(sm, pid, lambda t, temperature=0.2: _lj((0, "Alice", "confused")))
    lines = d._process_chunk("Why me? I never asked for this.", 0)
    assert lines[0]["speaker"] == "Alice"


def test_prose_third_person_pov_flipped_to_narrator(sm):
    pid, _ = _seed(sm, ["Alice walked into the room slowly."])
    d = _make_director(sm, pid, lambda t, temperature=0.2: _lj((0, "Alice", "cold")))
    lines = d._process_chunk("Alice walked into the room slowly.", 0)
    assert lines[0]["speaker"] == "Narrator"


def test_prose_other_character_flipped_to_narrator(sm):
    pid, _ = _seed(sm, ["The fortress loomed over the valley."])
    d = _make_director(sm, pid, lambda t, temperature=0.2: _lj((0, "Bob", "neutral")))
    lines = d._process_chunk("The fortress loomed over the valley.", 0)
    assert lines[0]["speaker"] == "Narrator"


def test_prose_emotion_survives_narrator_flip(sm):
    pid, _ = _seed(sm, ["Something horrible lurched out of the dark."])
    d = _make_director(sm, pid, lambda t, temperature=0.2: _lj((0, "Narrator", "frightened")))
    lines = d._process_chunk("Something horrible lurched out of the dark.", 0)
    assert lines[0]["speaker"] == "Narrator"
    assert lines[0]["emotion"] == "frightened"


# -- Thought enforcement -------------------------------------------------------

def test_thought_pov_label_trusted(sm):
    pid, _ = _seed(sm, ["'She has been gone for months...'"])
    d = _make_director(sm, pid, lambda t, temperature=0.2: _lj((0, "Alice", "sad")))
    lines = d._process_chunk("'She has been gone for months...'", 0)
    assert lines[0]["speaker"] == "Alice"


def test_thought_impossible_label_repaired_to_pov(sm):
    pid, _ = _seed(sm, ["'What a strange power...'"])
    d = _make_director(sm, pid, lambda t, temperature=0.2: _lj((0, SYSTEM_SPEAKER, "cold")))
    lines = d._process_chunk("'What a strange power...'", 0)
    assert lines[0]["speaker"] == "Alice"  # repaired to POV character


# -- Dialogue enforcement ------------------------------------------------------

def test_dialogue_narrator_becomes_unknown(sm):
    pid, _ = _seed(sm, ['"Who goes there?"'])
    d = _make_director(sm, pid, lambda t, temperature=0.2: _lj((0, "Narrator", "neutral")))
    lines = d._process_chunk('"Who goes there?"', 0)
    assert lines[0]["speaker"] == "Unknown"


# -- Integration: process_chapter ----------------------------------------------

def test_process_chapter_writes_diarized_lines(sm):
    text = 'Alice stared at the runes. "What does it mean?" she asked.'
    pid, ch_id = _seed(sm, [text])

    def mock_fn(t, temperature=0.2):
        return _lj((0, "Narrator", "neutral"), (1, "Alice", "confused"), (2, "Narrator", "neutral"))

    d = _make_director(sm, pid, mock_fn)
    n = d.process_chapter(ch_id)

    assert n == 3
    lines = sm.get_lines_for_chapter(ch_id)
    assert lines[1]["speaker"] == "Alice"
    assert lines[1]["text"] == "What does it mean?"
    assert lines[1]["emotion"] == "confused"
    assert sm.get_all_chapters(pid)[0]["status"] == "diarized"


def test_process_chapter_multi_chunk_offsets(sm):
    pid, ch_id = _seed(sm, ["Chunk one.", "Chunk two."])

    def mock_fn(t, temperature=0.2):
        return _lj((0, "Narrator", "neutral"))

    d = _make_director(sm, pid, mock_fn)
    n = d.process_chapter(ch_id)
    assert n == 2
    lines = sm.get_lines_for_chapter(ch_id)
    assert [ln["line_index"] for ln in lines] == [0, 1]


def test_retry_on_bad_json(sm):
    pid, ch_id = _seed(sm, ["The darkness stirred."])
    calls = [0]

    def mock_fn(t, temperature=0.2):
        calls[0] += 1
        return "{{bad json" if calls[0] < 2 else _lj((0, "Narrator", "neutral"))

    d = _make_director(sm, pid, mock_fn)
    n = d.process_chapter(ch_id)
    assert n == 1
    assert calls[0] == 2


def test_fallback_preserves_all_text(sm):
    import re
    text = 'The shadow fell. "Run!" she screamed.\n\n[A creature approaches.]'
    pid, ch_id = _seed(sm, [text], system_brackets=True)

    d = _make_director(sm, pid, lambda t, temperature=0.2: "not json }")
    n = d.process_chapter(ch_id)

    lines = sm.get_lines_for_chapter(ch_id)
    src_words = sorted(re.findall(r"[a-z0-9']+", text.lower()))
    out_words = sorted(re.findall(r"[a-z0-9']+", " ".join(ln["text"] for ln in lines).lower()))
    assert src_words == out_words


def test_call_llm_raises_outside_context(sm):
    pid, _ = _seed(sm, ["x."])
    d = LLMDirector(Path("fake.gguf"), sm, project_id=pid)
    with pytest.raises(RuntimeError, match="with"):
        d._call_llm("test")
