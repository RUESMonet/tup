import asyncio
import json
import sqlite3
import time
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import src.dependencies as dependencies
from src.api import canvas_routes
from src.api import image_routes as routes
from src.config import Settings
from src.main import create_app
from src.models.canvas import CanvasGenerateImageRequest, CanvasStoryboardImagePromptRequest, CanvasStoryboardVideoPromptRequest
from src.models.project import AssetKind, TaskKind
from src.services.billing_repository import BillingRepository
from src.services.billing_service import BillingService
from src.services.canvas_repository import CanvasRepository
from src.services.database import SQLiteDatabase
from src.services.project_repository import ProjectRepository


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


def _project(client: TestClient, name: str = "Design system") -> str:
    response = client.post("/api/projects", json={"name": name})
    assert response.status_code == 201
    return response.json()["id"]


def _canvas(client: TestClient, project_id: str, name: str = "Main board") -> str:
    response = client.post(f"/api/projects/{project_id}/canvases", json={"name": name})
    assert response.status_code == 201
    return response.json()["id"]


def _owner_id(tmp_path, username: str = "ada") -> str:
    with sqlite3.connect(tmp_path / "app.db") as connection:
        connection.row_factory = sqlite3.Row
        return connection.execute("SELECT id FROM users WHERE username = ?", (username,)).fetchone()["id"]


def _wait_for_task(client: TestClient, task_id: str) -> dict:
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        response = client.get(f"/api/tasks/{task_id}")
        assert response.status_code == 200
        payload = response.json()
        if payload["status"] in {"succeeded", "failed"}:
            return payload
        time.sleep(0.05)
    raise AssertionError("task did not finish")


class _Dumpable:
    def __init__(self, payload):
        self.payload = payload

    def model_dump(self, mode="json"):
        return self.payload


def test_canvas_image_batch_repository_records_candidate_selection_lineage(tmp_path):
    client = _client(tmp_path)
    _register(client, "ada")
    project_id = _project(client)
    canvas_id = _canvas(client, project_id)
    source = client.post(f"/api/canvases/{canvas_id}/nodes", json={"type": "brief", "title": "Prompt", "position": {"x": 0, "y": 0}, "payload": {"prompt": "高端香水海报"}}).json()
    owner_id = _owner_id(tmp_path)
    database = SQLiteDatabase(tmp_path / "app.db")
    projects = ProjectRepository(database)
    canvases = CanvasRepository(database)
    first_asset = projects.create_asset(owner_id, project_id, AssetKind.image, "/uploads/image-optimizer/first.png", "image/png", {"source": "test"})
    second_asset = projects.create_asset(owner_id, project_id, AssetKind.image, "/uploads/image-optimizer/second.png", "image/png", {"source": "test"})

    batch = canvases.create_image_batch(owner_id, canvas_id, [source["id"]], None, "task-batch", "final prompt", {"n": 2})
    first = canvases.create_image_candidate(owner_id, batch.id, first_asset.id, "task-1", 0, "prompt a", 0.81, {"variant": "a"})
    second = canvases.create_image_candidate(owner_id, batch.id, second_asset.id, "task-2", 1, "prompt b", 0.91, {"variant": "b"})
    selected = canvases.set_image_candidate_status(owner_id, canvas_id, batch.id, second.id, "selected", "best composition", {"x": 420, "y": 0})
    batches = canvases.list_image_batches(owner_id, canvas_id)
    canvas = client.get(f"/api/canvases/{canvas_id}").json()

    assert batch.status == "pending"
    assert first.status == "candidate"
    assert selected.status == "selected"
    assert selected.node_id
    assert [candidate.status for candidate in batches[0].candidates] == ["candidate", "selected"]
    selected_node = next(node for node in canvas["nodes"] if node["id"] == selected.node_id)
    assert selected_node["type"] == "selected_image"
    assert selected_node["payload"]["candidate_id"] == second.id
    assert selected_node["payload"]["batch_id"] == batch.id
    assert canvas["edges"][0]["type"] == "selected_candidate"


def test_canvas_image_batch_rejects_foreign_candidate_selection(tmp_path):
    ada_client = _client(tmp_path)
    grace_client = _client(tmp_path)
    _register(ada_client, "ada")
    _register(grace_client, "grace")
    ada_project_id = _project(ada_client, "Ada")
    grace_project_id = _project(grace_client, "Grace")
    ada_canvas_id = _canvas(ada_client, ada_project_id)
    grace_canvas_id = _canvas(grace_client, grace_project_id)
    ada_owner = _owner_id(tmp_path, "ada")
    grace_owner = _owner_id(tmp_path, "grace")
    database = SQLiteDatabase(tmp_path / "app.db")
    projects = ProjectRepository(database)
    canvases = CanvasRepository(database)
    ada_batch = canvases.create_image_batch(ada_owner, ada_canvas_id, [], None, "task-a", "prompt", {"n": 1})
    grace_batch = canvases.create_image_batch(grace_owner, grace_canvas_id, [], None, "task-g", "prompt", {"n": 1})
    grace_asset = projects.create_asset(grace_owner, grace_project_id, AssetKind.image, "/uploads/image-optimizer/grace.png", "image/png", {})
    grace_candidate = canvases.create_image_candidate(grace_owner, grace_batch.id, grace_asset.id, "task-g", 0, "prompt", 0.8, {})

    selected = canvases.set_image_candidate_status(ada_owner, ada_canvas_id, ada_batch.id, grace_candidate.id, "selected", "wrong owner", {"x": 0, "y": 0})
    ada_batches = canvases.list_image_batches(ada_owner, ada_canvas_id)
    grace_batches = canvases.list_image_batches(grace_owner, grace_canvas_id)

    assert selected is None
    assert ada_batches[0].candidates == []
    assert grace_batches[0].candidates[0].status == "candidate"


def test_canvas_image_batch_blocks_selecting_candidates_from_failed_batch(tmp_path):
    client = _client(tmp_path)
    _register(client, "ada")
    project_id = _project(client)
    canvas_id = _canvas(client, project_id)
    source = client.post(
        f"/api/canvases/{canvas_id}/nodes",
        json={"type": "brief", "title": "Prompt", "position": {"x": 0, "y": 0}, "payload": {"prompt": "高端香水海报"}},
    ).json()
    owner_id = _owner_id(tmp_path)
    database = SQLiteDatabase(tmp_path / "app.db")
    projects = ProjectRepository(database)
    canvases = CanvasRepository(database)
    asset = projects.create_asset(owner_id, project_id, AssetKind.image, "/uploads/image-optimizer/failed.png", "image/png", {"source": "test"})
    batch = canvases.create_image_batch(owner_id, canvas_id, [source["id"]], None, "task-batch", "prompt", {"n": 1}, status="failed")
    candidate = canvases.create_image_candidate(owner_id, batch.id, asset.id, "task-batch", 0, "prompt", 0.8, {"variant": "a"})

    response = client.patch(
        f"/api/canvases/{canvas_id}/image-batches/{batch.id}/candidates/{candidate.id}",
        json={"status": "selected", "reason": "should be blocked", "position": {"x": 420, "y": 0}},
    )
    canvas = client.get(f"/api/canvases/{canvas_id}").json()

    assert response.status_code == 409
    assert response.json()["detail"] == "Only succeeded image batches can be selected"
    assert all(node["type"] != "selected_image" for node in canvas["nodes"])


def test_create_canvas_image_batch_marks_task_failed_and_refunds_when_batch_record_is_missing(tmp_path, monkeypatch):
    client = _client(tmp_path)
    _register(client, "ada")
    project_id = _project(client)
    canvas_id = _canvas(client, project_id)
    source = client.post(
        f"/api/canvases/{canvas_id}/nodes",
        json={"type": "storyboard", "title": "Shot 01", "position": {"x": 0, "y": 0}, "payload": {"prompt": "高端香水海报"}},
    ).json()
    original_create_image_batch = CanvasRepository.create_image_batch

    def _return_none(*args, **kwargs):
        return None

    monkeypatch.setattr(CanvasRepository, "create_image_batch", _return_none)
    response = client.post(
        f"/api/canvases/{canvas_id}/image-batches",
        json={"selected_node_ids": [source["id"]], "root_node_id": source["id"], "model": "openai", "threshold": 0, "max_iter": 1, "skip_prompt_evaluation": True},
    )
    monkeypatch.setattr(CanvasRepository, "create_image_batch", original_create_image_batch)

    owner_id = _owner_id(tmp_path)
    task = ProjectRepository(SQLiteDatabase(tmp_path / "app.db")).list_tasks(owner_id, project_id)[0]
    transactions = BillingRepository(SQLiteDatabase(tmp_path / "app.db")).list_transactions(owner_id, limit=10)

    assert response.status_code == 404
    assert task.status == "failed"
    assert transactions[0].direction == "credit"
    assert transactions[1].direction == "debit"
    assert transactions[0].amount == transactions[1].amount
    assert transactions[0].task_id == transactions[1].task_id == task.task_id



def test_canvas_image_generation_winner_survives_duplicate_worker_loss(tmp_path):
    client = _client(tmp_path)
    _register(client, "ada")
    project_id = _project(client)
    canvas_id = _canvas(client, project_id)
    source = client.post(
        f"/api/canvases/{canvas_id}/nodes",
        json={"type": "storyboard", "title": "Shot 01", "position": {"x": 0, "y": 0}, "payload": {"prompt": "高端香水海报"}},
    ).json()
    owner_id = _owner_id(tmp_path)
    settings = Settings(
        auth_required=False,
        rate_limit_requests=1000,
        database_path=tmp_path / "app.db",
        asset_upload_dir=tmp_path / "uploads",
        use_mock_images=True,
        use_mock_videos=True,
        secure_session_cookies=False,
    )
    database = SQLiteDatabase(tmp_path / "app.db")
    canvases = CanvasRepository(database)
    projects = ProjectRepository(database)
    billing = BillingService(BillingRepository(database), settings)
    charge = billing.charge_for_action(owner_id, project_id, "canvas_image", {"workflow": "canvas_image_generation", "canvas_id": canvas_id})
    task = projects.create_task(
        owner_id,
        project_id,
        TaskKind.image,
        {"credit_transaction_id": charge.id, "canvas_id": canvas_id},
        charge.amount,
        charge.amount,
    )
    billing.attach_task(owner_id, charge.id, task.task_id)
    winner = canvases.create_generated_image_result(
        owner_id,
        project_id,
        canvas_id,
        [source["id"]],
        "/uploads/image-optimizer/winner-image.png",
        "image/png",
        task.task_id,
        "winner prompt",
        {"x": 420, "y": 0},
    )
    assert winner is not None
    winner_node, winner_asset_id = winner

    class _RaceProjectRepository:
        def __init__(self, base):
            self.base = base

        def __getattr__(self, name):
            return getattr(self.base, name)

        def set_task_succeeded(self, task_id, result, history=None):
            self.base.set_task_failed(task_id, "recovered elsewhere")
            return False

    class _ImagePipeline:
        async def run(self, prompt_request, model_id, threshold, max_iter, skip_prompt_evaluation=False):
            image = SimpleNamespace(
                b64_json="iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+a1n0AAAAASUVORK5CYII=",
                url=None,
                metadata={"media_type": "image/png"},
            )
            result = SimpleNamespace(
                image=image,
                final_prompt="loser prompt",
                score=9.1,
                iterations=1,
                prompt_report=SimpleNamespace(score=10.0, model_dump=lambda mode="json": {"score": 10.0}),
                optimization_trace=None,
                prompt_history=[],
            )
            prompt_skill = SimpleNamespace(quality_gates=[], model_dump=lambda mode="json": {"quality_gates": [], "final_english_prompt": "loser prompt"})
            return result, prompt_skill

    request = CanvasGenerateImageRequest(
        selected_node_ids=[source["id"]],
        root_node_id=source["id"],
        model="openai",
        threshold=0,
        max_iter=1,
        skip_prompt_evaluation=True,
    )
    compiled = SimpleNamespace(final_prompt="prompt", creative_graph=SimpleNamespace(references=[], character_anchors=[], nodes=[SimpleNamespace(position={"x": 0, "y": 0})]))

    asyncio.run(
        canvas_routes._run_canvas_image_task(
            owner_id,
            task.task_id,
            canvas_id,
            request,
            compiled,
            object(),
            charge.id,
            canvases,
            _RaceProjectRepository(projects),
            _ImagePipeline(),
            billing,
            settings,
        )
    )

    final_task = projects.get_task(owner_id, task.task_id)
    canvas = canvases.get_canvas(owner_id, canvas_id)
    assets = projects.list_assets(owner_id, project_id)

    assert final_task is not None
    assert final_task.status == "failed"
    assert any(node.id == winner_node.id and node.type == "generated_image" for node in canvas.nodes)
    assert any(asset.id == winner_asset_id for asset in assets)



