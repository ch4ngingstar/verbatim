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
NEVER pick a roster name just because that character is nearby. When unsure -> Unknown.
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
{{"labels":[{{"i":0,"speaker":"...","emotion":"..."}}]}}\
"""


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
