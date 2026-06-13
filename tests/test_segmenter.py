from verbatim.ingest.segmenter import SegmenterConfig, segment_chunk

DEFAULT = SegmenterConfig()
SHADOW_LIKE = SegmenterConfig(single_quote_thoughts=True, bracket_system_lines=True)


def kinds(segs):
    return [s["kind"] for s in segs]


def texts(segs):
    return [s["text"] for s in segs]


def test_dialogue_split_always_on():
    segs = segment_chunk('Anna smiled. "Hello there." She left.', DEFAULT)
    assert kinds(segs) == ["prose", "dialogue", "prose"]
    assert texts(segs) == ["Anna smiled.", "Hello there.", "She left."]


def test_unbalanced_quote_falls_back_to_prose():
    segs = segment_chunk('He said "never mind.', DEFAULT)
    assert kinds(segs) == ["prose"]


def test_thoughts_off_by_default():
    segs = segment_chunk("'Why me?' Sunny wondered.", DEFAULT)
    assert kinds(segs) == ["prose"]


def test_thoughts_on_with_profile_flag():
    segs = segment_chunk("'Why me?' Sunny wondered.", SHADOW_LIKE)
    assert kinds(segs) == ["thought", "prose"]
    assert texts(segs)[0] == "Why me?"


def test_contractions_never_trigger_thoughts():
    segs = segment_chunk("It was Sunny's turn, and he won't run.", SHADOW_LIKE)
    assert kinds(segs) == ["prose"]


def test_system_brackets_off_by_default():
    segs = segment_chunk("[Quest Complete]", DEFAULT)
    assert kinds(segs) == ["prose"]


def test_system_brackets_on_with_profile_flag():
    segs = segment_chunk("[Quest Complete] [Reward: Shadow Essence]", SHADOW_LIKE)
    assert kinds(segs) == ["system", "system"]
    assert texts(segs) == ["[Quest Complete]", "[Reward: Shadow Essence]"]


def test_indices_are_sequential():
    segs = segment_chunk('A. "B." C.\n\n"D."', DEFAULT)
    assert [s["index"] for s in segs] == list(range(len(segs)))


def test_empty_input():
    assert segment_chunk("", DEFAULT) == []
    assert segment_chunk(None, DEFAULT) == []
