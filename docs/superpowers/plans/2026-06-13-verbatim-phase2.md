# Verbatim Phase 2 — Casting Director + Profile-Driven Diarizer

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the Casting Director (new LLM stage that reads the first ~10 chapters and drafts the Novel Profile + character list) and a profile-driven port of the Shadow Slave diarizer v2 (speaker roster, POV guard, and segmenter config all driven by the per-project Novel Profile stored in SQLite).

**Architecture:** Two new package directories: `src/verbatim/llm/` (three files — parsing utilities, prompt builder, LLMDirector class) and `src/verbatim/casting/` (CastingDirector class). The LLMDirector is a near-direct port of Shadow Slave's `llm_director.py` with three structural changes: (1) speakers loaded from `StateManager.list_characters(project_id)` not hardcoded, (2) `_pov_character` from `profile["pov_characters"][0]` not "Sunny", (3) `segment_chunk` called with `SegmenterConfig` built from the profile. CastingDirector is entirely new — same VRAM context-manager pattern, different system prompt and JSON schema. All tests monkeypatch `_call_llm`; zero GPU required.

**Tech Stack:** Python 3.11, llama-cpp-python (import-guarded), llama_cpp.LlamaGrammar (import-guarded), existing `StateManager` + `SegmenterConfig` from Phase 1.

**Source repo for ports:** `C:\Users\alityan\OneDrive\Desktop\shaodw salve\src\llm_director.py` — read it before implementing. Port = copy then modify as shown; never import from that repo.

**Spec:** `docs/superpowers/specs/2026-06-13-verbatim-design.md`

---

## File map

```
src/verbatim/
  llm/
    __init__.py          create — empty
    parsing.py           create — EMOTION_VOCAB, SYSTEM_SPEAKER, extract_json_block,
                                  parse_labels, is_narrator_misattribution,
                                  label_json_schema, allowed_speakers
    prompts.py           create — _SYSTEM_PROMPT_TEMPLATE, build_system_prompt()
    director.py          create — LLMDirector (VRAM context manager, profile-aware)
  casting/
    __init__.py          create — empty
    director.py          create — CastingDirector (VRAM context manager, new)
tests/
  test_llm_parsing.py    create
  test_llm_prompts.py    create
  test_llm_director.py   create
  test_casting_director.py  create
```

---

### Task 1: LLM parsing utilities

Port the stateless parsing/validation functions from Shadow Slave `llm_director.py`.
Changes: `SYSTEM_SPEAKER` renamed to `"System"` (not "The Nightmare Spell"); all imports updated to verbatim package paths; `_is_narrator_misattribution` is identical (generic — no "Sunny" reference).

**Files:**
- Create: `src/verbatim/llm/__init__.py`
- Create: `src/verbatim/llm/parsing.py`
- Create: `tests/test_llm_parsing.py`

- [ ] **Step 1: Write the failing tests**

`tests/test_llm_parsing.py`:

```python
import json
import pytest
from verbatim.llm.parsing import (
    EMOTION_VOCAB,
    SYSTEM_SPEAKER,
    allowed_speakers,
    extract_json_block,
    is_narrator_misattribution,
    label_json_schema,
    parse_labels,
)


def _lj(*labels):
    return json.dumps({"labels": [{"i": i, "speaker": s, "emotion": e} for i, s, e in labels]})


def test_extract_json_strips_markdown():
    assert extract_json_block('```json\n{"labels": []}\n```') == '{"labels": []}'


def test_extract_json_no_object_raises():
    with pytest.raises(ValueError, match="No JSON"):
        extract_json_block("plain text")


def test_extract_json_unterminated_raises():
    with pytest.raises(ValueError, match="Unterminated"):
        extract_json_block('{"key": ')


def test_parse_labels_happy_path():
    raw = _lj((0, "Narrator", "neutral"), (1, "Alice", "confused"))
    labels = parse_labels(raw, n_segments=2)
    assert labels[0] == ("Narrator", "neutral")
    assert labels[1] == ("Alice", "confused")


def test_parse_labels_missing_index_raises():
    raw = _lj((0, "Narrator", "neutral"))
    with pytest.raises(ValueError, match="unlabeled"):
        parse_labels(raw, n_segments=2)


def test_parse_labels_invalid_emotion_falls_back():
    raw = _lj((0, "Alice", "mega_rage"))
    assert parse_labels(raw, 1)[0][1] == "neutral"


def test_parse_labels_no_json_raises():
    with pytest.raises((ValueError, json.JSONDecodeError)):
        parse_labels("not json", n_segments=1)


def test_is_narrator_misattribution_third_person_opening():
    assert is_narrator_misattribution("Alice", "Alice walked into the room slowly.")
    assert is_narrator_misattribution("Alice", "She opened the door and stepped back.")


def test_is_narrator_misattribution_first_person_kept():
    assert not is_narrator_misattribution("Alice", "I have to run. Now.")
    assert not is_narrator_misattribution("Alice", "My name is Alice and I won't stop.")


def test_is_narrator_misattribution_narrator_always_false():
    assert not is_narrator_misattribution("Narrator", "Anything at all.")
    assert not is_narrator_misattribution("Unknown", "Whatever.")


def test_allowed_speakers_includes_fixed_labels():
    spks = allowed_speakers(["Alice", "Bob"])
    assert {"Narrator", "Unknown", SYSTEM_SPEAKER, "Alice", "Bob"} <= spks


def test_label_json_schema_speaker_enum():
    schema = label_json_schema(["Alice", "Bob"])
    enum = schema["properties"]["labels"]["items"]["properties"]["speaker"]["enum"]
    assert "Alice" in enum and "Narrator" in enum and "Unknown" in enum and SYSTEM_SPEAKER in enum


def test_system_speaker_is_generic():
    assert SYSTEM_SPEAKER == "System"


def test_emotion_vocab_contains_core():
    for e in ("neutral", "angry", "sad", "cold", "frightened"):
        assert e in EMOTION_VOCAB
```

