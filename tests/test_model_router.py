import httpx
import pytest

from src.config import Settings
from src.models.prompt_skill import ImageSource
from src.services.model_router import ModelRouter


def test_model_router_exposes_openai_only_model_from_config():
    router = ModelRouter(
        Settings(
            OPENAI_IMAGE_API_KEY="image-key",
            OPENAI_BASE_URL="http://shared.example/v1",
            OPENAI_IMAGE_BASE_URL="http://openai-compatible.example/v1",
            OPENAI_IMAGE_MODEL="gpt-image-test",
        )
    )

    ids = {item["id"] for item in router.list_models()}
    openai = next(item for item in router.list_models() if item["id"] == "openai")

    assert ids == {"openai"}
    assert openai["provider_model"] == "gpt-image-test"
    assert openai["base_url"] == "http://openai-compatible.example/v1"
    assert openai["configured"] is True


def test_model_router_uses_shared_openai_key_as_image_fallback():
    router = ModelRouter(Settings(OPENAI_API_KEY="shared-key"))

    assert router.list_models()[0]["configured"] is True


def test_model_router_exposes_supported_image_parameters():
    router = ModelRouter(Settings(USE_MOCK_IMAGES=True))

    openai = router.list_models()[0]

    assert "size" in openai["supported_params"]
    assert openai["supported_params"]["quality"] == ["auto", "low", "medium", "high"]


def test_model_router_builds_payload_with_configured_field_mapping():
    router = ModelRouter(Settings(USE_MOCK_IMAGES=True))
    cfg = {"model": "mapped-model", "payload_fields": {"model": "model_name", "prompt": "input"}}

    payload = router._build_payload(cfg, "test prompt", {"size": "1024x1024"})

    assert payload == {
        "model_name": "mapped-model",
        "input": "test prompt",
        "size": "1024x1024",
    }


def test_model_router_sets_base64_media_type_from_output_format():
    result = ModelRouter._provider_image_result(
        "openai",
        "gpt-image-test",
        {"data": [{"b64_json": "abc"}], "created": 123},
        {"output_format": "webp"},
    )

    assert result.metadata["media_type"] == "image/webp"


def test_model_router_rejects_unsupported_image_parameter():
    router = ModelRouter(Settings(USE_MOCK_IMAGES=True))
    cfg = router._resolve_config("openai")

    with pytest.raises(ValueError, match="Unsupported image parameter"):
        router._build_payload(cfg, "test prompt", {"unknown": "value"})


def test_model_router_rejects_invalid_parameter_value():
    router = ModelRouter(Settings(USE_MOCK_IMAGES=True))
    cfg = router._resolve_config("openai")

    with pytest.raises(ValueError, match="Invalid value"):
        router._build_payload(cfg, "test prompt", {"quality": "ultra"})


def test_model_router_rejects_bool_for_integer_parameter():
    router = ModelRouter(Settings(USE_MOCK_IMAGES=True))
    cfg = router._resolve_config("openai")

    with pytest.raises(ValueError, match="expected integer"):
        router._build_payload(cfg, "test prompt", {"n": True})


def test_model_router_rejects_invalid_integer_ranges():
    router = ModelRouter(Settings(USE_MOCK_IMAGES=True))
    cfg = router._resolve_config("openai")

    with pytest.raises(ValueError, match="image parameter n"):
        router._build_payload(cfg, "test prompt", {"n": -1})
    with pytest.raises(ValueError, match="image parameter output_compression"):
        router._build_payload(cfg, "test prompt", {"output_compression": 999})


def test_model_router_rejects_provider_user_spoofing():
    router = ModelRouter(Settings(USE_MOCK_IMAGES=True))
    cfg = router._resolve_config("openai")

    with pytest.raises(ValueError, match="Unsupported image parameter"):
        router._build_payload(cfg, "test prompt", {"user": "someone-else"})


@pytest.mark.asyncio
async def test_model_router_mock_edit_image_records_sources():
    router = ModelRouter(Settings(USE_MOCK_IMAGES=True))

    result = await router.edit_image(
        "openai",
        "把背景换成星空，保持人物不变",
        [ImageSource(url="data:image/png;base64,ZmFrZQ==")],
        params={"quality": "high"},
    )

    assert result.url.startswith("mock://image-edit/")
    assert result.metadata["mock"] is True
    assert result.metadata["action"] == "edit"
    assert result.metadata["source_image_count"] == 1
    assert result.metadata["media_type"] == "image/png"


