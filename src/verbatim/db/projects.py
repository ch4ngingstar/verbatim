"""Project + Novel Profile operations (mixin for StateManager)."""

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from verbatim.db.base import Database, now_iso
from verbatim.db.schema import POV_STYLES, THOUGHT_CONVENTIONS

# Profile fields and their validators / serializers.
_PROFILE_FIELDS: dict[str, Any] = {
    "pov_style": lambda v: v in POV_STYLES,
    "pov_characters": lambda v: isinstance(v, list),
    "thought_convention": lambda v: v in THOUGHT_CONVENTIONS,
    "system_brackets": lambda v: isinstance(v, bool | int),
    "narrator_notes": lambda v: isinstance(v, str),
    "cover_path": lambda v: v is None or isinstance(v, str),
}


def _decode_project(row: Any) -> dict:  # type: ignore[type-arg]
    proj = dict(row)
    proj["pov_characters"] = json.loads(proj["pov_characters"])
    return proj


class ProjectOps:
    db: Database

    def seed_project(self, parsed_book: Any, force_reseed: bool = False) -> int:
        """Import a ParsedBook (dataclass or dict). Idempotent by project name."""
        book = asdict(parsed_book) if hasattr(parsed_book, "__dataclass_fields__") else parsed_book
        name = Path(book["source_epub"]).stem

        with self.db.conn() as conn:
            if not force_reseed:
                row = conn.execute("SELECT id FROM projects WHERE name=?", (name,)).fetchone()
                if row:
                    return int(row["id"])

            conn.execute(
                """INSERT INTO projects (name, source_epub, total_chapters, updated_at)
                   VALUES (?, ?, ?, ?)
                   ON CONFLICT(name) DO UPDATE SET
                     total_chapters=excluded.total_chapters, updated_at=excluded.updated_at""",
                (name, book["source_epub"], book["total_chapters"], now_iso()),
            )
            project_id = int(
                conn.execute("SELECT id FROM projects WHERE name=?", (name,)).fetchone()["id"]
            )
            for ch in book["chapters"]:
                conn.execute(
                    """INSERT INTO chapters
                         (project_id, chapter_index, title, total_chunks, status, updated_at)
                       VALUES (?, ?, ?, ?, 'pending', ?)
                       ON CONFLICT(project_id, chapter_index) DO NOTHING""",
                    (project_id, ch["chapter_index"], ch["title"], len(ch["chunks"]), now_iso()),
                )
                chapter_id = conn.execute(
                    "SELECT id FROM chapters WHERE project_id=? AND chapter_index=?",
                    (project_id, ch["chapter_index"]),
                ).fetchone()["id"]
                for ck in ch["chunks"]:
                    conn.execute(
                        """INSERT INTO chunks (chapter_id, chunk_index, text, word_count)
                           VALUES (?, ?, ?, ?)
                           ON CONFLICT(chapter_id, chunk_index) DO NOTHING""",
                        (chapter_id, ck["chunk_index"], ck["text"], ck["word_count"]),
                    )
        return project_id

    def get_project_by_id(self, project_id: int) -> "dict | None":  # type: ignore[type-arg]
        with self.db.conn() as conn:
            row = conn.execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone()
            return _decode_project(row) if row else None

    def get_project(self, name: str) -> "dict | None":  # type: ignore[type-arg]
        with self.db.conn() as conn:
            row = conn.execute("SELECT * FROM projects WHERE name=?", (name,)).fetchone()
            return _decode_project(row) if row else None

    def list_projects(self) -> list[dict]:  # type: ignore[type-arg]
        with self.db.conn() as conn:
            rows = conn.execute("SELECT * FROM projects ORDER BY created_at DESC").fetchall()
            return [_decode_project(r) for r in rows]

    def update_profile(self, project_id: int, **fields: Any) -> None:
        """Update Novel Profile fields. Unknown fields or invalid values raise ValueError."""
        for key, value in fields.items():
            validate = _PROFILE_FIELDS.get(key)
            if validate is None:
                raise ValueError(f"Unknown profile field: '{key}'")
            if not validate(value):
                raise ValueError(f"Invalid value for profile field '{key}': {value!r}")

        sets: list[str] = []
        params: list[Any] = []
        for key, value in fields.items():
            sets.append(f"{key}=?")
            if key == "pov_characters":
                params.append(json.dumps(value))
            elif key == "system_brackets":
                params.append(int(value))
            else:
                params.append(value)
        params.extend([now_iso(), project_id])
        with self.db.conn() as conn:
            conn.execute(
                f"UPDATE projects SET {', '.join(sets)}, updated_at=? WHERE id=?", params
            )