- [ ] **Step 2: Run tests to verify they fail**

```powershell
cd "C:\Users\alityan\OneDrive\Desktop\verbatim"
.\.venv\Scripts\python -m pytest tests/test_llm_parsing.py -v
```

Expected: FAIL — `ModuleNotFoundError: verbatim.llm`.

- [ ] **Step 3: Create `src/verbatim/llm/__init__.py`**

Empty file.

- [ ] **Step 4: Write `src/verbatim/llm/parsing.py`**

```python
"""LLM response parsing utilities for the label-only diarizer.

Ported from Shadow Slave llm_director.py. Changes:
  * SYSTEM_SPEAKER is "System" (was "The Nightmare Spell" — novel-specific)
  * No Shadow-Slave-specific imports; all helpers are generic
"""

import json
import re
from typing import Any

EMOTION_VOCAB: list[str] = [
    "neutral", "whispers", "angry", "sad", "excited",
    "commanding", "frightened", "confused", "pleading",
    "cold", "laughing", "sarcastic", "desperate",
]

SYSTEM_SPEAKER: str = "System"

_DIALOGUE_PERSON_MARKERS: frozenset[str] = frozenset({
    "i", "i'm", "i'll", "i've", "i'd", "me", "my", "mine", "myself",
    "we", "we're", "we'll", "we've", "us", "our", "ours", "ourselves",
    "you", "you're", "you'll", "you've", "your", "yours", "yourself",
    "yourselves", "let's",
})

_THIRD_PERSON_ACTORS: frozenset[str] = frozenset({
    "he", "she", "they", "him", "her", "them", "his", "their", "its",
})

_NARRATION_MIN_WORDS: int = 6


def allowed_speakers(speakers: list[str]) -> set[str]:
    """Full set of valid speaker labels including fixed labels."""
    return {"Narrator", "Unknown", SYSTEM_SPEAKER, *speakers}


def label_json_schema(speakers: list[str]) -> dict[str, Any]:
    """JSON schema for grammar-locked LLM output."""
    return {
        "type": "object",
        "properties": {
            "labels": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "i":       {"type": "integer"},
                        "speaker": {"enum": sorted(allowed_speakers(speakers))},
                        "emotion": {"enum": EMOTION_VOCAB},
                    },
                    "required": ["i", "speaker", "emotion"],
                },
            },
        },
        "required": ["labels"],
    }


def extract_json_block(text: str) -> str:
    """Strip markdown fences and extract the first JSON object from text."""
    text = re.sub(r"```(?:json)?\s*", "", text).strip()
    start = text.find("{")
    if start == -1:
        raise ValueError("No JSON object found in LLM response")
    depth, end = 0, -1
    for i, ch in enumerate(text[start:], start):
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                end = i
                break
    if end == -1:
        raise ValueError("Unterminated JSON object in LLM response")
    return text[start : end + 1]


def parse_labels(response_text: str, n_segments: int) -> dict[int, tuple[str, str]]:
    """
    Parse the LLM response into {segment_index: (speaker, emotion)}.
    Raises ValueError when any segment index is missing — triggers a retry.
    """
    data = json.loads(extract_json_block(response_text))
    if "labels" not in data or not isinstance(data["labels"], list):
        raise ValueError(f"Response missing 'labels' array. Got: {list(data.keys())}")

    labels: dict[int, tuple[str, str]] = {}
    for item in data["labels"]:
        try:
            idx = int(item.get("i"))
        except (TypeError, ValueError):
            continue
        speaker = str(item.get("speaker", "Narrator"))
        emotion = str(item.get("emotion", "neutral"))
        if emotion not in EMOTION_VOCAB:
            emotion = "neutral"
        labels[idx] = (speaker, emotion)

    missing = [i for i in range(n_segments) if i not in labels]
    if missing:
        raise ValueError(
            f"Labels missing for segment indices {missing[:8]} "
            f"({len(missing)}/{n_segments} unlabeled)"
        )
    return labels


def is_narrator_misattribution(speaker: str, text: str) -> bool:
    """
    Heuristic: does this text read as third-person narration ABOUT the speaker
    rather than something they would say/think in first person?

    Used as the guard on the prose->POV-character exception in _merge_labels:
    keep the label only when this returns False.
    """
    if not text or not speaker or speaker in ("Narrator", "Unknown"):
        return False
    words = text.split()
    if not words:
        return False

    speaker_lower = speaker.lower()
    first_word = words[0].rstrip(",.!?:;").lower()

    if first_word in (speaker_lower, speaker_lower + "'s"):
        return True
    if first_word in _THIRD_PERSON_ACTORS:
        return True

    lower_words = [w.strip(",.!?:;\"‘’“”'()").lower() for w in words]

    if any(w in _DIALOGUE_PERSON_MARKERS for w in lower_words):
        return False
    if speaker_lower in lower_words:
        return True
    if len(words) >= _NARRATION_MIN_WORDS and any(
        w in _THIRD_PERSON_ACTORS for w in lower_words
    ):
        return True

    return False
```

- [ ] **Step 5: Run tests to verify they pass**

```powershell
.\.venv\Scripts\python -m pytest tests/test_llm_parsing.py -v
```

Expected: 14 PASS.

- [ ] **Step 6: Commit**

```powershell
git -C "C:\Users\alityan\OneDrive\Desktop\verbatim" add src/verbatim/llm/ tests/test_llm_parsing.py
git -C "C:\Users\alityan\OneDrive\Desktop\verbatim" commit -m "feat: LLM parsing utilities (extract_json_block, parse_labels, misattribution guard)"
```

---

### Task 2: Profile-driven system prompt

New code — no Shadow Slave equivalent. The system prompt template is generic (no "Shadow Slave", no "Sunny", no "Nephis"); profile fill-ins drive everything: speaker roster, POV character name, conditional [T]/[S] kind descriptions, per-character emotion hints, narrator notes.

**Files:**
- Create: `src/verbatim/llm/prompts.py`
- Create: `tests/test_llm_prompts.py`

- [ ] **Step 1: Write the failing tests**

`tests/test_llm_prompts.py`:

```python
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
    # A4 attribution rule references the POV character
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
    # Should not crash; should still be a valid string
    assert "ATTRIBUTION RULES" in prompt
    assert "OUTPUT" in prompt
