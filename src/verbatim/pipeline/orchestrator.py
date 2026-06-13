"""PipelineOrchestrator — sequences diarize → synthesise → assemble per chapter.

VRAM lifecycle (critical — machine has ~12 GB):
  1. LLMDirector context  [loads ~9 GB] → diarize → [unloads on __exit__]
  2. VRAM barrier         [polls nvidia-smi until delta drops below threshold]
  3. TTSEngine context    [loads ~8 GB] → synthesise → [unloads on __exit__]
  4. AudioAssembler.assemble_chapter() [CPU only]

Resume logic:
  pending  → all three stages
  diarized → TTS + assemble
  tts_done → assemble only
  complete → skip
  error    → retry from [failed_stage:X] tag in error_message

Progress events emitted to callback and accumulated in self.events:
  pipeline_start, chapter_start, stage_start, stage_done,
  chapter_done, chapter_error, chapter_skip, vram_warning, pipeline_done
"""

import collections
import logging
import re
import subprocess
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from verbatim import config
from verbatim.audio.assembler import AudioAssembler
from verbatim.db.manager import StateManager
from verbatim.llm.director import LLMDirector
from verbatim.tts.engine import TTSEngine

log = logging.getLogger(__name__)

_ALL_STAGES = ["diarize", "synthesize", "assemble"]

_STAGES_FOR_STATUS: dict[str, list[str]] = {
    "pending":  _ALL_STAGES,
    "diarized": _ALL_STAGES[1:],
    "tts_done": _ALL_STAGES[2:],
    "assembled": [],
    "complete": [],
}

# Pipeline-added VRAM may leave allocator headroom; tolerate up to 500 MB above baseline.
_VRAM_DELTA_ALLOWANCE_MB = 500
_VRAM_FALLBACK_THRESHOLD_MB = 1000

_LIVE_TEXT_MAX = 200


def _truncate(text: Any) -> str:
    t = str(text or "")
    return t if len(t) <= _LIVE_TEXT_MAX else t[:_LIVE_TEXT_MAX - 1] + "…"


@dataclass
class OrchestratorConfig:
    """All tunable parameters for a pipeline run."""

    # Paths
    db_path:          str = "data/pipeline.db"
    llm_model_path:   str = ""
    tts_model_dir:    str = "index-tts/checkpoints"
    wav_output_dir:   str = "data/audio"
    mp3_output_dir:   str = "data/output"

    # LLM
    llm_n_gpu_layers: int = -1
    llm_n_ctx:        int = 8192

    # TTS
    tts_num_beams:    int = 3
    tts_use_deepspeed: bool = False

    # VRAM barrier
    vram_check_enabled: bool = True
    vram_wait_timeout_s: int = 30

    # Scope
    chapter_range: "tuple[int, int] | None" = None  # inclusive (start_idx, end_idx)

    # Extra pass-through for injected sub-configs
    extra: dict[str, Any] = field(default_factory=dict)


