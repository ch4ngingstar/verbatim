"""SQLite schema for Verbatim.

Differences from the Shadow Slave pipeline DB:
  * projects carries the Novel Profile (POV, thought convention, narrator notes).
  * characters is a first-class table (Shadow Slave hardcoded SPEAKER_ALIASES).
  * voices is a GLOBAL library keyed by voice name, not by speaker; casting
    happens via characters.voice_id per project.
  * All paths stored relative to the configured data root (see config.py).
"""

SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS projects (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT    NOT NULL UNIQUE,
    source_epub     TEXT    NOT NULL,
    cover_path      TEXT,
    total_chapters  INTEGER NOT NULL,
    -- Novel Profile -----------------------------------------------------
    pov_style          TEXT NOT NULL DEFAULT 'third',   -- 'first' | 'third'
    pov_characters     TEXT NOT NULL DEFAULT '[]',      -- JSON list of names
    thought_convention TEXT NOT NULL DEFAULT 'none',    -- 'none' | 'single_quotes'
    system_brackets    INTEGER NOT NULL DEFAULT 0,      -- [brackets] are system lines
    narrator_notes     TEXT NOT NULL DEFAULT '',
    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    updated_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);

CREATE TABLE IF NOT EXISTS chapters (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id    INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    chapter_index INTEGER NOT NULL,
    title         TEXT    NOT NULL,
    status        TEXT    NOT NULL DEFAULT 'pending',
    total_chunks  INTEGER NOT NULL DEFAULT 0,
    total_lines   INTEGER NOT NULL DEFAULT 0,
    output_audio_path      TEXT,
    output_file_size_bytes INTEGER,
    processing_seconds     REAL,
    error_message TEXT,
    created_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    updated_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    UNIQUE(project_id, chapter_index)
);

CREATE TABLE IF NOT EXISTS chunks (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    chapter_id    INTEGER NOT NULL REFERENCES chapters(id) ON DELETE CASCADE,
    chunk_index   INTEGER NOT NULL,
    text          TEXT    NOT NULL,
    word_count    INTEGER NOT NULL,
    UNIQUE(chapter_id, chunk_index)
);

CREATE TABLE IF NOT EXISTS lines (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    chapter_id    INTEGER NOT NULL REFERENCES chapters(id) ON DELETE CASCADE,
    line_index    INTEGER NOT NULL,
    speaker       TEXT    NOT NULL,
    text          TEXT    NOT NULL,
    emotion       TEXT    NOT NULL DEFAULT 'neutral',
    status        TEXT    NOT NULL DEFAULT 'pending',
    audio_path    TEXT,
    error_message TEXT,
    created_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    UNIQUE(chapter_id, line_index)
);

CREATE TABLE IF NOT EXISTS voices (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    name          TEXT    NOT NULL UNIQUE,
    path          TEXT    NOT NULL,
    tags          TEXT    NOT NULL DEFAULT '[]',
    created_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    updated_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);

CREATE TABLE IF NOT EXISTS characters (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id    INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    name          TEXT    NOT NULL,
    aliases       TEXT    NOT NULL DEFAULT '[]',
    emotion_hint  TEXT    NOT NULL DEFAULT '',
    is_pov        INTEGER NOT NULL DEFAULT 0,
    status        TEXT    NOT NULL DEFAULT 'suggested',  -- cast | suggested | ignored
    voice_id      INTEGER REFERENCES voices(id) ON DELETE SET NULL,
    line_count    INTEGER NOT NULL DEFAULT 0,
    chapter_count INTEGER NOT NULL DEFAULT 0,
    created_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    updated_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    UNIQUE(project_id, name)
);
"""

CHAPTER_STATUSES = {"pending", "diarized", "tts_done", "assembled", "complete", "error"}
LINE_STATUSES = {"pending", "tts_done", "failed"}
CHARACTER_STATUSES = {"cast", "suggested", "ignored"}
THOUGHT_CONVENTIONS = {"none", "single_quotes"}
POV_STYLES = {"first", "third"}
