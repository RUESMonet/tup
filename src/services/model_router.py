import asyncio
import base64
import hashlib
import json
from typing import Any

import httpx

from src.config import Settings
from src.models.prompt_skill import ImageSource
from src.models.task import ImageResult
from src.services.url_security import hosts_from_csv, hosts_from_urls, safe_https_base_url


def _runtime_allowed_hosts(settings: Settings) -> set[str]:
    return {
        "api.openai.com",
        *hosts_from_urls(
            (
                settings.openai_base_url,
                settings.openai_image_base_url,
                settings.openai_evaluator_base_url,
                settings.openai_prompt_draft_base_url,
                settings.openai_prompt_optimizer_base_url,
                settings.video_base_url,
            )
        ),
        *hosts_from_csv(settings.model_base_url_allowed_hosts),
    }


def _reference_prompt_policy(source_images: list[ImageSource]) -> str:
    lines = [f"Reference images supplied: {len(source_images)}. Use them as visual anchors without copying artifacts."]
    for index, source in enumerate(source_images, start=1):
        label = source.metadata.get("mention_label") or source.asset_id or f"reference-{index}"
        instruction = source.metadata.get("instruction") or "use as a bounded visual reference"
        influence = source.metadata.get("influence_strength")
        strength = f", influence={influence}" if influence is not None else ""
        lines.append(f"Reference {index} @{label}: role={source.role}{strength}; {instruction}")
    return "\n".join(lines)


