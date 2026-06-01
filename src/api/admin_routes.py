from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query

from src.config import Settings, get_settings
from src.dependencies import get_admin_repository, get_database, require_admin_user
from src.models.admin import AdminAssetListResponse, AdminAssetReviewUpdate, AdminAssetSummary, AdminTaskListResponse, AdminUserListResponse, ModelSettingsResponse, ModelSettingsUpdate
from src.models.auth import AuthUser
from src.models.billing import ReviewStatus
from src.models.project import TaskKind
from src.models.task import TaskStatus
from src.services.admin_repository import AdminRepository
from src.services.database import SQLiteDatabase
from src.services.model_settings import ModelSettingsService


router = APIRouter(prefix="/api/admin", tags=["admin"])

LimitQuery = Annotated[int, Query(ge=1, le=200)]


@router.get("/model-settings", response_model=ModelSettingsResponse)
def get_model_settings(
    user: AuthUser = Depends(require_admin_user),
    settings: Settings = Depends(get_settings),
    database: SQLiteDatabase = Depends(get_database),
) -> ModelSettingsResponse:
    return ModelSettingsResponse(settings=ModelSettingsService(database).describe(settings))


@router.post("/model-settings", response_model=ModelSettingsResponse)
def update_model_settings(
    request: ModelSettingsUpdate,
    user: AuthUser = Depends(require_admin_user),
    settings: Settings = Depends(get_settings),
    database: SQLiteDatabase = Depends(get_database),
) -> ModelSettingsResponse:
    service = ModelSettingsService(database)
    try:
        service.update(request.settings, user.id, settings)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return ModelSettingsResponse(settings=service.describe(settings))


@router.get("/users", response_model=AdminUserListResponse)
def list_users(
    limit: LimitQuery = 50,
    user: AuthUser = Depends(require_admin_user),
    repository: AdminRepository = Depends(get_admin_repository),
) -> AdminUserListResponse:
    return AdminUserListResponse(users=repository.list_users(limit=limit))


@router.get("/tasks", response_model=AdminTaskListResponse)
def list_tasks(
    status: TaskStatus | None = None,
    kind: TaskKind | None = None,
    limit: LimitQuery = 50,
    user: AuthUser = Depends(require_admin_user),
    repository: AdminRepository = Depends(get_admin_repository),
) -> AdminTaskListResponse:
    return AdminTaskListResponse(tasks=repository.list_tasks(status=status, kind=kind, limit=limit))


@router.get("/assets/review-queue", response_model=AdminAssetListResponse)
def list_asset_review_queue(
    review_status: ReviewStatus | None = None,
    limit: LimitQuery = 50,
    user: AuthUser = Depends(require_admin_user),
    repository: AdminRepository = Depends(get_admin_repository),
) -> AdminAssetListResponse:
    return AdminAssetListResponse(assets=repository.list_assets_for_review(review_status=review_status, limit=limit))


@router.post("/assets/{asset_id}/review", response_model=AdminAssetSummary)
def review_asset(
    asset_id: str,
    request: AdminAssetReviewUpdate,
    user: AuthUser = Depends(require_admin_user),
    repository: AdminRepository = Depends(get_admin_repository),
) -> AdminAssetSummary:
    asset = repository.update_asset_review(
        asset_id=asset_id,
        review_status=request.review_status,
        review_notes=request.review_notes,
        reviewed_by=user.id,
    )
    if asset is None:
        raise HTTPException(status_code=404, detail="Asset not found")
    return asset
