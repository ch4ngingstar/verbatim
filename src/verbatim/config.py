"""Data-root configuration and the relative-path storage contract.

Every file path persisted in the DB is stored relative to data_root()
(forward slashes). This makes the DB portable and immune to CWD changes -
the bug class that bit the Shadow Slave pipeline repeatedly.
"""

import os
from pathlib import Path


def data_root() -> Path:
    """Absolute data directory from VERBATIM_DATA_DIR (default ./data). Created on demand."""
    root = Path(os.environ.get("VERBATIM_DATA_DIR", "data")).resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


def to_stored(path: "str | Path") -> str:
    """Convert an absolute path under the data root to its stored (relative, posix) form."""
    p = Path(path).resolve()
    try:
        return p.relative_to(data_root()).as_posix()
    except ValueError as exc:
        raise ValueError(
            f"Refusing to store path outside data root {data_root()}: {p}"
        ) from exc


def from_stored(stored: str) -> Path:
    """Resolve a stored path back to an absolute path. Absolute inputs pass through."""
    p = Path(stored)
    return p.resolve() if p.is_absolute() else (data_root() / p).resolve()