```

- [ ] **Step 2: Run tests to verify they fail**

```powershell
.\.venv\Scripts\python -m pytest tests/test_llm_prompts.py -v
```

Expected: FAIL — `ModuleNotFoundError: verbatim.llm.prompts`.

- [ ] **Step 3: Write `src/verbatim/llm/prompts.py`**

```python
"""Profile-driven system prompt builder for the label-only diarizer.

build_system_prompt(profile, speakers, character_hints) fills a template with:
  - speaker roster from cast character names
  - POV character name for the prose inner-monologue exception (A4)
  - conditional [T] thought / [S] system segment kind lines
  - per-character emotion hints
  - narrator notes
"""

from typing import Any

from verbatim.llm.parsing import EMOTION_VOCAB, SYSTEM_SPEAKER

# {{ / }} are escaped literal braces in .format() strings.
# {variable} is a fill-in.  {pov_character} appears in the example output
# so the LLM sees the ACTUAL character name there after formatting.
_SYSTEM_PROMPT_TEMPLATE = """\
You label pre-split segments of a novel for a multi-voice audiobook. \
You NEVER output text -- only one speaker and one emotion label per segment.
{narrator_notes_section}
== SEGMENT KINDS ==
[D] dialogue -- words spoken aloud by a character. Label with the speaker's name.
[T] thought  -- inner monologue of the point-of-view character. \
Label with {pov_character_note}. NEVER label [T] as Narrator.
[P] prose    -- narration, description, actions, attribution tails ("she said"). Label Narrator.
{system_kind_line}
== SPEAKERS (use EXACTLY these names, nothing else) ==
{speakers_list}

== EMOTIONS ==
{emotions_list}

== ATTRIBUTION RULES ==
A1 Attribution tails name the speaker. In `1 [D] Wait, / 2 [P] Alice said`, segment 1 is Alice.
A2 With no tail, follow conversation flow: characters in a scene usually alternate turns.
A3 Only roster names are valid. Unnamed or unlisted characters -> Unknown. \
NEVER pick a roster name just because that character is mentioned nearby. When unsure -> Unknown.
A4 [P] segments are Narrator. ONE exception: a [P] segment clearly expressing the POV \
character's direct first-person thought ("Why me?", "I have to go.") may be labeled \
{pov_character}. Third-person prose about {pov_character} ("{pov_character} walked...", \
"He/She sighed...") is ALWAYS Narrator.
A5 [T] segments belong to whoever the scene follows. Even if the thought mentions others \
in third person ("She has been gone a month..."), it is still the POV character's thought -- \
not Narrator and not the person mentioned.
{system_rule_line}
{emotion_hints_section}
== EXAMPLE 1 ==
Input:
0 [P] Alice stared at the stranger, her expression unreadable.
1 [D] Who sent you?
2 [P] she asked quietly. The man shrugged.
3 [D] Someone you haven't met.
4 [T] He's lying. I can feel it.
Output:
{{"labels":[
{{"i":0,"speaker":"Narrator","emotion":"neutral"}},
{{"i":1,"speaker":"{pov_character}","emotion":"cold"}},
{{"i":2,"speaker":"Narrator","emotion":"neutral"}},
{{"i":3,"speaker":"Unknown","emotion":"neutral"}},
{{"i":4,"speaker":"{pov_character}","emotion":"cold"}}]}}

== EXAMPLE 2 (non-roster speakers -> Unknown) ==
Input:
0 [P] The guards exchanged uneasy glances.
1 [D] Who goes there?
2 [P] one of them demanded. Alice stepped forward.
3 [D] A traveler.
4 [P] she said calmly.
Output:
{{"labels":[
{{"i":0,"speaker":"Narrator","emotion":"neutral"}},
{{"i":1,"speaker":"Unknown","emotion":"commanding"}},
{{"i":2,"speaker":"Narrator","emotion":"neutral"}},
{{"i":3,"speaker":"{pov_character}","emotion":"neutral"}},
{{"i":4,"speaker":"Narrator","emotion":"neutral"}}]}}
Note: unnamed guards -> Unknown, never a roster name without evidence.

== OUTPUT ==
Return ONLY this JSON object, with exactly one label per input segment, in order:
{{"labels":[{{"i":0,"speaker":"...","emotion":"..."}}]}}"""


def build_system_prompt(
    profile: dict[str, Any],
    speakers: list[str],
    character_hints: "dict[str, str] | None" = None,
) -> str:
    """Render the diarizer system prompt from the project's Novel Profile."""
    pov_chars = profile.get("pov_characters") or []
    pov_character = pov_chars[0] if pov_chars else "the POV character"
    narrator_notes = str(profile.get("narrator_notes") or "").strip()
    system_brackets = bool(profile.get("system_brackets", 0))

    roster = ["Narrator"] + list(speakers) + ["Unknown", SYSTEM_SPEAKER]

    narrator_notes_section = (
        f"\n== NOVEL NOTES ==\n{narrator_notes}\n" if narrator_notes else ""
    )
    pov_character_note = (
        f"{pov_character} (the POV character)" if pov_chars else "the scene's POV character"
    )
    system_kind_line = (
        f"[S] system   -- [bracketed] in-world notification. Label {SYSTEM_SPEAKER}.\n"
        if system_brackets
        else ""
    )
    system_rule_line = (
        f"A6 [S] segments: in-world notifications -> {SYSTEM_SPEAKER}. "
        "If surrounding prose shows a character sending/receiving it, label that character.\n"
        if system_brackets
        else ""
    )
    emotion_hints_section = _build_emotion_hints_section(character_hints or {})

    return _SYSTEM_PROMPT_TEMPLATE.format(
        narrator_notes_section=narrator_notes_section,
        pov_character_note=pov_character_note,
        pov_character=pov_character,
        system_kind_line=system_kind_line,
        system_rule_line=system_rule_line,
        speakers_list="\n".join(roster),
        emotions_list=", ".join(EMOTION_VOCAB),
        emotion_hints_section=emotion_hints_section,
    )


