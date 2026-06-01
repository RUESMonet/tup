import asyncio
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Response, status

from src.agents.canvas_case_memory import CanvasCaseMemoryIndexer, CanvasCreativeDirector, IndexedCanvasCase, case_search_text
from src.agents.canvas_graph_compiler import CanvasCompileProduct, CanvasGraphCompiler
from src.agents.canvas_series_planner import CanvasSeriesPlanner
from src.agents.canvas_video_prompt_optimizer import build_storyboard_video_prompt
from src.api.generation_routes import _billing_error, _persist_generated_image_url, _provider_image_source, _stop_task_heartbeat, _task_heartbeat
from src.api.image_routes import require_high_cost_access
from src.config import Settings, get_settings
from src.dependencies import get_billing_service, get_canvas_repository, get_project_repository, get_prompt_skill_pipeline, get_video_router, require_current_user
from src.models.auth import AuthUser
from src.models.canvas import (
    BranchOperationListResponse,
    BranchOperationResponse,
    CanvasCaseIndexRequest,
    CanvasCaseIndexResponse,
    CanvasCompileRequest,
    CanvasCompileResponse,
    CanvasCreateRequest,
    CanvasDetailResponse,
    CanvasDirectorRequest,
    CanvasDirectorResponse,
    CanvasEdgeCreateRequest,
    CanvasEdgeResponse,
    CanvasFinalSubmitRequest,
    CanvasFinalSubmitResponse,
    CanvasFinalTaskResponse,
    CanvasGenerateImageEditRequest,
    CanvasGenerateImageRequest,
    CanvasGenerateResponse,
    CanvasGenerateVideoRequest,
    CanvasImageBatchListResponse,
    CanvasImageBatchResponse,
    CanvasImageCandidateResponse,
    CanvasImageCandidateStatusRequest,
    CanvasListResponse,
    CanvasMediaApprovalRequest,
    CanvasSeriesPlanRequest,
    CanvasSeriesPlanResponse,
    CanvasNodeCreateRequest,
    CanvasNodeListResponse,
    CanvasNodePositionsRequest,
    CanvasNodeResponse,
    CanvasNodeUpdateRequest,
    CanvasRepairVersionMaterializeRequest,
    CanvasRepairVersionPinRequest,
    CanvasRepairVersionStatusRequest,
    CanvasResponse,
    CanvasStoryboardImagePromptRequest,
    CanvasStoryboardImagePromptResponse,
    CanvasStoryboardVideoPromptRequest,
    CanvasStoryboardVideoPromptResponse,
    PromptArtifactListResponse,
    PromptArtifactResponse,
)
from src.models.project import AssetKind, TaskKind
from src.models.prompt_report import PromptReport
from src.models.prompt_skill import ImageActionType, ImageSource, PromptSkillRequest
from src.models.task import TaskStatus
from src.models.video import VideoGenerateRequest
from src.services.billing_service import BillingService
from src.services.canvas_repository import CanvasRepository
from src.services.project_repository import ProjectRepository
from src.services.prompt_skill_pipeline import PromptSkillPipeline
from src.services.video_router import VideoRouter, validate_video_params


router = APIRouter(tags=["canvas"])
logger = logging.getLogger(__name__)
CANVAS_IMAGE_FAILURE_MESSAGE = "画布图片生成失败，请稍后重试或检查模型配置。"


@router.get("/api/projects/{project_id}/canvases", response_model=CanvasListResponse)
def list_canvases(
    project_id: str,
    user: AuthUser = Depends(require_current_user),
    repository: CanvasRepository = Depends(get_canvas_repository),
) -> CanvasListResponse:
    canvases = repository.list_canvases(user.id, project_id)
    if canvases is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return CanvasListResponse(canvases=canvases)


@router.post("/api/projects/{project_id}/canvases", response_model=CanvasResponse, status_code=status.HTTP_201_CREATED)
def create_canvas(
    project_id: str,
    request: CanvasCreateRequest,
    user: AuthUser = Depends(require_current_user),
    repository: CanvasRepository = Depends(get_canvas_repository),
) -> CanvasResponse:
    canvas = repository.create_canvas(user.id, project_id, request.name, request.description)
    if canvas is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return canvas


@router.get("/api/canvases/{canvas_id}", response_model=CanvasDetailResponse)
def get_canvas(
    canvas_id: str,
    user: AuthUser = Depends(require_current_user),
    repository: CanvasRepository = Depends(get_canvas_repository),
) -> CanvasDetailResponse:
    canvas = repository.get_canvas(user.id, canvas_id)
    if canvas is None:
        raise HTTPException(status_code=404, detail="Canvas not found")
    return canvas


@router.get("/api/canvases/{canvas_id}/prompt-artifacts", response_model=PromptArtifactListResponse)
def list_canvas_prompt_artifacts(
    canvas_id: str,
    node_id: str | None = Query(default=None, min_length=1),
    kind: str | None = Query(default=None, min_length=1, max_length=80),
    limit: int = Query(default=50, ge=1, le=100),
    user: AuthUser = Depends(require_current_user),
    repository: CanvasRepository = Depends(get_canvas_repository),
) -> PromptArtifactListResponse:
    artifacts = repository.list_prompt_artifacts(
        user.id,
        canvas_id,
        node_id.strip() if node_id else None,
        kind.strip() if kind else None,
        limit,
    )
    if artifacts is None:
        raise HTTPException(status_code=404, detail="Canvas not found")
    return PromptArtifactListResponse(artifacts=artifacts)


@router.get("/api/canvases/{canvas_id}/branch-operations", response_model=BranchOperationListResponse)
def list_branch_operations(
    canvas_id: str,
    operation: str | None = Query(default=None, pattern="^(materialize|archive|restore|pin|unpin|approve|revoke|select|reject|candidate)$"),
    scope: str | None = Query(default=None, pattern="^(single|subtree|path)$"),
    target_node_id: str | None = Query(default=None, min_length=1),
    limit: int = Query(default=40, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    user: AuthUser = Depends(require_current_user),
    repository: CanvasRepository = Depends(get_canvas_repository),
) -> BranchOperationListResponse:
    try:
        result = repository.list_branch_operations(
            user.id,
            canvas_id,
            operation.strip() if operation else None,
            scope.strip() if scope else None,
            target_node_id.strip() if target_node_id else None,
            limit,
            offset,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if result is None:
        raise HTTPException(status_code=404, detail="Canvas not found")
    operations, total, summary = result
    return BranchOperationListResponse(operations=operations, total=total, limit=limit, offset=offset, summary=summary)


@router.post("/api/canvases/{canvas_id}/nodes", response_model=CanvasNodeResponse, status_code=status.HTTP_201_CREATED)
def create_node(
    canvas_id: str,
    request: CanvasNodeCreateRequest,
    user: AuthUser = Depends(require_current_user),
    repository: CanvasRepository = Depends(get_canvas_repository),
) -> CanvasNodeResponse:
    if request.type in {"repair_version", "selected_image", "edited_image", "generated_image", "generated_video"}:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Production media and repair version nodes are server-managed")
    _reject_client_managed_payload_impersonation(request.type, request.payload)
    node = repository.create_node(
        user.id,
        canvas_id,
        request.type,
        request.title,
        request.position.model_dump(),
        request.size.model_dump(),
        request.payload,
    )
    if node is None:
        raise HTTPException(status_code=404, detail="Canvas not found")
    return node


@router.patch("/api/canvases/{canvas_id}/nodes/positions", response_model=CanvasNodeListResponse)
def update_node_positions(
    canvas_id: str,
    request: CanvasNodePositionsRequest,
    user: AuthUser = Depends(require_current_user),
    repository: CanvasRepository = Depends(get_canvas_repository),
) -> CanvasNodeListResponse:
    nodes = repository.update_node_positions(
        user.id,
        canvas_id,
        [{"id": item.id, "position": item.position.model_dump()} for item in request.positions],
    )
    if nodes is None:
        raise HTTPException(status_code=404, detail="Canvas or node not found")
    return CanvasNodeListResponse(nodes=nodes)


@router.post("/api/canvases/{canvas_id}/compile", response_model=CanvasCompileResponse, status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_high_cost_access)])
def compile_canvas(
    canvas_id: str,
    request: CanvasCompileRequest,
    user: AuthUser = Depends(require_current_user),
    repository: CanvasRepository = Depends(get_canvas_repository),
) -> CanvasCompileResponse:
    canvas = repository.get_canvas(user.id, canvas_id)
    if canvas is None:
        raise HTTPException(status_code=404, detail="Canvas not found")
    canvas_node_ids = {node.id for node in canvas.nodes}
    if not set(request.selected_node_ids).issubset(canvas_node_ids):
        raise HTTPException(status_code=404, detail="Selected node not found")
    if request.artifact_node_id is not None and request.artifact_node_id not in set(request.selected_node_ids):
        raise HTTPException(status_code=404, detail="Artifact node not found")
    if request.root_node_id is not None and request.root_node_id not in set(request.selected_node_ids):
        raise HTTPException(status_code=404, detail="Root node not found")
    _reject_archived_repair_version_selection(canvas, request.selected_node_ids)
    compiled = _compile_canvas_or_422(canvas, request.selected_node_ids, request.profile, request.root_node_id)
    try:
        artifact = repository.create_prompt_artifact(user.id, canvas_id, request.artifact_node_id, "canvas_prompt_compile", compiled.artifact_payload(request.selected_node_ids))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if artifact is None:
        raise HTTPException(status_code=404, detail="Canvas or artifact node not found")
    return CanvasCompileResponse(creative_graph=compiled.creative_graph.model_dump(), prompt_spec=compiled.prompt_spec, final_prompt=compiled.final_prompt, artifact=artifact)


