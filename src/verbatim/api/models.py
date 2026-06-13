"""Pydantic request/response models for the Verbatim API."""

from pydantic import BaseModel, field_validator

# -- Project ------------------------------------------------------------------

class ProjectCreate(BaseModel):
    epub_path:      str
    llm_model_path: str = ""
    tts_model_dir:  str = "index-tts/checkpoints"


class NovelProfileUpdate(BaseModel):
    pov_style:          str | None = None
    pov_characters:     list[str] | None = None
    thought_convention: str | None = None
    system_brackets:    bool | None = None
    narrator_notes:     str | None = None


class CastingAnalyzeRequest(BaseModel):
    llm_model_path:   str
    n_chapters:       int = 10
    llm_n_gpu_layers: int = -1


# -- Pipeline -----------------------------------------------------------------

class PipelineStart(BaseModel):
    project_id:          int
    llm_model_path:      str
    tts_model_dir:       str = "index-tts/checkpoints"
    chapter_range:       list[int] | None = None  # [start_idx, end_idx] inclusive
    vram_check_enabled:  bool = True
    llm_n_gpu_layers:    int = -1
    tts_num_beams:       int = 3

    @field_validator("chapter_range")
    @classmethod
    def validate_range(cls, v: list[int] | None) -> list[int] | None:
        if v is None:
            return v
        if len(v) != 2:
            raise ValueError("chapter_range must have exactly 2 elements: [start, end]")
        if v[0] < 0:
            raise ValueError("chapter_range indices must be non-negative")
        if v[0] > v[1]:
            raise ValueError("chapter_range[0] must be <= chapter_range[1]")
        return v


# -- Characters / Casting -----------------------------------------------------

class CharacterUpsert(BaseModel):
    name:         str
    aliases:      list[str] = []
    emotion_hint: str = ""
    is_pov:       bool = False
    status:       str = "suggested"


class CharacterVoiceAssign(BaseModel):
    voice_name: str  # voice library name, not ID


# -- Voice library ------------------------------------------------------------

class VoiceAdd(BaseModel):
    name:  str
    path:  str  # absolute or data-root-relative
    tags:  list[str] = []


# -- M4B export ---------------------------------------------------------------

class M4BExportRequest(BaseModel):
    project_id: int
    output_filename: str = ""  # defaults to "<project-name>.m4b"
    author: str = ""