def _build_emotion_hints_section(hints: dict[str, str]) -> str:
    if not hints:
        return ""
    lines = [
        "== EMOTION GUIDE ==",
        "Narrator: neutral default / frightened in horror / excited at revelations",
    ]
    for name, hint in hints.items():
        if hint:
            lines.append(f"{name}: {hint}")
    lines.append(
        "Dialogue emotion follows the words: questions -> confused, "
        "threats -> cold or angry, shouting -> angry or excited, hushed -> whispers."
    )
    return "\n".join(lines) + "\n"
```

- [ ] **Step 4: Run tests to verify they pass**

```powershell
.\.venv\Scripts\python -m pytest tests/test_llm_prompts.py -v
```

Expected: 9 PASS.

- [ ] **Step 5: Commit**

```powershell
git -C "C:\Users\alityan\OneDrive\Desktop\verbatim" add src/verbatim/llm/prompts.py tests/test_llm_prompts.py
git -C "C:\Users\alityan\OneDrive\Desktop\verbatim" commit -m "feat: profile-driven diarizer system prompt (pov, thought/system flags, emotion hints)"
```

---

### Task 3: LLMDirector (profile-aware diarizer)

Port of `SHADOW\src\llm_director.py`. Key changes from source:
1. Constructor: `__init__(model_path, sm, project_id, cfg=None)` — no `speakers` arg.
2. `_setup_from_profile()`: new method that loads the project profile + cast from SM, builds `SegmenterConfig`, system prompt, and grammar. Called in `__enter__`. Separated so tests can call it without loading a model.
3. `_merge_labels()`: uses `self._pov_character` (from profile) instead of hardcoded `"Sunny"`.
4. `_process_chunk()`: calls `segment_chunk(text, self._segmenter_config)` with the config.
5. `print(...)` → `log.info(...)` / `log.debug(...)`.
6. Remove `DEFAULT_SPEAKERS` constant entirely.

**Files:**
- Create: `src/verbatim/llm/director.py`
- Create: `tests/test_llm_director.py`

- [ ] **Step 1: Write the failing tests**

`tests/test_llm_director.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

```powershell
.\.venv\Scripts\python -m pytest tests/test_llm_director.py -v
```

Expected: FAIL — `ModuleNotFoundError: verbatim.llm.director`.

- [ ] **Step 3: Write `src/verbatim/llm/director.py`**

Read `C:\Users\alityan\OneDrive\Desktop\shaodw salve\src\llm_director.py` first. Then write:

