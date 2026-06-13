"""LLM Director — label-only two-pass diarizer (Module 3).

Pass 1: SegmenterConfig (built from the Novel Profile) drives segment_chunk().
Pass 2: this module asks the local LLM to label each segment (speaker + emotion
        only — it never reproduces text). Grammar-locked JSON schema.

VRAM lifecycle: use as a context manager. Model loads in __enter__, purges in __exit__.
Never instantiate while the TTS engine is loaded (~12 GB VRAM constraint).

    with LLMDirector("models/Qwen3-14B-Q4_K_M.gguf", sm, project_id=pid) as d:
        d.process_chapter(chapter_id)
    # <- model fully unloaded here
"""

import gc
import json
import logging
import time
from pathlib import Path
from typing import Any, Optional

try:
    from llama_cpp import Llama
    from llama_cpp.llama_grammar import LlamaGrammar
    _LLAMA_AVAILABLE = True
except ImportError:
    _LLAMA_AVAILABLE = False

from verbatim.db.manager import StateManager
from verbatim.ingest.segmenter import (
    KIND_DIALOGUE, KIND_PROSE, KIND_SYSTEM, KIND_THOUGHT,
    SegmenterConfig, segment_chunk,
)
from verbatim.llm.parsing import (
    EMOTION_VOCAB, SYSTEM_SPEAKER,
    allowed_speakers, extract_json_block, is_narrator_misattribution,
    label_json_schema, parse_labels,
)
from verbatim.llm.prompts import build_system_prompt

log = logging.getLogger(__name__)

_KIND_TAGS = {KIND_DIALOGUE: "D", KIND_THOUGHT: "T", KIND_SYSTEM: "S", KIND_PROSE: "P"}

_DEFAULT_CFG: dict[str, Any] = {
    "n_ctx":        8192,
    "n_batch":      512,
    "n_gpu_layers": -1,
    "flash_attn":   True,
    "verbose":      False,
    "temperature":  0.2,
    "top_p":        0.8,
    "max_tokens":   4096,
    "retry_temp":   0.5,
    "max_retries":  3,
}


