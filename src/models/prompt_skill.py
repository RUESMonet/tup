from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator


class ImageActionType(StrEnum):
    TEXT_TO_IMAGE = "text_to_image"
    IMAGE_TO_IMAGE = "image_to_image"
    TEXT_AND_IMAGE_TO_IMAGE = "text_and_image_to_image"
    EDIT = "edit"
    INPAINT = "inpaint"
    OUTPAINT = "outpaint"
    STYLE_TRANSFER = "style_transfer"


class ImageSource(BaseModel):
    url: str | None = None
    asset_id: str | None = None
    media_type: str | None = None
    role: str = "source"
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def require_reference(self) -> "ImageSource":
        if not self.url and not self.asset_id:
            raise ValueError("ImageSource requires either url or asset_id")
        return self


class SuggestedImageParams(BaseModel):
    aspect_ratio: str | None = None
    size: str | None = None
    quality: str | None = None
    background: str | None = None
    extras: dict[str, Any] = Field(default_factory=dict)


class PromptIntent(BaseModel):
    action_type: ImageActionType = ImageActionType.TEXT_TO_IMAGE
    profile: str = "default"
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    needs_text_rendering: bool = False
    needs_character_consistency: bool = False
    needs_user_clarification: bool = False
    clarifying_questions: list[str] = Field(default_factory=list)
    detected_text_literals: list[str] = Field(default_factory=list)
    character_anchors: list[str] = Field(default_factory=list)
    aspect_ratio: str | None = None
    edit_instruction: str | None = None
    preserve_directives: list[str] = Field(default_factory=list)
    modify_directives: list[str] = Field(default_factory=list)
    avoid_directives: list[str] = Field(default_factory=list)
    source_image_count: int = 0
    signals: dict[str, float] = Field(default_factory=dict)


class ReferenceUsage(BaseModel):
    retrieval_strategy: str
    matched_cases: list[dict[str, Any]] = Field(default_factory=list)
    pattern_principles: list[str] = Field(default_factory=list)
    source_freshness: dict[str, Any] = Field(default_factory=dict)


class PromptSkillRequest(BaseModel):
    prompt: str = Field(min_length=1)
    action_type: ImageActionType | None = None
    source_images: list[ImageSource] = Field(default_factory=list, max_length=8)
    mask_image: ImageSource | None = None
    conversation_id: str | None = None
    conversation_context: list[dict[str, Any]] = Field(default_factory=list, max_length=12)
    character_anchors: list[str] = Field(default_factory=list, max_length=40)
    params: dict[str, Any] = Field(default_factory=dict)
    defects: list[str] = Field(default_factory=list, max_length=20)

    @field_validator("prompt")
    @classmethod
    def normalize_prompt(cls, value: str) -> str:
        normalized = " ".join(value.strip().split())
        if not normalized:
            raise ValueError("prompt cannot be empty")
        return normalized

    @model_validator(mode="after")
    def validate_action_assets(self) -> "PromptSkillRequest":
        edit_actions = {
            ImageActionType.EDIT,
            ImageActionType.INPAINT,
            ImageActionType.OUTPAINT,
            ImageActionType.STYLE_TRANSFER,
            ImageActionType.IMAGE_TO_IMAGE,
            ImageActionType.TEXT_AND_IMAGE_TO_IMAGE,
        }
        if self.action_type in edit_actions and not self.source_images:
            raise ValueError("source_images are required for image-based prompt skill actions")
        if self.action_type == ImageActionType.INPAINT and self.mask_image is None:
            raise ValueError("mask_image is required for inpaint actions")
        return self


class PromptSkillResponse(BaseModel):
    task: str = "prompt_skill_optimization"
    intent: PromptIntent
    optimized_prompt: dict[str, Any]
    final_english_prompt: str
    reference_usage: ReferenceUsage
    suggested_params: SuggestedImageParams = Field(default_factory=SuggestedImageParams)
    quality_gates: list[str] = Field(default_factory=list)
    edit_policy: dict[str, list[str]] = Field(default_factory=dict)
    character_policy: dict[str, Any] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