```python
"""LLM Director — label-only two-pass diarizer (Module 3).

Pass 1: SegmenterConfig (built from the Novel Profile) drives segment_chunk().
Pass 2: this module asks the local LLM to label each segment (speaker + emotion
        only — it never reproduces text). Grammar-locked JSON schema.

VRAM lifecycle: use as a context manager. Model loads in __enter__, purges in __exit__.
Never instantiate while the TTS engine is loaded (~12 GB VRAM constraint).

    with LLMDirector("models/Qwen3-14B-Q4_K_M.gguf", sm, project_id=pid) as d:
        d.process_chapter(chapter_id)
    # <- model fully unloaded here
"""

import gc
import json
import logging
import time
from pathlib import Path
from typing import Any, Optional

try:
    from llama_cpp import Llama
    from llama_cpp.llama_grammar import LlamaGrammar
    _LLAMA_AVAILABLE = True
except ImportError:
    _LLAMA_AVAILABLE = False

from verbatim.db.manager import StateManager
from verbatim.ingest.segmenter import KIND_DIALOGUE, KIND_PROSE, KIND_SYSTEM, KIND_THOUGHT
from verbatim.ingest.segmenter import SegmenterConfig, segment_chunk
from verbatim.llm.parsing import (
    EMOTION_VOCAB, SYSTEM_SPEAKER,
    allowed_speakers, extract_json_block, is_narrator_misattribution,
    label_json_schema, parse_labels,
)
from verbatim.llm.prompts import build_system_prompt

log = logging.getLogger(__name__)

_KIND_TAGS = {KIND_DIALOGUE: "D", KIND_THOUGHT: "T", KIND_SYSTEM: "S", KIND_PROSE: "P"}

_DEFAULT_CFG: dict[str, Any] = {
    "n_ctx":        8192,
    "n_batch":      512,
    "n_gpu_layers": -1,
    "flash_attn":   True,
    "verbose":      False,
    "temperature":  0.2,
    "top_p":        0.8,
    "max_tokens":   4096,
    "retry_temp":   0.5,
    "max_retries":  3,
}


class LLMDirector:
    """
    Profile-aware LLM director. Must be used as a context manager.

        with LLMDirector("models/model.gguf", sm, project_id=pid) as d:
            d.process_chapter(chapter_id)
    """

    def __init__(
        self,
        model_path: "str | Path",
        sm: StateManager,
        project_id: int,
        cfg: "dict[str, Any] | None" = None,
    ):
        self.model_path = Path(model_path)
        self.sm = sm
        self.project_id = project_id
        self.cfg = {**_DEFAULT_CFG, **(cfg or {})}
        self._llm: Any = None
        self._grammar: Any = None
        # Populated by _setup_from_profile():
        self._system_prompt: str = ""
        self._allowed: set[str] = set()
        self._pov_character: str = "Narrator"
        self._segmenter_config: SegmenterConfig = SegmenterConfig()

    # -- Context manager (VRAM lifecycle) ------------------------------------

    def __enter__(self) -> "LLMDirector":
        if not _LLAMA_AVAILABLE:
            raise RuntimeError(
                "llama-cpp-python is not installed. "
                "Run: pip install llama-cpp-python --extra-index-url "
                "https://abetlen.github.io/llama-cpp-python/whl/cu124"
            )
        if not self.model_path.exists():
            raise FileNotFoundError(f"GGUF model not found: {self.model_path}")
        log.info("Loading model: %s", self.model_path.name)
        llama_kwargs: dict[str, Any] = dict(
            model_path=str(self.model_path),
            n_gpu_layers=self.cfg["n_gpu_layers"],
            n_ctx=self.cfg["n_ctx"],
            n_batch=self.cfg["n_batch"],
            flash_attn=self.cfg.get("flash_attn", True),
            verbose=self.cfg["verbose"],
        )
        try:
            self._llm = Llama(**llama_kwargs)
        except TypeError:
            llama_kwargs.pop("flash_attn", None)
            self._llm = Llama(**llama_kwargs)
        self._setup_from_profile()
        log.info("Model loaded.")
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> bool:
        self._purge_vram()
        return False

    def _purge_vram(self) -> None:
        if self._llm is not None:
            log.info("Unloading model from VRAM...")
            del self._llm
            self._llm = None
        self._grammar = None
        gc.collect()
        try:
            import torch
            torch.cuda.empty_cache()
            log.info("CUDA cache cleared.")
        except ImportError:
            pass
        log.info("VRAM released.")

    def _setup_from_profile(self) -> None:
        """Load project profile + cast from SM; build segmenter config, prompt, grammar.

        Separated from __enter__ so tests can call it without a real model loaded.
        """
        profile = self.sm.get_project_by_id(self.project_id) or {}
        characters = self.sm.list_characters(self.project_id)
        speakers = [c["name"] for c in characters if c["status"] == "cast"]
        hints = {c["name"]: c["emotion_hint"] for c in characters if c.get("emotion_hint")}

        pov_chars = profile.get("pov_characters") or []
        self._pov_character = pov_chars[0] if pov_chars else "Narrator"
        self._segmenter_config = SegmenterConfig(
            single_quote_thoughts=profile.get("thought_convention") == "single_quotes",
            bracket_system_lines=bool(profile.get("system_brackets", 0)),
        )
        self._allowed = allowed_speakers(speakers)
        self._system_prompt = build_system_prompt(profile, speakers, hints)
        self._grammar = self._build_grammar(speakers)

    def _build_grammar(self, speakers: list[str]) -> Any:
        """GBNF grammar from the label JSON schema. None on failure -> json_object fallback."""
        if not _LLAMA_AVAILABLE:
            return None
        try:
            schema = json.dumps(label_json_schema(speakers))
            return LlamaGrammar.from_json_schema(schema, verbose=False)
        except Exception as e:
            log.warning("Grammar build failed (%s); falling back to response_format=json_object", e)
            return None

    # -- Public API -----------------------------------------------------------

    def process_chapter(self, chapter_id: int) -> int:
        """
        Diarize all chunks for a chapter and persist results to the DB.
        Returns total number of lines written. Sets chapter status to 'diarized'.
        """
        chunks = self.sm.get_chunks_for_chapter(chapter_id)
        if not chunks:
            raise ValueError(f"No chunks found for chapter_id={chapter_id}")

        log.info("Processing chapter_id=%d (%d chunks)...", chapter_id, len(chunks))
        all_lines: list[dict[str, Any]] = []
        for chunk in chunks:
            log.info("  Chunk %d/%d (%d words)...",
                     chunk["chunk_index"] + 1, len(chunks), chunk["word_count"])
            lines = self._process_chunk(chunk["text"], line_offset=len(all_lines))
            all_lines.extend(lines)
            log.info("  -> %d lines", len(lines))

        self.sm.save_diarized_lines(chapter_id, all_lines)
        log.info("Chapter %d diarized: %d total lines.", chapter_id, len(all_lines))
        return len(all_lines)

    # -- Internal: segment formatting / merging ------------------------------

    @staticmethod
    def _format_segments(segments: list[dict[str, Any]]) -> str:
        return "\n".join(
            f"{s['index']} [{_KIND_TAGS[s['kind']]}] {s['text']}" for s in segments
        )

    def _merge_labels(
        self,
        segments: list[dict[str, Any]],
        labels: dict[int, tuple[str, str]],
        line_offset: int,
    ) -> list[dict[str, Any]]:
        """Apply structural speaker enforcement and produce final line dicts."""
        lines: list[dict[str, Any]] = []
        for seg in segments:
            speaker, emotion = labels[seg["index"]]
            kind, text = seg["kind"], seg["text"]

            if kind == KIND_PROSE:
                # Keep POV character's genuine first-person inner thought only.
                if not (
                    speaker == self._pov_character
                    and not is_narrator_misattribution(speaker, text)
                ):
                    if speaker != "Narrator":
                        log.debug("FIX  prose %r -> Narrator | %r", speaker, text[:60])
                    speaker = "Narrator"
            elif kind == KIND_THOUGHT:
                # Structural evidence: it IS a thought. Trust POV label; repair impossible ones.
                if speaker not in self._allowed or speaker == SYSTEM_SPEAKER:
                    speaker = self._pov_character
            elif kind == KIND_SYSTEM:
                # Brackets carry notifications AND telepathic messages — keep any valid roster label.
                if speaker not in self._allowed:
                    speaker = SYSTEM_SPEAKER
            else:  # dialogue
                if speaker not in self._allowed or speaker == "Narrator":
                    speaker = "Unknown"

            if emotion not in EMOTION_VOCAB:
                emotion = "neutral"

            lines.append({
                "line_index": line_offset + len(lines),
                "speaker":    speaker,
                "text":       text,
                "emotion":    emotion,
            })
        return lines

    def _fallback_lines(
        self, segments: list[dict[str, Any]], line_offset: int
    ) -> list[dict[str, Any]]:
        """Total-failure fallback: sensible per-kind defaults, all text preserved."""
        defaults: dict[str, tuple[str, str]] = {
            KIND_DIALOGUE: ("Unknown",              "neutral"),
            KIND_THOUGHT:  (self._pov_character,    "neutral"),
            KIND_SYSTEM:   (SYSTEM_SPEAKER,         "cold"),
            KIND_PROSE:    ("Narrator",             "neutral"),
        }
        return [
            {
                "line_index": line_offset + i,
                "speaker":    defaults[seg["kind"]][0],
                "text":       seg["text"],
                "emotion":    defaults[seg["kind"]][1],
            }
            for i, seg in enumerate(segments)
        ]

    # -- Internal: retry loop ------------------------------------------------

    def _process_chunk(self, text: str, line_offset: int) -> list[dict[str, Any]]:
        segments = segment_chunk(text, self._segmenter_config)
        if not segments:
            return []

        user_msg = self._format_segments(segments)
        if "qwen3" in self.model_path.name.lower():
            user_msg += "\n/no_think"

        last_error: Optional[Exception] = None
        for attempt in range(self.cfg["max_retries"]):
            temp = self.cfg["temperature"] if attempt == 0 else self.cfg["retry_temp"]
            try:
                raw    = self._call_llm(user_msg, temperature=temp)
                labels = parse_labels(raw, n_segments=len(segments))
                return self._merge_labels(segments, labels, line_offset)
            except (ValueError, json.JSONDecodeError, KeyError, TypeError) as e:
                last_error = e
                log.warning("Label parse error (attempt %d): %s", attempt + 1, e)
                time.sleep(0.5)

        log.warning("All retries failed (%s). Falling back to per-segment defaults.", last_error)
        return self._fallback_lines(segments, line_offset)

    # -- Raw LLM call (injectable for testing) --------------------------------

    def _call_llm(self, text: str, temperature: float = 0.2) -> str:
        """Single inference call. Separated so tests can monkeypatch this."""
        if self._llm is None:
            raise RuntimeError(
                "LLMDirector must be used inside a 'with' block. Model is not loaded."
            )
        kwargs: dict[str, Any] = {
            "messages": [
                {"role": "system", "content": self._system_prompt},
                {"role": "user",   "content": text},
            ],
            "temperature": temperature,
            "top_p":       self.cfg.get("top_p", 0.8),
            "max_tokens":  self.cfg["max_tokens"],
        }
        if self._grammar is not None:
            kwargs["grammar"] = self._grammar
        else:
            kwargs["response_format"] = {"type": "json_object"}
        response = self._llm.create_chat_completion(**kwargs)
        return response["choices"][0]["message"]["content"]
```

