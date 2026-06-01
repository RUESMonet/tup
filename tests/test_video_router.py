import httpx
import pytest

from src.config import Settings
from src.models.video import VideoGenerateRequest
from src.services.video_router import VideoRouter, _safe_video_endpoint, validate_video_params


def test_video_router_rejects_absolute_endpoint():
    assert _safe_video_endpoint("/videos/generations") == "/videos/generations"
    with pytest.raises(RuntimeError, match="endpoint is not allowed"):
        _safe_video_endpoint("//evil.example/videos")
    with pytest.raises(RuntimeError, match="endpoint is not allowed"):
        _safe_video_endpoint("https://evil.example/videos")


def test_video_router_rejects_reserved_params():
    with pytest.raises(ValueError, match="image"):
        validate_video_params({"image": "https://example.com/x.png"})
    with pytest.raises(ValueError, match="model"):
        validate_video_params({"model": "other-model"})


@pytest.mark.asyncio
async def test_video_router_normalizes_invalid_success_json(monkeypatch):
    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def post(self, *args, **kwargs):
            request = httpx.Request("POST", "https://api.openai.com/v1/videos/generations")
            return httpx.Response(200, content=b"not json", request=request)

    router = VideoRouter(Settings(VIDEO_API_KEY="video-key", MODEL_REQUEST_RETRIES=0))
    monkeypatch.setattr("src.services.video_router.httpx.AsyncClient", FakeClient)
    monkeypatch.setattr("src.services.url_security.socket.getaddrinfo", lambda *args, **kwargs: [(None, None, None, None, ("93.184.216.34", 443))])

    with pytest.raises(RuntimeError, match="provider returned invalid JSON"):
        await router.generate(VideoGenerateRequest(prompt="一段产品视频"))
