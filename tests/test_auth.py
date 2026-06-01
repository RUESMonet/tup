from datetime import datetime, timezone
from hashlib import sha256
import sqlite3

import pytest
from fastapi.testclient import TestClient

import src.dependencies as dependencies
from src.api import image_routes as routes
from src.config import Settings, get_settings
from src.main import create_app
from src.services.auth import AuthService
from src.services.database import SQLiteDatabase


def _client(tmp_path, **settings_updates):
    values = {
        "auth_required": False,
        "rate_limit_requests": 1000,
        "database_path": tmp_path / "app.db",
        "asset_upload_dir": tmp_path / "uploads",
        "use_mock_images": True,
        "secure_session_cookies": False,
        **settings_updates,
    }
    settings = Settings(**values)
    _reset_app_state()
    return TestClient(create_app(settings))


def _reset_app_state() -> None:
    get_settings.cache_clear()
    dependencies.get_storage.cache_clear()
    dependencies._database_for_path.cache_clear()
    routes._rate_limit_hits.clear()


def test_register_creates_user_and_session(tmp_path):
    client = _client(tmp_path)

    response = client.post(
        "/api/auth/register",
        json={"username": "ada", "email": "ada@example.com", "password": "correct horse battery staple"},
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["user"]["id"]
    assert payload["user"]["username"] == "ada"
    assert payload["user"]["email"] == "ada@example.com"
    assert payload["user"]["role"] == "user"
    assert "password" not in payload["user"]


def test_register_rejects_duplicate_username_or_email(tmp_path):
    client = _client(tmp_path)
    account = {"username": "ada", "email": "ada@example.com", "password": "correct horse battery staple"}

    assert client.post("/api/auth/register", json=account).status_code == 201
    duplicate_username = client.post(
        "/api/auth/register",
        json={"username": "ada", "email": "other@example.com", "password": "correct horse battery staple"},
    )
    duplicate_email = client.post(
        "/api/auth/register",
        json={"username": "grace", "email": "ada@example.com", "password": "correct horse battery staple"},
    )

    assert duplicate_username.status_code == 409
    assert duplicate_email.status_code == 409


def test_register_validates_required_fields_and_password_length(tmp_path):
    client = _client(tmp_path)

    response = client.post("/api/auth/register", json={"username": " ", "email": "bad", "password": "short"})

    assert response.status_code == 422


def test_login_returns_token_for_valid_credentials(tmp_path):
    client = _client(tmp_path)
    client.post(
        "/api/auth/register",
        json={"username": "ada", "email": "ada@example.com", "password": "correct horse battery staple"},
    )

    response = client.post("/api/auth/login", json={"username": "ada", "password": "correct horse battery staple"})

    assert response.status_code == 200
    assert response.json()["user"]["username"] == "ada"
    assert client.get("/api/auth/me").json()["user"]["username"] == "ada"


def test_login_rejects_unknown_or_wrong_password(tmp_path):
    client = _client(tmp_path)
    client.post(
        "/api/auth/register",
        json={"username": "ada", "email": "ada@example.com", "password": "correct horse battery staple"},
    )

    unknown = client.post("/api/auth/login", json={"username": "missing", "password": "correct horse battery staple"})
    wrong = client.post("/api/auth/login", json={"username": "ada", "password": "wrong horse battery staple"})

    assert unknown.status_code == 401
    assert wrong.status_code == 401


def test_me_returns_current_user_for_valid_session_cookie(tmp_path):
    client = _client(tmp_path)
    registered = client.post(
        "/api/auth/register",
        json={"username": "ada", "email": "ada@example.com", "password": "correct horse battery staple"},
    ).json()

    response = client.get("/api/auth/me")

    assert response.status_code == 200
    assert response.json()["user"] == registered["user"]


def test_me_rejects_missing_invalid_or_logged_out_token(tmp_path):
    client = _client(tmp_path)
    missing = client.get("/api/auth/me")
    client.post(
        "/api/auth/register",
        json={"username": "ada", "email": "ada@example.com", "password": "correct horse battery staple"},
    )

    invalid = client.get("/api/auth/me", headers={"Authorization": "Bearer not-a-session"})
    logout = client.post("/api/auth/logout")
    logged_out = client.get("/api/auth/me")

    assert missing.status_code == 401
    assert invalid.status_code == 401
    assert logout.status_code == 200
    assert logged_out.status_code == 401


def test_logout_only_revokes_presented_session(tmp_path):
    first_client = _client(tmp_path)
    second_client = _client(tmp_path)
    account = {"username": "ada", "email": "ada@example.com", "password": "correct horse battery staple"}
    first_client.post("/api/auth/register", json=account)
    second_client.post("/api/auth/login", json={"username": "ada", "password": account["password"]})

    response = first_client.post("/api/auth/logout")

    assert response.status_code == 200
    assert first_client.get("/api/auth/me").status_code == 401
    assert second_client.get("/api/auth/me").status_code == 200


def test_public_registration_is_disabled_when_auth_required_by_default(tmp_path):
    client = _client(tmp_path, auth_required=True, api_key="secret-key")

    response = client.post(
        "/api/auth/register",
        json={"username": "ada", "email": "ada@example.com", "password": "correct horse battery staple"},
    )

    assert response.status_code == 403


def test_public_registration_is_disabled_when_api_key_implicitly_requires_auth(tmp_path):
    client = _client(tmp_path, auth_required=None, api_key="secret-key")

    response = client.post(
        "/api/auth/register",
        json={"username": "ada", "email": "ada@example.com", "password": "correct horse battery staple"},
    )

    assert response.status_code == 403


def test_session_or_api_key_can_access_high_cost_routes_when_auth_required(tmp_path):
    client = _client(tmp_path, auth_required=True, allow_public_registration=True, api_key="secret-key")
    client.post(
        "/api/auth/register",
        json={"username": "ada", "email": "ada@example.com", "password": "correct horse battery staple"},
    )
    session_token = client.cookies.get("session")
    anonymous_client = _client(tmp_path, auth_required=True, api_key="secret-key")

    session_cookie = client.get("/api/models")
    session_bearer = anonymous_client.get("/api/models", headers={"Authorization": f"Bearer {session_token}"})
    allowed_with_header = anonymous_client.get("/api/models", headers={"X-API-Key": "secret-key"})
    allowed_with_bearer = anonymous_client.get("/api/models", headers={"Authorization": "Bearer secret-key"})
    anonymous = anonymous_client.get("/api/models")

    assert session_cookie.status_code == 200
    assert session_bearer.status_code == 200
    assert allowed_with_header.status_code == 200
    assert allowed_with_bearer.status_code == 200
    assert anonymous.status_code == 401


def test_session_identity_can_own_tasks_when_high_cost_api_key_auth_is_disabled(tmp_path):
    client = _client(tmp_path, auth_required=False, api_key="secret-key")
    client.post(
        "/api/auth/register",
        json={"username": "ada", "email": "ada@example.com", "password": "correct horse battery staple"},
    )

    created = client.post(
        "/api/generate",
        json={"input": "一只猫", "model": "openai", "skip_prompt_evaluation": True},
    )
    assert created.status_code == 202
    task_id = created.json()["task_id"]
    same_session_poll = client.get(f"/api/task/{task_id}")
    anonymous_poll = _client(tmp_path, auth_required=False, api_key="secret-key").get(f"/api/task/{task_id}")

    assert same_session_poll.status_code == 200
    assert anonymous_poll.status_code == 404


def test_auth_endpoints_are_rate_limited(tmp_path):
    client = _client(tmp_path, rate_limit_requests=1)

    first = client.post(
        "/api/auth/register",
        json={"username": "ada", "email": "ada@example.com", "password": "correct horse battery staple"},
    )
    second = client.post(
        "/api/auth/register",
        json={"username": "grace", "email": "grace@example.com", "password": "correct horse battery staple"},
    )

    assert first.status_code == 201
    assert second.status_code == 429


def test_legacy_session_expiration_migration_uses_runtime_timestamp_format(tmp_path):
    database_path = tmp_path / "legacy.db"
    now = datetime.now(timezone.utc).isoformat()
    token = "legacy-session-token"
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
            CREATE TABLE sessions (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                token_hash TEXT NOT NULL UNIQUE,
                created_at TEXT NOT NULL,
                revoked_at TEXT
            );
            """
        )
        connection.execute(
            "INSERT INTO users (id, username, email, password_hash, role, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            ("user-id", "ada", "ada@example.com", "malformed", "user", now),
        )
        connection.execute(
            "INSERT INTO sessions (id, user_id, token_hash, created_at, revoked_at) VALUES (?, ?, ?, ?, NULL)",
            ("session-id", "user-id", sha256(token.encode("utf-8")).hexdigest(), now),
        )

    database = SQLiteDatabase(database_path)
    user = AuthService(database, 604800).current_user(token)
    with database.connect() as connection:
        expires_at = connection.execute("SELECT expires_at FROM sessions WHERE id = 'session-id'").fetchone()["expires_at"]

    assert "T" in expires_at
    assert user is not None
    assert user.username == "ada"


def test_admin_bootstrap_creates_admin_from_environment(monkeypatch, tmp_path):
    monkeypatch.setenv("ENV_FILE", str(tmp_path / "missing.env"))
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "app.db"))
    monkeypatch.setenv("ADMIN_USERNAME", "admin")
    monkeypatch.setenv("ADMIN_EMAIL", "admin@example.com")
    monkeypatch.setenv("ADMIN_PASSWORD", "correct horse battery staple")
    monkeypatch.setenv("SECURE_SESSION_COOKIES", "false")
    get_settings.cache_clear()

    try:
        with TestClient(create_app()) as client:
            response = client.post("/api/auth/login", json={"username": "admin", "password": "correct horse battery staple"})

            assert response.status_code == 200
            assert response.json()["user"]["role"] == "admin"
            assert client.get("/api/auth/me").json()["user"]["role"] == "admin"
    finally:
        get_settings.cache_clear()


def test_partial_admin_bootstrap_configuration_fails_closed(monkeypatch, tmp_path):
    monkeypatch.setenv("ENV_FILE", str(tmp_path / "missing.env"))
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "app.db"))
    monkeypatch.setenv("ADMIN_USERNAME", "admin")
    monkeypatch.delenv("ADMIN_EMAIL", raising=False)
    monkeypatch.delenv("ADMIN_PASSWORD", raising=False)
    monkeypatch.setenv("SECURE_SESSION_COOKIES", "false")
    get_settings.cache_clear()

    try:
        with pytest.raises(ValueError, match="ADMIN_USERNAME, ADMIN_EMAIL, and ADMIN_PASSWORD"):
            with TestClient(create_app()):
                pass
    finally:
        get_settings.cache_clear()
