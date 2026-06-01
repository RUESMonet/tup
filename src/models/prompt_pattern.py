from pydantic import BaseModel, Field


class PromptPattern(BaseModel):
    id: str
    profile: str
    title: str
    source_case: str
    principles: list[str] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)
    relevance: float = 0.0


class PromptPatternReference(BaseModel):
    profile: str
    profile_confidence: float
    matched_patterns: list[PromptPattern] = Field(default_factory=list)
    pattern_principles: list[str] = Field(default_factory=list)
    source_freshness: dict = Field(default_factory=dict)
