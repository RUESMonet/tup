import asyncio
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, status

from src.api.image_routes import SUPPORTED_MEDIA_EXTENSIONS, SUPPORTED_UPLOAD_MESSAGE, UPLOAD_BODY_OVERHEAD_BYTES, _asset_kind_for_media_type, _extract_upload_file, _read_limited_body, _sniff_upload_media_type, require_high_cost_access
from src.config import Settings, get_settings
from src.dependencies import get_project_repository, require_current_user
from src.models.auth import AuthUser
from src.models.project import AssetListResponse, AssetResponse, ProjectCreateRequest, ProjectListResponse, ProjectResponse, ProjectTaskListResponse
from src.services.project_repository import ProjectRepository


router = APIRouter(prefix="/api/projects", tags=["projects"])


@router.get("", response_model=ProjectListResponse)
def list_projects(
    user: AuthUser = Depends(require_current_user),
    repository: ProjectRepository = Depends(get_project_repository),
) -> ProjectListResponse:
    return ProjectListResponse(projects=repository.list_projects(user.id))


@router.post("", response_model=ProjectResponse, status_code=status.HTTP_201_CREATED)
def create_project(
    request: ProjectCreateRequest,
    user: AuthUser = Depends(require_current_user),
    repository: ProjectRepository = Depends(get_project_repository),
) -> ProjectResponse:
    return repository.create_project(user.id, request.name, request.description)


@router.get("/{project_id}", response_model=ProjectResponse)
def get_project(
    project_id: str,
    user: AuthUser = Depends(require_current_user),
    repository: ProjectRepository = Depends(get_project_repository),
) -> ProjectResponse:
    project = repository.get_project(user.id, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


@router.post("/{project_id}/assets/upload", response_model=AssetResponse, status_code=status.HTTP_201_CREATED)
async def upload_project_asset(
    project_id: str,
    request: Request,
    user: AuthUser = Depends(require_current_user),
    _access_identity: str = Depends(require_high_cost_access),
    repository: ProjectRepository = Depends(get_project_repository),
    settings: Settings = Depends(get_settings),
) -> AssetResponse:
    if await asyncio.to_thread(repository.get_project, user.id, project_id) is None:
        raise HTTPException(status_code=404, detail="Project not found")
    content_type = request.headers.get("content-type", "")
    if "multipart/form-data" not in content_type or "boundary=" not in content_type:
        raise HTTPException(status_code=400, detail="Expected multipart form-data with a file field")
    body = await _read_limited_body(request, settings.asset_upload_max_bytes + UPLOAD_BODY_OVERHEAD_BYTES)
    file_payload, filename, media_type = _extract_upload_file(body, content_type)
    if not file_payload:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")
    if len(file_payload) > settings.asset_upload_max_bytes:
        raise HTTPException(status_code=400, detail="Uploaded file exceeds the size limit")
    sniffed_media_type = _sniff_upload_media_type(file_payload)
    if sniffed_media_type is None:
        raise HTTPException(status_code=400, detail=SUPPORTED_UPLOAD_MESSAGE)
    media_type = sniffed_media_type
    extension = SUPPORTED_MEDIA_EXTENSIONS.get(media_type)
    asset_kind = _asset_kind_for_media_type(media_type)
    if extension is None or asset_kind is None:
        raise HTTPException(status_code=400, detail=SUPPORTED_UPLOAD_MESSAGE)
    upload_dir = settings.asset_upload_dir / "image-optimizer"
    await asyncio.to_thread(upload_dir.mkdir, parents=True, exist_ok=True)
    stored_filename = f"{uuid4().hex}{extension}"
    target = upload_dir / stored_filename
    await asyncio.to_thread(target.write_bytes, file_payload)
    return await asyncio.to_thread(
        repository.create_asset,
        user.id,
        project_id,
        asset_kind,
        f"/uploads/image-optimizer/{stored_filename}",
        media_type,
        {"filename": filename or stored_filename, "stored_filename": stored_filename, "size": len(file_payload), "source": "user_upload"},
    )


@router.get("/{project_id}/assets", response_model=AssetListResponse)
def list_assets(
    project_id: str,
    user: AuthUser = Depends(require_current_user),
    repository: ProjectRepository = Depends(get_project_repository),
) -> AssetListResponse:
    if repository.get_project(user.id, project_id) is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return AssetListResponse(assets=repository.list_assets(user.id, project_id))


@router.get("/{project_id}/tasks", response_model=ProjectTaskListResponse)
def list_tasks(
    project_id: str,
    user: AuthUser = Depends(require_current_user),
    repository: ProjectRepository = Depends(get_project_repository),
) -> ProjectTaskListResponse:
    if repository.get_project(user.id, project_id) is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return ProjectTaskListResponse(tasks=repository.list_tasks(user.id, project_id))
