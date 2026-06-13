"""Voice resolution — maps diarizer speaker labels to reference audio paths.

In Verbatim, SPEAKER_ALIASES is replaced by per-project character aliases stored
in the DB. `build_voice_map` derives the full title-cased lookup table from the
characters table; `resolve_ref_audio` performs a two-step lookup with _default
fallback.
"""

import logging
from pathlib import Path

from verbatim import config
from verbatim.db.manager import StateManager

log = logging.getLogger(__name__)


def build_voice_map(sm: StateManager, project_id: int) -> dict[str, str]:
    """Build {title-cased name-or-alias: stored voice path} from the DB.

    Delegates to StateManager.get_project_voice_map which covers:
      - All cast characters with an assigned voice (canonical names + aliases)
      - The global '_default' voice if registered
    """
    return sm.get_project_voice_map(project_id)


def resolve_ref_audio(
    speaker: str,
    voice_map: dict[str, str],
) -> Path | None:
    """Resolve a speaker label to an absolute reference-audio path.

    Resolution order:
      1. Normalise: speaker.strip().title()
      2. Look up in voice_map (already contains aliases expanded from DB)
      3. Try '_default' fallback
      4. Return None — caller should skip the line

    Returned path is absolute (via config.from_stored); the caller does not need
    to know whether voice_map values are relative or absolute.
    """
    normalised = speaker.strip().title()

    stored = voice_map.get(normalised)
    if stored:
        return config.from_stored(stored)

    stored = voice_map.get("_default")
    if stored:
        log.debug("FALLBACK voice for %r -> _default", speaker)
        return config.from_stored(stored)

    return None
