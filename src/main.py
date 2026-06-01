import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.types import Message, Receive, Scope, Send

from src.api.account_routes import router as account_router
from src.api.admin_routes import router as admin_router
from src.api.auth_routes import router as auth_router
from src.api.canvas_routes import router as canvas_router
from src.api.conversation_routes import router as conversation_router
from src.api.generation_routes import delete_generated_image_files_for_task, router as generation_router
from src.api.image_routes import router
from src.api.project_routes import router as project_router
from src.api.prompt_skill_routes import router as prompt_skill_router
from src.config import Settings, get_settings
from src.dependencies import get_auth_service, get_project_repository
from src.services.auth import AuthService
from src.services.billing_repository import BillingRepository
from src.services.billing_service import BillingService
from src.services.canvas_repository import CanvasRepository
from src.services.database import SQLiteDatabase
from src.services.project_repository import ProjectRepository


MAX_CANVAS_REQUEST_BODY_BYTES = 100_000
STARTUP_RECOVERY_MIN_TASK_AGE_SECONDS = 6 * 60 * 60
STARTUP_RECOVERY_FAILURE_MESSAGE = "任务在服务重启时中断，已退回积分。"

logger = logging.getLogger(__name__)


class CanvasBodyLimitMiddleware:
    def __init__(self, app: Callable[[Scope, Receive, Send], Awaitable[None]], max_bytes: int):
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope.get("method") not in {"POST", "PATCH"} or not _is_canvas_mutation_path(str(scope.get("path", ""))):
            await self.app(scope, receive, send)
            return
        messages: list[Message] = []
        total = 0
        while True:
            message = await receive()
            messages.append(message)
            if message["type"] != "http.request":
                break
            total += len(message.get("body", b""))
            if total > self.max_bytes:
                await _send_canvas_body_limit_response(send)
                return
            if not message.get("more_body", False):
                break
        iterator = iter(messages)

        async def replay_receive() -> Message:
            return next(iterator, {"type": "http.request", "body": b"", "more_body": False})

        await self.app(scope, replay_receive, send)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        async with _lifespan(settings):
            yield

    app = FastAPI(title="Image Generation Optimizer", version="0.1.0", lifespan=lifespan)
    app.dependency_overrides[get_settings] = lambda: settings
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://127.0.0.1:5173",
            "http://localhost:5173",
        ],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(CanvasBodyLimitMiddleware, max_bytes=MAX_CANVAS_REQUEST_BODY_BYTES)

    app.include_router(router)
    app.include_router(auth_router)
    app.include_router(account_router)
    app.include_router(project_router)
    app.include_router(canvas_router)
    app.include_router(generation_router)
    app.include_router(prompt_skill_router)
    app.include_router(conversation_router)
    app.include_router(admin_router)

    @app.get("/uploads/image-optimizer/{filename}")
    def get_upload(
        filename: str,
        request: Request,
        auth: AuthService = Depends(get_auth_service),
        repository: ProjectRepository = Depends(get_project_repository),
    ) -> FileResponse:
        if Path(filename).name != filename or filename in {".", ".."}:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Asset not found")
        url = f"/uploads/image-optimizer/{filename}"
        token = _request_token(request)
        user = auth.current_user(token) if token else None
        if user is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or missing session token")
        if not repository.asset_url_belongs_to_owner(user.id, url):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Asset not found")
        path = settings.asset_upload_dir / "image-optimizer" / filename
        if not path.is_file():
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Asset not found")
        return FileResponse(path)

    frontend_dist = Path(__file__).resolve().parents[1] / "frontend" / "dist"
    if frontend_dist.exists():
        app.mount("/", StaticFiles(directory=frontend_dist, html=True), name="frontend")

    return app


@asynccontextmanager
async def _lifespan(settings: Settings) -> AsyncIterator[None]:
    settings.asset_upload_dir.mkdir(parents=True, exist_ok=True)
    _bootstrap_admin(settings)
    _recover_charged_project_tasks(settings)
    yield


async def _send_canvas_body_limit_response(send: Send) -> None:
    body = b'{"detail":"Canvas request body exceeds the size limit"}'
    await send(
        {
            "type": "http.response.start",
            "status": status.HTTP_413_CONTENT_TOO_LARGE,
            "headers": [(b"content-length", str(len(body)).encode("ascii")), (b"content-type", b"application/json")],
        }
    )
    await send({"type": "http.response.body", "body": body, "more_body": False})


def _is_canvas_mutation_path(path: str) -> bool:
    return path.endswith("/canvases") or path.startswith("/api/canvases/")


def _request_token(request: Request) -> str | None:
    auth_header = request.headers.get("authorization", "")
    if auth_header.lower().startswith("bearer "):
        token = auth_header.split(" ", 1)[1].strip()
        if token:
            return token
    return request.cookies.get("session")


def _bootstrap_admin(settings: Settings) -> None:
    values = (settings.admin_username, settings.admin_email, settings.admin_password)
    if not any(values):
        return
    if not all(values):
        raise ValueError("ADMIN_USERNAME, ADMIN_EMAIL, and ADMIN_PASSWORD must be configured together")
    database = SQLiteDatabase(settings.database_path)
    AuthService(database, settings.session_max_age_seconds).ensure_bootstrap_admin(
        settings.admin_username,
        settings.admin_email,
        settings.admin_password,
    )


def _recover_charged_project_tasks(settings: Settings) -> None:
    database = SQLiteDatabase(settings.database_path)
    repository = ProjectRepository(database)
    canvas_repository = CanvasRepository(database)
    billing = BillingService(BillingRepository(database), settings)

    recover_before = datetime.now(timezone.utc) - timedelta(seconds=STARTUP_RECOVERY_MIN_TASK_AGE_SECONDS)
    for task in repository.list_recoverable_charged_tasks(recover_before):
        try:
            recovered = billing.recover_stale_task(
                task["owner_id"],
                task["credit_transaction_id"],
                task["task_id"],
                recover_before,
                STARTUP_RECOVERY_FAILURE_MESSAGE,
                "startup recovery",
            )
            if recovered:
                canvas_repository.cleanup_task_side_effects(task["owner_id"], task["task_id"])
                delete_generated_image_files_for_task(settings, task["task_id"])
        except Exception:
            logger.exception("Startup recovery failed for charged project task", extra={"task_id": task["task_id"]})

    for task in repository.list_failed_canvas_cleanup_tasks():
        try:
            canvas_repository.cleanup_task_side_effects(task["owner_id"], task["task_id"])
            delete_generated_image_files_for_task(settings, task["task_id"])
        except Exception:
            logger.exception("Startup cleanup failed for charged canvas task", extra={"task_id": task["task_id"]})


app = create_app()
