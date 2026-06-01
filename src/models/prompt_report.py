from pydantic import BaseModel, ConfigDict, Field


class PromptReport(BaseModel):
    model_config = ConfigDict(serialize_by_alias=True)

    score: float = Field(ge=0.0, le=10.0)
    passed: bool = Field(serialization_alias="pass")
    missing: list[str] = Field(default_factory=list)
    suggestion: str
