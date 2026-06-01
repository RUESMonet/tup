import time

from fastapi.testclient import TestClient

import src.dependencies as dependencies
from src.api import generation_routes, image_routes as routes
from src.config import Settings
from src.main import create_app
from src.services.project_repository import ProjectRepository


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


def test_projects_require_login_and_are_user_scoped(tmp_path):
    missing_client = _client(tmp_path)
    ada_client = _client(tmp_path)
    grace_client = _client(tmp_path)
    missing = missing_client.get("/api/projects")
    _register(ada_client, "ada")
    _register(grace_client, "grace")

    created = ada_client.post("/api/projects", json={"name": "Perfume launch"})
    ada_list = ada_client.get("/api/projects")
    grace_list = grace_client.get("/api/projects")
    grace_read = grace_client.get(f"/api/projects/{created.json()['id']}")

    assert missing.status_code == 401
    assert created.status_code == 201
    assert ada_list.json()["projects"][0]["name"] == "Perfume launch"
    assert grace_list.json()["projects"] == []
    assert grace_read.status_code == 404


def test_project_name_cannot_be_blank(tmp_path):
    client = _client(tmp_path)
    _register(client, "ada")

    response = client.post("/api/projects", json={"name": "   "})

    assert response.status_code == 422


def test_project_asset_upload_creates_owned_image_asset(tmp_path):
    client = _client(tmp_path)
    _register(client, "ada")
    project_id = client.post("/api/projects", json={"name": "References"}).json()["id"]
    image = b"\x89PNG\r\n\x1a\n" + b"source-image"

    response = client.post(
        f"/api/projects/{project_id}/assets/upload",
        files={"file": ("source.png", image, "image/png")},
    )

    assert response.status_code == 201
    asset = response.json()
    assert asset["kind"] == "image"
    assert asset["url"].startswith("/uploads/image-optimizer/")
    assert client.get(asset["url"]).status_code == 200
    assets = client.get(f"/api/projects/{project_id}/assets").json()["assets"]
    assert any(item["id"] == asset["id"] for item in assets)


def test_project_asset_upload_creates_owned_video_asset(tmp_path):
    client = _client(tmp_path)
    _register(client, "ada")
    project_id = client.post("/api/projects", json={"name": "References"}).json()["id"]
    video = b"\x00\x00\x00\x18ftypmp42\x00\x00\x00\x00mp42isom" + b"source-video"

    response = client.post(
        f"/api/projects/{project_id}/assets/upload",
        files={"file": ("shot.mp4", video, "video/mp4")},
    )

    assert response.status_code == 201
    asset = response.json()
    assert asset["kind"] == "video"
    assert asset["media_type"] == "video/mp4"
    assert asset["url"].startswith("/uploads/image-optimizer/")
    assert asset["url"].endswith(".mp4")
    assert client.get(asset["url"]).status_code == 200
    assets = client.get(f"/api/projects/{project_id}/assets").json()["assets"]
    assert any(item["id"] == asset["id"] and item["kind"] == "video" for item in assets)


def test_project_asset_upload_rejects_spoofed_video_content_type(tmp_path):
    client = _client(tmp_path)
    _register(client, "ada")
    project_id = client.post("/api/projects", json={"name": "References"}).json()["id"]

    response = client.post(
        f"/api/projects/{project_id}/assets/upload",
        files={"file": ("shot.mp4", b"not a video", "video/mp4")},
    )

    assert response.status_code == 400
    assert "MP4" in response.json()["detail"]


def test_project_asset_upload_is_project_scoped(tmp_path):
    ada_client = _client(tmp_path)
    grace_client = _client(tmp_path)
    _register(ada_client, "ada")
    _register(grace_client, "grace")
    project_id = ada_client.post("/api/projects", json={"name": "Private"}).json()["id"]
    image = b"\x89PNG\r\n\x1a\n" + b"source-image"
    asset_url = ada_client.post(
        f"/api/projects/{project_id}/assets/upload",
        files={"file": ("source.png", image, "image/png")},
    ).json()["url"]

    response = grace_client.post(
        f"/api/projects/{project_id}/assets/upload",
        files={"file": ("source.png", image, "image/png")},
    )

    assert response.status_code == 404
    assert grace_client.get(asset_url).status_code == 404


