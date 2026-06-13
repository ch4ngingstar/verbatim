"""Characters (per project) + global voice library (mixin for StateManager).

This is the data layer that replaces Shadow Slave's hardcoded SPEAKER_ALIASES:
aliases live on character rows; voice clips live in a shared library and are
cast per project via characters.voice_id.
"""

import json
from typing import Any

from verbatim.db.base import Database, now_iso
from verbatim.db.schema import CHARACTER_STATUSES


class CastingOps:
    db: Database

    # -- Characters --------------------------------------------------------

    def upsert_character(
        self,
        project_id: int,
        name: str,
        aliases: "list[str] | None" = None,
        emotion_hint: str = "",
        is_pov: bool = False,
        status: str = "suggested",
    ) -> int:
        if status not in CHARACTER_STATUSES:
            raise ValueError(f"Invalid character status: '{status}'. Valid: {CHARACTER_STATUSES}")
        with self.db.conn() as conn:
            conn.execute(
                """INSERT INTO characters
                     (project_id, name, aliases, emotion_hint, is_pov, status, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(project_id, name) DO UPDATE SET
                     aliases=excluded.aliases, emotion_hint=excluded.emotion_hint,
                     is_pov=excluded.is_pov, updated_at=excluded.updated_at""",
                (project_id, name, json.dumps(aliases or []), emotion_hint,
                 int(is_pov), status, now_iso()),
            )
            return int(conn.execute(
                "SELECT id FROM characters WHERE project_id=? AND name=?",
                (project_id, name),
            ).fetchone()["id"])

    def list_characters(self, project_id: int) -> list[dict[str, Any]]:
        """Characters ranked by importance (line_count desc), voice path joined in."""
        with self.db.conn() as conn:
            rows = conn.execute(
                """SELECT c.*, v.path AS voice_path, v.name AS voice_name
                   FROM characters c LEFT JOIN voices v ON v.id = c.voice_id
                   WHERE c.project_id=?
                   ORDER BY c.line_count DESC, c.name""",
                (project_id,),
            ).fetchall()
        chars = []
        for r in rows:
            c = dict(r)
            c["aliases"] = json.loads(c["aliases"])
            chars.append(c)
        return chars

    def set_character_status(self, character_id: int, status: str) -> None:
        if status not in CHARACTER_STATUSES:
            raise ValueError(f"Invalid character status: '{status}'. Valid: {CHARACTER_STATUSES}")
        with self.db.conn() as conn:
            conn.execute(
                "UPDATE characters SET status=?, updated_at=? WHERE id=?",
                (status, now_iso(), character_id),
            )

    def update_character_stats(
        self, project_id: int, name: str, line_count: int, chapter_count: int
    ) -> None:
        with self.db.conn() as conn:
            conn.execute(
                """UPDATE characters SET line_count=?, chapter_count=?, updated_at=?
                   WHERE project_id=? AND name=?""",
                (line_count, chapter_count, now_iso(), project_id, name),
            )

    def assign_voice(self, character_id: int, voice_id: "int | None") -> None:
        with self.db.conn() as conn:
            conn.execute(
                "UPDATE characters SET voice_id=?, updated_at=? WHERE id=?",
                (voice_id, now_iso(), character_id),
            )

    def get_alias_map(self, project_id: int) -> dict[str, int]:
        """{lowercased name-or-alias: character_id} for speaker resolution."""
        amap: dict[str, int] = {}
        for c in self.list_characters(project_id):
            amap[c["name"].lower()] = c["id"]
            for alias in c["aliases"]:
                amap[alias.lower()] = c["id"]
        return amap

    # -- Global voice library -------------------------------------------------

    def add_voice(self, name: str, path: str, tags: "list[str] | None" = None) -> int:
        """Register a voice clip. `path` must be in stored (data-root-relative) form."""
        with self.db.conn() as conn:
            conn.execute(
                """INSERT INTO voices (name, path, tags, updated_at) VALUES (?, ?, ?, ?)
                   ON CONFLICT(name) DO UPDATE SET
                     path=excluded.path, tags=excluded.tags, updated_at=excluded.updated_at""",
                (name, path, json.dumps(tags or []), now_iso()),
            )
            return int(conn.execute(
                "SELECT id FROM voices WHERE name=?", (name,)
            ).fetchone()["id"])

    def list_voices(self) -> list[dict[str, Any]]:
        with self.db.conn() as conn:
            rows = conn.execute("SELECT * FROM voices ORDER BY name").fetchall()
        voices = []
        for r in rows:
            v = dict(r)
            v["tags"] = json.loads(v["tags"])
            voices.append(v)
        return voices

    def get_voice_by_id(self, voice_id: int) -> "dict | None":
        with self.db.conn() as conn:
            row = conn.execute("SELECT * FROM voices WHERE id=?", (voice_id,)).fetchone()
        if row is None:
            return None
        v = dict(row)
        v["tags"] = json.loads(v["tags"])
        return v

    def get_voice_by_name(self, name: str) -> "dict | None":
        with self.db.conn() as conn:
            row = conn.execute("SELECT * FROM voices WHERE name=?", (name,)).fetchone()
        if row is None:
            return None
        v = dict(row)
        v["tags"] = json.loads(v["tags"])
        return v

    def delete_voice(self, voice_id: int) -> bool:
        with self.db.conn() as conn:
            return conn.execute("DELETE FROM voices WHERE id=?", (voice_id,)).rowcount > 0

    def get_project_voice_map(self, project_id: int) -> dict[str, str]:
        """Return {title-cased name or alias: stored voice path} for TTS resolution.

        Covers every cast character with a voice assigned (names + all aliases)
        plus the global '_default' voice if one is registered.
        """
        result: dict[str, str] = {}
        for char in self.list_characters(project_id):
            path = char.get("voice_path")
            if not path:
                continue
            result[char["name"].strip().title()] = path
            for alias in char.get("aliases", []):
                if alias:
                    result[alias.strip().title()] = path
        for voice in self.list_voices():
            if voice["name"] == "_default":
                result["_default"] = voice["path"]
                break
        return result
