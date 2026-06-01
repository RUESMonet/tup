import json
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


class ConversationCreateRequest(BaseModel):
    title: str = Field(default="Untitled conversation", max_length=160)
    summary: str = Field(default="", max_length=2000)

    @field_validator("title", "summary")
    @classmethod
    def strip_text(cls, value: str) -> str:
        return value.strip()


class ConversationMessageCreateRequest(BaseModel):
    role: Literal["user"] = "user"
    content: str = Field(min_length=1, max_length=20000)
    asset_ids: list[str] = Field(default_factory=list, max_length=16)
    prompt_snapshot: dict[str, Any] = Field(default_factory=dict, max_length=32)

    @field_validator("content")
    @classmethod
    def strip_content(cls, value: str) -> str:
        normalized = " ".join(value.strip().split())
        if not normalized:
            raise ValueError("content cannot be empty")
        return normalized

    @field_validator("prompt_snapshot")
    @classmethod
    def limit_prompt_snapshot(cls, value: dict[str, Any]) -> dict[str, Any]:
        if len(json.dumps(value, ensure_ascii=False, separators=(",", ":"))) > 12000:
            raise ValueError("prompt_snapshot is too large")
        if _contains_data_url(value):
            raise ValueError("prompt_snapshot cannot contain data URLs")
        return value


def _contains_data_url(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower().startswith("data:")
    if isinstance(value, dict):
        return any(_contains_data_url(item) for item in value.values())
    if isinstance(value, list):
        return any(_contains_data_url(item) for item in value)
    return False


class ConversationResponse(BaseModel):
    id: str
    project_id: str
    title: str
    summary: str = ""
    created_at: datetime
    updated_at: datetime


class ConversationMessageResponse(BaseModel):
    id: str
    conversation_id: str
    role: str
    content: str
    asset_ids: list[str] = Field(default_factory=list)
    prompt_snapshot: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class CharacterSheetResponse(BaseModel):
    id: str
    project_id: str
    conversation_id: str
    name: str
    identity_anchors: list[str]
    visual_traits: dict[str, Any] = Field(default_factory=dict)
    locked_prompt_text: str
    source_asset_ids: list[str] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class ConversationDetailResponse(ConversationResponse):
    messages: list[ConversationMessageResponse] = Field(default_factory=list)
    character_sheets: list[CharacterSheetResponse] = Field(default_factory=list)
