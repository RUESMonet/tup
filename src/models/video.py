from typing import Any

from pydantic import BaseModel, Field, field_validator


class VideoGenerateRequest(BaseModel):
    prompt: str = Field(min_length=1)
    source_image_asset_id: str | None = None
    source_image_url: str | None = None
    duration: int | None = Field(default=None, ge=1, le=60)
    aspect_ratio: str | None = Field(default=None, max_length=32)
    params: dict[str, Any] = Field(default_factory=dict)

    @field_validator("prompt")
    @classmethod
    def strip_prompt(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Prompt is required")
        return normalized


class VideoResult(BaseModel):
    url: str
    media_type: str = "video/mp4"
    model_id: str = "video"
    provider_model: str
    metadata: dict[str, Any] = Field(default_factory=dict)
