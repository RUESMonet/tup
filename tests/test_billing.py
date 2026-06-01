import asyncio
import sqlite3
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

import src.dependencies as dependencies
from src.api import generation_routes, image_routes as routes
from src.api.generation_routes import _run_image_edit_task, _run_image_task, _run_video_task
from src.config import Settings
from src.main import create_app
from src.models.prompt_skill import ImageActionType, ImageSource, PromptSkillRequest
from src.models.task import ImageResult
from src.models.video import VideoGenerateRequest, VideoResult
from src.services.billing_repository import BillingRepository
from src.services.billing_service import BillingService
from src.services.database import SQLiteDatabase
from src.services.project_repository import ProjectRepository


def _client(tmp_path, **settings_updates):
    settings_values = {
        "auth_required": False,
        "rate_limit_requests": 1000,
        "database_path": tmp_path / "app.db",
        "asset_upload_dir": tmp_path / "uploads",
        "use_mock_images": True,
        "use_mock_videos": True,
        "secure_session_cookies": False,
        "initial_credit_balance": 100,
    }
    settings = Settings(**{**settings_values, **settings_updates})
    dependencies.get_storage.cache_clear()
    dependencies._database_for_path.cache_clear()
    routes._rate_limit_hits.clear()
    return TestClient(create_app(settings)), settings


def _register(client: TestClient, username: str) -> str:
    response = client.post(
        "/api/auth/register",
        json={"username": username, "email": f"{username}@example.com", "password": "correct horse battery staple"},
    )
    assert response.status_code == 201
    return response.json()["user"]["id"]


def _create_project(database: SQLiteDatabase, user_id: str, project_id: str = "project-1") -> str:
    now = datetime.now(timezone.utc).isoformat()
    with database.connect() as connection:
        connection.execute(
            """
            INSERT INTO projects (id, owner_id, name, description, created_at, updated_at)
            VALUES (?, ?, 'Test project', '', ?, ?)
            """,
            (project_id, user_id, now, now),
        )
    return project_id


def _create_task(database: SQLiteDatabase, user_id: str, project_id: str, task_id: str = "task-1") -> str:
    now = datetime.now(timezone.utc).isoformat()
    with database.connect() as connection:
        connection.execute(
            """
            INSERT INTO generation_tasks (id, owner_id, project_id, kind, status, input_json, result_json, history_json, error, created_at, updated_at)
            VALUES (?, ?, ?, 'image', 'pending', '{}', NULL, NULL, NULL, ?, ?)
            """,
            (task_id, user_id, project_id, now, now),
        )
    return task_id


def test_billing_repository_creates_default_account_and_debits(tmp_path):
    client, settings = _client(tmp_path)
    user_id = _register(client, "ada")
    database = SQLiteDatabase(settings.database_path)
    repository = BillingRepository(database)

    account = repository.get_or_create_account(user_id, 100)
    transaction = repository.debit(
        user_id=user_id,
        project_id=None,
        task_id=None,
        action_type="canvas_video",
        amount=80,
        metadata={"source": "test"},
    )
    updated = repository.get_or_create_account(user_id, 100)
    transactions = repository.list_transactions(user_id, limit=10)

    assert account.balance == 100
    assert transaction.direction == "debit"
    assert transaction.amount == 80
    assert updated.balance == 20
    assert transactions[0].id == transaction.id


def test_billing_repository_rejects_insufficient_credit_without_transaction(tmp_path):
    client, settings = _client(tmp_path)
    user_id = _register(client, "ada")
    repository = BillingRepository(SQLiteDatabase(settings.database_path))
    repository.get_or_create_account(user_id, 25)

    with pytest.raises(ValueError, match="Insufficient credits"):
        repository.debit(
            user_id=user_id,
            project_id=None,
            task_id=None,
            action_type="canvas_video",
            amount=80,
            metadata={},
        )

    account = repository.get_or_create_account(user_id, 25)
    assert account.balance == 25
    assert repository.list_transactions(user_id, limit=10) == []


def test_billing_repository_refunds_failed_task_with_ledger_entry(tmp_path):
    client, settings = _client(tmp_path)
    user_id = _register(client, "ada")
    database = SQLiteDatabase(settings.database_path)
    repository = BillingRepository(database)
    repository.get_or_create_account(user_id, 100)
    project_id = _create_project(database, user_id)
    task_id = _create_task(database, user_id, project_id)
    debit = repository.debit(user_id, project_id, task_id, "project_video", 80, {"source": "test"})

    refund = repository.refund(user_id=user_id, original_transaction_id=debit.id, task_id=task_id, reason="failed task")

    account = repository.get_or_create_account(user_id, 100)
    transactions = repository.list_transactions(user_id, limit=10)

    assert refund.direction == "credit"
    assert refund.amount == 80
    assert refund.metadata["refund_of"] == debit.id
    assert account.balance == 100
    assert [item.direction for item in transactions] == ["credit", "debit"]


def test_billing_repository_rejects_unknown_project_reference_without_debit(tmp_path):
    client, settings = _client(tmp_path)
    user_id = _register(client, "ada")
    repository = BillingRepository(SQLiteDatabase(settings.database_path))
    repository.get_or_create_account(user_id, 100)

    with pytest.raises(ValueError, match="Project not found"):
        repository.debit(
            user_id=user_id,
            project_id="missing-project",
            task_id=None,
            action_type="canvas_video",
            amount=80,
            metadata={},
        )

    account = repository.get_or_create_account(user_id, 100)
    assert account.balance == 100
    assert repository.list_transactions(user_id, limit=10) == []


def test_billing_repository_attach_task_rejects_unknown_task(tmp_path):
    client, settings = _client(tmp_path)
    user_id = _register(client, "ada")
    repository = BillingRepository(SQLiteDatabase(settings.database_path))
    repository.get_or_create_account(user_id, 100)
    debit = repository.debit(user_id, None, None, "canvas_video", 10, {})

    with pytest.raises(ValueError, match="Task not found"):
        repository.attach_task(user_id, debit.id, "missing-task")


def test_billing_repository_refund_database_idempotency_prevents_duplicate_credit(tmp_path, monkeypatch):
    client, settings = _client(tmp_path)
    user_id = _register(client, "ada")
    repository = BillingRepository(SQLiteDatabase(settings.database_path))
    repository.get_or_create_account(user_id, 100)
    debit = repository.debit(user_id, None, None, "canvas_video", 80, {})
    monkeypatch.setattr(repository, "find_refund", lambda user_id, original_transaction_id: None)

    first_refund = repository.refund(user_id=user_id, original_transaction_id=debit.id, task_id=None, reason="failed task")
    second_refund = repository.refund(user_id=user_id, original_transaction_id=debit.id, task_id=None, reason="failed task")
    account = repository.get_or_create_account(user_id, 100)
    transactions = repository.list_transactions(user_id, limit=10)

    assert second_refund.id == first_refund.id
    assert account.balance == 100
    assert [item.direction for item in transactions] == ["credit", "debit"]


