"""Emotion → IndexTTS2 vector map, text normalisation, and WAV silence helpers.

Ported from Shadow Slave tts_engine.py. No novel-specific content here — the
emotion vocabulary and vector values are tuned for IndexTTS2's 8-dim space.
"""

import re
import struct

# 8-dim order: [happy, angry, sad, afraid, disgust, melancholic, surprised, calm]
# (vector, emo_alpha). alpha=0 → pure speaker timbre; ~0.7 = max stable blend.
INDEXTTS2_EMOTION_VECTORS: dict[str, tuple[list[float], float]] = {
    "neutral":    ([0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0], 0.0),
    "whispers":   ([0.0, 0.0, 0.1, 0.0, 0.0, 0.2, 0.0, 0.6], 0.45),
    "angry":      ([0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0], 0.65),
    "sad":        ([0.0, 0.0, 0.9, 0.0, 0.0, 0.3, 0.0, 0.0], 0.65),
    "excited":    ([0.8, 0.0, 0.0, 0.0, 0.0, 0.0, 0.4, 0.0], 0.65),
    "commanding": ([0.0, 0.3, 0.0, 0.0, 0.0, 0.0, 0.0, 0.6], 0.60),
    "frightened": ([0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.2, 0.0], 0.70),
    "confused":   ([0.0, 0.0, 0.0, 0.2, 0.0, 0.2, 0.5, 0.0], 0.55),
    "pleading":   ([0.0, 0.0, 0.6, 0.3, 0.0, 0.0, 0.0, 0.0], 0.65),
    "cold":       ([0.0, 0.15, 0.0, 0.0, 0.1, 0.1, 0.0, 0.6], 0.45),
    "laughing":   ([1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.3, 0.0], 0.65),
    "sarcastic":  ([0.3, 0.2, 0.0, 0.0, 0.3, 0.0, 0.0, 0.3], 0.55),
    "desperate":  ([0.0, 0.0, 0.5, 0.6, 0.0, 0.2, 0.0, 0.0], 0.70),
}

# LLM occasionally emits stage directions in asterisks; remove them outright.
_STAGE_RE = re.compile(
    r"\*(?:sighs?|pauses?|laughs?|chuckles?|giggles?|groans?|grunts?|gasps?|"
    r"coughs?|snorts?|scoffs?|hums?|exhales?|inhales?|sniffs?|sobs?|"
    r"clears throat|beat|silence)\*",
    re.IGNORECASE,
)


def resolve_emotion(emotion: str, alpha_scale: float = 1.0) -> tuple[list[float] | None, float]:
    """Map an emotion label to (emo_vector, emo_alpha) for IndexTTS2.

    Returns (None, 0.0) for neutral / unknown → pure speaker timbre.
    """
    vec, alpha = INDEXTTS2_EMOTION_VECTORS.get(emotion, (None, 0.0))
    if vec is None or not any(v > 0.0 for v in vec):
        return None, 0.0
    return vec, alpha * alpha_scale


def normalize_text(text: str) -> str:
    """Clean text for maximum TTS accuracy: typography, abbreviations, symbols."""
    text = text.replace("“", '"').replace("”", '"')
    text = text.replace("‘", "'").replace("’", "'")
    text = _STAGE_RE.sub("", text)
    text = re.sub(r"\*([^*]{1,120})\*", r"\1", text)
    text = re.sub(r"\[([^\]]*)\]", r"\1", text)
    text = re.sub(r"(\w)—$", r"\1...", text)
    text = re.sub(r"(\w)—(\w)", r"\1, \2", text)
    text = text.replace("—", ", ")
    text = text.replace("–", " - ")
    text = text.replace("…", "...")
    text = text.replace(" ", " ")
    text = text.replace("​", "").replace("﻿", "")
    for pat, rep in [
        (r"\bDr\.", "Doctor"), (r"\bMr\.", "Mister"), (r"\bMrs\.", "Missus"),
        (r"\bMs\.", "Miss"), (r"\bSt\.", "Saint"), (r"\bvs\.", "versus"),
        (r"\bapprox\.", "approximately"), (r"\betc\.", "and so on"),
    ]:
        text = re.sub(pat, rep, text)
    for abbr, word in [
        ("1st", "first"), ("2nd", "second"), ("3rd", "third"), ("4th", "fourth"),
        ("5th", "fifth"), ("6th", "sixth"), ("7th", "seventh"), ("8th", "eighth"),
        ("9th", "ninth"), ("10th", "tenth"), ("11th", "eleventh"), ("12th", "twelfth"),
    ]:
        text = re.sub(r"\b" + re.escape(abbr) + r"\b", word, text, flags=re.IGNORECASE)
    text = re.sub(r"(\d+)\s*%", r"\1 percent", text)
    text = re.sub(r"\$(\d+)", r"\1 dollars", text)
    text = re.sub(r" {2,}", " ", text)
    text = re.sub(r"[,;]\s*$", ".", text)
    text = re.sub(r"(\w)$", lambda m: m.group(1) + ".", text)
    return text.strip()


def split_long_line(text: str, max_chars: int) -> list[str]:
    """Split text at sentence boundaries when it exceeds max_chars."""
    if len(text) <= max_chars:
        return [text]

    def hard_split(sent: str) -> list[str]:
        parts: list[str] = []
        while len(sent) > max_chars:
            cut = sent.rfind(",", max_chars // 2, max_chars)
            if cut != -1:
                head, sent = sent[: cut + 1], sent[cut + 1:]
            else:
                cut = sent.rfind(" ", max_chars // 2, max_chars)
                if cut != -1:
                    head, sent = sent[:cut], sent[cut + 1:]
                else:
                    head, sent = sent[:max_chars], sent[max_chars:]
            parts.append(head.strip())
            sent = sent.strip()
        if sent:
            parts.append(sent)
        return parts

    units: list[str] = []
    for sent in re.split(r"(?<=[.!?])\s+", text):
        if len(sent) > max_chars:
            units.extend(hard_split(sent))
        else:
            units.append(sent)

    chunks: list[str] = []
    cur = ""
    for unit in units:
        if cur and len(cur) + 1 + len(unit) <= max_chars:
            cur += " " + unit
        else:
            if cur:
                chunks.append(cur)
            cur = unit
    if cur:
        chunks.append(cur)
    return chunks or [text]


def wav_silence(duration_ms: int = 100, sample_rate: int = 22050) -> bytes:
    """Generate a minimal silent WAV as a TTS fallback placeholder."""
    n_samples = int(sample_rate * duration_ms / 1000)
    data = b"\x00\x00" * n_samples
    data_size = len(data)
    header = struct.pack(
        "<4sI4s4sIHHIIHH4sI",
        b"RIFF", 36 + data_size, b"WAVE",
        b"fmt ", 16, 1, 1,
        sample_rate, sample_rate * 2, 2, 16,
        b"data", data_size,
    )
    return header + data
