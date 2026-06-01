from fastapi import APIRouter, Depends, HTTPException, Request, Response, status

from src.api.image_routes import _client_host, _enforce_rate_limit, _high_cost_auth_required
from src.config import Settings, get_settings
from src.dependencies import get_auth_service, require_current_user
from src.models.auth import AuthResponse, AuthUser, CurrentUserResponse, LoginRequest, LogoutResponse, RegisterRequest
from src.services.auth import AuthService, DuplicateAccountError, InvalidCredentialsError


router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/register", response_model=AuthResponse, status_code=status.HTTP_201_CREATED)
async def register(
    request: RegisterRequest,
    http_request: Request,
    response: Response,
    auth: AuthService = Depends(get_auth_service),
    settings: Settings = Depends(get_settings),
) -> AuthResponse:
    await _enforce_rate_limit(f"auth:{_client_host(http_request)}", settings, bucket_scope="auth")
    if _registration_requires_gate(settings) and not settings.allow_public_registration:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Public registration is disabled")
    try:
        user, token = auth.register(request)
    except DuplicateAccountError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    _set_session_cookie(response, token, settings)
    return AuthResponse(user=user)


@router.post("/login", response_model=AuthResponse)
async def login(
    request: LoginRequest,
    http_request: Request,
    response: Response,
    auth: AuthService = Depends(get_auth_service),
    settings: Settings = Depends(get_settings),
) -> AuthResponse:
    await _enforce_rate_limit(f"auth:{_client_host(http_request)}:{request.username.lower()}", settings, bucket_scope="auth")
    try:
        user, token = auth.login(request.username, request.password)
    except InvalidCredentialsError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid username or password") from exc
    _set_session_cookie(response, token, settings)
    return AuthResponse(user=user)


@router.get("/me", response_model=CurrentUserResponse)
def me(user: AuthUser = Depends(require_current_user)) -> CurrentUserResponse:
    return CurrentUserResponse(user=user)


@router.post("/logout", response_model=LogoutResponse)
def logout(
    request: Request,
    response: Response,
    auth: AuthService = Depends(get_auth_service),
    user: AuthUser = Depends(require_current_user),
) -> LogoutResponse:
    token = _session_token(request)
    auth.logout(token)
    response.delete_cookie("session", path="/")
    return LogoutResponse()


def _registration_requires_gate(settings: Settings) -> bool:
    return _high_cost_auth_required((settings.api_key or "").strip(), settings)


def _set_session_cookie(response: Response, token: str, settings: Settings) -> None:
    response.set_cookie(
        "session",
        token,
        max_age=settings.session_max_age_seconds,
        httponly=True,
        secure=settings.secure_session_cookies,
        samesite="lax",
        path="/",
    )


def _session_token(request: Request) -> str:
    auth_header = request.headers.get("authorization", "")
    if auth_header.lower().startswith("bearer "):
        token = auth_header.split(" ", 1)[1].strip()
        if token:
            return token
    cookie_token = request.cookies.get("session")
    if cookie_token:
        return cookie_token
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or missing session token")
