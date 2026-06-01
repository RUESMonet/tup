import socket

import pytest
from fastapi.testclient import TestClient

import src.dependencies as dependencies
from src.api import image_routes as routes
from src.config import Settings
from src.main import create_app
from src.services.database import SQLiteDatabase


def _client(tmp_path, **settings_updates):
    values = {
        "auth_required": False,
        "rate_limit_requests": 1000,
        "database_path": tmp_path / "app.db",
        "asset_upload_dir": tmp_path / "uploads",
        "use_mock_images": True,
        "use_mock_videos": True,
        "secure_session_cookies": False,
        **settings_updates,
    }
    settings = Settings(**values)
    dependencies.get_storage.cache_clear()
    dependencies._database_for_path.cache_clear()
    routes._rate_limit_hits.clear()
    return TestClient(create_app(settings)), settings


def _register(client: TestClient, username: str) -> None:
    response = client.post(
        "/api/auth/register",
        json={"username": username, "email": f"{username}@example.com", "password": "correct horse battery staple"},
    )
    assert response.status_code == 201


def _promote(settings, username: str) -> None:
    database = SQLiteDatabase(settings.database_path)
    with database.connect() as connection:
        connection.execute("UPDATE users SET role = 'admin' WHERE username = ?", (username,))


def _admin_client(tmp_path, **settings_updates):
    client, settings = _client(tmp_path, **settings_updates)
    _register(client, "admin")
    _promote(settings, "admin")
    return client, settings


def test_admin_model_settings_require_admin(tmp_path):
    missing_client, _ = _client(tmp_path)
    user_client, _ = _client(tmp_path)
    admin_client, admin_settings = _client(tmp_path)
    _register(user_client, "ada")
    _register(admin_client, "admin")
    _promote(admin_settings, "admin")

    missing = missing_client.get("/api/admin/model-settings")
    user = user_client.get("/api/admin/model-settings")
    admin = admin_client.get("/api/admin/model-settings")

    assert missing.status_code == 401
    assert user.status_code == 403
    assert admin.status_code == 200


def test_admin_model_settings_mask_secrets_and_update_effective_models(tmp_path, monkeypatch):
    monkeypatch.setattr("src.services.url_security.socket.getaddrinfo", lambda *args, **kwargs: [(None, None, None, None, ("93.184.216.34", 443))])
    client, _ = _admin_client(
        tmp_path,
        use_mock_images=False,
        openai_image_api_key="secret-env-key",
        openai_image_model="env-image-model",
        model_base_url_allowed_hosts="models.example",
    )

    update = client.post(
        "/api/admin/model-settings",
        json={"settings": {"OPENAI_IMAGE_MODEL": "admin-image-model", "OPENAI_IMAGE_BASE_URL": "https://models.example/v1"}},
    )
    model_settings = client.get("/api/admin/model-settings")
    models = client.get("/api/models")

    assert update.status_code == 200
    assert "secret-env-key" not in str(model_settings.json())
    image_key = model_settings.json()["settings"]["OPENAI_IMAGE_API_KEY"]
    assert image_key["configured"] is True
    assert image_key["masked_value"].endswith("-key")
    openai = models.json()["models"][0]
    assert openai["provider_model"] == "admin-image-model"
    assert openai["base_url"] == "https://models.example/v1"
    assert openai["configured"] is True


def test_admin_model_settings_update_prompt_optimizer_overrides(tmp_path, monkeypatch):
    monkeypatch.setattr("src.services.url_security.socket.getaddrinfo", lambda *args, **kwargs: [(None, None, None, None, ("93.184.216.34", 443))])
    client, _ = _admin_client(
        tmp_path,
        openai_prompt_draft_base_url="https://draft.example/v1",
        openai_prompt_draft_model="draft-model",
        model_base_url_allowed_hosts="models.example",
    )

    inherited = client.get("/api/admin/model-settings").json()["settings"]

    assert inherited["OPENAI_PROMPT_OPTIMIZER_BASE_URL"]["value"] == "https://draft.example/v1"
    assert inherited["OPENAI_PROMPT_OPTIMIZER_BASE_URL"]["source"] == "inherited"
    assert inherited["OPENAI_PROMPT_OPTIMIZER_MODEL"]["value"] == "draft-model"
    assert inherited["OPENAI_PROMPT_OPTIMIZER_MODEL"]["source"] == "inherited"

    update = client.post(
        "/api/admin/model-settings",
        json={
            "settings": {
                "OPENAI_PROMPT_OPTIMIZER_BASE_URL": "https://models.example/v1",
                "OPENAI_PROMPT_OPTIMIZER_MODEL": "optimizer-model",
            }
        },
    )
    updated = update.json()["settings"]

    assert update.status_code == 200
    assert updated["OPENAI_PROMPT_OPTIMIZER_BASE_URL"]["value"] == "https://models.example/v1"
    assert updated["OPENAI_PROMPT_OPTIMIZER_BASE_URL"]["source"] == "database"
    assert updated["OPENAI_PROMPT_OPTIMIZER_MODEL"]["value"] == "optimizer-model"
    assert updated["OPENAI_PROMPT_OPTIMIZER_MODEL"]["source"] == "database"

    cleared = client.post(
        "/api/admin/model-settings",
        json={"settings": {"OPENAI_PROMPT_OPTIMIZER_BASE_URL": None, "OPENAI_PROMPT_OPTIMIZER_MODEL": None}},
    ).json()["settings"]

    assert cleared["OPENAI_PROMPT_OPTIMIZER_BASE_URL"]["value"] == "https://draft.example/v1"
    assert cleared["OPENAI_PROMPT_OPTIMIZER_BASE_URL"]["source"] == "inherited"
    assert cleared["OPENAI_PROMPT_OPTIMIZER_MODEL"]["value"] == "draft-model"
    assert cleared["OPENAI_PROMPT_OPTIMIZER_MODEL"]["source"] == "inherited"