def test_billing_repository_increment_quota_rejects_after_limit(tmp_path):
    client, settings = _client(tmp_path)
    user_id = _register(client, "ada")
    repository = BillingRepository(SQLiteDatabase(settings.database_path))

    quota = repository.increment_quota(user_id, "canvas_video", "2026-05-21", 1)

    with pytest.raises(ValueError, match="Daily quota exceeded"):
        repository.increment_quota(user_id, "canvas_video", "2026-05-21", 1)

    current = repository.get_quota(user_id, "canvas_video", "2026-05-21", 1)
    assert quota.used_count == 1
    assert current.used_count == 1


def test_billing_repository_existing_refund_still_rejects_unknown_task_reference(tmp_path):
    client, settings = _client(tmp_path)
    user_id = _register(client, "ada")
    repository = BillingRepository(SQLiteDatabase(settings.database_path))
    repository.get_or_create_account(user_id, 100)
    debit = repository.debit(user_id, None, None, "canvas_video", 80, {})
    repository.refund(user_id=user_id, original_transaction_id=debit.id, task_id=None, reason="failed task")

    with pytest.raises(ValueError, match="Task not found"):
        repository.refund(user_id=user_id, original_transaction_id=debit.id, task_id="missing-task", reason="retry failed task")

    account = repository.get_or_create_account(user_id, 100)
    transactions = repository.list_transactions(user_id, limit=10)
    assert account.balance == 100
    assert [item.direction for item in transactions] == ["credit", "debit"]


def test_database_migration_deduplicates_legacy_duplicate_refunds_before_unique_index(tmp_path):
    database_path = tmp_path / "legacy-billing.db"
    now = datetime.now(timezone.utc).isoformat()
    debit_id = "debit-1"
    refund_one_id = "refund-1"
    refund_two_id = "refund-2"
    user_id = "user-1"

    connection = sqlite3.connect(database_path)
    try:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.executescript(
            """
            CREATE TABLE users (
                id TEXT PRIMARY KEY,
                username TEXT NOT NULL,
                email TEXT NOT NULL,
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
            CREATE TABLE generation_tasks (
                id TEXT PRIMARY KEY,
                owner_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                kind TEXT NOT NULL,
                status TEXT NOT NULL,
                input_json TEXT NOT NULL,
                result_json TEXT,
                history_json TEXT,
                error TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE credit_accounts (
                user_id TEXT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
                balance INTEGER NOT NULL,
                lifetime_granted INTEGER NOT NULL,
                lifetime_spent INTEGER NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE credit_transactions (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                project_id TEXT REFERENCES projects(id) ON DELETE SET NULL,
                task_id TEXT REFERENCES generation_tasks(id) ON DELETE SET NULL,
                action_type TEXT NOT NULL,
                direction TEXT NOT NULL,
                amount INTEGER NOT NULL,
                status TEXT NOT NULL,
                metadata_json TEXT NOT NULL,
                refund_of_transaction_id TEXT REFERENCES credit_transactions(id) ON DELETE SET NULL,
                created_at TEXT NOT NULL
            );
            """
        )
        connection.execute(
            "INSERT INTO users (id, username, email, password_hash, role, created_at) VALUES (?, 'ada', 'ada@example.com', 'hash', 'user', ?)",
            (user_id, now),
        )
        connection.execute(
            "INSERT INTO credit_accounts (user_id, balance, lifetime_granted, lifetime_spent, updated_at) VALUES (?, 180, 100, 80, ?)",
            (user_id, now),
        )
        connection.execute(
            """
            INSERT INTO credit_transactions (
                id, user_id, project_id, task_id, action_type, direction, amount, status, metadata_json, refund_of_transaction_id, created_at
            )
            VALUES (?, ?, NULL, NULL, 'canvas_video', 'debit', 80, 'refunded', '{}', NULL, ?)
            """,
            (debit_id, user_id, now),
        )
        connection.execute(
            """
            INSERT INTO credit_transactions (
                id, user_id, project_id, task_id, action_type, direction, amount, status, metadata_json, refund_of_transaction_id, created_at
            )
            VALUES (?, ?, NULL, NULL, 'canvas_video', 'credit', 80, 'applied', ?, ?, ?)
            """,
            (refund_one_id, user_id, '{"refund_of":"debit-1"}', debit_id, now),
        )
        connection.execute(
            """
            INSERT INTO credit_transactions (
                id, user_id, project_id, task_id, action_type, direction, amount, status, metadata_json, refund_of_transaction_id, created_at
            )
            VALUES (?, ?, NULL, NULL, 'canvas_video', 'credit', 80, 'applied', ?, ?, ?)
            """,
            (refund_two_id, user_id, '{"refund_of":"debit-1"}', debit_id, now),
        )
        connection.commit()
    finally:
        connection.close()

    SQLiteDatabase(database_path)

    connection = sqlite3.connect(database_path)
    connection.row_factory = sqlite3.Row
    try:
        remaining_refunds = connection.execute(
            """
            SELECT id FROM credit_transactions
            WHERE user_id = ? AND direction = 'credit' AND refund_of_transaction_id = ?
            ORDER BY created_at ASC, id ASC
            """,
            (user_id, debit_id),
        ).fetchall()
        account = connection.execute(
            "SELECT balance FROM credit_accounts WHERE user_id = ?",
            (user_id,),
        ).fetchone()

        assert len(remaining_refunds) == 1
        assert remaining_refunds[0]["id"] == refund_one_id
        assert account["balance"] == 100

        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """
                INSERT INTO credit_transactions (
                    id, user_id, project_id, task_id, action_type, direction, amount, status, metadata_json, refund_of_transaction_id, created_at
                )
                VALUES (?, ?, NULL, NULL, 'canvas_video', 'credit', 80, 'applied', ?, ?, ?)
                """,
                ("refund-3", user_id, '{"refund_of":"debit-1"}', debit_id, now),
            )
    finally:
        connection.close()