- [ ] **Step 4: Run tests to verify they pass**

```powershell
.\.venv\Scripts\python -m pytest tests/test_llm_director.py -v
```

Expected: 16 PASS.

- [ ] **Step 5: Run all existing tests to check for regressions**

```powershell
.\.venv\Scripts\python -m pytest -v
```

Expected: all pass (~49 total).

- [ ] **Step 6: Commit**

```powershell
git -C "C:\Users\alityan\OneDrive\Desktop\verbatim" add src/verbatim/llm/director.py tests/test_llm_director.py
git -C "C:\Users\alityan\OneDrive\Desktop\verbatim" commit -m "feat: profile-aware LLMDirector - pov character, SegmenterConfig, cast roster from DB"
```

---

### Task 4: Casting Director

New module — no Shadow Slave equivalent. Reads the first N chapters, sends text to the LLM with a structured analysis prompt, parses the JSON response, and writes draft profile fields and character list to the DB. Same VRAM context-manager pattern as `LLMDirector`.

**Files:**
- Create: `src/verbatim/casting/__init__.py`
- Create: `src/verbatim/casting/director.py`
- Create: `tests/test_casting_director.py`

- [ ] **Step 1: Write the failing tests**

`tests/test_casting_director.py`:

```python
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
            "chunks": [{"chunk_index": 0, "text": f"Chapter {i + 1} sample text.", "word_count": 4}],
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
```

- [ ] **Step 2: Run tests to verify they fail**

```powershell
.\.venv\Scripts\python -m pytest tests/test_casting_director.py -v
```

Expected: FAIL — `ModuleNotFoundError: verbatim.casting`.

- [ ] **Step 3: Create `src/verbatim/casting/__init__.py`**

Empty file.

- [ ] **Step 4: Write `src/verbatim/casting/director.py`**