@router.post(
    "/api/canvases/{canvas_id}/storyboard/image-prompt",
    response_model=CanvasStoryboardImagePromptResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_high_cost_access)],
)
async def optimize_storyboard_image_prompt(
    canvas_id: str,
    request: CanvasStoryboardImagePromptRequest,
    user: AuthUser = Depends(require_current_user),
    canvas_repository: CanvasRepository = Depends(get_canvas_repository),
    project_repository: ProjectRepository = Depends(get_project_repository),
    pipeline: PromptSkillPipeline = Depends(get_prompt_skill_pipeline),
    settings: Settings = Depends(get_settings),
) -> CanvasStoryboardImagePromptResponse:
    canvas = await asyncio.to_thread(canvas_repository.get_canvas, user.id, canvas_id)
    if canvas is None:
        raise HTTPException(status_code=404, detail="Canvas not found")
    canvas_node_ids = {node.id for node in canvas.nodes}
    if request.node_id not in canvas_node_ids or not set(request.selected_node_ids).issubset(canvas_node_ids):
        raise HTTPException(status_code=404, detail="Selected node not found")
    if request.node_id not in set(request.selected_node_ids):
        raise HTTPException(status_code=422, detail="node_id must be included in selected_node_ids")
    if request.root_node_id is not None and request.root_node_id not in set(request.selected_node_ids):
        raise HTTPException(status_code=404, detail="Root node not found")
    _reject_archived_repair_version_selection(canvas, request.selected_node_ids)

    compiled = await asyncio.to_thread(_compile_canvas_or_422, canvas, request.selected_node_ids, None, request.root_node_id)
    prompt_request = await asyncio.to_thread(_canvas_prompt_skill_request, user.id, canvas.project_id, compiled, request.params, project_repository, settings)
    prompt_skill = await pipeline.prompt_skill_agent.optimize(prompt_request)
    prompt_report = (
        PromptReport(score=10.0, passed=True, missing=[], suggestion="")
        if request.skip_prompt_evaluation
        else await pipeline.prompt_evaluator.evaluate(prompt_request.prompt)
    )
    optimization_trace = PromptSkillPipeline._trace(prompt_request.prompt, prompt_skill, prompt_report)
    prompt_skill_payload = prompt_skill.model_dump(mode="json")
    prompt_report_payload = prompt_report.model_dump(mode="json")
    trace_payload = optimization_trace.model_dump(mode="json")
    artifact_payload = {
        "workflow": "storyboard_image_prompt_optimization",
        "node_id": request.node_id,
        "selected_node_ids": request.selected_node_ids,
        "root_node_id": request.root_node_id,
        "params": request.params,
        "creative_graph": compiled.creative_graph.model_dump(mode="json"),
        "prompt_spec": compiled.prompt_spec,
        "compiled_prompt": compiled.final_prompt,
        "final_prompt": prompt_skill.final_english_prompt,
        "prompt_report": prompt_report_payload,
        "prompt_skill": {
            "task": prompt_skill_payload.get("task"),
            "intent": prompt_skill_payload.get("intent"),
            "final_english_prompt": prompt_skill_payload.get("final_english_prompt"),
            "suggested_params": prompt_skill_payload.get("suggested_params"),
            "quality_gates": prompt_skill_payload.get("quality_gates"),
            "warnings": prompt_skill_payload.get("warnings"),
        },
        "optimization_trace": {
            "original_prompt": trace_payload.get("original_prompt"),
            "profile": trace_payload.get("profile"),
            "quality_source": trace_payload.get("quality_source"),
            "stages": [
                {
                    "stage": stage.get("stage"),
                    "title": stage.get("title"),
                    "summary": stage.get("summary"),
                    "score": stage.get("score"),
                    "passed": stage.get("passed"),
                    "missing": stage.get("missing"),
                    "suggestion": stage.get("suggestion"),
                    "source": stage.get("source"),
                    "profile": stage.get("profile"),
                }
                for stage in trace_payload.get("stages", [])
            ],
        },
    }
    try:
        artifact = await asyncio.to_thread(
            canvas_repository.create_prompt_artifact,
            user.id,
            canvas_id,
            request.node_id,
            "storyboard_image_prompt_version",
            artifact_payload,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if artifact is None:
        raise HTTPException(status_code=404, detail="Canvas or node not found")
    return CanvasStoryboardImagePromptResponse(
        final_prompt=prompt_skill.final_english_prompt,
        prompt_report=prompt_report_payload,
        prompt_skill=prompt_skill_payload,
        optimization_trace=trace_payload,
        artifact=artifact,
    )


@router.post(
    "/api/canvases/{canvas_id}/storyboard/video-prompt",
    response_model=CanvasStoryboardVideoPromptResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_high_cost_access)],
)
async def optimize_storyboard_video_prompt(
    canvas_id: str,
    request: CanvasStoryboardVideoPromptRequest,
    user: AuthUser = Depends(require_current_user),
    canvas_repository: CanvasRepository = Depends(get_canvas_repository),
    project_repository: ProjectRepository = Depends(get_project_repository),
) -> CanvasStoryboardVideoPromptResponse:
    canvas = await asyncio.to_thread(canvas_repository.get_canvas, user.id, canvas_id)
    if canvas is None:
        raise HTTPException(status_code=404, detail="Canvas not found")
    canvas_node_ids = {node.id for node in canvas.nodes}
    if request.node_id not in canvas_node_ids or not set(request.selected_node_ids).issubset(canvas_node_ids):
        raise HTTPException(status_code=404, detail="Selected node not found")
    if request.root_node_id is not None and request.root_node_id not in set(request.selected_node_ids):
        raise HTTPException(status_code=404, detail="Root node not found")
    _reject_archived_repair_version_selection(canvas, request.selected_node_ids)
    prompt_node_id = request.root_node_id or request.node_id
    node = next(item for item in canvas.nodes if item.id == prompt_node_id)
    source_context = await asyncio.to_thread(
        _canvas_video_prompt_source_context,
        user.id,
        canvas_id,
        canvas.project_id,
        request,
        canvas_repository,
        project_repository,
    )
    asset_id = source_context.get("asset_id")
    if isinstance(asset_id, str):
        _reject_unbound_or_archived_asset_inputs(canvas, request.selected_node_ids, [asset_id])
    compiled = await asyncio.to_thread(_compile_canvas_or_422, canvas, request.selected_node_ids, None, request.root_node_id)
    draft = build_storyboard_video_prompt(node, compiled, source_context, request.duration, request.aspect_ratio)
    payload = {
        "workflow": "storyboard_video_prompt_optimization",
        "node_id": request.node_id,
        "selected_node_ids": request.selected_node_ids,
        "root_node_id": request.root_node_id,
        "source_candidate_id": request.source_candidate_id,
        "source_image_asset_id": request.source_image_asset_id,
        "duration": request.duration,
        "aspect_ratio": request.aspect_ratio,
        "compiled_prompt": compiled.final_prompt,
        "final_prompt": draft.final_prompt,
        "video_report": draft.video_report,
        "source_context": draft.source_context,
    }
    try:
        artifact = await asyncio.to_thread(
            canvas_repository.create_prompt_artifact,
            user.id,
            canvas_id,
            request.node_id,
            "storyboard_video_prompt_version",
            payload,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if artifact is None:
        raise HTTPException(status_code=404, detail="Canvas or node not found")
    return CanvasStoryboardVideoPromptResponse(
        final_prompt=draft.final_prompt,
        video_report=draft.video_report,
        source_context=draft.source_context,
        artifact=artifact,
    )


@router.post("/api/canvases/{canvas_id}/generate/image", response_model=CanvasGenerateResponse, status_code=status.HTTP_202_ACCEPTED, dependencies=[Depends(require_high_cost_access)])
async def generate_canvas_image(
    canvas_id: str,
    request: CanvasGenerateImageRequest,
    background_tasks: BackgroundTasks,
    user: AuthUser = Depends(require_current_user),
    canvas_repository: CanvasRepository = Depends(get_canvas_repository),
    project_repository: ProjectRepository = Depends(get_project_repository),
    pipeline: PromptSkillPipeline = Depends(get_prompt_skill_pipeline),
    billing: BillingService = Depends(get_billing_service),
    settings: Settings = Depends(get_settings),
) -> CanvasGenerateResponse:
    canvas = await asyncio.to_thread(canvas_repository.get_canvas, user.id, canvas_id)
    if canvas is None:
        raise HTTPException(status_code=404, detail="Canvas not found")
    canvas_node_ids = {node.id for node in canvas.nodes}
    if not set(request.selected_node_ids).issubset(canvas_node_ids):
        raise HTTPException(status_code=404, detail="Selected node not found")
    if request.root_node_id is not None and request.root_node_id not in set(request.selected_node_ids):
        raise HTTPException(status_code=404, detail="Root node not found")
    _reject_archived_repair_version_selection(canvas, request.selected_node_ids)
    artifact = None
    if request.prompt_artifact_id is not None:
        artifact = await asyncio.to_thread(canvas_repository.get_prompt_artifact, user.id, canvas_id, request.prompt_artifact_id)
        if artifact is None:
            raise HTTPException(status_code=404, detail="Prompt artifact not found")
    compiled = await asyncio.to_thread(_compile_canvas_or_422, canvas, request.selected_node_ids, None, request.root_node_id)
    effective_prompt = _prompt_artifact_final_prompt(artifact) or compiled.final_prompt
    prompt_request = await asyncio.to_thread(_canvas_prompt_skill_request, user.id, canvas.project_id, compiled, request.params, project_repository, settings, effective_prompt)
    try:
        charge = await asyncio.to_thread(billing.charge_for_action, user.id, canvas.project_id, "canvas_image", {"workflow": "canvas_image_generation", "canvas_id": canvas_id})
    except ValueError as exc:
        raise _billing_error(exc) from exc
    task_input = {
        "selected_node_ids": request.selected_node_ids,
        "root_node_id": request.root_node_id,
        "model": request.model,
        "prompt_artifact_id": request.prompt_artifact_id,
        "threshold": request.threshold,
        "max_iter": request.max_iter,
        "params": request.params,
        "skip_prompt_evaluation": request.skip_prompt_evaluation,
        "canvas_id": canvas_id,
        "credit_transaction_id": charge.id,
        "estimated_credit_cost": charge.amount,
    }
    try:
        task = await asyncio.to_thread(project_repository.create_task, user.id, canvas.project_id, TaskKind.image, task_input, charge.amount, charge.amount)
        await asyncio.to_thread(billing.repository.attach_task, user.id, charge.id, task.task_id)
    except Exception:
        await asyncio.to_thread(billing.refund_failed_task, user.id, charge.id, None, "task creation failed")
        raise
    background_tasks.add_task(_run_canvas_image_task, user.id, task.task_id, canvas_id, request, compiled, prompt_request, charge.id, canvas_repository, project_repository, pipeline, billing, settings)
    return CanvasGenerateResponse(task_id=task.task_id, status=task.status)


@router.post("/api/canvases/{canvas_id}/generate/image-edit", response_model=CanvasGenerateResponse, status_code=status.HTTP_202_ACCEPTED, dependencies=[Depends(require_high_cost_access)])
async def generate_canvas_image_edit(
    canvas_id: str,
    request: CanvasGenerateImageEditRequest,
    background_tasks: BackgroundTasks,
    user: AuthUser = Depends(require_current_user),
    canvas_repository: CanvasRepository = Depends(get_canvas_repository),
    project_repository: ProjectRepository = Depends(get_project_repository),
    pipeline: PromptSkillPipeline = Depends(get_prompt_skill_pipeline),
    billing: BillingService = Depends(get_billing_service),
    settings: Settings = Depends(get_settings),
) -> CanvasGenerateResponse:
    canvas = await asyncio.to_thread(canvas_repository.get_canvas, user.id, canvas_id)
    if canvas is None:
        raise HTTPException(status_code=404, detail="Canvas not found")
    canvas_node_ids = {node.id for node in canvas.nodes}
    if not set(request.source_node_ids).issubset(canvas_node_ids):
        raise HTTPException(status_code=404, detail="Source node not found")
    canonical_asset_ids = _ordered_node_bound_image_asset_ids(canvas, request.source_node_ids)
    canonical_source_asset_ids = [asset_id for asset_id in canonical_asset_ids if asset_id != request.mask_asset_id]
    if request.mask_asset_id and request.mask_asset_id not in canonical_asset_ids:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Mask asset must be bound to the selected source nodes")
    if set(request.source_image_asset_ids) != set(canonical_source_asset_ids):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Source image assets must match the selected source nodes")
    request = request.model_copy(update={"source_image_asset_ids": canonical_source_asset_ids})
    asset_inputs = [*request.source_image_asset_ids, *([request.mask_asset_id] if request.mask_asset_id else [])]
    _reject_unbound_or_archived_asset_inputs(canvas, request.source_node_ids, asset_inputs)
    prompt_request = await asyncio.to_thread(_canvas_image_edit_prompt_request, user.id, canvas.project_id, request, project_repository, settings)
    try:
        charge = await asyncio.to_thread(billing.charge_for_action, user.id, canvas.project_id, "canvas_image_edit", {"workflow": "canvas_image_edit_generation", "canvas_id": canvas_id})
    except ValueError as exc:
        raise _billing_error(exc) from exc
    task_input = {
        **request.model_dump(mode="json"),
        "canvas_id": canvas_id,
        "workflow": "canvas_image_edit",
        "credit_transaction_id": charge.id,
        "estimated_credit_cost": charge.amount,
    }
    try:
        task = await asyncio.to_thread(project_repository.create_task, user.id, canvas.project_id, TaskKind.image_edit, task_input, charge.amount, charge.amount)
        await asyncio.to_thread(billing.repository.attach_task, user.id, charge.id, task.task_id)
    except Exception:
        await asyncio.to_thread(billing.refund_failed_task, user.id, charge.id, None, "task creation failed")
        raise
    background_tasks.add_task(_run_canvas_image_edit_task, user.id, task.task_id, canvas_id, request, prompt_request, _result_node_position(canvas, request.source_node_ids, {"x": 840.0, "y": 120.0}), charge.id, canvas_repository, project_repository, pipeline, billing, settings)
    return CanvasGenerateResponse(task_id=task.task_id, status=task.status)


@router.post("/api/canvases/{canvas_id}/image-batches", response_model=CanvasImageBatchResponse, status_code=status.HTTP_202_ACCEPTED, dependencies=[Depends(require_high_cost_access)])
async def create_canvas_image_batch(
    canvas_id: str,
    request: CanvasGenerateImageRequest,
    background_tasks: BackgroundTasks,
    user: AuthUser = Depends(require_current_user),
    canvas_repository: CanvasRepository = Depends(get_canvas_repository),
    project_repository: ProjectRepository = Depends(get_project_repository),
    pipeline: PromptSkillPipeline = Depends(get_prompt_skill_pipeline),
    billing: BillingService = Depends(get_billing_service),
    settings: Settings = Depends(get_settings),
) -> CanvasImageBatchResponse:
    canvas = await asyncio.to_thread(canvas_repository.get_canvas, user.id, canvas_id)
    if canvas is None:
        raise HTTPException(status_code=404, detail="Canvas not found")
    canvas_node_ids = {node.id for node in canvas.nodes}
    if not set(request.selected_node_ids).issubset(canvas_node_ids):
        raise HTTPException(status_code=404, detail="Selected node not found")
    if request.root_node_id is not None and request.root_node_id not in set(request.selected_node_ids):
        raise HTTPException(status_code=404, detail="Root node not found")
    _reject_archived_repair_version_selection(canvas, request.selected_node_ids)
    _validate_repair_batch_source(canvas, request.selected_node_ids)
    artifact = None
    if request.prompt_artifact_id is not None:
        artifact = await asyncio.to_thread(canvas_repository.get_prompt_artifact, user.id, canvas_id, request.prompt_artifact_id)
        if artifact is None:
            raise HTTPException(status_code=404, detail="Prompt artifact not found")
    compiled = await asyncio.to_thread(_compile_canvas_or_422, canvas, request.selected_node_ids, None, request.root_node_id)
    effective_prompt = _prompt_artifact_final_prompt(artifact) or compiled.final_prompt
    try:
        charge = await asyncio.to_thread(billing.charge_for_action, user.id, canvas.project_id, "canvas_image_batch", {"workflow": "canvas_image_batch_generation", "canvas_id": canvas_id})
    except ValueError as exc:
        raise _billing_error(exc) from exc
    task_input = {
        "selected_node_ids": request.selected_node_ids,
        "root_node_id": request.root_node_id,
        "model": request.model,
        "prompt_artifact_id": request.prompt_artifact_id,
        "threshold": request.threshold,
        "max_iter": request.max_iter,
        "params": request.params,
        "skip_prompt_evaluation": request.skip_prompt_evaluation,
        "canvas_id": canvas_id,
        "workflow": "text_to_image_batch",
        "credit_transaction_id": charge.id,
        "estimated_credit_cost": charge.amount,
    }
    try:
        task = await asyncio.to_thread(project_repository.create_task, user.id, canvas.project_id, TaskKind.image_batch, task_input, charge.amount, charge.amount)
        await asyncio.to_thread(billing.repository.attach_task, user.id, charge.id, task.task_id)
    except Exception:
        await asyncio.to_thread(billing.refund_failed_task, user.id, charge.id, None, "task creation failed")
        raise
    batch = await asyncio.to_thread(canvas_repository.create_image_batch, user.id, canvas_id, request.selected_node_ids, request.prompt_artifact_id, task.task_id, effective_prompt, request.params)
    if batch is None:
        await asyncio.to_thread(billing.refund_failed_task, user.id, charge.id, task.task_id, "task creation failed")
        await asyncio.to_thread(project_repository.set_task_failed, task.task_id, CANVAS_IMAGE_FAILURE_MESSAGE)
        raise HTTPException(status_code=404, detail="Canvas or selected node not found")
    background_tasks.add_task(_run_canvas_image_batch_task, user.id, task.task_id, batch.id, canvas_id, request, compiled, effective_prompt, charge.id, canvas_repository, project_repository, pipeline, billing, settings)
    batches = await asyncio.to_thread(canvas_repository.list_image_batches, user.id, canvas_id)
    return _image_batch_with_repair_context(batch, canvas, batches or [batch])


@router.post("/api/canvases/{canvas_id}/repair-versions/materialize", response_model=CanvasDetailResponse, status_code=status.HTTP_201_CREATED)
def materialize_repair_version(
    canvas_id: str,
    request: CanvasRepairVersionMaterializeRequest,
    user: AuthUser = Depends(require_current_user),
    repository: CanvasRepository = Depends(get_canvas_repository),
) -> CanvasDetailResponse:
    canvas = repository.get_canvas(user.id, canvas_id)
    if canvas is None:
        raise HTTPException(status_code=404, detail="Canvas not found")
    batches = repository.list_image_batches(user.id, canvas_id)
    if batches is None:
        raise HTTPException(status_code=404, detail="Canvas not found")
    annotated_batches = [_image_batch_with_repair_context(batch, canvas, batches) for batch in batches]
    batch = next((item for item in annotated_batches if item.id == request.batch_id), None)
    if batch is None:
        raise HTTPException(status_code=404, detail="Repair batch not found")
    context = batch.repair_context
    if not context.get("is_repair_version"):
        raise HTTPException(status_code=422, detail="Only repair image batches can be materialized as repair_version nodes")
    canvas_node_ids = {node.id for node in canvas.nodes}
    source_node_ids = [str(context.get(key) or "") for key in ("source_image_node_id", "evaluation_node_id", "repair_prompt_node_id")]
    source_node_ids = [node_id for node_id in source_node_ids if node_id]
    if not source_node_ids or not set(source_node_ids).issubset(canvas_node_ids):
        raise HTTPException(status_code=422, detail="Repair version source nodes are missing")
    existing_version = next((item for item in canvas.nodes if item.type == "repair_version" and item.payload.get("batch_id") == batch.id), None)
    node = repository.materialize_repair_version(
        user.id,
        canvas_id,
        batch.id,
        f"Repair V{_repair_context_iteration(context)} · {((context.get('repair_focus') or {}).get('label') or '整体修复')}",
        request.position.model_dump(),
        request.size.model_dump(),
        _repair_version_node_payload(batch, context),
        source_node_ids,
        str((context.get("repair_focus") or {}).get("parent_batch_id") or ""),
        "Server materialized repair version node" if existing_version is None else None,
    )
    if node is None:
        raise HTTPException(status_code=422, detail="Repair version could not be materialized")
    updated_canvas = repository.get_canvas(user.id, canvas_id)
    if updated_canvas is None:
        raise HTTPException(status_code=404, detail="Canvas not found")
    return updated_canvas


@router.get("/api/canvases/{canvas_id}/image-batches", response_model=CanvasImageBatchListResponse)
def list_canvas_image_batches(
    canvas_id: str,
    user: AuthUser = Depends(require_current_user),
    repository: CanvasRepository = Depends(get_canvas_repository),
) -> CanvasImageBatchListResponse:
    canvas = repository.get_canvas(user.id, canvas_id)
    if canvas is None:
        raise HTTPException(status_code=404, detail="Canvas not found")
    batches = repository.list_image_batches(user.id, canvas_id)
    if batches is None:
        raise HTTPException(status_code=404, detail="Canvas not found")
    return CanvasImageBatchListResponse(batches=[_image_batch_with_repair_context(batch, canvas, batches) for batch in batches])


@router.patch("/api/canvases/{canvas_id}/image-batches/{batch_id}/candidates/{candidate_id}", response_model=CanvasImageCandidateResponse)
def update_canvas_image_candidate_status(
    canvas_id: str,
    batch_id: str,
    candidate_id: str,
    request: CanvasImageCandidateStatusRequest,
    user: AuthUser = Depends(require_current_user),
    repository: CanvasRepository = Depends(get_canvas_repository),
) -> CanvasImageCandidateResponse:
    canvas = repository.get_canvas(user.id, canvas_id)
    if canvas is None:
        raise HTTPException(status_code=404, detail="Canvas not found")
    existing = repository.get_image_candidate(user.id, canvas_id, candidate_id)
    if existing is None or existing.batch_id != batch_id:
        raise HTTPException(status_code=404, detail="Image candidate not found")
    batch = repository.get_image_batch(user.id, canvas_id, batch_id)
    if batch is None:
        raise HTTPException(status_code=404, detail="Image batch not found")
    if request.status == "selected" and batch.status != "succeeded":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Only succeeded image batches can be selected")
    if request.status != "selected" and existing.node_id in _protected_selected_image_ids(canvas):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Selected image has repair or production media descendants and cannot be rejected")
    candidate = repository.set_image_candidate_status(user.id, canvas_id, batch_id, candidate_id, request.status, request.reason, request.position.model_dump() if request.position else None)
    if candidate is None:
        raise HTTPException(status_code=404, detail="Image candidate not found")
    return _image_candidate_with_repair_protection(candidate, canvas)


@router.post("/api/canvases/{canvas_id}/generate/video", response_model=CanvasGenerateResponse, status_code=status.HTTP_202_ACCEPTED, dependencies=[Depends(require_high_cost_access)])
async def generate_canvas_video(
    canvas_id: str,
    request: CanvasGenerateVideoRequest,
    background_tasks: BackgroundTasks,
    user: AuthUser = Depends(require_current_user),
    canvas_repository: CanvasRepository = Depends(get_canvas_repository),
    project_repository: ProjectRepository = Depends(get_project_repository),
    video_router: VideoRouter = Depends(get_video_router),
    billing: BillingService = Depends(get_billing_service),
    settings: Settings = Depends(get_settings),
) -> CanvasGenerateResponse:
    canvas = await asyncio.to_thread(canvas_repository.get_canvas, user.id, canvas_id)
    if canvas is None:
        raise HTTPException(status_code=404, detail="Canvas not found")
    canvas_node_ids = {node.id for node in canvas.nodes}
    if request.selected_node_ids and not set(request.selected_node_ids).issubset(canvas_node_ids):
        raise HTTPException(status_code=404, detail="Selected node not found")
    _reject_archived_repair_version_selection(canvas, request.selected_node_ids)
    source_asset_id, source_node_ids = await asyncio.to_thread(_resolve_canvas_video_source, user.id, canvas_id, request, canvas_repository, project_repository)
    _reject_unbound_or_archived_asset_inputs(canvas, source_node_ids, [source_asset_id])
    source_asset = await asyncio.to_thread(project_repository.get_asset, user.id, canvas.project_id, source_asset_id)
    if source_asset is None or source_asset.kind != AssetKind.image:
        raise HTTPException(status_code=404, detail="Source image asset not found")
    try:
        validate_video_params(request.params)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    artifact = None
    if request.prompt_artifact_id is not None:
        artifact = await asyncio.to_thread(canvas_repository.get_prompt_artifact, user.id, canvas_id, request.prompt_artifact_id)
        if artifact is None or artifact.kind != "storyboard_video_prompt_version":
            raise HTTPException(status_code=404, detail="Prompt artifact not found")
    effective_prompt = _prompt_artifact_final_prompt(artifact) or request.prompt
    source_image_url = await asyncio.to_thread(_provider_image_source, source_asset.url, source_asset.media_type, settings)
    execution_request = VideoGenerateRequest(prompt=effective_prompt, source_image_asset_id=source_asset.id, source_image_url=source_image_url, duration=request.duration, aspect_ratio=request.aspect_ratio, params=request.params)
    try:
        charge = await asyncio.to_thread(billing.charge_for_action, user.id, canvas.project_id, "canvas_video", {"workflow": "canvas_video_generation", "canvas_id": canvas_id})
    except ValueError as exc:
        raise _billing_error(exc) from exc
    task_input = {
        **request.model_dump(mode="json"),
        "prompt": effective_prompt,
        "canvas_id": canvas_id,
        "source_asset_id": source_asset.id,
        "workflow": "image_to_video_from_canvas",
        "credit_transaction_id": charge.id,
        "estimated_credit_cost": charge.amount,
    }
    try:
        task = await asyncio.to_thread(project_repository.create_task, user.id, canvas.project_id, TaskKind.image_to_video, task_input, charge.amount, charge.amount)
        await asyncio.to_thread(billing.repository.attach_task, user.id, charge.id, task.task_id)
    except Exception:
        await asyncio.to_thread(billing.refund_failed_task, user.id, charge.id, None, "task creation failed")
        raise
    background_tasks.add_task(_run_canvas_video_task, user.id, task.task_id, canvas.project_id, canvas_id, source_node_ids or request.selected_node_ids, source_asset.id, request.prompt_artifact_id, execution_request, charge.id, canvas_repository, project_repository, video_router, billing)
    return CanvasGenerateResponse(task_id=task.task_id, status=task.status)


@router.post("/api/canvases/{canvas_id}/series/plan", response_model=CanvasSeriesPlanResponse, status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_high_cost_access)])
def plan_canvas_series(
    canvas_id: str,
    request: CanvasSeriesPlanRequest,
    user: AuthUser = Depends(require_current_user),
    repository: CanvasRepository = Depends(get_canvas_repository),
) -> CanvasSeriesPlanResponse:
    canvas = repository.get_canvas(user.id, canvas_id)
    if canvas is None:
        raise HTTPException(status_code=404, detail="Canvas not found")
    canvas_node_ids = {node.id for node in canvas.nodes}
    if not set(request.selected_node_ids).issubset(canvas_node_ids):
        raise HTTPException(status_code=404, detail="Selected node not found")
    _reject_archived_repair_version_selection(canvas, request.selected_node_ids)
    compiled = _compile_canvas_or_422(canvas, request.selected_node_ids, request.profile)
    return CanvasSeriesPlanner().plan(compiled, request.frame_count)