def test_database_migration_deduplicates_overspent_duplicate_refunds_without_negative_balance(tmp_path):
    database_path = tmp_path / "legacy-billing-overspent.db"
    now = datetime.now(timezone.utc).isoformat()
    debit_id = "debit-1"
    refund_one_id = "refund-1"
    refund_two_id = "refund-2"
    user_id = "user-1"

    connection = sqlite3.connect(database_path)
    try:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.executescript(
            """
            CREATE TABLE users (
                id TEXT PRIMARY KEY,
                username TEXT NOT NULL,
                email TEXT NOT NULL,
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
            CREATE TABLE generation_tasks (
                id TEXT PRIMARY KEY,
                owner_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                kind TEXT NOT NULL,
                status TEXT NOT NULL,
                input_json TEXT NOT NULL,
                result_json TEXT,
                history_json TEXT,
                error TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE credit_accounts (
                user_id TEXT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
                balance INTEGER NOT NULL,
                lifetime_granted INTEGER NOT NULL,
                lifetime_spent INTEGER NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE credit_transactions (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                project_id TEXT REFERENCES projects(id) ON DELETE SET NULL,
                task_id TEXT REFERENCES generation_tasks(id) ON DELETE SET NULL,
                action_type TEXT NOT NULL,
                direction TEXT NOT NULL,
                amount INTEGER NOT NULL,
                status TEXT NOT NULL,
                metadata_json TEXT NOT NULL,
                refund_of_transaction_id TEXT REFERENCES credit_transactions(id) ON DELETE SET NULL,
                created_at TEXT NOT NULL
            );
            """
        )
        connection.execute(
            "INSERT INTO users (id, username, email, password_hash, role, created_at) VALUES (?, 'ada', 'ada@example.com', 'hash', 'user', ?)",
            (user_id, now),
        )
        connection.execute(
            "INSERT INTO credit_accounts (user_id, balance, lifetime_granted, lifetime_spent, updated_at) VALUES (?, 20, 100, 80, ?)",
            (user_id, now),
        )
        connection.execute(
            """
            INSERT INTO credit_transactions (
                id, user_id, project_id, task_id, action_type, direction, amount, status, metadata_json, refund_of_transaction_id, created_at
            )
            VALUES (?, ?, NULL, NULL, 'canvas_video', 'debit', 80, 'refunded', '{}', NULL, ?)
            """,
            (debit_id, user_id, now),
        )
        connection.execute(
            """
            INSERT INTO credit_transactions (
                id, user_id, project_id, task_id, action_type, direction, amount, status, metadata_json, refund_of_transaction_id, created_at
            )
            VALUES (?, ?, NULL, NULL, 'canvas_video', 'credit', 80, 'applied', ?, ?, ?)
            """,
            (refund_one_id, user_id, '{"refund_of":"debit-1"}', debit_id, now),
        )
        connection.execute(
            """
            INSERT INTO credit_transactions (
                id, user_id, project_id, task_id, action_type, direction, amount, status, metadata_json, refund_of_transaction_id, created_at
            )
            VALUES (?, ?, NULL, NULL, 'canvas_video', 'credit', 80, 'applied', ?, ?, ?)
            """,
            (refund_two_id, user_id, '{"refund_of":"debit-1"}', debit_id, now),
        )
        connection.commit()
    finally:
        connection.close()

    SQLiteDatabase(database_path)

    connection = sqlite3.connect(database_path)
    connection.row_factory = sqlite3.Row
    try:
        remaining_refunds = connection.execute(
            """
            SELECT id FROM credit_transactions
            WHERE user_id = ? AND direction = 'credit' AND refund_of_transaction_id = ?
            ORDER BY created_at ASC, id ASC
            """,
            (user_id, debit_id),
        ).fetchall()
        account = connection.execute(
            "SELECT balance FROM credit_accounts WHERE user_id = ?",
            (user_id,),
        ).fetchone()

        assert len(remaining_refunds) == 1
        assert remaining_refunds[0]["id"] == refund_one_id
        assert account["balance"] == 0

        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """
                INSERT INTO credit_transactions (
                    id, user_id, project_id, task_id, action_type, direction, amount, status, metadata_json, refund_of_transaction_id, created_at
                )
                VALUES (?, ?, NULL, NULL, 'canvas_video', 'credit', 80, 'applied', ?, ?, ?)
                """,
                ("refund-3", user_id, '{"refund_of":"debit-1"}', debit_id, now),
            )
    finally:
        connection.close()


def test_account_credits_returns_balance_costs_and_quota(tmp_path):
    client, _ = _client(tmp_path, initial_credit_balance=250, canvas_video_credit_cost=75, daily_canvas_video_quota=3)
    _register(client, "ada")

    response = client.get("/api/account/credits")

    assert response.status_code == 200
    payload = response.json()
    assert payload["account"]["balance"] == 250
    costs = {item["action_type"]: item for item in payload["costs"]}
    assert costs["canvas_video"]["cost"] == 75
    assert costs["canvas_video"]["daily_quota"] == 3
    quotas = {item["action_type"]: item for item in payload["quotas"]}
    assert quotas["canvas_video"]["used_count"] == 0
    assert quotas["canvas_video"]["limit_count"] == 3


def test_account_transactions_are_owner_scoped(tmp_path):
    ada_client, ada_settings = _client(tmp_path, initial_credit_balance=100)
    _register(ada_client, "ada")
    ada_id = ada_client.get("/api/auth/me").json()["user"]["id"]
    repository = BillingRepository(SQLiteDatabase(ada_settings.database_path))
    repository.get_or_create_account(ada_id, 100)
    repository.debit(ada_id, None, None, "canvas_image", 10, {})

    grace_client, _ = _client(tmp_path, initial_credit_balance=100)
    _register(grace_client, "grace")

    ada_transactions = ada_client.get("/api/account/transactions").json()["transactions"]
    grace_transactions = grace_client.get("/api/account/transactions").json()["transactions"]

    assert len(ada_transactions) == 1
    assert grace_transactions == []


def test_billing_service_enforces_daily_quota(tmp_path):
    client, settings = _client(tmp_path, initial_credit_balance=100, daily_canvas_video_quota=1, canvas_video_credit_cost=5)
    user_id = _register(client, "ada")
    from src.services.billing_service import BillingService

    service = BillingService(BillingRepository(SQLiteDatabase(settings.database_path)), settings)
    first = service.charge_for_action(user_id, None, "canvas_video", {"attempt": 1})

    with pytest.raises(ValueError, match="Daily quota exceeded"):
        service.charge_for_action(user_id, None, "canvas_video", {"attempt": 2})

    assert first.amount == 5



def test_billing_service_does_not_consume_quota_when_debit_fails(tmp_path):
    client, settings = _client(tmp_path, initial_credit_balance=2, daily_canvas_video_quota=1, canvas_video_credit_cost=5)
    user_id = _register(client, "ada")
    repository = BillingRepository(SQLiteDatabase(settings.database_path))
    service = BillingService(repository, settings)

    with pytest.raises(ValueError, match="Insufficient credits"):
        service.charge_for_action(user_id, None, "canvas_video", {"attempt": 1})

    quotas = {item.action_type: item for item in service.quotas_for_user(user_id)}
    assert quotas["canvas_video"].used_count == 0
    assert repository.get_quota(user_id, "canvas_video", service.current_daily_period_key(), 1).used_count == 0
    assert repository.list_transactions(user_id, limit=10) == []


def test_project_image_generation_blocks_when_credits_are_insufficient(tmp_path):
    client, _ = _client(tmp_path, initial_credit_balance=5, project_image_credit_cost=10)
    _register(client, "ada")
    project_id = client.post("/api/projects", json={"name": "Ad campaign"}).json()["id"]

    response = client.post(
        f"/api/projects/{project_id}/generate/image",
        json={"input": "高端香水海报", "model": "openai", "threshold": 8.0},
    )
    tasks = client.get(f"/api/projects/{project_id}/tasks").json()["tasks"]

    assert response.status_code == 402
    assert response.json()["detail"] == "Insufficient credits"
    assert tasks == []


def test_project_video_generation_charges_and_links_task(tmp_path):
    client, settings = _client(tmp_path, initial_credit_balance=100, project_video_credit_cost=80)
    user_id = _register(client, "ada")
    project_id = client.post("/api/projects", json={"name": "Video campaign"}).json()["id"]

    response = client.post(
        f"/api/projects/{project_id}/generate/video",
        json={"prompt": "cinematic product motion", "source_image_url": "mock://image.png", "duration": 5},
    )

    assert response.status_code == 202
    task_id = response.json()["task_id"]
    repository = BillingRepository(SQLiteDatabase(settings.database_path))
    account = repository.get_or_create_account(user_id, 100)
    transactions = repository.list_transactions(user_id, limit=10)
    assert account.balance == 20
    assert transactions[0].task_id == task_id
    assert transactions[0].action_type == "project_video"
    assert transactions[0].amount == 80


