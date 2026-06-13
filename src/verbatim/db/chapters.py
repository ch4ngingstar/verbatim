"""Chapter, chunk, line, and progress operations (mixin for StateManager).

Fully populated in Task 5; seeded here with the single query Task 4's tests need.
"""

from typing import Any

from verbatim.db.base import Database


class ChapterOps:
    db: Database

    def get_all_chapters(self, project_id: int) -> list[dict[str, Any]]:
        with self.db.conn() as conn:
            rows = conn.execute(
                "SELECT * FROM chapters WHERE project_id=? ORDER BY chapter_index",
                (project_id,),
            ).fetchall()
            return [dict(r) for r in rows]
