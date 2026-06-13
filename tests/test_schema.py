import sqlite3

from verbatim.db.schema import SCHEMA

EXPECTED_TABLES = {"projects", "chapters", "chunks", "lines", "characters", "voices"}


def test_schema_creates_all_tables(tmp_path):
    conn = sqlite3.connect(tmp_path / "t.db")
    conn.executescript(SCHEMA)
    rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    names = {r[0] for r in rows}
    assert EXPECTED_TABLES <= names


def test_schema_is_idempotent(tmp_path):
    conn = sqlite3.connect(tmp_path / "t.db")
    conn.executescript(SCHEMA)
    conn.executescript(SCHEMA)  # must not raise
