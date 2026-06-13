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
