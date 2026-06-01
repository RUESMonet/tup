import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import src.dependencies as dependencies
from src.agents.prompt_optimizer import PromptOptimizerAgent
from src.agents.quality_reference import QualityReference
from src.api import image_routes as routes
from src.config import Settings, get_settings
from src.main import create_app


def _client(request, tmp_path: Path, **settings_updates) -> TestClient:
    temp_dir = tmp_path
    values = {
        "auth_required": False,
        "rate_limit_requests": 1000,
        "rate_limit_window_seconds": 60,
        "database_path": temp_dir / "app.db",
        "asset_upload_dir": temp_dir / "uploads",
        "use_mock_images": True,
        "secure_session_cookies": False,
        "openai_api_key": None,
        "openai_evaluator_api_key": None,
        **settings_updates,
    }
    settings = Settings(**values)
    get_settings.cache_clear()
    dependencies.get_storage.cache_clear()
    dependencies._database_for_path.cache_clear()
    routes._rate_limit_hits.clear()

    client = TestClient(create_app(settings))
    client.__enter__()
    request.addfinalizer(lambda: client.__exit__(None, None, None))
    return client


def test_models_endpoint_lists_supported_models(monkeypatch, tmp_path, request):
    client = _client(request, tmp_path)

    response = client.get("/api/models")

    assert response.status_code == 200
    ids = {item["id"] for item in response.json()["models"]}
    assert ids == {"openai"}


def test_generate_returns_task_id_for_async_processing(monkeypatch, tmp_path, request):
    client = _client(request, tmp_path)

    response = client.post(
        "/api/generate",
        json={"input": "一只猫", "model": "openai", "threshold": 8.0},
    )

    assert response.status_code == 202
    payload = response.json()
    assert payload["task_id"]
    assert payload["status"] == "pending"


def test_app_startup_does_not_require_database_url(monkeypatch, tmp_path):
    monkeypatch.setenv("ENV_FILE", str(tmp_path / "missing.env"))
    get_settings.cache_clear()

    try:
        app = create_app(get_settings().model_copy(update={"auth_required": False, "use_mock_images": True}))
        with TestClient(app) as client:
            response = client.get("/api/models")

        assert response.status_code == 200
    finally:
        get_settings.cache_clear()


def test_high_cost_endpoints_require_configured_api_key(monkeypatch, tmp_path, request):
    client = _client(request, tmp_path, auth_required=True, api_key="secret-key")

    missing = client.get("/api/models")
    wrong = client.get("/api/models", headers={"X-API-Key": "wrong-key"})
    allowed = client.get("/api/models", headers={"X-API-Key": "secret-key"})

    assert missing.status_code == 401
    assert wrong.status_code == 401
    assert allowed.status_code == 200


def test_high_cost_endpoint_allows_local_dev_without_auth_config(monkeypatch, tmp_path, request):
    client = _client(request, tmp_path, auth_required=None, api_key=None)

    response = client.get("/api/models")

    assert response.status_code == 200


def test_configured_api_key_enables_auth_when_auth_required_is_unset(monkeypatch, tmp_path, request):
    client = _client(request, tmp_path, auth_required=None, api_key="secret-key")

    missing = client.get("/api/models")
    allowed = client.get("/api/models", headers={"X-API-Key": "secret-key"})

    assert missing.status_code == 401
    assert allowed.status_code == 200


def test_high_cost_endpoints_fail_closed_without_configured_api_key(monkeypatch, tmp_path, request):
    client = _client(request, tmp_path, auth_required=True, api_key=None)

    response = client.get("/api/models")

    assert response.status_code == 503
    assert "not configured" in response.json()["detail"]


def test_high_cost_endpoint_rate_limit_uses_api_key(monkeypatch, tmp_path, request):
    client = _client(request, tmp_path, auth_required=True, api_key="secret-key", rate_limit_requests=2, rate_limit_window_seconds=60)
    headers = {"Authorization": "Bearer secret-key"}

    assert client.get("/api/models", headers=headers).status_code == 200
    assert client.get("/api/models", headers=headers).status_code == 200
    response = client.get("/api/models", headers=headers)

    assert response.status_code == 429
    assert response.headers["retry-after"]


