import time

from fastapi.testclient import TestClient

import src.dependencies as dependencies
from src.agents.canvas_graph_compiler import CanvasGraphCompiler
from src.agents.prompt_evaluator import PromptPreEvaluator
from src.api import image_routes as routes
from src.api.canvas_routes import _canvas_prompt_skill_request
from src.config import Settings
from src.main import create_app
from src.models.canvas import CanvasDetailResponse


TASK_WAIT_TIMEOUT_SECONDS = 10


def _client(tmp_path):
    settings = Settings(
        auth_required=False,
        rate_limit_requests=1000,
        database_path=tmp_path / "app.db",
        asset_upload_dir=tmp_path / "uploads",
        use_mock_images=True,
        use_mock_videos=True,
        secure_session_cookies=False,
    )
    dependencies.get_storage.cache_clear()
    dependencies._database_for_path.cache_clear()
    routes._rate_limit_hits.clear()
    return TestClient(create_app(settings))


def _register(client: TestClient, username: str) -> None:
    response = client.post(
        "/api/auth/register",
        json={"username": username, "email": f"{username}@example.com", "password": "correct horse battery staple"},
    )
    assert response.status_code == 201


def _wait_for_task(client: TestClient, task_id: str) -> dict:
    deadline = time.monotonic() + TASK_WAIT_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        response = client.get(f"/api/tasks/{task_id}")
        assert response.status_code == 200
        payload = response.json()
        if payload["status"] in {"succeeded", "failed"}:
            return payload
        time.sleep(0.05)
    raise AssertionError("task did not finish")


def _project(client: TestClient) -> str:
    response = client.post("/api/projects", json={"name": "Canvas generation"})
    assert response.status_code == 201
    return response.json()["id"]


def _canvas(client: TestClient, project_id: str) -> str:
    response = client.post(f"/api/projects/{project_id}/canvases", json={"name": "Creative Canvas"})
    assert response.status_code == 201
    return response.json()["id"]


def _node(client: TestClient, canvas_id: str, node_type: str, title: str, payload: dict, x: int = 0) -> dict:
    response = client.post(
        f"/api/canvases/{canvas_id}/nodes",
        json={"type": node_type, "title": title, "position": {"x": x, "y": 0}, "payload": payload},
    )
    assert response.status_code == 201
    return response.json()


def test_canvas_generate_image_honors_skip_prompt_evaluation(tmp_path, monkeypatch):
    async def fail_evaluate(self, prompt: str):
        raise AssertionError("prompt evaluator should be skipped")

    monkeypatch.setattr(PromptPreEvaluator, "evaluate", fail_evaluate)
    client = _client(tmp_path)
    _register(client, "ada")
    project_id = _project(client)
    canvas_id = _canvas(client, project_id)
    brief = _node(client, canvas_id, "brief", "Skip evaluator", {"prompt": "一张高端香水海报"})

    response = client.post(
        f"/api/canvases/{canvas_id}/generate/image",
        json={"selected_node_ids": [brief["id"]], "model": "openai", "threshold": 0.0, "skip_prompt_evaluation": True},
    )

    assert response.status_code == 202
    task = _wait_for_task(client, response.json()["task_id"])
    assert task["status"] == "succeeded"



