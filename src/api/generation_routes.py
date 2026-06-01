import asyncio
import base64
import logging
from contextlib import suppress
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from pydantic import BaseModel, Field, model_validator

from src.api.image_routes import GenerateRequest, require_high_cost_access
from src.config import Settings, get_settings
from src.dependencies import get_billing_service, get_pipeline, get_project_repository, get_prompt_skill_pipeline, get_video_router, require_current_user
from src.models.auth import AuthUser
from src.models.project import AssetKind, ProjectTaskResponse, TaskKind
from src.models.prompt_skill import ImageActionType, ImageSource, PromptSkillRequest
from src.models.task import TaskStatus
from src.models.video import VideoGenerateRequest
from src.services.billing_service import BillingService
from src.services.pipeline import ImageGenerationPipeline
from src.services.prompt_skill_pipeline import PromptSkillPipeline
from src.services.project_repository import ProjectRepository
from src.services.video_router import VideoRouter, validate_video_params


router = APIRouter(prefix="/api", tags=["generation"])
logger = logging.getLogger(__name__)
PROJECT_IMAGE_FAILURE_MESSAGE = "图片生成失败，请稍后重试或检查模型配置。"
PROJECT_VIDEO_FAILURE_MESSAGE = "视频生成失败，请稍后重试或检查模型配置。"
TASK_HEARTBEAT_INTERVAL_SECONDS = 60


def _billing_error(exc: ValueError) -> HTTPException:
    detail = str(exc)
    status_code = status.HTTP_429_TOO_MANY_REQUESTS if detail == "Daily quota exceeded" else status.HTTP_402_PAYMENT_REQUIRED
    return HTTPException(status_code=status_code, detail=detail)


class ImageEditGenerateRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=12000)
    model: str
    source_image_asset_ids: list[str] = Field(min_length=1, max_length=8)
    mask_asset_id: str | None = None
    action_type: ImageActionType = ImageActionType.EDIT
    threshold: float | None = Field(default=None, ge=0.0, le=10.0)
    max_iter: int | None = Field(default=None, ge=1, le=10)
    params: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_action(self) -> "ImageEditGenerateRequest":
        if self.action_type == ImageActionType.TEXT_TO_IMAGE:
            raise ValueError("image-edit tasks require an image-based action_type")
        if self.action_type == ImageActionType.INPAINT and self.mask_asset_id is None:
            raise ValueError("mask_asset_id is required for inpaint action_type")
        if self.action_type != ImageActionType.INPAINT and self.mask_asset_id is not None:
            raise ValueError("mask_asset_id is only supported for inpaint action_type")
        if self.mask_asset_id and self.mask_asset_id in self.source_image_asset_ids:
            raise ValueError("mask_asset_id must be distinct from source_image_asset_ids")
        return self


@router.post("/projects/{project_id}/generate/image", status_code=status.HTTP_202_ACCEPTED)
async def generate_project_image(
    project_id: str,
    request: GenerateRequest,
    background_tasks: BackgroundTasks,
    user: AuthUser = Depends(require_current_user),
    _access_identity: str = Depends(require_high_cost_access),
    repository: ProjectRepository = Depends(get_project_repository),
    pipeline: ImageGenerationPipeline = Depends(get_pipeline),
    billing: BillingService = Depends(get_billing_service),
    settings: Settings = Depends(get_settings),
) -> dict[str, str]:
    if await asyncio.to_thread(repository.get_project, user.id, project_id) is None:
        raise HTTPException(status_code=404, detail="Project not found")
    try:
        charge = await asyncio.to_thread(billing.charge_for_action, user.id, project_id, "project_image", {"source": "project_image"})
    except ValueError as exc:
        raise _billing_error(exc) from exc

    input_payload = {**request.model_dump(mode="json"), "credit_transaction_id": charge.id}
    try:
        task = await asyncio.to_thread(
            repository.create_task,
            user.id,
            project_id,
            TaskKind.image,
            input_payload,
            charge.amount,
            charge.amount,
        )
        await asyncio.to_thread(billing.attach_task, user.id, charge.id, task.task_id)
    except Exception:
        await asyncio.to_thread(billing.refund_failed_task, user.id, charge.id, None, "task creation failed")
        raise
    background_tasks.add_task(_run_image_task, user.id, task.task_id, request, charge.id, repository, pipeline, billing, settings)
    return {"task_id": task.task_id, "status": task.status}