```python
"""Casting Director — new pipeline stage between EPUB parse and diarization.

Reads the first N chapters, sends a sample to the local LLM, and receives a
structured JSON draft of the Novel Profile (POV style, thought convention,
narrator notes) plus a ranked character list. Writes directly to the DB via
StateManager; the user then reviews/edits the draft in the Casting Studio UI
before triggering diarization.

VRAM lifecycle: use as a context manager — model loads in __enter__, purges in __exit__.
Never run concurrently with LLMDirector or TTSEngine (~12 GB VRAM constraint).

    with CastingDirector("models/model.gguf", sm, project_id=pid) as cd:
        draft = cd.run()
    # <- model fully unloaded here
"""

import gc
import json
import logging
from pathlib import Path
from typing import Any

try:
    from llama_cpp import Llama
    _LLAMA_AVAILABLE = True
except ImportError:
    _LLAMA_AVAILABLE = False

from verbatim.db.manager import StateManager
from verbatim.db.schema import POV_STYLES, THOUGHT_CONVENTIONS
from verbatim.llm.parsing import extract_json_block

log = logging.getLogger(__name__)

_CASTING_SYSTEM_PROMPT = """\
You analyze the opening chapters of a novel to identify characters and narrative structure \
for a multi-voice audiobook production.

Return ONLY this JSON object, filled in for the given text:
{
  "pov_style": "third",
  "pov_characters": ["Name"],
  "thought_convention": "none",
  "narrator_notes": "One sentence describing narrator style.",
  "characters": [
    {
      "name": "canonical full name",
      "aliases": ["other names seen in text"],
      "is_pov": false,
      "emotion_hint": "brief personality note, e.g. stoic, cold default"
    }
  ]
}

Rules:
- Include ONLY named characters who speak, act, or are named in scenes
- List characters in order of importance (most appearances first)
- "aliases" lists EVERY other name used for this character in the text
- "pov_style": "first" if narrated in first person ("I walked in"), "third" otherwise
- "pov_characters": the character(s) whose perspective the narration follows
- "thought_convention": "single_quotes" if 'single-quoted spans' mark inner thoughts, "none" otherwise
- "emotion_hint": one line, e.g. "warm, enthusiastic" or "stoic, rarely emotional"
- "narrator_notes": brief style note, e.g. "Third-person limited. Dry, ironic tone."
"""

_CASTING_USER_PREFIX = (
    "Analyze the following novel excerpt and return the character profile JSON.\n\n"
)

_DEFAULT_CFG: dict[str, Any] = {
    "n_ctx":        8192,
    "n_batch":      512,
    "n_gpu_layers": -1,
    "flash_attn":   True,
    "verbose":      False,
    "temperature":  0.3,
    "top_p":        0.9,
    "max_tokens":   2048,
}


class CastingDirector:
    """
    Reads the first `n_chapters` chapters, calls the LLM for a character draft,
    and writes the result to the DB. Must be used as a context manager.

        with CastingDirector("models/model.gguf", sm, project_id=pid) as cd:
            draft = cd.run()
    """

    def __init__(
        self,
        model_path: "str | Path",
        sm: StateManager,
        project_id: int,
        cfg: "dict[str, Any] | None" = None,
        n_chapters: int = 10,
    ):
        self.model_path = Path(model_path)
        self.sm = sm
        self.project_id = project_id
        self.cfg = {**_DEFAULT_CFG, **(cfg or {})}
        self.n_chapters = n_chapters
        self._llm: Any = None

    # -- Context manager (VRAM lifecycle) ------------------------------------

    def __enter__(self) -> "CastingDirector":
        if not _LLAMA_AVAILABLE:
            raise RuntimeError(
                "llama-cpp-python is not installed. "
                "Run: pip install llama-cpp-python --extra-index-url "
                "https://abetlen.github.io/llama-cpp-python/whl/cu124"
            )
        if not self.model_path.exists():
            raise FileNotFoundError(f"GGUF model not found: {self.model_path}")
        log.info("CastingDirector: loading model %s", self.model_path.name)
        llama_kwargs: dict[str, Any] = dict(
            model_path=str(self.model_path),
            n_gpu_layers=self.cfg["n_gpu_layers"],
            n_ctx=self.cfg["n_ctx"],
            n_batch=self.cfg["n_batch"],
            flash_attn=self.cfg.get("flash_attn", True),
            verbose=self.cfg["verbose"],
        )
        try:
            self._llm = Llama(**llama_kwargs)
        except TypeError:
            llama_kwargs.pop("flash_attn", None)
            self._llm = Llama(**llama_kwargs)
        log.info("CastingDirector: model loaded.")
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> bool:
        if self._llm is not None:
            log.info("CastingDirector: unloading model...")
            del self._llm
            self._llm = None
        gc.collect()
        try:
            import torch
            torch.cuda.empty_cache()
        except ImportError:
            pass
        log.info("CastingDirector: VRAM released.")
        return False

    # -- Public API ----------------------------------------------------------

    def run(self) -> dict[str, Any]:
        """
        Read first n_chapters, call LLM, write profile + characters to DB.
        Returns the parsed draft dict.
        """
        sample_text = self._assemble_sample_text()
        user_message = _CASTING_USER_PREFIX + sample_text
        raw = self._call_llm(user_message)
        draft = self._parse_response(raw)
        self._write_to_db(draft)
        log.info(
            "CastingDirector: drafted %d characters, pov=%s, thought_convention=%s",
            len(draft["characters"]), draft["pov_style"], draft["thought_convention"],
        )
        return draft

    # -- Internal ------------------------------------------------------------

    def _assemble_sample_text(self) -> str:
        """Gather the first n_chapters chapters' chunk texts."""
        chapters = self.sm.get_all_chapters(self.project_id)
        sample_chapters = chapters[: self.n_chapters]
        parts: list[str] = []
        for ch in sample_chapters:
            chunks = self.sm.get_chunks_for_chapter(ch["id"])
            chapter_text = "\n\n".join(ck["text"] for ck in chunks)
            parts.append(f"=== {ch['title']} ===\n{chapter_text}")
        return "\n\n".join(parts)

    def _parse_response(self, raw: str) -> dict[str, Any]:
        """Parse and validate the LLM JSON response."""
        data = json.loads(extract_json_block(raw))

        pov_style = str(data.get("pov_style", "third"))
        if pov_style not in POV_STYLES:
            pov_style = "third"

        thought_convention = str(data.get("thought_convention", "none"))
        if thought_convention not in THOUGHT_CONVENTIONS:
            thought_convention = "none"

        pov_characters = [str(n) for n in data.get("pov_characters", []) if n]
        narrator_notes = str(data.get("narrator_notes", "") or "").strip()

        characters: list[dict[str, Any]] = []
        for c in data.get("characters", []):
            name = str(c.get("name", "")).strip()
            if not name:
                continue
            characters.append({
                "name":         name,
                "aliases":      [str(a) for a in c.get("aliases", []) if a],
                "is_pov":       bool(c.get("is_pov", False)),
                "emotion_hint": str(c.get("emotion_hint", "") or "").strip(),
            })

        return {
            "pov_style":          pov_style,
            "pov_characters":     pov_characters,
            "thought_convention": thought_convention,
            "narrator_notes":     narrator_notes,
            "characters":         characters,
        }

    def _write_to_db(self, draft: dict[str, Any]) -> None:
        """Persist the draft profile and character list to the DB."""
        self.sm.update_profile(
            self.project_id,
            pov_style=draft["pov_style"],
            pov_characters=draft["pov_characters"],
            thought_convention=draft["thought_convention"],
            narrator_notes=draft["narrator_notes"],
        )
        for char in draft["characters"]:
            self.sm.upsert_character(
                self.project_id,
                name=char["name"],
                aliases=char["aliases"],
                is_pov=char["is_pov"],
                emotion_hint=char["emotion_hint"],
                status="suggested",
            )

    def _call_llm(self, user_text: str) -> str:
        """Single inference call. Separated so tests can monkeypatch this."""
        if self._llm is None:
            raise RuntimeError(
                "CastingDirector must be used inside a 'with' block. Model is not loaded."
            )
        response = self._llm.create_chat_completion(
            messages=[
                {"role": "system", "content": _CASTING_SYSTEM_PROMPT},
                {"role": "user",   "content": user_text},
            ],
            temperature=self.cfg["temperature"],
            top_p=self.cfg.get("top_p", 0.9),
            max_tokens=self.cfg["max_tokens"],
            response_format={"type": "json_object"},
        )
        return response["choices"][0]["message"]["content"]
```