@router.post("/api/canvases/{canvas_id}/final-submit", response_model=CanvasFinalSubmitResponse, status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_high_cost_access)])
async def final_submit_canvas(
    canvas_id: str,
    request: CanvasFinalSubmitRequest,
    background_tasks: BackgroundTasks,
    user: AuthUser = Depends(require_current_user),
    canvas_repository: CanvasRepository = Depends(get_canvas_repository),
    project_repository: ProjectRepository = Depends(get_project_repository),
    pipeline: PromptSkillPipeline = Depends(get_prompt_skill_pipeline),
    settings: Settings = Depends(get_settings),
) -> CanvasFinalSubmitResponse:
    canvas = await asyncio.to_thread(canvas_repository.get_canvas, user.id, canvas_id)
    if canvas is None:
        raise HTTPException(status_code=404, detail="Canvas not found")
    canvas_node_ids = {node.id for node in canvas.nodes}
    if not set(request.selected_node_ids).issubset(canvas_node_ids):
        raise HTTPException(status_code=404, detail="Selected node not found")
    if request.artifact_node_id is not None and request.artifact_node_id not in set(request.selected_node_ids):
        raise HTTPException(status_code=404, detail="Artifact node not found")
    if request.root_node_id is not None and request.root_node_id not in set(request.selected_node_ids):
        raise HTTPException(status_code=404, detail="Root node not found")
    _reject_archived_repair_version_selection(canvas, request.selected_node_ids)

    compiled = await asyncio.to_thread(_compile_canvas_or_422, canvas, request.selected_node_ids, request.profile, request.root_node_id)
    generation = request.generation
    generation_params = generation.params if generation is not None else {}
    generate_request = None
    prompt_request = None
    if generation is not None and generation.enabled:
        generate_request = CanvasGenerateImageRequest(
            selected_node_ids=request.selected_node_ids,
            root_node_id=request.root_node_id,
            model=generation.model or "",
            threshold=generation.threshold,
            max_iter=generation.max_iter,
            params=generation.params,
            skip_prompt_evaluation=generation.skip_prompt_evaluation,
        )
        prompt_request = await asyncio.to_thread(_canvas_prompt_skill_request, user.id, canvas.project_id, compiled, generation.params, project_repository, settings)

    image_batches = await asyncio.to_thread(canvas_repository.list_image_batches, user.id, canvas_id, None, 24)
    annotated_batches = [_image_batch_with_repair_context(batch, canvas, image_batches or []) for batch in image_batches or []]
    lineage_node_ids = _lineage_scope_node_ids(canvas, set(request.selected_node_ids))
    branch_operations = await asyncio.to_thread(canvas_repository.list_branch_operations_for_node_ids, user.id, canvas_id, lineage_node_ids)
    if branch_operations is None:
        raise HTTPException(status_code=404, detail="Canvas not found")
    production_lineage = _canvas_production_lineage(canvas, annotated_batches, request.selected_node_ids, branch_operations)
    payload = _canvas_final_submission_payload(compiled, request.selected_node_ids, generation_params, production_lineage)
    try:
        artifact = await asyncio.to_thread(canvas_repository.create_prompt_artifact, user.id, canvas_id, request.artifact_node_id, "canvas_final_submission", payload)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if artifact is None:
        raise HTTPException(status_code=404, detail="Canvas or artifact node not found")

    task_response = None
    if generate_request is not None and prompt_request is not None:
        task_input = {
            "selected_node_ids": request.selected_node_ids,
            "root_node_id": request.root_node_id,
            "model": generate_request.model,
            "threshold": generate_request.threshold,
            "max_iter": generate_request.max_iter,
            "params": generate_request.params,
            "skip_prompt_evaluation": generate_request.skip_prompt_evaluation,
            "canvas_id": canvas_id,
            "final_submission_artifact_id": artifact.id,
        }
        task = await asyncio.to_thread(project_repository.create_task, user.id, canvas.project_id, TaskKind.image, task_input)
        background_tasks.add_task(_run_canvas_image_task, user.id, task.task_id, canvas_id, generate_request, compiled, prompt_request, None, canvas_repository, project_repository, pipeline, None, settings)
        task_response = CanvasFinalTaskResponse(task_id=task.task_id, status=task.status)

    return CanvasFinalSubmitResponse(
        canvas_id=canvas_id,
        project_id=canvas.project_id,
        selected_node_ids=request.selected_node_ids,
        creative_graph=compiled.creative_graph.model_dump(),
        prompt_spec=compiled.prompt_spec,
        final_prompt=compiled.final_prompt,
        asset_references=compiled.creative_graph.references,
        generation_params=generation_params,
        production_lineage=production_lineage,
        artifact=artifact,
        task=task_response,
    )


@router.post("/api/canvases/{canvas_id}/case-index", response_model=CanvasCaseIndexResponse, status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_high_cost_access)])
def index_canvas_case(
    canvas_id: str,
    request: CanvasCaseIndexRequest,
    user: AuthUser = Depends(require_current_user),
    repository: CanvasRepository = Depends(get_canvas_repository),
) -> CanvasCaseIndexResponse:
    canvas = repository.get_canvas(user.id, canvas_id)
    if canvas is None:
        raise HTTPException(status_code=404, detail="Canvas not found")
    artifact = repository.get_prompt_artifact(user.id, canvas_id, request.artifact_id)
    if artifact is None or artifact.kind != "canvas_prompt_compile":
        raise HTTPException(status_code=404, detail="Prompt artifact not found")
    case = CanvasCaseMemoryIndexer().index_payload("pending", request.title, request.quality_score, artifact)
    case_payload = {**case.model_dump(), "artifact_id": artifact.id}
    try:
        saved = repository.create_case_index_entry(user.id, canvas.project_id, case_payload, case_search_text(case).split())
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if saved is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return CanvasCaseIndexResponse(case=saved)


@router.post("/api/canvases/{canvas_id}/director", response_model=CanvasDirectorResponse, dependencies=[Depends(require_high_cost_access)])
def canvas_director(
    canvas_id: str,
    request: CanvasDirectorRequest,
    user: AuthUser = Depends(require_current_user),
    repository: CanvasRepository = Depends(get_canvas_repository),
) -> CanvasDirectorResponse:
    canvas = repository.get_canvas(user.id, canvas_id)
    if canvas is None:
        raise HTTPException(status_code=404, detail="Canvas not found")
    canvas_node_ids = {node.id for node in canvas.nodes}
    if not set(request.selected_node_ids).issubset(canvas_node_ids):
        raise HTTPException(status_code=404, detail="Selected node not found")
    entries = repository.list_case_index_entries(user.id, canvas.project_id)
    if entries is None:
        raise HTTPException(status_code=404, detail="Project not found")
    cases = [IndexedCanvasCase(**{key: value for key, value in entry.items() if key != "terms"}) for entry in entries]
    advice = CanvasCreativeDirector().advise(canvas, request.selected_node_ids, cases)
    return CanvasDirectorResponse(**advice.model_dump())


def _canvas_video_prompt_source_context(
    owner_id: str,
    canvas_id: str,
    project_id: str,
    request: CanvasStoryboardVideoPromptRequest,
    canvas_repository: CanvasRepository,
    project_repository: ProjectRepository,
) -> dict[str, Any]:
    if request.source_candidate_id:
        candidate = canvas_repository.get_image_candidate(owner_id, canvas_id, request.source_candidate_id)
        if candidate is None:
            raise HTTPException(status_code=404, detail="Source image candidate not found")
        return {
            "candidate_id": candidate.id,
            "asset_id": candidate.asset_id,
            "node_id": candidate.node_id,
            "prompt": candidate.prompt,
            "score": candidate.score,
            "status": candidate.status,
        }
    if request.source_image_asset_id:
        asset = project_repository.get_asset(owner_id, project_id, request.source_image_asset_id)
        if asset is None or asset.kind != AssetKind.image:
            raise HTTPException(status_code=404, detail="Source image asset not found")
        return {"asset_id": asset.id, "image_url": asset.url, "media_type": asset.media_type}
    return {}


def _resolve_canvas_video_source(
    owner_id: str,
    canvas_id: str,
    request: CanvasGenerateVideoRequest,
    canvas_repository: CanvasRepository,
    project_repository: ProjectRepository,
) -> tuple[str, list[str]]:
    if request.source_candidate_id:
        candidate = canvas_repository.get_image_candidate(owner_id, canvas_id, request.source_candidate_id)
        if candidate is None:
            raise HTTPException(status_code=404, detail="Source image candidate not found")
        if candidate.status != "selected" or not candidate.node_id:
            raise HTTPException(status_code=422, detail="Video generation requires a selected image candidate")
        return candidate.asset_id, [candidate.node_id]
    canvas = canvas_repository.get_canvas(owner_id, canvas_id)
    if canvas is None:
        raise HTTPException(status_code=404, detail="Canvas not found")
    if not request.selected_node_ids:
        raise HTTPException(status_code=422, detail="Direct canvas video generation requires selected source nodes")
    asset = project_repository.get_asset(owner_id, canvas.project_id, request.source_image_asset_id or "")
    if asset is None or asset.kind != AssetKind.image:
        raise HTTPException(status_code=404, detail="Source image asset not found")
    return asset.id, request.selected_node_ids


async def _run_canvas_video_task(
    owner_id: str,
    task_id: str,
    project_id: str,
    canvas_id: str,
    source_node_ids: list[str],
    source_asset_id: str,
    prompt_artifact_id: str | None,
    request: VideoGenerateRequest,
    credit_transaction_id: str | None,
    canvas_repository: CanvasRepository,
    project_repository: ProjectRepository,
    video_router: VideoRouter,
    billing: BillingService | None,
) -> None:
    if not await asyncio.to_thread(project_repository.set_task_running, task_id):
        task = await asyncio.to_thread(project_repository.get_task, owner_id, task_id)
        if task is None or task.status != TaskStatus.running:
            return
    task = await asyncio.to_thread(project_repository.get_task, owner_id, task_id)
    if task is None or task.status != TaskStatus.running:
        return
    heartbeat_task = asyncio.create_task(_task_heartbeat(project_repository, task_id))
    generated_node_id: str | None = None
    generated_asset_id: str | None = None
    try:
        result = await video_router.generate(request)
        generated = await asyncio.to_thread(
            canvas_repository.create_generated_video_result,
            owner_id,
            project_id,
            canvas_id,
            source_node_ids,
            source_asset_id,
            prompt_artifact_id,
            result.url,
            result.media_type,
            task_id,
            request.prompt,
            {"x": 840, "y": 0},
        )
        if generated is None:
            raise RuntimeError("generated canvas video result was not created")
        generated_node, asset_id = generated
        generated_node_id = generated_node.id
        generated_asset_id = asset_id
        payload = {
            **result.model_dump(mode="json"),
            "canvas": {
                "canvas_id": canvas_id,
                "source_node_ids": source_node_ids,
                "source_asset_id": source_asset_id,
                "generated_node_id": generated_node.id,
                "asset_id": asset_id,
            },
        }
        succeeded = await asyncio.to_thread(project_repository.set_task_succeeded, task_id, payload, [])
        if not succeeded:
            await asyncio.to_thread(canvas_repository.cleanup_generated_media, owner_id, canvas_id, generated_node_id, generated_asset_id)
            return
    except Exception:
        logger.exception("Canvas video generation failed", extra={"task_id": task_id})
        await asyncio.to_thread(canvas_repository.cleanup_generated_media, owner_id, canvas_id, generated_node_id, generated_asset_id)
        if billing is not None:
            await asyncio.to_thread(billing.refund_failed_task, owner_id, credit_transaction_id, task_id, "failed task")
        await asyncio.to_thread(project_repository.set_task_failed, task_id, "画布视频生成失败，请稍后重试或检查模型配置。")
    finally:
        await _stop_task_heartbeat(heartbeat_task)


