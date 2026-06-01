import json

import pytest

from src.agents.prompt_optimizer import PromptOptimizerAgent, _safe_base_url
from src.config import Settings


def test_prompt_optimizer_coerces_prompt_json_shape():
    agent = PromptOptimizerAgent(Settings(USE_MOCK_IMAGES=True))
    payload = {
        "task": "image_generation",
        "source": "llm_reference_optimizer",
        "original_prompt": "一张现代香水产品海报",
        "profile": "product",
        "optimization_hints": ["强化玻璃反射"],
        "prompt": {
            "subject": "透明玻璃香水瓶置于浅灰色石材台面",
            "environment": "浅灰色石材台面",
            "style": "高级商业摄影",
            "lighting": "柔和棚拍灯光",
            "camera_and_composition": "居中产品 hero 构图",
            "atmosphere": "精致奢华",
            "color_palette": "浅灰与透明玻璃高光",
            "text_and_logo_constraints": "避免文字水印和标签变形",
            "scene_constraints": ["保持瓶身几何准确"],
            "negative_prompt": ["negative prompt: watermark, warped label"],
        },
        "reference_usage": {
            "used_quality_dimensions": ["style"],
            "used_pattern_ids": [],
            "candidate_strategy": "use product profile",
        },
    }

    result = agent._coerce_optimized_prompt(payload)

    assert result["task"] == "image_generation"
    assert result["source"] == "llm_reference_optimizer"
    assert result["profile"] == "product"
    assert result["optimization_hints"] == ["强化玻璃反射"]
    assert result["prompt"]["scene_constraints"] == ["保持瓶身几何准确"]
    assert result["prompt"]["negative_prompt"] == ["watermark, warped label"]
    assert result["prompt"]["style"] == "高级商业摄影"
    assert result["reference_usage"]["candidate_strategy"] == "use product profile"


def test_prompt_optimizer_rejects_malformed_payload():
    agent = PromptOptimizerAgent(Settings(USE_MOCK_IMAGES=True))

    with pytest.raises(ValueError, match="optimized prompt payload is not an object"):
        agent._coerce_optimized_prompt([])


@pytest.mark.parametrize(
    "mutate_payload, message",
    [
        (lambda payload: payload.pop("task"), "task is required"),
        (lambda payload: payload.pop("source"), "source is required"),
        (lambda payload: payload.pop("reference_usage"), "reference_usage is required"),
        (lambda payload: payload["prompt"].pop("environment"), "environment is required"),
        (lambda payload: payload.update({"optimization_hints": "强化玻璃反射"}), "optimization_hints must be an array"),
    ],
)
def test_prompt_optimizer_rejects_missing_llm_fields_without_fallback(mutate_payload, message):
    agent = PromptOptimizerAgent(Settings(USE_MOCK_IMAGES=True))
    payload = _llm_prompt_payload()
    mutate_payload(payload)

    with pytest.raises(ValueError, match=message):
        agent._coerce_optimized_prompt(payload)


def test_prompt_optimizer_base_url_accepts_dedicated_optimizer_host(monkeypatch):
    settings = Settings(OPENAI_PROMPT_OPTIMIZER_BASE_URL="https://optimizer.example/v1", USE_MOCK_IMAGES=True)

    monkeypatch.setattr("src.services.url_security.socket.getaddrinfo", lambda *args, **kwargs: [(None, None, None, None, ("93.184.216.34", 443))])

    assert _safe_base_url(settings) == "https://optimizer.example/v1"


def test_prompt_optimizer_base_url_accepts_other_model_host(monkeypatch):
    settings = Settings(
        OPENAI_IMAGE_BASE_URL="https://models.example/v1",
        OPENAI_PROMPT_OPTIMIZER_BASE_URL="https://models.example/v1",
        USE_MOCK_IMAGES=True,
    )
    monkeypatch.setattr("src.services.url_security.socket.getaddrinfo", lambda *args, **kwargs: [(None, None, None, None, ("93.184.216.34", 443))])

    assert _safe_base_url(settings) == "https://models.example/v1"


def test_prompt_optimizer_base_url_rejects_private_dns(monkeypatch):
    settings = Settings(
        OPENAI_PROMPT_OPTIMIZER_BASE_URL="https://trusted.example/v1",
        MODEL_BASE_URL_ALLOWED_HOSTS="trusted.example",
        USE_MOCK_IMAGES=True,
    )
    monkeypatch.setattr("src.services.url_security.socket.getaddrinfo", lambda *args, **kwargs: [(None, None, None, None, ("100.64.0.1", 443))])

    with pytest.raises(RuntimeError, match="base URL is not allowed"):
        _safe_base_url(settings)


