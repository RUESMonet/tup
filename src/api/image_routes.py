import asyncio
import base64
from collections import deque
from email.parser import BytesParser
from email.policy import default
from hmac import compare_digest
import json
import logging
from math import ceil
from pathlib import Path
from time import monotonic
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from starlette.responses import StreamingResponse

from src.agents.optimization_guide import OptimizationGuideBuilder
from src.agents.prompt_draft import PromptDraftAgent
from src.agents.prompt_optimizer import PromptOptimizerAgent
from src.agents.prompt_pattern_library import prompt_pattern_library
from src.agents.quality_reference import QualityReference
from src.agents.visual_evaluator import VisualEvaluator
from src.config import Settings, get_settings
from src.dependencies import get_auth_service, get_effective_settings, get_pipeline, get_prompt_draft_agent, get_prompt_optimizer_agent, get_storage
from src.models.project import AssetKind
from src.services.auth import AuthService
from src.services.model_router import ModelRouter
from src.services.pipeline import ImageGenerationPipeline
from src.services.storage import InMemoryTaskStorage


router = APIRouter(prefix="/api")
logger = logging.getLogger(__name__)
_rate_limit_hits: dict[str, deque[float]] = {}
_rate_limit_lock = asyncio.Lock()

IMAGE_EXTENSIONS = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/webp": ".webp",
}
VIDEO_EXTENSIONS = {
    "video/mp4": ".mp4",
    "video/webm": ".webm",
    "video/quicktime": ".mov",
}
SUPPORTED_MEDIA_EXTENSIONS = {**IMAGE_EXTENSIONS, **VIDEO_EXTENSIONS}
SUPPORTED_UPLOAD_MESSAGE = "Only PNG, JPEG, WebP images and MP4, WebM, MOV videos are supported"
UPLOAD_BODY_OVERHEAD_BYTES = 64 * 1024
POLL_RATE_LIMIT_MULTIPLIER = 20
IMAGE_TASK_FAILURE_MESSAGE = "图片生成失败，请稍后重试或检查模型配置。"
MAX_PROMPT_LENGTH = 12000


class GenerateRequest(BaseModel):
    input: str = Field(min_length=1, max_length=MAX_PROMPT_LENGTH)
    model: str
    threshold: float | None = Field(default=None, ge=0.0, le=10.0)
    max_iter: int | None = Field(default=None, ge=1, le=10)
    params: dict[str, Any] = Field(default_factory=dict)
    skip_prompt_evaluation: bool = False


class GenerateResponse(BaseModel):
    task_id: str
    status: str


class ReferenceAnalyzeRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=MAX_PROMPT_LENGTH)
    defects: list[str] = Field(default_factory=list)


class PromptDraftRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=MAX_PROMPT_LENGTH)


async def require_high_cost_access(
    request: Request,
    settings: Settings = Depends(get_settings),
    auth: AuthService = Depends(get_auth_service),
) -> str:
    identity = _high_cost_identity(request, settings, auth)
    await _enforce_rate_limit(identity, settings)
    return identity


async def require_polling_access(
    request: Request,
    settings: Settings = Depends(get_settings),
    auth: AuthService = Depends(get_auth_service),
) -> str:
    identity = _high_cost_identity(request, settings, auth)
    await _enforce_rate_limit(
        identity,
        settings,
        bucket_scope="poll",
        limit_multiplier=POLL_RATE_LIMIT_MULTIPLIER,
    )
    return identity