def test_canvas_generate_image_creates_asset_node_and_lineage(tmp_path):
    client = _client(tmp_path)
    _register(client, "ada")
    project_id = _project(client)
    canvas_id = _canvas(client, project_id)
    brief = _node(client, canvas_id, "brief", "Noir brief", {"prompt": "高端 NOIR BLOOM 香水海报，黑金配色，标题写着\"NOIR BLOOM\"", "profile": "poster"})
    style = _node(client, canvas_id, "style_system", "Gold rim", {"lighting": "dramatic gold rim light", "style": "premium fragrance campaign"}, x=360)
    client.post(f"/api/canvases/{canvas_id}/edges", json={"source_node_id": brief["id"], "target_node_id": style["id"], "type": "influences"})

    response = client.post(
        f"/api/canvases/{canvas_id}/generate/image",
        json={"selected_node_ids": [brief["id"], style["id"]], "model": "openai", "threshold": 0.0, "skip_prompt_evaluation": True},
    )

    assert response.status_code == 202
    task = _wait_for_task(client, response.json()["task_id"])
    canvas = client.get(f"/api/canvases/{canvas_id}").json()
    assets = client.get(f"/api/projects/{project_id}/assets").json()["assets"]

    assert task["status"] == "succeeded"
    assert task["kind"] == "image"
    assert task["result"]["canvas"]["canvas_id"] == canvas_id
    assert task["result"]["canvas"]["source_node_ids"] == [brief["id"], style["id"]]
    assert "image_b64_json" not in task["result"]
    generated_node_id = task["result"]["canvas"]["generated_node_id"]
    generated_asset_id = task["result"]["canvas"]["asset_id"]
    generated = next(node for node in canvas["nodes"] if node["id"] == generated_node_id)
    lineage_edges = [edge for edge in canvas["edges"] if edge["target_node_id"] == generated_node_id]

    assert generated["type"] == "generated_image"
    assert generated["payload"]["asset_id"] == generated_asset_id
    assert generated["payload"]["task_id"] == task["task_id"]
    assert generated["payload"]["source"] == "canvas_generation"
    assert {edge["source_node_id"] for edge in lineage_edges} == {brief["id"], style["id"]}
    assert all(edge["type"] == "lineage" for edge in lineage_edges)
    assert any(asset["id"] == generated_asset_id and asset["metadata"].get("canvas_id") == canvas_id for asset in assets)


def test_canvas_generate_image_uses_asset_references_with_roles(tmp_path):
    client = _client(tmp_path)
    _register(client, "ada")
    project_id = _project(client)
    canvas_id = _canvas(client, project_id)
    asset = client.post(
        f"/api/projects/{project_id}/assets/upload",
        files={"file": ("bottle.png", b"\x89PNG\r\n\x1a\nsource-image", "image/png")},
    ).json()
    brief = _node(client, canvas_id, "brief", "Reference brief", {"prompt": "用 @bottle 的瓶身做一张高端香水海报", "profile": "poster"})
    product = _node(
        client,
        canvas_id,
        "asset",
        "bottle.png",
        {
            "asset_id": asset["id"],
            "media_type": asset["media_type"],
            "mention_label": "bottle",
            "reference_role": "product",
            "reference_instruction": "锁定瓶身轮廓和标签比例",
            "influence_strength": 0.9,
        },
        x=360,
    )

    response = client.post(
        f"/api/canvases/{canvas_id}/generate/image",
        json={"selected_node_ids": [brief["id"], product["id"]], "model": "openai", "threshold": 0.0, "skip_prompt_evaluation": True},
    )

    assert response.status_code == 202
    task = _wait_for_task(client, response.json()["task_id"])

    assert task["status"] == "succeeded"
    assert task["result"]["prompt_skill"]["intent"]["action_type"] == "text_and_image_to_image"
    assert "@bottle as product_reference" in task["result"]["final_prompt"]
    assert task["result"]["canvas"]["references"][0]["role"] == "product_reference"
    assert task["result"]["canvas"]["references"][0]["mention_label"] == "bottle"
    assert "data:image" not in str(task["input"])


def test_canvas_generate_rejects_missing_asset_reference(tmp_path):
    client = _client(tmp_path)
    _register(client, "ada")
    project_id = _project(client)
    canvas_id = _canvas(client, project_id)
    brief = _node(client, canvas_id, "brief", "Reference brief", {"prompt": "用 @missing 做一张海报"})
    missing_asset = _node(
        client,
        canvas_id,
        "asset",
        "missing.png",
        {"asset_id": "missing-asset", "media_type": "image/png", "mention_label": "missing", "reference_role": "style"},
    )

    response = client.post(f"/api/canvases/{canvas_id}/generate/image", json={"selected_node_ids": [brief["id"], missing_asset["id"]], "model": "openai"})

    assert response.status_code == 404