def test_project_image_generation_creates_task_and_asset(tmp_path):
    client = _client(tmp_path)
    _register(client, "ada")
    project_id = client.post("/api/projects", json={"name": "Perfume launch"}).json()["id"]

    response = client.post(
        f"/api/projects/{project_id}/generate/image",
        json={"input": "一张香水产品图", "model": "openai", "threshold": 0.0, "skip_prompt_evaluation": True, "params": {"response_format": "url"}},
    )

    assert response.status_code == 202
    task = _wait_for_task(client, response.json()["task_id"])
    assets = client.get(f"/api/projects/{project_id}/assets").json()["assets"]
    history = client.get(f"/api/tasks/{task['task_id']}/history")

    assert task["status"] == "succeeded"
    assert task["kind"] == "image"
    assert task["result"]["final_prompt"]
    assert task["result"]["image_url"].startswith("/uploads/image-optimizer/")
    assert task["result"]["prompt_report"]
    trace = task["result"]["optimization_trace"]
    assert trace["profile"] == "product"
    assert trace["stages"]
    assert trace["stages"][0]["selected_terms"]["style"]
    assert any(asset["kind"] == "image" for asset in assets)
    assert history.status_code == 200
    assert history.json()["history"]
    assert history.json()["history"][0]["visual_report"]


def test_project_generation_stays_succeeded_when_asset_save_fails(tmp_path, monkeypatch):
    def fail_create_asset(self, *args, **kwargs):
        raise RuntimeError("asset storage failed with provider details")

    monkeypatch.setattr(ProjectRepository, "create_asset", fail_create_asset)
    client = _client(tmp_path)
    _register(client, "ada")
    project_id = client.post("/api/projects", json={"name": "Asset failure"}).json()["id"]

    image_response = client.post(
        f"/api/projects/{project_id}/generate/image",
        json={"input": "一张香水产品图", "model": "openai", "threshold": 0.0, "skip_prompt_evaluation": True},
    )
    video_response = client.post(
        f"/api/projects/{project_id}/generate/video",
        json={"prompt": "香水瓶在雾气中缓慢旋转", "duration": 4},
    )

    image_task = _wait_for_task(client, image_response.json()["task_id"])
    video_task = _wait_for_task(client, video_response.json()["task_id"])

    assert image_task["status"] == "succeeded"
    assert image_task["error"] is None
    assert image_task["result"]["final_prompt"]
    assert video_task["status"] == "succeeded"
    assert video_task["error"] is None
    assert video_task["result"]["url"].startswith("mock://video/")


def test_project_image_edit_uses_source_asset_and_creates_new_asset(tmp_path):
    client = _client(tmp_path)
    _register(client, "ada")
    project_id = client.post("/api/projects", json={"name": "Edit board"}).json()["id"]
    image = b"\x89PNG\r\n\x1a\n" + b"source-image"
    upload = client.post(
        f"/api/projects/{project_id}/assets/upload",
        files={"file": ("source.png", image, "image/png")},
    )
    source_asset_id = upload.json()["id"]

    response = client.post(
        f"/api/projects/{project_id}/generate/image-edit",
        json={
            "prompt": "把这张图背景换成星空，保持人物不变",
            "model": "openai",
            "source_image_asset_ids": [source_asset_id],
            "threshold": 0.0,
            "params": {"quality": "high", "response_format": "url"},
        },
    )

    assert response.status_code == 202
    task = _wait_for_task(client, response.json()["task_id"])
    assets = client.get(f"/api/projects/{project_id}/assets").json()["assets"]

    assert task["status"] == "succeeded"
    assert task["kind"] == "image_edit"
    assert task["input"]["source_image_asset_ids"] == [source_asset_id]
    assert "source_images" not in task["input"]
    assert "data:image" not in str(task["input"])
    assert task["result"]["image_url"].startswith("/uploads/image-optimizer/")
    assert task["result"]["prompt_skill"]["intent"]["action_type"] == "edit"
    assert any(asset["metadata"].get("task_id") == task["task_id"] for asset in assets)


