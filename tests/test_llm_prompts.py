from verbatim.llm.parsing import SYSTEM_SPEAKER
from verbatim.llm.prompts import build_system_prompt


def _profile(**kwargs):
    base = {
        "pov_style": "third",
        "pov_characters": ["Alice"],
        "thought_convention": "none",
        "system_brackets": False,
        "narrator_notes": "",
    }
    base.update(kwargs)
    return base


def test_speaker_roster_in_prompt():
    prompt = build_system_prompt(_profile(), ["Alice", "Bob"])
    for name in ("Alice", "Bob", "Narrator", "Unknown", SYSTEM_SPEAKER):
        assert name in prompt


def test_pov_character_fills_in():
    prompt = build_system_prompt(_profile(pov_characters=["Zara"]), ["Zara"])
    assert "Zara" in prompt
    assert "A4" in prompt


def test_narrator_notes_section_present_when_set():
    prompt = build_system_prompt(_profile(narrator_notes="Epic fantasy, dry wit."), [])
    assert "Epic fantasy, dry wit." in prompt


def test_narrator_notes_section_absent_when_empty():
    prompt = build_system_prompt(_profile(narrator_notes=""), [])
    assert "NOVEL NOTES" not in prompt


def test_system_brackets_off_hides_s_kind():
    prompt = build_system_prompt(_profile(system_brackets=False), [])
    assert "[S]" not in prompt


def test_system_brackets_on_shows_s_kind():
    prompt = build_system_prompt(_profile(system_brackets=True), [])
    assert "[S]" in prompt
    assert SYSTEM_SPEAKER in prompt


def test_emotion_hints_section_present():
    hints = {"Alice": "stoic, cold default", "Bob": "cheerful, loud"}
    prompt = build_system_prompt(_profile(), ["Alice", "Bob"], character_hints=hints)
    assert "stoic, cold default" in prompt
    assert "cheerful, loud" in prompt


def test_emotion_hints_absent_when_empty():
    prompt = build_system_prompt(_profile(), ["Alice"])
    assert "EMOTION GUIDE" not in prompt


def test_no_pov_character_fallback():
    prompt = build_system_prompt(_profile(pov_characters=[]), [])
    assert "ATTRIBUTION RULES" in prompt
    assert "OUTPUT" in prompt