def test_rate_limit_ignores_untrusted_api_key_when_auth_is_disabled(monkeypatch, tmp_path, request):
    client = _client(request, tmp_path, auth_required=False, api_key=None, rate_limit_requests=2, rate_limit_window_seconds=60)

    assert client.get("/api/models", headers={"X-API-Key": "spoof-1"}).status_code == 200
    assert client.get("/api/models", headers={"X-API-Key": "spoof-2"}).status_code == 200
    response = client.get("/api/models", headers={"X-API-Key": "spoof-3"})

    assert response.status_code == 429


def test_reference_endpoint_uses_high_cost_access(monkeypatch, tmp_path, request):
    client = _client(request, tmp_path, auth_required=True, api_key="secret-key")

    missing = client.get("/api/reference", params={"prompt": "一张香水产品图"})
    allowed = client.get("/api/reference", params={"prompt": "一张香水产品图"}, headers={"X-API-Key": "secret-key"})

    assert missing.status_code == 401
    assert allowed.status_code == 200
    assert allowed.json()["guide"]["summary"]


def test_prompt_endpoints_reject_oversized_prompts(monkeypatch, tmp_path, request):
    client = _client(request, tmp_path)
    prompt = "猫" * (routes.MAX_PROMPT_LENGTH + 1)

    generate = client.post("/api/generate", json={"input": prompt, "model": "openai"})
    analyze = client.post("/api/reference/analyze", json={"prompt": prompt})
    draft = client.post("/api/reference/draft", json={"prompt": prompt})
    stream = client.post("/api/reference/draft/stream", json={"prompt": prompt})
    optimize = client.post("/api/prompt/optimize", json={"prompt": prompt})

    assert generate.status_code == 422
    assert analyze.status_code == 422
    assert draft.status_code == 422
    assert stream.status_code == 422
    assert optimize.status_code == 422


def test_prompt_optimize_requires_high_cost_access(monkeypatch, tmp_path, request):
    client = _client(request, tmp_path, auth_required=True, api_key="secret-key")

    missing = client.post("/api/prompt/optimize", json={"prompt": "一张香水产品海报"})
    allowed = client.post(
        "/api/prompt/optimize",
        json={"prompt": "一张香水产品海报"},
        headers={"X-API-Key": "secret-key"},
    )

    assert missing.status_code == 401
    assert allowed.status_code == 200
    assert allowed.json()["intent"]["profile"] == "product"