@router.post(
    "/generate",
    response_model=GenerateResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def generate(
    req: GenerateRequest,
    storage: InMemoryTaskStorage = Depends(get_storage),
    pipeline: ImageGenerationPipeline = Depends(get_pipeline),
    owner_id: str = Depends(require_high_cost_access),
) -> GenerateResponse:
    task = await storage.create(owner_id)
    asyncio.create_task(_run_task(task.task_id, req, storage, pipeline))
    return GenerateResponse(task_id=task.task_id, status=task.status)


@router.get("/task/{task_id}")
async def get_task(
    task_id: str,
    storage: InMemoryTaskStorage = Depends(get_storage),
    owner_id: str = Depends(require_polling_access),
) -> dict[str, Any]:
    task = await storage.get(task_id)
    if task is None or task.owner_id != owner_id:
        raise HTTPException(status_code=404, detail="Task not found")

    payload = {
        "task_id": task.task_id,
        "status": task.status,
        "created_at": task.created_at,
        "updated_at": task.updated_at,
        "error": task.error,
        "image_url": None,
        "final_prompt": None,
        "score": None,
        "iterations": None,
    }
    if task.result:
        payload.update(
            {
                "image_url": task.result.image.url,
                "image_b64_json": task.result.image.b64_json,
                "image_media_type": task.result.image.metadata.get("media_type", "image/png"),
                "final_prompt": task.result.final_prompt,
                "score": task.result.score,
                "iterations": task.result.iterations,
            }
        )
    return payload


@router.get("/task/{task_id}/history")
async def get_task_history(
    task_id: str,
    storage: InMemoryTaskStorage = Depends(get_storage),
    owner_id: str = Depends(require_polling_access),
) -> dict[str, Any]:
    task = await storage.get(task_id)
    if task is None or task.owner_id != owner_id:
        raise HTTPException(status_code=404, detail="Task not found")
    if task.result is None:
        return {"task_id": task_id, "status": task.status, "history": []}

    return {
        "task_id": task_id,
        "status": task.status,
        "history": [
            {
                "iteration": item.iteration,
                "prompt": item.prompt,
                "score": item.visual_report.total_score if item.visual_report else None,
                "image_url": item.image.url if item.image else None,
                "visual_report": item.visual_report,
            }
            for item in task.result.prompt_history
        ],
    }


@router.get("/models", dependencies=[Depends(require_high_cost_access)])
async def get_models(settings: Settings = Depends(get_effective_settings)) -> dict[str, Any]:
    return {"models": ModelRouter(settings).list_models()}


@router.post("/assets/upload", dependencies=[Depends(require_high_cost_access)])
async def upload_asset(request: Request, settings: Settings = Depends(get_settings)) -> dict[str, Any]:
    content_type = request.headers.get("content-type", "")
    if "multipart/form-data" not in content_type or "boundary=" not in content_type:
        raise HTTPException(status_code=400, detail="Expected multipart form-data with a file field")

    body = await _read_limited_body(request, settings.asset_upload_max_bytes + UPLOAD_BODY_OVERHEAD_BYTES)
    file_payload, filename, media_type = _extract_upload_file(body, content_type)
    if not file_payload:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")
    if len(file_payload) > settings.asset_upload_max_bytes:
        raise HTTPException(status_code=400, detail="Uploaded file exceeds the size limit")

    media_type = _sniff_image_media_type(file_payload)
    extension = IMAGE_EXTENSIONS.get(media_type or "")
    if extension is None:
        raise HTTPException(status_code=400, detail="Only PNG, JPEG, and WebP images are supported")

    upload_dir = settings.asset_upload_dir / "image-optimizer"
    await asyncio.to_thread(upload_dir.mkdir, parents=True, exist_ok=True)
    stored_filename = f"{uuid4().hex}{extension}"
    target = upload_dir / stored_filename
    await asyncio.to_thread(target.write_bytes, file_payload)

    data_url = f"data:{media_type};base64,{base64.b64encode(file_payload).decode('ascii')}"
    return {
        "url": data_url,
        "filename": filename or stored_filename,
        "stored_filename": stored_filename,
        "media_type": media_type,
        "size": len(file_payload),
    }


@router.get("/reference", dependencies=[Depends(require_high_cost_access)])
async def get_quality_reference(prompt: str = "") -> dict[str, Any]:
    return _build_reference_payload(prompt)


@router.post("/reference/analyze", dependencies=[Depends(require_high_cost_access)])
async def analyze_quality_reference(
    request: ReferenceAnalyzeRequest,
    optimizer: PromptOptimizerAgent = Depends(get_prompt_optimizer_agent),
) -> dict[str, Any]:
    prompt_text = _prompt_text(request.prompt, include_constraints=True)
    payload = _build_reference_payload(request.prompt, request.defects)
    try:
        payload["optimized_prompt"] = await optimizer.optimize(prompt_text, payload)
        payload["scoring_request"] = _optimized_scoring_request(prompt_text, payload["optimized_prompt"])
        payload["optimizer"] = {
            "source": "llm",
            "model": optimizer.settings.prompt_optimizer_model,
            "fallback": False,
            "error": None,
        }
    except RuntimeError as exc:
        logger.exception("Prompt optimizer failed")
        raise HTTPException(status_code=502, detail="大模型提示词优化失败，请检查模型配置后重试。") from exc
    return payload


@router.get("/reference/patterns", dependencies=[Depends(require_high_cost_access)])
async def get_reference_patterns(prompt: str = "") -> dict[str, Any]:
    return prompt_pattern_library.build_reference(_prompt_text(prompt)).model_dump(mode="json")


@router.post("/reference/draft", dependencies=[Depends(require_high_cost_access)])
async def draft_reference_prompt(
    request: PromptDraftRequest,
    agent: PromptDraftAgent = Depends(get_prompt_draft_agent),
) -> dict[str, Any]:
    try:
        return await agent.draft(_prompt_text(request.prompt, include_constraints=True))
    except RuntimeError as exc:
        logger.exception("Prompt draft failed")
        raise HTTPException(status_code=502, detail="提示词草稿生成失败，请稍后重试或检查模型配置。") from exc


@router.post("/reference/draft/stream", dependencies=[Depends(require_high_cost_access)])
async def draft_reference_prompt_stream(
    request: PromptDraftRequest,
    agent: PromptDraftAgent = Depends(get_prompt_draft_agent),
) -> StreamingResponse:
    async def stream():
        try:
            async for event in agent.stream_draft(_prompt_text(request.prompt, include_constraints=True)):
                yield json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n"
        except RuntimeError:
            logger.exception("Prompt draft stream failed")
            yield json.dumps({"type": "error", "error": "提示词草稿生成失败，请稍后重试或检查模型配置。"}, ensure_ascii=False, separators=(",", ":")) + "\n"

    return StreamingResponse(stream(), media_type="application/x-ndjson")


def _high_cost_identity(request: Request, settings: Settings, auth: AuthService) -> str:
    configured_key = (settings.api_key or "").strip()
    session_identity = _session_identity(request, auth)
    if session_identity:
        return session_identity
    if _high_cost_auth_required(configured_key, settings):
        return _access_identity(request, _require_api_key(request, settings))
    return _access_identity(request, None)


def _session_identity(request: Request, auth: AuthService) -> str | None:
    token = _bearer_token(request)
    if not token:
        return None
    user = auth.current_user(token)
    return f"user:{user.id}" if user else None


def _bearer_token(request: Request) -> str | None:
    auth_header = request.headers.get("authorization", "")
    if auth_header.lower().startswith("bearer "):
        token = auth_header.split(" ", 1)[1].strip()
        if token:
            return token
    return request.cookies.get("session") or None


def _require_api_key(request: Request, settings: Settings) -> str | None:
    supplied_key = _request_api_key(request)
    configured_key = (settings.api_key or "").strip()

    if not _high_cost_auth_required(configured_key, settings):
        return None

    if not configured_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="API key authentication is not configured",
        )
    if not supplied_key or not compare_digest(supplied_key, configured_key):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or missing API key")
    return supplied_key


