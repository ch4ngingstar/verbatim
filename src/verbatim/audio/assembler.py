"""AudioAssembler — concatenate per-line WAVs into a chapter MP3 via FFmpeg.

Uses the FFmpeg concat demuxer (no re-encoding of WAVs until the final MP3
transcode), which is the most robust approach for large chapter files.
"""

import logging
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from verbatim import config

log = logging.getLogger(__name__)

_DEFAULT_CFG: dict[str, Any] = {
    "ffmpeg_bin": "ffmpeg",
    "mp3_bitrate": "128k",
    "silence_ms_between_lines": 150,
}


class AudioAssembler:
    """Assemble ordered per-line WAVs into a final chapter MP3."""

    def __init__(self, cfg: "dict[str, Any] | None" = None) -> None:
        self._cfg: dict[str, Any] = {**_DEFAULT_CFG, **(cfg or {})}
        # Injectable for tests — receives (cmd: list[str]) and may raise
        self._run_ffmpeg: Any = None

    def assemble_chapter(
        self,
        lines: list[dict[str, Any]],
        output_path: "str | Path",
        title: str = "",
        track_num: int = 0,
    ) -> Path:
        """Concatenate *lines* WAVs into an MP3 at *output_path*.

        Args:
            lines:       List of dicts with 'audio_path' (stored) and 'line_index'.
            output_path: Destination MP3 (absolute).
            title:       Chapter title embedded as ID3 title tag.
            track_num:   Track number embedded as ID3 track tag.

        Returns:
            Resolved absolute Path to the written MP3.
        """
        out = Path(output_path).resolve()
        out.parent.mkdir(parents=True, exist_ok=True)

        wav_paths = self._collect_wavs(lines)
        if not wav_paths:
            raise ValueError("No WAV files available for assembly")

        with tempfile.TemporaryDirectory(prefix="verbatim_assemble_") as tmp:
            concat_list = Path(tmp) / "concat.txt"
            silence_wav = Path(tmp) / "silence.wav"

            silence_bytes = self._write_silence_wav(silence_wav)
            concat_list.write_text(
                self._build_concat_list(wav_paths, silence_wav if silence_bytes else None),
                encoding="utf-8",
            )

            cmd = self._build_ffmpeg_cmd(concat_list, out, title, track_num)
            self._dispatch_ffmpeg(cmd)

        log.info("assembled %d lines -> %s", len(wav_paths), out.name)
        return out

    # -- Internals --------------------------------------------------------

    def _collect_wavs(self, lines: list[dict[str, Any]]) -> list[Path]:
        """Resolve stored paths to absolute WAV paths, skipping missing files."""
        paths: list[Path] = []
        for ln in sorted(lines, key=lambda ln: ln["line_index"]):
            stored = ln.get("audio_path")
            if not stored:
                continue
            p = config.from_stored(stored)
            if p.exists():
                paths.append(p)
            else:
                log.warning("WAV missing for line %s: %s", ln.get("id"), p)
        return paths

    def _build_concat_list(self, paths: list[Path], silence: "Path | None") -> str:
        """Build FFmpeg concat file content, optionally inserting silence between lines."""
        lines: list[str] = []
        for i, p in enumerate(paths):
            lines.append(f"file '{p.as_posix()}'")
            if silence is not None and i < len(paths) - 1:
                lines.append(f"file '{silence.as_posix()}'")
        return "\n".join(lines) + "\n"

    def _write_silence_wav(self, dest: Path) -> bytes:
        """Write a silent WAV of configured duration; return bytes if written."""
        from verbatim.tts.emotion import wav_silence

        data = wav_silence(self._cfg["silence_ms_between_lines"])
        dest.write_bytes(data)
        return data

    def _build_ffmpeg_cmd(
        self,
        concat_list: Path,
        output: Path,
        title: str,
        track_num: int,
    ) -> list[str]:
        meta: list[str] = []
        if title:
            meta += ["-metadata", f"title={title}"]
        if track_num:
            meta += ["-metadata", f"track={track_num}"]
        return [
            self._cfg["ffmpeg_bin"],
            "-y",
            "-f", "concat",
            "-safe", "0",
            "-i", str(concat_list),
            "-vn",
            "-codec:a", "libmp3lame",
            "-b:a", self._cfg["mp3_bitrate"],
            *meta,
            str(output),
        ]

    def _dispatch_ffmpeg(self, cmd: list[str]) -> None:
        """Run FFmpeg command via injected stub or subprocess."""
        if self._run_ffmpeg is not None:
            self._run_ffmpeg(cmd)
            return

        if not shutil.which(self._cfg["ffmpeg_bin"]):
            raise RuntimeError(
                f"FFmpeg binary '{self._cfg['ffmpeg_bin']}' not found in PATH. "
                "Install FFmpeg: https://ffmpeg.org/download.html"
            )
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(
                f"FFmpeg failed (code {result.returncode}):\n{result.stderr[-2000:]}"
            )
