import sqlite3

from fastapi.testclient import TestClient

import src.dependencies as dependencies
from src.api import image_routes as routes
from src.config import Settings
from src.main import create_app
from src.services.database import SQLiteDatabase


def _client(tmp_path):
    settings = Settings(
        auth_required=False,
        rate_limit_requests=1000,
        database_path=tmp_path / "app.db",
        asset_upload_dir=tmp_path / "uploads",
        use_mock_images=True,
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


def test_project_conversation_stores_messages_and_character_sheet(tmp_path):
    client = _client(tmp_path)
    _register(client, "ada")
    project_id = client.post("/api/projects", json={"name": "Character board"}).json()["id"]

    created = client.post(f"/api/projects/{project_id}/conversations", json={"title": "Heroine"})
    conversation_id = created.json()["id"]
    message = client.post(
        f"/api/conversations/{conversation_id}/messages",
        json={"role": "user", "content": "保持同一个白发蓝眼角色一致，生成三个不同场景"},
    )
    detail = client.get(f"/api/conversations/{conversation_id}")

    assert created.status_code == 201
    assert message.status_code == 201
    payload = detail.json()
    assert payload["messages"][0]["content"].startswith("保持同一个")
    assert payload["character_sheets"]
    assert "白发" in payload["character_sheets"][0]["identity_anchors"]
    assert "蓝眼" in payload["character_sheets"][0]["identity_anchors"]


def test_conversation_prompt_optimize_uses_previous_character_context(tmp_path):
    client = _client(tmp_path)
    _register(client, "ada")
    project_id = client.post("/api/projects", json={"name": "Character board"}).json()["id"]
    conversation_id = client.post(f"/api/projects/{project_id}/conversations", json={"title": "Heroine"}).json()["id"]
    client.post(
        f"/api/conversations/{conversation_id}/messages",
        json={"role": "user", "content": "一个白发蓝眼、黑色制服、戴银色耳机的少女角色，保持角色一致"},
    )

    response = client.post(
        f"/api/conversations/{conversation_id}/prompt/optimize",
        json={"prompt": "换到雨夜街头，镜头更近一点"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["intent"]["needs_character_consistency"] is True
    assert "白发" in payload["final_english_prompt"]
    assert "蓝眼" in payload["final_english_prompt"]
    assert "黑色制服" in payload["final_english_prompt"]


def test_conversation_prompt_optimize_rejects_raw_image_urls(tmp_path):
    client = _client(tmp_path)
    _register(client, "ada")
    project_id = client.post("/api/projects", json={"name": "Character board"}).json()["id"]
    conversation_id = client.post(f"/api/projects/{project_id}/conversations", json={"title": "Heroine"}).json()["id"]

    response = client.post(
        f"/api/conversations/{conversation_id}/prompt/optimize",
        json={"prompt": "参考这张图生成", "action_type": "image_to_image", "source_images": [{"url": "/uploads/image-optimizer/other.png"}]},
    )

    assert response.status_code == 400


def test_conversation_message_rejects_data_url_prompt_snapshot(tmp_path):
    client = _client(tmp_path)
    _register(client, "ada")
    project_id = client.post("/api/projects", json={"name": "Private"}).json()["id"]
    conversation_id = client.post(f"/api/projects/{project_id}/conversations", json={"title": "Private"}).json()["id"]

    response = client.post(
        f"/api/conversations/{conversation_id}/messages",
        json={"content": "hello", "prompt_snapshot": {"image": "data:image/png;base64,abcd"}},
    )

    assert response.status_code == 422


def test_conversations_are_user_scoped(tmp_path):
    ada_client = _client(tmp_path)
    grace_client = _client(tmp_path)
    _register(ada_client, "ada")
    _register(grace_client, "grace")
    project_id = ada_client.post("/api/projects", json={"name": "Private"}).json()["id"]
    conversation_id = ada_client.post(f"/api/projects/{project_id}/conversations", json={"title": "Private"}).json()["id"]

    assert grace_client.get(f"/api/conversations/{conversation_id}").status_code == 404
    assert grace_client.post(f"/api/conversations/{conversation_id}/messages", json={"role": "user", "content": "hi"}).status_code == 404


def test_database_initialization_deduplicates_legacy_character_sheets(tmp_path):
    path = tmp_path / "legacy.db"
    with sqlite3.connect(path) as connection:
        connection.execute(
            """
            CREATE TABLE character_sheets (
                id TEXT PRIMARY KEY,
                owner_id TEXT NOT NULL,
                project_id TEXT NOT NULL,
                conversation_id TEXT NOT NULL,
                name TEXT NOT NULL,
                identity_anchors_json TEXT NOT NULL,
                visual_traits_json TEXT NOT NULL,
                locked_prompt_text TEXT NOT NULL,
                source_asset_ids_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            "INSERT INTO character_sheets VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("old", "owner", "project", "conversation", "主角色", '["白发"]', '{"hair":["白发"]}', "old", "[]", "2026-01-01T00:00:00+00:00", "2026-01-01T00:00:00+00:00"),
        )
        connection.execute(
            "INSERT INTO character_sheets VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("new", "owner", "project", "conversation", "主角色", '["蓝眼"]', '{"eyes":["蓝眼"]}', "new", "[]", "2026-01-02T00:00:00+00:00", "2026-01-02T00:00:00+00:00"),
        )

    SQLiteDatabase(path)

    with sqlite3.connect(path) as connection:
        rows = connection.execute("SELECT identity_anchors_json FROM character_sheets").fetchall()
        indexes = connection.execute("PRAGMA index_list(character_sheets)").fetchall()

    assert len(rows) == 1
    assert "白发" in rows[0][0]
    assert "蓝眼" in rows[0][0]
    assert any("idx_character_sheets_owner_conversation_name" in row for row in indexes)
