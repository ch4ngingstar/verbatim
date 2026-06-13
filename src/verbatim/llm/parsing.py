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

    lower_words = [w.strip(",.!?:;\"'’‘“”()").lower() for w in words]

    if any(w in _DIALOGUE_PERSON_MARKERS for w in lower_words):
        return False
    if speaker_lower in lower_words:
        return True
    if len(words) >= _NARRATION_MIN_WORDS and any(
        w in _THIRD_PERSON_ACTORS for w in lower_words
    ):
        return True

    return False
