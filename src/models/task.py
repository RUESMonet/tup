from datetime import datetime, timezone
from enum import StrEnum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field

from src.models.prompt_report import PromptReport
from src.models.visual_report import VisualReport


class TaskStatus(StrEnum):
    pending = "pending"
    running = "running"
    succeeded = "succeeded"
    failed = "failed"


class ImageResult(BaseModel):
    url: str | None = None
    b64_json: str | None = None
    model_id: str
    provider_model: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class IterationRecord(BaseModel):
    iteration: int
    prompt: str
    image: ImageResult | None = None
    visual_report: VisualReport | None = None


PromptPayloadValue = str | list[str]


class PromptPayloadView(BaseModel):
    subject: PromptPayloadValue | None = None
    environment: PromptPayloadValue | None = None
    style: PromptPayloadValue | None = None
    lighting: PromptPayloadValue | None = None
    camera_and_composition: PromptPayloadValue | None = None
    atmosphere: PromptPayloadValue | None = None
    color_palette: PromptPayloadValue | None = None
    text_and_logo_constraints: PromptPayloadValue | None = None
    constraints: PromptPayloadValue | None = None
    negative_prompt: PromptPayloadValue | None = None
    additional_constraints: list[PromptPayloadValue] = Field(default_factory=list)
    pattern_principles: list[PromptPayloadValue] = Field(default_factory=list)
    quality_requirements: list[PromptPayloadValue] = Field(default_factory=list)
    revision_focus: list[PromptPayloadValue] = Field(default_factory=list)


class PromptOptimizationStage(BaseModel):
    stage: str
    title: str
    summary: str = ""
    score: float | None = None
    passed: bool | None = None
    missing: list[str] = Field(default_factory=list)
    defects: list[str] = Field(default_factory=list)
    suggestion: str = ""
    source: str = ""
    profile: str = ""
    selected_terms: dict[str, PromptPayloadValue | None] = Field(default_factory=dict)
    prompt_payload: PromptPayloadView | None = None


class PromptOptimizationTrace(BaseModel):
    original_prompt: str
    profile: str
    quality_source: str
    stages: list[PromptOptimizationStage] = Field(default_factory=list)


class PipelineResult(BaseModel):
    image: ImageResult
    final_prompt: str
    score: float
    iterations: int
    prompt_report: PromptReport
    prompt_history: list[IterationRecord]
    optimization_trace: PromptOptimizationTrace | None = None


class TaskRecord(BaseModel):
    task_id: str = Field(default_factory=lambda: str(uuid4()))
    owner_id: str
    status: TaskStatus = TaskStatus.pending
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    result: PipelineResult | None = None
    error: str | None = None

    def touch(self) -> None:
        self.updated_at = datetime.now(timezone.utc)

