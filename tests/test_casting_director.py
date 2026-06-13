import json

import pytest

from verbatim.casting.director import CastingDirector
from verbatim.db.manager import StateManager

_BOOK_5CH = {
    "source_epub": "mynovel.epub",
    "total_chapters": 5,
    "chapters": [
        {
            "chapter_index": i,
            "title": f"Chapter {i + 1}",
            "chunks": [
                {"chunk_index": 0, "text": f"Chapter {i + 1} sample text.", "word_count": 4},
            ],
        }
        for i in range(5)
    ],
}

_MOCK_RESPONSE = json.dumps({
    "pov_style": "third",
    "pov_characters": ["Alice"],
    "thought_convention": "single_quotes",
    "narrator_notes": "Third-person limited, follows Alice.",
    "characters": [
        {"name": "Alice", "aliases": ["Ali"], "is_pov": True,  "emotion_hint": "determined, cold"},
        {"name": "Bob",   "aliases": [],      "is_pov": False, "emotion_hint": "cheerful"},
    ],
})


@pytest.fixture
def sm(tmp_path):
    return StateManager(tmp_path / "t.db")


@pytest.fixture
def pid(sm):
    return sm.seed_project(_BOOK_5CH)


def _make_director(sm: StateManager, pid: int, mock_fn, n_chapters: int = 10) -> CastingDirector:
    d = CastingDirector(model_path="fake.gguf", sm=sm, project_id=pid, n_chapters=n_chapters)
    d._llm = object()
    d._call_llm = mock_fn
    return d


def test_run_writes_profile(sm, pid):
    _make_director(sm, pid, lambda t: _MOCK_RESPONSE).run()
    proj = sm.get_project_by_id(pid)
    assert proj["pov_style"] == "third"
    assert proj["pov_characters"] == ["Alice"]
    assert proj["thought_convention"] == "single_quotes"
    assert proj["narrator_notes"] != ""


def test_run_writes_characters(sm, pid):
    _make_director(sm, pid, lambda t: _MOCK_RESPONSE).run()
    chars = sm.list_characters(pid)
    assert {c["name"] for c in chars} == {"Alice", "Bob"}
    alice = next(c for c in chars if c["name"] == "Alice")
    assert alice["aliases"] == ["Ali"]
    assert alice["is_pov"] == 1
    assert alice["status"] == "suggested"


def test_run_is_idempotent(sm, pid):
    d = _make_director(sm, pid, lambda t: _MOCK_RESPONSE)
    d.run()
    d.run()
    assert len(sm.list_characters(pid)) == 2  # no duplicates


def test_run_n_chapters_limits_input(sm, pid):
    captured: list[str] = []

    def capture(t: str) -> str:
        captured.append(t)
        return _MOCK_RESPONSE

    _make_director(sm, pid, capture, n_chapters=2).run()
    assert "Chapter 1 sample text." in captured[0]
    assert "Chapter 2 sample text." in captured[0]
    assert "Chapter 3 sample text." not in captured[0]


def test_run_corrects_invalid_pov_style(sm, pid):
    bad = json.dumps({
        "pov_style": "omniscient",  # not in POV_STYLES -> corrected to "third"
        "pov_characters": [],
        "thought_convention": "none",
        "narrator_notes": "",
        "characters": [],
    })
    _make_director(sm, pid, lambda t: bad).run()
    assert sm.get_project_by_id(pid)["pov_style"] == "third"


def test_run_corrects_invalid_thought_convention(sm, pid):
    bad = json.dumps({
        "pov_style": "third",
        "pov_characters": [],
        "thought_convention": "italics",  # not in THOUGHT_CONVENTIONS -> corrected to "none"
        "narrator_notes": "",
        "characters": [],
    })
    _make_director(sm, pid, lambda t: bad).run()
    assert sm.get_project_by_id(pid)["thought_convention"] == "none"


def test_run_raises_on_broken_json(sm, pid):
    with pytest.raises((ValueError, json.JSONDecodeError)):
        _make_director(sm, pid, lambda t: "not {{ json at all").run()


def test_call_llm_raises_outside_context(sm, pid):
    d = CastingDirector(model_path="fake.gguf", sm=sm, project_id=pid)
    with pytest.raises(RuntimeError, match="with"):
        d._call_llm("text")
