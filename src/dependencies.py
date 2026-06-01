"""FastAPI dependency injection for services and configuration."""

from functools import lru_cache
from pathlib import Path

from fastapi import Depends, HTTPException, Request, status

from src.agents.prompt_draft import PromptDraftAgent
from src.agents.prompt_optimizer import PromptOptimizerAgent
from src.agents.prompt_skill_agent import PromptSkillAgent
from src.config import Settings, get_settings
from src.models.auth import AuthUser
from src.services.admin_repository import AdminRepository
from src.services.auth import AuthService
from src.services.billing_repository import BillingRepository
from src.services.billing_service import BillingService
from src.services.canvas_repository import CanvasRepository
from src.services.conversation_repository import ConversationRepository
from src.services.database import SQLiteDatabase
from src.services.model_settings import ModelSettingsService
from src.services.pipeline import ImageGenerationPipeline
from src.services.prompt_skill_pipeline import PromptSkillPipeline
from src.services.project_repository import ProjectRepository
from src.services.storage import InMemoryTaskStorage
from src.services.video_router import VideoRouter


@lru_cache()
def get_storage() -> InMemoryTaskStorage:
    """Get singleton task storage instance."""
    return InMemoryTaskStorage()


def get_database(settings: Settings = Depends(get_settings)) -> SQLiteDatabase:
    return _database_for_path(str(settings.database_path))


@lru_cache()
def _database_for_path(path: str) -> SQLiteDatabase:
    return SQLiteDatabase(Path(path))


def get_effective_settings(settings: Settings = Depends(get_settings), database: SQLiteDatabase = Depends(get_database)) -> Settings:
    return ModelSettingsService(database).effective_settings(settings)


def get_pipeline(settings: Settings = Depends(get_effective_settings)) -> ImageGenerationPipeline:
    """Get image generation pipeline with injected settings."""
    return ImageGenerationPipeline(settings)


def get_prompt_skill_pipeline(settings: Settings = Depends(get_effective_settings)) -> PromptSkillPipeline:
    return PromptSkillPipeline(settings)


def get_prompt_draft_agent(settings: Settings = Depends(get_effective_settings)) -> PromptDraftAgent:
    """Get prompt draft agent with injected settings."""
    return PromptDraftAgent(settings)


def get_prompt_optimizer_agent(settings: Settings = Depends(get_effective_settings)) -> PromptOptimizerAgent:
    return PromptOptimizerAgent(settings)


def get_prompt_skill_agent() -> PromptSkillAgent:
    return PromptSkillAgent()


def get_auth_service(settings: Settings = Depends(get_settings), database: SQLiteDatabase = Depends(get_database)) -> AuthService:
    return AuthService(database, settings.session_max_age_seconds)


def get_project_repository(database: SQLiteDatabase = Depends(get_database)) -> ProjectRepository:
    return ProjectRepository(database)


def get_admin_repository(database: SQLiteDatabase = Depends(get_database)) -> AdminRepository:
    return AdminRepository(database)


def get_canvas_repository(database: SQLiteDatabase = Depends(get_database)) -> CanvasRepository:
    return CanvasRepository(database)


def get_conversation_repository(database: SQLiteDatabase = Depends(get_database)) -> ConversationRepository:
    return ConversationRepository(database)


def get_billing_repository(database: SQLiteDatabase = Depends(get_database)) -> BillingRepository:
    return BillingRepository(database)


def get_billing_service(
    repository: BillingRepository = Depends(get_billing_repository),
    settings: Settings = Depends(get_settings),
) -> BillingService:
    return BillingService(repository, settings)


def get_video_router(settings: Settings = Depends(get_effective_settings)) -> VideoRouter:
    return VideoRouter(settings)


def require_current_user(request: Request, auth: AuthService = Depends(get_auth_service)) -> AuthUser:
    token = _bearer_token(request)
    user = auth.current_user(token)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or missing session token")
    return user


def require_admin_user(user: AuthUser = Depends(require_current_user)) -> AuthUser:
    if user.role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")
    return user


def _bearer_token(request: Request) -> str:
    auth_header = request.headers.get("authorization", "")
    if auth_header.lower().startswith("bearer "):
        token = auth_header.split(" ", 1)[1].strip()
        if token:
            return token
    cookie_token = request.cookies.get("session")
    if cookie_token:
        return cookie_token
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or missing session token")