def test_project_video_failure_refunds_charged_credits(tmp_path, monkeypatch):
    client, settings = _client(tmp_path, initial_credit_balance=100, project_video_credit_cost=80)
    user_id = _register(client, "ada")
    project_id = client.post("/api/projects", json={"name": "Video campaign"}).json()["id"]

    async def fail_generate(self, request):
        raise RuntimeError("provider failed")

    monkeypatch.setattr("src.services.video_router.VideoRouter.generate", fail_generate)
    response = client.post(
        f"/api/projects/{project_id}/generate/video",
        json={"prompt": "cinematic product motion", "source_image_url": "mock://image.png", "duration": 5},
    )

    assert response.status_code == 202
    repository = BillingRepository(SQLiteDatabase(settings.database_path))
    account = repository.get_or_create_account(user_id, 100)
    transactions = repository.list_transactions(user_id, limit=10)
    assert account.balance == 100
    assert [item.direction for item in transactions] == ["credit", "debit"]
    assert transactions[0].metadata["reason"] == "failed task"


def test_startup_does_not_recover_fresh_charged_running_task(tmp_path):
    settings = Settings(
        auth_required=False,
        rate_limit_requests=1000,
        database_path=tmp_path / "app.db",
        asset_upload_dir=tmp_path / "uploads",
        use_mock_images=True,
        use_mock_videos=True,
        secure_session_cookies=False,
        initial_credit_balance=100,
    )
    dependencies.get_storage.cache_clear()
    dependencies._database_for_path.cache_clear()
    routes._rate_limit_hits.clear()

    database = SQLiteDatabase(settings.database_path)
    now = datetime.now(timezone.utc).isoformat()
    user_id = "user-1"
    project_id = "project-1"
    task_id = "task-1"
    debit_id = "debit-1"

    with database.connect() as connection:
        connection.execute(
            """
            INSERT INTO users (id, username, email, password_hash, role, created_at)
            VALUES (?, 'ada', 'ada@example.com', 'hash', 'user', ?)
            """,
            (user_id, now),
        )
        connection.execute(
            """
            INSERT INTO projects (id, owner_id, name, description, created_at, updated_at)
            VALUES (?, ?, 'Video campaign', '', ?, ?)
            """,
            (project_id, user_id, now, now),
        )
        connection.execute(
            """
            INSERT INTO credit_accounts (user_id, balance, lifetime_granted, lifetime_spent, updated_at)
            VALUES (?, 20, 100, 80, ?)
            """,
            (user_id, now),
        )
        connection.execute(
            """
            INSERT INTO generation_tasks (
                id, owner_id, project_id, kind, status, input_json, result_json, history_json, error,
                cost_estimate, charged_credits, created_at, updated_at
            )
            VALUES (?, ?, ?, 'image_to_video', 'running', ?, NULL, NULL, NULL, 80, 80, ?, ?)
            """,
            (task_id, user_id, project_id, '{"credit_transaction_id":"debit-1"}', now, now),
        )
        connection.execute(
            """
            INSERT INTO credit_transactions (
                id, user_id, project_id, task_id, action_type, direction, amount, status, metadata_json,
                refund_of_transaction_id, created_at
            )
            VALUES (?, ?, ?, ?, 'project_video', 'debit', 80, 'applied', ?, NULL, ?)
            """,
            (debit_id, user_id, project_id, task_id, '{"source":"project_video"}', now),
        )

    with TestClient(create_app(settings)):
        pass

    repository = BillingRepository(SQLiteDatabase(settings.database_path))
    account = repository.get_or_create_account(user_id, 100)
    transactions = repository.list_transactions(user_id, limit=10)

    with database.connect() as connection:
        task_row = connection.execute("SELECT status FROM generation_tasks WHERE id = ?", (task_id,)).fetchone()

    assert account.balance == 20
    assert task_row["status"] == "running"
    assert [item.direction for item in transactions] == ["debit"]



def test_task_heartbeat_removes_stale_task_from_recovery_candidates(tmp_path):
    client, settings = _client(tmp_path)
    user_id = _register(client, "ada")
    database = SQLiteDatabase(settings.database_path)
    project_id = _create_project(database, user_id)
    repository = ProjectRepository(database)
    billing = BillingRepository(database)
    billing.get_or_create_account(user_id, 100)
    debit = billing.debit(user_id, project_id, None, "project_video", 80, {"source": "project_video"})
    now = datetime.now(timezone.utc)
    stale = (now - timedelta(hours=7)).isoformat()
    cutoff = now - timedelta(hours=6)
    task_id = "task-1"
    with database.connect() as connection:
        connection.execute(
            """
            INSERT INTO generation_tasks (
                id, owner_id, project_id, kind, status, input_json, result_json, history_json, error,
                cost_estimate, charged_credits, created_at, updated_at
            )
            VALUES (?, ?, ?, 'image_to_video', 'running', ?, NULL, NULL, NULL, 80, 80, ?, ?)
            """,
            (task_id, user_id, project_id, f'{{"credit_transaction_id":"{debit.id}"}}', stale, stale),
        )

    assert [task["task_id"] for task in repository.list_recoverable_charged_tasks(cutoff)] == [task_id]

    repository.touch_task(task_id)

    assert repository.list_recoverable_charged_tasks(cutoff) == []


async def test_task_heartbeat_ignores_touch_failures(monkeypatch):
    monkeypatch.setattr(generation_routes, "TASK_HEARTBEAT_INTERVAL_SECONDS", 0)

    async def fail_to_thread(func, *args):
        raise RuntimeError("database temporarily unavailable")

    class BrokenRepository:
        def touch_task(self, task_id):
            return None

    monkeypatch.setattr(generation_routes.asyncio, "to_thread", fail_to_thread)
    heartbeat_task = asyncio.create_task(generation_routes._task_heartbeat(BrokenRepository(), "task-1"))
    await asyncio.sleep(0)
    await asyncio.sleep(0)

    await generation_routes._stop_task_heartbeat(heartbeat_task)