def test_canvas_image_generation_race_cleanup_removes_generated_side_effects(tmp_path):
    client = _client(tmp_path)
    _register(client, "ada")
    project_id = _project(client)
    canvas_id = _canvas(client, project_id)
    source = client.post(
        f"/api/canvases/{canvas_id}/nodes",
        json={"type": "storyboard", "title": "Shot 01", "position": {"x": 0, "y": 0}, "payload": {"prompt": "高端香水海报"}},
    ).json()
    owner_id = _owner_id(tmp_path)
    settings = Settings(
        auth_required=False,
        rate_limit_requests=1000,
        database_path=tmp_path / "app.db",
        asset_upload_dir=tmp_path / "uploads",
        use_mock_images=True,
        use_mock_videos=True,
        secure_session_cookies=False,
    )
    database = SQLiteDatabase(tmp_path / "app.db")
    canvases = CanvasRepository(database)
    projects = ProjectRepository(database)
    billing = BillingService(BillingRepository(database), settings)
    charge = billing.charge_for_action(owner_id, project_id, "canvas_image", {"source": "canvas_image", "canvas_id": canvas_id})
    task = projects.create_task(
        owner_id,
        project_id,
        TaskKind.image,
        {"credit_transaction_id": charge.id, "canvas_id": canvas_id},
        charge.amount,
        charge.amount,
    )
    billing.attach_task(owner_id, charge.id, task.task_id)

    class _RacePipeline:
        async def run(self, prompt_request, model_id, threshold, max_iter, skip_prompt_evaluation=False):
            billing.refund_failed_task(owner_id, charge.id, task.task_id, "recovered elsewhere")
            projects.set_task_failed(task.task_id, "recovered elsewhere")
            image = SimpleNamespace(
                b64_json="iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+a1n0AAAAASUVORK5CYII=",
                url=None,
                metadata={"media_type": "image/png"},
            )
            result = SimpleNamespace(
                image=image,
                final_prompt="Recovered prompt",
                score=9.1,
                iterations=1,
                prompt_report=SimpleNamespace(score=10.0, model_dump=lambda mode="json": {"score": 10.0}),
                optimization_trace=None,
                prompt_history=[],
            )
            prompt_skill = SimpleNamespace(quality_gates=[], model_dump=lambda mode="json": {"quality_gates": [], "final_english_prompt": "Recovered prompt"})
            return result, prompt_skill

    request = CanvasGenerateImageRequest(
        selected_node_ids=[source["id"]],
        root_node_id=source["id"],
        model="openai",
        threshold=0,
        max_iter=1,
        skip_prompt_evaluation=True,
    )
    compiled = SimpleNamespace(final_prompt="prompt", creative_graph=SimpleNamespace(references=[], character_anchors=[], nodes=[SimpleNamespace(position={"x": 0, "y": 0})]))

    asyncio.run(
        canvas_routes._run_canvas_image_task(
            owner_id,
            task.task_id,
            canvas_id,
            request,
            compiled,
            object(),
            charge.id,
            canvases,
            projects,
            _RacePipeline(),
            billing,
            settings,
        )
    )

    final_task = projects.get_task(owner_id, task.task_id)
    canvas = canvases.get_canvas(owner_id, canvas_id)
    assets = projects.list_assets(owner_id, project_id)
    transactions = BillingRepository(database).list_transactions(owner_id, limit=10)

    assert final_task is not None
    assert final_task.status == "failed"
    assert all(node.type != "generated_image" for node in canvas.nodes)
    assert assets == []
    assert transactions[0].direction == "credit"
    assert transactions[1].direction == "debit"



def test_canvas_image_batch_api_generates_candidates_and_selects_one(tmp_path):
    client = _client(tmp_path)
    _register(client, "ada")
    project_id = _project(client)
    canvas_id = _canvas(client, project_id)
    source = client.post(f"/api/canvases/{canvas_id}/nodes", json={"type": "brief", "title": "Batch prompt", "position": {"x": 0, "y": 0}, "payload": {"prompt": "高端香水海报，电影级灯光"}}).json()

    created = client.post(
        f"/api/canvases/{canvas_id}/image-batches",
        json={"selected_node_ids": [source["id"]], "model": "openai", "threshold": 0.0, "max_iter": 1, "params": {"n": 2}, "skip_prompt_evaluation": True},
    )
    listed = client.get(f"/api/canvases/{canvas_id}/image-batches")
    candidates = listed.json()["batches"][0]["candidates"]
    selected = client.patch(
        f"/api/canvases/{canvas_id}/image-batches/{created.json()['id']}/candidates/{candidates[0]['id']}",
        json={"status": "selected", "reason": "best hero frame", "position": {"x": 420, "y": 0}},
    )
    canvas = client.get(f"/api/canvases/{canvas_id}")

    assert created.status_code == 202
    assert created.json()["task_id"]
    assert listed.status_code == 200
    assert listed.json()["batches"][0]["status"] == "succeeded"
    assert len(candidates) == 2
    assert all(candidate["status"] == "candidate" for candidate in candidates)
    video = client.post(
        f"/api/canvases/{canvas_id}/generate/video",
        json={"prompt": "慢速推进镜头，保持香水瓶高级质感", "source_candidate_id": candidates[0]["id"], "duration": 3},
    )
    canvas_after_video = client.get(f"/api/canvases/{canvas_id}")
    final_submission = client.post(f"/api/canvases/{canvas_id}/final-submit", json={"selected_node_ids": [source["id"]]})

    assert selected.status_code == 200
    assert selected.json()["status"] == "selected"
    assert selected.json()["node_id"]
    assert any(node["type"] == "selected_image" and node["payload"]["candidate_id"] == candidates[0]["id"] for node in canvas.json()["nodes"])
    assert video.status_code == 202
    assert video.json()["task_id"]
    assert any(node["type"] == "generated_video" and node["payload"]["source_asset_id"] == candidates[0]["asset_id"] for node in canvas_after_video.json()["nodes"])
    assert any(edge["type"] == "video_from_image" for edge in canvas_after_video.json()["edges"])
    assert final_submission.status_code == 201
    lineage = final_submission.json()["production_lineage"]
    assert lineage["image_batches"][0]["id"] == created.json()["id"]
    assert lineage["selected_images"][0]["id"] == candidates[0]["id"]
    assert lineage["video_outputs"][0]["type"] == "generated_video"
    assert {edge["type"] for edge in lineage["lineage_edges"]} == {"selected_candidate", "video_from_image"}


def test_canvas_image_batch_failure_removes_generated_files(tmp_path, monkeypatch):
    client = _client(tmp_path)
    _register(client, "ada")
    project_id = _project(client)
    canvas_id = _canvas(client, project_id)
    source = client.post(
        f"/api/canvases/{canvas_id}/nodes",
        json={"type": "storyboard", "title": "Shot 01", "position": {"x": 0, "y": 0}, "payload": {"prompt": "高端香水海报"}},
    ).json()
    original_create_image_candidate = CanvasRepository.create_image_candidate

    def _return_none(*args, **kwargs):
        return None

    monkeypatch.setattr(CanvasRepository, "create_image_candidate", _return_none)
    response = client.post(
        f"/api/canvases/{canvas_id}/image-batches",
        json={"selected_node_ids": [source["id"]], "root_node_id": source["id"], "model": "openai", "threshold": 0.0, "max_iter": 1, "params": {"n": 1}, "skip_prompt_evaluation": True},
    )
    monkeypatch.setattr(CanvasRepository, "create_image_candidate", original_create_image_candidate)
    task = _wait_for_task(client, response.json()["task_id"])
    image_dir = tmp_path / "uploads" / "image-optimizer"
    leftovers = sorted(path.name for path in image_dir.glob(f"generated-{response.json()['task_id']}*") if path.is_file()) if image_dir.exists() else []

    assert response.status_code == 202
    assert task["status"] == "failed"
    assert leftovers == []



def test_canvas_image_batch_blocks_when_credits_are_insufficient(tmp_path):
    client = _client(tmp_path)
    _register(client, "ada")
    project_id = _project(client)
    canvas_id = _canvas(client, project_id)
    source = client.post(
        f"/api/canvases/{canvas_id}/nodes",
        json={"type": "storyboard", "title": "Shot 01", "position": {"x": 0, "y": 0}, "payload": {"prompt": "高端香水海报"}},
    ).json()
    with sqlite3.connect(tmp_path / "app.db") as connection:
        user_id = connection.execute("SELECT id FROM users WHERE username = 'ada'").fetchone()[0]
        connection.execute(
            "INSERT INTO credit_accounts (user_id, balance, lifetime_granted, lifetime_spent, updated_at) VALUES (?, 5, 5, 0, '2026-05-21T00:00:00+00:00')",
            (user_id,),
        )

    response = client.post(
        f"/api/canvases/{canvas_id}/image-batches",
        json={"selected_node_ids": [source["id"]], "root_node_id": source["id"], "model": "openai", "threshold": 0, "max_iter": 1, "skip_prompt_evaluation": True},
    )

    assert response.status_code == 402
    assert response.json()["detail"] == "Insufficient credits"


def test_canvas_image_batch_winner_candidates_survive_duplicate_worker_loss(tmp_path):
    client = _client(tmp_path)
    _register(client, "ada")
    project_id = _project(client)
    canvas_id = _canvas(client, project_id)
    source = client.post(
        f"/api/canvases/{canvas_id}/nodes",
        json={"type": "storyboard", "title": "Shot 01", "position": {"x": 0, "y": 0}, "payload": {"prompt": "高端香水海报"}},
    ).json()
    owner_id = _owner_id(tmp_path)
    settings = Settings(
        auth_required=False,
        rate_limit_requests=1000,
        database_path=tmp_path / "app.db",
        asset_upload_dir=tmp_path / "uploads",
        use_mock_images=True,
        use_mock_videos=True,
        secure_session_cookies=False,
    )
    database = SQLiteDatabase(tmp_path / "app.db")
    canvases = CanvasRepository(database)
    projects = ProjectRepository(database)
    billing = BillingService(BillingRepository(database), settings)
    charge = billing.charge_for_action(owner_id, project_id, "canvas_image_batch", {"workflow": "canvas_image_batch_generation", "canvas_id": canvas_id})
    task = projects.create_task(
        owner_id,
        project_id,
        TaskKind.image_batch,
        {"credit_transaction_id": charge.id, "canvas_id": canvas_id},
        charge.amount,
        charge.amount,
    )
    billing.attach_task(owner_id, charge.id, task.task_id)
    batch = canvases.create_image_batch(owner_id, canvas_id, [source["id"]], None, task.task_id, "prompt", {"n": 2})
    winner_asset = projects.create_asset(owner_id, project_id, AssetKind.image, "/uploads/image-optimizer/winner-batch.png", "image/png", {"task_id": task.task_id, "batch_id": batch.id, "canvas_id": canvas_id, "source": "canvas_image_batch", "candidate_index": 5, "source_node_ids": [source["id"]]})
    winner_candidate = canvases.create_image_candidate(owner_id, batch.id, winner_asset.id, task.task_id, 5, "winner prompt", 9.5, {"image_url": winner_asset.url, "media_type": "image/png"})
    assert winner_candidate is not None
    canvases.set_image_batch_status(owner_id, batch.id, "succeeded")

    class _RaceProjectRepository:
        def __init__(self, base):
            self.base = base

        def __getattr__(self, name):
            return getattr(self.base, name)

        def set_task_succeeded(self, task_id, result, history=None):
            self.base.set_task_failed(task_id, "recovered elsewhere")
            return False

    class _BatchPipeline:
        async def run(self, prompt_request, model_id, threshold, max_iter, skip_prompt_evaluation=False):
            image = SimpleNamespace(
                b64_json="iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+a1n0AAAAASUVORK5CYII=",
                url=None,
                metadata={"media_type": "image/png"},
            )
            result = SimpleNamespace(
                image=image,
                final_prompt="loser prompt",
                score=9.1,
                iterations=1,
                prompt_report=SimpleNamespace(score=10.0, model_dump=lambda mode="json": {"score": 10.0}),
                optimization_trace=None,
                prompt_history=[],
            )
            prompt_skill = SimpleNamespace(quality_gates=[], model_dump=lambda mode="json": {"quality_gates": [], "final_english_prompt": "loser prompt"})
            return result, prompt_skill

    request = CanvasGenerateImageRequest(
        selected_node_ids=[source["id"]],
        root_node_id=source["id"],
        model="openai",
        threshold=0,
        max_iter=1,
        params={"n": 1},
        skip_prompt_evaluation=True,
    )
    compiled = SimpleNamespace(final_prompt="prompt", creative_graph=SimpleNamespace(references=[], character_anchors=[], nodes=[SimpleNamespace(position={"x": 0, "y": 0})]))

    asyncio.run(
        canvas_routes._run_canvas_image_batch_task(
            owner_id,
            task.task_id,
            batch.id,
            canvas_id,
            request,
            compiled,
            "prompt",
            charge.id,
            canvases,
            _RaceProjectRepository(projects),
            _BatchPipeline(),
            billing,
            settings,
        )
    )

    final_task = projects.get_task(owner_id, task.task_id)
    final_batch = canvases.get_image_batch(owner_id, canvas_id, batch.id)
    assets = projects.list_assets(owner_id, project_id)

    assert final_task is not None
    assert final_task.status == "failed"
    assert final_batch is not None
    assert any(candidate.id == winner_candidate.id for candidate in final_batch.candidates)
    assert any(asset.id == winner_asset.id for asset in assets)