def test_project_image_edit_preserves_reference_generation_action_type(tmp_path):
    client = _client(tmp_path)
    _register(client, "ada")
    project_id = client.post("/api/projects", json={"name": "References"}).json()["id"]
    image = b"\x89PNG\r\n\x1a\n" + b"source-image"
    source_asset_id = client.post(
        f"/api/projects/{project_id}/assets/upload",
        files={"file": ("source.png", image, "image/png")},
    ).json()["id"]

    response = client.post(
        f"/api/projects/{project_id}/generate/image-edit",
        json={
            "prompt": "参考这张图生成同风格海报",
            "model": "openai",
            "source_image_asset_ids": [source_asset_id],
            "action_type": "image_to_image",
            "threshold": 0.0,
        },
    )

    assert response.status_code == 202
    task = _wait_for_task(client, response.json()["task_id"])
    assert task["status"] == "succeeded"
    assert task["input"]["action_type"] == "image_to_image"
    assert task["result"]["prompt_skill"]["intent"]["action_type"] == "image_to_image"
    assert task["result"]["image_url"].startswith("/uploads/image-optimizer/")


def test_project_image_edit_rejects_mask_as_source_asset(tmp_path):
    client = _client(tmp_path)
    _register(client, "ada")
    project_id = client.post("/api/projects", json={"name": "Mask"}).json()["id"]
    image = b"\x89PNG\r\n\x1a\n" + b"source-image"
    source_asset_id = client.post(
        f"/api/projects/{project_id}/assets/upload",
        files={"file": ("source.png", image, "image/png")},
    ).json()["id"]

    response = client.post(
        f"/api/projects/{project_id}/generate/image-edit",
        json={
            "prompt": "只修复蒙版区域",
            "model": "openai",
            "source_image_asset_ids": [source_asset_id],
            "mask_asset_id": source_asset_id,
            "action_type": "inpaint",
        },
    )

    assert response.status_code == 422


def test_project_image_edit_rejects_mask_for_non_inpaint_action(tmp_path):
    client = _client(tmp_path)
    _register(client, "ada")
    project_id = client.post("/api/projects", json={"name": "Mask"}).json()["id"]
    image = b"\x89PNG\r\n\x1a\n" + b"source-image"
    source_id = client.post(
        f"/api/projects/{project_id}/assets/upload",
        files={"file": ("source.png", image, "image/png")},
    ).json()["id"]
    mask_id = client.post(
        f"/api/projects/{project_id}/assets/upload",
        files={"file": ("mask.png", image, "image/png")},
    ).json()["id"]

    response = client.post(
        f"/api/projects/{project_id}/generate/image-edit",
        json={
            "prompt": "把背景换成雪山",
            "model": "openai",
            "source_image_asset_ids": [source_id],
            "mask_asset_id": mask_id,
            "action_type": "edit",
        },
    )

    assert response.status_code == 422


def test_project_image_edit_rejects_unowned_source_asset(tmp_path):
    ada_client = _client(tmp_path)
    grace_client = _client(tmp_path)
    _register(ada_client, "ada")
    _register(grace_client, "grace")
    ada_project_id = ada_client.post("/api/projects", json={"name": "Ada"}).json()["id"]
    grace_project_id = grace_client.post("/api/projects", json={"name": "Grace"}).json()["id"]
    image = b"\x89PNG\r\n\x1a\n" + b"source-image"
    source_asset = ada_client.post(
        f"/api/projects/{ada_project_id}/assets/upload",
        files={"file": ("source.png", image, "image/png")},
    ).json()

    response = grace_client.post(
        f"/api/projects/{grace_project_id}/generate/image-edit",
        json={
            "prompt": "把背景换成雪山",
            "model": "openai",
            "source_image_asset_ids": [source_asset["id"]],
        },
    )

    assert response.status_code == 404