@pytest.mark.asyncio
async def test_prompt_optimizer_optimize_parses_output_text(monkeypatch):
    agent = PromptOptimizerAgent(Settings(OPENAI_EVALUATOR_API_KEY="test-key", USE_MOCK_IMAGES=True))
    captured = {}

    async def fake_request(payload, headers, timeout):
        captured["payload"] = payload
        captured["headers"] = headers
        return {"output_text": json.dumps(_llm_prompt_payload(), ensure_ascii=False)}

    monkeypatch.setattr(agent, "_request_openai", fake_request)

    result = await agent.optimize("一张现代香水产品海报", _reference_payload())

    assert result["source"] == "llm_reference_optimizer"
    assert result["prompt"]["subject"] == "透明玻璃香水瓶置于浅灰色石材台面"
    assert captured["headers"]["Authorization"] == "Bearer test-key"
    assert captured["payload"]["text"]["format"]["type"] == "json_schema"
    request = json.loads(captured["payload"]["input"][0]["content"][0]["text"])
    assert request["user_prompt"] == "一张现代香水产品海报"
    assert request["reference"]["quality"]["profile"] == "product"


@pytest.mark.asyncio
async def test_prompt_optimizer_optimize_parses_nested_text(monkeypatch):
    agent = PromptOptimizerAgent(Settings(OPENAI_EVALUATOR_API_KEY="test-key", USE_MOCK_IMAGES=True))

    async def fake_request(payload, headers, timeout):
        return {"output": [{"content": [{"text": json.dumps(_llm_prompt_payload(), ensure_ascii=False)}]}]}

    monkeypatch.setattr(agent, "_request_openai", fake_request)

    result = await agent.optimize("一张现代香水产品海报", _reference_payload())

    assert result["prompt"]["negative_prompt"] == ["watermark"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "provider_payload, message",
    [
        ({"output_text": "not json"}, "invalid JSON"),
        ({"output_text": "[]"}, "invalid prompt"),
        ({"output_text": ""}, "no text content"),
    ],
)
async def test_prompt_optimizer_optimize_normalizes_provider_malformed_responses(monkeypatch, provider_payload, message):
    agent = PromptOptimizerAgent(Settings(OPENAI_EVALUATOR_API_KEY="test-key", USE_MOCK_IMAGES=True))

    async def fake_request(payload, headers, timeout):
        return provider_payload

    monkeypatch.setattr(agent, "_request_openai", fake_request)

    with pytest.raises(RuntimeError, match=message):
        await agent.optimize("一张现代香水产品海报", _reference_payload())


def _reference_payload():
    fallback = {
        "task": "image_generation",
        "source": "quality_reference_candidate_optimizer",
        "original_prompt": "一张现代香水产品海报",
        "prompt": {
            "subject": "一张现代香水产品海报",
            "style": "realistic commercial product photography",
            "lighting": "softbox studio lighting",
            "camera_and_composition": "centered hero composition",
            "atmosphere": "premium advertising-grade finish",
            "scene_constraints": ["avoid warped labels"],
            "negative_prompt": ["watermark"],
        },
    }
    return {
        "quality": {"profile": "product"},
        "optimization_hints": ["强化材质"],
        "candidate_prompts": [{"id": "original", "optimized_prompt": fallback}],
        "optimized_prompt": fallback,
        "matched_patterns": [],
        "pattern_principles": [],
        "scoring_reference": {},
        "guide": {"summary": "产品图优化"},
    }


def _llm_prompt_payload():
    return {
        "task": "image_generation",
        "source": "llm_reference_optimizer",
        "original_prompt": "一张现代香水产品海报",
        "profile": "product",
        "optimization_hints": ["强化材质"],
        "prompt": {
            "subject": "透明玻璃香水瓶置于浅灰色石材台面",
            "environment": "浅灰色石材台面",
            "style": "高级商业摄影",
            "lighting": "柔和棚拍灯光",
            "camera_and_composition": "居中 hero 构图",
            "atmosphere": "精致奢华",
            "color_palette": "浅灰和透明高光",
            "text_and_logo_constraints": "避免文字水印",
            "scene_constraints": ["保持瓶身几何准确"],
            "negative_prompt": ["watermark"],
        },
        "reference_usage": {
            "used_quality_dimensions": ["style"],
            "used_pattern_ids": [],
            "candidate_strategy": "combine reference data",
        },
    }
