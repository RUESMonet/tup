from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field, field_validator

from src.models.billing import ReviewStatus
from src.models.task import TaskStatus


class TaskKind(StrEnum):
    image = "image"
    image_batch = "image_batch"
    image_edit = "image_edit"
    text_to_video = "text_to_video"
    image_to_video = "image_to_video"


class AssetKind(StrEnum):
    image = "image"
    video = "video"


class ProjectCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=1000)

    @field_validator("name", "description")
    @classmethod
    def strip_text(cls, value: str) -> str:
        return value.strip()

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        if not value:
            raise ValueError("Project name is required")
        return value


class ProjectRecord(BaseModel):
    id: str
    owner_id: str
    name: str
    description: str = ""
    created_at: datetime
    updated_at: datetime


class ProjectResponse(BaseModel):
    id: str
    name: str
    description: str = ""
    created_at: datetime
    updated_at: datetime


class ProjectListResponse(BaseModel):
    projects: list[ProjectResponse]


class AssetResponse(BaseModel):
    id: str
    project_id: str
    kind: AssetKind
    url: str
    media_type: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    review_status: ReviewStatus = "pending"
    review_notes: str = ""
    reviewed_by: str | None = None
    reviewed_at: datetime | None = None
    created_at: datetime


class AssetListResponse(BaseModel):
    assets: list[AssetResponse]


class ProjectTaskResponse(BaseModel):
    task_id: str
    project_id: str
    kind: TaskKind
    status: TaskStatus
    input: dict[str, Any]
    result: dict[str, Any] | None = None
    error: str | None = None
    cost_estimate: int = 0
    charged_credits: int = 0
    created_at: datetime
    updated_at: datetime


class ProjectTaskListResponse(BaseModel):
    tasks: list[ProjectTaskResponse]