def _high_cost_auth_required(configured_key: str, settings: Settings) -> bool:
    if settings.auth_required is not None:
        return settings.auth_required
    return bool(configured_key)


def _access_identity(request: Request, principal: str | None) -> str:
    if principal:
        return f"api:{principal}"
    return f"ip:{_client_host(request)}"


def _client_host(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _request_api_key(request: Request) -> str | None:
    auth_header = request.headers.get("authorization", "")
    if auth_header.lower().startswith("bearer "):
        token = auth_header.split(" ", 1)[1].strip()
        if token:
            return token

    api_key = request.headers.get("x-api-key", "").strip()
    return api_key or None


async def _enforce_rate_limit(
    identity: str,
    settings: Settings,
    *,
    bucket_scope: str = "api",
    limit_multiplier: int = 1,
) -> None:
    limit = settings.rate_limit_requests * limit_multiplier
    window_seconds = settings.rate_limit_window_seconds
    if limit <= 0 or window_seconds <= 0:
        return

    bucket_key = f"{bucket_scope}:{identity}"
    now = monotonic()
    cutoff = now - window_seconds

    async with _rate_limit_lock:
        for key, bucket in list(_rate_limit_hits.items()):
            while bucket and bucket[0] <= cutoff:
                bucket.popleft()
            if not bucket:
                del _rate_limit_hits[key]

        hits = _rate_limit_hits.setdefault(bucket_key, deque())
        if len(hits) >= limit:
            retry_after = max(1, ceil(window_seconds - (now - hits[0])))
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Rate limit exceeded",
                headers={"Retry-After": str(retry_after)},
            )

        hits.append(now)


