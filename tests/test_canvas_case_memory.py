from fastapi.testclient import TestClient

import src.dependencies as dependencies
from src.api import image_routes as routes
from src.config import Settings
from src.main import create_app


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


def _brief(client: TestClient, canvas_id: str, prompt: str, profile: str = "poster") -> dict:
    response = client.post(
        f"/api/canvases/{canvas_id}/nodes",
        json={"type": "brief", "title": "Creative brief", "position": {"x": 0, "y": 0}, "payload": {"prompt": prompt, "profile": profile}},
    )
    assert response.status_code == 201
    return response.json()


def _style(client: TestClient, canvas_id: str, lighting: str, style: str) -> dict:
    response = client.post(
        f"/api/canvases/{canvas_id}/nodes",
        json={"type": "style_system", "title": "Style", "position": {"x": 320, "y": 0}, "payload": {"lighting": lighting, "style": style, "composition": "centered hero product with disciplined negative space"}},
    )
    assert response.status_code == 201
    return response.json()


def test_canvas_case_memory_indexes_compile_artifact_and_director_reuses_it(tmp_path):
    client = _client(tmp_path)
    _register(client, "ada")
    project_id = _project(client)
    canvas_id = _canvas(client, project_id, "Noir launch")
    brief = _brief(client, canvas_id, "高端 NOIR BLOOM 香水海报，黑色石材，金色标题，强烈边缘光")
    style = _style(client, canvas_id, "dramatic gold rim light", "premium fragrance campaign")
    client.post(f"/api/canvases/{canvas_id}/edges", json={"source_node_id": brief["id"], "target_node_id": style["id"], "type": "influences"})
    compiled = client.post(f"/api/canvases/{canvas_id}/compile", json={"selected_node_ids": [brief["id"], style["id"]], "artifact_node_id": brief["id"]}).json()

    indexed = client.post(
        f"/api/canvases/{canvas_id}/case-index",
        json={"artifact_id": compiled["artifact"]["id"], "title": "Noir fragrance poster", "quality_score": 0.93},
    )
    assert indexed.status_code == 201
    indexed_case = indexed.json()["case"]
    assert indexed_case["title"] == "Noir fragrance poster"
    assert indexed_case["visual_dna"]["lighting"] == ["dramatic gold rim light"]
    assert indexed_case["prompt_spec"]["creative_strategy"]

    next_canvas_id = _canvas(client, project_id, "Noir follow-up")
    next_brief = _brief(client, next_canvas_id, "同系列 NOIR BLOOM 香水 KV，保持高级黑金质感，标题写着\"NOIR BLOOM\"")
    director = client.post(f"/api/canvases/{next_canvas_id}/director", json={"selected_node_ids": [next_brief["id"]]})

    assert director.status_code == 200
    payload = director.json()
    assert payload["matched_cases"][0]["title"] == "Noir fragrance poster"
    assert any(item["category"] == "case_memory" and "Noir fragrance poster" in item["message"] for item in payload["suggestions"])
    assert any(item["category"] == "typography" for item in payload["suggestions"])
    assert payload["canvas_summary"]["primary_brief"].startswith("同系列 NOIR BLOOM")


def test_canvas_case_memory_is_owner_scoped(tmp_path):
    ada_client = _client(tmp_path)
    grace_client = _client(tmp_path)
    _register(ada_client, "ada")
    _register(grace_client, "grace")
    project_id = _project(ada_client, "Ada")
    canvas_id = _canvas(ada_client, project_id)
    brief = _brief(ada_client, canvas_id, "高端腕表产品广告，金属材质，棚拍")
    compiled = ada_client.post(f"/api/canvases/{canvas_id}/compile", json={"selected_node_ids": [brief["id"]], "artifact_node_id": brief["id"]}).json()

    foreign_index = grace_client.post(f"/api/canvases/{canvas_id}/case-index", json={"artifact_id": compiled["artifact"]["id"], "title": "Stolen", "quality_score": 0.9})
    foreign_director = grace_client.post(f"/api/canvases/{canvas_id}/director", json={"selected_node_ids": [brief["id"]]})

    assert foreign_index.status_code == 404
    assert foreign_director.status_code == 404


def test_canvas_case_memory_indexing_is_idempotent(tmp_path):
    client = _client(tmp_path)
    _register(client, "ada")
    project_id = _project(client)
    canvas_id = _canvas(client, project_id)
    brief = _brief(client, canvas_id, "高端腕表产品广告，金属材质，棚拍", profile="product")
    compiled = client.post(f"/api/canvases/{canvas_id}/compile", json={"selected_node_ids": [brief["id"]], "artifact_node_id": brief["id"]}).json()

    first = client.post(f"/api/canvases/{canvas_id}/case-index", json={"artifact_id": compiled["artifact"]["id"], "title": "Watch campaign", "quality_score": 0.91})
    second = client.post(f"/api/canvases/{canvas_id}/case-index", json={"artifact_id": compiled["artifact"]["id"], "title": "Watch campaign", "quality_score": 0.91})
    director = client.post(f"/api/canvases/{canvas_id}/director", json={"selected_node_ids": [brief["id"]]})

    assert first.status_code == 201
    assert second.status_code == 201
    assert second.json()["case"]["id"] == first.json()["case"]["id"]
    assert [case["id"] for case in director.json()["matched_cases"]].count(first.json()["case"]["id"]) == 1


def test_canvas_director_does_not_return_unrelated_zero_score_cases(tmp_path):
    client = _client(tmp_path)
    _register(client, "ada")
    project_id = _project(client)
    source_canvas_id = _canvas(client, project_id, "Watch memory")
    source_brief = _brief(client, source_canvas_id, "高端腕表产品广告，金属材质，棚拍", profile="product")
    compiled = client.post(f"/api/canvases/{source_canvas_id}/compile", json={"selected_node_ids": [source_brief["id"]], "artifact_node_id": source_brief["id"]}).json()
    client.post(f"/api/canvases/{source_canvas_id}/case-index", json={"artifact_id": compiled["artifact"]["id"], "title": "Watch campaign", "quality_score": 0.97})

    unrelated_canvas_id = _canvas(client, project_id, "Unrelated")
    unrelated_brief = _brief(client, unrelated_canvas_id, "水彩风格的儿童动物绘本封面，森林里的狐狸和月亮")
    director = client.post(f"/api/canvases/{unrelated_canvas_id}/director", json={"selected_node_ids": [unrelated_brief["id"]]})

    assert director.status_code == 200
    assert director.json()["matched_cases"] == []
    assert not any(item["category"] == "case_memory" for item in director.json()["suggestions"])
