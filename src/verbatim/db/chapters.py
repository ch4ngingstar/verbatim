"""Chapter, chunk, line, and progress operations (mixin for StateManager).

Chapter status lifecycle: pending -> diarized -> tts_done -> assembled -> complete
                                                                       \\-> error
"""

from typing import Any

from verbatim import config
from verbatim.db.base import Database, now_iso
from verbatim.db.schema import CHAPTER_STATUSES


class ChapterOps:
    db: Database

    # -- Chapters ----------------------------------------------------------

    def get_all_chapters(self, project_id: int) -> list[dict[str, Any]]:
        with self.db.conn() as conn:
            rows = conn.execute(
                "SELECT * FROM chapters WHERE project_id=? ORDER BY chapter_index",
                (project_id,),
            ).fetchall()
            return [dict(r) for r in rows]

    def get_chapters_by_status(self, project_id: int, status: str) -> list[dict[str, Any]]:
        with self.db.conn() as conn:
            rows = conn.execute(
                "SELECT * FROM chapters WHERE project_id=? AND status=? ORDER BY chapter_index",
                (project_id, status),
            ).fetchall()
            return [dict(r) for r in rows]

    def mark_chapter_status(
        self,
        chapter_id: int,
        status: str,
        audio_path: "str | None" = None,
        error_message: "str | None" = None,
        file_size_bytes: "int | None" = None,
        processing_seconds: "float | None" = None,
    ) -> None:
        if status not in CHAPTER_STATUSES:
            raise ValueError(f"Invalid chapter status: '{status}'. Valid: {CHAPTER_STATUSES}")
        with self.db.conn() as conn:
            conn.execute(
                """UPDATE chapters
                   SET status=?, output_audio_path=COALESCE(?,output_audio_path),
                       output_file_size_bytes=COALESCE(?,output_file_size_bytes),
                       error_message=COALESCE(?,error_message),
                       processing_seconds=COALESCE(?,processing_seconds),
                       updated_at=?
                   WHERE id=?""",
                (status, audio_path, file_size_bytes, error_message,
                 processing_seconds, now_iso(), chapter_id),
            )

    def delete_chapter_audio(self, chapter_id: int) -> bool:
        with self.db.conn() as conn:
            n = conn.execute(
                """UPDATE chapters
                   SET output_audio_path=NULL, output_file_size_bytes=NULL, updated_at=?
                   WHERE id=?""",
                (now_iso(), chapter_id),
            ).rowcount
        return n > 0

    def reset_chapter_to_pending(self, chapter_id: int) -> bool:
        """Reset to pending, deleting all lines and their WAVs for a full re-run."""
        with self.db.conn() as conn:
            line_paths = [
                r["audio_path"] for r in conn.execute(
                    "SELECT audio_path FROM lines WHERE chapter_id=? AND audio_path IS NOT NULL",
                    (chapter_id,),
                ).fetchall()
            ]
            conn.execute("DELETE FROM lines WHERE chapter_id=?", (chapter_id,))
            n = conn.execute(
                """UPDATE chapters
                   SET status='pending', output_audio_path=NULL, output_file_size_bytes=NULL,
                       error_message=NULL, total_lines=0, processing_seconds=NULL, updated_at=?
                   WHERE id=?""",
                (now_iso(), chapter_id),
            ).rowcount
        for stored in line_paths:
            p = config.from_stored(stored)
            try:
                if p.exists():
                    p.unlink()
            except OSError:
                pass  # a locked file must not block the DB reset
        return n > 0

    # -- Chunks --------------------------------------------------------------

    def get_chunks_for_chapter(self, chapter_id: int) -> list[dict[str, Any]]:
        with self.db.conn() as conn:
            rows = conn.execute(
                """SELECT id, chapter_id, chunk_index, text, word_count
                   FROM chunks WHERE chapter_id=? ORDER BY chunk_index""",
                (chapter_id,),
            ).fetchall()
            return [dict(r) for r in rows]

    # -- Lines -----------------------------------------------------------------

    def save_diarized_lines(self, chapter_id: int, lines: list[dict[str, Any]]) -> None:
        with self.db.conn() as conn:
            conn.execute("DELETE FROM lines WHERE chapter_id=?", (chapter_id,))
            conn.executemany(
                """INSERT INTO lines (chapter_id, line_index, speaker, text, emotion)
                   VALUES (?, ?, ?, ?, ?)""",
                [
                    (chapter_id, ln["line_index"], ln["speaker"],
                     ln["text"], ln.get("emotion", "neutral"))
                    for ln in lines
                ],
            )
            conn.execute(
                "UPDATE chapters SET status='diarized', total_lines=?, updated_at=? WHERE id=?",
                (len(lines), now_iso(), chapter_id),
            )

    def get_pending_tts_lines(self, chapter_id: int) -> list[dict[str, Any]]:
        with self.db.conn() as conn:
            rows = conn.execute(
                """SELECT id, chapter_id, line_index, speaker, text, emotion
                   FROM lines WHERE chapter_id=? AND status='pending' ORDER BY line_index""",
                (chapter_id,),
            ).fetchall()
            return [dict(r) for r in rows]

    def get_lines_for_chapter(self, chapter_id: int) -> list[dict[str, Any]]:
        with self.db.conn() as conn:
            rows = conn.execute(
                """SELECT id, line_index, speaker, text, emotion, status, audio_path, error_message
                   FROM lines WHERE chapter_id=? ORDER BY line_index""",
                (chapter_id,),
            ).fetchall()
            return [dict(r) for r in rows]

    def mark_line_tts_done(self, line_id: int, audio_path: str) -> None:
        with self.db.conn() as conn:
            conn.execute(
                "UPDATE lines SET status='tts_done', audio_path=? WHERE id=?",
                (audio_path, line_id),
            )

    def mark_line_failed(self, line_id: int, error: str) -> None:
        with self.db.conn() as conn:
            conn.execute(
                "UPDATE lines SET status='failed', error_message=? WHERE id=?",
                (error, line_id),
            )

    # -- Progress -----------------------------------------------------------

    def get_progress(self, project_id: int) -> dict[str, Any]:
        with self.db.conn() as conn:
            rows = conn.execute(
                "SELECT status, COUNT(*) AS cnt FROM chapters WHERE project_id=? GROUP BY status",
                (project_id,),
            ).fetchall()
        counts = {r["status"]: r["cnt"] for r in rows}
        total = sum(counts.values())
        complete = counts.get("complete", 0)
        return {
            "total": total,
            "pending": counts.get("pending", 0),
            "diarized": counts.get("diarized", 0),
            "tts_done": counts.get("tts_done", 0),
            "assembled": counts.get("assembled", 0),
            "complete": complete,
            "error": counts.get("error", 0),
            "pct_complete": round(complete / total * 100, 1) if total else 0.0,
        }

    def get_line_progress(self, chapter_id: int) -> dict[str, Any]:
        with self.db.conn() as conn:
            rows = conn.execute(
                "SELECT status, COUNT(*) AS cnt FROM lines WHERE chapter_id=? GROUP BY status",
                (chapter_id,),
            ).fetchall()
        counts = {r["status"]: r["cnt"] for r in rows}
        total = sum(counts.values())
        done = counts.get("tts_done", 0)
        return {
            "total": total,
            "pending": counts.get("pending", 0),
            "tts_done": done,
            "failed": counts.get("failed", 0),
            "pct_done": round(done / total * 100, 1) if total else 0.0,
        }
