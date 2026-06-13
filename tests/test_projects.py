import pytest

from verbatim.db.manager import StateManager


@pytest.fixture
def sm(tmp_path):
    return StateManager(tmp_path / "t.db")


PARSED = {
    "source_epub": "mybook.epub",
    "total_chapters": 2,
    "chapters": [
        {"chapter_index": 0, "title": "One",
         "chunks": [{"chunk_index": 0, "text": "Hello world.", "word_count": 2}]},
        {"chapter_index": 1, "title": "Two",
         "chunks": [{"chunk_index": 0, "text": "Bye.", "word_count": 1}]},
    ],
}


def test_seed_project_creates_rows(sm):
    pid = sm.seed_project(PARSED)
    proj = sm.get_project_by_id(pid)
    assert proj["name"] == "mybook"
    assert proj["total_chapters"] == 2
    assert proj["thought_convention"] == "none"  # profile defaults exist
    assert len(sm.get_all_chapters(pid)) == 2


def test_seed_project_is_idempotent(sm):
    pid1 = sm.seed_project(PARSED)
    pid2 = sm.seed_project(PARSED)
    assert pid1 == pid2
    assert len(sm.list_projects()) == 1


def test_update_profile(sm):
    pid = sm.seed_project(PARSED)
    sm.update_profile(pid, pov_style="third", pov_characters=["Sunny"],
                      thought_convention="single_quotes", system_brackets=True,
                      narrator_notes="LitRPG with system messages.")
    proj = sm.get_project_by_id(pid)
    assert proj["pov_characters"] == ["Sunny"]       # JSON decoded on read
    assert proj["thought_convention"] == "single_quotes"
    assert proj["system_brackets"] == 1


def test_update_profile_rejects_bad_values(sm):
    pid = sm.seed_project(PARSED)
    with pytest.raises(ValueError):
        sm.update_profile(pid, thought_convention="telepathy")
    with pytest.raises(ValueError):
        sm.update_profile(pid, pov_style="second")
    with pytest.raises(ValueError):
        sm.update_profile(pid, favourite_color="red")  # unknown field