def test_startup_recovery_skips_task_completed_after_selection(tmp_path, monkeypatch):
    settings = Settings(
        auth_required=False,
        rate_limit_requests=1000,
        database_path=tmp_path / "app.db",
        asset_upload_dir=tmp_path / "uploads",
        use_mock_images=True,
        use_mock_videos=True,
        secure_session_cookies=False,
        initial_credit_balance=100,
    )
    dependencies.get_storage.cache_clear()
    dependencies._database_for_path.cache_clear()
    routes._rate_limit_hits.clear()

    database = SQLiteDatabase(settings.database_path)
    now = datetime.now(timezone.utc).isoformat()
    stale = (datetime.now(timezone.utc) - timedelta(hours=7)).isoformat()
    user_id = "user-1"
    project_id = "project-1"
    task_id = "task-1"
    debit_id = "debit-1"

    with database.connect() as connection:
        connection.execute(
            """
            INSERT INTO users (id, username, email, password_hash, role, created_at)
            VALUES (?, 'ada', 'ada@example.com', 'hash', 'user', ?)
            """,
            (user_id, now),
        )
        connection.execute(
            """
            INSERT INTO projects (id, owner_id, name, description, created_at, updated_at)
            VALUES (?, ?, 'Video campaign', '', ?, ?)
            """,
            (project_id, user_id, now, now),
        )
        connection.execute(
            """
            INSERT INTO credit_accounts (user_id, balance, lifetime_granted, lifetime_spent, updated_at)
            VALUES (?, 20, 100, 80, ?)
            """,
            (user_id, now),
        )
        connection.execute(
            """
            INSERT INTO generation_tasks (
                id, owner_id, project_id, kind, status, input_json, result_json, history_json, error,
                cost_estimate, charged_credits, created_at, updated_at
            )
            VALUES (?, ?, ?, 'image_to_video', 'running', ?, NULL, NULL, NULL, 80, 80, ?, ?)
            """,
            (task_id, user_id, project_id, '{"credit_transaction_id":"debit-1"}', stale, stale),
        )
        connection.execute(
            """
            INSERT INTO credit_transactions (
                id, user_id, project_id, task_id, action_type, direction, amount, status, metadata_json,
                refund_of_transaction_id, created_at
            )
            VALUES (?, ?, ?, ?, 'project_video', 'debit', 80, 'applied', ?, NULL, ?)
            """,
            (debit_id, user_id, project_id, task_id, '{"source":"project_video"}', now),
        )

    original = ProjectRepository.list_recoverable_charged_tasks

    def complete_after_selection(self, updated_before):
        tasks = original(self, updated_before)
        with self.database.connect() as connection:
            connection.execute(
                """
                UPDATE generation_tasks
                SET status = 'succeeded', result_json = '{}', history_json = '[]', updated_at = ?
                WHERE id = ?
                """,
                (datetime.now(timezone.utc).isoformat(), task_id),
            )
        return tasks

    monkeypatch.setattr(ProjectRepository, "list_recoverable_charged_tasks", complete_after_selection)

    with TestClient(create_app(settings)):
        pass

    repository = BillingRepository(SQLiteDatabase(settings.database_path))
    account = repository.get_or_create_account(user_id, 100)
    transactions = repository.list_transactions(user_id, limit=10)

    with database.connect() as connection:
        task_row = connection.execute("SELECT status FROM generation_tasks WHERE id = ?", (task_id,)).fetchone()

    assert account.balance == 20
    assert task_row["status"] == "succeeded"
    assert [item.direction for item in transactions] == ["debit"]



async def test_worker_does_not_persist_asset_after_recovery_failure_race(tmp_path):
    client, settings = _client(tmp_path)
    user_id = _register(client, "ada")
    database = SQLiteDatabase(settings.database_path)
    project_id = _create_project(database, user_id)
    repository = ProjectRepository(database)
    billing_repository = BillingRepository(database)
    billing_repository.get_or_create_account(user_id, 100)
    debit = billing_repository.debit(user_id, project_id, None, "project_video", 80, {"source": "project_video"})
    task = repository.create_task(
        user_id,
        project_id,
        "image_to_video",
        {"prompt": "late success", "credit_transaction_id": debit.id},
        cost_estimate=80,
        charged_credits=80,
    )
    billing_repository.attach_task(user_id, debit.id, task.task_id)
    repository.set_task_running(task.task_id)

    class LateSuccessVideoRouter:
        async def generate(self, request):
            repository.set_task_failed(task.task_id, "startup recovery")
            return VideoResult(url="mock://video/late-success", media_type="video/mp4", provider_model="mock", metadata={"mock": True})

    await _run_video_task(
        user_id,
        task.task_id,
        VideoGenerateRequest(prompt="late success", source_image_url="mock://image.png"),
        debit.id,
        repository,
        LateSuccessVideoRouter(),
        BillingService(billing_repository, settings),
    )

    stored_task = repository.get_task(user_id, task.task_id)
    assets = repository.list_assets(user_id, project_id)

    assert stored_task.status == "failed"
    assert assets == []



async def test_image_worker_deletes_file_after_recovery_failure_race(tmp_path):
    client, settings = _client(tmp_path)
    user_id = _register(client, "ada")
    database = SQLiteDatabase(settings.database_path)
    project_id = _create_project(database, user_id)
    repository = ProjectRepository(database)
    billing_repository = BillingRepository(database)
    billing_repository.get_or_create_account(user_id, 100)
    debit = billing_repository.debit(user_id, project_id, None, "project_image", 10, {"source": "project_image"})
    task = repository.create_task(
        user_id,
        project_id,
        "image",
        {"input": "late success", "model": "openai", "credit_transaction_id": debit.id},
        cost_estimate=10,
        charged_credits=10,
    )
    billing_repository.attach_task(user_id, debit.id, task.task_id)
    repository.set_task_running(task.task_id)

    class Dumpable:
        def model_dump(self, mode="json"):
            return {}

    class LateSuccessImagePipeline:
        async def run(self, **kwargs):
            repository.set_task_failed(task.task_id, "startup recovery")
            return SimpleNamespace(
                image=ImageResult(
                    b64_json="iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/p9sAAAAASUVORK5CYII=",
                    url=None,
                    model_id="openai",
                    provider_model="mock",
                    metadata={"media_type": "image/png"},
                ),
                final_prompt="late success",
                score=9.0,
                iterations=1,
                prompt_report=Dumpable(),
                optimization_trace=None,
                prompt_history=[],
            )

    await _run_image_task(
        user_id,
        task.task_id,
        routes.GenerateRequest(input="late success", model="openai"),
        debit.id,
        repository,
        LateSuccessImagePipeline(),
        BillingService(billing_repository, settings),
        settings,
    )

    stored_task = repository.get_task(user_id, task.task_id)
    generated_files = list((settings.asset_upload_dir / "image-optimizer").glob(f"generated-{task.task_id}*"))
    assets = repository.list_assets(user_id, project_id)

    assert stored_task.status == "failed"
    assert generated_files == []
    assert assets == []


