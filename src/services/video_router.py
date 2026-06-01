import asyncio
import hashlib
from typing import Any
from urllib.parse import urlsplit

import httpx

from src.config import Settings
from src.models.video import VideoGenerateRequest, VideoResult
from src.services.url_security import hosts_from_csv, hosts_from_urls, safe_https_base_url


SUPPORTED_VIDEO_PARAMS: dict[str, type] = {}


def _safe_video_base_url(settings: Settings) -> str:
    return safe_https_base_url(
        settings.video_base_url,
        _runtime_allowed_hosts(settings),
        error_message="video model base URL is not allowed",
        proxy_fake_ip_allowed_hosts=hosts_from_csv(settings.model_base_url_allowed_hosts),
    )


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


def _safe_video_endpoint(endpoint: str) -> str:
    parsed = urlsplit(endpoint)
    if not endpoint.startswith("/") or endpoint.startswith("//") or parsed.scheme or parsed.netloc:
        raise RuntimeError("video generate endpoint is not allowed")
    return endpoint


def validate_video_params(params: dict[str, Any]) -> None:
    for key, value in params.items():
        expected_type = SUPPORTED_VIDEO_PARAMS.get(key)
        if expected_type is None:
            raise ValueError(f"Unsupported video parameter: {key}")
        if type(value) is not expected_type:
            raise ValueError(f"Invalid value for video parameter {key}")


class VideoRouter:
    def __init__(self, settings: Settings):
        self.settings = settings

    async def generate(self, request: VideoGenerateRequest) -> VideoResult:
        if self.settings.use_mock_videos:
            return self._mock_video(request)
        return await self._generate_with_retries(request)

    async def _generate_with_retries(self, request: VideoGenerateRequest) -> VideoResult:
        attempts = max(1, self.settings.model_request_retries + 1)
        last_exc: Exception | None = None
        for attempt in range(attempts):
            try:
                return await self._generate_once(request)
            except httpx.HTTPStatusError as exc:
                last_exc = exc
                if exc.response.status_code < 500 or attempt == attempts - 1:
                    raise RuntimeError(self._http_error_message(exc.response)) from exc
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                last_exc = exc
                if attempt == attempts - 1:
                    raise RuntimeError(f"Video generation failed: {exc.__class__.__name__}: {str(exc).strip()}") from exc
            await asyncio.sleep(min(2**attempt * 0.25, 2.0))
        raise RuntimeError("Video generation failed") from last_exc

    async def _generate_once(self, request: VideoGenerateRequest) -> VideoResult:
        if not self.settings.video_api_key:
            raise RuntimeError("Video API key is not configured")
        timeout = httpx.Timeout(self.settings.request_timeout_seconds)
        async with httpx.AsyncClient(base_url=_safe_video_base_url(self.settings), timeout=timeout) as client:
            response = await client.post(
                _safe_video_endpoint(self.settings.video_generate_endpoint),
                json=self._payload(request),
                headers={"Authorization": f"Bearer {self.settings.video_api_key}"},
            )
            response.raise_for_status()
            try:
                data = response.json()
            except ValueError as exc:
                raise RuntimeError("Video generation failed: provider returned invalid JSON") from exc
        return self._provider_result(data)

    def _payload(self, request: VideoGenerateRequest) -> dict[str, Any]:
        validate_video_params(request.params)
        payload = {"model": self.settings.video_model, "prompt": request.prompt}
        if request.source_image_url:
            payload["image"] = request.source_image_url
        if request.duration is not None:
            payload["duration"] = request.duration
        if request.aspect_ratio:
            payload["aspect_ratio"] = request.aspect_ratio
        payload.update(request.params)
        return payload

    def _provider_result(self, data: dict[str, Any]) -> VideoResult:
        url = _extract_path(data, ["data", 0, "url"]) or _extract_path(data, ["url"]) or _extract_path(data, ["video", "url"])
        if not url:
            raise RuntimeError("Video provider response did not include a video URL")
        media_type = _extract_path(data, ["data", 0, "media_type"]) or _extract_path(data, ["media_type"]) or "video/mp4"
        return VideoResult(url=url, media_type=media_type, provider_model=self.settings.video_model, metadata={"raw_provider": data})

    def _mock_video(self, request: VideoGenerateRequest) -> VideoResult:
        digest = hashlib.sha256(f"{request.prompt}:{request.source_image_url}:{request.duration}".encode("utf-8")).hexdigest()
        return VideoResult(
            url=f"mock://video/{digest[:16]}",
            media_type="video/mp4",
            provider_model=self.settings.video_model,
            metadata={"mock": True, "digest": digest, "source_image_url": request.source_image_url},
        )

    @staticmethod
    def _http_error_message(response: httpx.Response) -> str:
        try:
            detail = response.json()
        except ValueError:
            detail = response.text.strip()
        return f"Video generation failed: provider returned HTTP {response.status_code}: {detail}"


def _extract_path(data: Any, path: list[str | int]) -> str | None:
    current = data
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
