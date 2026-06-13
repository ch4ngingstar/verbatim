"""Casting Director — new pipeline stage between EPUB parse and diarization.

Reads the first N chapters, sends a sample to the local LLM, and receives a
structured JSON draft of the Novel Profile (POV style, thought convention,
narrator notes) plus a ranked character list. Writes directly to the DB via
StateManager; the user then reviews/edits the draft in the Casting Studio UI
before triggering diarization.

VRAM lifecycle: use as a context manager — model loads in __enter__, purges in __exit__.
Never run concurrently with LLMDirector or TTSEngine (~12 GB VRAM constraint).

    with CastingDirector("models/model.gguf", sm, project_id=pid) as cd:
        draft = cd.run()
    # <- model fully unloaded here
"""

import gc
import json
import logging
from pathlib import Path
from typing import Any

try:
    from llama_cpp import Llama
    _LLAMA_AVAILABLE = True
except ImportError:
    _LLAMA_AVAILABLE = False

from verbatim.db.manager import StateManager
from verbatim.db.schema import POV_STYLES, THOUGHT_CONVENTIONS
from verbatim.llm.parsing import extract_json_block

log = logging.getLogger(__name__)

_CASTING_SYSTEM_PROMPT = """\
You analyze the opening chapters of a novel to identify characters and narrative structure \
for a multi-voice audiobook production.

Return ONLY this JSON object, filled in for the given text:
{
  "pov_style": "third",
  "pov_characters": ["Name"],
  "thought_convention": "none",
  "narrator_notes": "One sentence describing narrator style.",
  "characters": [
    {
      "name": "canonical full name",
      "aliases": ["other names seen in text"],
      "is_pov": false,
      "emotion_hint": "brief personality note, e.g. stoic, cold default"
    }
  ]
}

Rules:
- Include ONLY named characters who speak, act, or are named in scenes
- List characters in order of importance (most appearances first)
- "aliases" lists EVERY other name used for this character in the text
- "pov_style": "first" if narrated in first person ("I walked in"), "third" otherwise
- "pov_characters": the character(s) whose perspective the narration follows
- "thought_convention": "single_quotes" if 'single-quoted spans' mark inner thoughts, \
  "none" otherwise
- "emotion_hint": one line, e.g. "warm, enthusiastic" or "stoic, rarely emotional"
- "narrator_notes": brief style note, e.g. "Third-person limited. Dry, ironic tone."
"""

_CASTING_USER_PREFIX = (
    "Analyze the following novel excerpt and return the character profile JSON.\n\n"
)

_DEFAULT_CFG: dict[str, Any] = {
    "n_ctx":        8192,
    "n_batch":      512,
    "n_gpu_layers": -1,
    "flash_attn":   True,
    "verbose":      False,
    "temperature":  0.3,
    "top_p":        0.9,
    "max_tokens":   2048,
}


