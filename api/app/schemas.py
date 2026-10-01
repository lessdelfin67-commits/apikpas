from enum import Enum
from typing import Any
from pydantic import BaseModel, Field, HttpUrl, field_validator


class MediaType(str, Enum):
    video = "video"
    audio = "audio"


class JobStatus(str, Enum):
    queued = "queued"
    processing = "processing"
    completed = "completed"
    failed = "failed"


class ConvertRequest(BaseModel):
    type: MediaType = Field(..., alias="tipo")
    format: str = Field(..., alias="formato", min_length=2, max_length=10)
    quality: str | None = Field(None, alias="qualidade", pattern=r"^\d{3,4}p$")
    resolution: str | None = Field(None, alias="resolucao", pattern=r"^\d{2,5}x\d{2,5}$")
    fps: float | None = Field(None, alias="fps", gt=0, le=240)
    codec: str | None = Field(None, alias="codec", min_length=2, max_length=32)
    bitrate: int | None = Field(None, alias="bitrate", ge=8, le=100000)

    model_config = {"populate_by_name": True}

    @field_validator("format", "codec", mode="before")
    @classmethod
    def normalize_text(cls, value: Any) -> Any:
        return value.lower().strip() if isinstance(value, str) else value


class JobResponse(BaseModel):
    job_id: str
    status: JobStatus
    progress: float = Field(ge=0, le=100)
    speed: str | None = None
    eta_seconds: float | None = None
    error: str | None = None
    filename: str | None = None


class AnalyzeResponse(BaseModel):
    title: str | None
    duration_seconds: float | None
    size_bytes: int | None
    media_type: MediaType
    resolutions: list[str]
    qualities: list[str]
    fps: list[float]
    video_codecs: list[str]
    audio_codecs: list[str]
    video_formats: list[str]
    audio_formats: list[str]
    audio_bitrates_kbps: list[int]
    streams: list[dict[str, Any]]