def _build_reference_payload(prompt: str, defects: list[str] | None = None) -> dict[str, Any]:
    prompt_text = _prompt_text(prompt)
    pattern_reference = prompt_pattern_library.build_reference(prompt_text)
    quality = QualityReference.prompt_quality(prompt_text)
    optimization_hints = QualityReference.optimization_hints(prompt_text, defects)
    candidate_prompts = QualityReference.candidate_prompt_payloads(prompt_text, optimization_hints)
    if candidate_prompts:
        optimized_prompt = candidate_prompts[1]["optimized_prompt"] if len(candidate_prompts) > 1 else candidate_prompts[0]["optimized_prompt"]
    else:
        optimized_prompt = QualityReference.optimized_prompt_payload(prompt_text, optimization_hints)
    current_prompt = _input_current_prompt_text(prompt) or _optimized_prompt_text(optimized_prompt)
    scoring_request = json.loads(VisualEvaluator._build_scoring_request(prompt_text, current_prompt))
    payload = {
        "source": {
            "name": QualityReference.SOURCE_NAME,
            "url": QualityReference.SOURCE_URL,
        },
        "quality": quality,
        "scoring_reference": QualityReference.scoring_reference(prompt_text),
        "optimization_hints": optimization_hints,
        "candidate_prompts": candidate_prompts,
        "optimized_prompt": optimized_prompt,
        "scoring_request": scoring_request,
        "matched_patterns": [pattern.model_dump(mode="json") for pattern in pattern_reference.matched_patterns],
        "pattern_principles": pattern_reference.pattern_principles,
        "source_freshness": pattern_reference.source_freshness,
        "profile_confidence": pattern_reference.profile_confidence,
    }
    payload["guide"] = OptimizationGuideBuilder().build(prompt_text, payload).model_dump(mode="json")
    return payload


def _optimized_scoring_request(original_prompt: str, optimized_prompt: dict[str, Any]) -> dict[str, Any]:
    current_prompt = _optimized_prompt_text(optimized_prompt)
    return json.loads(VisualEvaluator._build_scoring_request(original_prompt, current_prompt))


def _prompt_text(prompt: str, include_constraints: bool = False) -> str:
    try:
        payload = json.loads(prompt)
    except json.JSONDecodeError:
        return prompt
    if not isinstance(payload, dict):
        return prompt

    prompt_payload = payload.get("prompt")
    if not isinstance(prompt_payload, dict):
        return prompt
    raw_text = prompt_payload.get("raw_text")
    if include_constraints:
        structured_text = _prompt_payload_text(prompt_payload)
        text_parts = [item for item in (raw_text, structured_text) if isinstance(item, str) and item.strip()]
        if text_parts:
            return "\n".join(dict.fromkeys(item.strip() for item in text_parts))
    if isinstance(raw_text, str) and raw_text.strip():
        return raw_text
    structured_text = _prompt_payload_analysis_text(prompt_payload)
    if structured_text:
        return structured_text
    original_prompt = payload.get("original_prompt")
    return original_prompt if isinstance(original_prompt, str) and original_prompt.strip() else prompt


def _input_current_prompt_text(prompt: str) -> str:
    try:
        payload = json.loads(prompt)
    except json.JSONDecodeError:
        return ""
    if not isinstance(payload, dict):
        return ""
    prompt_payload = payload.get("prompt")
    return _prompt_payload_text(prompt_payload) if isinstance(prompt_payload, dict) else ""


def _optimized_prompt_text(payload: dict[str, Any]) -> str:
    prompt_payload = payload.get("prompt")
    if isinstance(prompt_payload, dict):
        text = _prompt_payload_text(prompt_payload)
        if text:
            return text
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def _prompt_payload_analysis_text(prompt_payload: dict[str, Any]) -> str:
    fields = (
        ("subject", prompt_payload.get("subject")),
        ("environment", prompt_payload.get("environment")),
        ("style", prompt_payload.get("style")),
        ("lighting", prompt_payload.get("lighting")),
        ("camera and composition", prompt_payload.get("camera_and_composition")),
        ("atmosphere", prompt_payload.get("atmosphere")),
        ("color palette", prompt_payload.get("color_palette")),
        ("text and logo constraints", prompt_payload.get("text_and_logo_constraints")),
        ("negative prompt", _negative_prompt_value(prompt_payload.get("negative_prompt"))),
    )
    lines = [line for label, value in fields if (line := _prompt_text_line(label, value))]
    return "\n".join(lines)