def _compile_canvas_or_422(canvas: CanvasDetailResponse, selected_node_ids: list[str], profile: str | None, root_node_id: str | None = None) -> CanvasCompileProduct:
    try:
        return CanvasGraphCompiler().compile(canvas, selected_node_ids, profile, root_node_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def _reject_client_managed_payload_impersonation(node_type: str, payload: dict[str, object]) -> None:
    if not payload:
        return
    if any(key in payload for key in ("approval_status", "approved_at", "approval_reason")):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Approval fields are server-managed")
    if payload.get("source") == "canvas_image_edit":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Production media source markers are server-managed")
    if payload.get("role") in {"selected_image", "edited_image", "generated_image", "generated_video", "generated_result", "repair_version"}:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Production and repair roles are server-managed")


def _image_batch_with_repair_context(batch: CanvasImageBatchResponse, canvas: CanvasDetailResponse, image_batches: list[CanvasImageBatchResponse] | None = None) -> CanvasImageBatchResponse:
    repair_context = _image_batch_repair_context(batch, {node.id: node for node in canvas.nodes}, image_batches or [batch])
    candidates = [_image_candidate_with_repair_protection(candidate, canvas) for candidate in batch.candidates]
    return batch.model_copy(update={"repair_context": repair_context or {}, "candidates": candidates})


def _image_candidate_with_repair_protection(candidate: CanvasImageCandidateResponse, canvas: CanvasDetailResponse) -> CanvasImageCandidateResponse:
    protected_node_ids = _protected_selected_image_ids(canvas)
    return candidate.model_copy(update={"repair_protected": bool(candidate.node_id and candidate.node_id in protected_node_ids)})


def _protected_selected_image_ids(canvas: CanvasDetailResponse) -> set[str]:
    return _repair_protected_selected_image_ids(canvas) | _production_media_protected_selected_image_ids(canvas)


def _repair_protected_selected_image_ids(canvas: CanvasDetailResponse) -> set[str]:
    nodes_by_id = {node.id: node for node in canvas.nodes}
    protected_ids = {str(node.payload.get("source_image_node_id")) for node in canvas.nodes if node.type == "repair_version" and node.payload.get("source_image_node_id")}
    for node in canvas.nodes:
        if node.type in {"evaluation", "prompt_program"} and node.payload.get("workflow") == "evaluation_repair_phase_4":
            for source_node_id in node.payload.get("source_node_ids") or []:
                source = nodes_by_id.get(str(source_node_id))
                if source and source.type == "selected_image":
                    protected_ids.add(source.id)
    for edge in canvas.edges:
        if edge.type in {"evaluated_by", "repair_prompt", "repair_version_source"}:
            source = nodes_by_id.get(edge.source_node_id)
            if source and source.type == "selected_image":
                protected_ids.add(source.id)
    return protected_ids


def _production_media_protected_selected_image_ids(canvas: CanvasDetailResponse) -> set[str]:
    nodes_by_id = {node.id: node for node in canvas.nodes}
    media_node_ids = {node.id for node in canvas.nodes if node.type in {"edited_image", "generated_image", "generated_video"}}
    reverse_lineage: dict[str, list[str]] = {}
    for node in canvas.nodes:
        if node.type in {"edited_image", "generated_image", "generated_video"}:
            reverse_lineage.setdefault(node.id, []).extend(str(item) for item in list(node.payload.get("source_node_ids") or []) if item)
    for edge in canvas.edges:
        if edge.type in {"lineage", "image_edit", "video_from_image", "video_remix"} and edge.target_node_id in nodes_by_id:
            reverse_lineage.setdefault(edge.target_node_id, []).append(edge.source_node_id)
    protected_ids: set[str] = set()
    queue = list(media_node_ids)
    visited: set[str] = set()
    while queue:
        node_id = queue.pop(0)
        if node_id in visited:
            continue
        visited.add(node_id)
        for source_id in reverse_lineage.get(node_id, []):
            source = nodes_by_id.get(source_id)
            if source is None:
                continue
            if source.type == "selected_image":
                protected_ids.add(source.id)
            if source_id not in visited:
                queue.append(source_id)
    return protected_ids


def _is_production_media_lineage_edge(canvas: CanvasDetailResponse, edge: CanvasEdgeResponse) -> bool:
    if edge.type not in {"lineage", "image_edit", "video_from_image", "video_remix"}:
        return False
    target = next((node for node in canvas.nodes if node.id == edge.target_node_id), None)
    return bool(target and target.type in {"edited_image", "generated_image", "generated_video"})


def _is_server_managed_lineage_edge_request(canvas: CanvasDetailResponse, edge_type: str, source_node_id: str, target_node_id: str) -> bool:
    source = next((node for node in canvas.nodes if node.id == source_node_id), None)
    target = next((node for node in canvas.nodes if node.id == target_node_id), None)
    managed_types = {"selected_image", "edited_image", "generated_image", "generated_video", "repair_version"}
    if edge_type == "lineage" and (source and source.type in managed_types or target and target.type in managed_types):
        return True
    return bool(target and target.type in {"selected_image", "edited_image", "generated_image", "generated_video"})


def _is_server_managed_lineage_source_node(canvas: CanvasDetailResponse, node_id: str) -> bool:
    return any(
        edge.source_node_id == node_id and (edge.type in {"selected_candidate", "image_edit", "video_from_image", "video_remix"} or _is_server_managed_lineage_edge_request(canvas, edge.type, edge.source_node_id, edge.target_node_id))
        for edge in canvas.edges
    )


def _locked_repair_branch_node_ids(canvas: CanvasDetailResponse) -> set[str]:
    locked_ids: set[str] = set()
    for node in canvas.nodes:
        if node.type == "repair_version":
            locked_ids.update(str(node.payload.get(key)) for key in ("evaluation_node_id", "repair_prompt_node_id") if node.payload.get(key))
    for edge in canvas.edges:
        if edge.type == "repair_version_source":
            source = next((node for node in canvas.nodes if node.id == edge.source_node_id), None)
            if source and source.type in {"evaluation", "prompt_program"}:
                locked_ids.add(source.id)
    return locked_ids


def _is_locked_repair_edge(canvas: CanvasDetailResponse, edge: CanvasEdgeResponse) -> bool:
    locked_ids = _locked_repair_branch_node_ids(canvas)
    return edge.source_node_id in locked_ids or edge.target_node_id in locked_ids


def _image_batch_repair_context(batch: CanvasImageBatchResponse, node_by_id: dict[str, CanvasNodeResponse], image_batches: list[CanvasImageBatchResponse]) -> dict[str, object] | None:
    source_nodes = [node_by_id[node_id] for node_id in batch.source_node_ids if node_id in node_by_id]
    repair_prompt = next((node for node in source_nodes if node.type == "prompt_program" and node.payload.get("workflow") == "evaluation_repair_phase_4"), None)
    if repair_prompt is None:
        return None
    evaluation = next((node for node in source_nodes if node.type == "evaluation" and node.payload.get("workflow") == "evaluation_repair_phase_4"), None)
    source_image = next((node for node in source_nodes if node.type == "selected_image"), None)
    baseline_candidate = _source_image_candidate(source_image, image_batches)
    source_score = _lineage_score(source_image.payload.get("score") if source_image else None)
    evaluation_score = _lineage_score(evaluation.payload.get("score") if evaluation else None)
    baseline_score = source_score if source_score is not None else evaluation_score
    baseline_dimensions = _candidate_dimension_scores(baseline_candidate) if baseline_candidate else {}
    baseline_repair_targets = _candidate_repair_targets(baseline_candidate) if baseline_candidate else []
    return {
        "is_repair_version": True,
        "repair_prompt_node_id": repair_prompt.id,
        "repair_prompt_title": _lineage_text(repair_prompt.title, 240),
        "repair_focus": _repair_focus_lineage(repair_prompt),
        "evaluation_node_id": evaluation.id if evaluation else None,
        "source_image_node_id": source_image.id if source_image else None,
        "source_image_asset_id": source_image.payload.get("asset_id") if source_image else None,
        "source_image_url": source_image.payload.get("image_url") if source_image else None,
        "source_image_media_type": source_image.payload.get("media_type") if source_image else None,
        "source_image_title": _lineage_text(source_image.title, 240) if source_image else "",
        "baseline_score": baseline_score,
        "baseline_dimensions": list(baseline_dimensions.values()),
        "baseline_repair_targets": baseline_repair_targets,
        "candidate_deltas": {candidate.id: _repair_candidate_delta(candidate, baseline_score, baseline_dimensions, baseline_repair_targets) for candidate in batch.candidates[:24]},
    }


def _repair_context_iteration(repair_context: dict[str, Any]) -> int:
    iteration = (repair_context.get("repair_focus") or {}).get("iteration")
    if isinstance(iteration, int | float) and not isinstance(iteration, bool):
        return int(iteration)
    return 1


def _repair_context_best_score_delta(repair_context: dict[str, Any]) -> float:
    candidate_deltas = repair_context.get("candidate_deltas") if isinstance(repair_context.get("candidate_deltas"), dict) else {}
    scores = [_signed_lineage_number(item.get("score_delta")) for item in candidate_deltas.values() if isinstance(item, dict)]
    scores = [score for score in scores if score is not None]
    return max(scores) if scores else 0.0


def _repair_version_node_payload(batch: CanvasImageBatchResponse, repair_context: dict[str, Any]) -> dict[str, object]:
    repair_focus = repair_context.get("repair_focus") if isinstance(repair_context.get("repair_focus"), dict) else {}
    return {
        "role": "repair_version",
        "source": "canvas_repair_version_graph",
        "batch_id": batch.id,
        "status": "active",
        "is_primary_path": False,
        "repair_prompt_node_id": repair_context.get("repair_prompt_node_id") or "",
        "evaluation_node_id": repair_context.get("evaluation_node_id") or "",
        "source_image_node_id": repair_context.get("source_image_node_id") or "",
        "source_image_asset_id": repair_context.get("source_image_asset_id") or "",
        "source_image_title": repair_context.get("source_image_title") or "精选图",
        "repair_focus_key": repair_focus.get("key") or "",
        "repair_focus_label": repair_focus.get("label") or "整体修复",
        "repair_parent_batch_id": repair_focus.get("parent_batch_id") or "",
        "repair_iteration": _repair_context_iteration(repair_context),
        "score": _repair_context_best_score_delta(repair_context),
        "instruction": f"修复版本：{repair_focus.get('label') or '整体修复'}，来源 {repair_context.get('source_image_title') or '精选图'}",
        "source_node_ids": [node_id for node_id in [repair_context.get("source_image_node_id"), repair_context.get("evaluation_node_id"), repair_context.get("repair_prompt_node_id")] if node_id],
    }


def _repair_focus_lineage(repair_prompt: CanvasNodeResponse) -> dict[str, object]:
    focus_key = _lineage_text(str(repair_prompt.payload.get("repair_focus_key") or ""), 80)
    focus_label = _lineage_text(str(repair_prompt.payload.get("repair_focus_label") or focus_key), 120)
    focus: dict[str, object] = {}
    if focus_key:
        focus["key"] = focus_key
    if focus_label:
        focus["label"] = focus_label
    if repair_prompt.payload.get("repair_parent_batch_id"):
        focus["parent_batch_id"] = _lineage_text(str(repair_prompt.payload.get("repair_parent_batch_id")), 120)
    if isinstance(repair_prompt.payload.get("repair_iteration"), int | float) and not isinstance(repair_prompt.payload.get("repair_iteration"), bool):
        focus["iteration"] = repair_prompt.payload.get("repair_iteration")
    return focus


def _reject_archived_repair_version_selection(canvas: CanvasDetailResponse, selected_node_ids: list[str]) -> None:
    selected = set(selected_node_ids)
    if selected & _archived_repair_governed_node_ids(canvas):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Archived repair branches cannot be used as production inputs")


def _node_bound_asset_ids(canvas: CanvasDetailResponse, node_ids: list[str]) -> set[str]:
    return set(_ordered_node_bound_image_asset_ids(canvas, node_ids))


def _ordered_node_bound_image_asset_ids(canvas: CanvasDetailResponse, node_ids: list[str]) -> list[str]:
    nodes_by_id = {node.id: node for node in canvas.nodes}
    asset_ids: list[str] = []
    seen: set[str] = set()
    for node_id in node_ids:
        node = nodes_by_id.get(node_id)
        if node is None:
            continue
        asset_id = _node_bound_image_asset_id(node)
        if asset_id and asset_id not in seen:
            seen.add(asset_id)
            asset_ids.append(asset_id)
    return asset_ids


def _node_bound_image_asset_id(node: CanvasNodeResponse) -> str:
    if node.type in {"asset", "selected_image", "edited_image", "generated_image"} and node.payload.get("asset_id"):
        if node.type != "asset" or str(node.payload.get("asset_kind") or "").lower() == "image" or str(node.payload.get("media_type") or "").startswith("image/"):
            return str(node.payload.get("asset_id"))
    if node.type == "generated_video" and node.payload.get("source_asset_id"):
        return str(node.payload.get("source_asset_id"))
    if node.type == "repair_version" and node.payload.get("source_image_asset_id"):
        return str(node.payload.get("source_image_asset_id"))
    return ""


def _reject_unbound_or_archived_asset_inputs(canvas: CanvasDetailResponse, node_ids: list[str], asset_ids: list[str]) -> None:
    if set(node_ids) & _archived_repair_governed_node_ids(canvas):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Archived repair branches cannot be used as production inputs")
    bound_asset_ids = _node_bound_asset_ids(canvas, node_ids)
    if not set(asset_ids).issubset(bound_asset_ids):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Canvas asset inputs must be bound to the selected non-archived source nodes")


def _validate_repair_batch_source(canvas: CanvasDetailResponse, selected_node_ids: list[str]) -> None:
    selected = set(selected_node_ids)
    nodes_by_id = {node.id: node for node in canvas.nodes}
    repair_prompts = [node for node in canvas.nodes if node.id in selected and node.type == "prompt_program" and node.payload.get("workflow") == "evaluation_repair_phase_4"]
    if not repair_prompts:
        return
    for prompt in repair_prompts:
        prompt_sources = set(str(item) for item in prompt.payload.get("source_node_ids") or [])
        evaluation = next((nodes_by_id.get(node_id) for node_id in prompt_sources if nodes_by_id.get(node_id, None) and nodes_by_id[node_id].type == "evaluation"), None)
        source_image = next((nodes_by_id.get(node_id) for node_id in prompt_sources if nodes_by_id.get(node_id, None) and nodes_by_id[node_id].type == "selected_image"), None)
        if evaluation is None or source_image is None or evaluation.id not in selected or source_image.id not in selected:
            raise HTTPException(status_code=422, detail="Repair image batches require selected source image, evaluation, and repair prompt nodes")
        evaluation_sources = set(str(item) for item in evaluation.payload.get("source_node_ids") or [])
        if evaluation.payload.get("workflow") != "evaluation_repair_phase_4" or source_image.id not in evaluation_sources:
            raise HTTPException(status_code=422, detail="Repair evaluation is not bound to the selected image")
        if evaluation.payload.get("asset_id") and source_image.payload.get("asset_id") and evaluation.payload.get("asset_id") != source_image.payload.get("asset_id"):
            raise HTTPException(status_code=422, detail="Repair evaluation asset does not match the selected image")
        if evaluation.payload.get("candidate_id") and source_image.payload.get("candidate_id") and evaluation.payload.get("candidate_id") != source_image.payload.get("candidate_id"):
            raise HTTPException(status_code=422, detail="Repair evaluation candidate does not match the selected image")


def _canvas_final_submission_payload(compiled: CanvasCompileProduct, selected_node_ids: list[str], generation_params: dict, production_lineage: dict[str, object]) -> dict:
    return {
        **compiled.artifact_payload(selected_node_ids),
        "primary_workflow": "text_to_image_to_video",
        "asset_references": compiled.creative_graph.references,
        "generation_params": generation_params,
        "production_lineage": _compact_production_lineage_for_artifact(production_lineage),
    }


def _compact_production_lineage_for_artifact(lineage: dict[str, object]) -> dict[str, object]:
    return {
        "limits": {**dict(lineage.get("limits") or {}), "artifact_lineage_compacted": True},
        "selected_images": [_compact_media_lineage(item) for item in list(lineage.get("selected_images") or [])[:20] if isinstance(item, dict)],
        "rejected_images": [_compact_media_lineage(item) for item in list(lineage.get("rejected_images") or [])[:20] if isinstance(item, dict)],
        "generated_images": [_compact_media_lineage(item) for item in list(lineage.get("generated_images") or [])[:12] if isinstance(item, dict)],
        "edited_images": [_compact_media_lineage(item) for item in list(lineage.get("edited_images") or [])[:12] if isinstance(item, dict)],
        "video_outputs": [_compact_media_lineage(item) for item in list(lineage.get("video_outputs") or [])[:12] if isinstance(item, dict)],
        "approved_production_media": [_compact_media_lineage(item) for item in list(lineage.get("approved_production_media") or [])[:12] if isinstance(item, dict)],
        "approval_summary": _compact_approval_summary(dict(lineage.get("approval_summary") or {})),
        "repair_versions": [_compact_repair_version_lineage(item) for item in list(lineage.get("repair_versions") or [])[:24] if isinstance(item, dict)],
        "repair_branch_reports": [_compact_branch_report(item) for item in list(lineage.get("repair_branch_reports") or [])[:12] if isinstance(item, dict)],
        "pinned_production_path": _compact_path_lineage(dict(lineage.get("pinned_production_path") or {})),
        "active_production_path": _compact_path_lineage(dict(lineage.get("active_production_path") or {})),
        "branch_operation_log": _compact_branch_operation_log(dict(lineage.get("branch_operation_log") or {})),
        "lineage_edges": [_compact_edge_lineage(item) for item in list(lineage.get("lineage_edges") or [])[:80] if isinstance(item, dict)],
    }


def _compact_media_lineage(item: dict[str, object]) -> dict[str, object]:
    keys = ("id", "batch_id", "asset_id", "task_id", "node_id", "status", "score", "type", "source_node_ids", "source_asset_id", "source_asset_ids", "mask_asset_id", "action_type", "approval_status", "approved_at", "approval_reason")
    return {key: item[key] for key in keys if item.get(key) not in (None, "", [])}


def _compact_approval_summary(item: dict[str, object]) -> dict[str, object]:
    return {
        "approved_count": item.get("approved_count") or 0,
        "draft_count": item.get("draft_count") or 0,
        "approved_edited_images": item.get("approved_edited_images") or 0,
        "approved_videos": item.get("approved_videos") or 0,
        "latest_approve": _compact_operation_reference(dict(item.get("latest_approve") or {})),
        "latest_revoke": _compact_operation_reference(dict(item.get("latest_revoke") or {})),
    }


def _compact_operation_reference(item: dict[str, object]) -> dict[str, object]:
    return {key: item.get(key) for key in ("id", "operation", "reason", "target_node_id", "created_at") if item.get(key) not in (None, "", [])}


def _compact_repair_version_lineage(item: dict[str, object]) -> dict[str, object]:
    focus = item.get("repair_focus") if isinstance(item.get("repair_focus"), dict) else {}
    return {
        "batch_id": item.get("batch_id"),
        "version_status": item.get("version_status"),
        "is_primary_path": bool(item.get("is_primary_path")),
        "source_image_node_id": item.get("source_image_node_id"),
        "source_image_asset_id": item.get("source_image_asset_id"),
        "baseline_score": item.get("baseline_score"),
        "repair_focus": {key: focus.get(key) for key in ("key", "label", "iteration", "parent_batch_id") if focus.get(key) not in (None, "")},
    }


def _compact_branch_report(item: dict[str, object]) -> dict[str, object]:
    return {
        "branch_id": item.get("branch_id"),
        "status": item.get("status"),
        "version_count": item.get("version_count"),
        "score_start": item.get("score_start"),
        "score_end": item.get("score_end"),
        "score_delta": item.get("score_delta"),
        "versions": [_compact_path_version(version) for version in list(item.get("versions") or [])[:12] if isinstance(version, dict)],
    }


def _compact_path_lineage(item: dict[str, object]) -> dict[str, object]:
    return {
        "status": item.get("status"),
        "branch_id": item.get("branch_id"),
        "version_count": item.get("version_count"),
        "score_start": item.get("score_start"),
        "score_end": item.get("score_end"),
        "score_delta": item.get("score_delta"),
        "selection_strategy": item.get("selection_strategy"),
        "versions": [_compact_path_version(version) for version in list(item.get("versions") or [])[:12] if isinstance(version, dict)],
    }


def _compact_path_version(item: dict[str, object]) -> dict[str, object]:
    return {key: item.get(key) for key in ("batch_id", "version_status", "is_primary_path", "iteration", "focus_key", "focus_label", "best_score") if item.get(key) not in (None, "", [])}


def _compact_branch_operation_log(item: dict[str, object]) -> dict[str, object]:
    return {
        "operation_counts": item.get("operation_counts") or {},
        "scope_counts": item.get("scope_counts") or {},
        "latest_materialize": _compact_operation_reference(dict(item.get("latest_materialize") or {})),
        "latest_pin": _compact_operation_reference(dict(item.get("latest_pin") or {})),
        "latest_unpin": _compact_operation_reference(dict(item.get("latest_unpin") or {})),
        "latest_archive": _compact_operation_reference(dict(item.get("latest_archive") or {})),
        "latest_restore": _compact_operation_reference(dict(item.get("latest_restore") or {})),
        "latest_approve": _compact_operation_reference(dict(item.get("latest_approve") or {})),
        "latest_revoke": _compact_operation_reference(dict(item.get("latest_revoke") or {})),
        "latest_select": _compact_operation_reference(dict(item.get("latest_select") or {})),
        "latest_reject": _compact_operation_reference(dict(item.get("latest_reject") or {})),
        "latest_candidate": _compact_operation_reference(dict(item.get("latest_candidate") or {})),
        "latest_operations": [
            {
                "id": operation.get("id"),
                "operation": operation.get("operation"),
                "reason": operation.get("reason"),
                "scope": operation.get("scope"),
                "target_node_id": operation.get("target_node_id"),
                "affected_count": operation.get("affected_count"),
                "payload": _compact_branch_operation_payload(dict(operation.get("payload") or {})),
                "created_at": operation.get("created_at"),
            }
            for operation in list(item.get("latest_operations") or [])[:12]
            if isinstance(operation, dict)
        ],
    }


def _compact_branch_operation_payload(item: dict[str, object]) -> dict[str, object]:
    keys = ("batch_id", "parent_batch_id", "candidate_id", "node_id", "status", "include_descendants", "pinned_node_id", "path_node_ids", "unpin_count", "node_type", "asset_id", "task_id", "from_status", "to_status", "approved_at", "source_asset_id", "source_asset_ids", "mask_asset_id", "action_type")
    return {key: item[key] for key in keys if item.get(key) not in (None, "", [])}


def _compact_edge_lineage(item: dict[str, object]) -> dict[str, object]:
    return {key: item.get(key) for key in ("id", "type", "source_node_id", "target_node_id") if item.get(key) not in (None, "")}


def _canvas_production_lineage(canvas: CanvasDetailResponse, image_batches: list[CanvasImageBatchResponse], selected_node_ids: list[str], branch_operations: list[BranchOperationResponse] | None = None) -> dict[str, object]:
    selected_ids = set(selected_node_ids)
    lineage_node_ids = _lineage_scope_node_ids(canvas, selected_ids)
    scoped_nodes = [node for node in canvas.nodes if node.id in lineage_node_ids]
    scoped_edges = [edge for edge in canvas.edges if edge.source_node_id in lineage_node_ids and edge.target_node_id in lineage_node_ids]
    node_by_id = {node.id: node for node in scoped_nodes}
    lineage_batch_ids = {str(node.payload.get("batch_id")) for node in scoped_nodes if node.type == "repair_version" and node.payload.get("batch_id")}
    bounded_batches = [batch for batch in image_batches if _batch_is_contained_in_lineage(batch, lineage_node_ids, lineage_batch_ids)][:20]
    repair_version_node_by_batch_id = {str(node.payload.get("batch_id")): node for node in scoped_nodes if node.type == "repair_version" and node.payload.get("batch_id")}
    repair_versions = [_repair_version_lineage(batch, node_by_id, bounded_batches, repair_version_node_by_batch_id.get(batch.id)) for batch in bounded_batches]
    repair_versions = [version for version in repair_versions if version is not None][:40]
    active_repair_versions = [version for version in repair_versions if version.get("version_status") == "active"][:40]
    archived_repair_versions = [version for version in repair_versions if version.get("version_status") == "archived"][:40]
    repair_branch_reports = _repair_branch_reports(repair_versions)
    pinned_production_path = _pinned_production_path(repair_branch_reports)
    active_production_path = _active_production_path(repair_branch_reports)
    selected_images = [_candidate_lineage(candidate) for batch in bounded_batches for candidate in batch.candidates[:24] if candidate.status == "selected" and candidate.node_id in node_by_id and node_by_id[candidate.node_id].type == "selected_image"][:80]
    rejected_images = [_candidate_lineage(candidate) for batch in bounded_batches for candidate in batch.candidates[:24] if candidate.status == "rejected"][:80]
    generated_images = [_generated_image_node_lineage(node) for node in scoped_nodes if node.type == "generated_image"][:40]
    video_outputs = [_video_node_lineage(node) for node in scoped_nodes if node.type == "generated_video"][:40]
    edited_images = [_edited_image_node_lineage(node) for node in scoped_nodes if node.type == "edited_image"][:40]
    approved_production_media = _approved_production_media_lineage(edited_images, video_outputs)
    semantic_manifest = _semantic_manifest_lineage(scoped_nodes)
    branch_operation_log = _branch_operation_log_lineage(branch_operations if branch_operations is not None else canvas.branch_operations, lineage_node_ids)
    approval_summary = _approval_summary_lineage(edited_images, video_outputs, branch_operation_log)
    return {
        "limits": {"max_batches": 20, "max_candidates_per_batch": 24, "max_selected_images": 80, "max_rejected_images": 80, "max_generated_images": 40, "max_video_outputs": 40, "max_edited_images": 40, "max_repair_versions": 40, "max_repair_branch_reports": 20, "max_branch_operations": 24, "max_semantic_nodes": 80},
        "semantic_manifest": semantic_manifest,
        "image_batches": [
            {
                "id": batch.id,
                "status": batch.status,
                "task_id": batch.task_id,
                "source_node_ids": batch.source_node_ids[:40],
                "prompt": _lineage_text(batch.prompt),
                "params": {key: batch.params[key] for key in sorted(batch.params)[:12]},
                "candidates": [_candidate_lineage(candidate) for candidate in batch.candidates[:24]],
            }
            for batch in bounded_batches
        ],
        "selected_images": selected_images,
        "rejected_images": rejected_images,
        "generated_images": generated_images,
        "edited_images": edited_images,
        "approved_production_media": approved_production_media,
        "approval_summary": approval_summary,
        "repair_versions": repair_versions,
        "active_repair_versions": active_repair_versions,
        "archived_repair_versions": archived_repair_versions,
        "repair_branch_reports": repair_branch_reports,
        "pinned_production_path": pinned_production_path,
        "active_production_path": active_production_path,
        "branch_operation_log": branch_operation_log,
        "video_outputs": video_outputs,
        "lineage_edges": [_edge_lineage(edge) for edge in scoped_edges if edge.type in {"lineage", "semantic_analysis", "compiled_to_prompt", "evaluated_by", "plans_scene", "contains_shot", "included_in_final", "selected_candidate", "video_from_image", "video_remix", "image_edit", "series_lineage", "repair_prompt", "repair_version_source", "repair_version_child"}][:200],
    }


def _approved_production_media_lineage(edited_images: list[dict[str, object]], video_outputs: list[dict[str, object]]) -> list[dict[str, object]]:
    approved = [item for item in [*edited_images, *video_outputs] if item.get("approval_status") == "approved"]
    return approved[:40]


def _approval_summary_lineage(edited_images: list[dict[str, object]], video_outputs: list[dict[str, object]], branch_operation_log: dict[str, object]) -> dict[str, object]:
    approved_edited_images = sum(1 for item in edited_images if item.get("approval_status") == "approved")
    approved_videos = sum(1 for item in video_outputs if item.get("approval_status") == "approved")
    draft_count = sum(1 for item in [*edited_images, *video_outputs] if item.get("approval_status") != "approved")
    return {
        "approved_count": approved_edited_images + approved_videos,
        "draft_count": draft_count,
        "approved_edited_images": approved_edited_images,
        "approved_videos": approved_videos,
        "latest_approve": branch_operation_log.get("latest_approve"),
        "latest_revoke": branch_operation_log.get("latest_revoke"),
    }


def _lineage_scope_node_ids(canvas: CanvasDetailResponse, selected_ids: set[str]) -> set[str]:
    allowed_downstream_edges = {
        "lineage",
        "semantic_analysis",
        "compiled_to_prompt",
        "evaluated_by",
        "plans_scene",
        "contains_shot",
        "included_in_final",
        "selected_candidate",
        "video_from_image",
        "video_remix",
        "image_edit",
        "series_lineage",
        "repair_prompt",
        "repair_version_source",
        "repair_version_child",
    }
    adjacency: dict[str, list[str]] = {}
    reverse_adjacency: dict[str, list[str]] = {}
    for edge in canvas.edges:
        if edge.type in allowed_downstream_edges:
            adjacency.setdefault(edge.source_node_id, []).append(edge.target_node_id)
            reverse_adjacency.setdefault(edge.target_node_id, []).append(edge.source_node_id)
    for node in canvas.nodes:
        if node.type in {"edited_image", "generated_image", "generated_video", "repair_version"}:
            reverse_adjacency.setdefault(node.id, []).extend(str(item) for item in list(node.payload.get("source_node_ids") or []) if item)
    scoped_ids = set(selected_ids)
    downstream_queue = list(selected_ids)
    while downstream_queue:
        node_id = downstream_queue.pop(0)
        for target_id in adjacency.get(node_id, []):
            if target_id in scoped_ids:
                continue
            scoped_ids.add(target_id)
            downstream_queue.append(target_id)
    upstream_ids = set(selected_ids)
    upstream_queue = list(selected_ids)
    while upstream_queue:
        node_id = upstream_queue.pop(0)
        for source_id in reverse_adjacency.get(node_id, []):
            if source_id in upstream_ids:
                continue
            upstream_ids.add(source_id)
            upstream_queue.append(source_id)
    return scoped_ids | upstream_ids


def _batch_is_contained_in_lineage(batch: CanvasImageBatchResponse, lineage_node_ids: set[str], lineage_batch_ids: set[str]) -> bool:
    if batch.id in lineage_batch_ids:
        return True
    source_ids = set(batch.source_node_ids)
    if source_ids and not source_ids.issubset(lineage_node_ids):
        return False
    return bool(source_ids or any(candidate.node_id in lineage_node_ids for candidate in batch.candidates))


def _branch_operation_log_lineage(branch_operations: list[BranchOperationResponse], lineage_node_ids: set[str]) -> dict[str, object]:
    latest_operations = []
    latest_by_operation: dict[str, dict[str, object]] = {}
    operation_counts: dict[str, int] = {}
    scope_counts: dict[str, int] = {}
    for operation in branch_operations:
        affected_node_ids = [str(item) for item in operation.affected_node_ids if str(item) in lineage_node_ids][:20]
        target_in_scope = bool(operation.target_node_id and operation.target_node_id in lineage_node_ids)
        if not target_in_scope and not affected_node_ids:
            continue
        operation_counts[operation.operation] = operation_counts.get(operation.operation, 0) + 1
        scope_counts[operation.scope] = scope_counts.get(operation.scope, 0) + 1
        operation_lineage = _branch_operation_lineage(operation, affected_node_ids)
        latest_by_operation.setdefault(operation.operation, operation_lineage)
        if len(latest_operations) < 24:
            latest_operations.append(operation_lineage)
    return {
        "latest_operations": latest_operations,
        "operation_counts": operation_counts,
        "scope_counts": scope_counts,
        "latest_materialize": latest_by_operation.get("materialize"),
        "latest_pin": latest_by_operation.get("pin"),
        "latest_unpin": latest_by_operation.get("unpin"),
        "latest_archive": latest_by_operation.get("archive"),
        "latest_restore": latest_by_operation.get("restore"),
        "latest_approve": latest_by_operation.get("approve"),
        "latest_revoke": latest_by_operation.get("revoke"),
        "latest_select": latest_by_operation.get("select"),
        "latest_reject": latest_by_operation.get("reject"),
        "latest_candidate": latest_by_operation.get("candidate"),
    }


def _branch_operation_lineage(operation: BranchOperationResponse, affected_node_ids: list[str]) -> dict[str, object]:
    payload = operation.payload if isinstance(operation.payload, dict) else {}
    allowed_payload_keys = ("batch_id", "parent_batch_id", "candidate_id", "node_id", "status", "include_descendants", "pinned_node_id", "path_node_ids", "unpin_count", "node_type", "asset_id", "task_id", "from_status", "to_status", "approved_at", "source_asset_id", "source_asset_ids", "mask_asset_id", "action_type")
    return {
        "id": operation.id,
        "operation": operation.operation,
        "reason": _lineage_text(operation.reason, 300),
        "scope": operation.scope,
        "target_node_id": operation.target_node_id,
        "affected_node_ids": affected_node_ids,
        "affected_count": len(operation.affected_node_ids),
        "payload": {key: payload[key] for key in allowed_payload_keys if key in payload},
        "created_at": operation.created_at.isoformat(),
    }


def _semantic_manifest_lineage(nodes: list[CanvasNodeResponse]) -> dict[str, object]:
    semantic_types = {"brief", "semantic_spec", "prompt_program", "evaluation", "scene", "shot", "series_frame", "final_json", "repair_version"}
    nodes = [node for node in nodes if node.type in semantic_types][:80]
    return {
        "briefs": [_semantic_node_lineage(node) for node in nodes if node.type == "brief"][:20],
        "semantic_specs": [_semantic_node_lineage(node) for node in nodes if node.type == "semantic_spec"][:20],
        "prompt_programs": [_semantic_node_lineage(node) for node in nodes if node.type == "prompt_program"][:20],
        "evaluations": [_semantic_node_lineage(node) for node in nodes if node.type == "evaluation"][:20],
        "scenes": [_semantic_node_lineage(node) for node in nodes if node.type == "scene"][:20],
        "shots": [_semantic_node_lineage(node) for node in nodes if node.type == "shot"][:40],
        "series_frames": [_semantic_node_lineage(node) for node in nodes if node.type == "series_frame"][:40],
        "final_json_nodes": [_semantic_node_lineage(node) for node in nodes if node.type == "final_json"][:10],
        "repair_version_nodes": [_semantic_node_lineage(node) for node in nodes if node.type == "repair_version"][:40],
    }


def _semantic_node_lineage(node: CanvasNodeResponse) -> dict[str, object]:
    payload_keys = (
        "role",
        "goal",
        "prompt",
        "subject",
        "subject_block",
        "scene",
        "scene_block",
        "composition",
        "composition_block",
        "lighting",
        "lighting_block",
        "visual_style",
        "camera",
        "camera_block",
        "motion_prompt",
        "instruction",
        "reference_instruction",
        "negative_prompt",
        "optimization_prompt",
        "repair_focus_key",
        "repair_focus_label",
        "repair_parent_batch_id",
        "repair_prompt_node_id",
        "evaluation_node_id",
        "source_image_node_id",
        "source_image_asset_id",
        "source_image_title",
        "plan_profile",
        "profile",
        "provenance",
        "source_canvas_id",
        "source_project_id",
        "status",
    )
    payload = {key: _lineage_text(str(node.payload.get(key) or ""), 600) for key in payload_keys if node.payload.get(key)}
    for numeric_key in ("frame_index", "repair_iteration", "score", "total_score"):
        if isinstance(node.payload.get(numeric_key), int | float) and not isinstance(node.payload.get(numeric_key), bool):
            payload[numeric_key] = node.payload[numeric_key]
    list_keys = ("must_keep", "can_change", "negative_constraints", "dimensions", "manifest_sections", "repair_targets", "referenced_asset_ids", "referenced_asset_mentions", "source_node_ids")
    payload.update({key: [str(item)[:180] for item in list(node.payload.get(key) or [])[:12]] for key in list_keys if isinstance(node.payload.get(key), list)})
    return {
        "id": node.id,
        "type": node.type,
        "title": _lineage_text(node.title, 240),
        "payload": payload,
    }


def _repair_branch_reports(repair_versions: list[dict[str, object]]) -> list[dict[str, object]]:
    version_by_batch_id = {str(version.get("batch_id")): version for version in repair_versions if version.get("batch_id")}
    parent_by_batch_id = {batch_id: str((version.get("repair_focus") or {}).get("parent_batch_id") or "") for batch_id, version in version_by_batch_id.items()}
    parent_ids = {parent_id for parent_id in parent_by_batch_id.values() if parent_id}
    terminal_ids = [batch_id for batch_id in version_by_batch_id if batch_id not in parent_ids]
    reports: list[dict[str, object]] = []
    for terminal_id in terminal_ids[:20]:
        chain = _repair_branch_chain(terminal_id, version_by_batch_id, parent_by_batch_id)
        if not chain:
            continue
        first_score = _repair_version_best_score(chain[0])
        last_score = _repair_version_best_score(chain[-1])
        reports.append(
            {
                "branch_id": terminal_id,
                "status": chain[-1].get("version_status") or "unmaterialized",
                "version_count": len(chain),
                "score_start": first_score,
                "score_end": last_score,
                "score_delta": round(last_score - first_score, 2) if first_score is not None and last_score is not None else None,
                "versions": [_repair_branch_report_version(version) for version in chain],
            }
        )
    return reports[:20]


def _pinned_production_path(repair_branch_reports: list[dict[str, object]]) -> dict[str, object]:
    for report in repair_branch_reports:
        versions = [version for version in report.get("versions") or [] if isinstance(version, dict)]
        for index, version in enumerate(versions):
            if not version.get("is_primary_path"):
                continue
            path_versions = versions[: index + 1]
            if any(item.get("version_status") != "active" for item in path_versions):
                return {"status": "invalid", "branch_id": version.get("batch_id") or "", "version_count": len(path_versions), "score_delta": None, "versions": path_versions, "selection_strategy": "designer_pinned"}
            return _production_path_payload(version, path_versions, "designer_pinned")
    return {"status": "none", "branch_id": "", "version_count": 0, "score_delta": None, "versions": [], "selection_strategy": "designer_pinned"}


def _active_production_path(repair_branch_reports: list[dict[str, object]]) -> dict[str, object]:
    pinned_path = _pinned_production_path(repair_branch_reports)
    if pinned_path.get("status") == "active":
        return pinned_path
    candidates: list[tuple[dict[str, object], list[dict[str, object]], float]] = []
    for report in repair_branch_reports:
        versions = [version for version in report.get("versions") or [] if isinstance(version, dict)]
        for index, version in enumerate(versions):
            if version.get("version_status") != "active":
                continue
            path_versions = versions[: index + 1]
            if any(item.get("version_status") != "active" for item in path_versions):
                continue
            score = _lineage_score(version.get("best_score"))
            if score is not None:
                candidates.append((version, path_versions, score))
    if not candidates:
        return {"status": "none", "branch_id": "", "version_count": 0, "score_delta": None, "versions": [], "selection_strategy": "auto_score"}
    best_version, path_versions, _score_end = max(candidates, key=lambda item: item[2])
    return _production_path_payload(best_version, path_versions, "auto_score")


def _production_path_payload(version: dict[str, object], path_versions: list[dict[str, object]], selection_strategy: str) -> dict[str, object]:
    score_end = _lineage_score(version.get("best_score"))
    score_start = _lineage_score(path_versions[0].get("best_score")) if path_versions else None
    return {
        "status": "active" if score_end is not None else "none",
        "branch_id": version.get("batch_id") or "",
        "version_count": len(path_versions),
        "score_start": score_start,
        "score_end": score_end,
        "score_delta": round(score_end - score_start, 2) if score_end is not None and score_start is not None else None,
        "versions": path_versions,
        "selection_strategy": selection_strategy,
    }


def _repair_branch_chain(terminal_id: str, version_by_batch_id: dict[str, dict[str, object]], parent_by_batch_id: dict[str, str]) -> list[dict[str, object]]:
    chain: list[dict[str, object]] = []
    seen: set[str] = set()
    batch_id = terminal_id
    while batch_id and batch_id not in seen:
        version = version_by_batch_id.get(batch_id)
        if version is None:
            break
        chain.insert(0, version)
        seen.add(batch_id)
        batch_id = parent_by_batch_id.get(batch_id, "")
    return chain


def _repair_branch_report_version(version: dict[str, object]) -> dict[str, object]:
    best_candidate = _repair_version_best_candidate(version)
    focus = version.get("repair_focus") if isinstance(version.get("repair_focus"), dict) else {}
    return {
        "batch_id": version.get("batch_id"),
        "version_status": version.get("version_status"),
        "is_primary_path": bool(version.get("is_primary_path")),
        "iteration": focus.get("iteration"),
        "focus_key": focus.get("key"),
        "focus_label": focus.get("label"),
        "baseline_score": version.get("baseline_score"),
        "best_score": _repair_version_best_score(version),
        "best_score_delta": best_candidate.get("score_delta") if best_candidate else None,
        "dimension_deltas": best_candidate.get("dimension_deltas") if best_candidate else [],
        "resolved_targets": best_candidate.get("resolved_targets") if best_candidate else [],
        "branch_audit_trail": version.get("branch_audit_trail") or [],
    }


def _repair_version_best_score(version: dict[str, object]) -> float | None:
    best_candidate = _repair_version_best_candidate(version)
    if best_candidate is None:
        return _lineage_score(version.get("baseline_score"))
    return _lineage_score(best_candidate.get("score"))


def _repair_version_best_candidate(version: dict[str, object]) -> dict[str, object] | None:
    candidates = [candidate for candidate in version.get("candidates") or [] if isinstance(candidate, dict)]
    scored = [(candidate, _lineage_score(candidate.get("score"))) for candidate in candidates]
    scored = [(candidate, score) for candidate, score in scored if score is not None]
    if not scored:
        return None
    return max(scored, key=lambda item: item[1])[0]


def _repair_version_lineage(batch: CanvasImageBatchResponse, node_by_id: dict[str, CanvasNodeResponse], image_batches: list[CanvasImageBatchResponse], version_node: CanvasNodeResponse | None = None) -> dict[str, object] | None:
    repair_context = batch.repair_context or _image_batch_repair_context(batch, node_by_id, image_batches)
    if not repair_context:
        return None
    version_status = version_node.payload.get("status") if version_node else None
    return {
        "batch_id": batch.id,
        "status": version_status or batch.status,
        "batch_status": batch.status,
        "version_status": version_status or "unmaterialized",
        "is_primary_path": bool(version_node and version_node.payload.get("is_primary_path")),
        "repair_prompt_node_id": repair_context.get("repair_prompt_node_id"),
        "repair_prompt_title": repair_context.get("repair_prompt_title"),
        "repair_focus": repair_context.get("repair_focus") or {},
        "evaluation_node_id": repair_context.get("evaluation_node_id"),
        "source_image_node_id": repair_context.get("source_image_node_id"),
        "source_image_asset_id": repair_context.get("source_image_asset_id"),
        "source_image_url": repair_context.get("source_image_url"),
        "source_image_media_type": repair_context.get("source_image_media_type"),
        "baseline_score": repair_context.get("baseline_score"),
        "baseline_dimensions": repair_context.get("baseline_dimensions") or [],
        "baseline_repair_targets": repair_context.get("baseline_repair_targets") or [],
        "branch_audit_trail": [item for item in list(version_node.payload.get("branch_audit_trail") or [])[:12] if isinstance(item, dict)] if version_node else [],
        "candidates": list((repair_context.get("candidate_deltas") or {}).values())[:24],
    }


def _source_image_candidate(source_image: CanvasNodeResponse | None, image_batches: list[CanvasImageBatchResponse]) -> CanvasImageCandidateResponse | None:
    candidate_id = source_image.payload.get("candidate_id") if source_image else None
    if not candidate_id:
        return None
    return next((candidate for batch in image_batches for candidate in batch.candidates if candidate.id == candidate_id), None)


def _candidate_dimension_scores(candidate: CanvasImageCandidateResponse | None) -> dict[str, dict[str, object]]:
    if candidate is None:
        return {}
    evaluation = candidate.metadata.get("evaluation") if isinstance(candidate.metadata, dict) else None
    dimensions = evaluation.get("dimensions") if isinstance(evaluation, dict) and isinstance(evaluation.get("dimensions"), list) else []
    scores: dict[str, dict[str, object]] = {}
    for item in dimensions[:8]:
        if not isinstance(item, dict):
            continue
        key = str(item.get("key") or item.get("label") or "").strip()
        score = _lineage_score(item.get("score"))
        if not key or score is None:
            continue
        scores[key] = {"key": _lineage_text(key, 80), "label": _lineage_text(str(item.get("label") or key), 80), "score": score}
    return scores


def _candidate_repair_targets(candidate: CanvasImageCandidateResponse | None) -> list[str]:
    if candidate is None:
        return []
    evaluation = candidate.metadata.get("evaluation") if isinstance(candidate.metadata, dict) else None
    repair_targets = evaluation.get("repair_targets") if isinstance(evaluation, dict) and isinstance(evaluation.get("repair_targets"), list) else []
    return [_lineage_text(str(item), 240) for item in repair_targets[:8]]


def _repair_candidate_delta(candidate: CanvasImageCandidateResponse, baseline_score: float | None, baseline_dimensions: dict[str, dict[str, object]], baseline_repair_targets: list[str]) -> dict[str, object]:
    score = _lineage_score(candidate.score)
    current_dimensions = _candidate_dimension_scores(candidate)
    current_repair_targets = set(_candidate_repair_targets(candidate))
    return {
        "id": candidate.id,
        "asset_id": candidate.asset_id,
        "status": candidate.status,
        "score": score,
        "score_delta": round(score - baseline_score, 2) if score is not None and baseline_score is not None else None,
        "dimension_deltas": [_dimension_delta(item, current_dimensions.get(key)) for key, item in baseline_dimensions.items()],
        "resolved_targets": [target for target in baseline_repair_targets if target not in current_repair_targets],
    }


def _dimension_delta(baseline: dict[str, object], current: dict[str, object] | None) -> dict[str, object]:
    baseline_score = _lineage_score(baseline.get("score"))
    current_score = _lineage_score(current.get("score") if current else None)
    return {
        "key": baseline.get("key") or "",
        "label": baseline.get("label") or baseline.get("key") or "",
        "baseline_score": baseline_score,
        "score": current_score,
        "delta": round(current_score - baseline_score, 2) if current_score is not None and baseline_score is not None else None,
    }


def _candidate_lineage(candidate: CanvasImageCandidateResponse) -> dict[str, object]:
    return {
        "id": candidate.id,
        "batch_id": candidate.batch_id,
        "asset_id": candidate.asset_id,
        "task_id": candidate.task_id,
        "node_id": candidate.node_id,
        "index": candidate.index,
        "status": candidate.status,
        "score": candidate.score,
        "prompt": _lineage_text(candidate.prompt),
        "evaluation": _candidate_evaluation_lineage(candidate.metadata.get("evaluation")),
    }


def _candidate_evaluation_lineage(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        return {}
    dimensions = value.get("dimensions") if isinstance(value.get("dimensions"), list) else []
    repair_targets = value.get("repair_targets") if isinstance(value.get("repair_targets"), list) else []
    return {
        "total_score": _lineage_score(value.get("total_score")),
        "dimensions": [
            {
                "key": _lineage_text(str(item.get("key") or ""), 80),
                "label": _lineage_text(str(item.get("label") or ""), 80),
                "score": _lineage_score(item.get("score")),
            }
            for item in dimensions[:8]
            if isinstance(item, dict)
        ],
        "repair_targets": [_lineage_text(str(item), 240) for item in repair_targets[:8]],
        "suggestion": _lineage_text(str(value.get("suggestion") or ""), 600),
        "optimization_prompt": _lineage_text(str(value.get("optimization_prompt") or ""), 800),
    }


def _lineage_score(value: object) -> float | None:
    score = _signed_lineage_number(value)
    if score is None or not 0 <= score <= 10:
        return None
    return score


def _signed_lineage_number(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        return round(float(value), 2)
    except (TypeError, ValueError):
        return None


def _generated_image_node_lineage(node: CanvasNodeResponse) -> dict[str, object]:
    return {
        "id": node.id,
        "type": node.type,
        "asset_id": node.payload.get("asset_id"),
        "source_node_ids": list(node.payload.get("source_node_ids") or [])[:40],
        "task_id": node.payload.get("task_id"),
        "final_prompt": _lineage_text(str(node.payload.get("final_prompt") or "")),
    }


def _edited_image_node_lineage(node: CanvasNodeResponse) -> dict[str, object]:
    return {
        "id": node.id,
        "type": node.type,
        "asset_id": node.payload.get("asset_id"),
        "source_node_ids": list(node.payload.get("source_node_ids") or [])[:40],
        "source_asset_ids": list(node.payload.get("source_asset_ids") or [])[:8],
        "mask_asset_id": node.payload.get("mask_asset_id"),
        "task_id": node.payload.get("task_id"),
        "action_type": node.payload.get("action_type"),
        "approval_status": node.payload.get("approval_status"),
        "approved_at": node.payload.get("approved_at"),
        "approval_reason": _lineage_text(str(node.payload.get("approval_reason") or ""), 400),
        "edit_prompt": _lineage_text(str(node.payload.get("edit_prompt") or "")),
        "final_prompt": _lineage_text(str(node.payload.get("final_prompt") or "")),
    }


def _video_node_lineage(node: CanvasNodeResponse) -> dict[str, object]:
    return {
        "id": node.id,
        "type": node.type,
        "asset_id": node.payload.get("asset_id"),
        "source_node_ids": list(node.payload.get("source_node_ids") or [])[:40],
        "source_asset_id": node.payload.get("source_asset_id"),
        "task_id": node.payload.get("task_id"),
        "approval_status": node.payload.get("approval_status"),
        "approved_at": node.payload.get("approved_at"),
        "approval_reason": _lineage_text(str(node.payload.get("approval_reason") or ""), 400),
        "motion_prompt": _lineage_text(str(node.payload.get("motion_prompt") or "")),
    }


def _edge_lineage(edge: CanvasEdgeResponse) -> dict[str, object]:
    return {
        "id": edge.id,
        "type": edge.type,
        "source_node_id": edge.source_node_id,
        "target_node_id": edge.target_node_id,
        "payload": _safe_edge_lineage_payload(edge.payload),
    }


def _safe_edge_lineage_payload(payload: dict[str, object]) -> dict[str, object]:
    safe: dict[str, object] = {}
    for key in sorted(payload)[:8]:
        value = _safe_edge_lineage_value(payload[key])
        if value not in (None, "", []):
            safe[key] = value
    return safe


def _safe_edge_lineage_value(value: object) -> object:
    if isinstance(value, str):
        return _lineage_text(value, 600)
    if isinstance(value, bool):
        return value
    if isinstance(value, int | float):
        return value
    if isinstance(value, list):
        return [_lineage_text(str(item), 180) for item in value[:12] if isinstance(item, str | int | float | bool)]
    return None


def _lineage_text(value: str, limit: int = 1200) -> str:
    return value if len(value) <= limit else f"{value[:limit]}…"


async def _run_canvas_image_task(
    owner_id: str,
    task_id: str,
    canvas_id: str,
    request: CanvasGenerateImageRequest,
    compiled: CanvasCompileProduct,
    prompt_request: PromptSkillRequest,
    credit_transaction_id: str | None,
    canvas_repository: CanvasRepository,
    project_repository: ProjectRepository,
    pipeline: PromptSkillPipeline,
    billing: BillingService | None,
    settings: Settings,
) -> None:
    image_url: str | None = None
    generated_node_id: str | None = None
    generated_asset_id: str | None = None
    if not await asyncio.to_thread(project_repository.set_task_running, task_id):
        task = await asyncio.to_thread(project_repository.get_task, owner_id, task_id)
        if task is None or task.status != TaskStatus.running:
            return
    task = await asyncio.to_thread(project_repository.get_task, owner_id, task_id)
    if task is None or task.status != TaskStatus.running:
        return
    heartbeat_task = asyncio.create_task(_task_heartbeat(project_repository, task_id))
    try:
        result, prompt_skill = await pipeline.run(
            prompt_request,
            model_id=request.model,
            threshold=request.threshold,
            max_iter=request.max_iter,
            skip_prompt_evaluation=request.skip_prompt_evaluation,
        )
        media_type = result.image.metadata.get("media_type", "image/png")
        image_url = await asyncio.to_thread(_persist_generated_image_url, result.image.b64_json, result.image.url, media_type, task_id, settings)
        generated = await asyncio.to_thread(
            canvas_repository.create_generated_image_result,
            owner_id,
            task.project_id,
            canvas_id,
            request.selected_node_ids,
            image_url,
            media_type,
            task_id,
            result.final_prompt,
            _generated_node_position(compiled),
        )
        if generated is None:
            raise RuntimeError("generated canvas result was not created")
        generated_node, asset_id = generated
        generated_node_id = generated_node.id
        generated_asset_id = asset_id
        payload = {
            "image_url": image_url,
            "image_media_type": media_type,
            "final_prompt": result.final_prompt,
            "score": result.score,
            "iterations": result.iterations,
            "prompt_report": result.prompt_report.model_dump(mode="json"),
            "optimization_trace": result.optimization_trace.model_dump(mode="json") if result.optimization_trace else None,
            "prompt_skill": prompt_skill.model_dump(mode="json"),
            "canvas": {
                "canvas_id": canvas_id,
                "source_node_ids": request.selected_node_ids,
                "generated_node_id": generated_node.id,
                "asset_id": asset_id,
                "references": compiled.creative_graph.references,
            },
        }
        history = [
            {
                "iteration": item.iteration,
                "prompt": item.prompt,
                "score": item.visual_report.total_score if item.visual_report else None,
                "image_url": item.image.url if item.image else None,
                "visual_report": item.visual_report.model_dump(mode="json") if item.visual_report else None,
            }
            for item in result.prompt_history
        ]
        succeeded = await asyncio.to_thread(project_repository.set_task_succeeded, task_id, payload, history)
        if not succeeded:
            await asyncio.to_thread(canvas_repository.cleanup_generated_media, owner_id, canvas_id, generated_node_id, generated_asset_id)
            if image_url is not None:
                await asyncio.to_thread(_delete_generated_image_file, image_url, settings)
            return
    except Exception:
        logger.exception("Canvas image generation failed", extra={"task_id": task_id})
        await asyncio.to_thread(canvas_repository.cleanup_generated_media, owner_id, canvas_id, generated_node_id, generated_asset_id)
        if image_url is not None:
            await asyncio.to_thread(_delete_generated_image_file, image_url, settings)
        if billing is not None:
            await asyncio.to_thread(billing.refund_failed_task, owner_id, credit_transaction_id, task_id, "failed task")
        await asyncio.to_thread(project_repository.set_task_failed, task_id, CANVAS_IMAGE_FAILURE_MESSAGE)
    finally:
        await _stop_task_heartbeat(heartbeat_task)


async def _run_canvas_image_edit_task(
    owner_id: str,
    task_id: str,
    canvas_id: str,
    request: CanvasGenerateImageEditRequest,
    prompt_request: PromptSkillRequest,
    position: dict[str, float],
    credit_transaction_id: str | None,
    canvas_repository: CanvasRepository,
    project_repository: ProjectRepository,
    pipeline: PromptSkillPipeline,
    billing: BillingService | None,
    settings: Settings,
) -> None:
    image_url: str | None = None
    generated_node_id: str | None = None
    generated_asset_id: str | None = None
    if not await asyncio.to_thread(project_repository.set_task_running, task_id):
        task = await asyncio.to_thread(project_repository.get_task, owner_id, task_id)
        if task is None or task.status != TaskStatus.running:
            return
    task = await asyncio.to_thread(project_repository.get_task, owner_id, task_id)
    if task is None or task.status != TaskStatus.running:
        return
    heartbeat_task = asyncio.create_task(_task_heartbeat(project_repository, task_id))
    try:
        result, prompt_skill = await pipeline.run(
            prompt_request,
            model_id=request.model,
            threshold=request.threshold,
            max_iter=request.max_iter,
            skip_prompt_evaluation=request.skip_prompt_evaluation,
        )
        media_type = result.image.metadata.get("media_type", "image/png")
        image_url = await asyncio.to_thread(_persist_generated_image_url, result.image.b64_json, result.image.url, media_type, task_id, settings)
        generated = await asyncio.to_thread(
            canvas_repository.create_edited_image_result,
            owner_id,
            task.project_id,
            canvas_id,
            request.source_node_ids,
            request.source_image_asset_ids,
            request.mask_asset_id,
            image_url,
            media_type,
            task_id,
            request.prompt,
            result.final_prompt,
            request.action_type.value,
            position,
        )
        if generated is None:
            raise RuntimeError("edited canvas image result was not created")
        generated_node, asset_id = generated
        generated_node_id = generated_node.id
        generated_asset_id = asset_id
        payload = {
            "image_url": image_url,
            "image_media_type": media_type,
            "final_prompt": result.final_prompt,
            "score": result.score,
            "iterations": result.iterations,
            "prompt_report": result.prompt_report.model_dump(mode="json"),
            "optimization_trace": result.optimization_trace.model_dump(mode="json") if result.optimization_trace else None,
            "prompt_skill": prompt_skill.model_dump(mode="json"),
            "canvas": {
                "canvas_id": canvas_id,
                "source_node_ids": request.source_node_ids,
                "source_asset_ids": request.source_image_asset_ids,
                "generated_node_id": generated_node.id,
                "asset_id": asset_id,
                "action_type": request.action_type.value,
            },
        }
        history = [
            {
                "iteration": item.iteration,
                "prompt": item.prompt,
                "score": item.visual_report.total_score if item.visual_report else None,
                "image_url": item.image.url if item.image else None,
                "visual_report": item.visual_report.model_dump(mode="json") if item.visual_report else None,
            }
            for item in result.prompt_history
        ]
        succeeded = await asyncio.to_thread(project_repository.set_task_succeeded, task_id, payload, history)
        if not succeeded:
            await asyncio.to_thread(canvas_repository.cleanup_generated_media, owner_id, canvas_id, generated_node_id, generated_asset_id)
            if image_url is not None:
                await asyncio.to_thread(_delete_generated_image_file, image_url, settings)
            return
    except Exception:
        logger.exception("Canvas image edit failed", extra={"task_id": task_id})
        await asyncio.to_thread(canvas_repository.cleanup_generated_media, owner_id, canvas_id, generated_node_id, generated_asset_id)
        if image_url is not None:
            await asyncio.to_thread(_delete_generated_image_file, image_url, settings)
        if billing is not None:
            await asyncio.to_thread(billing.refund_failed_task, owner_id, credit_transaction_id, task_id, "failed task")
        await asyncio.to_thread(project_repository.set_task_failed, task_id, CANVAS_IMAGE_FAILURE_MESSAGE)
    finally:
        await _stop_task_heartbeat(heartbeat_task)


def _candidate_evaluation_metadata(result: Any) -> dict[str, object]:
    visual_report = result.prompt_history[-1].visual_report if result.prompt_history else None
    if visual_report is None:
        return {
            "total_score": result.score,
            "dimensions": [],
            "repair_targets": [],
            "suggestion": "",
            "optimization_prompt": "",
        }
    dimensions = [
        {"key": "composition", "label": "构图", "score": visual_report.composition},
        {"key": "subject_match", "label": "主体一致", "score": visual_report.subject_match},
        {"key": "style_match", "label": "风格一致", "score": visual_report.style_match},
        {"key": "technical_quality", "label": "技术质量", "score": visual_report.technical_quality},
    ]
    return {
        "total_score": visual_report.total_score,
        "dimensions": dimensions,
        "repair_targets": [*visual_report.defects[:6], *visual_report.optimization_hints[:6]][:8],
        "suggestion": visual_report.suggestion[:1000],
        "optimization_prompt": visual_report.optimization_prompt[:1200],
    }


async def _run_canvas_image_batch_task(
    owner_id: str,
    task_id: str,
    batch_id: str,
    canvas_id: str,
    request: CanvasGenerateImageRequest,
    compiled: CanvasCompileProduct,
    prompt: str,
    credit_transaction_id: str | None,
    canvas_repository: CanvasRepository,
    project_repository: ProjectRepository,
    pipeline: PromptSkillPipeline,
    billing: BillingService | None,
    settings: Settings,
) -> None:
    created_candidates: list[dict[str, object]] = []
    created_candidate_ids: list[str] = []
    created_asset_ids: list[str] = []
    created_image_urls: list[str] = []
    if not await asyncio.to_thread(project_repository.set_task_running, task_id):
        task = await asyncio.to_thread(project_repository.get_task, owner_id, task_id)
        if task is None or task.status != TaskStatus.running:
            return
    task = await asyncio.to_thread(project_repository.get_task, owner_id, task_id)
    if task is None or task.status != TaskStatus.running:
        return
    heartbeat_task = asyncio.create_task(_task_heartbeat(project_repository, task_id))
    try:
        await asyncio.to_thread(canvas_repository.set_image_batch_status, owner_id, batch_id, "running")
        count = int(request.params.get("n") or 1)
        for index in range(count):
            candidate_params = {**request.params, "n": 1}
            prompt_request = await asyncio.to_thread(_canvas_prompt_skill_request, owner_id, task.project_id, compiled, candidate_params, project_repository, settings, prompt)
            result, prompt_skill = await pipeline.run(
                prompt_request,
                model_id=request.model,
                threshold=request.threshold,
                max_iter=request.max_iter,
                skip_prompt_evaluation=request.skip_prompt_evaluation,
            )
            media_type = result.image.metadata.get("media_type", "image/png")
            image_url = await asyncio.to_thread(_persist_generated_image_url, result.image.b64_json, result.image.url, media_type, f"{task_id}-{index}", settings)
            created_image_urls.append(image_url)
            asset = await asyncio.to_thread(
                project_repository.create_asset,
                owner_id,
                task.project_id,
                AssetKind.image,
                image_url,
                media_type,
                {
                    "task_id": task_id,
                    "batch_id": batch_id,
                    "canvas_id": canvas_id,
                    "source": "canvas_image_batch",
                    "candidate_index": index,
                    "source_node_ids": request.selected_node_ids,
                },
            )
            created_asset_ids.append(asset.id)
            candidate_metadata = {
                "image_url": image_url,
                "media_type": media_type,
                "iterations": result.iterations,
                "prompt_score": result.prompt_report.score,
                "reference_count": len(compiled.creative_graph.references),
                "quality_gate_count": len(prompt_skill.quality_gates),
                "evaluation": _candidate_evaluation_metadata(result),
            }
            candidate = await asyncio.to_thread(canvas_repository.create_image_candidate, owner_id, batch_id, asset.id, task_id, index, result.final_prompt, result.score, candidate_metadata)
            if candidate is None:
                raise RuntimeError("image batch candidate was not created")
            created_candidate_ids.append(candidate.id)
            created_candidates.append(candidate.model_dump(mode="json"))
        await asyncio.to_thread(canvas_repository.set_image_batch_status, owner_id, batch_id, "succeeded")
        succeeded = await asyncio.to_thread(
            project_repository.set_task_succeeded,
            task_id,
            {
                "batch_id": batch_id,
                "canvas_id": canvas_id,
                "selected_node_ids": request.selected_node_ids,
                "candidate_count": len(created_candidates),
                "candidates": created_candidates,
            },
            [],
        )
        if not succeeded:
            await asyncio.to_thread(canvas_repository.cleanup_image_batch_candidates_by_ids, owner_id, batch_id, created_candidate_ids, created_asset_ids)
            for created_image_url in created_image_urls:
                await asyncio.to_thread(_delete_generated_image_file, created_image_url, settings)
            return
    except Exception:
        logger.exception("Canvas image batch generation failed", extra={"task_id": task_id, "batch_id": batch_id})
        await asyncio.to_thread(canvas_repository.cleanup_image_batch_candidates_by_ids, owner_id, batch_id, created_candidate_ids, created_asset_ids)
        for created_image_url in created_image_urls:
            await asyncio.to_thread(_delete_generated_image_file, created_image_url, settings)
        if billing is not None:
            await asyncio.to_thread(billing.refund_failed_task, owner_id, credit_transaction_id, task_id, "failed task")
        await asyncio.to_thread(project_repository.set_task_failed, task_id, CANVAS_IMAGE_FAILURE_MESSAGE)
    finally:
        await _stop_task_heartbeat(heartbeat_task)


def _canvas_image_edit_prompt_request(
    owner_id: str,
    project_id: str,
    request: CanvasGenerateImageEditRequest,
    repository: ProjectRepository,
    settings: Settings,
) -> PromptSkillRequest:
    source_images = [_canvas_asset_image_source(owner_id, project_id, asset_id, repository, settings) for asset_id in request.source_image_asset_ids]
    mask_image = _canvas_asset_image_source(owner_id, project_id, request.mask_asset_id, repository, settings, role="mask") if request.mask_asset_id else None
    return PromptSkillRequest(
        prompt=request.prompt,
        action_type=request.action_type,
        source_images=source_images,
        mask_image=mask_image,
        params={**request.params, "response_format": "b64_json"},
    )


def _canvas_asset_image_source(
    owner_id: str,
    project_id: str,
    asset_id: str,
    repository: ProjectRepository,
    settings: Settings,
    role: str = "source",
) -> ImageSource:
    asset = repository.get_asset(owner_id, project_id, asset_id)
    if asset is None or asset.kind != AssetKind.image:
        raise HTTPException(status_code=404, detail="Source image asset not found")
    return ImageSource(
        asset_id=asset.id,
        url=_provider_image_source(asset.url, asset.media_type, settings),
        media_type=asset.media_type,
        role=role,
        metadata={"project_id": project_id, "asset_url": asset.url},
    )


def _prompt_artifact_final_prompt(artifact: PromptArtifactResponse | None) -> str | None:
    if artifact is None:
        return None
    prompt = artifact.payload.get("final_prompt") or artifact.payload.get("compiled_prompt")
    if not isinstance(prompt, str):
        return None
    stripped = prompt.strip()
    return stripped or None


def _canvas_prompt_skill_request(
    owner_id: str,
    project_id: str,
    compiled: CanvasCompileProduct,
    params: dict,
    repository: ProjectRepository,
    settings: Settings,
    prompt: str | None = None,
) -> PromptSkillRequest:
    source_images = [_canvas_image_source(owner_id, project_id, reference, repository, settings) for reference in _canvas_image_references(compiled.creative_graph.references)]
    return PromptSkillRequest(
        prompt=prompt or compiled.final_prompt,
        action_type=ImageActionType.TEXT_AND_IMAGE_TO_IMAGE if source_images else ImageActionType.TEXT_TO_IMAGE,
        source_images=source_images,
        character_anchors=compiled.creative_graph.character_anchors,
        params={**params, "response_format": "b64_json"},
    )


def _canvas_image_references(references: list[dict[str, object]]) -> list[dict[str, object]]:
    return [
        reference
        for reference in references
        if str(reference.get("asset_kind") or "").lower() == "image" or str(reference.get("media_type") or "").lower().startswith("image/")
    ]


def _canvas_image_source(
    owner_id: str,
    project_id: str,
    reference: dict[str, object],
    repository: ProjectRepository,
    settings: Settings,
) -> ImageSource:
    asset_id = str(reference.get("asset_id") or "")
    asset = repository.get_asset(owner_id, project_id, asset_id)
    if asset is None or asset.kind != AssetKind.image:
        raise HTTPException(status_code=404, detail="Canvas reference asset not found")
    metadata = {key: reference[key] for key in ("node_id", "mention_label", "instruction", "influence_strength") if key in reference}
    return ImageSource(asset_id=asset.id, url=_provider_image_source(asset.url, asset.media_type, settings), media_type=asset.media_type, role=str(reference.get("role") or "reference_image"), metadata=metadata)


def _delete_generated_image_file(image_url: str, settings: Settings) -> None:
    if not image_url.startswith("/uploads/image-optimizer/"):
        return
    path = settings.asset_upload_dir / "image-optimizer" / Path(image_url).name
    try:
        path.unlink()
    except FileNotFoundError:
        return
    except OSError:
        logger.warning("Generated image file cleanup failed", extra={"path": str(path)})


def _result_node_position(canvas: CanvasDetailResponse, source_node_ids: list[str], fallback: dict[str, float]) -> dict[str, float]:
    source_set = set(source_node_ids)
    nodes = [node for node in canvas.nodes if node.id in source_set]
    if not nodes:
        return fallback
    max_x = max(node.position.x for node in nodes)
    min_y = min(node.position.y for node in nodes)
    return {"x": float(max_x + 420), "y": float(min_y)}


def _generated_node_position(compiled: CanvasCompileProduct) -> dict[str, float]:
    nodes = compiled.creative_graph.nodes
    if not nodes:
        return {"x": 480.0, "y": 120.0}
    max_x = max(node.position.get("x", 0.0) for node in nodes)
    min_y = min(node.position.get("y", 0.0) for node in nodes)
    return {"x": float(max_x + 420), "y": float(min_y)}


def _repair_version_child_nodes(canvas: CanvasDetailResponse) -> dict[str, list[CanvasNodeResponse]]:
    repair_nodes = [node for node in canvas.nodes if node.type == "repair_version" and node.payload.get("batch_id")]
    node_by_id = {node.id: node for node in repair_nodes}
    node_by_batch_id = {str(node.payload.get("batch_id")): node for node in repair_nodes}
    children: dict[str, list[CanvasNodeResponse]] = {}
    seen_edges: set[tuple[str, str]] = set()
    for node in repair_nodes:
        parent_batch_id = str(node.payload.get("repair_parent_batch_id") or "")
        if parent_batch_id and parent_batch_id in node_by_batch_id:
            edge_key = (parent_batch_id, node.id)
            if edge_key not in seen_edges:
                children.setdefault(parent_batch_id, []).append(node)
                seen_edges.add(edge_key)
    for edge in canvas.edges:
        if edge.type != "repair_version_child":
            continue
        source = node_by_id.get(edge.source_node_id)
        target = node_by_id.get(edge.target_node_id)
        if source is None or target is None:
            continue
        parent_batch_id = str(source.payload.get("batch_id") or "")
        edge_key = (parent_batch_id, target.id)
        if parent_batch_id and edge_key not in seen_edges:
            children.setdefault(parent_batch_id, []).append(target)
            seen_edges.add(edge_key)
    return children


def _archived_repair_governed_node_ids(canvas: CanvasDetailResponse) -> set[str]:
    archived_repair_nodes = [node for node in canvas.nodes if node.type == "repair_version" and node.payload.get("status") == "archived"]
    archived_version_node_ids: set[str] = set()
    archived_batch_ids: set[str] = set()
    for node in archived_repair_nodes:
        for version_node in [node, *_repair_version_descendant_nodes(canvas, node)]:
            archived_version_node_ids.add(version_node.id)
            batch_id = str(version_node.payload.get("batch_id") or "")
            if batch_id:
                archived_batch_ids.add(batch_id)
    governed_ids = set(archived_version_node_ids)
    for node in canvas.nodes:
        batch_id = str(node.payload.get("batch_id") or "")
        parent_batch_id = str(node.payload.get("repair_parent_batch_id") or "")
        if batch_id in archived_batch_ids or parent_batch_id in archived_batch_ids:
            governed_ids.add(node.id)
    downstream_by_source: dict[str, list[str]] = {}
    for edge in canvas.edges:
        downstream_by_source.setdefault(edge.source_node_id, []).append(edge.target_node_id)
    queue = list(governed_ids)
    while queue:
        source_id = queue.pop(0)
        for target_id in downstream_by_source.get(source_id, []):
            if target_id in governed_ids:
                continue
            governed_ids.add(target_id)
            queue.append(target_id)
    return governed_ids


def _repair_version_descendant_nodes(canvas: CanvasDetailResponse, node: CanvasNodeResponse) -> list[CanvasNodeResponse]:
    children_by_batch_id = _repair_version_child_nodes(canvas)
    descendants: list[CanvasNodeResponse] = []
    queue = list(children_by_batch_id.get(str(node.payload.get("batch_id") or ""), []))
    seen = {node.id}
    while queue:
        child = queue.pop(0)
        if child.id in seen:
            continue
        seen.add(child.id)
        descendants.append(child)
        queue.extend(children_by_batch_id.get(str(child.payload.get("batch_id") or ""), []))
    return descendants


def _repair_version_ancestor_nodes(canvas: CanvasDetailResponse, node: CanvasNodeResponse) -> list[CanvasNodeResponse]:
    node_by_batch_id = {str(item.payload.get("batch_id")): item for item in canvas.nodes if item.type == "repair_version" and item.payload.get("batch_id")}
    ancestors: list[CanvasNodeResponse] = []
    seen = {node.id}
    parent_batch_id = str(node.payload.get("repair_parent_batch_id") or "")
    while parent_batch_id:
        parent = node_by_batch_id.get(parent_batch_id)
        if parent is None or parent.id in seen:
            break
        seen.add(parent.id)
        ancestors.insert(0, parent)
        parent_batch_id = str(parent.payload.get("repair_parent_batch_id") or "")
    return ancestors


def _branch_audit_payload(node: CanvasNodeResponse, operation: str, next_status: str | None, reason: str, is_primary_path: bool | None = None) -> dict[str, object]:
    current_status = str(node.payload.get("status") or "active")
    target_status = next_status or current_status
    audit_entry: dict[str, object] = {
        "operation": operation,
        "from_status": current_status,
        "to_status": target_status,
        "at": datetime.now(timezone.utc).isoformat(),
    }
    if reason:
        audit_entry["reason"] = reason[:500]
    audit_trail = [item for item in node.payload.get("branch_audit_trail") or [] if isinstance(item, dict)]
    updated_payload: dict[str, object] = {**node.payload, "status": target_status, "branch_audit_trail": [*audit_trail, audit_entry][-12:]}
    if is_primary_path is not None:
        updated_payload["is_primary_path"] = is_primary_path
    if target_status == "archived":
        updated_payload["is_primary_path"] = False
    return updated_payload


def _update_repair_version_payloads(repository: CanvasRepository, owner_id: str, canvas_id: str, payloads_by_node_id: dict[str, dict[str, object]]) -> CanvasNodeListResponse:
    updated = repository.update_node_payloads(owner_id, canvas_id, payloads_by_node_id)
    if updated is None:
        raise HTTPException(status_code=404, detail="Node not found")
    return CanvasNodeListResponse(nodes=updated)


@router.post("/api/canvases/{canvas_id}/repair-versions/{node_id}/status", response_model=CanvasNodeListResponse)
def set_repair_version_status(
    canvas_id: str,
    node_id: str,
    request: CanvasRepairVersionStatusRequest,
    user: AuthUser = Depends(require_current_user),
    repository: CanvasRepository = Depends(get_canvas_repository),
) -> CanvasNodeListResponse:
    canvas = repository.get_canvas(user.id, canvas_id)
    if canvas is None:
        raise HTTPException(status_code=404, detail="Canvas not found")
    node = next((item for item in canvas.nodes if item.id == node_id), None)
    if node is None:
        raise HTTPException(status_code=404, detail="Node not found")
    if node.type != "repair_version":
        raise HTTPException(status_code=422, detail="Only repair_version nodes support branch status operations")
    target_nodes = [node, *_repair_version_descendant_nodes(canvas, node)] if request.include_descendants else [node]
    if request.status == "active" and any(item.payload.get("status") == "archived" for item in _repair_version_ancestor_nodes(canvas, node)):
        raise HTTPException(status_code=422, detail="Restore the archived ancestor branch before restoring this repair version")
    operation = "restore" if request.status == "active" else "archive"
    payloads_by_node_id = {
        item.id: _branch_audit_payload(item, operation, request.status, request.reason)
        for item in target_nodes
        if str(item.payload.get("status") or "active") != request.status
    }
    if not payloads_by_node_id:
        return CanvasNodeListResponse(nodes=target_nodes)
    try:
        updated = repository.update_node_payloads_and_create_branch_operations(
            user.id,
            canvas_id,
            payloads_by_node_id,
            [
                {
                    "operation": operation,
                    "reason": request.reason,
                    "scope": "subtree" if request.include_descendants else "single",
                    "target_node_id": node.id,
                    "affected_node_ids": list(payloads_by_node_id),
                    "payload": {"status": request.status, "include_descendants": request.include_descendants},
                }
            ],
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if updated is None:
        raise HTTPException(status_code=404, detail="Node not found")
    return CanvasNodeListResponse(nodes=updated)


@router.post("/api/canvases/{canvas_id}/repair-versions/{node_id}/pin", response_model=CanvasNodeListResponse)
def pin_repair_version_path(
    canvas_id: str,
    node_id: str,
    request: CanvasRepairVersionPinRequest,
    user: AuthUser = Depends(require_current_user),
    repository: CanvasRepository = Depends(get_canvas_repository),
) -> CanvasNodeListResponse:
    canvas = repository.get_canvas(user.id, canvas_id)
    if canvas is None:
        raise HTTPException(status_code=404, detail="Canvas not found")
    node = next((item for item in canvas.nodes if item.id == node_id), None)
    if node is None:
        raise HTTPException(status_code=404, detail="Node not found")
    if node.type != "repair_version":
        raise HTTPException(status_code=422, detail="Only repair_version nodes support production path pinning")
    path_nodes = [*_repair_version_ancestor_nodes(canvas, node), node]
    if any(str(item.payload.get("status") or "active") != "active" for item in path_nodes):
        raise HTTPException(status_code=422, detail="Pinned production path must have only active ancestors")
    repair_nodes = [item for item in canvas.nodes if item.type == "repair_version"]
    payloads_by_node_id: dict[str, dict[str, object]] = {}
    for item in repair_nodes:
        is_target = item.id == node.id
        if is_target:
            payloads_by_node_id[item.id] = _branch_audit_payload(item, "pin", None, request.reason, True)
        elif item.payload.get("is_primary_path"):
            payloads_by_node_id[item.id] = _branch_audit_payload(item, "unpin", None, request.reason, False)
    if not payloads_by_node_id:
        return CanvasNodeListResponse(nodes=[node])
    path_node_ids = [item.id for item in path_nodes]
    affected_node_ids = list(dict.fromkeys([*path_node_ids, *payloads_by_node_id]))
    unpinned_node_ids = [item.id for item in repair_nodes if item.id != node.id and item.payload.get("is_primary_path")]
    branch_operations = [
        {
            "operation": "pin",
            "reason": request.reason,
            "scope": "path",
            "target_node_id": node.id,
            "affected_node_ids": affected_node_ids,
            "payload": {"pinned_node_id": node.id, "path_node_ids": path_node_ids, "unpin_count": len(unpinned_node_ids)},
        },
        *[
            {
                "operation": "unpin",
                "reason": request.reason,
                "scope": "single",
                "target_node_id": unpinned_node_id,
                "affected_node_ids": [unpinned_node_id],
                "payload": {"pinned_node_id": node.id, "path_node_ids": path_node_ids},
            }
            for unpinned_node_id in unpinned_node_ids
        ],
    ]
    try:
        updated = repository.update_node_payloads_and_create_branch_operations(user.id, canvas_id, payloads_by_node_id, branch_operations)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if updated is None:
        raise HTTPException(status_code=404, detail="Node not found")
    return CanvasNodeListResponse(nodes=updated)


@router.post("/api/canvases/{canvas_id}/repair-versions/{node_id}/unpin", response_model=CanvasNodeListResponse)
def unpin_repair_version_path(
    canvas_id: str,
    node_id: str,
    request: CanvasRepairVersionPinRequest,
    user: AuthUser = Depends(require_current_user),
    repository: CanvasRepository = Depends(get_canvas_repository),
) -> CanvasNodeListResponse:
    canvas = repository.get_canvas(user.id, canvas_id)
    if canvas is None:
        raise HTTPException(status_code=404, detail="Canvas not found")
    node = next((item for item in canvas.nodes if item.id == node_id), None)
    if node is None:
        raise HTTPException(status_code=404, detail="Node not found")
    if node.type != "repair_version":
        raise HTTPException(status_code=422, detail="Only repair_version nodes support production path unpinning")
    if not node.payload.get("is_primary_path"):
        return CanvasNodeListResponse(nodes=[node])
    payloads_by_node_id = {node.id: _branch_audit_payload(node, "unpin", None, request.reason, False)}
    try:
        updated = repository.update_node_payloads_and_create_branch_operations(
            user.id,
            canvas_id,
            payloads_by_node_id,
            [
                {
                    "operation": "unpin",
                    "reason": request.reason,
                    "scope": "single",
                    "target_node_id": node.id,
                    "affected_node_ids": [node.id],
                    "payload": {"pinned_node_id": node.id, "path_node_ids": [node.id]},
                }
            ],
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if updated is None:
        raise HTTPException(status_code=404, detail="Node not found")
    return CanvasNodeListResponse(nodes=updated)


@router.post("/api/canvases/{canvas_id}/media/{node_id}/approval", response_model=CanvasNodeResponse)
def set_media_approval(
    canvas_id: str,
    node_id: str,
    request: CanvasMediaApprovalRequest,
    user: AuthUser = Depends(require_current_user),
    repository: CanvasRepository = Depends(get_canvas_repository),
) -> CanvasNodeResponse:
    canvas = repository.get_canvas(user.id, canvas_id)
    if canvas is None:
        raise HTTPException(status_code=404, detail="Canvas not found")
    existing = next((item for item in canvas.nodes if item.id == node_id), None)
    if existing is None:
        raise HTTPException(status_code=404, detail="Node not found")
    if existing.type not in {"edited_image", "generated_video"}:
        raise HTTPException(status_code=422, detail="Only edited images and generated videos can be approved as production media")
    if request.approved and existing.id in _archived_repair_governed_node_ids(canvas):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Archived repair branches cannot be approved as production media")
    from_status = str(existing.payload.get("approval_status") or "draft")
    to_status = "approved" if request.approved else "draft"
    if from_status == to_status:
        return existing
    if not request.reason:
        raise HTTPException(status_code=422, detail="Approval reason is required")
    approved_at = datetime.now(timezone.utc).isoformat() if request.approved else ""
    payload = {
        **existing.payload,
        "approval_status": to_status,
        "approved_at": approved_at,
        "approval_reason": request.reason,
    }
    try:
        node = repository.update_node_payload_and_create_branch_operation(
            user.id,
            canvas_id,
            node_id,
            payload,
            "approve" if request.approved else "revoke",
            request.reason,
            "single",
            node_id,
            [node_id],
            {
                "node_type": existing.type,
                "asset_id": payload.get("asset_id"),
                "task_id": payload.get("task_id"),
                "from_status": from_status,
                "to_status": to_status,
                "approved_at": approved_at,
                "source_asset_id": payload.get("source_asset_id"),
                "source_asset_ids": list(payload.get("source_asset_ids") or [])[:8],
                "mask_asset_id": payload.get("mask_asset_id"),
                "action_type": payload.get("action_type"),
            },
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if node is None:
        raise HTTPException(status_code=404, detail="Node not found")
    return node


@router.patch("/api/canvases/{canvas_id}/nodes/{node_id}", response_model=CanvasNodeResponse)
def update_node(
    canvas_id: str,
    node_id: str,
    request: CanvasNodeUpdateRequest,
    user: AuthUser = Depends(require_current_user),
    repository: CanvasRepository = Depends(get_canvas_repository),
) -> CanvasNodeResponse:
    canvas = repository.get_canvas(user.id, canvas_id)
    if canvas is None:
        raise HTTPException(status_code=404, detail="Canvas not found")
    existing = next((item for item in canvas.nodes if item.id == node_id), None)
    if existing is None:
        raise HTTPException(status_code=404, detail="Node not found")
    updates = request.model_dump(exclude_unset=True)
    if existing.type == "repair_version" and "payload" in updates:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Repair version payload is branch-managed; use explicit branch operations")
    if existing.type in {"selected_image", "edited_image", "generated_image", "generated_video"} and "payload" in updates:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Production media payload is server-managed")
    if "payload" in updates and updates["payload"] is not None:
        _reject_client_managed_payload_impersonation(existing.type, updates["payload"])
    node = repository.update_node(user.id, canvas_id, node_id, updates)
    if node is None:
        raise HTTPException(status_code=404, detail="Node not found")
    return node


@router.delete("/api/canvases/{canvas_id}/nodes/{node_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_node(
    canvas_id: str,
    node_id: str,
    user: AuthUser = Depends(require_current_user),
    repository: CanvasRepository = Depends(get_canvas_repository),
) -> Response:
    canvas = repository.get_canvas(user.id, canvas_id)
    if canvas is None:
        raise HTTPException(status_code=404, detail="Canvas not found")
    node = next((item for item in canvas.nodes if item.id == node_id), None)
    if node is None:
        raise HTTPException(status_code=404, detail="Node not found")
    if node.type == "selected_image":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Selected image nodes are server-managed; update the candidate status instead")
    if node.type in {"edited_image", "generated_image", "generated_video"}:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Production media nodes are server-managed and cannot be deleted")
    if _is_server_managed_lineage_source_node(canvas, node.id):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Nodes with server-managed production lineage cannot be deleted")
    if node.id in _locked_repair_branch_node_ids(canvas):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Repair branch nodes cannot be deleted while protecting a selected image")
    if node.type == "repair_version":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Repair version nodes are archive-only and cannot be deleted")
    if not repository.delete_node(user.id, canvas_id, node_id):
        raise HTTPException(status_code=404, detail="Node not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/api/canvases/{canvas_id}/edges", response_model=CanvasEdgeResponse, status_code=status.HTTP_201_CREATED)
def create_edge(
    canvas_id: str,
    request: CanvasEdgeCreateRequest,
    user: AuthUser = Depends(require_current_user),
    repository: CanvasRepository = Depends(get_canvas_repository),
) -> CanvasEdgeResponse:
    canvas = repository.get_canvas(user.id, canvas_id)
    if canvas is None:
        raise HTTPException(status_code=404, detail="Canvas not found")
    if request.type in {"repair_version_source", "repair_version_child"}:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Repair version edges are server-managed; use explicit repair version materialization")
    if request.type in {"selected_candidate", "image_edit", "video_from_image", "video_remix"} or _is_server_managed_lineage_edge_request(canvas, request.type, request.source_node_id, request.target_node_id):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Production media lineage edges are server-managed")
    try:
        edge = repository.create_edge(user.id, canvas_id, request.source_node_id, request.target_node_id, request.type, request.payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if edge is None:
        raise HTTPException(status_code=404, detail="Canvas not found")
    return edge


@router.delete("/api/canvases/{canvas_id}/edges/{edge_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_edge(
    canvas_id: str,
    edge_id: str,
    user: AuthUser = Depends(require_current_user),
    repository: CanvasRepository = Depends(get_canvas_repository),
) -> Response:
    canvas = repository.get_canvas(user.id, canvas_id)
    if canvas is None:
        raise HTTPException(status_code=404, detail="Canvas not found")
    edge = next((item for item in canvas.edges if item.id == edge_id), None)
    if edge is None:
        raise HTTPException(status_code=404, detail="Edge not found")
    if _is_locked_repair_edge(canvas, edge):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Repair branch edges cannot be deleted while protecting a selected image")
    if _is_production_media_lineage_edge(canvas, edge) or edge.type == "selected_candidate" or _is_server_managed_lineage_edge_request(canvas, edge.type, edge.source_node_id, edge.target_node_id):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Production media lineage edges cannot be deleted")
    if edge.type in {"repair_version_source", "repair_version_child"}:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Repair version edges are archive-only and cannot be deleted")
    if not repository.delete_edge(user.id, canvas_id, edge_id):
        raise HTTPException(status_code=404, detail="Edge not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)