@router.post("/projects/{project_id}/generate/image-edit", status_code=status.HTTP_202_ACCEPTED)
async def generate_project_image_edit(
    project_id: str,
    request: ImageEditGenerateRequest,
    background_tasks: BackgroundTasks,
    user: AuthUser = Depends(require_current_user),
    _access_identity: str = Depends(require_high_cost_access),
    repository: ProjectRepository = Depends(get_project_repository),
    pipeline: PromptSkillPipeline = Depends(get_prompt_skill_pipeline),
    billing: BillingService = Depends(get_billing_service),
    settings: Settings = Depends(get_settings),
) -> dict[str, str]:
    if await asyncio.to_thread(repository.get_project, user.id, project_id) is None:
        raise HTTPException(status_code=404, detail="Project not found")
    prompt_request = await asyncio.to_thread(_project_image_edit_prompt_request, user.id, project_id, request, repository, settings)
    try:
        charge = await asyncio.to_thread(billing.charge_for_action, user.id, project_id, "project_image_edit", {"source": "project_image_edit"})
    except ValueError as exc:
        raise _billing_error(exc) from exc

    input_payload = {**request.model_dump(mode="json"), "credit_transaction_id": charge.id}
    try:
        task = await asyncio.to_thread(
            repository.create_task,
            user.id,
            project_id,
            TaskKind.image_edit,
            input_payload,
            charge.amount,
            charge.amount,
        )
        await asyncio.to_thread(billing.attach_task, user.id, charge.id, task.task_id)
    except Exception:
        await asyncio.to_thread(billing.refund_failed_task, user.id, charge.id, None, "task creation failed")
        raise
    background_tasks.add_task(
        _run_image_edit_task,
        user.id,
        task.task_id,
        request.model,
        prompt_request,
        request.threshold,
        request.max_iter,
        charge.id,
        repository,
        pipeline,
        billing,
        settings,
    )
    return {"task_id": task.task_id, "status": task.status}


@router.post("/projects/{project_id}/generate/video", status_code=status.HTTP_202_ACCEPTED)
async def generate_project_video(
    project_id: str,
    request: VideoGenerateRequest,
    background_tasks: BackgroundTasks,
    user: AuthUser = Depends(require_current_user),
    _access_identity: str = Depends(require_high_cost_access),
    repository: ProjectRepository = Depends(get_project_repository),
    video_router: VideoRouter = Depends(get_video_router),
    billing: BillingService = Depends(get_billing_service),
    settings: Settings = Depends(get_settings),
) -> dict[str, str]:
    if await asyncio.to_thread(repository.get_project, user.id, project_id) is None:
        raise HTTPException(status_code=404, detail="Project not found")
    execution_request = await asyncio.to_thread(_resolve_video_source, user.id, project_id, request, repository, settings)
    _validate_direct_video_source(execution_request)
    _validate_video_params(execution_request)
    kind = TaskKind.image_to_video if execution_request.source_image_url else TaskKind.text_to_video
    try:
        charge = await asyncio.to_thread(billing.charge_for_action, user.id, project_id, "project_video", {"source": "project_video"})
    except ValueError as exc:
        raise _billing_error(exc) from exc

    input_payload = {**request.model_dump(mode="json"), "credit_transaction_id": charge.id}
    try:
        task = await asyncio.to_thread(
            repository.create_task,
            user.id,
            project_id,
            kind,
            input_payload,
            charge.amount,
            charge.amount,
        )
        await asyncio.to_thread(billing.attach_task, user.id, charge.id, task.task_id)
    except Exception:
        await asyncio.to_thread(billing.refund_failed_task, user.id, charge.id, None, "task creation failed")
        raise
    background_tasks.add_task(_run_video_task, user.id, task.task_id, execution_request, charge.id, repository, video_router, billing)
    return {"task_id": task.task_id, "status": task.status}


def _resolve_video_source(
    owner_id: str,
    project_id: str,
    request: VideoGenerateRequest,
    repository: ProjectRepository,
    settings: Settings,
) -> VideoGenerateRequest:
    if not request.source_image_asset_id:
        return request
    asset = repository.get_asset(owner_id, project_id, request.source_image_asset_id)
    if asset is None or asset.kind != AssetKind.image:
        raise HTTPException(status_code=404, detail="Source image asset not found")
    return request.model_copy(update={"source_image_url": _provider_image_source(asset.url, asset.media_type, settings)})