@pytest.mark.asyncio
async def test_model_router_mock_text_image_uses_safe_png_media_type():
    router = ModelRouter(Settings(USE_MOCK_IMAGES=True))

    result = await router.generate_text_to_image("openai", "一张香水产品图", {})

    assert result.url.startswith("mock://image/")
    assert result.metadata["media_type"] == "image/png"
    assert result.b64_json


@pytest.mark.asyncio
async def test_model_router_reference_generation_sends_source_images(monkeypatch):
    router = ModelRouter(Settings(OPENAI_IMAGE_API_KEY="image-key", USE_MOCK_IMAGES=False))
    captured = {}

    async def edit_with_retries(model_id, prompt, source_images, mask_image, params):
        captured["source_images"] = source_images
        captured["mask_image"] = mask_image
        return ModelRouter._mock_reference_image(model_id, "gpt-image-2", prompt, source_images, params)

    monkeypatch.setattr(router, "_edit_with_retries", edit_with_retries)

    result = await router.generate_with_references("openai", "参考生成", [ImageSource(url="data:image/png;base64,ZmFrZQ==")])

    assert captured["source_images"]
    assert captured["mask_image"] is None
    assert result.metadata["source_image_count"] == 1


@pytest.mark.asyncio
async def test_model_router_edit_requires_source_image():
    router = ModelRouter(Settings(USE_MOCK_IMAGES=True))

    with pytest.raises(ValueError, match="source image"):
        await router.edit_image("openai", "编辑图片", [])


@pytest.mark.asyncio
async def test_model_router_rejects_private_dns_at_request_time(monkeypatch):
    router = ModelRouter(
        Settings(
            OPENAI_IMAGE_API_KEY="image-key",
            OPENAI_IMAGE_BASE_URL="https://trusted.example/v1",
            MODEL_BASE_URL_ALLOWED_HOSTS="trusted.example",
            MODEL_REQUEST_RETRIES=0,
        )
    )
    monkeypatch.setattr("src.services.url_security.socket.getaddrinfo", lambda *args, **kwargs: [(None, None, None, None, ("100.64.0.1", 443))])

    with pytest.raises(RuntimeError, match="base URL is not allowed"):
        await router.generate("openai", "test prompt")


@pytest.mark.asyncio
async def test_model_router_requires_key_when_mock_mode_is_disabled():
    router = ModelRouter(Settings(USE_MOCK_IMAGES=False))

    with pytest.raises(RuntimeError, match="API key is not configured"):
        await router.generate("openai", "test prompt")


@pytest.mark.asyncio
async def test_model_router_normalizes_invalid_success_json(monkeypatch):
    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def post(self, *args, **kwargs):
            request = httpx.Request("POST", "https://api.openai.com/v1/images/generations")
            return httpx.Response(200, content=b"not json", request=request)

    router = ModelRouter(Settings(OPENAI_IMAGE_API_KEY="image-key", MODEL_REQUEST_RETRIES=0))
    monkeypatch.setattr("src.services.model_router.httpx.AsyncClient", FakeClient)
    monkeypatch.setattr("src.services.url_security.socket.getaddrinfo", lambda *args, **kwargs: [(None, None, None, None, ("93.184.216.34", 443))])

    with pytest.raises(RuntimeError, match="provider returned invalid JSON"):
        await router.generate("openai", "test prompt")


@pytest.mark.asyncio
async def test_model_router_reports_provider_error_detail(monkeypatch):
    router = ModelRouter(Settings(OPENAI_IMAGE_API_KEY="image-key", MODEL_REQUEST_RETRIES=0))
    request = httpx.Request("POST", "http://image.example/v1/images/generations")
    response = httpx.Response(
        400,
        json={"error": {"message": "invalid image prompt", "code": "invalid_prompt"}},
        request=request,
    )

    async def fail_once(model_id, prompt, params):
        raise httpx.HTTPStatusError("bad request", request=request, response=response)

    monkeypatch.setattr(router, "_generate_once", fail_once)

    with pytest.raises(RuntimeError, match="HTTP 400.*invalid image prompt.*invalid_prompt"):
        await router.generate("openai", "test prompt")


@pytest.mark.asyncio
async def test_model_router_reports_transport_error_detail(monkeypatch):
    router = ModelRouter(Settings(OPENAI_IMAGE_API_KEY="image-key", MODEL_REQUEST_RETRIES=0))

    async def fail_once(model_id, prompt, params):
        raise httpx.ConnectError("nodename nor servname provided")

    monkeypatch.setattr(router, "_generate_once", fail_once)

    with pytest.raises(RuntimeError, match="ConnectError.*nodename nor servname provided"):
        await router.generate("openai", "test prompt")