def test_canvas_image_batch_race_cleanup_removes_files_and_db_side_effects(tmp_path):
    client = _client(tmp_path)
    _register(client, "ada")
    project_id = _project(client)
    canvas_id = _canvas(client, project_id)
    source = client.post(
        f"/api/canvases/{canvas_id}/nodes",
        json={"type": "storyboard", "title": "Shot 01", "position": {"x": 0, "y": 0}, "payload": {"prompt": "高端香水海报"}},
    ).json()
    owner_id = _owner_id(tmp_path)
    settings = Settings(
        auth_required=False,
        rate_limit_requests=1000,
        database_path=tmp_path / "app.db",
        asset_upload_dir=tmp_path / "uploads",
        use_mock_images=True,
        use_mock_videos=True,
        secure_session_cookies=False,
    )
    database = SQLiteDatabase(tmp_path / "app.db")
    canvases = CanvasRepository(database)
    projects = ProjectRepository(database)
    billing = BillingService(BillingRepository(database), settings)
    charge = billing.charge_for_action(owner_id, project_id, "canvas_image_batch", {"source": "canvas_image_batch", "canvas_id": canvas_id})
    task = projects.create_task(
        owner_id,
        project_id,
        TaskKind.image_batch,
        {"credit_transaction_id": charge.id, "canvas_id": canvas_id},
        charge.amount,
        charge.amount,
    )
    billing.attach_task(owner_id, charge.id, task.task_id)
    batch = canvases.create_image_batch(owner_id, canvas_id, [source["id"]], None, task.task_id, "prompt", {"n": 1})

    class _RaceProjectRepository:
        def __init__(self, base):
            self.base = base

        def __getattr__(self, name):
            return getattr(self.base, name)

        def set_task_succeeded(self, task_id, result, history=None):
            self.base.set_task_failed(task_id, "recovered elsewhere")
            return False

    class _BatchPipeline:
        async def run(self, prompt_request, model_id, threshold, max_iter, skip_prompt_evaluation=False):
            image = SimpleNamespace(
                b64_json="iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+a1n0AAAAASUVORK5CYII=",
                url=None,
                metadata={"media_type": "image/png"},
            )
            result = SimpleNamespace(
                image=image,
                final_prompt="Recovered prompt",
                score=9.1,
                iterations=1,
                prompt_report=SimpleNamespace(score=10.0, model_dump=lambda mode="json": {"score": 10.0}),
                optimization_trace=None,
                prompt_history=[],
            )
            prompt_skill = SimpleNamespace(quality_gates=[], model_dump=lambda mode="json": {"quality_gates": [], "final_english_prompt": "Recovered prompt"})
            return result, prompt_skill

    request = CanvasGenerateImageRequest(
        selected_node_ids=[source["id"]],
        root_node_id=source["id"],
        model="openai",
        threshold=0,
        max_iter=1,
        params={"n": 1},
        skip_prompt_evaluation=True,
    )
    compiled = SimpleNamespace(final_prompt="prompt", creative_graph=SimpleNamespace(references=[], character_anchors=[], nodes=[SimpleNamespace(position={"x": 0, "y": 0})]))

    asyncio.run(
        canvas_routes._run_canvas_image_batch_task(
            owner_id,
            task.task_id,
            batch.id,
            canvas_id,
            request,
            compiled,
            "prompt",
            charge.id,
            canvases,
            _RaceProjectRepository(projects),
            _BatchPipeline(),
            billing,
            settings,
        )
    )

    final_task = projects.get_task(owner_id, task.task_id)
    final_batch = canvases.get_image_batch(owner_id, canvas_id, batch.id)
    canvas = canvases.get_canvas(owner_id, canvas_id)
    assets = projects.list_assets(owner_id, project_id)
    image_dir = tmp_path / "uploads" / "image-optimizer"
    leftovers = sorted(path.name for path in image_dir.glob(f"generated-{task.task_id}*") if path.is_file()) if image_dir.exists() else []

    assert final_task is not None
    assert final_task.status == "failed"
    assert final_batch is not None
    assert final_batch.candidates == []
    assert assets == []
    assert all(node.type != "selected_image" for node in canvas.nodes)
    assert leftovers == []



def test_canvas_image_edit_race_cleanup_removes_generated_side_effects(tmp_path):
    client = _client(tmp_path)
    _register(client, "ada")
    project_id = _project(client)
    canvas_id = _canvas(client, project_id)
    owner_id = _owner_id(tmp_path)
    settings = Settings(
        auth_required=False,
        rate_limit_requests=1000,
        database_path=tmp_path / "app.db",
        asset_upload_dir=tmp_path / "uploads",
        use_mock_images=True,
        use_mock_videos=True,
        secure_session_cookies=False,
    )
    database = SQLiteDatabase(tmp_path / "app.db")
    canvases = CanvasRepository(database)
    projects = ProjectRepository(database)
    billing = BillingService(BillingRepository(database), settings)
    source_asset = projects.create_asset(owner_id, project_id, AssetKind.image, "mock://source.png", "image/png", {"source": "test"})
    source_node = client.post(
        f"/api/canvases/{canvas_id}/nodes",
        json={"type": "asset", "title": "Source", "position": {"x": 0, "y": 0}, "payload": {"asset_id": source_asset.id, "asset_kind": "image", "media_type": "image/png"}},
    ).json()
    charge = billing.charge_for_action(owner_id, project_id, "canvas_image_edit", {"source": "canvas_image_edit", "canvas_id": canvas_id})
    task = projects.create_task(
        owner_id,
        project_id,
        TaskKind.image_edit,
        {"credit_transaction_id": charge.id, "canvas_id": canvas_id},
        charge.amount,
        charge.amount,
    )
    billing.attach_task(owner_id, charge.id, task.task_id)

    class _RaceProjectRepository:
        def __init__(self, base):
            self.base = base

        def __getattr__(self, name):
            return getattr(self.base, name)

        def set_task_succeeded(self, task_id, result, history=None):
            self.base.set_task_failed(task_id, "recovered elsewhere")
            return False

    class _EditPipeline:
        async def run(self, prompt_request, model_id, threshold, max_iter, skip_prompt_evaluation=False):
            image = SimpleNamespace(
                b64_json="iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+a1n0AAAAASUVORK5CYII=",
                url=None,
                metadata={"media_type": "image/png"},
            )
            result = SimpleNamespace(
                image=image,
                final_prompt="Recovered edit prompt",
                score=9.1,
                iterations=1,
                prompt_report=SimpleNamespace(score=10.0, model_dump=lambda mode="json": {"score": 10.0}),
                optimization_trace=None,
                prompt_history=[],
            )
            prompt_skill = _Dumpable({"quality_gates": [], "final_english_prompt": "Recovered edit prompt"})
            return result, prompt_skill

    request = SimpleNamespace(
        source_node_ids=[source_node["id"]],
        source_image_asset_ids=[source_asset.id],
        mask_asset_id=None,
        prompt="refine highlights",
        action_type=SimpleNamespace(value="edit"),
        model="openai",
        threshold=0,
        max_iter=1,
        skip_prompt_evaluation=True,
    )

    asyncio.run(
        canvas_routes._run_canvas_image_edit_task(
            owner_id,
            task.task_id,
            canvas_id,
            request,
            object(),
            {"x": 840.0, "y": 120.0},
            charge.id,
            canvases,
            _RaceProjectRepository(projects),
            _EditPipeline(),
            billing,
            settings,
        )
    )

    final_task = projects.get_task(owner_id, task.task_id)
    canvas = canvases.get_canvas(owner_id, canvas_id)
    assets = projects.list_assets(owner_id, project_id)
    image_dir = tmp_path / "uploads" / "image-optimizer"
    leftovers = sorted(path.name for path in image_dir.glob(f"generated-{task.task_id}*") if path.is_file()) if image_dir.exists() else []

    assert final_task is not None
    assert final_task.status == "failed"
    assert all(node.type != "edited_image" for node in canvas.nodes)
    assert [asset.id for asset in assets] == [source_asset.id]
    assert leftovers == []



def test_canvas_video_winner_survives_duplicate_worker_loss(tmp_path):
    client = _client(tmp_path)
    _register(client, "ada")
    project_id = _project(client)
    canvas_id = _canvas(client, project_id)
    owner_id = _owner_id(tmp_path)
    settings = Settings(
        auth_required=False,
        rate_limit_requests=1000,
        database_path=tmp_path / "app.db",
        asset_upload_dir=tmp_path / "uploads",
        use_mock_images=True,
        use_mock_videos=True,
        secure_session_cookies=False,
    )
    database = SQLiteDatabase(tmp_path / "app.db")
    canvases = CanvasRepository(database)
    projects = ProjectRepository(database)
    billing = BillingService(BillingRepository(database), settings)
    source_asset = projects.create_asset(owner_id, project_id, AssetKind.image, "mock://source.png", "image/png", {"source": "test"})
    source_node = client.post(
        f"/api/canvases/{canvas_id}/nodes",
        json={"type": "asset", "title": "Source", "position": {"x": 0, "y": 0}, "payload": {"asset_id": source_asset.id, "asset_kind": "image", "media_type": "image/png"}},
    ).json()
    charge = billing.charge_for_action(owner_id, project_id, "canvas_video", {"workflow": "canvas_video_generation", "canvas_id": canvas_id})
    task = projects.create_task(
        owner_id,
        project_id,
        TaskKind.image_to_video,
        {"credit_transaction_id": charge.id, "canvas_id": canvas_id},
        charge.amount,
        charge.amount,
    )
    billing.attach_task(owner_id, charge.id, task.task_id)
    winner = canvases.create_generated_video_result(
        owner_id,
        project_id,
        canvas_id,
        [source_node["id"]],
        source_asset.id,
        None,
        "mock://winner-video.mp4",
        "video/mp4",
        task.task_id,
        "winner motion",
        {"x": 840, "y": 0},
    )
    assert winner is not None
    winner_node, winner_asset_id = winner

    class _RaceProjectRepository:
        def __init__(self, base):
            self.base = base

        def __getattr__(self, name):
            return getattr(self.base, name)

        def set_task_succeeded(self, task_id, result, history=None):
            self.base.set_task_failed(task_id, "recovered elsewhere")
            return False

    class _VideoRouter:
        async def generate(self, request):
            from src.models.video import VideoResult
            return VideoResult(url="mock://video.mp4", provider_model="mock-video", metadata={})

    request = canvas_routes.VideoGenerateRequest(prompt="slow dolly in", source_image_asset_id=source_asset.id, source_image_url="mock://source.png", duration=5)

    asyncio.run(
        canvas_routes._run_canvas_video_task(
            owner_id,
            task.task_id,
            project_id,
            canvas_id,
            [source_node["id"]],
            source_asset.id,
            None,
            request,
            charge.id,
            canvases,
            _RaceProjectRepository(projects),
            _VideoRouter(),
            billing,
        )
    )

    final_task = projects.get_task(owner_id, task.task_id)
    canvas = canvases.get_canvas(owner_id, canvas_id)
    assets = projects.list_assets(owner_id, project_id)

    assert final_task is not None
    assert final_task.status == "failed"
    assert any(node.id == winner_node.id and node.type == "generated_video" for node in canvas.nodes)
    assert any(asset.id == winner_asset_id for asset in assets)