class CastingDirector:
    """
    Reads the first `n_chapters` chapters, calls the LLM for a character draft,
    and writes the result to the DB. Must be used as a context manager.

        with CastingDirector("models/model.gguf", sm, project_id=pid) as cd:
            draft = cd.run()
    """

    def __init__(
        self,
        model_path: "str | Path",
        sm: StateManager,
        project_id: int,
        cfg: "dict[str, Any] | None" = None,
        n_chapters: int = 10,
    ):
        self.model_path = Path(model_path)
        self.sm = sm
        self.project_id = project_id
        self.cfg = {**_DEFAULT_CFG, **(cfg or {})}
        self.n_chapters = n_chapters
        self._llm: Any = None

    # -- Context manager (VRAM lifecycle) ------------------------------------

    def __enter__(self) -> "CastingDirector":
        if not _LLAMA_AVAILABLE:
            raise RuntimeError(
                "llama-cpp-python is not installed. "
                "Run: pip install llama-cpp-python --extra-index-url "
                "https://abetlen.github.io/llama-cpp-python/whl/cu124"
            )
        if not self.model_path.exists():
            raise FileNotFoundError(f"GGUF model not found: {self.model_path}")
        log.info("CastingDirector: loading model %s", self.model_path.name)
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
        log.info("CastingDirector: model loaded.")
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        if self._llm is not None:
            log.info("CastingDirector: unloading model...")
            del self._llm
            self._llm = None
        gc.collect()
        try:
            import torch
            torch.cuda.empty_cache()
        except ImportError:
            pass
        log.info("CastingDirector: VRAM released.")

    # -- Public API ----------------------------------------------------------

    def run(self) -> dict[str, Any]:
        """
        Read first n_chapters, call LLM, write profile + characters to DB.
        Returns the parsed draft dict.
        """
        sample_text = self._assemble_sample_text()
        user_message = _CASTING_USER_PREFIX + sample_text
        raw = self._call_llm(user_message)
        draft = self._parse_response(raw)
        self._write_to_db(draft)
        log.info(
            "CastingDirector: drafted %d characters, pov=%s, thought_convention=%s",
            len(draft["characters"]), draft["pov_style"], draft["thought_convention"],
        )
        return draft

    # -- Internal ------------------------------------------------------------

    def _assemble_sample_text(self) -> str:
        """Gather the first n_chapters chapters' chunk texts."""
        chapters = self.sm.get_all_chapters(self.project_id)
        sample_chapters = chapters[: self.n_chapters]
        parts: list[str] = []
        for ch in sample_chapters:
            chunks = self.sm.get_chunks_for_chapter(ch["id"])
            chapter_text = "\n\n".join(ck["text"] for ck in chunks)
            parts.append(f"=== {ch['title']} ===\n{chapter_text}")
        return "\n\n".join(parts)

    def _parse_response(self, raw: str) -> dict[str, Any]:
        """Parse and validate the LLM JSON response."""
        data = json.loads(extract_json_block(raw))

        pov_style = str(data.get("pov_style", "third"))
        if pov_style not in POV_STYLES:
            pov_style = "third"

        thought_convention = str(data.get("thought_convention", "none"))
        if thought_convention not in THOUGHT_CONVENTIONS:
            thought_convention = "none"

        pov_characters = [str(n) for n in data.get("pov_characters", []) if n]
        narrator_notes = str(data.get("narrator_notes", "") or "").strip()

        characters: list[dict[str, Any]] = []
        for c in data.get("characters", []):
            name = str(c.get("name", "")).strip()
            if not name:
                continue
            characters.append({
                "name":         name,
                "aliases":      [str(a) for a in c.get("aliases", []) if a],
                "is_pov":       bool(c.get("is_pov", False)),
                "emotion_hint": str(c.get("emotion_hint", "") or "").strip(),
            })

        return {
            "pov_style":          pov_style,
            "pov_characters":     pov_characters,
            "thought_convention": thought_convention,
            "narrator_notes":     narrator_notes,
            "characters":         characters,
        }

    def _write_to_db(self, draft: dict[str, Any]) -> None:
        """Persist the draft profile and character list to the DB."""
        self.sm.update_profile(
            self.project_id,
            pov_style=draft["pov_style"],
            pov_characters=draft["pov_characters"],
            thought_convention=draft["thought_convention"],
            narrator_notes=draft["narrator_notes"],
        )
        for char in draft["characters"]:
            self.sm.upsert_character(
                self.project_id,
                name=char["name"],
                aliases=char["aliases"],
                is_pov=char["is_pov"],
                emotion_hint=char["emotion_hint"],
                status="suggested",
            )

    def _call_llm(self, user_text: str) -> str:
        """Single inference call. Separated so tests can monkeypatch this."""
        if self._llm is None:
            raise RuntimeError(
                "CastingDirector must be used inside a 'with' block. Model is not loaded."
            )
        response = self._llm.create_chat_completion(
            messages=[
                {"role": "system", "content": _CASTING_SYSTEM_PROMPT},
                {"role": "user",   "content": user_text},
            ],
            temperature=self.cfg["temperature"],
            top_p=self.cfg.get("top_p", 0.9),
            max_tokens=self.cfg["max_tokens"],
            response_format={"type": "json_object"},
        )
        return response["choices"][0]["message"]["content"]
