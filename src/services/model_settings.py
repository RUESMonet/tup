import json
import os
from dataclasses import dataclass
from urllib.parse import urlsplit
from datetime import datetime, timezone
from typing import Any, Literal
from src.config import Settings
from src.services.database import SQLiteDatabase
from src.services.url_security import hosts_from_csv, hosts_from_urls, safe_https_base_url


SettingKind = Literal["string", "secret", "url", "endpoint", "bool", "float", "int"]


@dataclass(frozen=True)
class SettingDefinition:
    field: str
    kind: SettingKind
    default: Any = None


SETTING_DEFINITIONS: dict[str, SettingDefinition] = {
    "OPENAI_API_KEY": SettingDefinition("openai_api_key", "secret"),
    "OPENAI_IMAGE_API_KEY": SettingDefinition("openai_image_api_key", "secret"),
    "OPENAI_EVALUATOR_API_KEY": SettingDefinition("openai_evaluator_api_key", "secret"),
    "OPENAI_BASE_URL": SettingDefinition("openai_base_url", "url", "https://api.openai.com/v1"),
    "OPENAI_IMAGE_BASE_URL": SettingDefinition("openai_image_base_url", "url"),
    "OPENAI_EVALUATOR_BASE_URL": SettingDefinition("openai_evaluator_base_url", "url"),
    "OPENAI_PROMPT_DRAFT_BASE_URL": SettingDefinition("openai_prompt_draft_base_url", "url"),
    "OPENAI_PROMPT_OPTIMIZER_BASE_URL": SettingDefinition("openai_prompt_optimizer_base_url", "url"),
    "OPENAI_IMAGE_MODEL": SettingDefinition("openai_image_model", "string", "gpt-image-2"),
    "OPENAI_EVALUATOR_MODEL": SettingDefinition("openai_evaluator_model", "string", "gpt-4.1-mini"),
    "OPENAI_PROMPT_DRAFT_MODEL": SettingDefinition("openai_prompt_draft_model", "string"),
    "OPENAI_PROMPT_OPTIMIZER_MODEL": SettingDefinition("openai_prompt_optimizer_model", "string"),
    "USE_MOCK_IMAGES": SettingDefinition("use_mock_images", "bool", False),
    "VIDEO_API_KEY": SettingDefinition("video_api_key", "secret"),
    "VIDEO_BASE_URL": SettingDefinition("video_base_url", "url", "https://api.openai.com/v1"),
    "VIDEO_MODEL": SettingDefinition("video_model", "string", "video-generation"),
    "VIDEO_GENERATE_ENDPOINT": SettingDefinition("video_generate_endpoint", "endpoint", "/videos/generations"),
    "USE_MOCK_VIDEOS": SettingDefinition("use_mock_videos", "bool", False),
    "REQUEST_TIMEOUT_SECONDS": SettingDefinition("request_timeout_seconds", "float", 60.0),
    "MODEL_REQUEST_RETRIES": SettingDefinition("model_request_retries", "int", 2),
}
SECRET_KEYS = {key for key, definition in SETTING_DEFINITIONS.items() if definition.kind == "secret"}
EFFECTIVE_ATTRS = {
    "OPENAI_IMAGE_API_KEY": "image_api_key",
    "OPENAI_EVALUATOR_API_KEY": "evaluator_api_key",
    "OPENAI_IMAGE_BASE_URL": "image_base_url",
    "OPENAI_EVALUATOR_BASE_URL": "evaluator_base_url",
    "OPENAI_PROMPT_DRAFT_BASE_URL": "prompt_draft_base_url",
    "OPENAI_PROMPT_OPTIMIZER_BASE_URL": "prompt_optimizer_base_url",
    "OPENAI_PROMPT_DRAFT_MODEL": "prompt_draft_model",
    "OPENAI_PROMPT_OPTIMIZER_MODEL": "prompt_optimizer_model",
}


