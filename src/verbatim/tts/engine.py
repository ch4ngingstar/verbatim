"""TTSEngine — IndexTTS2 in-process synthesis with per-line emotion control.

Context manager loads IndexTTS2 once, synthesises all pending lines for a
chapter, then unloads on exit. `_synthesize` is injectable for GPU-free tests.
"""

import logging
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from verbatim import config
from verbatim.db.manager import StateManager
from verbatim.tts.emotion import (
    normalize_text,
    resolve_emotion,
    split_long_line,
    wav_silence,
)
from verbatim.tts.voices import build_voice_map, resolve_ref_audio

log = logging.getLogger(__name__)

_LINE_MAX_CHARS = 300

_DEFAULT_CFG: dict[str, Any] = {
    "tts_model_dir": "index-tts/checkpoints",
    "use_deepspeed": False,
    "num_beams": 3,
    "max_new_tokens": 2048,
    "wav_sample_rate": 24000,
    "silence_ms_between_lines": 150,
}


class TTSEngine:
    """IndexTTS2 synthesis engine for one project chapter.

    Usage::

        with TTSEngine(sm, project_id, wav_dir, cfg=cfg) as engine:
            n_done = engine.process_chapter(chapter_id)
    """

    def __init__(
        self,
        sm: StateManager,
        project_id: int,
        wav_output_dir: "str | Path",
        cfg: "dict[str, Any] | None" = None,
    ) -> None:
        self._sm = sm
        self._project_id = project_id
        self._wav_dir = Path(wav_output_dir)
        self._cfg: dict[str, Any] = {**_DEFAULT_CFG, **(cfg or {})}
        self._tts: Any = None  # IndexTTS2 instance (loaded in __enter__)
        # Override in tests — receives (text, ref_path, emo_vector, emo_alpha) → bytes
        self._synthesize: Callable[..., bytes] | None = None

    # -- Context manager -------------------------------------------------

    def __enter__(self) -> "TTSEngine":
        if self._synthesize is None:
            self._tts = self._load_model()
        return self

    def __exit__(self, *_: Any) -> None:
        self._unload_model()

    # -- Public API -------------------------------------------------------

    def process_chapter(self, chapter_id: int) -> int:
        """Synthesise all pending TTS lines for chapter_id.

        Returns the count of successfully synthesised lines.
        """
        if self._tts is None and self._synthesize is None:
            raise RuntimeError("TTSEngine must be used as a context manager")

        voice_map = build_voice_map(self._sm, self._project_id)
        lines = self._sm.get_pending_tts_lines(chapter_id)
        if not lines:
            log.info("chapter %d: no pending TTS lines", chapter_id)
            return 0

        ch_dir = self._wav_dir / f"ch_{chapter_id:04d}"
        ch_dir.mkdir(parents=True, exist_ok=True)

        n_done = 0
        for line in lines:
            try:
                n_done += self._process_line(line, voice_map, ch_dir)
            except Exception as exc:  # noqa: BLE001
                log.error("line %d failed: %s", line["id"], exc, exc_info=True)
                self._sm.mark_line_failed(line["id"], str(exc))

        if lines and n_done == len(lines):
            self._sm.mark_chapter_status(chapter_id, "tts_done")
        elif n_done < len(lines):
            failed = len(lines) - n_done
            self._sm.mark_chapter_status(
                chapter_id, "error",
                error_message=f"[failed_stage:tts] {failed}/{len(lines)} lines failed",
            )

        return n_done

    # -- Internals --------------------------------------------------------

    def _process_line(
        self,
        line: dict[str, Any],
        voice_map: dict[str, str],
        ch_dir: Path,
    ) -> int:
        ref_path = resolve_ref_audio(line["speaker"], voice_map)
        if ref_path is None:
            log.warning("no voice for speaker %r — skipping line %d", line["speaker"], line["id"])
            return 0

        text = normalize_text(line["text"])
        if not text:
            return 0

        emo_vec, emo_alpha = resolve_emotion(line.get("emotion", "neutral") or "neutral")

        segments = split_long_line(text, _LINE_MAX_CHARS)
        wavs: list[bytes] = []
        for seg in segments:
            wav = self._call_synthesize(seg, ref_path, emo_vec, emo_alpha)
            wavs.append(wav)
            if len(segments) > 1:
                wavs.append(wav_silence(self._cfg["silence_ms_between_lines"]))

        combined = wavs[0] if len(wavs) == 1 else self._concat_wavs(wavs)

        out_path = ch_dir / f"line_{line['line_index']:04d}.wav"
        out_path.write_bytes(combined)

        stored = config.to_stored(out_path)
        self._sm.mark_line_tts_done(line["id"], stored)
        log.debug("line %d -> %s", line["id"], out_path.name)
        return 1

    def _call_synthesize(
        self,
        text: str,
        ref_path: Path,
        emo_vec: "list[float] | None",
        emo_alpha: float,
    ) -> bytes:
        """Dispatch to injected stub or live IndexTTS2."""
        if self._synthesize is not None:
            return self._synthesize(text, ref_path, emo_vec, emo_alpha)
        return self._synthesize_live(text, ref_path, emo_vec, emo_alpha)

    def _synthesize_live(
        self,
        text: str,
        ref_path: Path,
        emo_vec: "list[float] | None",
        emo_alpha: float,
    ) -> bytes:
        """Live IndexTTS synthesis — only called outside tests."""
        import io

        import soundfile as sf  # type: ignore[import-untyped]

        t0 = time.perf_counter()
        # output_path=None → returns (sample_rate, numpy_int16_array)
        sr, audio = self._tts.infer(
            str(ref_path),
            text,
            output_path=None,
            num_beams=self._cfg["num_beams"],
            max_mel_tokens=self._cfg["max_new_tokens"],
        )
        elapsed = time.perf_counter() - t0
        log.debug("synthesised in %.1fs", elapsed)

        buf = io.BytesIO()
        sf.write(buf, audio, sr, format="WAV")
        return buf.getvalue()

    def _concat_wavs(self, wavs: list[bytes]) -> bytes:
        """Concatenate WAV byte blobs by splicing PCM data (same format assumed)."""
        import io
        import wave

        frames_parts: list[bytes] = []
        params = None
        for wav_bytes in wavs:
            with wave.open(io.BytesIO(wav_bytes)) as wf:
                if params is None:
                    params = wf.getparams()
                frames_parts.append(wf.readframes(wf.getnframes()))

        out = io.BytesIO()
        with wave.open(out, "wb") as wf:
            assert params is not None  # always set after first iteration
            wf.setparams(params)
            for chunk in frames_parts:
                wf.writeframes(chunk)
        return out.getvalue()

    def _load_model(self) -> Any:
        import os
        import sys

        # When running inside a venv, pull GPU packages (torch, torchaudio, soundfile)
        # from the base Python installation where they are installed.
        if sys.prefix != sys.base_prefix:
            base_site = os.path.join(sys.base_prefix, "Lib", "site-packages")
            if base_site not in sys.path:
                sys.path.insert(0, base_site)

        # indextts/ package lives one level above the checkpoints dir
        sys.path.insert(0, str(Path(self._cfg["tts_model_dir"]).parent))
        from indextts.infer import IndexTTS  # type: ignore[import-not-found]

        cfg_path = str(Path(self._cfg["tts_model_dir"]) / "config.yaml")
        tts = IndexTTS(
            model_dir=self._cfg["tts_model_dir"],
            cfg_path=cfg_path,
            use_fp16=False,
        )
        log.info("IndexTTS loaded from %s", self._cfg["tts_model_dir"])
        return tts

    def _unload_model(self) -> None:
        if self._tts is not None:
            try:
                import torch  # type: ignore[import-untyped]

                del self._tts
                self._tts = None
                torch.cuda.empty_cache()
                log.info("IndexTTS2 unloaded")
            except Exception as exc:  # noqa: BLE001
                log.warning("Error unloading IndexTTS2: %s", exc)