- [ ] **Step 5: Run tests to verify they pass**

```powershell
.\.venv\Scripts\python -m pytest tests/test_casting_director.py -v
```

Expected: 8 PASS.

- [ ] **Step 6: Run full suite to check for regressions**

```powershell
.\.venv\Scripts\python -m pytest -v
```

Expected: all pass (~57 total).

- [ ] **Step 7: Commit**

```powershell
git -C "C:\Users\alityan\OneDrive\Desktop\verbatim" add src/verbatim/casting/ tests/test_casting_director.py
git -C "C:\Users\alityan\OneDrive\Desktop\verbatim" commit -m "feat: CastingDirector - LLM drafts Novel Profile + character list from first N chapters"
```

---

### Task 5: Lint, typecheck, final test run

**Files:** None created. Fix anything ruff or mypy surface.

- [ ] **Step 1: Run ruff**

```powershell
cd "C:\Users\alityan\OneDrive\Desktop\verbatim"
.\.venv\Scripts\python -m ruff check .
```

Expected: `All checks passed!`. Common issues to fix if they appear:
- Unused imports → remove them.
- `dict` without type args → `dict[str, Any]`.
- Missing trailing comma in multi-line dict → add it.

- [ ] **Step 2: Run mypy**

```powershell
.\.venv\Scripts\python -m mypy src
```

Expected: `Success: no issues found`. Common issues:
- `Any` not imported where used → add `from typing import Any`.
- Return type missing → add annotation.
- Never use `# type: ignore` — fix the root cause.

- [ ] **Step 3: Run the full test suite**

```powershell
.\.venv\Scripts\python -m pytest -v
```

Expected: all tests pass (~57 tests).

- [ ] **Step 4: Commit any fixes** (only if there were issues to fix)

```powershell
git -C "C:\Users\alityan\OneDrive\Desktop\verbatim" add -A
git -C "C:\Users\alityan\OneDrive\Desktop\verbatim" commit -m "fix: ruff and mypy clean-up for Phase 2 modules"
```

If there were no issues, skip this commit.

---

## Self-review notes

**Spec coverage check (Phase 2 scope):**
- Casting Director reads first ~10 chapters + calls LLM + writes draft profile + characters ✅ (Task 4)
- Characters ranked by importance: upsert writes to DB; ranking happens in `list_characters()` ORDER BY `line_count DESC` (line_count populated by diarizer in Phase 3 — casting director only seeds them at 0 initially, ordering by LLM response order is acceptable for the draft) ✅
- Profile-driven diarizer: speaker roster from SM, POV character from profile, `SegmenterConfig` from profile ✅ (Task 3)
- `SPEAKER_ALIASES` constant eliminated → aliases come from `get_alias_map(project_id)` ✅ (Phase 1 data layer already provides this; diarizer will call it in Phase 3 orchestration)
- Advisory checkpoints (Phase 4 concern) ✅ not in scope for Phase 2
- Grammar-locked JSON schema retained ✅
- Retry loop + fallback retained ✅
- VRAM context manager retained in both directors ✅
- GPU-free tests: all tests monkeypatch `_call_llm` ✅

**Placeholder scan:** None.

**Type consistency:**
- `_setup_from_profile()` sets `self._pov_character: str`, `self._segmenter_config: SegmenterConfig`, `self._allowed: set[str]` — all referenced in `_merge_labels` and `_fallback_lines` ✅
- `CastingDirector.run()` → `_parse_response()` → `_write_to_db()` — return type `dict[str, Any]` threaded through ✅
- `extract_json_block` imported from `verbatim.llm.parsing` in both `director.py` files ✅
- `POV_STYLES`, `THOUGHT_CONVENTIONS` from `verbatim.db.schema` used in `CastingDirector._parse_response()` for validation ✅