class PipelineOrchestrator:
    """Sequences diarize → synthesise → assemble for each chapter of a project.

    Construct with a project_id that already exists in the DB (seeded by
    epub_parser). Injectable *_cls arguments let tests substitute fakes.
    """

    def __init__(
        self,
        project_id: int,
        sm: StateManager,
        cfg: "OrchestratorConfig | None" = None,
        progress_callback: "Callable[[dict[str, Any]], None] | None" = None,
        llm_director_cls: type = LLMDirector,
        tts_engine_cls: type = TTSEngine,
        assembler_cls: type = AudioAssembler,
    ) -> None:
        self._project_id = project_id
        self._sm = sm
        self._cfg = cfg or OrchestratorConfig()
        self._on_progress = progress_callback or (lambda _e: None)
        self._llm_cls = llm_director_cls
        self._tts_cls = tts_engine_cls
        self._assembler_cls = assembler_cls

        self._pause_event = threading.Event()
        self._pause_event.set()   # set = running
        self._stop_event = threading.Event()
        self._stop_event.set()    # set = not-stopped
        self.events: collections.deque[dict[str, Any]] = collections.deque(maxlen=500)
        self._current_stage = "unknown"
        self._vram_baseline_mb = -1

    # -- Public control API -----------------------------------------------

    def run(self) -> dict[str, Any]:
        """Execute the pipeline. Returns {success, error, skipped, elapsed_s}."""
        t0 = time.time()
        chapters = self._chapters_to_process()
        self._emit("pipeline_start", total=len(chapters))
        results: dict[str, int] = {"success": 0, "error": 0, "skipped": 0}

        for chapter in chapters:
            self._pause_event.wait()
            if not self._stop_event.is_set():
                break

            stages = self._stages_for_chapter(chapter)
            if not stages:
                self._emit("chapter_skip", chapter_id=chapter["id"],
                           reason=f"status={chapter['status']}")
                results["skipped"] += 1
                continue

            try:
                self._run_chapter(chapter, stages)
                results["success"] += 1
            except Exception as exc:  # noqa: BLE001
                self._emit("chapter_error", chapter_id=chapter["id"],
                           stage=self._current_stage, error=str(exc))
                self._sm.mark_chapter_status(
                    chapter["id"], "error",
                    error_message=f"[failed_stage:{self._current_stage}] {exc}",
                )
                results["error"] += 1
                log.exception("chapter %d failed at %s", chapter["id"], self._current_stage)

        elapsed = round(time.time() - t0, 1)
        event_type = "pipeline_done" if self._stop_event.is_set() else "pipeline_stopped"
        self._emit(event_type, elapsed_s=elapsed, **results)
        return {**results, "elapsed_s": elapsed}

    def pause(self) -> None:
        self._pause_event.clear()

    def resume(self) -> None:
        self._pause_event.set()

    def stop(self) -> None:
        self._stop_event.clear()
        self._pause_event.set()  # unblock if currently paused

    @property
    def stopped(self) -> bool:
        return not self._stop_event.is_set()

    # -- Chapter routing --------------------------------------------------

    def _chapters_to_process(self) -> list[dict[str, Any]]:
        chapters = self._sm.get_all_chapters(self._project_id)
        r = self._cfg.chapter_range
        if r:
            start, end = r
            chapters = [c for c in chapters if start <= c["chapter_index"] <= end]
        return chapters

    def _stages_for_chapter(self, chapter: dict[str, Any]) -> list[str]:
        status = chapter["status"]
        if status != "error":
            return list(_STAGES_FOR_STATUS.get(status, []))
        # Resume from the stage that failed
        msg = chapter.get("error_message") or ""
        m = re.search(r"\[failed_stage:(\w+)\]", msg)
        if m:
            failed = m.group(1)
            try:
                return list(_ALL_STAGES[_ALL_STAGES.index(failed):])
            except ValueError:
                pass
        return list(_ALL_STAGES)

    # -- Chapter execution ------------------------------------------------

    def _run_chapter(self, chapter: dict[str, Any], stages: list[str]) -> None:
        ch_id = chapter["id"]
        self._emit("chapter_start", chapter_id=ch_id,
                   chapter_index=chapter["chapter_index"],
                   title=chapter.get("title", ""), stages=stages)
        t0 = time.time()

        if "diarize" in stages:
            self._stage_diarize(ch_id)
            self._vram_barrier()

        if "synthesize" in stages:
            self._stage_synthesize(ch_id)

        if "assemble" in stages:
            self._stage_assemble(ch_id, chapter)

        elapsed = round(time.time() - t0, 1)
        self._sm.mark_chapter_status(ch_id, "complete", processing_seconds=elapsed)
        ch_rows = self._sm.get_all_chapters(self._project_id)
        ch_row = next((c for c in ch_rows if c["id"] == ch_id), {})
        self._emit("chapter_done", chapter_id=ch_id,
                   audio_path=ch_row.get("output_audio_path", ""),
                   elapsed_s=elapsed)

    # -- Stages -----------------------------------------------------------

    def _stage_diarize(self, chapter_id: int) -> None:
        self._current_stage = "diarize"
        t0 = time.time()
        self._emit("stage_start", chapter_id=chapter_id, stage="diarize")

        if self._cfg.vram_check_enabled:
            self._vram_baseline_mb = _query_vram_mb()
            if self._vram_baseline_mb >= 0:
                log.info("VRAM baseline before LLM: %d MB", self._vram_baseline_mb)

        llm_cfg = {
            "n_gpu_layers": self._cfg.llm_n_gpu_layers,
            "n_ctx": self._cfg.llm_n_ctx,
        }
        with self._llm_cls(self._cfg.llm_model_path, self._sm, self._project_id, cfg=llm_cfg) as d:
            d.process_chapter(chapter_id)

        self._emit("stage_done", chapter_id=chapter_id, stage="diarize",
                   elapsed_s=round(time.time() - t0, 1))

    def _stage_synthesize(self, chapter_id: int) -> None:
        self._current_stage = "synthesize"
        t0 = time.time()
        self._emit("stage_start", chapter_id=chapter_id, stage="synthesize")

        tts_cfg = {
            "tts_model_dir": self._cfg.tts_model_dir,
            "num_beams": self._cfg.tts_num_beams,
            "use_deepspeed": self._cfg.tts_use_deepspeed,
        }
        wav_dir = config.from_stored(self._cfg.wav_output_dir) \
            if not Path(self._cfg.wav_output_dir).is_absolute() \
            else Path(self._cfg.wav_output_dir)

        with self._tts_cls(self._sm, self._project_id, wav_dir, cfg=tts_cfg) as engine:
            engine.process_chapter(chapter_id)

        self._emit("stage_done", chapter_id=chapter_id, stage="synthesize",
                   elapsed_s=round(time.time() - t0, 1))

    def _stage_assemble(self, chapter_id: int, chapter: dict[str, Any]) -> None:
        self._current_stage = "assemble"
        t0 = time.time()
        self._emit("stage_start", chapter_id=chapter_id, stage="assemble")

        lines = self._sm.get_lines_for_chapter(chapter_id)
        mp3_dir = Path(self._cfg.mp3_output_dir)
        if not mp3_dir.is_absolute():
            mp3_dir = config.data_root() / mp3_dir
        output_path = mp3_dir / f"ch_{chapter_id:04d}.mp3"

        asm = self._assembler_cls()
        out = asm.assemble_chapter(
            lines,
            output_path,
            title=chapter.get("title", ""),
            track_num=chapter.get("chapter_index", 0),
        )

        stored = config.to_stored(out)
        file_size = out.stat().st_size if out.exists() else None
        self._sm.mark_chapter_status(chapter_id, "tts_done",
                                     audio_path=stored,
                                     file_size_bytes=file_size)

        self._emit("stage_done", chapter_id=chapter_id, stage="assemble",
                   elapsed_s=round(time.time() - t0, 1))

    # -- VRAM barrier -----------------------------------------------------

    def _vram_barrier(self) -> None:
        if not self._cfg.vram_check_enabled:
            return
        baseline = self._vram_baseline_mb
        threshold = (
            baseline + _VRAM_DELTA_ALLOWANCE_MB
            if baseline >= 0
            else _VRAM_FALLBACK_THRESHOLD_MB
        )
        deadline = time.time() + self._cfg.vram_wait_timeout_s
        while True:
            used = _query_vram_mb()
            if used < 0:
                return  # nvidia-smi unavailable
            if used <= threshold:
                log.info(
                    "VRAM barrier OK: %d MB (baseline %d, limit %d)", used, baseline, threshold
                )
                return
            remaining = deadline - time.time()
            if remaining <= 0:
                self._emit("vram_warning", used_mb=used, threshold_mb=threshold,
                           baseline_mb=baseline)
                log.warning(
                    "VRAM still %d MB after %ds wait (baseline %d, limit %d). "
                    "Proceeding — risk of OOM.",
                    used, self._cfg.vram_wait_timeout_s, baseline, threshold,
                )
                return
            log.info(
                "VRAM barrier: %d MB used, want ≤%d MB, %.0fs left", used, threshold, remaining
            )
            time.sleep(2)

    # -- Event emitter ----------------------------------------------------

    def _emit(self, event_type: str, **kwargs: Any) -> None:
        event: dict[str, Any] = {"type": event_type, "ts": time.time(), **kwargs}
        self.events.append(event)
        self._on_progress(event)
        _log_event(event)


# -- Module-level helpers -------------------------------------------------

def _query_vram_mb() -> int:
    """Return VRAM used on GPU 0 in MB via nvidia-smi, or -1 on failure."""
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0:
            return int(result.stdout.strip().split("\n")[0])
    except Exception:  # noqa: BLE001
        pass
    return -1


def _log_event(event: dict[str, Any]) -> None:
    t = event.get("type", "?")
    if t == "stage_start":
        log.info(">> Stage: %s (chapter %s)", event.get("stage"), event.get("chapter_id"))
    elif t == "stage_done":
        log.info("<< Done: %s in %ss", event.get("stage"), event.get("elapsed_s"))
    elif t == "chapter_done":
        log.info("Chapter %s complete (%ss) -> %s",
                 event.get("chapter_id"), event.get("elapsed_s"), event.get("audio_path"))
    elif t == "chapter_error":
        log.error("Chapter %s FAILED at %s: %s",
                  event.get("chapter_id"), event.get("stage"), event.get("error"))
    elif t in ("pipeline_done", "pipeline_stopped"):
        log.info("Pipeline %s in %ss — success=%s error=%s skipped=%s",
                 t, event.get("elapsed_s"),
                 event.get("success"), event.get("error"), event.get("skipped"))