class LLMDirector:
    """
    Profile-aware LLM director. Must be used as a context manager.

        with LLMDirector("models/model.gguf", sm, project_id=pid) as d:
            d.process_chapter(chapter_id)
    """

    def __init__(
        self,
        model_path: "str | Path",
        sm: StateManager,
        project_id: int,
        cfg: "dict[str, Any] | None" = None,
    ):
        self.model_path = Path(model_path)
        self.sm = sm
        self.project_id = project_id
        self.cfg = {**_DEFAULT_CFG, **(cfg or {})}
        self._llm: Any = None
        self._grammar: Any = None
        # Populated by _setup_from_profile():
        self._system_prompt: str = ""
        self._allowed: set[str] = set()
        self._pov_character: str = "Narrator"
        self._segmenter_config: SegmenterConfig = SegmenterConfig()

    # -- Context manager (VRAM lifecycle) ------------------------------------

    def __enter__(self) -> "LLMDirector":
        if not _LLAMA_AVAILABLE:
            raise RuntimeError(
                "llama-cpp-python is not installed. "
                "Run: pip install llama-cpp-python --extra-index-url "
                "https://abetlen.github.io/llama-cpp-python/whl/cu124"
            )
        if not self.model_path.exists():
            raise FileNotFoundError(f"GGUF model not found: {self.model_path}")
        log.info("Loading model: %s", self.model_path.name)
        llama_kwargs: dict[str, Any] = dict(
            model_path=str(self.model_path),
            n_gpu_layers=self.cfg["n_gpu_layers"],
            n_ctx=self.cfg["n_ctx"],
            n_batch=self.cfg["n_batch"],
            flash_attn=self.cfg.get("flash_attn", True),
            verbose=self.cfg["verbose"],
        )
        try:
            self._llm = Llama(**llama_kwargs)
        except TypeError:
            llama_kwargs.pop("flash_attn", None)
            self._llm = Llama(**llama_kwargs)
        self._setup_from_profile()
        log.info("Model loaded.")
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> bool:
        self._purge_vram()
        return False

    def _purge_vram(self) -> None:
        if self._llm is not None:
            log.info("Unloading model from VRAM...")
            del self._llm
            self._llm = None
        self._grammar = None
        gc.collect()
        try:
            import torch
            torch.cuda.empty_cache()
            log.info("CUDA cache cleared.")
        except ImportError:
            pass
        log.info("VRAM released.")

    def _setup_from_profile(self) -> None:
        """Load project profile + cast from SM; build segmenter config, prompt, grammar.

        Separated from __enter__ so tests can call it without a real model loaded.
        """
        profile = self.sm.get_project_by_id(self.project_id) or {}
        characters = self.sm.list_characters(self.project_id)
        speakers = [c["name"] for c in characters if c["status"] == "cast"]
        hints = {c["name"]: c["emotion_hint"] for c in characters if c.get("emotion_hint")}

        pov_chars = profile.get("pov_characters") or []
        self._pov_character = pov_chars[0] if pov_chars else "Narrator"
        self._segmenter_config = SegmenterConfig(
            single_quote_thoughts=profile.get("thought_convention") == "single_quotes",
            bracket_system_lines=bool(profile.get("system_brackets", 0)),
        )
        self._allowed = allowed_speakers(speakers)
        self._system_prompt = build_system_prompt(profile, speakers, hints)
        self._grammar = self._build_grammar(speakers)

    def _build_grammar(self, speakers: list[str]) -> Any:
        """GBNF grammar from the label JSON schema. None on failure -> json_object fallback."""
        if not _LLAMA_AVAILABLE:
            return None
        try:
            schema = json.dumps(label_json_schema(speakers))
            return LlamaGrammar.from_json_schema(schema, verbose=False)
        except Exception as e:
            log.warning(
                "Grammar build failed (%s); falling back to response_format=json_object", e
            )
            return None

    # -- Public API -----------------------------------------------------------

    def process_chapter(self, chapter_id: int) -> int:
        """
        Diarize all chunks for a chapter and persist results to the DB.
        Returns total number of lines written. Sets chapter status to 'diarized'.
        """
        chunks = self.sm.get_chunks_for_chapter(chapter_id)
        if not chunks:
            raise ValueError(f"No chunks found for chapter_id={chapter_id}")

        log.info("Processing chapter_id=%d (%d chunks)...", chapter_id, len(chunks))
        all_lines: list[dict[str, Any]] = []
        for chunk in chunks:
            log.info(
                "  Chunk %d/%d (%d words)...",
                chunk["chunk_index"] + 1, len(chunks), chunk["word_count"],
            )
            lines = self._process_chunk(chunk["text"], line_offset=len(all_lines))
            all_lines.extend(lines)
            log.info("  -> %d lines", len(lines))

        self.sm.save_diarized_lines(chapter_id, all_lines)
        log.info("Chapter %d diarized: %d total lines.", chapter_id, len(all_lines))
        return len(all_lines)

    # -- Internal: segment formatting / merging ------------------------------

    @staticmethod
    def _format_segments(segments: list[dict[str, Any]]) -> str:
        return "\n".join(
            f"{s['index']} [{_KIND_TAGS[s['kind']]}] {s['text']}" for s in segments
        )

    def _merge_labels(
        self,
        segments: list[dict[str, Any]],
        labels: dict[int, tuple[str, str]],
        line_offset: int,
    ) -> list[dict[str, Any]]:
        """Apply structural speaker enforcement and produce final line dicts."""
        lines: list[dict[str, Any]] = []
        for seg in segments:
            speaker, emotion = labels[seg["index"]]
            kind, text = seg["kind"], seg["text"]

            if kind == KIND_PROSE:
                # Keep POV character's genuine first-person inner thought only.
                if not (
                    speaker == self._pov_character
                    and not is_narrator_misattribution(speaker, text)
                ):
                    if speaker != "Narrator":
                        log.debug("FIX  prose %r -> Narrator | %r", speaker, text[:60])
                    speaker = "Narrator"
            elif kind == KIND_THOUGHT:
                # Structural evidence: it IS a thought. Trust POV label; repair impossible ones.
                if speaker not in self._allowed or speaker == SYSTEM_SPEAKER:
                    speaker = self._pov_character
            elif kind == KIND_SYSTEM:
                # Brackets carry notifications AND telepathic messages — keep any valid roster label.
                if speaker not in self._allowed:
                    speaker = SYSTEM_SPEAKER
            else:  # dialogue
                if speaker not in self._allowed or speaker == "Narrator":
                    speaker = "Unknown"

            if emotion not in EMOTION_VOCAB:
                emotion = "neutral"

            lines.append({
                "line_index": line_offset + len(lines),
                "speaker":    speaker,
                "text":       text,
                "emotion":    emotion,
            })
        return lines

    def _fallback_lines(
        self, segments: list[dict[str, Any]], line_offset: int
    ) -> list[dict[str, Any]]:
        """Total-failure fallback: sensible per-kind defaults, all text preserved."""
        defaults: dict[str, tuple[str, str]] = {
            KIND_DIALOGUE: ("Unknown",           "neutral"),
            KIND_THOUGHT:  (self._pov_character, "neutral"),
            KIND_SYSTEM:   (SYSTEM_SPEAKER,      "cold"),
            KIND_PROSE:    ("Narrator",          "neutral"),
        }
        return [
            {
                "line_index": line_offset + i,
                "speaker":    defaults[seg["kind"]][0],
                "text":       seg["text"],
                "emotion":    defaults[seg["kind"]][1],
            }
            for i, seg in enumerate(segments)
        ]

    # -- Internal: retry loop ------------------------------------------------

    def _process_chunk(self, text: str, line_offset: int) -> list[dict[str, Any]]:
        segments = segment_chunk(text, self._segmenter_config)
        if not segments:
            return []

        user_msg = self._format_segments(segments)
        if "qwen3" in self.model_path.name.lower():
            user_msg += "\n/no_think"

        last_error: Optional[Exception] = None
        for attempt in range(self.cfg["max_retries"]):
            temp = self.cfg["temperature"] if attempt == 0 else self.cfg["retry_temp"]
            try:
                raw    = self._call_llm(user_msg, temperature=temp)
                labels = parse_labels(raw, n_segments=len(segments))
                return self._merge_labels(segments, labels, line_offset)
            except (ValueError, json.JSONDecodeError, KeyError, TypeError) as e:
                last_error = e
                log.warning("Label parse error (attempt %d): %s", attempt + 1, e)
                time.sleep(0.5)

        log.warning("All retries failed (%s). Falling back to per-segment defaults.", last_error)
        return self._fallback_lines(segments, line_offset)

    # -- Raw LLM call (injectable for testing) --------------------------------

    def _call_llm(self, text: str, temperature: float = 0.2) -> str:
        """Single inference call. Separated so tests can monkeypatch this."""
        if self._llm is None:
            raise RuntimeError(
                "LLMDirector must be used inside a 'with' block. Model is not loaded."
            )
        kwargs: dict[str, Any] = {
            "messages": [
                {"role": "system", "content": self._system_prompt},
                {"role": "user",   "content": text},
            ],
            "temperature": temperature,
            "top_p":       self.cfg.get("top_p", 0.8),
            "max_tokens":  self.cfg["max_tokens"],
        }
        if self._grammar is not None:
            kwargs["grammar"] = self._grammar
        else:
            kwargs["response_format"] = {"type": "json_object"}
        response = self._llm.create_chat_completion(**kwargs)
        return response["choices"][0]["message"]["content"]