async def test_image_edit_worker_deletes_file_after_recovery_failure_race(tmp_path):
    client, settings = _client(tmp_path)
    user_id = _register(client, "ada")
    database = SQLiteDatabase(settings.database_path)
    project_id = _create_project(database, user_id)
    repository = ProjectRepository(database)
    billing_repository = BillingRepository(database)
    billing_repository.get_or_create_account(user_id, 100)
    debit = billing_repository.debit(user_id, project_id, None, "project_image_edit", 12, {"source": "project_image_edit"})
    task = repository.create_task(
        user_id,
        project_id,
        "image_edit",
        {"prompt": "late edit", "model": "openai", "credit_transaction_id": debit.id},
        cost_estimate=12,
        charged_credits=12,
    )
    billing_repository.attach_task(user_id, debit.id, task.task_id)
    repository.set_task_running(task.task_id)

    class Dumpable:
        def model_dump(self, mode="json"):
            return {}

    class LateSuccessImageEditPipeline:
        async def run(self, request, model_id, threshold, max_iter):
            repository.set_task_failed(task.task_id, "startup recovery")
            return (
                SimpleNamespace(
                    image=ImageResult(
                        b64_json="iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/p9sAAAAASUVORK5CYII=",
                        url=None,
                        model_id="openai",
                        provider_model="mock",
                        metadata={"media_type": "image/png"},
                    ),
                    final_prompt="late edit",
                    score=9.0,
                    iterations=1,
                    prompt_report=Dumpable(),
                    optimization_trace=None,
                    prompt_history=[],
                ),
                Dumpable(),
            )

    await _run_image_edit_task(
        user_id,
        task.task_id,
        "openai",
        PromptSkillRequest(
            prompt="late edit",
            action_type=ImageActionType.EDIT,
            source_images=[ImageSource(asset_id="source-1", media_type="image/png")],
        ),
        None,
        None,
        debit.id,
        repository,
        LateSuccessImageEditPipeline(),
        BillingService(billing_repository, settings),
        settings,
    )

    stored_task = repository.get_task(user_id, task.task_id)
    generated_files = list((settings.asset_upload_dir / "image-optimizer").glob(f"generated-{task.task_id}*"))
    assets = repository.list_assets(user_id, project_id)

    assert stored_task.status == "failed"
    assert generated_files == []
    assert assets == []


async def test_image_worker_keeps_winning_file_after_success_race(tmp_path):
    client, settings = _client(tmp_path)
    user_id = _register(client, "ada")
    database = SQLiteDatabase(settings.database_path)
    project_id = _create_project(database, user_id)
    repository = ProjectRepository(database)
    billing_repository = BillingRepository(database)
    billing_repository.get_or_create_account(user_id, 100)
    debit = billing_repository.debit(user_id, project_id, None, "project_image", 10, {"source": "project_image"})
    task = repository.create_task(
        user_id,
        project_id,
        "image",
        {"input": "late success", "model": "openai", "credit_transaction_id": debit.id},
        cost_estimate=10,
        charged_credits=10,
    )
    billing_repository.attach_task(user_id, debit.id, task.task_id)
    repository.set_task_running(task.task_id)
    image_dir = settings.asset_upload_dir / "image-optimizer"
    image_dir.mkdir(parents=True)
    winner_path = image_dir / f"generated-{task.task_id}.png"
    winner_path.write_bytes(b"\x89PNG\r\n\x1a\nwinning")
    winner_url = f"/uploads/image-optimizer/{winner_path.name}"

    class Dumpable:
        def model_dump(self, mode="json"):
            return {}

    class LateSuccessImagePipeline:
        async def run(self, **kwargs):
            repository.set_task_succeeded(task.task_id, {"image_url": winner_url, "image_media_type": "image/png"}, [])
            repository.create_asset(user_id, project_id, "image", winner_url, "image/png", {"task_id": task.task_id})
            return SimpleNamespace(
                image=ImageResult(
                    b64_json="iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/p9sAAAAASUVORK5CYII=",
                    url=None,
                    model_id="openai",
                    provider_model="mock",
                    metadata={"media_type": "image/png"},
                ),
                final_prompt="late success",
                score=9.0,
                iterations=1,
                prompt_report=Dumpable(),
                optimization_trace=None,
                prompt_history=[],
            )

    await _run_image_task(
        user_id,
        task.task_id,
        routes.GenerateRequest(input="late success", model="openai"),
        debit.id,
        repository,
        LateSuccessImagePipeline(),
        BillingService(billing_repository, settings),
        settings,
    )

    stored_task = repository.get_task(user_id, task.task_id)
    generated_files = sorted(path.name for path in image_dir.glob(f"generated-{task.task_id}*"))
    assets = repository.list_assets(user_id, project_id)

    assert stored_task.status == "succeeded"
    assert winner_path.exists()
    assert generated_files == [winner_path.name]
    assert [asset.url for asset in assets] == [winner_url]



def test_startup_recovers_charged_project_task_left_running(tmp_path):
    settings = Settings(
        auth_required=False,
        rate_limit_requests=1000,
        database_path=tmp_path / "app.db",
        asset_upload_dir=tmp_path / "uploads",
        use_mock_images=True,
        use_mock_videos=True,
        secure_session_cookies=False,
        initial_credit_balance=100,
    )
    dependencies.get_storage.cache_clear()
    dependencies._database_for_path.cache_clear()
    routes._rate_limit_hits.clear()

    database = SQLiteDatabase(settings.database_path)
    now = datetime.now(timezone.utc).isoformat()
    stale = (datetime.now(timezone.utc) - timedelta(hours=7)).isoformat()
    user_id = "user-1"
    project_id = "project-1"
    task_id = "task-1"
    debit_id = "debit-1"

    with database.connect() as connection:
        connection.execute(
            """
            INSERT INTO users (id, username, email, password_hash, role, created_at)
            VALUES (?, 'ada', 'ada@example.com', 'hash', 'user', ?)
            """,
            (user_id, now),
        )
        connection.execute(
            """
            INSERT INTO projects (id, owner_id, name, description, created_at, updated_at)
            VALUES (?, ?, 'Video campaign', '', ?, ?)
            """,
            (project_id, user_id, now, now),
        )
        connection.execute(
            """
            INSERT INTO credit_accounts (user_id, balance, lifetime_granted, lifetime_spent, updated_at)
            VALUES (?, 20, 100, 80, ?)
            """,
            (user_id, now),
        )
        connection.execute(
            """
            INSERT INTO generation_tasks (
                id, owner_id, project_id, kind, status, input_json, result_json, history_json, error,
                cost_estimate, charged_credits, created_at, updated_at
            )
            VALUES (?, ?, ?, 'image_to_video', 'running', ?, NULL, NULL, NULL, 80, 80, ?, ?)
            """,
            (task_id, user_id, project_id, '{"credit_transaction_id":"debit-1"}', stale, stale),
        )
        connection.execute(
            """
            INSERT INTO credit_transactions (
                id, user_id, project_id, task_id, action_type, direction, amount, status, metadata_json,
                refund_of_transaction_id, created_at
            )
            VALUES (?, ?, ?, ?, 'project_video', 'debit', 80, 'applied', ?, NULL, ?)
            """,
            (debit_id, user_id, project_id, task_id, '{"source":"project_video"}', now),
        )

    image_dir = settings.asset_upload_dir / "image-optimizer"
    image_dir.mkdir(parents=True)
    legacy_orphan = image_dir / f"generated-{task_id}.png"
    attempt_orphan = image_dir / f"generated-{task_id}-{uuid4().hex}.png"
    legacy_orphan.write_bytes(b"orphan")
    attempt_orphan.write_bytes(b"orphan")

    with TestClient(create_app(settings)):
        pass

    repository = BillingRepository(SQLiteDatabase(settings.database_path))
    account = repository.get_or_create_account(user_id, 100)
    transactions = repository.list_transactions(user_id, limit=10)

    with database.connect() as connection:
        task_row = connection.execute("SELECT status FROM generation_tasks WHERE id = ?", (task_id,)).fetchone()

    assert account.balance == 100
    assert task_row["status"] == "failed"
    assert not legacy_orphan.exists()
    assert not attempt_orphan.exists()
    assert [item.direction for item in transactions] == ["credit", "debit"]
    assert transactions[0].metadata["reason"] == "startup recovery"