class ModelRouter:
    OPENAI_IMAGE_RESPONSE = {"url": ["data", 0, "url"], "b64_json": ["data", 0, "b64_json"]}
    OPENAI_IMAGE_PAYLOAD = {"model": "model", "prompt": "prompt"}
    OPENAI_IMAGE_PARAMS = {
        "size": ["auto", "1024x1024", "1536x1024", "1024x1536"],
        "quality": ["auto", "low", "medium", "high"],
        "background": ["auto", "transparent", "opaque"],
        "output_format": ["png", "jpeg", "webp"],
        "moderation": ["auto", "low"],
        "n": "integer",
        "output_compression": "integer",
        "response_format": ["url", "b64_json"],
    }

    MODELS: dict[str, dict[str, Any]] = {
        "openai": {
            "base_url": "https://api.openai.com/v1",
            "model": "gpt-image-2",
            "endpoint": "/images/generations",
            "payload_fields": OPENAI_IMAGE_PAYLOAD,
            "response_fields": OPENAI_IMAGE_RESPONSE,
            "supported_params": OPENAI_IMAGE_PARAMS,
        },
    }
    API_KEY_ATTRS: dict[str, str] = {
        "openai": "image_api_key",
    }

    def __init__(self, settings: Settings):
        self.settings = settings

    def list_models(self) -> list[dict[str, Any]]:
        return [
            {
                "id": model_id,
                "provider_model": self._resolve_config(model_id)["model"],
                "base_url": self._resolve_config(model_id)["base_url"],
                "endpoint": self._resolve_config(model_id)["endpoint"],
                "configured": bool(self._api_key(model_id)) or self.settings.use_mock_images,
                "supported_params": self._resolve_config(model_id).get("supported_params", {}),
            }
            for model_id in self.MODELS
        ]

    async def generate(self, model_id: str, prompt: str, params: dict[str, Any] | None = None) -> ImageResult:
        return await self.generate_text_to_image(model_id, prompt, params)

    async def generate_text_to_image(self, model_id: str, prompt: str, params: dict[str, Any] | None = None) -> ImageResult:
        cfg = self._resolve_config(model_id)
        params = params or {}

        if self.settings.use_mock_images:
            return self._mock_image(model_id, cfg["model"], prompt, params)

        return await self._generate_with_retries(model_id, prompt, params)

    async def generate_with_references(
        self,
        model_id: str,
        prompt: str,
        source_images: list[ImageSource],
        params: dict[str, Any] | None = None,
    ) -> ImageResult:
        cfg = self._resolve_config(model_id)
        params = params or {}
        if not source_images:
            raise ValueError("At least one source image is required for reference generation")
        self._validate_params(cfg, params)
        reference_prompt = "\n".join([prompt, _reference_prompt_policy(source_images)])
        if self.settings.use_mock_images:
            return self._mock_reference_image(model_id, cfg["model"], reference_prompt, source_images, params)
        return await self._edit_with_retries(model_id, reference_prompt, source_images, None, params)

    async def edit_image(
        self,
        model_id: str,
        prompt: str,
        source_images: list[ImageSource],
        mask_image: ImageSource | None = None,
        params: dict[str, Any] | None = None,
    ) -> ImageResult:
        cfg = self._resolve_config(model_id)
        params = params or {}
        if not source_images:
            raise ValueError("At least one source image is required for image editing")
        self._validate_params(cfg, params)
        if self.settings.use_mock_images:
            return self._mock_edit_image(model_id, cfg["model"], prompt, source_images, mask_image, params)
        return await self._edit_with_retries(model_id, prompt, source_images, mask_image, params)

    async def _generate_with_retries(
        self,
        model_id: str,
        prompt: str,
        params: dict[str, Any],
    ) -> ImageResult:
        attempts = max(1, self.settings.model_request_retries + 1)
        last_exc: Exception | None = None

        for attempt in range(attempts):
            try:
                return await self._generate_once(model_id, prompt, params)
            except httpx.HTTPStatusError as exc:
                last_exc = exc
                if exc.response.status_code < 500 or attempt == attempts - 1:
                    raise RuntimeError(self._http_error_message(model_id, exc.response)) from exc
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                last_exc = exc
                if attempt == attempts - 1:
                    raise RuntimeError(self._transport_error_message(model_id, exc)) from exc

            if attempt < attempts - 1:
                await asyncio.sleep(min(2**attempt * 0.25, 2.0))

        raise RuntimeError(f"Image generation failed for model: {model_id}") from last_exc

    async def _edit_with_retries(
        self,
        model_id: str,
        prompt: str,
        source_images: list[ImageSource],
        mask_image: ImageSource | None,
        params: dict[str, Any],
    ) -> ImageResult:
        attempts = max(1, self.settings.model_request_retries + 1)
        last_exc: Exception | None = None
        for attempt in range(attempts):
            try:
                return await self._edit_once(model_id, prompt, source_images, mask_image, params)
            except httpx.HTTPStatusError as exc:
                last_exc = exc
                if exc.response.status_code < 500 or attempt == attempts - 1:
                    raise RuntimeError(self._http_error_message(model_id, exc.response)) from exc
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                last_exc = exc
                if attempt == attempts - 1:
                    raise RuntimeError(self._transport_error_message(model_id, exc)) from exc
            if attempt < attempts - 1:
                await asyncio.sleep(min(2**attempt * 0.25, 2.0))
        raise RuntimeError(f"Image editing failed for model: {model_id}") from last_exc

    async def _edit_once(
        self,
        model_id: str,
        prompt: str,
        source_images: list[ImageSource],
        mask_image: ImageSource | None,
        params: dict[str, Any],
    ) -> ImageResult:
        cfg = self._resolve_config(model_id)
        api_key = self._api_key(model_id)
        if not api_key:
            raise RuntimeError(f"API key is not configured for model: {model_id}")
        data = {"model": cfg["model"], "prompt": prompt, **params}
        source_files = await asyncio.gather(*(self._source_file_tuple(source, index) for index, source in enumerate(source_images)))
        files = [("image", source_file) for source_file in source_files]
        if mask_image is not None:
            files.append(("mask", await self._source_file_tuple(mask_image, 0, default_name="mask.png")))
        headers = {"Authorization": f"Bearer {api_key}"}
        timeout = httpx.Timeout(self.settings.request_timeout_seconds)
        async with httpx.AsyncClient(base_url=self._safe_base_url(cfg["base_url"]), timeout=timeout) as client:
            response = await client.post("/images/edits", data=data, files=files, headers=headers)
            response.raise_for_status()
            try:
                payload = response.json()
            except ValueError as exc:
                raise RuntimeError(f"Image editing failed for model {model_id}: provider returned invalid JSON") from exc
        return self._provider_image_result(model_id, cfg["model"], payload, params, cfg.get("response_fields", self.OPENAI_IMAGE_RESPONSE))

    async def _source_file_tuple(self, source: ImageSource, index: int, default_name: str | None = None) -> tuple[str, bytes, str]:
        media_type, payload = await self._source_image_bytes(source)
        filename = default_name or f"source-{index}.png"
        return (filename, payload, media_type)

    async def _source_image_bytes(self, source: ImageSource) -> tuple[str, bytes]:
        if source.url and source.url.startswith("data:"):
            header, encoded = source.url.split(",", 1)
            media_type = header[5:].split(";", 1)[0] or source.media_type or "image/png"
            return media_type, base64.b64decode(encoded)
        if source.url and source.url.startswith("/uploads/image-optimizer/"):
            path = self.settings.asset_upload_dir / "image-optimizer" / source.url.rsplit("/", 1)[-1]
            return source.media_type or "image/png", await asyncio.to_thread(path.read_bytes)
        raise ValueError("Image source must be a project upload or data URL for provider image editing")

    async def _generate_once(self, model_id: str, prompt: str, params: dict[str, Any]) -> ImageResult:
        cfg = self._resolve_config(model_id)
        api_key = self._api_key(model_id)
        if not api_key:
            raise RuntimeError(f"API key is not configured for model: {model_id}")

        payload = self._build_payload(cfg, prompt, params)
        headers = {"Authorization": f"Bearer {api_key}"}
        timeout = httpx.Timeout(self.settings.request_timeout_seconds)
        async with httpx.AsyncClient(base_url=self._safe_base_url(cfg["base_url"]), timeout=timeout) as client:
            response = await client.post(cfg["endpoint"], json=payload, headers=headers)
            response.raise_for_status()
            try:
                data = response.json()
            except ValueError as exc:
                raise RuntimeError(f"Image generation failed for model {model_id}: provider returned invalid JSON") from exc

        return self._provider_image_result(model_id, cfg["model"], data, params, cfg.get("response_fields", self.OPENAI_IMAGE_RESPONSE))

    def _resolve_config(self, model_id: str) -> dict[str, Any]:
        if model_id not in self.MODELS:
            raise ValueError(f"Unsupported model: {model_id}")
        cfg = dict(self.MODELS[model_id])
        if model_id == "openai":
            cfg["base_url"] = self.settings.image_base_url
            cfg["model"] = self.settings.openai_image_model
        return cfg

    def _api_key(self, model_id: str) -> str | None:
        if model_id not in self.API_KEY_ATTRS:
            raise ValueError(f"Unsupported model: {model_id}")
        return getattr(self.settings, self.API_KEY_ATTRS[model_id])

    def _safe_base_url(self, base_url: str) -> str:
        return safe_https_base_url(
            base_url,
            _runtime_allowed_hosts(self.settings),
            error_message="image model base URL is not allowed",
            proxy_fake_ip_allowed_hosts=hosts_from_csv(self.settings.model_base_url_allowed_hosts),
        )

    def _build_payload(self, cfg: dict[str, Any], prompt: str, params: dict[str, Any]) -> dict[str, Any]:
        fields = cfg.get("payload_fields", self.OPENAI_IMAGE_PAYLOAD)
        payload = {
            fields.get("model", "model"): cfg["model"],
            fields.get("prompt", "prompt"): prompt,
        }
        self._validate_params(cfg, params)
        payload.update(params)
        return payload

    def _validate_params(self, cfg: dict[str, Any], params: dict[str, Any]) -> None:
        supported = cfg.get("supported_params")
        if not supported:
            return
        for key, value in params.items():
            if key not in supported:
                raise ValueError(f"Unsupported image parameter: {key}")
            allowed = supported[key]
            if isinstance(allowed, list) and value not in allowed:
                raise ValueError(f"Invalid value for image parameter {key}: {value}")
            if allowed == "integer":
                if type(value) is not int:
                    raise ValueError(f"Invalid value for image parameter {key}: expected integer")
                if key == "n" and value < 1:
                    raise ValueError("Invalid value for image parameter n: expected at least 1")
                if key == "output_compression" and (value < 0 or value > 100):
                    raise ValueError("Invalid value for image parameter output_compression: expected 0-100")
            if allowed == "string" and not isinstance(value, str):
                raise ValueError(f"Invalid value for image parameter {key}: expected string")

    @classmethod
    def _provider_image_result(
        cls,
        model_id: str,
        provider_model: str,
        data: dict[str, Any],
        params: dict[str, Any],
        response_fields: dict[str, list[str | int]] | None = None,
    ) -> ImageResult:
        fields = response_fields or cls.OPENAI_IMAGE_RESPONSE
        b64_json = cls._extract_path(data, fields["b64_json"])
        metadata = {"raw_provider": data.get("created")}
        if b64_json:
            metadata["media_type"] = cls._media_type(params)
        return ImageResult(
            url=cls._extract_path(data, fields["url"]),
            b64_json=b64_json,
            model_id=model_id,
            provider_model=provider_model,
            metadata=metadata,
        )

    @staticmethod
    def _media_type(params: dict[str, Any]) -> str:
        output_format = params.get("output_format", "png")
        if output_format == "jpeg":
            return "image/jpeg"
        if output_format == "webp":
            return "image/webp"
        return "image/png"

    @staticmethod
    def _extract_path(data: dict[str, Any], path: list[str | int]) -> str | None:
        current: Any = data
        for part in path:
            if isinstance(part, int):
                if not isinstance(current, list) or len(current) <= part:
                    return None
                current = current[part]
                continue

            if not isinstance(current, dict):
                return None
            current = current.get(part)

            if current is None:
                return None

        return current if isinstance(current, str) else None

    @classmethod
    def _http_error_message(cls, model_id: str, response: httpx.Response) -> str:
        detail = cls._response_error_detail(response)
        message = f"Image generation failed for model {model_id}: provider returned HTTP {response.status_code}"
        return f"{message}: {detail}" if detail else message

    @staticmethod
    def _transport_error_message(model_id: str, exc: httpx.HTTPError) -> str:
        detail = str(exc).strip()
        exc_name = exc.__class__.__name__
        message = f"Image generation failed for model {model_id}: {exc_name}"
        return f"{message}: {detail}" if detail else message

    @staticmethod
    def _response_error_detail(response: httpx.Response) -> str:
        raw_text = response.text.strip()
        if not raw_text:
            return ""

        try:
            payload = response.json()
        except ValueError:
            compact = " ".join(raw_text.split())
        else:
            compact = ModelRouter._compact_error_payload(payload)

        return compact[:500]

    @staticmethod
    def _compact_error_payload(payload: Any) -> str:
        if isinstance(payload, dict):
            error = payload.get("error")
            if isinstance(error, dict):
                parts = [
                    str(error[key]).strip()
                    for key in ("message", "type", "code")
                    if error.get(key) not in (None, "")
                ]
                if parts:
                    return " | ".join(parts)
            if isinstance(error, str) and error.strip():
                return error.strip()

            detail = payload.get("detail")
            if isinstance(detail, str) and detail.strip():
                return detail.strip()

        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))

    @staticmethod
    def _mock_edit_image(
        model_id: str,
        provider_model: str,
        prompt: str,
        source_images: list[ImageSource],
        mask_image: ImageSource | None,
        params: dict[str, Any],
    ) -> ImageResult:
        digest = hashlib.sha256(f"edit:{model_id}:{prompt}:{[source.model_dump(mode='json') for source in source_images]}:{params}".encode("utf-8")).hexdigest()
        b64_json = _mock_png_b64()
        return ImageResult(
            url=f"mock://image-edit/{digest[:16]}",
            b64_json=b64_json,
            model_id=model_id,
            provider_model=provider_model,
            metadata={
                "mock": True,
                "action": "edit",
                "digest": digest,
                "media_type": "image/png",
                "source_image_count": len(source_images),
                "mask": mask_image is not None,
            },
        )

    @staticmethod
    def _mock_reference_image(model_id: str, provider_model: str, prompt: str, source_images: list[ImageSource], params: dict[str, Any]) -> ImageResult:
        digest = hashlib.sha256(f"reference:{model_id}:{prompt}:{[source.model_dump(mode='json') for source in source_images]}:{params}".encode("utf-8")).hexdigest()
        b64_json = _mock_png_b64()
        return ImageResult(
            url=f"mock://image/{digest[:16]}",
            b64_json=b64_json,
            model_id=model_id,
            provider_model=provider_model,
            metadata={"mock": True, "action": "reference", "digest": digest, "media_type": "image/png", "source_image_count": len(source_images)},
        )

    @staticmethod
    def _mock_image(model_id: str, provider_model: str, prompt: str, params: dict[str, Any]) -> ImageResult:
        digest = hashlib.sha256(f"{model_id}:{prompt}:{params}".encode("utf-8")).hexdigest()
        b64_json = _mock_png_b64()
        return ImageResult(
            url=f"mock://image/{digest[:16]}",
            b64_json=b64_json,
            model_id=model_id,
            provider_model=provider_model,
            metadata={"mock": True, "digest": digest, "media_type": "image/png"},
        )


def _mock_png_b64() -> str:
    return "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/p9sAAAAASUVORK5CYII="