def test_project_video_source_converts_local_asset_to_data_url(tmp_path):
    upload_dir = tmp_path / "uploads"
    stored_dir = upload_dir / "image-optimizer"
    stored_dir.mkdir(parents=True)
    image_path = stored_dir / "source.png"
    image_path.write_bytes(b"fake-image")
    settings = Settings(asset_upload_dir=upload_dir)

    source = generation_routes._provider_image_source("/uploads/image-optimizer/source.png", "image/png", settings)

    assert source == "data:image/png;base64,ZmFrZS1pbWFnZQ=="


def test_project_video_generation_rejects_reserved_params(tmp_path):
    client = _client(tmp_path)
    _register(client, "ada")
    project_id = client.post("/api/projects", json={"name": "Video board"}).json()["id"]

    for key in ("image", "model", "prompt"):
        response = client.post(
            f"/api/projects/{project_id}/generate/video",
            json={"prompt": "香水瓶在雾气中缓慢旋转", "params": {key: "override"}},
        )
        assert response.status_code == 400
        assert key in response.json()["detail"]


def test_project_video_generation_uses_mock_video_model(tmp_path):
    client = _client(tmp_path)
    _register(client, "ada")
    project_id = client.post("/api/projects", json={"name": "Video board"}).json()["id"]

    response = client.post(
        f"/api/projects/{project_id}/generate/video",
        json={"prompt": "香水瓶在雾气中缓慢旋转", "source_image_url": "mock://image/source", "duration": 4},
    )

    assert response.status_code == 202
    task = _wait_for_task(client, response.json()["task_id"])
    assets = client.get(f"/api/projects/{project_id}/assets").json()["assets"]

    assert task["status"] == "succeeded"
    assert task["kind"] == "image_to_video"
    assert task["result"]["url"].startswith("mock://video/")
    assert any(asset["kind"] == "video" for asset in assets)


def test_project_video_generation_resolves_owned_source_asset(tmp_path):
    client = _client(tmp_path)
    _register(client, "ada")
    project_id = client.post("/api/projects", json={"name": "Video board"}).json()["id"]
    image_response = client.post(
        f"/api/projects/{project_id}/generate/image",
        json={"input": "一张香水产品图", "model": "openai", "threshold": 0.0, "skip_prompt_evaluation": True},
    )
    _wait_for_task(client, image_response.json()["task_id"])
    image_asset = next(asset for asset in client.get(f"/api/projects/{project_id}/assets").json()["assets"] if asset["kind"] == "image")

    response = client.post(
        f"/api/projects/{project_id}/generate/video",
        json={"prompt": "香水瓶在雾气中缓慢旋转", "source_image_asset_id": image_asset["id"], "duration": 4},
    )

    assert response.status_code == 202
    task = _wait_for_task(client, response.json()["task_id"])
    assert task["status"] == "succeeded"
    assert task["kind"] == "image_to_video"
    assert task["input"]["source_image_asset_id"] == image_asset["id"]
    assert task["input"].get("source_image_url") is None
    assert "data:image" not in str(task["input"])


def test_project_tasks_are_user_scoped(tmp_path):
    ada_client = _client(tmp_path)
    grace_client = _client(tmp_path)
    _register(ada_client, "ada")
    _register(grace_client, "grace")
    project_id = ada_client.post("/api/projects", json={"name": "Perfume launch"}).json()["id"]
    response = ada_client.post(
        f"/api/projects/{project_id}/generate/video",
        json={"prompt": "香水瓶在雾气中缓慢旋转", "duration": 4},
    )
    task_id = response.json()["task_id"]

    assert grace_client.get(f"/api/tasks/{task_id}").status_code == 404
    assert grace_client.get(f"/api/tasks/{task_id}/history").status_code == 404
