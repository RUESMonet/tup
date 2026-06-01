from typing import Literal

from pydantic import BaseModel, Field


GuideDimension = Literal["subject", "style", "lighting", "composition", "detail", "constraints"]


class GuideIssue(BaseModel):
    dimension: GuideDimension
    title: str
    detail: str
    severity: Literal["high", "medium", "low"] = "medium"


class GuideAction(BaseModel):
    title: str
    instruction: str
    example: str = ""
    priority: Literal["high", "medium", "low"] = "medium"


class OptimizationGuide(BaseModel):
    summary: str
    issues: list[GuideIssue] = Field(default_factory=list)
    actions: list[GuideAction] = Field(default_factory=list)
    next_steps: list[str] = Field(default_factory=list)