def test_startup_recovers_charged_canvas_task_and_removes_canvas_side_effects(tmp_path):
    settings = Settings(
        auth_required=False,
        rate_limit_requests=1000,
        database_path=tmp_path / "app.db",
        asset_upload_dir=tmp_path / "uploads",
        use_mock_images=True,
        use_mock_videos=True,
        secure_session_cookies=False,
        initial_credit_balance=100,
    )
    dependencies.get_storage.cache_clear()
    dependencies._database_for_path.cache_clear()
    routes._rate_limit_hits.clear()

    database = SQLiteDatabase(settings.database_path)
    now = datetime.now(timezone.utc).isoformat()
    stale = (datetime.now(timezone.utc) - timedelta(hours=7)).isoformat()
    user_id = "user-1"
    project_id = "project-1"
    canvas_id = "canvas-1"
    task_id = "task-1"
    debit_id = "debit-1"
    asset_id = "asset-1"
    generated_node_id = "generated-node-1"
    source_node_id = "source-node-1"
    image_dir = settings.asset_upload_dir / "image-optimizer"
    image_dir.mkdir(parents=True)
    generated_file = image_dir / f"generated-{task_id}.png"
    generated_file.write_bytes(b"orphan")

    with database.connect() as connection:
        connection.execute(
            """
            INSERT INTO users (id, username, email, password_hash, role, created_at)
            VALUES (?, 'ada', 'ada@example.com', 'hash', 'user', ?)
            """,
            (user_id, now),
        )
        connection.execute(
            """
            INSERT INTO projects (id, owner_id, name, description, created_at, updated_at)
            VALUES (?, ?, 'Canvas project', '', ?, ?)
            """,
            (project_id, user_id, now, now),
        )
        connection.execute(
            """
            INSERT INTO canvases (id, owner_id, project_id, name, description, created_at, updated_at)
            VALUES (?, ?, ?, 'Main board', '', ?, ?)
            """,
            (canvas_id, user_id, project_id, now, now),
        )
        connection.execute(
            """
            INSERT INTO canvas_nodes (id, canvas_id, type, title, position_json, size_json, payload_json, created_at, updated_at)
            VALUES (?, ?, 'storyboard', 'Source', '{"x":0,"y":0}', '{"width":320,"height":180}', '{"prompt":"hero"}', ?, ?)
            """,
            (source_node_id, canvas_id, now, now),
        )
        connection.execute(
            """
            INSERT INTO credit_accounts (user_id, balance, lifetime_granted, lifetime_spent, updated_at)
            VALUES (?, 20, 100, 80, ?)
            """,
            (user_id, now),
        )
        connection.execute(
            """
            INSERT INTO generation_tasks (
                id, owner_id, project_id, kind, status, input_json, result_json, history_json, error,
                cost_estimate, charged_credits, created_at, updated_at
            )
            VALUES (?, ?, ?, 'image', 'running', ?, NULL, NULL, NULL, 80, 80, ?, ?)
            """,
            (task_id, user_id, project_id, '{"credit_transaction_id":"debit-1","canvas_id":"canvas-1"}', stale, stale),
        )
        connection.execute(
            """
            INSERT INTO credit_transactions (
                id, user_id, project_id, task_id, action_type, direction, amount, status, metadata_json,
                refund_of_transaction_id, created_at
            )
            VALUES (?, ?, ?, ?, 'canvas_image', 'debit', 80, 'applied', ?, NULL, ?)
            """,
            (debit_id, user_id, project_id, task_id, '{"source":"canvas_image","canvas_id":"canvas-1"}', now),
        )
        connection.execute(
            """
            INSERT INTO assets (id, owner_id, project_id, kind, url, media_type, metadata_json, created_at)
            VALUES (?, ?, ?, 'image', ?, 'image/png', ?, ?)
            """,
            (asset_id, user_id, project_id, f"/uploads/image-optimizer/{generated_file.name}", '{"task_id":"task-1","canvas_id":"canvas-1","source":"canvas_generation","source_node_ids":["source-node-1"]}', now),
        )
        connection.execute(
            """
            INSERT INTO canvas_nodes (id, canvas_id, type, title, position_json, size_json, payload_json, created_at, updated_at)
            VALUES (?, ?, 'generated_image', 'Generated image', '{"x":420,"y":0}', '{"width":320,"height":220}', ?, ?, ?)
            """,
            (generated_node_id, canvas_id, '{"asset_id":"asset-1","source_node_ids":["source-node-1"],"media_type":"image/png","task_id":"task-1","final_prompt":"hero"}', now, now),
        )

    with TestClient(create_app(settings)):
        pass

    repository = BillingRepository(SQLiteDatabase(settings.database_path))
    account = repository.get_or_create_account(user_id, 100)
    transactions = repository.list_transactions(user_id, limit=10)

    with database.connect() as connection:
        task_row = connection.execute("SELECT status FROM generation_tasks WHERE id = ?", (task_id,)).fetchone()
        asset_row = connection.execute("SELECT id FROM assets WHERE id = ?", (asset_id,)).fetchone()
        node_row = connection.execute("SELECT id FROM canvas_nodes WHERE id = ?", (generated_node_id,)).fetchone()

    assert account.balance == 100
    assert task_row["status"] == "failed"
    assert asset_row is None
    assert node_row is None
    assert not generated_file.exists()
    assert [item.direction for item in transactions] == ["credit", "debit"]
    assert transactions[0].metadata["reason"] == "startup recovery"