def _provider_image_source(url: str, media_type: str, settings: Settings) -> str:
    if url.startswith("mock://") or _is_raster_data_url(url):
        return url
    if url.startswith(("http://", "https://", "data:")):
        raise HTTPException(status_code=400, detail="Source image asset is not provider-compatible")
    if not url.startswith("/uploads/image-optimizer/"):
        raise HTTPException(status_code=400, detail="Source image asset is not provider-compatible")
    path = settings.asset_upload_dir / "image-optimizer" / Path(url).name
    try:
        payload = path.read_bytes()
    except OSError as exc:
        raise HTTPException(status_code=400, detail="Source image asset is not available") from exc
    if _image_extension(media_type) is None:
        raise HTTPException(status_code=400, detail="Source image media type is not supported")
    return f"data:{media_type};base64,{base64.b64encode(payload).decode('ascii')}"


def _is_raster_data_url(url: str) -> bool:
    return url.startswith(("data:image/png;base64,", "data:image/jpeg;base64,", "data:image/jpg;base64,", "data:image/webp;base64,"))


def _validate_direct_video_source(request: VideoGenerateRequest) -> None:
    if request.source_image_asset_id or not request.source_image_url:
        return
    if not request.source_image_url.startswith("mock://"):
        raise HTTPException(status_code=400, detail="Use a project image asset as the video source")


def _validate_video_params(request: VideoGenerateRequest) -> None:
    try:
        validate_video_params(request.params)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _project_image_edit_prompt_request(
    owner_id: str,
    project_id: str,
    request: ImageEditGenerateRequest,
    repository: ProjectRepository,
    settings: Settings,
) -> PromptSkillRequest:
    source_images = [_asset_image_source(owner_id, project_id, asset_id, repository, settings) for asset_id in request.source_image_asset_ids]
    mask_image = _asset_image_source(owner_id, project_id, request.mask_asset_id, repository, settings) if request.mask_asset_id else None
    return PromptSkillRequest(
        prompt=request.prompt,
        action_type=request.action_type,
        source_images=source_images,
        mask_image=mask_image,
        params={**request.params, "response_format": "b64_json"},
    )


def _asset_image_source(
    owner_id: str,
    project_id: str,
    asset_id: str,
    repository: ProjectRepository,
    settings: Settings,
) -> ImageSource:
    asset = repository.get_asset(owner_id, project_id, asset_id)
    if asset is None or asset.kind != AssetKind.image:
        raise HTTPException(status_code=404, detail="Source image asset not found")
    return ImageSource(
        asset_id=asset.id,
        url=_provider_image_source(asset.url, asset.media_type, settings),
        media_type=asset.media_type,
        role="source",
        metadata={"project_id": project_id, "asset_url": asset.url},
    )


