import json
import re
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from src.models.prompt_skill import ImageActionType


MAX_CANVAS_PAYLOAD_BYTES = 20000
MAX_CANVAS_PAYLOAD_DEPTH = 8
MAX_CANVAS_GENERATE_IMAGE_COUNT = 4
MENTION_LABEL_RE = re.compile(r"^[a-z0-9一-龥-]{1,32}$")
CANVAS_GENERATE_IMAGE_PARAMS = {
    "size": {"auto", "1024x1024", "1536x1024", "1024x1536"},
    "quality": {"auto", "low", "medium", "high"},
    "background": {"auto", "transparent", "opaque"},
    "output_format": {"png", "jpeg", "webp"},
    "moderation": {"auto", "low"},
}
CANVAS_PROMPT_TEXT_FIELDS = {
    "action_type",
    "approval_reason",
    "approval_status",
    "approved_at",
    "asset_id",
    "asset_kind",
    "aspect_ratio",
    "at",
    "atmosphere",
    "batch_id",
    "brief",
    "camera",
    "camera_and_composition",
    "camera_block",
    "camera_motion",
    "candidate_id",
    "color_palette",
    "composition",
    "composition_block",
    "duration",
    "edit_prompt",
    "ending_state",
    "environment",
    "evaluation_node_id",
    "final_prompt",
    "from_status",
    "goal",
    "image_url",
    "instruction",
    "lighting",
    "lighting_block",
    "mask_asset_id",
    "media_type",
    "mention_label",
    "motion_prompt",
    "negative_prompt",
    "operation",
    "optimization_prompt",
    "plan_profile",
    "profile",
    "prompt",
    "prompt_artifact_id",
    "video_prompt_artifact_id",
    "provenance",
    "reference_instruction",
    "reference_role",
    "repair_focus_key",
    "repair_focus_label",
    "repair_parent_batch_id",
    "repair_prompt_node_id",
    "role",
    "scene",
    "scene_block",
    "setting",
    "shot_size",
    "source",
    "source_asset_id",
    "source_canvas_id",
    "source_image_asset_id",
    "source_image_node_id",
    "source_image_title",
    "source_project_id",
    "status",
    "style",
    "subject",
    "subject_action",
    "subject_block",
    "target_profile",
    "target_score",
    "task_id",
    "temporal_rhythm",
    "to_status",
    "video_url",
    "visual_style",
    "workflow",
}
CANVAS_PROMPT_TEXT_LIST_FIELDS = {
    "avoid",
    "character_anchors",
    "constraints",
    "defects",
    "dimensions",
    "identity_anchors",
    "manifest_sections",
    "must_keep",
    "can_change",
    "negative_constraints",
    "preserve",
    "preserve_directives",
    "repair_targets",
    "referenced_asset_ids",
    "referenced_asset_mentions",
    "required_text",
    "scene_constraints",
    "source_asset_ids",
    "source_node_ids",
    "text_literals",
}
CANVAS_PROMPT_NUMERIC_FIELDS = {"frame_index", "influence_strength", "n", "output_compression", "repair_iteration", "score", "total_score", "weight"}
CANVAS_PAYLOAD_ALLOWED_FIELDS = {
    *CANVAS_PROMPT_TEXT_FIELDS,
    *CANVAS_PROMPT_TEXT_LIST_FIELDS,
    *CANVAS_PROMPT_NUMERIC_FIELDS,
    *CANVAS_GENERATE_IMAGE_PARAMS,
    "action_type",
    "batch_id",
    "branch_audit_trail",
    "candidate_id",
    "edit_prompt",
    "final_prompt",
    "image_url",
    "is_primary_path",
    "reason",
    "source",
    "source_asset_id",
    "source_canvas_id",
    "task_id",
    "video_url",
}


class CanvasCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

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
            raise ValueError("Canvas name is required")
        return value


class CanvasPosition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    x: float
    y: float


