from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator

from src.models.prompt_skill import ImageSource


class EditMode(StrEnum):
    GLOBAL_EDIT = "global_edit"
    INPAINT = "inpaint"
    OUTPAINT = "outpaint"
    STYLE_TRANSFER = "style_transfer"
    REFERENCE_GENERATION = "reference_generation"


class NormalizedRegion(BaseModel):
    x: float = Field(ge=0.0, le=1.0)
    y: float = Field(ge=0.0, le=1.0)
    width: float = Field(gt=0.0, le=1.0)
    height: float = Field(gt=0.0, le=1.0)


class ImageEditRequest(BaseModel):
    prompt: str = Field(min_length=1)
    mode: EditMode = EditMode.GLOBAL_EDIT
    source_images: list[ImageSource] = Field(min_length=1)
    mask_image: ImageSource | None = None
    selected_regions: list[NormalizedRegion] = Field(default_factory=list)
    params: dict[str, Any] = Field(default_factory=dict)

    @field_validator("prompt")
    @classmethod
    def normalize_prompt(cls, value: str) -> str:
        normalized = " ".join(value.strip().split())
        if not normalized:
            raise ValueError("prompt cannot be empty")
        return normalized

    @model_validator(mode="after")
    def validate_edit_invariants(self) -> "ImageEditRequest":
        if self.mode == EditMode.INPAINT and self.mask_image is None and not self.selected_regions:
            raise ValueError("inpaint requires mask_image or selected_regions")
        if self.mode == EditMode.OUTPAINT and not self.selected_regions:
            raise ValueError("outpaint requires selected_regions describing the canvas extension area")
        return self