class ModelSettingsService:
    def __init__(self, database: SQLiteDatabase):
        self.database = database

    def effective_settings(self, base: Settings) -> Settings:
        overrides = self.overrides()
        updates = {SETTING_DEFINITIONS[key].field: value for key, value in overrides.items()}
        return Settings.model_validate({**base.model_dump(), **updates})

    def describe(self, base: Settings) -> dict[str, dict[str, Any]]:
        overrides = self.overrides()
        effective = self.effective_settings(base)
        return {key: self._describe_key(key, definition, base, effective, overrides) for key, definition in SETTING_DEFINITIONS.items()}

    def update(self, values: dict[str, Any | None], updated_by: str, base: Settings | None = None) -> dict[str, Any]:
        normalized: dict[str, Any] = {}
        cleared: list[str] = []
        for key, value in values.items():
            definition = SETTING_DEFINITIONS.get(key)
            if definition is None:
                raise ValueError(f"Unknown model setting: {key}")
            if value is None:
                cleared.append(key)
                continue
            if definition.kind == "secret":
                raise ValueError(f"{key} must be configured with environment variables")
            normalized[key] = self._normalize_value(key, definition, value, base)

        now = datetime.now(timezone.utc).isoformat()
        with self.database.connect() as connection:
            for key in cleared:
                connection.execute("DELETE FROM model_settings WHERE key = ?", (key,))
            for key, value in normalized.items():
                connection.execute(
                    """
                    INSERT INTO model_settings (key, value, updated_at, updated_by)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at, updated_by = excluded.updated_by
                    """,
                    (key, json.dumps(value), now, updated_by),
                )
        return self.overrides()

    def overrides(self) -> dict[str, Any]:
        with self.database.connect() as connection:
            rows = connection.execute("SELECT key, value FROM model_settings").fetchall()
        overrides: dict[str, Any] = {}
        for row in rows:
            if row["key"] not in SETTING_DEFINITIONS or row["key"] in SECRET_KEYS:
                continue
            try:
                overrides[row["key"]] = json.loads(row["value"])
            except json.JSONDecodeError:
                continue
        return overrides

    def _describe_key(
        self,
        key: str,
        definition: SettingDefinition,
        base: Settings,
        effective: Settings,
        overrides: dict[str, Any],
    ) -> dict[str, Any]:
        value = getattr(effective, EFFECTIVE_ATTRS.get(key, definition.field))
        source = self._source(key, definition, value, overrides)
        if definition.kind == "secret":
            return {
                "secret": True,
                "configured": bool(value),
                "masked_value": _mask_secret(value),
                "source": source,
            }
        return {"secret": False, "value": value, "source": source, "configured": value not in (None, "")}

    def _source(self, key: str, definition: SettingDefinition, value: Any, overrides: dict[str, Any]) -> str:
        if key in overrides:
            return "database"
        if os.getenv(key) not in (None, ""):
            return "env"
        if key in EFFECTIVE_ATTRS and value not in (None, ""):
            return "inherited"
        if definition.default is not None:
            return "default"
        return "unset"

    def _normalize_value(self, key: str, definition: SettingDefinition, value: Any, base: Settings | None = None) -> Any:
        if definition.kind in {"string", "secret"}:
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{key} must be a non-empty string")
            return value.strip()
        if definition.kind == "url":
            return _validate_url(key, value, base)
        if definition.kind == "endpoint":
            if not isinstance(value, str):
                raise ValueError(f"{key} must be a path endpoint")
            endpoint = value.strip()
            parsed = urlsplit(endpoint)
            if not endpoint.startswith("/") or endpoint.startswith("//") or parsed.scheme or parsed.netloc:
                raise ValueError(f"{key} must be a path endpoint")
            return endpoint
        if definition.kind == "bool":
            if isinstance(value, bool):
                return value
            if isinstance(value, str) and value.strip().lower() in {"true", "false", "1", "0", "yes", "no", "on", "off"}:
                return value.strip().lower() in {"true", "1", "yes", "on"}
            raise ValueError(f"{key} must be a boolean")
        if definition.kind == "float":
            number = _to_number(value, float, key)
            if number <= 0:
                raise ValueError(f"{key} must be greater than 0")
            return number
        if definition.kind == "int":
            number = _to_number(value, int, key)
            if number < 0:
                raise ValueError(f"{key} must be greater than or equal to 0")
            return number
        raise ValueError(f"Unsupported model setting: {key}")


def _validate_url(key: str, value: Any, base: Settings | None = None) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{key} must be an https URL")
    return safe_https_base_url(
        value,
        _allowed_base_url_hosts(base),
        error_type=ValueError,
        error_message=f"{key} base URL is not allowed",
        proxy_fake_ip_allowed_hosts=hosts_from_csv(base.model_base_url_allowed_hosts) if base is not None else (),
    )


def _allowed_base_url_hosts(base: Settings | None) -> set[str]:
    hosts = {"api.openai.com"}
    if base is None:
        return hosts
    hosts.update(
        hosts_from_urls(
            (
                base.openai_base_url,
                base.openai_image_base_url,
                base.openai_evaluator_base_url,
                base.openai_prompt_draft_base_url,
                base.openai_prompt_optimizer_base_url,
                base.video_base_url,
            )
        )
    )
    hosts.update(hosts_from_csv(base.model_base_url_allowed_hosts))
    return hosts


def _to_number(value: Any, target_type, key: str):
    if isinstance(value, bool):
        raise ValueError(f"{key} must be a number")
    try:
        return target_type(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{key} must be a number") from exc


def _mask_secret(value: str | None) -> str | None:
    if not value:
        return None
    if len(value) <= 8:
        return "..." + value[-4:]
    return f"{value[:4]}...{value[-4:]}"
