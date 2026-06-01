from pydantic import BaseModel, Field


class VisualReport(BaseModel):
    total_score: float = Field(ge=0.0, le=10.0)
    composition: float = Field(ge=0.0, le=10.0)
    subject_match: float = Field(ge=0.0, le=10.0)
    style_match: float = Field(ge=0.0, le=10.0)
    technical_quality: float = Field(ge=0.0, le=10.0)
    defects: list[str] = Field(default_factory=list)
    suggestion: str = ""
    optimization_hints: list[str] = Field(default_factory=list)
    optimization_prompt: str = ""
    candidate_prompts: list[dict] = Field(default_factory=list)