@router.get("/tasks/{task_id}", response_model=ProjectTaskResponse)
def get_task(
    task_id: str,
    user: AuthUser = Depends(require_current_user),
    repository: ProjectRepository = Depends(get_project_repository),
) -> ProjectTaskResponse:
    task = repository.get_task(user.id, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return task


@router.get("/tasks/{task_id}/history")
def get_task_history(
    task_id: str,
    user: AuthUser = Depends(require_current_user),
    repository: ProjectRepository = Depends(get_project_repository),
) -> dict[str, Any]:
    history = repository.task_history(user.id, task_id)
    if history is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return {"task_id": task_id, "history": history}


async def _task_heartbeat(repository: ProjectRepository, task_id: str) -> None:
    while True:
        await asyncio.sleep(TASK_HEARTBEAT_INTERVAL_SECONDS)
        try:
            await asyncio.to_thread(repository.touch_task, task_id)
        except Exception:
            logger.warning("Project task heartbeat failed", extra={"task_id": task_id}, exc_info=True)


async def _stop_task_heartbeat(heartbeat_task: asyncio.Task[None]) -> None:
    heartbeat_task.cancel()
    with suppress(asyncio.CancelledError):
        await heartbeat_task


async def _run_image_edit_task(
    owner_id: str,
    task_id: str,
    model_id: str,
    request: PromptSkillRequest,
    threshold: float | None,
    max_iter: int | None,
    credit_transaction_id: str,
    repository: ProjectRepository,
    pipeline: PromptSkillPipeline,
    billing: BillingService,
    settings: Settings,
) -> None:
    await asyncio.to_thread(repository.set_task_running, task_id)
    task = await asyncio.to_thread(repository.get_task, owner_id, task_id)
    if task is None or task.status != TaskStatus.running:
        return
    heartbeat_task = asyncio.create_task(_task_heartbeat(repository, task_id))
    image_url: str | None = None
    try:
        result, prompt_skill = await pipeline.run(request, model_id=model_id, threshold=threshold, max_iter=max_iter)
        image_url = await asyncio.to_thread(_persist_generated_image_url, result.image.b64_json, result.image.url, result.image.metadata.get("media_type", "image/png"), task_id, settings)
        payload = {
            "image_url": image_url,
            "image_b64_json": result.image.b64_json,
            "image_media_type": result.image.metadata.get("media_type", "image/png"),
            "final_prompt": result.final_prompt,
            "score": result.score,
            "iterations": result.iterations,
            "prompt_report": result.prompt_report.model_dump(mode="json"),
            "optimization_trace": result.optimization_trace.model_dump(mode="json") if result.optimization_trace else None,
            "prompt_skill": prompt_skill.model_dump(mode="json"),
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
        succeeded = await asyncio.to_thread(repository.set_task_succeeded, task_id, payload, history)
        if not succeeded:
            await asyncio.to_thread(_delete_generated_image_url, image_url, task_id, settings)
            return
    except Exception:
        if image_url is not None:
            await asyncio.to_thread(_delete_generated_image_url, image_url, task_id, settings)
        logger.exception("Project image edit failed", extra={"task_id": task_id})
        await asyncio.to_thread(billing.refund_failed_task, owner_id, credit_transaction_id, task_id, "failed task")
        await asyncio.to_thread(repository.set_task_failed, task_id, PROJECT_IMAGE_FAILURE_MESSAGE)
        return
    finally:
        await _stop_task_heartbeat(heartbeat_task)
    try:
        await asyncio.to_thread(
            repository.create_asset,
            owner_id,
            task.project_id,
            AssetKind.image,
            payload["image_url"],
            payload["image_media_type"],
            {"task_id": task_id, "source": "image_edit", "source_asset_ids": [source.asset_id for source in request.source_images]},
        )
    except Exception:
        logger.exception("Project image edit asset persistence failed", extra={"task_id": task_id})


async def _run_image_task(
    owner_id: str,
    task_id: str,
    request: GenerateRequest,
    credit_transaction_id: str,
    repository: ProjectRepository,
    pipeline: ImageGenerationPipeline,
    billing: BillingService,
    settings: Settings,
) -> None:
    await asyncio.to_thread(repository.set_task_running, task_id)
    task = await asyncio.to_thread(repository.get_task, owner_id, task_id)
    if task is None or task.status != TaskStatus.running:
        return
    heartbeat_task = asyncio.create_task(_task_heartbeat(repository, task_id))
    image_url: str | None = None
    try:
        result = await pipeline.run(
            user_input=request.input,
            model_id=request.model,
            threshold=request.threshold,
            max_iter=request.max_iter,
            params={**request.params, "response_format": "b64_json"},
            skip_prompt_evaluation=request.skip_prompt_evaluation,
        )
        image_url = await asyncio.to_thread(_persist_generated_image_url, result.image.b64_json, result.image.url, result.image.metadata.get("media_type", "image/png"), task_id, settings)
        payload = {
            "image_url": image_url,
            "image_b64_json": result.image.b64_json,
            "image_media_type": result.image.metadata.get("media_type", "image/png"),
            "final_prompt": result.final_prompt,
            "score": result.score,
            "iterations": result.iterations,
            "prompt_report": result.prompt_report.model_dump(mode="json"),
            "optimization_trace": result.optimization_trace.model_dump(mode="json") if result.optimization_trace else None,
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
        succeeded = await asyncio.to_thread(repository.set_task_succeeded, task_id, payload, history)
        if not succeeded:
            await asyncio.to_thread(_delete_generated_image_url, image_url, task_id, settings)
            return
    except Exception:
        if image_url is not None:
            await asyncio.to_thread(_delete_generated_image_url, image_url, task_id, settings)
        logger.exception("Project image generation failed", extra={"task_id": task_id})
        await asyncio.to_thread(billing.refund_failed_task, owner_id, credit_transaction_id, task_id, "failed task")
        await asyncio.to_thread(repository.set_task_failed, task_id, PROJECT_IMAGE_FAILURE_MESSAGE)
        return
    finally:
        await _stop_task_heartbeat(heartbeat_task)

    try:
        await asyncio.to_thread(repository.create_asset, owner_id, task.project_id, AssetKind.image, payload["image_url"], payload["image_media_type"], {"task_id": task_id})
    except Exception:
        logger.exception("Project image asset persistence failed", extra={"task_id": task_id})


def _persist_generated_image_url(b64_json: str | None, image_url: str | None, media_type: str, task_id: str, settings: Settings) -> str:
    if not b64_json:
        if image_url and image_url.startswith("mock://"):
            return image_url
        raise RuntimeError("provider did not return durable image data")
    extension = _image_extension(media_type)
    if extension is None:
        raise RuntimeError("provider returned unsupported image media type")
    if len(b64_json) > ((settings.asset_upload_max_bytes + 2) // 3) * 4 + 4:
        raise RuntimeError("provider returned image data above the size limit")
    payload = base64.b64decode(b64_json, validate=True)
    if len(payload) > settings.asset_upload_max_bytes:
        raise RuntimeError("provider returned image data above the size limit")
    if not _matches_image_signature(payload, media_type):
        raise RuntimeError("provider returned image data that does not match the media type")
    upload_dir = settings.asset_upload_dir / "image-optimizer"
    upload_dir.mkdir(parents=True, exist_ok=True)
    filename = f"generated-{task_id}-{uuid4().hex}{extension}"
    (upload_dir / filename).write_bytes(payload)
    return f"/uploads/image-optimizer/{filename}"


def delete_generated_image_files_for_task(settings: Settings, task_id: str) -> None:
    upload_dir = settings.asset_upload_dir / "image-optimizer"
    try:
        paths = tuple(upload_dir.iterdir()) if upload_dir.is_dir() else ()
    except OSError:
        logger.warning("Failed to inspect generated image directory", extra={"path": str(upload_dir)}, exc_info=True)
        return
    for path in paths:
        try:
            if path.is_file() and _generated_image_filename_belongs_to_task(path.name, task_id):
                _delete_generated_image_file(path)
        except OSError:
            logger.warning("Failed to inspect generated image file", extra={"path": str(path)}, exc_info=True)


def _delete_generated_image_url(image_url: str, task_id: str, settings: Settings) -> None:
    prefix = "/uploads/image-optimizer/"
    if not image_url.startswith(prefix):
        return
    filename = image_url[len(prefix) :]
    if Path(filename).name != filename or not _generated_image_filename_belongs_to_task(filename, task_id):
        return
    _delete_generated_image_file(settings.asset_upload_dir / "image-optimizer" / filename)


def _delete_generated_image_file(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        return
    except OSError:
        logger.warning("Failed to delete generated image file", extra={"path": str(path)}, exc_info=True)


def _generated_image_filename_belongs_to_task(filename: str, task_id: str) -> bool:
    extensions = (".png", ".jpg", ".webp")
    return any(filename == f"generated-{task_id}{extension}" for extension in extensions) or (
        filename.startswith(f"generated-{task_id}-") and filename.endswith(extensions)
    )


def _image_extension(media_type: str) -> str | None:
    return {"image/png": ".png", "image/jpeg": ".jpg", "image/jpg": ".jpg", "image/webp": ".webp"}.get(media_type.lower())


def _matches_image_signature(payload: bytes, media_type: str) -> bool:
    normalized = media_type.lower()
    if normalized == "image/png":
        return payload.startswith(b"\x89PNG\r\n\x1a\n")
    if normalized in {"image/jpeg", "image/jpg"}:
        return payload.startswith(b"\xff\xd8\xff")
    if normalized == "image/webp":
        return len(payload) >= 12 and payload[:4] == b"RIFF" and payload[8:12] == b"WEBP"
    return False


async def _run_video_task(
    owner_id: str,
    task_id: str,
    request: VideoGenerateRequest,
    credit_transaction_id: str,
    repository: ProjectRepository,
    video_router: VideoRouter,
    billing: BillingService,
) -> None:
    await asyncio.to_thread(repository.set_task_running, task_id)
    task = await asyncio.to_thread(repository.get_task, owner_id, task_id)
    if task is None or task.status != TaskStatus.running:
        return
    heartbeat_task = asyncio.create_task(_task_heartbeat(repository, task_id))
    try:
        result = await video_router.generate(request)
        payload = result.model_dump(mode="json")
        succeeded = await asyncio.to_thread(repository.set_task_succeeded, task_id, payload, [])
        if not succeeded:
            return
    except Exception:
        logger.exception("Project video generation failed", extra={"task_id": task_id})
        await asyncio.to_thread(billing.refund_failed_task, owner_id, credit_transaction_id, task_id, "failed task")
        await asyncio.to_thread(repository.set_task_failed, task_id, PROJECT_VIDEO_FAILURE_MESSAGE)
        return
    finally:
        await _stop_task_heartbeat(heartbeat_task)

    try:
        await asyncio.to_thread(repository.create_asset, owner_id, task.project_id, AssetKind.video, result.url, result.media_type, {"task_id": task_id, **result.metadata})
    except Exception:
        logger.exception("Project video asset persistence failed", extra={"task_id": task_id})
