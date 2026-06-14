"""M4B exporter — wrap chapter MP3s into a single audiobook file with chapters.

Uses FFmpeg's FFMETADATA format to embed chapter markers, then remuxes into
an M4B container (AAC + chapter marks + cover art if provided).
"""

import logging
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

_DEFAULT_CFG: dict[str, Any] = {
    "ffmpeg_bin": "ffmpeg",
    "aac_bitrate": "128k",
}


def _probe_duration_ms(audio_path: "str | Path", ffprobe_bin: str = "ffprobe") -> int:
    """Return audio duration in milliseconds via ffprobe, or 0 on failure."""
    import json as _json
    try:
        result = subprocess.run(
            [
                ffprobe_bin, "-v", "quiet",
                "-print_format", "json",
                "-show_format",
                str(audio_path),
            ],
            capture_output=True, text=True, timeout=15,
        )
        if result.returncode == 0:
            data = _json.loads(result.stdout)
            duration_s = float(data.get("format", {}).get("duration", 0))
            return int(duration_s * 1000)
    except Exception:
        pass
    return 0


class M4BExporter:
    """Bundle ordered MP3 chapters into a single M4B audiobook with chapter markers."""

    def __init__(self, cfg: "dict[str, Any] | None" = None) -> None:
        self._cfg: dict[str, Any] = {**_DEFAULT_CFG, **(cfg or {})}
        # Injectable for tests
        self._run_ffmpeg: Any = None

    def export(
        self,
        chapter_mp3s: list[dict[str, Any]],
        output_path: "str | Path",
        book_title: str = "",
        author: str = "",
        cover_path: "str | Path | None" = None,
    ) -> Path:
        """Create an M4B file from ordered chapter MP3s.

        Args:
            chapter_mp3s: List of dicts with 'audio_path' (absolute Path | str),
                          'title' (chapter title), and 'duration_ms' (int).
            output_path:  Destination .m4b file.
            book_title:   Embedded as the album title tag.
            author:       Embedded as the artist tag.
            cover_path:   Optional JPEG/PNG cover image.

        Returns:
            Resolved absolute Path to the written M4B.
        """
        if not chapter_mp3s:
            raise ValueError("No chapters provided for M4B export")

        out = Path(output_path).resolve()
        out.parent.mkdir(parents=True, exist_ok=True)

        with tempfile.TemporaryDirectory(prefix="verbatim_m4b_") as tmp:
            concat_list = Path(tmp) / "concat.txt"
            meta_file = Path(tmp) / "chapters.ffmeta"

            self._write_concat_list(concat_list, chapter_mp3s)
            self._write_ffmetadata(meta_file, chapter_mp3s, book_title, author)

            # Step 1: concatenate MP3s to intermediate AAC
            intermediate = Path(tmp) / "intermediate.aac"
            self._dispatch_ffmpeg([
                self._cfg["ffmpeg_bin"], "-y",
                "-f", "concat", "-safe", "0",
                "-i", str(concat_list),
                "-c:a", "aac",
                "-b:a", self._cfg["aac_bitrate"],
                str(intermediate),
            ])

            # Step 2: mux AAC + chapter metadata (+ optional cover) into M4B
            cmd = [
                self._cfg["ffmpeg_bin"], "-y",
                "-i", str(intermediate),
                "-i", str(meta_file),
            ]
            if cover_path:
                cmd += ["-i", str(cover_path), "-map", "0:a", "-map", "2:v"]
            else:
                cmd += ["-map", "0:a"]
            cmd += [
                "-map_metadata", "1",
                "-c:a", "copy",
                "-movflags", "+faststart",
                str(out),
            ]
            self._dispatch_ffmpeg(cmd)

        log.info("exported %d chapters -> %s", len(chapter_mp3s), out.name)
        return out

    # -- Internals --------------------------------------------------------

    def _write_concat_list(self, dest: Path, chapters: list[dict[str, Any]]) -> None:
        lines: list[str] = []
        for ch in chapters:
            p = Path(ch["audio_path"]).resolve()
            lines.append(f"file '{p.as_posix()}'")
        dest.write_text("\n".join(lines) + "\n", encoding="utf-8")

    def _write_ffmetadata(
        self,
        dest: Path,
        chapters: list[dict[str, Any]],
        book_title: str,
        author: str,
    ) -> None:
        """Write FFMETADATA1 file with per-chapter TIME_BASE=1/1000 markers."""
        lines = [";FFMETADATA1\n"]
        if book_title:
            lines.append(f"title={book_title}\n")
        if author:
            lines.append(f"artist={author}\n")
            lines.append(f"album_artist={author}\n")

        cursor_ms = 0
        for ch in chapters:
            duration = int(ch.get("duration_ms", 0))
            start = cursor_ms
            end = cursor_ms + duration
            title = ch.get("title", "")
            lines.append("\n[CHAPTER]\n")
            lines.append("TIMEBASE=1/1000\n")
            lines.append(f"START={start}\n")
            lines.append(f"END={end}\n")
            if title:
                lines.append(f"title={title}\n")
            cursor_ms = end

        dest.write_text("".join(lines), encoding="utf-8")

    def _dispatch_ffmpeg(self, cmd: list[str]) -> None:
        if self._run_ffmpeg is not None:
            self._run_ffmpeg(cmd)
            return

        if not shutil.which(self._cfg["ffmpeg_bin"]):
            raise RuntimeError(
                f"FFmpeg binary '{self._cfg['ffmpeg_bin']}' not found in PATH."
            )
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(
                f"FFmpeg failed (code {result.returncode}):\n{result.stderr[-2000:]}"
            )