class CanvasSize(BaseModel):
    model_config = ConfigDict(extra="forbid")

    width: float = Field(default=320, gt=0)
    height: float = Field(default=180, gt=0)


class CanvasNodeCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: str = Field(min_length=1, max_length=80)
    title: str = Field(min_length=1, max_length=160)
    position: CanvasPosition
    size: CanvasSize = Field(default_factory=CanvasSize)
    payload: dict[str, Any] = Field(default_factory=dict)

    @field_validator("type", "title")
    @classmethod
    def strip_required_text(cls, value: str) -> str:
        return value.strip()

    @field_validator("type")
    @classmethod
    def validate_type(cls, value: str) -> str:
        if not value:
            raise ValueError("Node type is required")
        return value

    @field_validator("title")
    @classmethod
    def validate_title(cls, value: str) -> str:
        if not value:
            raise ValueError("Node title is required")
        return value

    @field_validator("payload")
    @classmethod
    def validate_payload(cls, value: dict[str, Any]) -> dict[str, Any]:
        _validate_canvas_payload(value)
        return value


class CanvasNodeUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, min_length=1, max_length=160)
    position: CanvasPosition | None = None
    size: CanvasSize | None = None
    payload: dict[str, Any] | None = None

    @field_validator("title")
    @classmethod
    def validate_title(cls, value: str | None) -> str | None:
        if value is None:
            return value
        stripped = value.strip()
        if not stripped:
            raise ValueError("Node title is required")
        return stripped

    @field_validator("payload")
    @classmethod
    def validate_payload(cls, value: dict[str, Any] | None) -> dict[str, Any] | None:
        if value is not None:
            _validate_canvas_payload(value)
        return value


class CanvasNodePositionUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    position: CanvasPosition


class CanvasNodePositionsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    positions: list[CanvasNodePositionUpdate] = Field(min_length=1, max_length=200)

    @field_validator("positions")
    @classmethod
    def validate_unique_node_ids(cls, value: list[CanvasNodePositionUpdate]) -> list[CanvasNodePositionUpdate]:
        node_ids = [item.id for item in value]
        if len(node_ids) != len(set(node_ids)):
            raise ValueError("Node position updates must be unique")
        return value


class CanvasEdgeCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_node_id: str = Field(min_length=1)
    target_node_id: str = Field(min_length=1)
    type: str = Field(default="lineage", min_length=1, max_length=80)
    payload: dict[str, Any] = Field(default_factory=dict)

    @field_validator("type")
    @classmethod
    def validate_type(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("Edge type is required")
        return stripped

    @field_validator("payload")
    @classmethod
    def validate_payload(cls, value: dict[str, Any]) -> dict[str, Any]:
        _validate_canvas_payload(value)
        return value


class CanvasCompileRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    selected_node_ids: list[str] = Field(min_length=1, max_length=80)
    artifact_node_id: str | None = Field(default=None, min_length=1)
    root_node_id: str | None = Field(default=None, min_length=1)
    profile: str | None = Field(default=None, min_length=1, max_length=80)

    @field_validator("selected_node_ids")
    @classmethod
    def validate_unique_selected_node_ids(cls, value: list[str]) -> list[str]:
        normalized = [item.strip() for item in value]
        if any(not item for item in normalized):
            raise ValueError("Selected node ids cannot be blank")
        if len(normalized) != len(set(normalized)):
            raise ValueError("Selected node ids must be unique")
        return normalized

    @field_validator("artifact_node_id", "root_node_id", "profile")
    @classmethod
    def strip_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return value
        stripped = value.strip()
        if not stripped:
            raise ValueError("Value cannot be blank")
        return stripped


class CanvasCaseIndexRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_id: str = Field(min_length=1)
    title: str = Field(min_length=1, max_length=160)
    quality_score: float = Field(ge=0.0, le=1.0)

    @field_validator("artifact_id", "title")
    @classmethod
    def strip_case_index_text(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("Value cannot be blank")
        return stripped


class CanvasDirectorRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    selected_node_ids: list[str] = Field(min_length=1, max_length=80)

    @field_validator("selected_node_ids")
    @classmethod
    def validate_unique_director_node_ids(cls, value: list[str]) -> list[str]:
        return _validate_unique_node_ids(value)


class CanvasGenerateImageRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    selected_node_ids: list[str] = Field(min_length=1, max_length=80)
    root_node_id: str | None = Field(default=None, min_length=1)
    prompt_artifact_id: str | None = Field(default=None, min_length=1)
    model: str = Field(min_length=1, max_length=80)
    threshold: float | None = Field(default=None, ge=0.0, le=10.0)
    max_iter: int | None = Field(default=None, ge=1, le=10)
    params: dict[str, Any] = Field(default_factory=dict)
    skip_prompt_evaluation: bool = True

    @field_validator("selected_node_ids")
    @classmethod
    def validate_unique_generate_node_ids(cls, value: list[str]) -> list[str]:
        return _validate_unique_node_ids(value)

    @field_validator("model")
    @classmethod
    def strip_model(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("Model is required")
        return stripped

    @field_validator("root_node_id", "prompt_artifact_id")
    @classmethod
    def strip_optional_root_node_id(cls, value: str | None) -> str | None:
        if value is None:
            return value
        stripped = value.strip()
        if not stripped:
            raise ValueError("Value cannot be blank")
        return stripped

    @field_validator("params")
    @classmethod
    def validate_params(cls, value: dict[str, Any]) -> dict[str, Any]:
        _validate_canvas_payload(value)
        _validate_canvas_generate_image_params(value)
        return value


class CanvasStoryboardImagePromptRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    node_id: str = Field(min_length=1)
    selected_node_ids: list[str] = Field(min_length=1, max_length=80)
    root_node_id: str | None = Field(default=None, min_length=1)
    params: dict[str, Any] = Field(default_factory=dict)
    skip_prompt_evaluation: bool = False

    @field_validator("node_id", "root_node_id")
    @classmethod
    def strip_optional_storyboard_ids(cls, value: str | None) -> str | None:
        if value is None:
            return value
        stripped = value.strip()
        if not stripped:
            raise ValueError("Value cannot be blank")
        return stripped

    @field_validator("selected_node_ids")
    @classmethod
    def validate_unique_storyboard_node_ids(cls, value: list[str]) -> list[str]:
        return _validate_unique_node_ids(value)

    @field_validator("params")
    @classmethod
    def validate_storyboard_prompt_params(cls, value: dict[str, Any]) -> dict[str, Any]:
        _validate_canvas_payload(value)
        _validate_canvas_generate_image_params(value)
        return value

    @model_validator(mode="after")
    def validate_storyboard_node_in_selection(self) -> "CanvasStoryboardImagePromptRequest":
        if self.node_id not in self.selected_node_ids:
            raise ValueError("node_id must be included in selected_node_ids")
        return self


class CanvasStoryboardVideoPromptRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    node_id: str = Field(min_length=1)
    selected_node_ids: list[str] = Field(min_length=1, max_length=80)
    root_node_id: str | None = Field(default=None, min_length=1)
    source_candidate_id: str | None = Field(default=None, min_length=1)
    source_image_asset_id: str | None = Field(default=None, min_length=1)
    duration: int | None = Field(default=None, ge=1, le=60)
    aspect_ratio: str | None = Field(default=None, max_length=32)
    params: dict[str, Any] = Field(default_factory=dict)

    @field_validator("node_id", "root_node_id", "source_candidate_id", "source_image_asset_id", "aspect_ratio")
    @classmethod
    def strip_optional_video_prompt_ids(cls, value: str | None) -> str | None:
        if value is None:
            return value
        stripped = value.strip()
        if not stripped:
            raise ValueError("Value cannot be blank")
        return stripped

    @field_validator("selected_node_ids")
    @classmethod
    def validate_unique_video_prompt_node_ids(cls, value: list[str]) -> list[str]:
        return _validate_unique_node_ids(value)

    @field_validator("params")
    @classmethod
    def validate_video_prompt_params(cls, value: dict[str, Any]) -> dict[str, Any]:
        _validate_canvas_payload(value)
        return value

    @model_validator(mode="after")
    def validate_video_prompt_selection(self) -> "CanvasStoryboardVideoPromptRequest":
        if self.node_id not in self.selected_node_ids:
            raise ValueError("node_id must be included in selected_node_ids")
        if self.source_candidate_id and self.source_image_asset_id:
            raise ValueError("Choose at most one source image")
        return self


class CanvasGenerateImageEditRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    prompt: str = Field(min_length=1, max_length=12000)
    source_node_ids: list[str] = Field(min_length=1, max_length=80)
    source_image_asset_ids: list[str] = Field(min_length=1, max_length=8)
    mask_asset_id: str | None = Field(default=None, min_length=1)
    action_type: ImageActionType = ImageActionType.EDIT
    model: str = Field(min_length=1, max_length=80)
    threshold: float | None = Field(default=None, ge=0.0, le=10.0)
    max_iter: int | None = Field(default=None, ge=1, le=10)
    params: dict[str, Any] = Field(default_factory=dict)
    skip_prompt_evaluation: bool = True

    @field_validator("prompt", "model")
    @classmethod
    def strip_required_text(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("Value cannot be blank")
        return stripped

    @field_validator("source_node_ids", "source_image_asset_ids")
    @classmethod
    def validate_unique_edit_ids(cls, value: list[str]) -> list[str]:
        return _validate_unique_node_ids(value)

    @field_validator("params")
    @classmethod
    def validate_edit_params(cls, value: dict[str, Any]) -> dict[str, Any]:
        _validate_canvas_payload(value)
        _validate_canvas_generate_image_params(value)
        return value

    @model_validator(mode="after")
    def validate_edit_action(self) -> "CanvasGenerateImageEditRequest":
        if self.action_type == ImageActionType.TEXT_TO_IMAGE:
            raise ValueError("image-edit tasks require an image-based action_type")
        if self.action_type == ImageActionType.INPAINT and self.mask_asset_id is None:
            raise ValueError("mask_asset_id is required for inpaint action_type")
        if self.action_type != ImageActionType.INPAINT and self.mask_asset_id is not None:
            raise ValueError("mask_asset_id is only supported for inpaint action_type")
        if self.mask_asset_id and self.mask_asset_id in self.source_image_asset_ids:
            raise ValueError("mask_asset_id must be distinct from source_image_asset_ids")
        return self


class CanvasRepairVersionMaterializeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    batch_id: str = Field(min_length=1)
    position: CanvasPosition
    size: CanvasSize = Field(default_factory=CanvasSize)

    @field_validator("batch_id")
    @classmethod
    def strip_batch_id(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("batch_id cannot be blank")
        return stripped


class CanvasRepairVersionStatusRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str = Field(pattern="^(active|archived)$")
    include_descendants: bool = False
    reason: str = Field(default="", max_length=500)

    @field_validator("reason")
    @classmethod
    def strip_reason(cls, value: str) -> str:
        reason = value.strip()
        if not reason:
            raise ValueError("Governance reason is required")
        return reason


class CanvasRepairVersionPinRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(default="", max_length=500)

    @field_validator("reason")
    @classmethod
    def strip_reason(cls, value: str) -> str:
        reason = value.strip()
        if not reason:
            raise ValueError("Governance reason is required")
        return reason


class CanvasImageCandidateStatusRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str = Field(pattern="^(candidate|selected|rejected)$")
    reason: str = Field(default="", max_length=500)
    position: CanvasPosition | None = None

    @field_validator("reason")
    @classmethod
    def strip_reason(cls, value: str) -> str:
        reason = value.strip()
        if not reason:
            raise ValueError("Candidate governance reason is required")
        return reason


class CanvasGenerateVideoRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    prompt: str = Field(min_length=1, max_length=12000)
    prompt_artifact_id: str | None = Field(default=None, min_length=1)
    source_candidate_id: str | None = Field(default=None, min_length=1)
    source_image_asset_id: str | None = Field(default=None, min_length=1)
    selected_node_ids: list[str] = Field(default_factory=list, max_length=80)
    duration: int | None = Field(default=None, ge=1, le=60)
    aspect_ratio: str | None = Field(default=None, max_length=32)
    params: dict[str, Any] = Field(default_factory=dict)

    @field_validator("prompt")
    @classmethod
    def strip_video_prompt(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("Prompt is required")
        return stripped

    @field_validator("prompt_artifact_id", "source_candidate_id", "source_image_asset_id", "aspect_ratio")
    @classmethod
    def strip_optional_video_text(cls, value: str | None) -> str | None:
        if value is None:
            return value
        stripped = value.strip()
        if not stripped:
            raise ValueError("Value cannot be blank")
        return stripped

    @field_validator("selected_node_ids")
    @classmethod
    def validate_unique_video_node_ids(cls, value: list[str]) -> list[str]:
        return _validate_unique_node_ids(value) if value else []

    @field_validator("params")
    @classmethod
    def validate_video_params_payload(cls, value: dict[str, Any]) -> dict[str, Any]:
        _validate_canvas_payload(value)
        return value

    @model_validator(mode="after")
    def validate_video_source(self) -> "CanvasGenerateVideoRequest":
        if bool(self.source_candidate_id) == bool(self.source_image_asset_id):
            raise ValueError("Choose exactly one source image candidate or source image asset")
        return self


class CanvasFinalGenerationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = False
    model: str | None = Field(default=None, min_length=1, max_length=80)
    threshold: float | None = Field(default=None, ge=0.0, le=10.0)
    max_iter: int | None = Field(default=None, ge=1, le=10)
    params: dict[str, Any] = Field(default_factory=dict)
    skip_prompt_evaluation: bool = True

    @field_validator("model")
    @classmethod
    def strip_optional_model(cls, value: str | None) -> str | None:
        if value is None:
            return value
        stripped = value.strip()
        if not stripped:
            raise ValueError("Model is required")
        return stripped

    @field_validator("params")
    @classmethod
    def validate_final_generation_params(cls, value: dict[str, Any]) -> dict[str, Any]:
        _validate_canvas_payload(value)
        _validate_canvas_generate_image_params(value)
        return value

    @model_validator(mode="after")
    def validate_enabled_model(self) -> "CanvasFinalGenerationRequest":
        if self.enabled and not self.model:
            raise ValueError("Model is required when generation is enabled")
        return self


class CanvasMediaApprovalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    approved: bool = True
    reason: str = Field(default="", max_length=1000)

    @field_validator("reason")
    @classmethod
    def strip_reason(cls, value: str) -> str:
        return value.strip()


class CanvasFinalSubmitRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    selected_node_ids: list[str] = Field(min_length=1, max_length=80)
    artifact_node_id: str | None = Field(default=None, min_length=1)
    root_node_id: str | None = Field(default=None, min_length=1)
    profile: str | None = Field(default=None, min_length=1, max_length=80)
    generation: CanvasFinalGenerationRequest | None = None

    @field_validator("selected_node_ids")
    @classmethod
    def validate_unique_final_node_ids(cls, value: list[str]) -> list[str]:
        return _validate_unique_node_ids(value)

    @field_validator("artifact_node_id", "root_node_id", "profile")
    @classmethod
    def strip_optional_final_text(cls, value: str | None) -> str | None:
        if value is None:
            return value
        stripped = value.strip()
        if not stripped:
            raise ValueError("Value cannot be blank")
        return stripped


class CanvasResponse(BaseModel):
    id: str
    project_id: str
    name: str
    description: str = ""
    created_at: datetime
    updated_at: datetime


class CanvasListResponse(BaseModel):
    canvases: list[CanvasResponse]


class CanvasNodeResponse(BaseModel):
    id: str
    canvas_id: str
    type: str
    title: str
    position: CanvasPosition
    size: CanvasSize
    payload: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime


class CanvasNodeListResponse(BaseModel):
    nodes: list[CanvasNodeResponse]


class CanvasEdgeResponse(BaseModel):
    id: str
    canvas_id: str
    source_node_id: str
    target_node_id: str
    type: str
    payload: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class BranchOperationResponse(BaseModel):
    id: str
    canvas_id: str
    operation: str
    reason: str = ""
    scope: str = "single"
    target_node_id: str | None = None
    affected_node_ids: list[str] = Field(default_factory=list)
    payload: dict[str, Any] = Field(default_factory=dict)
    actor_id: str = ""
    actor_display: str = ""
    created_at: datetime


class BranchOperationSummaryResponse(BaseModel):
    operation_counts: dict[str, int] = Field(default_factory=dict)
    scope_counts: dict[str, int] = Field(default_factory=dict)
    latest_materialize: BranchOperationResponse | None = None
    latest_pin: BranchOperationResponse | None = None
    latest_unpin: BranchOperationResponse | None = None
    latest_archive: BranchOperationResponse | None = None
    latest_restore: BranchOperationResponse | None = None
    latest_approve: BranchOperationResponse | None = None
    latest_revoke: BranchOperationResponse | None = None
    latest_select: BranchOperationResponse | None = None
    latest_reject: BranchOperationResponse | None = None
    latest_candidate: BranchOperationResponse | None = None


class BranchOperationListResponse(BaseModel):
    operations: list[BranchOperationResponse]
    total: int
    limit: int
    offset: int
    summary: BranchOperationSummaryResponse = Field(default_factory=BranchOperationSummaryResponse)
    summary_scope: str = "canvas"


class CanvasDetailResponse(CanvasResponse):
    nodes: list[CanvasNodeResponse] = Field(default_factory=list)
    edges: list[CanvasEdgeResponse] = Field(default_factory=list)
    branch_operations: list[BranchOperationResponse] = Field(default_factory=list)


class PromptArtifactResponse(BaseModel):
    id: str
    canvas_id: str
    node_id: str | None = None
    kind: str
    payload: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class PromptArtifactListResponse(BaseModel):
    artifacts: list[PromptArtifactResponse]


class CanvasStoryboardImagePromptResponse(BaseModel):
    final_prompt: str
    prompt_report: dict[str, Any]
    prompt_skill: dict[str, Any]
    optimization_trace: dict[str, Any]
    artifact: PromptArtifactResponse


class CanvasStoryboardVideoPromptResponse(BaseModel):
    final_prompt: str
    video_report: dict[str, Any]
    source_context: dict[str, Any]
    artifact: PromptArtifactResponse


class CanvasImageCandidateResponse(BaseModel):
    id: str
    batch_id: str
    canvas_id: str
    asset_id: str
    task_id: str | None = None
    node_id: str | None = None
    index: int
    prompt: str
    score: float | None = None
    status: str
    repair_protected: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime


class CanvasImageBatchResponse(BaseModel):
    id: str
    canvas_id: str
    project_id: str
    source_node_ids: list[str] = Field(default_factory=list)
    prompt_artifact_id: str | None = None
    task_id: str | None = None
    status: str
    prompt: str
    params: dict[str, Any] = Field(default_factory=dict)
    repair_context: dict[str, Any] = Field(default_factory=dict)
    candidates: list[CanvasImageCandidateResponse] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class CanvasImageBatchListResponse(BaseModel):
    batches: list[CanvasImageBatchResponse]


class CanvasCompileResponse(BaseModel):
    creative_graph: dict[str, Any]
    prompt_spec: dict[str, Any]
    final_prompt: str
    artifact: PromptArtifactResponse


class CanvasCaseIndexResponse(BaseModel):
    case: dict[str, Any]


class CanvasDirectorResponse(BaseModel):
    canvas_summary: dict[str, Any]
    matched_cases: list[dict[str, Any]] = Field(default_factory=list)
    suggestions: list[dict[str, Any]] = Field(default_factory=list)


class CanvasGenerateResponse(BaseModel):
    task_id: str
    status: str


class CanvasFinalTaskResponse(BaseModel):
    task_id: str
    status: str


class CanvasFinalSubmitResponse(BaseModel):
    canvas_id: str
    project_id: str
    selected_node_ids: list[str]
    creative_graph: dict[str, Any]
    prompt_spec: dict[str, Any]
    final_prompt: str
    asset_references: list[dict[str, Any]] = Field(default_factory=list)
    generation_params: dict[str, Any] = Field(default_factory=dict)
    production_lineage: dict[str, Any] = Field(default_factory=dict)
    artifact: PromptArtifactResponse
    task: CanvasFinalTaskResponse | None = None


class CanvasSeriesPlanRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    selected_node_ids: list[str] = Field(min_length=1, max_length=80)
    frame_count: int = Field(default=4, ge=3, le=8)
    profile: str | None = Field(default=None, min_length=1, max_length=80)

    @field_validator("selected_node_ids")
    @classmethod
    def validate_unique_series_node_ids(cls, value: list[str]) -> list[str]:
        return _validate_unique_node_ids(value)

    @field_validator("profile")
    @classmethod
    def strip_optional_profile(cls, value: str | None) -> str | None:
        if value is None:
            return value
        stripped = value.strip()
        if not stripped:
            raise ValueError("Value cannot be blank")
        return stripped


class CanvasSeriesFrameResponse(BaseModel):
    index: int
    title: str
    beat: str
    camera: str
    prompt: str
    continuity: list[str] = Field(default_factory=list)
    source_node_ids: list[str] = Field(default_factory=list)


class CanvasSeriesPlanResponse(BaseModel):
    canvas_id: str
    project_id: str
    primary_brief: str
    character_lock: list[str] = Field(default_factory=list)
    style_lock: dict[str, str] = Field(default_factory=dict)
    reference_policy: list[str] = Field(default_factory=list)
    text_literals: list[str] = Field(default_factory=list)
    frames: list[CanvasSeriesFrameResponse] = Field(default_factory=list)


def _validate_unique_node_ids(value: list[str]) -> list[str]:
    normalized = [item.strip() for item in value]
    if any(not item for item in normalized):
        raise ValueError("Selected node ids cannot be blank")
    if len(normalized) != len(set(normalized)):
        raise ValueError("Selected node ids must be unique")
    return normalized


def _validate_canvas_generate_image_params(value: dict[str, Any]) -> None:
    allowed_keys = {*CANVAS_GENERATE_IMAGE_PARAMS, "n", "output_compression"}
    for key, item in value.items():
        if key not in allowed_keys:
            raise ValueError(f"Unsupported canvas image parameter: {key}")
        if key in CANVAS_GENERATE_IMAGE_PARAMS and item not in CANVAS_GENERATE_IMAGE_PARAMS[key]:
            raise ValueError(f"Invalid canvas image parameter: {key}")
        if key == "n" and (type(item) is not int or item < 1 or item > MAX_CANVAS_GENERATE_IMAGE_COUNT):
            raise ValueError(f"Canvas image count must be between 1 and {MAX_CANVAS_GENERATE_IMAGE_COUNT}")
        if key == "output_compression" and (type(item) is not int or item < 0 or item > 100):
            raise ValueError("Canvas image output_compression must be between 0 and 100")


def _validate_canvas_payload(value: dict[str, Any]) -> None:
    _validate_canvas_payload_fields(value)
    if _payload_depth(value) > MAX_CANVAS_PAYLOAD_DEPTH:
        raise ValueError("Canvas payload is too deeply nested")
    encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    if len(encoded.encode("utf-8")) > MAX_CANVAS_PAYLOAD_BYTES:
        raise ValueError("Canvas payload exceeds the size limit")


def _validate_canvas_payload_fields(value: Any) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if key not in CANVAS_PAYLOAD_ALLOWED_FIELDS:
                raise ValueError(f"Unsupported canvas payload field: {key}")
            if key == "mention_label" and (not isinstance(item, str) or not MENTION_LABEL_RE.fullmatch(item)):
                raise ValueError("Canvas mention_label must use 1-32 lowercase letters, numbers, hyphens, or Chinese characters")
            if key == "asset_kind" and (not isinstance(item, str) or item not in {"image", "video"}):
                raise ValueError("Canvas asset_kind must be image or video")
            if key == "branch_audit_trail":
                _validate_branch_audit_trail(item)
                continue
            if key in CANVAS_PROMPT_TEXT_FIELDS and not isinstance(item, str):
                raise ValueError(f"Canvas payload field {key} must be a string")
            if key in CANVAS_GENERATE_IMAGE_PARAMS and not isinstance(item, str):
                raise ValueError(f"Canvas payload field {key} must be a string")
            if key in CANVAS_PROMPT_NUMERIC_FIELDS and item is not None and (not isinstance(item, int | float) or isinstance(item, bool)):
                raise ValueError(f"Canvas payload field {key} must be numeric")
            if key in CANVAS_PROMPT_TEXT_LIST_FIELDS:
                _validate_prompt_text_or_list(key, item)
            _validate_canvas_payload_fields(item)
        return
    if isinstance(value, list):
        for item in value:
            _validate_canvas_payload_fields(item)



def _validate_branch_audit_trail(value: Any) -> None:
    if not isinstance(value, list):
        raise ValueError("Canvas branch_audit_trail must be a list")
    for item in value:
        if not isinstance(item, dict):
            raise ValueError("Canvas branch_audit_trail entries must be objects")
        required_keys = {"operation", "from_status", "to_status", "at"}
        allowed_keys = {*required_keys, "reason"}
        if not required_keys.issubset(item) or set(item) - allowed_keys:
            raise ValueError("Canvas branch_audit_trail entries must contain operation, from_status, to_status, and at")
        if item.get("operation") not in {"archive", "restore", "pin", "unpin"}:
            raise ValueError("Canvas branch_audit_trail operation must be archive, restore, pin, or unpin")
        if item.get("from_status") not in {"active", "archived", "unmaterialized"} or item.get("to_status") not in {"active", "archived"}:
            raise ValueError("Canvas branch_audit_trail statuses are invalid")
        if not isinstance(item.get("at"), str) or not item.get("at"):
            raise ValueError("Canvas branch_audit_trail at must be a string")
        if "reason" in item and (not isinstance(item.get("reason"), str) or len(item.get("reason") or "") > 500):
            raise ValueError("Canvas branch_audit_trail reason must be a string up to 500 characters")


def _validate_prompt_text_or_list(key: str, value: Any) -> None:
    if isinstance(value, str):
        return
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        return
    raise ValueError(f"Canvas payload field {key} must be a string or list of strings")



def _payload_depth(value: Any, depth: int = 0) -> int:
    if isinstance(value, dict):
        if not value:
            return depth + 1
        return max(_payload_depth(item, depth + 1) for item in value.values())
    if isinstance(value, list):
        if not value:
            return depth + 1
        return max(_payload_depth(item, depth + 1) for item in value)
    return depth
