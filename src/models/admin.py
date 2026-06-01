from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from src.models.billing import ReviewStatus
from src.models.project import AssetKind, TaskKind
from src.models.task import TaskStatus


class ModelSettingsUpdate(BaseModel):
    settings: dict[str, Any | None] = Field(default_factory=dict)


class ModelSettingsResponse(BaseModel):
    settings: dict[str, dict[str, Any]]




class AdminUserSummary(BaseModel):
    id: str
    username: str
    email: str
    role: Literal["user", "admin"]
    credit_balance: int = 0
    created_at: datetime


class AdminUserListResponse(BaseModel):
    users: list[AdminUserSummary]


class AdminTaskSummary(BaseModel):
    task_id: str
    owner_id: str
    project_id: str
    kind: TaskKind
    status: TaskStatus
    error: str | None = None
    cost_estimate: int = 0
    charged_credits: int = 0
    created_at: datetime
    updated_at: datetime
    owner_username: str | None = None


class AdminTaskListResponse(BaseModel):
    tasks: list[AdminTaskSummary]


class AdminAssetSummary(BaseModel):
    id: str
    owner_id: str
    owner_username: str
    project_id: str
    project_name: str
    kind: AssetKind
    url: str
    media_type: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    review_status: ReviewStatus = "pending"
    review_notes: str = ""
    reviewed_by: str | None = None
    reviewed_at: datetime | None = None
    created_at: datetime


class AdminAssetListResponse(BaseModel):
    assets: list[AdminAssetSummary]


class AdminAssetReviewUpdate(BaseModel):
    review_status: ReviewStatus
    review_notes: str = Field(default="", max_length=1000)

    @field_validator("review_notes", mode="before")
    @classmethod
    def strip_review_notes(cls, value: str) -> str:
        if isinstance(value, str):
            return value.strip()
        return value


AdminAssetReviewUpdateRequest = AdminAssetReviewUpdate