def test_prompt_optimize_returns_industrial_payload(monkeypatch, tmp_path, request):
    client = _client(request, tmp_path)

    response = client.post(
        "/api/prompt/optimize",
        json={"prompt": '做一张咖啡店海报，标题写着"SUMMER LATTE"'},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["task"] == "prompt_skill_optimization"
    assert payload["intent"]["needs_text_rendering"] is True
    assert payload["optimized_prompt"]["prompt"]["subject"]
    assert payload["final_english_prompt"]
    assert payload["reference_usage"]["matched_cases"]
    assert payload["quality_gates"]


def test_prompt_optimize_returns_safe_error_when_agent_fails(monkeypatch, tmp_path, request):
    from src.agents.prompt_skill_agent import PromptSkillAgent

    async def fail_optimize(self, request_payload):
        raise RuntimeError("provider returned secret diagnostics")

    monkeypatch.setattr(PromptSkillAgent, "optimize", fail_optimize)
    client = _client(request, tmp_path)

    response = client.post("/api/prompt/optimize", json={"prompt": "一只猫坐在窗台上"})

    assert response.status_code == 502
    assert "secret diagnostics" not in response.json()["detail"]
    assert "Prompt" in response.json()["detail"] or "提示词" in response.json()["detail"]


def test_task_endpoints_use_polling_access(monkeypatch, tmp_path, request):
    client = _client(request, tmp_path, auth_required=True, api_key="secret-key")
    headers = {"X-API-Key": "secret-key"}

    assert client.get("/api/task/missing-task").status_code == 401
    assert client.get("/api/task/missing-task/history").status_code == 401
    assert client.get("/api/task/missing-task", headers=headers).status_code == 404
    assert client.get("/api/task/missing-task/history", headers=headers).status_code == 404


@pytest.mark.asyncio
async def test_failed_image_task_stores_safe_error_message():
    class FailingPipeline:
        async def run(self, **kwargs):
            raise RuntimeError("provider returned secret upstream diagnostics")

    storage = routes.InMemoryTaskStorage()
    task = await storage.create("owner")

    await routes._run_task(
        task.task_id,
        routes.GenerateRequest(input="一只猫", model="openai"),
        storage,
        FailingPipeline(),
    )

    failed = await storage.get(task.task_id)

    assert failed.error == routes.IMAGE_TASK_FAILURE_MESSAGE
    assert "secret upstream diagnostics" not in failed.error


def test_task_polling_uses_separate_rate_limit_bucket(monkeypatch, tmp_path, request):
    client = _client(request, tmp_path, auth_required=True, api_key="secret-key", rate_limit_requests=2, rate_limit_window_seconds=60)
    headers = {"X-API-Key": "secret-key"}

    assert client.get("/api/models", headers=headers).status_code == 200
    assert client.get("/api/models", headers=headers).status_code == 200
    assert client.get("/api/models", headers=headers).status_code == 429

    for _ in range(20):
        assert client.get("/api/task/missing-task", headers=headers).status_code == 404


def test_asset_upload_uses_high_cost_access(monkeypatch, tmp_path, request):
    client = _client(request, tmp_path, auth_required=True, api_key="secret-key", asset_upload_dir=tmp_path)
    image = b"\x89PNG\r\n\x1a\n" + b"small"

    missing = client.post("/api/assets/upload", files={"file": ("character.png", image, "image/png")})
    allowed = client.post(
        "/api/assets/upload",
        files={"file": ("character.png", image, "image/png")},
        headers={"X-API-Key": "secret-key"},
    )

    assert missing.status_code == 401
    assert allowed.status_code == 200
    assert allowed.json()["media_type"] == "image/png"


def test_reference_patterns_endpoint_uses_high_cost_access(monkeypatch, tmp_path, request):
    client = _client(request, tmp_path, auth_required=True, api_key="secret-key")

    missing = client.get("/api/reference/patterns", params={"prompt": "高级手表产品广告"})
    allowed = client.get(
        "/api/reference/patterns",
        params={"prompt": "高级手表产品广告"},
        headers={"X-API-Key": "secret-key"},
    )

    assert missing.status_code == 401
    assert allowed.status_code == 200
    assert allowed.json()["profile"] == "product"


def test_reference_analyze_returns_backend_optimized_prompt(monkeypatch, tmp_path, request):
    async def fake_optimize(self, prompt: str, reference_payload: dict):
        return reference_payload["optimized_prompt"]

    monkeypatch.setattr(PromptOptimizerAgent, "optimize", fake_optimize)
    client = _client(request, tmp_path, openai_evaluator_api_key="test-key")

    response = client.post(
        "/api/reference/analyze",
        json={"prompt": "创作一张超写实海报，主体是装饰着[iphone]标志和名称的[I phone air]，位于高山草甸中央。"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["quality"]["profile"] == "product"
    assert any("方括号" in hint for hint in payload["optimization_hints"])
    assert len(payload["candidate_prompts"]) == 4
    assert payload["candidate_prompts"][0]["id"] == "original"
    assert payload["candidate_prompts"][1]["id"] == "product_subject_anchor"
    assert payload["candidate_prompts"][1]["summary"]["主体"].startswith("创作一张超写实海报")
    assert payload["optimized_prompt"]["task"] == "image_generation"
    assert (
        payload["optimized_prompt"]["prompt"]["subject"]
        == "创作一张超写实海报，主体是装饰着iPhone标志和名称的iPhone Air，位于高山草甸中央。"
    )
    assert payload["scoring_request"]["current_prompt"]
    assert payload["guide"]["summary"]
    assert payload["guide"]["issues"]
    assert payload["guide"]["actions"]
    assert "先应用评分最高的候选提示词" in payload["guide"]["next_steps"]
    assert payload["matched_patterns"]
    assert payload["pattern_principles"]
    assert payload["source_freshness"]["case_count"] >= len(payload["matched_patterns"])
    assert payload["profile_confidence"] >= 0
    serialized = json.dumps(payload, ensure_ascii=False)
    assert "藤蔓" not in serialized
    assert "牵牛花" not in serialized


def test_reference_analyze_uses_llm_json_optimizer(monkeypatch, tmp_path, request):
    async def fake_optimize(self, prompt: str, reference_payload: dict):
        assert prompt == "一张现代香水产品海报"
        assert reference_payload["quality"]["profile"] == "product"
        return {
            "task": "image_generation",
            "source": "llm_reference_optimizer",
            "original_prompt": prompt,
            "profile": "product",
            "optimization_hints": ["强化透明玻璃与石材台面的材质关系"],
            "prompt": {
                "subject": "一张现代香水产品海报，透明玻璃瓶作为画面中心主体",
                "environment": "浅灰色石材台面，干净商业棚拍空间",
                "style": "高级商业产品摄影，现代香水广告海报",
                "lighting": "柔和棚拍灯光，受控高光和细腻反射",
                "camera_and_composition": "中心 hero 构图，三分之二正面视角，产品边缘清晰",
                "atmosphere": "克制、精致、奢华",
                "color_palette": "浅灰、透明玻璃、柔和冷白高光",
                "text_and_logo_constraints": "不要文字、水印或变形标签",
                "scene_constraints": ["保持玻璃瓶几何准确", "避免多余道具抢占主体"],
                "negative_prompt": ["text", "watermark", "warped label"],
            },
            "reference_usage": {
                "used_quality_dimensions": ["style", "lighting"],
                "used_pattern_ids": [],
                "candidate_strategy": "combine product profile and user constraints",
            },
        }

    monkeypatch.setattr(PromptOptimizerAgent, "optimize", fake_optimize)
    client = _client(request, tmp_path, openai_evaluator_api_key="test-key", openai_prompt_optimizer_model="gpt-4.1-mini")

    response = client.post("/api/reference/analyze", json={"prompt": "一张现代香水产品海报"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["optimized_prompt"]["source"] == "llm_reference_optimizer"
    assert payload["optimized_prompt"]["prompt"]["subject"].startswith("一张现代香水产品海报")
    assert payload["optimized_prompt"]["prompt"]["negative_prompt"] == ["text", "watermark", "warped label"]
    assert "透明玻璃瓶作为画面中心主体" in payload["scoring_request"]["current_prompt"]
    assert payload["optimizer"] == {"source": "llm", "model": "gpt-4.1-mini", "fallback": False, "error": None}
    assert payload["guide"]["summary"]
    assert payload["candidate_prompts"]
    assert payload["matched_patterns"]


def test_reference_analyze_normalizes_structured_prompt_for_llm_optimizer(monkeypatch, tmp_path, request):
    structured_prompt = json.dumps(
        {"prompt": {"raw_text": "一张现代香水产品海报", "scene_constraints": ["保持透明玻璃瓶居中"]}},
        ensure_ascii=False,
    )

    async def fake_optimize(self, prompt: str, reference_payload: dict):
        assert "一张现代香水产品海报" in prompt
        assert "scene constraints: 保持透明玻璃瓶居中" in prompt
        assert "一张现代香水产品海报" in reference_payload["candidate_prompts"][0]["summary"]["原始输入"]
        return QualityReference.optimized_prompt_payload(prompt)

    monkeypatch.setattr(PromptOptimizerAgent, "optimize", fake_optimize)
    client = _client(request, tmp_path, openai_evaluator_api_key="test-key")

    response = client.post("/api/reference/analyze", json={"prompt": structured_prompt})

    assert response.status_code == 200
    payload = response.json()
    assert "一张现代香水产品海报" in payload["optimized_prompt"]["original_prompt"]
    assert "保持透明玻璃瓶居中" in payload["optimized_prompt"]["original_prompt"]
    assert not payload["scoring_request"]["current_prompt"].startswith("{")


def test_reference_analyze_handles_empty_candidate_prompts(monkeypatch, tmp_path, request):
    async def fake_optimize(self, prompt: str, reference_payload: dict):
        return reference_payload["optimized_prompt"]

    monkeypatch.setattr(PromptOptimizerAgent, "optimize", fake_optimize)
    client = _client(request, tmp_path, openai_evaluator_api_key="test-key")

    monkeypatch.setattr(QualityReference, "candidate_prompt_payloads", lambda prompt, hints=None: [])

    response = client.post("/api/reference/analyze", json={"prompt": "一只猫坐在窗台上"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["candidate_prompts"] == []
    assert payload["optimized_prompt"]["task"] == "image_generation"
    assert payload["guide"]["summary"]


def test_reference_analyze_returns_error_when_llm_optimizer_fails(monkeypatch, tmp_path, request):
    async def fail_optimize(self, prompt: str, reference_payload: dict):
        raise RuntimeError("optimizer unavailable with provider details")

    monkeypatch.setattr(PromptOptimizerAgent, "optimize", fail_optimize)
    client = _client(request, tmp_path, openai_evaluator_api_key="test-key")

    response = client.post("/api/reference/analyze", json={"prompt": "一只猫坐在窗台上"})

    assert response.status_code == 502
    assert "provider details" not in response.json()["detail"]
    assert "大模型" in response.json()["detail"]


def test_reference_analyze_accepts_stringified_optimized_prompt(monkeypatch, tmp_path, request):
    async def fake_optimize(self, prompt: str, reference_payload: dict):
        return reference_payload["optimized_prompt"]

    monkeypatch.setattr(PromptOptimizerAgent, "optimize", fake_optimize)
    client = _client(request, tmp_path, openai_evaluator_api_key="test-key")
    optimized_prompt = QualityReference.optimized_prompt_payload("一只猫坐在窗台上")

    response = client.post(
        "/api/reference/analyze",
        json={"prompt": json.dumps(optimized_prompt, ensure_ascii=False)},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["quality"]["profile"] == "default"
    assert "subject: 一只猫坐在窗台上" in payload["scoring_request"]["current_prompt"]
    assert "negative prompt:" in payload["scoring_request"]["current_prompt"]
    assert not payload["scoring_request"]["current_prompt"].startswith("{")
    assert "一只猫坐在窗台上" in payload["candidate_prompts"][0]["summary"]["原始输入"]
    assert not any("方括号" in hint for hint in payload["optimization_hints"])


def test_reference_analyze_preserves_optimizer_style_constraints(monkeypatch, tmp_path, request):
    optimizer_payload = {
        "task": "image_generation",
        "source": "prompt_pre_evaluation",
        "original_prompt": "一只猫坐在窗台上",
        "prompt": {
            "subject": "一只猫坐在窗台上",
            "style": "cinematic photorealistic style",
            "lighting": "soft directional light",
            "camera_and_composition": "35mm lens, clear composition",
            "atmosphere": "polished and coherent",
            "constraints": "preserve the user's core subject and remove visual ambiguity",
            "negative_prompt": ["Negative Prompt: low resolution", "negative prompt: blurry", "watermark"],
        },
    }

    async def fake_optimize(self, prompt: str, reference_payload: dict):
        return optimizer_payload

    monkeypatch.setattr(PromptOptimizerAgent, "optimize", fake_optimize)
    client = _client(request, tmp_path, openai_evaluator_api_key="test-key")

    response = client.post(
        "/api/reference/analyze",
        json={"prompt": json.dumps(optimizer_payload, ensure_ascii=False)},
    )

    assert response.status_code == 200
    current_prompt = response.json()["scoring_request"]["current_prompt"]
    assert "scene constraints:" in current_prompt
    assert "preserve the user's core subject" in current_prompt
    assert current_prompt.count("negative prompt:") == 1
    assert not current_prompt.startswith("{")


def test_reference_patterns_endpoint_returns_explainable_principles(monkeypatch, tmp_path, request):
    client = _client(request, tmp_path)

    response = client.get("/api/reference/patterns", params={"prompt": "高级手表产品广告，棚拍反光"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["profile"] == "product"
    assert payload["matched_patterns"]
    assert payload["pattern_principles"]
    assert payload["source_freshness"]["source"] == "EvoLinkAI/awesome-gpt-image-2-prompts"


def test_reference_draft_returns_llm_prompt(monkeypatch, tmp_path, request):
    client = _client(request, tmp_path)

    async def fake_draft(self, prompt: str):
        assert prompt == "美国白宫"
        return {
            "draft_prompt": "美国白宫，纪录片式新闻摄影，清晨自然光，正面广角构图，天空通透，建筑细节清晰，避免路人遮挡和文字水印",
            "source": "llm",
            "model": "gpt-5.5",
            "error": None,
        }

    from src.agents.prompt_draft import PromptDraftAgent
    monkeypatch.setattr(PromptDraftAgent, "draft", fake_draft)

    response = client.post(
        "/api/reference/draft",
        json={"prompt": "美国白宫"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["source"] == "llm"
    assert payload["model"] == "gpt-5.5"
    assert "美国白宫" in payload["draft_prompt"]


def test_reference_draft_normalizes_structured_prompt(monkeypatch, tmp_path, request):
    client = _client(request, tmp_path)
    structured_prompt = json.dumps({"prompt": {"raw_text": "美国白宫", "scene_constraints": ["保持正面广角构图"]}}, ensure_ascii=False)

    async def fake_draft(self, prompt: str):
        assert "美国白宫" in prompt
        assert "scene constraints: 保持正面广角构图" in prompt
        return {"draft_prompt": "美国白宫，清晨自然光", "source": "llm", "model": "gpt-5.5", "error": None}

    from src.agents.prompt_draft import PromptDraftAgent
    monkeypatch.setattr(PromptDraftAgent, "draft", fake_draft)

    response = client.post("/api/reference/draft", json={"prompt": structured_prompt})

    assert response.status_code == 200
    assert response.json()["draft_prompt"] == "美国白宫，清晨自然光"


def test_reference_draft_returns_generic_error(monkeypatch, tmp_path, request):
    client = _client(request, tmp_path)

    async def fake_draft(self, prompt: str):
        raise RuntimeError("provider leaked upstream diagnostics")

    from src.agents.prompt_draft import PromptDraftAgent
    monkeypatch.setattr(PromptDraftAgent, "draft", fake_draft)

    response = client.post("/api/reference/draft", json={"prompt": "美国白宫"})

    assert response.status_code == 502
    assert "provider leaked" not in response.json()["detail"]


def test_reference_draft_stream_returns_incremental_events(monkeypatch, tmp_path, request):
    client = _client(request, tmp_path)

    async def fake_stream_draft(self, prompt: str):
        assert prompt == "美国白宫"
        yield {"type": "delta", "delta": "美国白宫，纪录片式新闻摄影，"}
        yield {"type": "delta", "delta": "清晨自然光，正面广角构图"}
        yield {
            "type": "done",
            "draft_prompt": "美国白宫，纪录片式新闻摄影，清晨自然光，正面广角构图",
            "source": "llm",
            "model": "gpt-5.5",
            "error": None,
        }

    from src.agents.prompt_draft import PromptDraftAgent
    monkeypatch.setattr(PromptDraftAgent, "stream_draft", fake_stream_draft)

    with client.stream("POST", "/api/reference/draft/stream", json={"prompt": "美国白宫"}) as response:
        assert response.status_code == 200
        lines = [line for line in response.iter_lines() if line]

    payloads = [json.loads(line) for line in lines]
    assert payloads[0] == {"type": "delta", "delta": "美国白宫，纪录片式新闻摄影，"}
    assert payloads[1] == {"type": "delta", "delta": "清晨自然光，正面广角构图"}
    assert payloads[2]["type"] == "done"
    assert payloads[2]["model"] == "gpt-5.5"


def test_reference_draft_stream_normalizes_structured_prompt(monkeypatch, tmp_path, request):
    client = _client(request, tmp_path)
    structured_prompt = json.dumps({"prompt": {"raw_text": "美国白宫", "scene_constraints": ["保持正面广角构图"]}}, ensure_ascii=False)

    async def fake_stream_draft(self, prompt: str):
        assert "美国白宫" in prompt
        assert "scene constraints: 保持正面广角构图" in prompt
        yield {"type": "done", "draft_prompt": "美国白宫，清晨自然光", "source": "llm", "model": "gpt-5.5", "error": None}

    from src.agents.prompt_draft import PromptDraftAgent
    monkeypatch.setattr(PromptDraftAgent, "stream_draft", fake_stream_draft)

    with client.stream("POST", "/api/reference/draft/stream", json={"prompt": structured_prompt}) as response:
        assert response.status_code == 200
        lines = [line for line in response.iter_lines() if line]

    payload = json.loads(lines[0])
    assert payload["draft_prompt"] == "美国白宫，清晨自然光"


def test_reference_draft_stream_returns_generic_error(monkeypatch, tmp_path, request):
    client = _client(request, tmp_path)

    async def fake_stream_draft(self, prompt: str):
        raise RuntimeError("provider leaked stream diagnostics")
        yield

    from src.agents.prompt_draft import PromptDraftAgent
    monkeypatch.setattr(PromptDraftAgent, "stream_draft", fake_stream_draft)

    with client.stream("POST", "/api/reference/draft/stream", json={"prompt": "美国白宫"}) as response:
        assert response.status_code == 200
        lines = [line for line in response.iter_lines() if line]

    payload = json.loads(lines[0])
    assert payload["type"] == "error"
    assert "provider leaked" not in payload["error"]


def test_asset_upload_saves_supported_image_and_blocks_orphaned_static_file(monkeypatch, tmp_path, request):
    client = _client(request, tmp_path, asset_upload_dir=tmp_path, asset_upload_max_bytes=1024)
    image = b"\x89PNG\r\n\x1a\n" + b"small"

    response = client.post("/api/assets/upload", files={"file": ("character.png", image, "image/png")})

    assert response.status_code == 200
    payload = response.json()
    assert payload["url"].startswith("data:image/png;base64,")
    assert "storage_url" not in payload
    assert payload["media_type"] == "image/png"
    assert payload["size"] == len(image)

    filename = payload["stored_filename"]
    saved_file = tmp_path / "image-optimizer" / filename
    assert saved_file.exists()
    assert saved_file.read_bytes() == image

    served = client.get(f"/uploads/image-optimizer/{filename}")
    assert served.status_code == 401


def test_asset_upload_rejects_non_image_file(monkeypatch, tmp_path, request):
    client = _client(request, tmp_path, asset_upload_dir=tmp_path, asset_upload_max_bytes=1024)

    response = client.post("/api/assets/upload", files={"file": ("notes.txt", b"not an image", "text/plain")})

    assert response.status_code == 400
    assert "PNG" in response.json()["detail"]


def test_asset_upload_rejects_spoofed_image_content_type(monkeypatch, tmp_path, request):
    client = _client(request, tmp_path, asset_upload_dir=tmp_path, asset_upload_max_bytes=1024)

    response = client.post("/api/assets/upload", files={"file": ("character.png", b"not an image", "image/png")})

    assert response.status_code == 400
    assert "PNG" in response.json()["detail"]


def test_asset_upload_rejects_oversized_file(monkeypatch, tmp_path, request):
    client = _client(request, tmp_path, asset_upload_dir=tmp_path, asset_upload_max_bytes=10)
    image = b"\x89PNG\r\n\x1a\n" + b"too large"

    response = client.post("/api/assets/upload", files={"file": ("large.png", image, "image/png")})

    assert response.status_code == 400
    assert "size limit" in response.json()["detail"]
