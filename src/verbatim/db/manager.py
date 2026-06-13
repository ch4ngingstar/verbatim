"""StateManager facade - the single source of truth for all pipeline state.

Composed from ops mixins so each concern stays in its own file:
  ProjectOps  - projects + Novel Profile
  ChapterOps  - chapters, chunks, lines, progress
  CastingOps  - characters + global voice library
"""

from pathlib import Path

from verbatim.db.base import Database
from verbatim.db.casting import CastingOps
from verbatim.db.chapters import ChapterOps
from verbatim.db.projects import ProjectOps


class StateManager(ProjectOps, ChapterOps, CastingOps):
    def __init__(self, db_path: "str | Path"):
        self.db = Database(db_path)