def test_canvas_video_race_cleanup_removes_generated_side_effects(tmp_path):
    client = _client(tmp_path)
    _register(client, "ada")
    project_id = _project(client)
    canvas_id = _canvas(client, project_id)
    owner_id = _owner_id(tmp_path)
    settings = Settings(
        auth_required=False,
        rate_limit_requests=1000,
        database_path=tmp_path / "app.db",
        asset_upload_dir=tmp_path / "uploads",
        use_mock_images=True,
        use_mock_videos=True,
        secure_session_cookies=False,
    )
    database = SQLiteDatabase(tmp_path / "app.db")
    canvases = CanvasRepository(database)
    projects = ProjectRepository(database)
    billing = BillingService(BillingRepository(database), settings)
    source_asset = projects.create_asset(owner_id, project_id, AssetKind.image, "mock://source.png", "image/png", {"source": "test"})
    source_node = client.post(
        f"/api/canvases/{canvas_id}/nodes",
        json={"type": "asset", "title": "Source", "position": {"x": 0, "y": 0}, "payload": {"asset_id": source_asset.id, "asset_kind": "image", "media_type": "image/png"}},
    ).json()
    charge = billing.charge_for_action(owner_id, project_id, "canvas_video", {"source": "canvas_video", "canvas_id": canvas_id})
    task = projects.create_task(
        owner_id,
        project_id,
        TaskKind.image_to_video,
        {"credit_transaction_id": charge.id, "canvas_id": canvas_id},
        charge.amount,
        charge.amount,
    )
    billing.attach_task(owner_id, charge.id, task.task_id)

    class _RaceProjectRepository:
        def __init__(self, base):
            self.base = base

        def __getattr__(self, name):
            return getattr(self.base, name)

        def set_task_succeeded(self, task_id, result, history=None):
            self.base.set_task_failed(task_id, "recovered elsewhere")
            return False

    class _VideoRouter:
        async def generate(self, request):
            from src.models.video import VideoResult
            return VideoResult(url="mock://video.mp4", provider_model="mock-video", metadata={})

    request = canvas_routes.VideoGenerateRequest(prompt="slow dolly in", source_image_asset_id=source_asset.id, source_image_url="mock://source.png", duration=5)

    asyncio.run(
        canvas_routes._run_canvas_video_task(
            owner_id,
            task.task_id,
            project_id,
            canvas_id,
            [source_node["id"]],
            source_asset.id,
            None,
            request,
            charge.id,
            canvases,
            _RaceProjectRepository(projects),
            _VideoRouter(),
            billing,
        )
    )

    final_task = projects.get_task(owner_id, task.task_id)
    canvas = canvases.get_canvas(owner_id, canvas_id)
    assets = projects.list_assets(owner_id, project_id)

    assert final_task is not None
    assert final_task.status == "failed"
    assert all(node.type != "generated_video" for node in canvas.nodes)
    assert [asset.id for asset in assets] == [source_asset.id]



def test_canvas_generate_image_charges_canvas_image_action(tmp_path):
    client = _client(tmp_path)
    _register(client, "ada")
    project_id = _project(client)
    canvas_id = _canvas(client, project_id)
    node = client.post(
        f"/api/canvases/{canvas_id}/nodes",
        json={"type": "storyboard", "title": "Shot", "position": {"x": 0, "y": 0}, "payload": {"prompt": "高端香水广告图"}},
    ).json()

    response = client.post(
        f"/api/canvases/{canvas_id}/generate/image",
        json={"selected_node_ids": [node["id"]], "model": "openai", "threshold": 0.0, "max_iter": 1, "skip_prompt_evaluation": True},
    )
    task = _wait_for_task(client, response.json()["task_id"])
    owner_id = _owner_id(tmp_path)
    transactions = BillingRepository(SQLiteDatabase(tmp_path / "app.db")).list_transactions(owner_id, limit=10)

    assert response.status_code == 202
    assert transactions[0].action_type == "canvas_image"
    assert transactions[0].task_id == response.json()["task_id"]
    assert transactions[0].metadata["workflow"] == "canvas_image_generation"
    assert transactions[0].metadata["canvas_id"] == canvas_id
    assert task["input"]["credit_transaction_id"] == transactions[0].id
    assert task["input"]["estimated_credit_cost"] == transactions[0].amount
    assert task["cost_estimate"] == transactions[0].amount
    assert task["charged_credits"] == transactions[0].amount



def test_canvas_generate_image_edit_charges_canvas_image_edit_action(tmp_path):
    client = _client(tmp_path)
    _register(client, "ada")
    project_id = _project(client)
    canvas_id = _canvas(client, project_id)
    owner_id = _owner_id(tmp_path)
    asset = ProjectRepository(SQLiteDatabase(tmp_path / "app.db")).create_asset(owner_id, project_id, AssetKind.image, "mock://source.png", "image/png", {"source": "test"})
    source = client.post(
        f"/api/canvases/{canvas_id}/nodes",
        json={"type": "asset", "title": "Source", "position": {"x": 0, "y": 0}, "payload": {"asset_id": asset.id, "asset_kind": "image", "media_type": "image/png"}},
    ).json()

    response = client.post(
        f"/api/canvases/{canvas_id}/generate/image-edit",
        json={
            "prompt": "refine highlights",
            "source_node_ids": [source["id"]],
            "source_image_asset_ids": [asset.id],
            "model": "openai",
            "threshold": 0.0,
            "max_iter": 1,
            "skip_prompt_evaluation": True,
        },
    )
    task = _wait_for_task(client, response.json()["task_id"])
    transactions = BillingRepository(SQLiteDatabase(tmp_path / "app.db")).list_transactions(owner_id, limit=10)

    assert response.status_code == 202
    assert transactions[0].action_type == "canvas_image_edit"
    assert transactions[0].task_id == response.json()["task_id"]
    assert transactions[0].metadata["workflow"] == "canvas_image_edit_generation"
    assert transactions[0].metadata["canvas_id"] == canvas_id
    assert task["input"]["credit_transaction_id"] == transactions[0].id
    assert task["input"]["estimated_credit_cost"] == transactions[0].amount
    assert task["cost_estimate"] == transactions[0].amount
    assert task["charged_credits"] == transactions[0].amount



def test_canvas_image_batch_charges_canvas_image_batch_action(tmp_path):
    client = _client(tmp_path)
    _register(client, "ada")
    project_id = _project(client)
    canvas_id = _canvas(client, project_id)
    node = client.post(
        f"/api/canvases/{canvas_id}/nodes",
        json={"type": "storyboard", "title": "Shot", "position": {"x": 0, "y": 0}, "payload": {"prompt": "高端香水广告图"}},
    ).json()

    response = client.post(
        f"/api/canvases/{canvas_id}/image-batches",
        json={"selected_node_ids": [node["id"]], "model": "openai", "threshold": 0.0, "max_iter": 1, "params": {"n": 1}, "skip_prompt_evaluation": True},
    )
    task = _wait_for_task(client, response.json()["task_id"])
    owner_id = _owner_id(tmp_path)
    transactions = BillingRepository(SQLiteDatabase(tmp_path / "app.db")).list_transactions(owner_id, limit=10)

    assert response.status_code == 202
    assert transactions[0].action_type == "canvas_image_batch"
    assert transactions[0].task_id == response.json()["task_id"]
    assert transactions[0].metadata["workflow"] == "canvas_image_batch_generation"
    assert transactions[0].metadata["canvas_id"] == canvas_id
    assert task["input"]["credit_transaction_id"] == transactions[0].id
    assert task["input"]["estimated_credit_cost"] == transactions[0].amount
    assert task["cost_estimate"] == transactions[0].amount
    assert task["charged_credits"] == transactions[0].amount



def test_canvas_video_generation_charges_canvas_video_action(tmp_path):
    client = _client(tmp_path)
    _register(client, "ada")
    project_id = _project(client)
    canvas_id = _canvas(client, project_id)
    owner_id = _owner_id(tmp_path)
    storyboard = client.post(
        f"/api/canvases/{canvas_id}/nodes",
        json={
            "type": "storyboard",
            "title": "Shot 01",
            "position": {"x": 0, "y": 0},
            "payload": {"prompt": "香水瓶英雄镜头", "camera_motion": "slow dolly in", "subject_action": "瓶身稳定"},
        },
    ).json()
    batch = client.post(
        f"/api/canvases/{canvas_id}/image-batches",
        json={"selected_node_ids": [storyboard["id"]], "model": "openai", "threshold": 0.0, "max_iter": 1, "params": {"n": 1}, "skip_prompt_evaluation": True},
    ).json()
    _wait_for_task(client, batch["task_id"])
    candidate = client.get(f"/api/canvases/{canvas_id}/image-batches").json()["batches"][0]["candidates"][0]
    selected = client.patch(
        f"/api/canvases/{canvas_id}/image-batches/{batch['id']}/candidates/{candidate['id']}",
        json={"status": "selected", "reason": "best hero frame", "position": {"x": 420, "y": 0}},
    ).json()

    response = client.post(
        f"/api/canvases/{canvas_id}/generate/video",
        json={"prompt": "slow dolly in", "source_candidate_id": candidate["id"], "selected_node_ids": [storyboard["id"], selected["node_id"]], "duration": 5},
    )

    assert response.status_code == 202
    task = _wait_for_task(client, response.json()["task_id"])
    transactions = BillingRepository(SQLiteDatabase(tmp_path / "app.db")).list_transactions(owner_id, limit=10)
    assert transactions[0].action_type == "canvas_video"
    assert transactions[0].task_id == response.json()["task_id"]
    assert transactions[0].metadata["workflow"] == "canvas_video_generation"
    assert transactions[0].metadata["canvas_id"] == canvas_id
    assert task["input"]["credit_transaction_id"] == transactions[0].id
    assert task["input"]["estimated_credit_cost"] == transactions[0].amount
    assert task["cost_estimate"] == transactions[0].amount
    assert task["charged_credits"] == transactions[0].amount


def test_canvas_video_generation_uses_video_prompt_artifact(tmp_path):
    client = _client(tmp_path)
    _register(client, "ada")
    project_id = _project(client)
    canvas_id = _canvas(client, project_id)
    storyboard = client.post(
        f"/api/canvases/{canvas_id}/nodes",
        json={
            "type": "storyboard",
            "title": "Shot 01",
            "position": {"x": 0, "y": 0},
            "payload": {"prompt": "香水瓶英雄镜头", "camera_motion": "slow dolly in", "subject_action": "瓶身稳定，光线流动"},
        },
    ).json()
    batch = client.post(
        f"/api/canvases/{canvas_id}/image-batches",
        json={"selected_node_ids": [storyboard["id"]], "model": "openai", "threshold": 0.0, "max_iter": 1, "params": {"n": 1}, "skip_prompt_evaluation": True},
    ).json()
    _wait_for_task(client, batch["task_id"])
    candidate = client.get(f"/api/canvases/{canvas_id}/image-batches").json()["batches"][0]["candidates"][0]
    selected = client.patch(
        f"/api/canvases/{canvas_id}/image-batches/{batch['id']}/candidates/{candidate['id']}",
        json={"status": "selected", "reason": "best hero frame", "position": {"x": 420, "y": 0}},
    ).json()
    optimized = client.post(
        f"/api/canvases/{canvas_id}/storyboard/video-prompt",
        json={"node_id": selected["node_id"], "selected_node_ids": [storyboard["id"], selected["node_id"]], "source_candidate_id": candidate["id"], "duration": 5},
    ).json()

    response = client.post(
        f"/api/canvases/{canvas_id}/generate/video",
        json={"prompt": "manual prompt should be replaced", "prompt_artifact_id": optimized["artifact"]["id"], "source_candidate_id": candidate["id"], "duration": 5},
    )
    task = _wait_for_task(client, response.json()["task_id"])
    canvas = client.get(f"/api/canvases/{canvas_id}").json()
    generated = next(node for node in canvas["nodes"] if node["type"] == "generated_video")

    assert response.status_code == 202
    assert task["input"]["prompt_artifact_id"] == optimized["artifact"]["id"]
    assert task["input"]["prompt"] == optimized["final_prompt"]
    assert generated["payload"]["prompt_artifact_id"] == optimized["artifact"]["id"]
    assert generated["payload"]["motion_prompt"] == optimized["final_prompt"]


def test_storyboard_image_prompt_request_requires_node_in_selection():
    with pytest.raises(ValueError, match="node_id must be included in selected_node_ids"):
        CanvasStoryboardImagePromptRequest(node_id="storyboard-a", selected_node_ids=["storyboard-b"])


def test_storyboard_video_prompt_request_requires_node_in_selection():
    with pytest.raises(ValueError, match="node_id must be included in selected_node_ids"):
        CanvasStoryboardVideoPromptRequest(node_id="storyboard-a", selected_node_ids=["storyboard-b"])


def test_storyboard_video_prompt_request_rejects_duplicate_sources():
    with pytest.raises(ValueError, match="Choose at most one source image"):
        CanvasStoryboardVideoPromptRequest(
            node_id="storyboard-a",
            selected_node_ids=["storyboard-a"],
            source_candidate_id="candidate-a",
            source_image_asset_id="asset-a",
        )