def _prompt_payload_text(prompt_payload: dict[str, Any]) -> str:
    fields = (
        ("subject", prompt_payload.get("subject")),
        ("environment", prompt_payload.get("environment")),
        ("style", prompt_payload.get("style")),
        ("lighting", prompt_payload.get("lighting")),
        ("camera and composition", prompt_payload.get("camera_and_composition")),
        ("atmosphere", prompt_payload.get("atmosphere")),
        ("color palette", prompt_payload.get("color_palette")),
        ("text and logo constraints", prompt_payload.get("text_and_logo_constraints")),
        ("scene constraints", prompt_payload.get("scene_constraints") or prompt_payload.get("constraints")),
        ("negative prompt", _negative_prompt_value(prompt_payload.get("negative_prompt"))),
    )
    lines = [line for label, value in fields if (line := _prompt_text_line(label, value))]
    return "\n".join(lines)


def _prompt_text_line(label: str, value: Any) -> str:
    items = _prompt_text_items(value)
    return f"{label}: {'; '.join(items)}" if items else ""


def _negative_prompt_value(value: Any) -> Any:
    if isinstance(value, str):
        return _strip_negative_prompt_prefix(value)
    if isinstance(value, list):
        return [_strip_negative_prompt_prefix(item) if isinstance(item, str) else item for item in value]
    return value


def _strip_negative_prompt_prefix(value: str) -> str:
    prefix = "negative prompt:"
    return value[len(prefix) :].strip() if value.lower().startswith(prefix) else value


def _prompt_text_items(value: Any) -> list[str]:
    if isinstance(value, str) and value.strip():
        return [value]
    if isinstance(value, list):
        return [item for item in value if isinstance(item, str) and item.strip()]
    return []


async def _read_limited_body(request: Request, max_bytes: int) -> bytes:
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > max_bytes:
            raise HTTPException(status_code=400, detail="Uploaded request exceeds the size limit")
    return bytes(body)


def _extract_upload_file(body: bytes, content_type: str) -> tuple[bytes, str, str]:
    message = BytesParser(policy=default).parsebytes(
        b"Content-Type: " + content_type.encode("utf-8") + b"\r\nMIME-Version: 1.0\r\n\r\n" + body
    )
    if not message.is_multipart():
        raise HTTPException(status_code=400, detail="Invalid multipart payload")

    for part in message.iter_parts():
        if part.get_param("name", header="content-disposition") != "file":
            continue
        payload = part.get_payload(decode=True)
        filename = Path(part.get_filename() or "").name
        return payload or b"", filename, part.get_content_type()

    raise HTTPException(status_code=400, detail="Missing file field")


def _sniff_image_media_type(payload: bytes) -> str | None:
    if payload.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if payload.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if payload.startswith(b"RIFF") and len(payload) > 12 and payload[8:12] == b"WEBP":
        return "image/webp"
    return None


def _sniff_video_media_type(payload: bytes) -> str | None:
    if len(payload) >= 12 and payload[4:8] == b"ftyp":
        brand = payload[8:12]
        compatible = payload[16:64]
        if brand == b"qt  " or b"qt  " in compatible:
            return "video/quicktime"
        if brand in {b"isom", b"mp41", b"mp42", b"avc1", b"iso2", b"M4V "}:
            return "video/mp4"
    if payload.startswith(b"\x1a\x45\xdf\xa3"):
        return "video/webm"
    return None


def _sniff_upload_media_type(payload: bytes) -> str | None:
    return _sniff_image_media_type(payload) or _sniff_video_media_type(payload)


def _asset_kind_for_media_type(media_type: str) -> AssetKind | None:
    if media_type.startswith("image/"):
        return AssetKind.image
    if media_type.startswith("video/"):
        return AssetKind.video
    return None


async def _run_task(
    task_id: str,
    request: GenerateRequest,
    storage: InMemoryTaskStorage,
    pipeline: ImageGenerationPipeline,
) -> None:
    await storage.set_running(task_id)
    try:
        result = await pipeline.run(
            user_input=request.input,
            model_id=request.model,
            threshold=request.threshold,
            max_iter=request.max_iter,
            params=request.params,
            skip_prompt_evaluation=request.skip_prompt_evaluation,
        )
        await storage.set_succeeded(task_id, result)
    except Exception:
        logger.exception("Image generation task failed", extra={"task_id": task_id, "model": request.model})
        await storage.set_failed(task_id, IMAGE_TASK_FAILURE_MESSAGE)