def test_canvas_generate_ignores_video_references_as_image_sources(tmp_path):
    client = _client(tmp_path)
    _register(client, "ada")
    project_id = _project(client)
    canvas_id = _canvas(client, project_id)
    video_upload = client.post(
        f"/api/projects/{project_id}/assets/upload",
        files={"file": ("shot.mp4", b"\x00\x00\x00\x18ftypmp42\x00\x00\x00\x00mp42isomsource-video", "video/mp4")},
    )
    assert video_upload.status_code == 201
    asset = video_upload.json()
    brief = _node(client, canvas_id, "brief", "Video motion brief", {"prompt": "参考 @shot 的镜头运动做一张香水海报"})
    video = _node(
        client,
        canvas_id,
        "asset",
        "shot.mp4",
        {
            "asset_id": asset["id"],
            "asset_kind": "video",
            "media_type": asset["media_type"],
            "mention_label": "shot",
            "reference_role": "motion",
            "reference_instruction": "只参考镜头推进和剪辑节奏",
        },
        x=360,
    )

    response = client.post(
        f"/api/canvases/{canvas_id}/generate/image",
        json={"selected_node_ids": [brief["id"], video["id"]], "model": "openai", "threshold": 0.0, "skip_prompt_evaluation": True},
    )

    assert response.status_code == 202
    task = _wait_for_task(client, response.json()["task_id"])
    assert task["status"] == "succeeded"
    assert task["result"]["prompt_skill"]["intent"]["action_type"] == "text_to_image"
    assert task["result"]["canvas"]["references"][0]["asset_kind"] == "video"


def test_canvas_prompt_skill_request_uses_compiled_character_anchors(tmp_path):
    client = _client(tmp_path)
    _register(client, "ada")
    project_id = _project(client)
    canvas_id = _canvas(client, project_id)
    brief = _node(client, canvas_id, "brief", "Character brief", {"prompt": "生成角色系列海报", "character_anchors": ["白发", "蓝眼"]})
    canvas = CanvasDetailResponse(**client.get(f"/api/canvases/{canvas_id}").json())
    compiled = CanvasGraphCompiler().compile(canvas, [brief["id"]])

    prompt_request = _canvas_prompt_skill_request("owner", project_id, compiled, {}, object(), Settings(database_path=tmp_path / "app.db", asset_upload_dir=tmp_path / "uploads"))

    assert prompt_request.character_anchors == ["白发", "蓝眼"]


def test_canvas_generate_rejects_foreign_or_missing_nodes(tmp_path):
    ada_client = _client(tmp_path)
    grace_client = _client(tmp_path)
    _register(ada_client, "ada")
    _register(grace_client, "grace")
    ada_project_id = _project(ada_client)
    grace_project_id = _project(grace_client)
    ada_canvas_id = _canvas(ada_client, ada_project_id)
    grace_canvas_id = _canvas(grace_client, grace_project_id)
    ada_node = _node(ada_client, ada_canvas_id, "brief", "Ada", {"prompt": "高端腕表广告"})
    grace_node = _node(grace_client, grace_canvas_id, "brief", "Grace", {"prompt": "私有参考"})

    missing = ada_client.post(f"/api/canvases/{ada_canvas_id}/generate/image", json={"selected_node_ids": [ada_node["id"], "missing"], "model": "openai"})
    foreign_node = ada_client.post(f"/api/canvases/{ada_canvas_id}/generate/image", json={"selected_node_ids": [ada_node["id"], grace_node["id"]], "model": "openai"})
    foreign_canvas = grace_client.post(f"/api/canvases/{ada_canvas_id}/generate/image", json={"selected_node_ids": [ada_node["id"]], "model": "openai"})
    oversized_params = ada_client.post(
        f"/api/canvases/{ada_canvas_id}/generate/image",
        json={"selected_node_ids": [ada_node["id"]], "model": "openai", "params": {"prompt": "x" * 21000}},
    )
    excessive_batch = ada_client.post(
        f"/api/canvases/{ada_canvas_id}/generate/image",
        json={"selected_node_ids": [ada_node["id"]], "model": "openai", "params": {"n": 9}},
    )
    spoofed_provider_user = ada_client.post(
        f"/api/canvases/{ada_canvas_id}/generate/image",
        json={"selected_node_ids": [ada_node["id"]], "model": "openai", "params": {"user": "someone-else"}},
    )

    assert missing.status_code == 404
    assert foreign_node.status_code == 404
    assert foreign_canvas.status_code == 404
    assert oversized_params.status_code == 422
    assert excessive_batch.status_code == 422
    assert spoofed_provider_user.status_code == 422
