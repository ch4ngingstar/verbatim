import pytest

from tests.test_projects import PARSED
from verbatim.db.manager import StateManager


@pytest.fixture
def sm(tmp_path):
    return StateManager(tmp_path / "t.db")


@pytest.fixture
def pid(sm):
    return sm.seed_project(PARSED)


def test_character_upsert_and_ranking(sm, pid):
    sm.upsert_character(pid, "Sunny", aliases=["Lost From Light"], is_pov=True)
    sm.upsert_character(pid, "Nephis", aliases=["Changing Star"])
    sm.update_character_stats(pid, "Nephis", line_count=50, chapter_count=9)
    sm.update_character_stats(pid, "Sunny", line_count=120, chapter_count=10)
    chars = sm.list_characters(pid)
    assert [c["name"] for c in chars] == ["Sunny", "Nephis"]  # ranked by line_count desc
    assert chars[0]["aliases"] == ["Lost From Light"]
    assert chars[0]["is_pov"] == 1


def test_upsert_updates_existing(sm, pid):
    cid = sm.upsert_character(pid, "Sunny")
    cid2 = sm.upsert_character(pid, "Sunny", aliases=["Shadow"], emotion_hint="dry wit")
    assert cid == cid2
    chars = sm.list_characters(pid)
    assert len(chars) == 1
    assert chars[0]["aliases"] == ["Shadow"]


def test_character_status_validation(sm, pid):
    cid = sm.upsert_character(pid, "Jet")
    sm.set_character_status(cid, "cast")
    with pytest.raises(ValueError):
        sm.set_character_status(cid, "fired")


def test_voice_library_and_casting(sm, pid):
    vid = sm.add_voice("Deep Male", "voices/deep_male.wav", tags=["male", "deep"])
    assert sm.list_voices()[0]["tags"] == ["male", "deep"]
    cid = sm.upsert_character(pid, "Sunny")
    sm.assign_voice(cid, vid)
    chars = sm.list_characters(pid)
    assert chars[0]["voice_id"] == vid
    assert chars[0]["voice_path"] == "voices/deep_male.wav"  # joined for convenience
    assert sm.delete_voice(vid)
    assert sm.list_characters(pid)[0]["voice_id"] is None  # ON DELETE SET NULL


def test_alias_map_resolution(sm, pid):
    sm.upsert_character(pid, "Nephis", aliases=["Changing Star", "Neph"])
    amap = sm.get_alias_map(pid)
    assert amap["nephis"] == amap["changing star"] == amap["neph"]


def test_get_voice_by_id(sm, pid):
    vid = sm.add_voice("TestVoice", "voices/test.wav", tags=["test"])
    v = sm.get_voice_by_id(vid)
    assert v is not None
    assert v["name"] == "TestVoice"
    assert v["tags"] == ["test"]
    assert sm.get_voice_by_id(99999) is None


def test_get_voice_by_name(sm, pid):
    sm.add_voice("NamedVoice", "voices/named.wav")
    v = sm.get_voice_by_name("NamedVoice")
    assert v is not None
    assert v["name"] == "NamedVoice"
    assert sm.get_voice_by_name("no-such-voice") is None
