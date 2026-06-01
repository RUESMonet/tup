import os
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_UPLOAD_DIR = PROJECT_ROOT / "uploads"
DEFAULT_DATABASE_PATH = PROJECT_ROOT / "data" / "app.db"


class Settings(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    openai_api_key: str | None = Field(default=None, alias="OPENAI_API_KEY")
    openai_image_api_key: str | None = Field(default=None, alias="OPENAI_IMAGE_API_KEY")
    openai_evaluator_api_key: str | None = Field(default=None, alias="OPENAI_EVALUATOR_API_KEY")
    openai_base_url: str = Field(default="https://api.openai.com/v1", alias="OPENAI_BASE_URL")
    openai_image_base_url: str | None = Field(default=None, alias="OPENAI_IMAGE_BASE_URL")
    openai_evaluator_base_url: str | None = Field(default=None, alias="OPENAI_EVALUATOR_BASE_URL")
    openai_prompt_draft_base_url: str | None = Field(default=None, alias="OPENAI_PROMPT_DRAFT_BASE_URL")
    openai_prompt_optimizer_base_url: str | None = Field(default=None, alias="OPENAI_PROMPT_OPTIMIZER_BASE_URL")
    openai_image_model: str = Field(default="gpt-image-2", alias="OPENAI_IMAGE_MODEL")
    openai_evaluator_model: str = Field(default="gpt-4.1-mini", alias="OPENAI_EVALUATOR_MODEL")
    openai_prompt_draft_model: str | None = Field(default=None, alias="OPENAI_PROMPT_DRAFT_MODEL")
    openai_prompt_optimizer_model: str | None = Field(default=None, alias="OPENAI_PROMPT_OPTIMIZER_MODEL")

    prompt_pass_threshold: float = Field(default=6.0, alias="PROMPT_PASS_THRESHOLD")
    visual_pass_threshold: float = Field(default=8.0, alias="VISUAL_PASS_THRESHOLD")
    max_iterations: int = Field(default=3, alias="MAX_ITERATIONS")
    request_timeout_seconds: float = Field(default=60.0, alias="REQUEST_TIMEOUT_SECONDS")
    model_request_retries: int = Field(default=2, alias="MODEL_REQUEST_RETRIES")
    use_mock_images: bool = Field(default=False, alias="USE_MOCK_IMAGES")
    api_key: str | None = Field(default=None, alias="API_KEY")
    auth_required: bool | None = Field(default=None, alias="AUTH_REQUIRED")
    allow_public_registration: bool = Field(default=False, alias="ALLOW_PUBLIC_REGISTRATION")
    rate_limit_requests: int = Field(default=30, alias="RATE_LIMIT_REQUESTS")
    rate_limit_window_seconds: int = Field(default=60, alias="RATE_LIMIT_WINDOW_SECONDS")
    asset_upload_dir: Path = Field(default=DEFAULT_UPLOAD_DIR, alias="ASSET_UPLOAD_DIR")
    asset_upload_max_bytes: int = Field(default=8 * 1024 * 1024, alias="ASSET_UPLOAD_MAX_BYTES")
    database_path: Path = Field(default=DEFAULT_DATABASE_PATH, alias="DATABASE_PATH")
    video_api_key: str | None = Field(default=None, alias="VIDEO_API_KEY")
    video_base_url: str = Field(default="https://api.openai.com/v1", alias="VIDEO_BASE_URL")
    video_model: str = Field(default="video-generation", alias="VIDEO_MODEL")
    video_generate_endpoint: str = Field(default="/videos/generations", alias="VIDEO_GENERATE_ENDPOINT")
    use_mock_videos: bool = Field(default=False, alias="USE_MOCK_VIDEOS")
    session_max_age_seconds: int = Field(default=7 * 24 * 60 * 60, alias="SESSION_MAX_AGE_SECONDS")
    secure_session_cookies: bool = Field(default=True, alias="SECURE_SESSION_COOKIES")
    admin_username: str | None = Field(default=None, alias="ADMIN_USERNAME")
    admin_email: str | None = Field(default=None, alias="ADMIN_EMAIL")
    admin_password: str | None = Field(default=None, alias="ADMIN_PASSWORD")
    model_base_url_allowed_hosts: str | None = Field(default=None, alias="MODEL_BASE_URL_ALLOWED_HOSTS")
    initial_credit_balance: int = Field(default=1000, alias="INITIAL_CREDIT_BALANCE")
    project_image_credit_cost: int = Field(default=10, alias="PROJECT_IMAGE_CREDIT_COST")
    project_image_edit_credit_cost: int = Field(default=12, alias="PROJECT_IMAGE_EDIT_CREDIT_COST")
    project_video_credit_cost: int = Field(default=80, alias="PROJECT_VIDEO_CREDIT_COST")
    canvas_image_credit_cost: int = Field(default=10, alias="CANVAS_IMAGE_CREDIT_COST")
    canvas_image_edit_credit_cost: int = Field(default=12, alias="CANVAS_IMAGE_EDIT_CREDIT_COST")
    canvas_image_batch_credit_cost: int = Field(default=20, alias="CANVAS_IMAGE_BATCH_CREDIT_COST")
    canvas_video_credit_cost: int = Field(default=80, alias="CANVAS_VIDEO_CREDIT_COST")
    daily_project_image_quota: int = Field(default=100, alias="DAILY_PROJECT_IMAGE_QUOTA")
    daily_project_image_edit_quota: int = Field(default=50, alias="DAILY_PROJECT_IMAGE_EDIT_QUOTA")
    daily_project_video_quota: int = Field(default=20, alias="DAILY_PROJECT_VIDEO_QUOTA")
    daily_canvas_image_quota: int = Field(default=100, alias="DAILY_CANVAS_IMAGE_QUOTA")
    daily_canvas_image_edit_quota: int = Field(default=50, alias="DAILY_CANVAS_IMAGE_EDIT_QUOTA")
    daily_canvas_image_batch_quota: int = Field(default=60, alias="DAILY_CANVAS_IMAGE_BATCH_QUOTA")
    daily_canvas_video_quota: int = Field(default=20, alias="DAILY_CANVAS_VIDEO_QUOTA")

    @property
    def image_api_key(self) -> str | None:
        return self.openai_image_api_key or self.openai_api_key

    @property
    def evaluator_api_key(self) -> str | None:
        return self.openai_evaluator_api_key or self.openai_api_key

    @property
    def image_base_url(self) -> str:
        return self.openai_image_base_url or self.openai_base_url

    @property
    def evaluator_base_url(self) -> str:
        return self.openai_evaluator_base_url or self.openai_base_url

    @property
    def prompt_draft_base_url(self) -> str:
        return self.openai_prompt_draft_base_url or self.evaluator_base_url

    @property
    def prompt_draft_model(self) -> str:
        return self.openai_prompt_draft_model or self.openai_evaluator_model

    @property
    def prompt_optimizer_base_url(self) -> str:
        return self.openai_prompt_optimizer_base_url or self.prompt_draft_base_url

    @property
    def prompt_optimizer_model(self) -> str:
        return self.openai_prompt_optimizer_model or self.prompt_draft_model


@lru_cache
def get_settings() -> Settings:
    _load_dotenv()
    values = {
        "OPENAI_API_KEY": os.getenv("OPENAI_API_KEY"),
        "OPENAI_IMAGE_API_KEY": os.getenv("OPENAI_IMAGE_API_KEY"),
        "OPENAI_EVALUATOR_API_KEY": os.getenv("OPENAI_EVALUATOR_API_KEY"),
        "OPENAI_BASE_URL": os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1"),
        "OPENAI_IMAGE_BASE_URL": os.getenv("OPENAI_IMAGE_BASE_URL"),
        "OPENAI_EVALUATOR_BASE_URL": os.getenv("OPENAI_EVALUATOR_BASE_URL"),
        "OPENAI_PROMPT_DRAFT_BASE_URL": os.getenv("OPENAI_PROMPT_DRAFT_BASE_URL"),
        "OPENAI_PROMPT_OPTIMIZER_BASE_URL": os.getenv("OPENAI_PROMPT_OPTIMIZER_BASE_URL"),
        "OPENAI_IMAGE_MODEL": os.getenv("OPENAI_IMAGE_MODEL", "gpt-image-2"),
        "OPENAI_EVALUATOR_MODEL": os.getenv("OPENAI_EVALUATOR_MODEL", "gpt-4.1-mini"),
        "OPENAI_PROMPT_DRAFT_MODEL": os.getenv("OPENAI_PROMPT_DRAFT_MODEL"),
        "OPENAI_PROMPT_OPTIMIZER_MODEL": os.getenv("OPENAI_PROMPT_OPTIMIZER_MODEL"),
        "PROMPT_PASS_THRESHOLD": _float_env("PROMPT_PASS_THRESHOLD", 6.0),
        "VISUAL_PASS_THRESHOLD": _float_env("VISUAL_PASS_THRESHOLD", 8.0),
        "MAX_ITERATIONS": _int_env("MAX_ITERATIONS", 3),
        "REQUEST_TIMEOUT_SECONDS": _float_env("REQUEST_TIMEOUT_SECONDS", 60.0),
        "MODEL_REQUEST_RETRIES": _int_env("MODEL_REQUEST_RETRIES", 2),
        "USE_MOCK_IMAGES": _bool_env("USE_MOCK_IMAGES", False),
        "API_KEY": os.getenv("API_KEY"),
        "AUTH_REQUIRED": _optional_bool_env("AUTH_REQUIRED"),
        "ALLOW_PUBLIC_REGISTRATION": _bool_env("ALLOW_PUBLIC_REGISTRATION", False),
        "RATE_LIMIT_REQUESTS": _int_env("RATE_LIMIT_REQUESTS", 30),
        "RATE_LIMIT_WINDOW_SECONDS": _int_env("RATE_LIMIT_WINDOW_SECONDS", 60),
        "ASSET_UPLOAD_DIR": Path(os.getenv("ASSET_UPLOAD_DIR", str(DEFAULT_UPLOAD_DIR))),
        "ASSET_UPLOAD_MAX_BYTES": _int_env("ASSET_UPLOAD_MAX_BYTES", 8 * 1024 * 1024),
        "DATABASE_PATH": Path(os.getenv("DATABASE_PATH", str(DEFAULT_DATABASE_PATH))),
        "VIDEO_API_KEY": os.getenv("VIDEO_API_KEY"),
        "VIDEO_BASE_URL": os.getenv("VIDEO_BASE_URL", "https://api.openai.com/v1"),
        "VIDEO_MODEL": os.getenv("VIDEO_MODEL", "video-generation"),
        "VIDEO_GENERATE_ENDPOINT": os.getenv("VIDEO_GENERATE_ENDPOINT", "/videos/generations"),
        "USE_MOCK_VIDEOS": _bool_env("USE_MOCK_VIDEOS", False),
        "SESSION_MAX_AGE_SECONDS": _int_env("SESSION_MAX_AGE_SECONDS", 7 * 24 * 60 * 60),
        "SECURE_SESSION_COOKIES": _bool_env("SECURE_SESSION_COOKIES", True),
        "ADMIN_USERNAME": os.getenv("ADMIN_USERNAME"),
        "ADMIN_EMAIL": os.getenv("ADMIN_EMAIL"),
        "ADMIN_PASSWORD": os.getenv("ADMIN_PASSWORD"),
        "MODEL_BASE_URL_ALLOWED_HOSTS": os.getenv("MODEL_BASE_URL_ALLOWED_HOSTS"),
        "INITIAL_CREDIT_BALANCE": _int_env("INITIAL_CREDIT_BALANCE", 1000),
        "PROJECT_IMAGE_CREDIT_COST": _int_env("PROJECT_IMAGE_CREDIT_COST", 10),
        "PROJECT_IMAGE_EDIT_CREDIT_COST": _int_env("PROJECT_IMAGE_EDIT_CREDIT_COST", 12),
        "PROJECT_VIDEO_CREDIT_COST": _int_env("PROJECT_VIDEO_CREDIT_COST", 80),
        "CANVAS_IMAGE_CREDIT_COST": _int_env("CANVAS_IMAGE_CREDIT_COST", 10),
        "CANVAS_IMAGE_EDIT_CREDIT_COST": _int_env("CANVAS_IMAGE_EDIT_CREDIT_COST", 12),
        "CANVAS_IMAGE_BATCH_CREDIT_COST": _int_env("CANVAS_IMAGE_BATCH_CREDIT_COST", 20),
        "CANVAS_VIDEO_CREDIT_COST": _int_env("CANVAS_VIDEO_CREDIT_COST", 80),
        "DAILY_PROJECT_IMAGE_QUOTA": _int_env("DAILY_PROJECT_IMAGE_QUOTA", 100),
        "DAILY_PROJECT_IMAGE_EDIT_QUOTA": _int_env("DAILY_PROJECT_IMAGE_EDIT_QUOTA", 50),
        "DAILY_PROJECT_VIDEO_QUOTA": _int_env("DAILY_PROJECT_VIDEO_QUOTA", 20),
        "DAILY_CANVAS_IMAGE_QUOTA": _int_env("DAILY_CANVAS_IMAGE_QUOTA", 100),
        "DAILY_CANVAS_IMAGE_EDIT_QUOTA": _int_env("DAILY_CANVAS_IMAGE_EDIT_QUOTA", 50),
        "DAILY_CANVAS_IMAGE_BATCH_QUOTA": _int_env("DAILY_CANVAS_IMAGE_BATCH_QUOTA", 60),
        "DAILY_CANVAS_VIDEO_QUOTA": _int_env("DAILY_CANVAS_VIDEO_QUOTA", 20),
    }
    return Settings(**values)


def _load_dotenv() -> None:
    env_file = Path(os.getenv("ENV_FILE", Path(__file__).resolve().parents[1] / ".env"))
    if not env_file.exists():
        return

    for raw_line in env_file.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line.removeprefix("export ").strip()

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("'\"")
        if key and key not in os.environ:
            os.environ[key] = value


def _float_env(name: str, default: float) -> float:
    raw = os.getenv(name)
    return default if raw is None else float(raw)


def _int_env(name: str, default: int) -> int:
    raw = os.getenv(name)
    return default if raw is None else int(raw)


def _bool_env(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _optional_bool_env(name: str) -> bool | None:
    raw = os.getenv(name)
    if raw is None:
        return None
    return raw.strip().lower() in {"1", "true", "yes", "on"}