def test_database_initialization_removes_legacy_secret_model_settings(tmp_path):
    database_path = tmp_path / "legacy-secrets.db"
    database = SQLiteDatabase(database_path)
    with database.connect() as connection:
        connection.execute(
            "INSERT INTO model_settings (key, value, updated_at, updated_by) VALUES (?, ?, ?, NULL)",
            ("OPENAI_API_KEY", '"legacy-secret"', "2026-01-01T00:00:00+00:00"),
        )
        connection.execute(
            "INSERT INTO model_settings (key, value, updated_at, updated_by) VALUES (?, ?, ?, NULL)",
            ("OPENAI_IMAGE_MODEL", '"legacy-model"', "2026-01-01T00:00:00+00:00"),
        )

    SQLiteDatabase(database_path)
    with database.connect() as connection:
        rows = connection.execute("SELECT key FROM model_settings ORDER BY key").fetchall()

    assert [row["key"] for row in rows] == ["OPENAI_IMAGE_MODEL"]


    client, _ = _admin_client(tmp_path, openai_image_model="env-image-model")
    assert client.post("/api/admin/model-settings", json={"settings": {"OPENAI_IMAGE_MODEL": "db-image-model"}}).status_code == 200

    response = client.post("/api/admin/model-settings", json={"settings": {"OPENAI_IMAGE_MODEL": None}})
    settings = response.json()["settings"]

    assert response.status_code == 200
    assert settings["OPENAI_IMAGE_MODEL"]["value"] == "env-image-model"
    assert settings["OPENAI_IMAGE_MODEL"]["source"] != "database"


@pytest.mark.parametrize("resolved_ip", ["10.0.0.8", "100.64.0.1", "127.0.0.1", "::1", "fc00::1"])
def test_admin_model_settings_rejects_allowed_host_with_private_dns(tmp_path, monkeypatch, resolved_ip):
    monkeypatch.setattr(
        "src.services.url_security.socket.getaddrinfo",
        lambda *args, **kwargs: [(None, None, None, None, (resolved_ip, 443))],
    )
    client, _ = _admin_client(tmp_path, model_base_url_allowed_hosts="trusted.example")

    response = client.post(
        "/api/admin/model-settings",
        json={"settings": {"OPENAI_PROMPT_OPTIMIZER_BASE_URL": "https://trusted.example/v1"}},
    )

    assert response.status_code == 422


def test_admin_model_settings_rejects_unresolvable_allowed_host(tmp_path, monkeypatch):
    def fail_resolution(*args, **kwargs):
        raise socket.gaierror("not found")

    monkeypatch.setattr("src.services.url_security.socket.getaddrinfo", fail_resolution)
    client, _ = _admin_client(tmp_path, model_base_url_allowed_hosts="trusted.example")

    response = client.post(
        "/api/admin/model-settings",
        json={"settings": {"OPENAI_PROMPT_OPTIMIZER_BASE_URL": "https://trusted.example/v1"}},
    )

    assert response.status_code == 422


def test_admin_model_settings_validate_payload(tmp_path):
    client, _ = _admin_client(tmp_path)

    invalid_url = client.post("/api/admin/model-settings", json={"settings": {"OPENAI_BASE_URL": "not-a-url"}})
    private_url = client.post("/api/admin/model-settings", json={"settings": {"OPENAI_BASE_URL": "http://127.0.0.1:11434/v1"}})
    http_url = client.post("/api/admin/model-settings", json={"settings": {"OPENAI_BASE_URL": "http://api.openai.com/v1"}})
    untrusted_public_url = client.post("/api/admin/model-settings", json={"settings": {"OPENAI_BASE_URL": "https://evil.example/v1"}})
    invalid_endpoint = client.post("/api/admin/model-settings", json={"settings": {"VIDEO_GENERATE_ENDPOINT": "videos"}})
    host_endpoint = client.post("/api/admin/model-settings", json={"settings": {"VIDEO_GENERATE_ENDPOINT": "//evil.example/videos"}})
    secret_override = client.post("/api/admin/model-settings", json={"settings": {"OPENAI_API_KEY": "secret-db-key"}})
    unknown = client.post("/api/admin/model-settings", json={"settings": {"UNKNOWN_SETTING": "value"}})

    assert invalid_url.status_code == 422
    assert private_url.status_code == 422
    assert http_url.status_code == 422
    assert untrusted_public_url.status_code == 422
    assert invalid_endpoint.status_code == 422
    assert host_endpoint.status_code == 422
    assert secret_override.status_code == 422
    assert unknown.status_code == 422