def test_startup_cleans_side_effects_for_already_failed_charged_canvas_task(tmp_path):
    settings = Settings(
        auth_required=False,
        rate_limit_requests=1000,
        database_path=tmp_path / "app.db",
        asset_upload_dir=tmp_path / "uploads",
        use_mock_images=True,
        use_mock_videos=True,
        secure_session_cookies=False,
        initial_credit_balance=100,
    )
    dependencies.get_storage.cache_clear()
    dependencies._database_for_path.cache_clear()
    routes._rate_limit_hits.clear()

    database = SQLiteDatabase(settings.database_path)
    now = datetime.now(timezone.utc).isoformat()
    user_id = "user-1"
    project_id = "project-1"
    canvas_id = "canvas-1"
    task_id = "task-1"
    debit_id = "debit-1"
    refund_id = "refund-1"
    asset_id = "asset-1"
    generated_node_id = "generated-node-1"
    source_node_id = "source-node-1"
    image_dir = settings.asset_upload_dir / "image-optimizer"
    image_dir.mkdir(parents=True)
    generated_file = image_dir / f"generated-{task_id}.png"
    generated_file.write_bytes(b"orphan")

    with database.connect() as connection:
        connection.execute(
            """
            INSERT INTO users (id, username, email, password_hash, role, created_at)
            VALUES (?, 'ada', 'ada@example.com', 'hash', 'user', ?)
            """,
            (user_id, now),
        )
        connection.execute(
            """
            INSERT INTO projects (id, owner_id, name, description, created_at, updated_at)
            VALUES (?, ?, 'Canvas project', '', ?, ?)
            """,
            (project_id, user_id, now, now),
        )
        connection.execute(
            """
            INSERT INTO canvases (id, owner_id, project_id, name, description, created_at, updated_at)
            VALUES (?, ?, ?, 'Main board', '', ?, ?)
            """,
            (canvas_id, user_id, project_id, now, now),
        )
        connection.execute(
            """
            INSERT INTO canvas_nodes (id, canvas_id, type, title, position_json, size_json, payload_json, created_at, updated_at)
            VALUES (?, ?, 'storyboard', 'Source', '{"x":0,"y":0}', '{"width":320,"height":180}', '{"prompt":"hero"}', ?, ?)
            """,
            (source_node_id, canvas_id, now, now),
        )
        connection.execute(
            """
            INSERT INTO credit_accounts (user_id, balance, lifetime_granted, lifetime_spent, updated_at)
            VALUES (?, 100, 100, 80, ?)
            """,
            (user_id, now),
        )
        connection.execute(
            """
            INSERT INTO generation_tasks (
                id, owner_id, project_id, kind, status, input_json, result_json, history_json, error,
                cost_estimate, charged_credits, created_at, updated_at
            )
            VALUES (?, ?, ?, 'image', 'failed', ?, NULL, NULL, 'startup recovery', 80, 80, ?, ?)
            """,
            (task_id, user_id, project_id, '{"credit_transaction_id":"debit-1","canvas_id":"canvas-1"}', now, now),
        )
        connection.execute(
            """
            INSERT INTO credit_transactions (
                id, user_id, project_id, task_id, action_type, direction, amount, status, metadata_json,
                refund_of_transaction_id, created_at
            )
            VALUES (?, ?, ?, ?, 'canvas_image', 'debit', 80, 'applied', ?, NULL, ?)
            """,
            (debit_id, user_id, project_id, task_id, '{"source":"canvas_image","canvas_id":"canvas-1"}', now),
        )
        connection.execute(
            """
            INSERT INTO credit_transactions (
                id, user_id, project_id, task_id, action_type, direction, amount, status, metadata_json,
                refund_of_transaction_id, created_at
            )
            VALUES (?, ?, ?, ?, 'canvas_image', 'credit', 80, 'applied', ?, ?, ?)
            """,
            (refund_id, user_id, project_id, task_id, '{"reason":"startup recovery","canvas_id":"canvas-1"}', debit_id, now),
        )
        connection.execute(
            """
            INSERT INTO assets (id, owner_id, project_id, kind, url, media_type, metadata_json, created_at)
            VALUES (?, ?, ?, 'image', ?, 'image/png', ?, ?)
            """,
            (asset_id, user_id, project_id, f"/uploads/image-optimizer/{generated_file.name}", '{"task_id":"task-1","canvas_id":"canvas-1","source":"canvas_generation","source_node_ids":["source-node-1"]}', now),
        )
        connection.execute(
            """
            INSERT INTO canvas_nodes (id, canvas_id, type, title, position_json, size_json, payload_json, created_at, updated_at)
            VALUES (?, ?, 'generated_image', 'Generated image', '{"x":420,"y":0}', '{"width":320,"height":220}', ?, ?, ?)
            """,
            (generated_node_id, canvas_id, '{"asset_id":"asset-1","source_node_ids":["source-node-1"],"media_type":"image/png","task_id":"task-1","final_prompt":"hero"}', now, now),
        )

    with TestClient(create_app(settings)):
        pass

    repository = BillingRepository(SQLiteDatabase(settings.database_path))
    account = repository.get_or_create_account(user_id, 100)
    transactions = repository.list_transactions(user_id, limit=10)

    with database.connect() as connection:
        task_row = connection.execute("SELECT status FROM generation_tasks WHERE id = ?", (task_id,)).fetchone()
        asset_row = connection.execute("SELECT id FROM assets WHERE id = ?", (asset_id,)).fetchone()
        node_row = connection.execute("SELECT id FROM canvas_nodes WHERE id = ?", (generated_node_id,)).fetchone()

    assert account.balance == 100
    assert task_row["status"] == "failed"
    assert asset_row is None
    assert node_row is None
    assert not generated_file.exists()
    assert [item.direction for item in transactions] == ["credit", "debit"]



def test_startup_recovers_charged_project_task_when_debit_was_not_attached(tmp_path):
    settings = Settings(
        auth_required=False,
        rate_limit_requests=1000,
        database_path=tmp_path / "app.db",
        asset_upload_dir=tmp_path / "uploads",
        use_mock_images=True,
        use_mock_videos=True,
        secure_session_cookies=False,
        initial_credit_balance=100,
    )
    dependencies.get_storage.cache_clear()
    dependencies._database_for_path.cache_clear()
    routes._rate_limit_hits.clear()

    database = SQLiteDatabase(settings.database_path)
    now = datetime.now(timezone.utc).isoformat()
    stale = (datetime.now(timezone.utc) - timedelta(hours=7)).isoformat()
    user_id = "user-1"
    project_id = "project-1"
    task_id = "task-1"
    debit_id = "debit-1"

    with database.connect() as connection:
        connection.execute(
            """
            INSERT INTO users (id, username, email, password_hash, role, created_at)
            VALUES (?, 'ada', 'ada@example.com', 'hash', 'user', ?)
            """,
            (user_id, now),
        )
        connection.execute(
            """
            INSERT INTO projects (id, owner_id, name, description, created_at, updated_at)
            VALUES (?, ?, 'Video campaign', '', ?, ?)
            """,
            (project_id, user_id, now, now),
        )
        connection.execute(
            """
            INSERT INTO credit_accounts (user_id, balance, lifetime_granted, lifetime_spent, updated_at)
            VALUES (?, 20, 100, 80, ?)
            """,
            (user_id, now),
        )
        connection.execute(
            """
            INSERT INTO generation_tasks (
                id, owner_id, project_id, kind, status, input_json, result_json, history_json, error,
                cost_estimate, charged_credits, created_at, updated_at
            )
            VALUES (?, ?, ?, 'image_to_video', 'running', ?, NULL, NULL, NULL, 80, 80, ?, ?)
            """,
            (task_id, user_id, project_id, '{"credit_transaction_id":"debit-1"}', stale, stale),
        )
        connection.execute(
            """
            INSERT INTO credit_transactions (
                id, user_id, project_id, task_id, action_type, direction, amount, status, metadata_json,
                refund_of_transaction_id, created_at
            )
            VALUES (?, ?, ?, NULL, 'project_video', 'debit', 80, 'applied', ?, NULL, ?)
            """,
            (debit_id, user_id, project_id, '{"source":"project_video"}', now),
        )

    with TestClient(create_app(settings)):
        pass

    repository = BillingRepository(SQLiteDatabase(settings.database_path))
    account = repository.get_or_create_account(user_id, 100)
    transactions = repository.list_transactions(user_id, limit=10)

    with database.connect() as connection:
        task_row = connection.execute("SELECT status FROM generation_tasks WHERE id = ?", (task_id,)).fetchone()
        debit_row = connection.execute("SELECT task_id FROM credit_transactions WHERE id = ?", (debit_id,)).fetchone()

    assert account.balance == 100
    assert task_row["status"] == "failed"
    assert debit_row["task_id"] == task_id
    assert [item.direction for item in transactions] == ["credit", "debit"]
    assert transactions[0].metadata["reason"] == "startup recovery"