def test_canvas_node_update_accepts_video_prompt_artifact_metadata(tmp_path):
    client = _client(tmp_path)
    _register(client, "ada")
    project_id = _project(client)
    canvas_id = _canvas(client, project_id)
    node = client.post(
        f"/api/canvases/{canvas_id}/nodes",
        json={"type": "shot", "title": "Shot 01", "position": {"x": 0, "y": 0}, "payload": {"motion_prompt": "steady motion"}},
    ).json()

    response = client.patch(
        f"/api/canvases/{canvas_id}/nodes/{node['id']}",
        json={"payload": {"motion_prompt": "slow dolly in", "video_prompt_artifact_id": "artifact-123"}},
    )

    assert response.status_code == 200
    assert response.json()["payload"]["video_prompt_artifact_id"] == "artifact-123"


def test_canvas_storyboard_image_prompt_optimization_persists_version(tmp_path):
    client = _client(tmp_path)
    _register(client, "ada")
    project_id = _project(client)
    canvas_id = _canvas(client, project_id)
    storyboard = client.post(
        f"/api/canvases/{canvas_id}/nodes",
        json={
            "type": "storyboard",
            "title": "Shot 01",
            "position": {"x": 0, "y": 0},
            "payload": {
                "role": "storyboard",
                "prompt": "高端香水广告首镜，黑金背景，产品居中",
                "scene": "黑金摄影棚",
                "camera": "slow dolly in",
                "subject_action": "香水瓶保持稳定，瓶身高光缓慢移动",
                "shot_size": "medium close-up",
                "duration": "5",
                "aspect_ratio": "16:9",
            },
        },
    )
    assert storyboard.status_code == 201

    response = client.post(
        f"/api/canvases/{canvas_id}/storyboard/image-prompt",
        json={
            "node_id": storyboard.json()["id"],
            "selected_node_ids": [storyboard.json()["id"]],
            "root_node_id": storyboard.json()["id"],
            "params": {"size": "1024x1024", "quality": "high"},
            "skip_prompt_evaluation": True,
        },
    )
    listed = client.get(
        f"/api/canvases/{canvas_id}/prompt-artifacts",
        params={"node_id": storyboard.json()["id"], "kind": "storyboard_image_prompt_version"},
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["final_prompt"]
    assert payload["prompt_report"]["score"] == 10.0
    assert payload["artifact"]["kind"] == "storyboard_image_prompt_version"
    assert payload["artifact"]["node_id"] == storyboard.json()["id"]
    assert payload["artifact"]["payload"]["workflow"] == "storyboard_image_prompt_optimization"
    assert payload["artifact"]["payload"]["selected_node_ids"] == [storyboard.json()["id"]]
    assert payload["artifact"]["payload"]["prompt_skill"]["final_english_prompt"] == payload["final_prompt"]
    assert listed.status_code == 200
    assert [artifact["id"] for artifact in listed.json()["artifacts"]] == [payload["artifact"]["id"]]


def test_canvas_storyboard_video_prompt_optimization_persists_version(tmp_path):
    client = _client(tmp_path)
    _register(client, "ada")
    project_id = _project(client)
    canvas_id = _canvas(client, project_id)
    storyboard = client.post(
        f"/api/canvases/{canvas_id}/nodes",
        json={
            "type": "storyboard",
            "title": "Shot 01",
            "position": {"x": 0, "y": 0},
            "payload": {
                "role": "storyboard",
                "prompt": "高端香水广告首镜，黑金背景，产品居中",
                "scene": "黑金摄影棚",
                "camera_motion": "slow dolly in",
                "subject_action": "香水瓶保持稳定，瓶身高光缓慢移动",
                "shot_size": "medium close-up",
                "temporal_rhythm": "calm commercial pacing",
                "ending_state": "clean hero frame",
                "duration": "5",
                "aspect_ratio": "16:9",
            },
        },
    ).json()
    batch = client.post(
        f"/api/canvases/{canvas_id}/image-batches",
        json={
            "selected_node_ids": [storyboard["id"]],
            "model": "openai",
            "threshold": 0.0,
            "max_iter": 1,
            "params": {"n": 1},
            "skip_prompt_evaluation": True,
        },
    ).json()
    _wait_for_task(client, batch["task_id"])
    listed = client.get(f"/api/canvases/{canvas_id}/image-batches").json()["batches"][0]
    candidate = listed["candidates"][0]
    selected = client.patch(
        f"/api/canvases/{canvas_id}/image-batches/{batch['id']}/candidates/{candidate['id']}",
        json={"status": "selected", "reason": "best hero frame", "position": {"x": 420, "y": 0}},
    ).json()

    response = client.post(
        f"/api/canvases/{canvas_id}/storyboard/video-prompt",
        json={
            "node_id": selected["node_id"],
            "selected_node_ids": [storyboard["id"], selected["node_id"]],
            "root_node_id": storyboard["id"],
            "source_candidate_id": candidate["id"],
            "duration": 5,
            "aspect_ratio": "16:9",
        },
    )
    artifacts = client.get(
        f"/api/canvases/{canvas_id}/prompt-artifacts",
        params={"node_id": selected["node_id"], "kind": "storyboard_video_prompt_version"},
    )

    assert response.status_code == 201
    payload = response.json()
    assert "slow dolly in" in payload["final_prompt"]
    assert "香水瓶保持稳定" in payload["final_prompt"]
    assert payload["video_report"]["score"] >= 8.0
    assert payload["artifact"]["kind"] == "storyboard_video_prompt_version"
    assert payload["artifact"]["node_id"] == selected["node_id"]
    assert payload["artifact"]["payload"]["workflow"] == "storyboard_video_prompt_optimization"
    assert payload["artifact"]["payload"]["source_context"]["candidate_id"] == candidate["id"]
    assert payload["artifact"]["payload"]["final_prompt"] == payload["final_prompt"]
    assert artifacts.status_code == 200
    assert [artifact["id"] for artifact in artifacts.json()["artifacts"]] == [payload["artifact"]["id"]]


def test_canvas_storyboard_video_prompt_rejects_unselected_candidate_source(tmp_path):
    client = _client(tmp_path)
    _register(client, "ada")
    project_id = _project(client)
    canvas_id = _canvas(client, project_id)
    storyboard = client.post(
        f"/api/canvases/{canvas_id}/nodes",
        json={
            "type": "storyboard",
            "title": "Shot 01",
            "position": {"x": 0, "y": 0},
            "payload": {
                "role": "storyboard",
                "prompt": "高端香水广告首镜，黑金背景，产品居中",
                "camera_motion": "slow dolly in",
                "subject_action": "香水瓶保持稳定，瓶身高光缓慢移动",
            },
        },
    ).json()
    batch = client.post(
        f"/api/canvases/{canvas_id}/image-batches",
        json={
            "selected_node_ids": [storyboard["id"]],
            "model": "openai",
            "threshold": 0.0,
            "max_iter": 1,
            "params": {"n": 1},
            "skip_prompt_evaluation": True,
        },
    ).json()
    _wait_for_task(client, batch["task_id"])
    listed = client.get(f"/api/canvases/{canvas_id}/image-batches").json()["batches"][0]
    candidate = listed["candidates"][0]
    selected = client.patch(
        f"/api/canvases/{canvas_id}/image-batches/{batch['id']}/candidates/{candidate['id']}",
        json={"status": "selected", "reason": "best hero frame", "position": {"x": 420, "y": 0}},
    ).json()

    response = client.post(
        f"/api/canvases/{canvas_id}/storyboard/video-prompt",
        json={
            "node_id": storyboard["id"],
            "selected_node_ids": [storyboard["id"]],
            "root_node_id": storyboard["id"],
            "source_candidate_id": candidate["id"],
            "duration": 5,
            "aspect_ratio": "16:9",
        },
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "Canvas asset inputs must be bound to the selected non-archived source nodes"


def test_canvas_storyboard_video_prompt_rejects_unselected_direct_asset_source(tmp_path):
    client = _client(tmp_path)
    _register(client, "ada")
    project_id = _project(client)
    canvas_id = _canvas(client, project_id)
    storyboard = client.post(
        f"/api/canvases/{canvas_id}/nodes",
        json={
            "type": "storyboard",
            "title": "Shot 01",
            "position": {"x": 0, "y": 0},
            "payload": {"prompt": "高端香水广告首镜", "camera_motion": "slow dolly in"},
        },
    ).json()
    owner_id = _owner_id(tmp_path)
    projects = ProjectRepository(SQLiteDatabase(tmp_path / "app.db"))
    unbound_asset = projects.create_asset(owner_id, project_id, AssetKind.image, "/uploads/image-optimizer/unbound.png", "image/png", {"source": "test"})

    response = client.post(
        f"/api/canvases/{canvas_id}/storyboard/video-prompt",
        json={
            "node_id": storyboard["id"],
            "selected_node_ids": [storyboard["id"]],
            "root_node_id": storyboard["id"],
            "source_image_asset_id": unbound_asset.id,
            "duration": 5,
            "aspect_ratio": "16:9",
        },
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "Canvas asset inputs must be bound to the selected non-archived source nodes"


def test_canvas_storyboard_video_prompt_rejects_foreign_candidate(tmp_path):
    ada_client = _client(tmp_path)
    grace_client = _client(tmp_path)
    _register(ada_client, "ada")
    _register(grace_client, "grace")
    ada_project_id = _project(ada_client, "Ada")
    grace_project_id = _project(grace_client, "Grace")
    ada_canvas_id = _canvas(ada_client, ada_project_id)
    grace_canvas_id = _canvas(grace_client, grace_project_id)
    ada_node = ada_client.post(
        f"/api/canvases/{ada_canvas_id}/nodes",
        json={"type": "storyboard", "title": "Ada shot", "position": {"x": 0, "y": 0}, "payload": {"prompt": "Ada 私有分镜"}},
    ).json()
    grace_node = grace_client.post(
        f"/api/canvases/{grace_canvas_id}/nodes",
        json={"type": "storyboard", "title": "Grace shot", "position": {"x": 0, "y": 0}, "payload": {"prompt": "Grace 私有分镜"}},
    ).json()
    grace_batch = grace_client.post(
        f"/api/canvases/{grace_canvas_id}/image-batches",
        json={"selected_node_ids": [grace_node["id"]], "model": "openai", "threshold": 0.0, "max_iter": 1, "params": {"n": 1}, "skip_prompt_evaluation": True},
    ).json()
    _wait_for_task(grace_client, grace_batch["task_id"])
    grace_candidate = grace_client.get(f"/api/canvases/{grace_canvas_id}/image-batches").json()["batches"][0]["candidates"][0]

    response = ada_client.post(
        f"/api/canvases/{ada_canvas_id}/storyboard/video-prompt",
        json={"node_id": ada_node["id"], "selected_node_ids": [ada_node["id"]], "source_candidate_id": grace_candidate["id"]},
    )

    assert grace_batch["id"]
    assert response.status_code == 404
    assert response.json()["detail"] == "Source image candidate not found"


def test_canvas_storyboard_image_prompt_rejects_foreign_node(tmp_path):
    ada_client = _client(tmp_path)
    grace_client = _client(tmp_path)
    _register(ada_client, "ada")
    _register(grace_client, "grace")
    ada_project_id = _project(ada_client, "Ada")
    grace_project_id = _project(grace_client, "Grace")
    ada_canvas_id = _canvas(ada_client, ada_project_id)
    grace_canvas_id = _canvas(grace_client, grace_project_id)
    grace_node = grace_client.post(
        f"/api/canvases/{grace_canvas_id}/nodes",
        json={"type": "storyboard", "title": "Private", "position": {"x": 0, "y": 0}, "payload": {"prompt": "私有分镜"}},
    ).json()

    response = ada_client.post(
        f"/api/canvases/{ada_canvas_id}/storyboard/image-prompt",
        json={"node_id": grace_node["id"], "selected_node_ids": [grace_node["id"]], "skip_prompt_evaluation": True},
    )

    assert response.status_code == 404


def test_canvas_generate_image_accepts_prompt_artifact_link(tmp_path):
    client = _client(tmp_path)
    _register(client, "ada")
    project_id = _project(client)
    canvas_id = _canvas(client, project_id)
    node = client.post(
        f"/api/canvases/{canvas_id}/nodes",
        json={"type": "storyboard", "title": "Shot", "position": {"x": 0, "y": 0}, "payload": {"prompt": "高端香水广告图"}},
    ).json()
    optimized = client.post(
        f"/api/canvases/{canvas_id}/storyboard/image-prompt",
        json={"node_id": node["id"], "selected_node_ids": [node["id"]], "skip_prompt_evaluation": True},
    ).json()

    response = client.post(
        f"/api/canvases/{canvas_id}/generate/image",
        json={
            "selected_node_ids": [node["id"]],
            "model": "openai",
            "threshold": 0.0,
            "max_iter": 1,
            "skip_prompt_evaluation": True,
            "prompt_artifact_id": optimized["artifact"]["id"],
        },
    )

    assert response.status_code == 202
    task = _wait_for_task(client, response.json()["task_id"])
    assert task["input"]["prompt_artifact_id"] == optimized["artifact"]["id"]
    assert task["result"]["optimization_trace"]["original_prompt"] == " ".join(optimized["final_prompt"].split())


def test_canvas_generate_image_rejects_foreign_prompt_artifact(tmp_path):
    ada_client = _client(tmp_path)
    grace_client = _client(tmp_path)
    _register(ada_client, "ada")
    _register(grace_client, "grace")
    ada_project_id = _project(ada_client, "Ada")
    grace_project_id = _project(grace_client, "Grace")
    ada_canvas_id = _canvas(ada_client, ada_project_id)
    grace_canvas_id = _canvas(grace_client, grace_project_id)
    grace_node = grace_client.post(
        f"/api/canvases/{grace_canvas_id}/nodes",
        json={"type": "storyboard", "title": "Grace Shot", "position": {"x": 0, "y": 0}, "payload": {"prompt": "Grace 私有分镜"}},
    ).json()
    grace_optimized = grace_client.post(
        f"/api/canvases/{grace_canvas_id}/storyboard/image-prompt",
        json={"node_id": grace_node["id"], "selected_node_ids": [grace_node["id"]], "skip_prompt_evaluation": True},
    ).json()
    ada_node = ada_client.post(
        f"/api/canvases/{ada_canvas_id}/nodes",
        json={"type": "storyboard", "title": "Ada Shot", "position": {"x": 0, "y": 0}, "payload": {"prompt": "Ada 自有分镜"}},
    ).json()

    response = ada_client.post(
        f"/api/canvases/{ada_canvas_id}/generate/image",
        json={
            "selected_node_ids": [ada_node["id"]],
            "model": "openai",
            "threshold": 0.0,
            "max_iter": 1,
            "skip_prompt_evaluation": True,
            "prompt_artifact_id": grace_optimized["artifact"]["id"],
        },
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Prompt artifact not found"


def test_canvas_image_batch_rejects_foreign_prompt_artifact(tmp_path):
    ada_client = _client(tmp_path)
    grace_client = _client(tmp_path)
    _register(ada_client, "ada")
    _register(grace_client, "grace")
    ada_project_id = _project(ada_client, "Ada")
    grace_project_id = _project(grace_client, "Grace")
    ada_canvas_id = _canvas(ada_client, ada_project_id)
    grace_canvas_id = _canvas(grace_client, grace_project_id)
    grace_node = grace_client.post(
        f"/api/canvases/{grace_canvas_id}/nodes",
        json={"type": "storyboard", "title": "Grace Shot", "position": {"x": 0, "y": 0}, "payload": {"prompt": "Grace 私有分镜"}},
    ).json()
    grace_optimized = grace_client.post(
        f"/api/canvases/{grace_canvas_id}/storyboard/image-prompt",
        json={"node_id": grace_node["id"], "selected_node_ids": [grace_node["id"]], "skip_prompt_evaluation": True},
    ).json()
    ada_node = ada_client.post(
        f"/api/canvases/{ada_canvas_id}/nodes",
        json={"type": "storyboard", "title": "Ada Shot", "position": {"x": 0, "y": 0}, "payload": {"prompt": "Ada 自有分镜"}},
    ).json()

    response = ada_client.post(
        f"/api/canvases/{ada_canvas_id}/image-batches",
        json={
            "selected_node_ids": [ada_node["id"]],
            "model": "openai",
            "threshold": 0.0,
            "max_iter": 1,
            "params": {"n": 1},
            "skip_prompt_evaluation": True,
            "prompt_artifact_id": grace_optimized["artifact"]["id"],
        },
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Prompt artifact not found"


def test_canvas_image_batch_records_prompt_artifact_link(tmp_path):
    client = _client(tmp_path)
    _register(client, "ada")
    project_id = _project(client)
    canvas_id = _canvas(client, project_id)
    node = client.post(
        f"/api/canvases/{canvas_id}/nodes",
        json={"type": "storyboard", "title": "Shot", "position": {"x": 0, "y": 0}, "payload": {"prompt": "高端香水广告图"}},
    ).json()
    optimized = client.post(
        f"/api/canvases/{canvas_id}/storyboard/image-prompt",
        json={"node_id": node["id"], "selected_node_ids": [node["id"]], "skip_prompt_evaluation": True},
    ).json()

    response = client.post(
        f"/api/canvases/{canvas_id}/image-batches",
        json={
            "selected_node_ids": [node["id"]],
            "model": "openai",
            "threshold": 0.0,
            "max_iter": 1,
            "params": {"n": 1},
            "skip_prompt_evaluation": True,
            "prompt_artifact_id": optimized["artifact"]["id"],
        },
    )

    assert response.status_code == 202
    assert response.json()["prompt_artifact_id"] == optimized["artifact"]["id"]
    assert response.json()["prompt"] == optimized["final_prompt"]

    listed = client.get(f"/api/canvases/{canvas_id}/image-batches")
    assert listed.status_code == 200
    assert listed.json()["batches"][0]["prompt_artifact_id"] == optimized["artifact"]["id"]
    assert listed.json()["batches"][0]["prompt"] == optimized["final_prompt"]


def test_canvas_video_generation_rejects_oversized_or_deep_params(tmp_path):
    client = _client(tmp_path)
    _register(client, "ada")
    project_id = _project(client)
    canvas_id = _canvas(client, project_id)

    oversized = client.post(
        f"/api/canvases/{canvas_id}/generate/video",
        json={"prompt": "motion", "source_image_asset_id": "asset-1", "params": {"note": "x" * 20001}},
    )
    deep = client.post(
        f"/api/canvases/{canvas_id}/generate/video",
        json={"prompt": "motion", "source_image_asset_id": "asset-1", "params": {"a": {"b": {"c": {"d": {"e": {"f": {"g": {"h": {"i": 1}}}}}}}}}},
    )

    assert oversized.status_code == 422
    assert deep.status_code == 422


def test_canvas_constraint_migration_rebuilds_legacy_edge_table(tmp_path):
    database_path = tmp_path / "legacy.db"
    now = "2026-05-19T00:00:00+00:00"
    with sqlite3.connect(database_path) as connection:
        connection.executescript(
            """
            CREATE TABLE users (
                id TEXT PRIMARY KEY,
                username TEXT NOT NULL UNIQUE COLLATE NOCASE,
                email TEXT NOT NULL UNIQUE COLLATE NOCASE,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL DEFAULT 'user',
                created_at TEXT NOT NULL
            );
            CREATE TABLE projects (
                id TEXT PRIMARY KEY,
                owner_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                name TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE canvases (
                id TEXT PRIMARY KEY,
                owner_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                name TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE canvas_nodes (
                id TEXT PRIMARY KEY,
                canvas_id TEXT NOT NULL REFERENCES canvases(id) ON DELETE CASCADE,
                type TEXT NOT NULL,
                title TEXT NOT NULL,
                position_json TEXT NOT NULL,
                size_json TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE canvas_edges (
                id TEXT PRIMARY KEY,
                canvas_id TEXT NOT NULL REFERENCES canvases(id) ON DELETE CASCADE,
                source_node_id TEXT NOT NULL REFERENCES canvas_nodes(id) ON DELETE CASCADE,
                target_node_id TEXT NOT NULL REFERENCES canvas_nodes(id) ON DELETE CASCADE,
                type TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            """
        )
        connection.execute("INSERT INTO users (id, username, email, password_hash, role, created_at) VALUES (?, ?, ?, ?, ?, ?)", ("user-id", "ada", "ada@example.com", "hash", "user", now))
        connection.execute("INSERT INTO projects (id, owner_id, name, description, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)", ("project-id", "user-id", "Project", "", now, now))
        connection.execute("INSERT INTO canvases (id, owner_id, project_id, name, description, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)", ("canvas-a", "user-id", "project-id", "A", "", now, now))
        connection.execute("INSERT INTO canvases (id, owner_id, project_id, name, description, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)", ("canvas-b", "user-id", "project-id", "B", "", now, now))
        connection.executemany(
            "INSERT INTO canvas_nodes (id, canvas_id, type, title, position_json, size_json, payload_json, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                ("node-a", "canvas-a", "brief", "A", '{"x":0,"y":0}', '{"width":320,"height":180}', "{}", now, now),
                ("node-b", "canvas-a", "brief", "B", '{"x":0,"y":0}', '{"width":320,"height":180}', "{}", now, now),
                ("node-c", "canvas-b", "brief", "C", '{"x":0,"y":0}', '{"width":320,"height":180}', "{}", now, now),
            ],
        )
        connection.executemany(
            "INSERT INTO canvas_edges (id, canvas_id, source_node_id, target_node_id, type, payload_json, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            [
                ("edge-valid", "canvas-a", "node-a", "node-b", "lineage", "{}", now),
                ("edge-invalid", "canvas-a", "node-a", "node-c", "lineage", "{}", now),
            ],
        )

    database = SQLiteDatabase(database_path)
    with database.connect() as connection:
        edge_ids = [row["id"] for row in connection.execute("SELECT id FROM canvas_edges ORDER BY id").fetchall()]
        edge_sql = connection.execute("SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'canvas_edges'").fetchone()["sql"]

    with database.connect() as connection:
        connection.execute("INSERT INTO users (id, username, email, password_hash, role, created_at) VALUES (?, ?, ?, ?, ?, ?)", ("other-user", "grace", "grace@example.com", "hash", "user", now))
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "INSERT INTO canvases (id, owner_id, project_id, name, description, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                ("invalid-canvas", "other-user", "project-id", "Invalid", "", now, now),
            )

    assert edge_ids == ["edge-valid"]
    assert "FOREIGN KEY (source_node_id, canvas_id)" in edge_sql


def test_canvas_routes_require_login_and_project_ownership(tmp_path):
    missing_client = _client(tmp_path)
    ada_client = _client(tmp_path)
    grace_client = _client(tmp_path)
    _register(ada_client, "ada")
    _register(grace_client, "grace")
    project_id = _project(ada_client, "Private launch")

    missing = missing_client.get(f"/api/projects/{project_id}/canvases")
    created = ada_client.post(f"/api/projects/{project_id}/canvases", json={"name": "Campaign canvas"})
    ada_list = ada_client.get(f"/api/projects/{project_id}/canvases")
    grace_list = grace_client.get(f"/api/projects/{project_id}/canvases")
    grace_read = grace_client.get(f"/api/canvases/{created.json()['id']}")

    assert missing.status_code == 401
    assert created.status_code == 201
    assert created.json()["name"] == "Campaign canvas"
    assert ada_list.status_code == 200
    assert ada_list.json()["canvases"][0]["id"] == created.json()["id"]
    assert grace_list.status_code == 404
    assert grace_read.status_code == 404


def test_canvas_returns_nodes_and_edges_for_owner(tmp_path):
    client = _client(tmp_path)
    _register(client, "ada")
    project_id = _project(client)
    canvas_id = _canvas(client, project_id)

    brief = client.post(
        f"/api/canvases/{canvas_id}/nodes",
        json={
            "type": "brief",
            "title": "Perfume hero shot",
            "position": {"x": 120, "y": 80},
            "size": {"width": 320, "height": 180},
            "payload": {"prompt": "高端香水海报", "profile": "product"},
        },
    )
    style = client.post(
        f"/api/canvases/{canvas_id}/nodes",
        json={
            "type": "style_system",
            "title": "Chrome noir",
            "position": {"x": 560, "y": 120},
            "payload": {"lighting": "low-key rim light"},
        },
    )
    edge = client.post(
        f"/api/canvases/{canvas_id}/edges",
        json={"source_node_id": brief.json()["id"], "target_node_id": style.json()["id"], "type": "influences", "payload": {"weight": 0.8}},
    )
    canvas = client.get(f"/api/canvases/{canvas_id}")

    assert brief.status_code == 201
    assert style.status_code == 201
    assert edge.status_code == 201
    assert canvas.status_code == 200
    assert canvas.json()["id"] == canvas_id
    assert [node["title"] for node in canvas.json()["nodes"]] == ["Perfume hero shot", "Chrome noir"]
    assert canvas.json()["nodes"][0]["payload"]["profile"] == "product"
    assert canvas.json()["nodes"][0]["position"] == {"x": 120.0, "y": 80.0}
    assert canvas.json()["edges"][0]["source_node_id"] == brief.json()["id"]
    assert canvas.json()["edges"][0]["target_node_id"] == style.json()["id"]
    assert canvas.json()["edges"][0]["payload"] == {"weight": 0.8}


def test_canvas_node_update_delete_and_bulk_move(tmp_path):
    client = _client(tmp_path)
    _register(client, "ada")
    project_id = _project(client)
    canvas_id = _canvas(client, project_id)
    node = client.post(
        f"/api/canvases/{canvas_id}/nodes",
        json={"type": "asset", "title": "Reference A", "position": {"x": 0, "y": 0}, "payload": {"asset_id": "asset-1"}},
    ).json()

    moved = client.patch(f"/api/canvases/{canvas_id}/nodes/positions", json={"positions": [{"id": node["id"], "position": {"x": 240, "y": -160}}]})
    updated = client.patch(
        f"/api/canvases/{canvas_id}/nodes/{node['id']}",
        json={"title": "Reference A edited", "payload": {"asset_id": "asset-1", "role": "composition_reference"}},
    )
    deleted = client.delete(f"/api/canvases/{canvas_id}/nodes/{node['id']}")
    canvas = client.get(f"/api/canvases/{canvas_id}")

    assert moved.status_code == 200
    assert moved.json()["nodes"][0]["position"] == {"x": 240.0, "y": -160.0}
    assert updated.status_code == 200
    assert updated.json()["title"] == "Reference A edited"
    assert updated.json()["payload"]["role"] == "composition_reference"
    assert deleted.status_code == 204
    assert canvas.json()["nodes"] == []


def test_canvas_edges_must_stay_inside_same_owned_canvas(tmp_path):
    ada_client = _client(tmp_path)
    grace_client = _client(tmp_path)
    _register(ada_client, "ada")
    _register(grace_client, "grace")
    ada_project_id = _project(ada_client, "Ada")
    grace_project_id = _project(grace_client, "Grace")
    first_canvas_id = _canvas(ada_client, ada_project_id, "First")
    second_canvas_id = _canvas(ada_client, ada_project_id, "Second")
    grace_canvas_id = _canvas(grace_client, grace_project_id, "Grace")
    first_node = ada_client.post(f"/api/canvases/{first_canvas_id}/nodes", json={"type": "brief", "title": "A", "position": {"x": 0, "y": 0}}).json()
    second_node = ada_client.post(f"/api/canvases/{second_canvas_id}/nodes", json={"type": "brief", "title": "B", "position": {"x": 0, "y": 0}}).json()
    grace_node = grace_client.post(f"/api/canvases/{grace_canvas_id}/nodes", json={"type": "brief", "title": "G", "position": {"x": 0, "y": 0}}).json()

    cross_canvas = ada_client.post(
        f"/api/canvases/{first_canvas_id}/edges",
        json={"source_node_id": first_node["id"], "target_node_id": second_node["id"], "type": "lineage"},
    )
    cross_user = ada_client.post(
        f"/api/canvases/{first_canvas_id}/edges",
        json={"source_node_id": first_node["id"], "target_node_id": grace_node["id"], "type": "lineage"},
    )

    assert cross_canvas.status_code == 400
    assert cross_user.status_code == 400


def test_canvas_rejects_duplicate_bulk_move_node_ids(tmp_path):
    client = _client(tmp_path)
    _register(client, "ada")
    project_id = _project(client)
    canvas_id = _canvas(client, project_id)
    node = client.post(f"/api/canvases/{canvas_id}/nodes", json={"type": "brief", "title": "A", "position": {"x": 0, "y": 0}}).json()

    response = client.patch(
        f"/api/canvases/{canvas_id}/nodes/positions",
        json={
            "positions": [
                {"id": node["id"], "position": {"x": 100, "y": 100}},
                {"id": node["id"], "position": {"x": 200, "y": 200}},
            ]
        },
    )

    assert response.status_code == 422


def test_canvas_rejects_oversized_node_and_edge_payloads(tmp_path):
    client = _client(tmp_path)
    _register(client, "ada")
    project_id = _project(client)
    canvas_id = _canvas(client, project_id)
    oversized = {"text": "x" * 20001}

    node_response = client.post(
        f"/api/canvases/{canvas_id}/nodes",
        json={"type": "brief", "title": "Oversized", "position": {"x": 0, "y": 0}, "payload": oversized},
    )
    source = client.post(f"/api/canvases/{canvas_id}/nodes", json={"type": "brief", "title": "A", "position": {"x": 0, "y": 0}}).json()
    target = client.post(f"/api/canvases/{canvas_id}/nodes", json={"type": "brief", "title": "B", "position": {"x": 0, "y": 0}}).json()
    edge_response = client.post(
        f"/api/canvases/{canvas_id}/edges",
        json={"source_node_id": source["id"], "target_node_id": target["id"], "type": "lineage", "payload": oversized},
    )

    assert node_response.status_code == 422
    assert edge_response.status_code == 422


def test_canvas_rejects_request_body_before_large_json_parse(tmp_path):
    client = _client(tmp_path)
    _register(client, "ada")
    project_id = _project(client)
    canvas_id = _canvas(client, project_id)

    response = client.post(
        f"/api/canvases/{canvas_id}/nodes",
        json={"type": "brief", "title": "Huge", "position": {"x": 0, "y": 0}, "payload": {"text": "x" * 120000}},
    )

    assert response.status_code == 413


def test_canvas_name_and_node_title_cannot_be_blank(tmp_path):
    client = _client(tmp_path)
    _register(client, "ada")
    project_id = _project(client)
    canvas_id = _canvas(client, project_id)

    blank_canvas = client.post(f"/api/projects/{project_id}/canvases", json={"name": "   "})
    blank_node = client.post(f"/api/canvases/{canvas_id}/nodes", json={"type": "brief", "title": "   ", "position": {"x": 0, "y": 0}})

    assert blank_canvas.status_code == 422
    assert blank_node.status_code == 422


def test_canvas_compile_selected_nodes_creates_prompt_artifact(tmp_path):
    client = _client(tmp_path)
    _register(client, "ada")
    project_id = _project(client)
    canvas_id = _canvas(client, project_id)
    brief = client.post(
        f"/api/canvases/{canvas_id}/nodes",
        json={
            "type": "brief",
            "title": "Noir perfume launch",
            "position": {"x": 80, "y": 120},
            "payload": {"prompt": "为 NOIR BLOOM 香水制作高端海报，黑色石材台面，标题写着\"NOIR BLOOM\"", "profile": "poster"},
        },
    ).json()
    style = client.post(
        f"/api/canvases/{canvas_id}/nodes",
        json={
            "type": "style_system",
            "title": "Luxury rim lighting",
            "position": {"x": 500, "y": 140},
            "payload": {"lighting": "dramatic gold rim light", "style": "premium fragrance campaign", "color_palette": "black, gold, deep amber"},
        },
    ).json()
    asset = client.post(
        f"/api/canvases/{canvas_id}/nodes",
        json={
            "type": "asset",
            "title": "Bottle reference",
            "position": {"x": 900, "y": 160},
            "payload": {"asset_id": "asset-1", "media_type": "image/png", "role": "product_identity_reference"},
        },
    ).json()
    out_of_selection = client.post(
        f"/api/canvases/{canvas_id}/nodes",
        json={"type": "brief", "title": "Not selected", "position": {"x": 0, "y": 0}, "payload": {"prompt": "不要进入本次编译"}},
    ).json()
    selected_edge = client.post(
        f"/api/canvases/{canvas_id}/edges",
        json={"source_node_id": brief["id"], "target_node_id": style["id"], "type": "influences", "payload": {"weight": 0.9}},
    ).json()
    client.post(
        f"/api/canvases/{canvas_id}/edges",
        json={"source_node_id": brief["id"], "target_node_id": out_of_selection["id"], "type": "ignored"},
    )

    response = client.post(
        f"/api/canvases/{canvas_id}/compile",
        json={"selected_node_ids": [brief["id"], style["id"], asset["id"]], "artifact_node_id": brief["id"]},
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["creative_graph"]["primary_brief"] == "为 NOIR BLOOM 香水制作高端海报，黑色石材台面，标题写着\"NOIR BLOOM\""
    assert [node["id"] for node in payload["creative_graph"]["nodes"]] == [brief["id"], style["id"], asset["id"]]
    assert [edge["id"] for edge in payload["creative_graph"]["edges"]] == [selected_edge["id"]]
    assert payload["prompt_spec"]["scene_graph"]["hero_subject"].startswith("为 NOIR BLOOM 香水制作高端海报")
    assert payload["prompt_spec"]["style_system"]["lighting"] == "dramatic gold rim light"
    assert "NOIR BLOOM" in payload["final_prompt"]
    assert payload["artifact"]["kind"] == "canvas_prompt_compile"
    assert payload["artifact"]["node_id"] == brief["id"]

    with sqlite3.connect(tmp_path / "app.db") as connection:
        connection.row_factory = sqlite3.Row
        row = connection.execute("SELECT owner_id, project_id, canvas_id, node_id, kind, payload_json FROM prompt_artifacts").fetchone()
    artifact_payload = json.loads(row["payload_json"])
    assert row["project_id"] == project_id
    assert row["canvas_id"] == canvas_id
    assert row["node_id"] == brief["id"]
    assert artifact_payload["selected_node_ids"] == [brief["id"], style["id"], asset["id"]]
    assert artifact_payload["final_prompt"] == payload["final_prompt"]


def test_canvas_compile_does_not_use_artifact_node_as_graph_root(tmp_path):
    client = _client(tmp_path)
    _register(client, "ada")
    project_id = _project(client)
    canvas_id = _canvas(client, project_id)
    brief = client.post(
        f"/api/canvases/{canvas_id}/nodes",
        json={"type": "brief", "title": "Brief", "position": {"x": 0, "y": 0}, "payload": {"prompt": "主简报"}},
    ).json()
    style = client.post(
        f"/api/canvases/{canvas_id}/nodes",
        json={"type": "style_system", "title": "Attach artifact here", "position": {"x": 360, "y": 0}, "payload": {"style": "高端极简"}},
    ).json()
    client.post(f"/api/canvases/{canvas_id}/edges", json={"source_node_id": brief["id"], "target_node_id": style["id"], "type": "influences"})

    response = client.post(
        f"/api/canvases/{canvas_id}/compile",
        json={"selected_node_ids": [brief["id"], style["id"]], "artifact_node_id": style["id"]},
    )

    assert response.status_code == 201
    payload = response.json()
    assert [node["id"] for node in payload["creative_graph"]["nodes"]] == [brief["id"], style["id"]]
    assert payload["artifact"]["node_id"] == style["id"]


def test_canvas_final_submit_returns_json_artifact_without_task(tmp_path):
    client = _client(tmp_path)
    _register(client, "ada")
    project_id = _project(client)
    canvas_id = _canvas(client, project_id)
    brief = client.post(
        f"/api/canvases/{canvas_id}/nodes",
        json={"type": "brief", "title": "Final brief", "position": {"x": 0, "y": 0}, "payload": {"prompt": "用 @bottle 做一张高端香水海报", "profile": "poster"}},
    ).json()
    asset = client.post(
        f"/api/canvases/{canvas_id}/nodes",
        json={
            "type": "asset",
            "title": "Bottle",
            "position": {"x": 360, "y": 0},
            "payload": {"asset_id": "asset-1", "media_type": "image/png", "mention_label": "bottle", "reference_role": "product"},
        },
    ).json()

    response = client.post(
        f"/api/canvases/{canvas_id}/final-submit",
        json={"selected_node_ids": [brief["id"], asset["id"]], "artifact_node_id": brief["id"], "profile": "poster", "generation": {"enabled": False, "params": {"size": "1024x1024"}}},
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["canvas_id"] == canvas_id
    assert payload["project_id"] == project_id
    assert payload["selected_node_ids"] == [brief["id"], asset["id"]]
    assert payload["asset_references"][0]["mention_label"] == "bottle"
    assert payload["prompt_spec"]["intent"]["profile"] == "poster"
    assert "@bottle as product_reference" in payload["final_prompt"]
    assert payload["generation_params"] == {"size": "1024x1024"}
    assert payload["artifact"]["kind"] == "canvas_final_submission"
    assert payload["task"] is None

    with sqlite3.connect(tmp_path / "app.db") as connection:
        connection.row_factory = sqlite3.Row
        row = connection.execute("SELECT kind, payload_json FROM prompt_artifacts").fetchone()
    artifact_payload = json.loads(row["payload_json"])
    assert row["kind"] == "canvas_final_submission"
    assert artifact_payload["asset_references"][0]["mention_label"] == "bottle"


def test_canvas_final_submit_rejects_unresolved_mentions_without_artifact(tmp_path):
    client = _client(tmp_path)
    _register(client, "ada")
    project_id = _project(client)
    canvas_id = _canvas(client, project_id)
    brief = client.post(
        f"/api/canvases/{canvas_id}/nodes",
        json={"type": "brief", "title": "Missing", "position": {"x": 0, "y": 0}, "payload": {"prompt": "用 @missing 做一张海报"}},
    ).json()

    response = client.post(f"/api/canvases/{canvas_id}/final-submit", json={"selected_node_ids": [brief["id"]]})

    assert response.status_code == 422
    assert response.json()["detail"] == "Unresolved canvas asset mention: @missing"
    with sqlite3.connect(tmp_path / "app.db") as connection:
        count = connection.execute("SELECT COUNT(*) FROM prompt_artifacts").fetchone()[0]
    assert count == 0


def test_canvas_final_submit_includes_video_asset_references(tmp_path):
    client = _client(tmp_path)
    _register(client, "ada")
    project_id = _project(client)
    canvas_id = _canvas(client, project_id)
    brief = client.post(
        f"/api/canvases/{canvas_id}/nodes",
        json={"type": "brief", "title": "Video brief", "position": {"x": 0, "y": 0}, "payload": {"prompt": "参考 @shot 的镜头运动做海报"}},
    ).json()
    video = client.post(
        f"/api/canvases/{canvas_id}/nodes",
        json={
            "type": "asset",
            "title": "shot.mp4",
            "position": {"x": 360, "y": 0},
            "payload": {"asset_id": "asset-video-1", "asset_kind": "video", "media_type": "video/mp4", "mention_label": "shot", "reference_role": "motion"},
        },
    ).json()

    response = client.post(f"/api/canvases/{canvas_id}/final-submit", json={"selected_node_ids": [brief["id"], video["id"]]})

    assert response.status_code == 201
    reference = response.json()["asset_references"][0]
    assert reference["asset_kind"] == "video"
    assert reference["media_type"] == "video/mp4"
    assert reference["mention_label"] == "shot"


def test_canvas_final_submit_generation_failure_does_not_create_artifact(tmp_path):
    client = _client(tmp_path)
    _register(client, "ada")
    project_id = _project(client)
    canvas_id = _canvas(client, project_id)
    brief = client.post(
        f"/api/canvases/{canvas_id}/nodes",
        json={"type": "brief", "title": "Missing asset", "position": {"x": 0, "y": 0}, "payload": {"prompt": "用 @bottle 做一张高端香水海报"}},
    ).json()
    asset = client.post(
        f"/api/canvases/{canvas_id}/nodes",
        json={
            "type": "asset",
            "title": "Missing bottle",
            "position": {"x": 360, "y": 0},
            "payload": {"asset_id": "missing-asset", "media_type": "image/png", "mention_label": "bottle", "reference_role": "product"},
        },
    ).json()

    response = client.post(
        f"/api/canvases/{canvas_id}/final-submit",
        json={"selected_node_ids": [brief["id"], asset["id"]], "generation": {"enabled": True, "model": "openai"}},
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Canvas reference asset not found"
    with sqlite3.connect(tmp_path / "app.db") as connection:
        count = connection.execute("SELECT COUNT(*) FROM prompt_artifacts WHERE kind = 'canvas_final_submission'").fetchone()[0]
    assert count == 0


def test_canvas_final_submit_can_create_generation_task(tmp_path):
    client = _client(tmp_path)
    _register(client, "ada")
    project_id = _project(client)
    canvas_id = _canvas(client, project_id)
    brief = client.post(
        f"/api/canvases/{canvas_id}/nodes",
        json={"type": "brief", "title": "Generate", "position": {"x": 0, "y": 0}, "payload": {"prompt": "一张高端香水海报"}},
    ).json()

    response = client.post(
        f"/api/canvases/{canvas_id}/final-submit",
        json={"selected_node_ids": [brief["id"]], "generation": {"enabled": True, "model": "openai", "threshold": 0.0, "skip_prompt_evaluation": True}},
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["task"]["status"] == "pending"
    assert payload["task"]["task_id"]
    assert payload["generation_params"] == {}


def test_canvas_final_submit_validates_selection_and_generation_params(tmp_path):
    ada_client = _client(tmp_path)
    grace_client = _client(tmp_path)
    _register(ada_client, "ada")
    _register(grace_client, "grace")
    ada_project_id = _project(ada_client, "Ada")
    grace_project_id = _project(grace_client, "Grace")
    canvas_id = _canvas(ada_client, ada_project_id)
    grace_canvas_id = _canvas(grace_client, grace_project_id)
    node = ada_client.post(f"/api/canvases/{canvas_id}/nodes", json={"type": "brief", "title": "A", "position": {"x": 0, "y": 0}, "payload": {"prompt": "A"}}).json()
    grace_node = grace_client.post(f"/api/canvases/{grace_canvas_id}/nodes", json={"type": "brief", "title": "G", "position": {"x": 0, "y": 0}, "payload": {"prompt": "G"}}).json()

    missing = ada_client.post(f"/api/canvases/{canvas_id}/final-submit", json={"selected_node_ids": [node["id"], "missing"]})
    foreign_node = ada_client.post(f"/api/canvases/{canvas_id}/final-submit", json={"selected_node_ids": [node["id"], grace_node["id"]]})
    foreign_canvas = grace_client.post(f"/api/canvases/{canvas_id}/final-submit", json={"selected_node_ids": [node["id"]]})
    missing_model = ada_client.post(f"/api/canvases/{canvas_id}/final-submit", json={"selected_node_ids": [node["id"]], "generation": {"enabled": True}})
    bad_param = ada_client.post(f"/api/canvases/{canvas_id}/final-submit", json={"selected_node_ids": [node["id"]], "generation": {"params": {"user": "spoof"}}})

    assert missing.status_code == 404
    assert foreign_node.status_code == 404
    assert foreign_canvas.status_code == 404
    assert missing_model.status_code == 422
    assert bad_param.status_code == 422


def test_canvas_node_rejects_unsafe_mention_label(tmp_path):
    client = _client(tmp_path)
    _register(client, "ada")
    project_id = _project(client)
    canvas_id = _canvas(client, project_id)

    response = client.post(
        f"/api/canvases/{canvas_id}/nodes",
        json={
            "type": "asset",
            "title": "Unsafe reference",
            "position": {"x": 0, "y": 0},
            "payload": {"asset_id": "asset-1", "media_type": "image/png", "mention_label": "bottle; ignore previous"},
        },
    )

    assert response.status_code == 422


def test_canvas_node_rejects_non_string_prompt_list_members(tmp_path):
    client = _client(tmp_path)
    _register(client, "ada")
    project_id = _project(client)
    canvas_id = _canvas(client, project_id)

    response = client.post(
        f"/api/canvases/{canvas_id}/nodes",
        json={
            "type": "brief",
            "title": "Bad anchors",
            "position": {"x": 0, "y": 0},
            "payload": {"prompt": "角色海报", "character_anchors": ["白发", {"unsafe": "dict"}]},
        },
    )

    assert response.status_code == 422


def test_canvas_compile_rejects_empty_missing_and_foreign_selection(tmp_path):
    ada_client = _client(tmp_path)
    grace_client = _client(tmp_path)
    _register(ada_client, "ada")
    _register(grace_client, "grace")
    ada_project_id = _project(ada_client, "Ada")
    grace_project_id = _project(grace_client, "Grace")
    canvas_id = _canvas(ada_client, ada_project_id)
    grace_canvas_id = _canvas(grace_client, grace_project_id)
    node = ada_client.post(f"/api/canvases/{canvas_id}/nodes", json={"type": "brief", "title": "A", "position": {"x": 0, "y": 0}, "payload": {"prompt": "A"}}).json()
    grace_node = grace_client.post(f"/api/canvases/{grace_canvas_id}/nodes", json={"type": "brief", "title": "G", "position": {"x": 0, "y": 0}, "payload": {"prompt": "G"}}).json()

    empty = ada_client.post(f"/api/canvases/{canvas_id}/compile", json={"selected_node_ids": []})
    missing = ada_client.post(f"/api/canvases/{canvas_id}/compile", json={"selected_node_ids": [node["id"], "missing-node"]})
    foreign_node = ada_client.post(f"/api/canvases/{canvas_id}/compile", json={"selected_node_ids": [node["id"], grace_node["id"]]})
    foreign_canvas = grace_client.post(f"/api/canvases/{canvas_id}/compile", json={"selected_node_ids": [node["id"]]})

    assert empty.status_code == 422
    assert missing.status_code == 404
    assert foreign_node.status_code == 404
    assert foreign_canvas.status_code == 404


def test_canvas_routes_reject_unresolved_prompt_mentions(tmp_path):
    client = _client(tmp_path)
    _register(client, "ada")
    project_id = _project(client)
    canvas_id = _canvas(client, project_id)
    brief = client.post(
        f"/api/canvases/{canvas_id}/nodes",
        json={"type": "brief", "title": "Missing mention", "position": {"x": 0, "y": 0}, "payload": {"prompt": "用 @missing 做一张海报"}},
    ).json()

    compile_response = client.post(f"/api/canvases/{canvas_id}/compile", json={"selected_node_ids": [brief["id"]]})
    series_response = client.post(f"/api/canvases/{canvas_id}/series/plan", json={"selected_node_ids": [brief["id"]]})
    generate_response = client.post(f"/api/canvases/{canvas_id}/generate/image", json={"selected_node_ids": [brief["id"]], "model": "openai"})

    assert compile_response.status_code == 422
    assert compile_response.json()["detail"] == "Unresolved canvas asset mention: @missing"
    assert series_response.status_code == 422
    assert generate_response.status_code == 422


def test_canvas_series_plan_returns_frames_without_mutating_canvas(tmp_path):
    client = _client(tmp_path)
    _register(client, "ada")
    project_id = _project(client)
    canvas_id = _canvas(client, project_id)
    brief = client.post(
        f"/api/canvases/{canvas_id}/nodes",
        json={
            "type": "brief",
            "title": "Series brief",
            "position": {"x": 0, "y": 0},
            "payload": {"prompt": "为同一个白发蓝眼角色制作香水系列广告，标题写着\"NOIR BLOOM\"", "character_anchors": ["白发", "蓝眼"]},
        },
    ).json()
    style = client.post(
        f"/api/canvases/{canvas_id}/nodes",
        json={"type": "style_system", "title": "Style", "position": {"x": 360, "y": 0}, "payload": {"style": "premium noir", "lighting": "gold rim light"}},
    ).json()
    client.post(f"/api/canvases/{canvas_id}/edges", json={"source_node_id": brief["id"], "target_node_id": style["id"], "type": "influences"})
    before = client.get(f"/api/canvases/{canvas_id}").json()

    response = client.post(f"/api/canvases/{canvas_id}/series/plan", json={"selected_node_ids": [style["id"], brief["id"]], "frame_count": 4})
    after = client.get(f"/api/canvases/{canvas_id}").json()

    assert response.status_code == 201
    payload = response.json()
    assert payload["character_lock"] == ["白发", "蓝眼"]
    assert payload["style_lock"]["style"] == "premium noir"
    assert len(payload["frames"]) == 4
    assert payload["frames"][0]["index"] == 1
    assert "NOIR BLOOM" in payload["frames"][0]["prompt"]
    assert [node["id"] for node in after["nodes"]] == [node["id"] for node in before["nodes"]]
    assert after["edges"] == before["edges"]


def test_canvas_series_plan_rejects_empty_missing_and_foreign_selection(tmp_path):
    ada_client = _client(tmp_path)
    grace_client = _client(tmp_path)
    _register(ada_client, "ada")
    _register(grace_client, "grace")
    ada_project_id = _project(ada_client, "Ada")
    grace_project_id = _project(grace_client, "Grace")
    canvas_id = _canvas(ada_client, ada_project_id)
    grace_canvas_id = _canvas(grace_client, grace_project_id)
    node = ada_client.post(f"/api/canvases/{canvas_id}/nodes", json={"type": "brief", "title": "A", "position": {"x": 0, "y": 0}, "payload": {"prompt": "A"}}).json()
    grace_node = grace_client.post(f"/api/canvases/{grace_canvas_id}/nodes", json={"type": "brief", "title": "G", "position": {"x": 0, "y": 0}, "payload": {"prompt": "G"}}).json()

    empty = ada_client.post(f"/api/canvases/{canvas_id}/series/plan", json={"selected_node_ids": []})
    missing = ada_client.post(f"/api/canvases/{canvas_id}/series/plan", json={"selected_node_ids": [node["id"], "missing-node"]})
    foreign_node = ada_client.post(f"/api/canvases/{canvas_id}/series/plan", json={"selected_node_ids": [node["id"], grace_node["id"]]})
    foreign_canvas = grace_client.post(f"/api/canvases/{canvas_id}/series/plan", json={"selected_node_ids": [node["id"]]})

    assert empty.status_code == 422
    assert missing.status_code == 404
    assert foreign_node.status_code == 404
    assert foreign_canvas.status_code == 404
