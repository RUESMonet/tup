# Professional Canvas Phase 1C SaaS Controls Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add SaaS safety controls around the existing project/canvas generation workflows: credit balances, immutable credit transactions, simple daily quotas, asset review state, and admin visibility.

**Architecture:** Keep the FastAPI monolith and SQLite repository pattern. Add a focused billing service/repository for credit and quota checks, add review fields directly to assets, and extend existing account/admin/frontend surfaces without changing the core image/video pipelines.

**Tech Stack:** FastAPI, Pydantic v2, SQLite, existing auth/admin dependencies, existing project/canvas generation routes, React/Vite.

---

## Scope

This phase implements a narrow SaaS controls baseline:

- User credit account with default starting balance.
- Immutable credit transaction ledger for high-cost generation actions.
- Simple daily quota counters per user and action type.
- Credit preflight checks before project/canvas task creation.
- Credit refund transaction when a charged background generation task fails.
- Asset review state on uploaded and generated project assets.
- Admin API visibility for users, tasks, assets, review queue, and credit balances.
- Minimal frontend visibility for credit balance, costs, review state, and admin operations.

This phase does not implement payments, subscriptions, team billing, public publishing gates, multi-user collaboration, or external moderation integrations.

## File Structure

- Create: `src/models/billing.py`
  - Pydantic models and action type literals for credit balances, transactions, quota summaries, cost tables, and account responses.
- Create: `src/services/billing_repository.py`
  - SQLite credit account, transaction, quota, and asset review persistence.
- Create: `src/services/billing_service.py`
  - Small orchestration layer for cost lookup, quota checks, debits, refunds, and task linkage.
- Create: `src/services/admin_repository.py`
  - Admin list queries across users, tasks, assets, and credit balances.
- Create: `src/api/account_routes.py`
  - Authenticated account endpoints for credit summary, costs, and transaction history.
- Modify: `src/services/database.py`
  - Add credit tables, quota table, asset review columns, and optional generation task cost columns.
- Modify: `src/config.py`
  - Add credit defaults, per-action costs, and per-action daily quota settings.
- Modify: `src/dependencies.py`
  - Add `get_billing_repository`, `get_billing_service`, and `get_admin_repository` dependencies.
- Modify: `src/main.py`
  - Include the account router.
- Modify: `src/models/project.py`
  - Add review and charge fields to asset/task responses.
- Modify: `src/services/project_repository.py`
  - Read/write asset review fields and task charge fields.
- Modify: `src/api/project_routes.py`
  - Ensure uploaded assets default to pending review through repository behavior.
- Modify: `src/api/generation_routes.py`
  - Enforce credits/quotas for project image, image edit, and video generation; refund on task failure.
- Modify: `src/api/canvas_routes.py`
  - Enforce credits/quotas for canvas image, image edit, image batch, and video generation; refund on task failure.
- Modify: `src/models/admin.py`
  - Add admin response/request models for users, tasks, assets, review queue, and review updates.
- Modify: `src/api/admin_routes.py`
  - Add admin users, tasks, review queue, and review update endpoints.
- Create: `tests/test_billing.py`
  - Billing repository/service and account API tests.
- Create: `tests/test_admin_operations.py`
  - Admin visibility and review mutation tests.
- Modify: `tests/test_projects.py` or create if absent by using existing project route test patterns.
  - Project asset review-state and credit display coverage if a focused file exists; otherwise keep route tests in `tests/test_billing.py`.
- Modify: `tests/test_canvas_routes.py`
  - Canvas credit enforcement and refund regression tests.
- Create: `frontend/src/api/account.js`
  - Account credit/cost/transaction API calls.
- Modify: `frontend/src/api/admin.js`
  - Admin operations API calls.
- Create: `frontend/src/account/AccountCreditsPanel.jsx`
  - Compact credit balance/cost display used in the project workspace.
- Create: `frontend/src/admin/AdminOperationsPage.jsx`
  - Admin operations tabs for model settings, users, tasks, and review queue.
- Modify: `frontend/src/admin/AdminModelSettingsPage.jsx`
  - Export existing model settings content as a tab-friendly component or embed it inside the new operations page.
- Modify: `frontend/src/workspace/ProjectWorkspace.jsx`
  - Load and display credit summary/cost hints and review state.
- Modify: `frontend/src/workspace/AssetGallery.jsx`
  - Show review status and charged credits on asset/task cards.
- Modify: `frontend/src/App.jsx`
  - Route admin users to the new admin operations page.

## Shared Constants and Action Names

Use these exact action names in backend models, services, tests, and frontend labels:

```python
CreditAction = Literal[
    "project_image",
    "project_image_edit",
    "project_video",
    "canvas_image",
    "canvas_image_edit",
    "canvas_image_batch",
    "canvas_video",
]
```

Default costs:

```python
DEFAULT_ACTION_COSTS = {
    "project_image": 10,
    "project_image_edit": 12,
    "project_video": 80,
    "canvas_image": 10,
    "canvas_image_edit": 12,
    "canvas_image_batch": 20,
    "canvas_video": 80,
}
```

Default daily quotas:

```python
DEFAULT_DAILY_QUOTAS = {
    "project_image": 100,
    "project_image_edit": 50,
    "project_video": 20,
    "canvas_image": 100,
    "canvas_image_edit": 50,
    "canvas_image_batch": 60,
    "canvas_video": 20,
}
```

The first implementation should use integer credits only. No decimals and no currency formatting.

## Task 1: Database, Billing Models, and Repository

**Files:**
- Create: `src/models/billing.py`
- Create: `src/services/billing_repository.py`
- Modify: `src/services/database.py:20-260`
- Test: `tests/test_billing.py`

- [ ] **Step 1: Write failing billing repository tests**

Create `tests/test_billing.py` with these initial tests:

```python
import sqlite3

import pytest
from fastapi.testclient import TestClient

import src.dependencies as dependencies
from src.api import image_routes as routes
from src.config import Settings
from src.main import create_app
from src.services.billing_repository import BillingRepository
from src.services.database import SQLiteDatabase


def _client(tmp_path, **settings_updates):
    settings = Settings(
        auth_required=False,
        rate_limit_requests=1000,
        database_path=tmp_path / "app.db",
        asset_upload_dir=tmp_path / "uploads",
        use_mock_images=True,
        use_mock_videos=True,
        secure_session_cookies=False,
        initial_credit_balance=100,
        **settings_updates,
    )
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


def test_billing_repository_creates_default_account_and_debits(tmp_path):
    client, settings = _client(tmp_path)
    user_id = _register(client, "ada")
    repository = BillingRepository(SQLiteDatabase(settings.database_path))

    account = repository.get_or_create_account(user_id, 100)
    transaction = repository.debit(
        user_id=user_id,
        project_id="project-1",
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
            project_id="project-1",
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
    repository = BillingRepository(SQLiteDatabase(settings.database_path))
    debit = repository.debit(user_id, "project-1", "task-1", "project_video", 80, {"source": "test"})

    refund = repository.refund(user_id=user_id, original_transaction_id=debit.id, task_id="task-1", reason="failed task")
    account = repository.get_or_create_account(user_id, 100)
    transactions = repository.list_transactions(user_id, limit=10)

    assert refund.direction == "credit"
    assert refund.amount == 80
    assert refund.metadata["refund_of"] == debit.id
    assert account.balance == 100
    assert [item.direction for item in transactions] == ["credit", "debit"]
```

- [ ] **Step 2: Run tests to verify RED**

Run:

```bash
.venv/bin/python -m pytest tests/test_billing.py::test_billing_repository_creates_default_account_and_debits tests/test_billing.py::test_billing_repository_rejects_insufficient_credit_without_transaction tests/test_billing.py::test_billing_repository_refunds_failed_task_with_ledger_entry -q
```

Expected: fail during import with `ModuleNotFoundError: No module named 'src.services.billing_repository'`.

- [ ] **Step 3: Add billing models**

Create `src/models/billing.py`:

```python
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


CreditAction = Literal[
    "project_image",
    "project_image_edit",
    "project_video",
    "canvas_image",
    "canvas_image_edit",
    "canvas_image_batch",
    "canvas_video",
]
CreditDirection = Literal["debit", "credit"]
CreditTransactionStatus = Literal["applied", "refunded", "voided"]
ReviewStatus = Literal["pending", "approved", "rejected"]


class CreditAccountResponse(BaseModel):
    user_id: str
    balance: int
    lifetime_granted: int
    lifetime_spent: int
    updated_at: datetime


class CreditTransactionResponse(BaseModel):
    id: str
    user_id: str
    project_id: str | None = None
    task_id: str | None = None
    action_type: CreditAction
    direction: CreditDirection
    amount: int
    status: CreditTransactionStatus
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class QuotaUsageResponse(BaseModel):
    action_type: CreditAction
    scope: Literal["daily"]
    period_key: str
    used_count: int
    limit_count: int


class CreditCostResponse(BaseModel):
    action_type: CreditAction
    cost: int
    daily_quota: int


class AccountCreditsResponse(BaseModel):
    account: CreditAccountResponse
    quotas: list[QuotaUsageResponse]
    costs: list[CreditCostResponse]


class CreditTransactionListResponse(BaseModel):
    transactions: list[CreditTransactionResponse]
```

- [ ] **Step 4: Add database tables and columns**

Modify `src/services/database.py` inside the `CREATE TABLE` script after `generation_tasks`:

```sql
                CREATE TABLE IF NOT EXISTS credit_accounts (
                    user_id TEXT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
                    balance INTEGER NOT NULL CHECK (balance >= 0),
                    lifetime_granted INTEGER NOT NULL DEFAULT 0 CHECK (lifetime_granted >= 0),
                    lifetime_spent INTEGER NOT NULL DEFAULT 0 CHECK (lifetime_spent >= 0),
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS credit_transactions (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    project_id TEXT REFERENCES projects(id) ON DELETE SET NULL,
                    task_id TEXT REFERENCES generation_tasks(id) ON DELETE SET NULL,
                    action_type TEXT NOT NULL,
                    direction TEXT NOT NULL CHECK (direction IN ('debit', 'credit')),
                    amount INTEGER NOT NULL CHECK (amount > 0),
                    status TEXT NOT NULL DEFAULT 'applied' CHECK (status IN ('applied', 'refunded', 'voided')),
                    metadata_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_credit_transactions_user_created ON credit_transactions(user_id, created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_credit_transactions_task ON credit_transactions(task_id);

                CREATE TABLE IF NOT EXISTS usage_quotas (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    scope TEXT NOT NULL CHECK (scope IN ('daily')),
                    period_key TEXT NOT NULL,
                    action_type TEXT NOT NULL,
                    used_count INTEGER NOT NULL DEFAULT 0 CHECK (used_count >= 0),
                    limit_count INTEGER NOT NULL CHECK (limit_count >= 0),
                    updated_at TEXT NOT NULL,
                    UNIQUE (user_id, scope, period_key, action_type)
                );
```

Add these migration helpers after the current `_add_column_if_missing` calls:

```python
            _add_column_if_missing(connection, "assets", "review_status", "TEXT NOT NULL DEFAULT 'pending'")
            _add_column_if_missing(connection, "assets", "review_notes", "TEXT NOT NULL DEFAULT ''")
            _add_column_if_missing(connection, "assets", "reviewed_by", "TEXT")
            _add_column_if_missing(connection, "assets", "reviewed_at", "TEXT")
            _add_column_if_missing(connection, "generation_tasks", "cost_estimate", "INTEGER NOT NULL DEFAULT 0")
            _add_column_if_missing(connection, "generation_tasks", "charged_credits", "INTEGER NOT NULL DEFAULT 0")
```

- [ ] **Step 5: Add billing repository**

Create `src/services/billing_repository.py`:

```python
import json
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from src.models.billing import CreditAccountResponse, CreditTransactionResponse, QuotaUsageResponse
from src.services.database import SQLiteDatabase


class BillingRepository:
    def __init__(self, database: SQLiteDatabase):
        self.database = database

    def get_or_create_account(self, user_id: str, initial_balance: int) -> CreditAccountResponse:
        now = _utc_now()
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT user_id, balance, lifetime_granted, lifetime_spent, updated_at FROM credit_accounts WHERE user_id = ?",
                (user_id,),
            ).fetchone()
            if row is None:
                connection.execute(
                    """
                    INSERT INTO credit_accounts (user_id, balance, lifetime_granted, lifetime_spent, updated_at)
                    VALUES (?, ?, ?, 0, ?)
                    """,
                    (user_id, initial_balance, initial_balance, now),
                )
                row = connection.execute(
                    "SELECT user_id, balance, lifetime_granted, lifetime_spent, updated_at FROM credit_accounts WHERE user_id = ?",
                    (user_id,),
                ).fetchone()
        return _account_response(row)

    def debit(self, user_id: str, project_id: str | None, task_id: str | None, action_type: str, amount: int, metadata: dict[str, Any]) -> CreditTransactionResponse:
        transaction_id = str(uuid4())
        now = _utc_now()
        with self.database.connect() as connection:
            row = connection.execute("SELECT balance FROM credit_accounts WHERE user_id = ?", (user_id,)).fetchone()
            if row is None:
                raise ValueError("Credit account not found")
            if int(row["balance"]) < amount:
                raise ValueError("Insufficient credits")
            connection.execute(
                "UPDATE credit_accounts SET balance = balance - ?, lifetime_spent = lifetime_spent + ?, updated_at = ? WHERE user_id = ?",
                (amount, amount, now, user_id),
            )
            connection.execute(
                """
                INSERT INTO credit_transactions (id, user_id, project_id, task_id, action_type, direction, amount, status, metadata_json, created_at)
                VALUES (?, ?, ?, ?, ?, 'debit', ?, 'applied', ?, ?)
                """,
                (transaction_id, user_id, project_id, task_id, action_type, amount, _json(metadata), now),
            )
        return self.get_transaction(user_id, transaction_id)

    def attach_task(self, user_id: str, transaction_id: str, task_id: str) -> None:
        with self.database.connect() as connection:
            connection.execute("UPDATE credit_transactions SET task_id = ? WHERE user_id = ? AND id = ?", (task_id, user_id, transaction_id))

    def refund(self, user_id: str, original_transaction_id: str, task_id: str | None, reason: str) -> CreditTransactionResponse:
        original = self.get_transaction(user_id, original_transaction_id)
        if original.direction != "debit":
            raise ValueError("Only debit transactions can be refunded")
        existing = self.find_refund(user_id, original_transaction_id)
        if existing is not None:
            return existing
        transaction_id = str(uuid4())
        now = _utc_now()
        metadata = {"refund_of": original_transaction_id, "reason": reason}
        with self.database.connect() as connection:
            connection.execute(
                "UPDATE credit_accounts SET balance = balance + ?, updated_at = ? WHERE user_id = ?",
                (original.amount, now, user_id),
            )
            connection.execute(
                """
                INSERT INTO credit_transactions (id, user_id, project_id, task_id, action_type, direction, amount, status, metadata_json, created_at)
                VALUES (?, ?, ?, ?, ?, 'credit', ?, 'applied', ?, ?)
                """,
                (transaction_id, user_id, original.project_id, task_id or original.task_id, original.action_type, original.amount, _json(metadata), now),
            )
            connection.execute("UPDATE credit_transactions SET status = 'refunded' WHERE user_id = ? AND id = ?", (user_id, original_transaction_id))
        return self.get_transaction(user_id, transaction_id)

    def increment_quota(self, user_id: str, action_type: str, period_key: str, limit_count: int) -> QuotaUsageResponse:
        quota_id = str(uuid4())
        now = _utc_now()
        with self.database.connect() as connection:
            row = connection.execute(
                """
                SELECT id, used_count FROM usage_quotas
                WHERE user_id = ? AND scope = 'daily' AND period_key = ? AND action_type = ?
                """,
                (user_id, period_key, action_type),
            ).fetchone()
            if row is None:
                if limit_count < 1:
                    raise ValueError("Daily quota exceeded")
                connection.execute(
                    """
                    INSERT INTO usage_quotas (id, user_id, scope, period_key, action_type, used_count, limit_count, updated_at)
                    VALUES (?, ?, 'daily', ?, ?, 1, ?, ?)
                    """,
                    (quota_id, user_id, period_key, action_type, limit_count, now),
                )
            else:
                if int(row["used_count"]) >= limit_count:
                    raise ValueError("Daily quota exceeded")
                connection.execute(
                    """
                    UPDATE usage_quotas
                    SET used_count = used_count + 1, limit_count = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (limit_count, now, row["id"]),
                )
        return self.get_quota(user_id, action_type, period_key, limit_count)

    def get_quota(self, user_id: str, action_type: str, period_key: str, limit_count: int) -> QuotaUsageResponse:
        with self.database.connect() as connection:
            row = connection.execute(
                """
                SELECT action_type, scope, period_key, used_count, limit_count
                FROM usage_quotas
                WHERE user_id = ? AND scope = 'daily' AND period_key = ? AND action_type = ?
                """,
                (user_id, period_key, action_type),
            ).fetchone()
        if row is None:
            return QuotaUsageResponse(action_type=action_type, scope="daily", period_key=period_key, used_count=0, limit_count=limit_count)
        return QuotaUsageResponse(action_type=row["action_type"], scope=row["scope"], period_key=row["period_key"], used_count=row["used_count"], limit_count=row["limit_count"])

    def get_transaction(self, user_id: str, transaction_id: str) -> CreditTransactionResponse:
        with self.database.connect() as connection:
            row = connection.execute(
                """
                SELECT id, user_id, project_id, task_id, action_type, direction, amount, status, metadata_json, created_at
                FROM credit_transactions
                WHERE user_id = ? AND id = ?
                """,
                (user_id, transaction_id),
            ).fetchone()
        if row is None:
            raise ValueError("Credit transaction not found")
        return _transaction_response(row)

    def find_refund(self, user_id: str, original_transaction_id: str) -> CreditTransactionResponse | None:
        with self.database.connect() as connection:
            rows = connection.execute(
                """
                SELECT id, user_id, project_id, task_id, action_type, direction, amount, status, metadata_json, created_at
                FROM credit_transactions
                WHERE user_id = ? AND direction = 'credit'
                ORDER BY created_at DESC
                """,
                (user_id,),
            ).fetchall()
        for row in rows:
            transaction = _transaction_response(row)
            if transaction.metadata.get("refund_of") == original_transaction_id:
                return transaction
        return None

    def list_transactions(self, user_id: str, limit: int = 50, project_id: str | None = None) -> list[CreditTransactionResponse]:
        query = """
            SELECT id, user_id, project_id, task_id, action_type, direction, amount, status, metadata_json, created_at
            FROM credit_transactions
            WHERE user_id = ?
        """
        values: tuple[Any, ...] = (user_id,)
        if project_id is not None:
            query = f"{query} AND project_id = ?"
            values = (*values, project_id)
        query = f"{query} ORDER BY created_at DESC LIMIT ?"
        values = (*values, limit)
        with self.database.connect() as connection:
            rows = connection.execute(query, values).fetchall()
        return [_transaction_response(row) for row in rows]


def _account_response(row) -> CreditAccountResponse:
    return CreditAccountResponse(
        user_id=row["user_id"],
        balance=row["balance"],
        lifetime_granted=row["lifetime_granted"],
        lifetime_spent=row["lifetime_spent"],
        updated_at=_dt(row["updated_at"]),
    )


def _transaction_response(row) -> CreditTransactionResponse:
    return CreditTransactionResponse(
        id=row["id"],
        user_id=row["user_id"],
        project_id=row["project_id"],
        task_id=row["task_id"],
        action_type=row["action_type"],
        direction=row["direction"],
        amount=row["amount"],
        status=row["status"],
        metadata=json.loads(row["metadata_json"]),
        created_at=_dt(row["created_at"]),
    )


def _json(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _dt(value: str) -> datetime:
    return datetime.fromisoformat(value)
```

- [ ] **Step 6: Run billing repository tests to verify GREEN**

Run:

```bash
.venv/bin/python -m pytest tests/test_billing.py::test_billing_repository_creates_default_account_and_debits tests/test_billing.py::test_billing_repository_rejects_insufficient_credit_without_transaction tests/test_billing.py::test_billing_repository_refunds_failed_task_with_ledger_entry -q
```

Expected: `3 passed`.

- [ ] **Step 7: Commit checkpoint if executing in a git repo**

Current workspace `/Users/apple/Documents/tup` is not a git repository. If execution has moved into a git repo, run:

```bash
git add src/models/billing.py src/services/billing_repository.py src/services/database.py tests/test_billing.py
git commit -m "feat: add credit ledger persistence"
```

## Task 2: Billing Service, Settings, Dependencies, and Account API

**Files:**
- Create: `src/services/billing_service.py`
- Create: `src/api/account_routes.py`
- Modify: `src/config.py:13-130`
- Modify: `src/dependencies.py`
- Modify: `src/main.py`
- Test: `tests/test_billing.py`

- [ ] **Step 1: Add failing account API and quota tests**

Append to `tests/test_billing.py`:

```python
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
    repository.debit(ada_id, "project-1", "task-1", "canvas_image", 10, {})

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
    first = service.charge_for_action(user_id, "project-1", "canvas_video", {"attempt": 1})

    with pytest.raises(ValueError, match="Daily quota exceeded"):
        service.charge_for_action(user_id, "project-1", "canvas_video", {"attempt": 2})

    assert first.amount == 5
```

- [ ] **Step 2: Run tests to verify RED**

Run:

```bash
.venv/bin/python -m pytest tests/test_billing.py::test_account_credits_returns_balance_costs_and_quota tests/test_billing.py::test_account_transactions_are_owner_scoped tests/test_billing.py::test_billing_service_enforces_daily_quota -q
```

Expected: fail with 404 for `/api/account/credits` and `ModuleNotFoundError` or import error for `src.services.billing_service`.

- [ ] **Step 3: Add settings fields**

Modify `src/config.py` `Settings` with these fields after `model_base_url_allowed_hosts`:

```python
    initial_credit_balance: int = Field(default=1000, alias="INITIAL_CREDIT_BALANCE")
    project_image_credit_cost: int = Field(default=10, alias="PROJECT_IMAGE_CREDIT_COST")
    project_image_edit_credit_cost: int = Field(default=12, alias="PROJECT_IMAGE_EDIT_CREDIT_COST")
    project_video_credit_cost: int = Field(default=80, alias="PROJECT_VIDEO_CREDIT_COST")
    canvas_image_credit_cost: int = Field(default=10, alias="CANVAS_IMAGE_CREDIT_COST")
    canvas_image_edit_credit_cost: int = Field(default=12, alias="CANVAS_IMAGE_EDIT_CREDIT_COST")
    canvas_image_batch_credit_cost: int = Field(default=20, alias="CANVAS_IMAGE_BATCH_CREDIT_COST")
    canvas_video_credit_cost: int = Field(default=80, alias="CANVAS_VIDEO_CREDIT_COST")
    daily_project_image_quota: int = Field(default=100, alias="DAILY_PROJECT_IMAGE_QUOTA")
    daily_project_image_edit_quota: int = Field(default=50, alias="DAILY_PROJECT_IMAGE_EDIT_QUOTA")
    daily_project_video_quota: int = Field(default=20, alias="DAILY_PROJECT_VIDEO_QUOTA")
    daily_canvas_image_quota: int = Field(default=100, alias="DAILY_CANVAS_IMAGE_QUOTA")
    daily_canvas_image_edit_quota: int = Field(default=50, alias="DAILY_CANVAS_IMAGE_EDIT_QUOTA")
    daily_canvas_image_batch_quota: int = Field(default=60, alias="DAILY_CANVAS_IMAGE_BATCH_QUOTA")
    daily_canvas_video_quota: int = Field(default=20, alias="DAILY_CANVAS_VIDEO_QUOTA")
```

Add these entries to the `values` dict in `get_settings()`:

```python
        "INITIAL_CREDIT_BALANCE": _int_env("INITIAL_CREDIT_BALANCE", 1000),
        "PROJECT_IMAGE_CREDIT_COST": _int_env("PROJECT_IMAGE_CREDIT_COST", 10),
        "PROJECT_IMAGE_EDIT_CREDIT_COST": _int_env("PROJECT_IMAGE_EDIT_CREDIT_COST", 12),
        "PROJECT_VIDEO_CREDIT_COST": _int_env("PROJECT_VIDEO_CREDIT_COST", 80),
        "CANVAS_IMAGE_CREDIT_COST": _int_env("CANVAS_IMAGE_CREDIT_COST", 10),
        "CANVAS_IMAGE_EDIT_CREDIT_COST": _int_env("CANVAS_IMAGE_EDIT_CREDIT_COST", 12),
        "CANVAS_IMAGE_BATCH_CREDIT_COST": _int_env("CANVAS_IMAGE_BATCH_CREDIT_COST", 20),
        "CANVAS_VIDEO_CREDIT_COST": _int_env("CANVAS_VIDEO_CREDIT_COST", 80),
        "DAILY_PROJECT_IMAGE_QUOTA": _int_env("DAILY_PROJECT_IMAGE_QUOTA", 100),
        "DAILY_PROJECT_IMAGE_EDIT_QUOTA": _int_env("DAILY_PROJECT_IMAGE_EDIT_QUOTA", 50),
        "DAILY_PROJECT_VIDEO_QUOTA": _int_env("DAILY_PROJECT_VIDEO_QUOTA", 20),
        "DAILY_CANVAS_IMAGE_QUOTA": _int_env("DAILY_CANVAS_IMAGE_QUOTA", 100),
        "DAILY_CANVAS_IMAGE_EDIT_QUOTA": _int_env("DAILY_CANVAS_IMAGE_EDIT_QUOTA", 50),
        "DAILY_CANVAS_IMAGE_BATCH_QUOTA": _int_env("DAILY_CANVAS_IMAGE_BATCH_QUOTA", 60),
        "DAILY_CANVAS_VIDEO_QUOTA": _int_env("DAILY_CANVAS_VIDEO_QUOTA", 20),
```

- [ ] **Step 4: Add billing service**

Create `src/services/billing_service.py`:

```python
from datetime import datetime, timezone
from typing import Any

from src.config import Settings
from src.models.billing import CreditCostResponse, CreditTransactionResponse, QuotaUsageResponse
from src.services.billing_repository import BillingRepository


CREDIT_COST_FIELDS = {
    "project_image": "project_image_credit_cost",
    "project_image_edit": "project_image_edit_credit_cost",
    "project_video": "project_video_credit_cost",
    "canvas_image": "canvas_image_credit_cost",
    "canvas_image_edit": "canvas_image_edit_credit_cost",
    "canvas_image_batch": "canvas_image_batch_credit_cost",
    "canvas_video": "canvas_video_credit_cost",
}

DAILY_QUOTA_FIELDS = {
    "project_image": "daily_project_image_quota",
    "project_image_edit": "daily_project_image_edit_quota",
    "project_video": "daily_project_video_quota",
    "canvas_image": "daily_canvas_image_quota",
    "canvas_image_edit": "daily_canvas_image_edit_quota",
    "canvas_image_batch": "daily_canvas_image_batch_quota",
    "canvas_video": "daily_canvas_video_quota",
}


class BillingService:
    def __init__(self, repository: BillingRepository, settings: Settings):
        self.repository = repository
        self.settings = settings

    def costs(self) -> list[CreditCostResponse]:
        return [CreditCostResponse(action_type=action, cost=self.cost_for(action), daily_quota=self.daily_quota_for(action)) for action in CREDIT_COST_FIELDS]

    def quotas_for_user(self, user_id: str) -> list[QuotaUsageResponse]:
        period_key = self.current_daily_period_key()
        return [self.repository.get_quota(user_id, action, period_key, self.daily_quota_for(action)) for action in CREDIT_COST_FIELDS]

    def charge_for_action(self, user_id: str, project_id: str | None, action_type: str, metadata: dict[str, Any]) -> CreditTransactionResponse:
        self.repository.get_or_create_account(user_id, self.settings.initial_credit_balance)
        self.repository.increment_quota(user_id, action_type, self.current_daily_period_key(), self.daily_quota_for(action_type))
        return self.repository.debit(user_id, project_id, None, action_type, self.cost_for(action_type), metadata)

    def attach_task(self, user_id: str, transaction_id: str, task_id: str) -> None:
        self.repository.attach_task(user_id, transaction_id, task_id)

    def refund_failed_task(self, user_id: str, transaction_id: str | None, task_id: str, reason: str) -> None:
        if transaction_id is None:
            return
        self.repository.refund(user_id=user_id, original_transaction_id=transaction_id, task_id=task_id, reason=reason)

    def cost_for(self, action_type: str) -> int:
        field = CREDIT_COST_FIELDS[action_type]
        return int(getattr(self.settings, field))

    def daily_quota_for(self, action_type: str) -> int:
        field = DAILY_QUOTA_FIELDS[action_type]
        return int(getattr(self.settings, field))

    def current_daily_period_key(self) -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%d")
```

- [ ] **Step 5: Add dependencies**

Modify `src/dependencies.py` imports and functions:

```python
from src.services.admin_repository import AdminRepository
from src.services.billing_repository import BillingRepository
from src.services.billing_service import BillingService
```

Add:

```python
def get_billing_repository(database: SQLiteDatabase = Depends(get_database)) -> BillingRepository:
    return BillingRepository(database)


def get_billing_service(
    repository: BillingRepository = Depends(get_billing_repository),
    settings: Settings = Depends(get_settings),
) -> BillingService:
    return BillingService(repository, settings)


def get_admin_repository(database: SQLiteDatabase = Depends(get_database)) -> AdminRepository:
    return AdminRepository(database)
```

If `AdminRepository` is not created until Task 5, add only billing dependencies in this task and add admin dependency in Task 5.

- [ ] **Step 6: Add account routes and include router**

Create `src/api/account_routes.py`:

```python
from fastapi import APIRouter, Depends, Query

from src.dependencies import get_billing_service, require_current_user
from src.models.auth import AuthUser
from src.models.billing import AccountCreditsResponse, CreditTransactionListResponse
from src.services.billing_service import BillingService


router = APIRouter(prefix="/api/account", tags=["account"])


@router.get("/credits", response_model=AccountCreditsResponse)
def get_account_credits(
    user: AuthUser = Depends(require_current_user),
    billing: BillingService = Depends(get_billing_service),
) -> AccountCreditsResponse:
    account = billing.repository.get_or_create_account(user.id, billing.settings.initial_credit_balance)
    return AccountCreditsResponse(account=account, quotas=billing.quotas_for_user(user.id), costs=billing.costs())


@router.get("/transactions", response_model=CreditTransactionListResponse)
def list_account_transactions(
    project_id: str | None = None,
    limit: int = Query(default=50, ge=1, le=100),
    user: AuthUser = Depends(require_current_user),
    billing: BillingService = Depends(get_billing_service),
) -> CreditTransactionListResponse:
    billing.repository.get_or_create_account(user.id, billing.settings.initial_credit_balance)
    return CreditTransactionListResponse(transactions=billing.repository.list_transactions(user.id, limit=limit, project_id=project_id))
```

Modify `src/main.py` to import and include the router:

```python
from src.api.account_routes import router as account_router
```

and inside `create_app` with the other routers:

```python
    app.include_router(account_router)
```

- [ ] **Step 7: Run account API tests to verify GREEN**

Run:

```bash
.venv/bin/python -m pytest tests/test_billing.py::test_account_credits_returns_balance_costs_and_quota tests/test_billing.py::test_account_transactions_are_owner_scoped tests/test_billing.py::test_billing_service_enforces_daily_quota -q
```

Expected: `3 passed`.

- [ ] **Step 8: Commit checkpoint if executing in a git repo**

```bash
git add src/config.py src/dependencies.py src/main.py src/api/account_routes.py src/services/billing_service.py tests/test_billing.py
git commit -m "feat: expose account credit controls"
```

Skip this checkpoint in `/Users/apple/Documents/tup` unless it becomes a git repository.

## Task 3: Project Generation Credit Enforcement and Refunds

**Files:**
- Modify: `src/api/generation_routes.py:52-108,222-360`
- Modify: `src/services/project_repository.py:44-78,190-201`
- Modify: `src/models/project.py:75-85`
- Test: `tests/test_billing.py`

- [ ] **Step 1: Add failing project generation credit tests**

Append to `tests/test_billing.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify RED**

Run:

```bash
.venv/bin/python -m pytest tests/test_billing.py::test_project_image_generation_blocks_when_credits_are_insufficient tests/test_billing.py::test_project_video_generation_charges_and_links_task tests/test_billing.py::test_project_video_failure_refunds_charged_credits -q
```

Expected: first test returns `202` instead of `402`, and later tests find no transactions.

- [ ] **Step 3: Extend task responses with charge fields**

Modify `src/models/project.py` `ProjectTaskResponse`:

```python
class ProjectTaskResponse(BaseModel):
    task_id: str
    project_id: str
    kind: TaskKind
    status: TaskStatus
    input: dict[str, Any]
    result: dict[str, Any] | None = None
    error: str | None = None
    cost_estimate: int = 0
    charged_credits: int = 0
    created_at: datetime
    updated_at: datetime
```

Modify `src/services/project_repository.py` `create_task` signature:

```python
    def create_task(self, owner_id: str, project_id: str, kind: TaskKind, input_payload: dict[str, Any], cost_estimate: int = 0, charged_credits: int = 0) -> ProjectTaskResponse:
```

Change its insert SQL to include `cost_estimate` and `charged_credits`:

```python
                INSERT INTO generation_tasks (id, owner_id, project_id, kind, status, input_json, result_json, history_json, error, cost_estimate, charged_credits, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, NULL, NULL, NULL, ?, ?, ?, ?)
```

and values:

```python
(task_id, owner_id, project_id, kind, TaskStatus.pending, _json(input_payload), cost_estimate, charged_credits, now, now)
```

Update `get_task` and `list_tasks` SELECT lists to include:

```sql
cost_estimate, charged_credits
```

Update `_task_response`:

```python
        cost_estimate=row["cost_estimate"],
        charged_credits=row["charged_credits"],
```

- [ ] **Step 4: Add billing to project generation routes**

Modify `src/api/generation_routes.py` imports:

```python
from src.dependencies import get_billing_service, get_pipeline, get_project_repository, get_prompt_skill_pipeline, get_video_router, require_current_user
from src.services.billing_service import BillingService
```

Add this helper near the route functions:

```python
def _billing_error(exc: ValueError) -> HTTPException:
    detail = str(exc)
    status_code = status.HTTP_429_TOO_MANY_REQUESTS if detail == "Daily quota exceeded" else status.HTTP_402_PAYMENT_REQUIRED
    return HTTPException(status_code=status_code, detail=detail)
```

For `generate_project_image`, add dependency:

```python
    billing: BillingService = Depends(get_billing_service),
```

Then replace task creation with:

```python
    try:
        charge = await asyncio.to_thread(billing.charge_for_action, user.id, project_id, "project_image", {"workflow": "project_image_generation"})
    except ValueError as exc:
        raise _billing_error(exc) from exc
    try:
        task = await asyncio.to_thread(repository.create_task, user.id, project_id, TaskKind.image, {**request.model_dump(mode="json"), "credit_transaction_id": charge.id}, charge.amount, charge.amount)
        await asyncio.to_thread(billing.attach_task, user.id, charge.id, task.task_id)
    except Exception:
        await asyncio.to_thread(billing.refund_failed_task, user.id, charge.id, "", "task creation failed")
        raise
    background_tasks.add_task(_run_image_task, user.id, task.task_id, charge.id, request, repository, pipeline, settings, billing)
```

Update `_run_image_task` signature:

```python
async def _run_image_task(
    owner_id: str,
    task_id: str,
    credit_transaction_id: str | None,
    request: GenerateRequest,
    repository: ProjectRepository,
    pipeline: ImageGenerationPipeline,
    settings: Settings,
    billing: BillingService | None = None,
) -> None:
```

Inside its `except Exception:` block, before `return`, add:

```python
        if billing is not None:
            await asyncio.to_thread(billing.refund_failed_task, owner_id, credit_transaction_id, task_id, "failed task")
```

Apply the same pattern to:

```python
"project_image_edit" -> generate_project_image_edit -> _run_image_edit_task
"project_video" -> generate_project_video -> _run_video_task
```

For `_run_video_task`, add `credit_transaction_id` and `billing` parameters and refund inside its exception block.

- [ ] **Step 5: Run project billing tests to verify GREEN**

Run:

```bash
.venv/bin/python -m pytest tests/test_billing.py::test_project_image_generation_blocks_when_credits_are_insufficient tests/test_billing.py::test_project_video_generation_charges_and_links_task tests/test_billing.py::test_project_video_failure_refunds_charged_credits -q
```

Expected: `3 passed`.

- [ ] **Step 6: Commit checkpoint if executing in a git repo**

```bash
git add src/api/generation_routes.py src/models/project.py src/services/project_repository.py tests/test_billing.py
git commit -m "feat: enforce credits on project generation"
```

Skip this checkpoint in `/Users/apple/Documents/tup` unless it becomes a git repository.

## Task 4: Canvas Generation Credit Enforcement

**Files:**
- Modify: `src/api/canvas_routes.py:406-654,860-910`
- Test: `tests/test_canvas_routes.py`

- [ ] **Step 1: Add failing canvas credit tests**

Append to `tests/test_canvas_routes.py`:

```python
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
        connection.execute("INSERT INTO credit_accounts (user_id, balance, lifetime_granted, lifetime_spent, updated_at) VALUES (?, 5, 5, 0, '2026-05-21T00:00:00+00:00')", (user_id,))

    response = client.post(
        f"/api/canvases/{canvas_id}/image-batches",
        json={"selected_node_ids": [source["id"]], "root_node_id": source["id"], "model": "openai", "threshold": 0, "max_iter": 1, "skip_prompt_evaluation": True},
    )

    assert response.status_code == 402
    assert response.json()["detail"] == "Insufficient credits"


def test_canvas_video_generation_charges_canvas_video_action(tmp_path):
    client = _client(tmp_path)
    _register(client, "ada")
    project_id = _project(client)
    canvas_id = _canvas(client, project_id)
    owner_id = _owner_id(tmp_path)
    projects = ProjectRepository(SQLiteDatabase(tmp_path / "app.db"))
    asset = projects.create_asset(owner_id, project_id, AssetKind.image, "mock://source.png", "image/png", {"source": "test"})
    source = client.post(
        f"/api/canvases/{canvas_id}/nodes",
        json={"type": "asset", "title": "Source", "position": {"x": 0, "y": 0}, "payload": {"asset_id": asset.id, "role": "reference"}},
    ).json()

    response = client.post(
        f"/api/canvases/{canvas_id}/generate/video",
        json={"prompt": "slow dolly in", "source_image_asset_id": asset.id, "selected_node_ids": [source["id"]], "duration": 5},
    )

    assert response.status_code == 202
    transactions = BillingRepository(SQLiteDatabase(tmp_path / "app.db")).list_transactions(owner_id, limit=10)
    assert transactions[0].action_type == "canvas_video"
    assert transactions[0].task_id == response.json()["task_id"]
```

- [ ] **Step 2: Run tests to verify RED**

Run:

```bash
.venv/bin/python -m pytest tests/test_canvas_routes.py::test_canvas_image_batch_blocks_when_credits_are_insufficient tests/test_canvas_routes.py::test_canvas_video_generation_charges_canvas_video_action -q
```

Expected: first test returns `202` instead of `402`, second test finds no credit transaction.

- [ ] **Step 3: Add billing dependencies to canvas generation routes**

Modify `src/api/canvas_routes.py` imports:

```python
from src.dependencies import get_billing_service, get_canvas_repository, get_pipeline, get_project_repository, get_prompt_skill_pipeline, get_video_router, require_current_user
from src.services.billing_service import BillingService
```

Use the same `_billing_error` helper from `generation_routes.py`, or define this local helper:

```python
def _billing_error(exc: ValueError) -> HTTPException:
    detail = str(exc)
    status_code = status.HTTP_429_TOO_MANY_REQUESTS if detail == "Daily quota exceeded" else status.HTTP_402_PAYMENT_REQUIRED
    return HTTPException(status_code=status_code, detail=detail)
```

For each task-creating canvas route, add:

```python
    billing: BillingService = Depends(get_billing_service),
```

Charge action mapping:

```python
/api/canvases/{canvas_id}/generate/image      -> "canvas_image"
/api/canvases/{canvas_id}/generate/image-edit -> "canvas_image_edit"
/api/canvases/{canvas_id}/image-batches       -> "canvas_image_batch"
/api/canvases/{canvas_id}/generate/video      -> "canvas_video"
```

Before `project_repository.create_task`, add:

```python
    try:
        charge = await asyncio.to_thread(billing.charge_for_action, user.id, canvas.project_id, "canvas_video", {"workflow": "canvas_video_generation", "canvas_id": canvas_id})
    except ValueError as exc:
        raise _billing_error(exc) from exc
```

When creating task input, include:

```python
"credit_transaction_id": charge.id,
"estimated_credit_cost": charge.amount,
```

Call `create_task` with cost fields:

```python
    task = await asyncio.to_thread(project_repository.create_task, user.id, canvas.project_id, TaskKind.image_to_video, task_input, charge.amount, charge.amount)
    await asyncio.to_thread(billing.attach_task, user.id, charge.id, task.task_id)
```

Update background task calls to pass `charge.id` and `billing`.

For `_run_canvas_video_task`, change signature:

```python
async def _run_canvas_video_task(
    owner_id: str,
    task_id: str,
    credit_transaction_id: str | None,
    project_id: str,
    canvas_id: str,
    source_node_ids: list[str],
    source_asset_id: str,
    prompt_artifact_id: str | None,
    request: VideoGenerateRequest,
    canvas_repository: CanvasRepository,
    project_repository: ProjectRepository,
    video_router: VideoRouter,
    billing: BillingService | None = None,
) -> None:
```

Inside the exception block:

```python
        if billing is not None:
            await asyncio.to_thread(billing.refund_failed_task, owner_id, credit_transaction_id, task_id, "failed task")
```

Apply the equivalent signature and exception changes to canvas image, image edit, and image batch background functions in the same file.

- [ ] **Step 4: Run canvas billing tests to verify GREEN**

Run:

```bash
.venv/bin/python -m pytest tests/test_canvas_routes.py::test_canvas_image_batch_blocks_when_credits_are_insufficient tests/test_canvas_routes.py::test_canvas_video_generation_charges_canvas_video_action -q
```

Expected: `2 passed`.

- [ ] **Step 5: Commit checkpoint if executing in a git repo**

```bash
git add src/api/canvas_routes.py tests/test_canvas_routes.py
git commit -m "feat: enforce credits on canvas generation"
```

Skip this checkpoint in `/Users/apple/Documents/tup` unless it becomes a git repository.

## Task 5: Asset Review State and Admin Review API

**Files:**
- Modify: `src/models/project.py:61-69`
- Modify: `src/services/project_repository.py:115-159,204-213`
- Modify: `src/models/admin.py`
- Modify: `src/api/admin_routes.py`
- Create: `src/services/admin_repository.py`
- Modify: `src/dependencies.py`
- Test: `tests/test_admin_operations.py`

- [ ] **Step 1: Add failing admin review tests**

Create `tests/test_admin_operations.py`:

```python
import sqlite3

from fastapi.testclient import TestClient

import src.dependencies as dependencies
from src.api import image_routes as routes
from src.config import Settings
from src.main import create_app
from src.models.project import AssetKind
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
    return TestClient(create_app(settings)), settings


def _register(client: TestClient, username: str) -> str:
    response = client.post(
        "/api/auth/register",
        json={"username": username, "email": f"{username}@example.com", "password": "correct horse battery staple"},
    )
    assert response.status_code == 201
    return response.json()["user"]["id"]


def _promote(settings: Settings, username: str) -> None:
    with sqlite3.connect(settings.database_path) as connection:
        connection.execute("UPDATE users SET role = 'admin' WHERE username = ?", (username,))


def test_uploaded_or_repository_created_assets_default_to_pending_review(tmp_path):
    client, settings = _client(tmp_path)
    user_id = _register(client, "ada")
    project_id = client.post("/api/projects", json={"name": "Review project"}).json()["id"]
    repository = ProjectRepository(SQLiteDatabase(settings.database_path))

    asset = repository.create_asset(user_id, project_id, AssetKind.image, "mock://image.png", "image/png", {"source": "test"})
    response = client.get(f"/api/projects/{project_id}/assets")

    assert asset.review_status == "pending"
    assert response.json()["assets"][0]["review_status"] == "pending"


def test_admin_review_queue_requires_admin_and_can_approve_asset(tmp_path):
    user_client, settings = _client(tmp_path)
    admin_client, _ = _client(tmp_path)
    user_id = _register(user_client, "ada")
    _register(admin_client, "admin")
    _promote(settings, "admin")
    project_id = user_client.post("/api/projects", json={"name": "Review project"}).json()["id"]
    asset = ProjectRepository(SQLiteDatabase(settings.database_path)).create_asset(user_id, project_id, AssetKind.image, "mock://image.png", "image/png", {"source": "test"})

    forbidden = user_client.get("/api/admin/assets/review-queue")
    queue = admin_client.get("/api/admin/assets/review-queue")
    update = admin_client.post(f"/api/admin/assets/{asset.id}/review", json={"review_status": "approved", "review_notes": "safe product image"})
    updated_queue = admin_client.get("/api/admin/assets/review-queue?review_status=approved")

    assert forbidden.status_code == 403
    assert queue.status_code == 200
    assert queue.json()["assets"][0]["id"] == asset.id
    assert update.status_code == 200
    assert update.json()["review_status"] == "approved"
    assert updated_queue.json()["assets"][0]["review_notes"] == "safe product image"
```

- [ ] **Step 2: Run tests to verify RED**

Run:

```bash
.venv/bin/python -m pytest tests/test_admin_operations.py::test_uploaded_or_repository_created_assets_default_to_pending_review tests/test_admin_operations.py::test_admin_review_queue_requires_admin_and_can_approve_asset -q
```

Expected: fail because `AssetResponse` has no `review_status`, and admin review endpoints return 404.

- [ ] **Step 3: Extend asset response and repository**

Modify `src/models/project.py` `AssetResponse`:

```python
class AssetResponse(BaseModel):
    id: str
    project_id: str
    kind: AssetKind
    url: str
    media_type: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    review_status: str = "pending"
    review_notes: str = ""
    reviewed_by: str | None = None
    reviewed_at: datetime | None = None
    created_at: datetime
```

Modify `ProjectRepository.create_asset` insert SQL to include review columns:

```python
                INSERT INTO assets (id, owner_id, project_id, kind, url, media_type, metadata_json, review_status, review_notes, reviewed_by, reviewed_at, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', '', NULL, NULL, ?)
```

Modify `AssetResponse(...)` creation:

```python
        return AssetResponse(id=asset_id, project_id=project_id, kind=kind, url=url, media_type=media_type, metadata=metadata or {}, review_status="pending", review_notes="", reviewed_by=None, reviewed_at=None, created_at=_dt(now))
```

Update `list_assets` and `get_asset` SELECT fields:

```sql
SELECT id, project_id, kind, url, media_type, metadata_json, review_status, review_notes, reviewed_by, reviewed_at, created_at
```

Update `_asset_response`:

```python
        review_status=row["review_status"],
        review_notes=row["review_notes"],
        reviewed_by=row["reviewed_by"],
        reviewed_at=_dt(row["reviewed_at"]) if row["reviewed_at"] else None,
```

- [ ] **Step 4: Add admin models**

Modify `src/models/admin.py`:

```python
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


class AdminUserSummary(BaseModel):
    id: str
    username: str
    email: str
    role: str
    credit_balance: int
    created_at: datetime


class AdminUserListResponse(BaseModel):
    users: list[AdminUserSummary]


class AdminTaskSummary(BaseModel):
    task_id: str
    owner_id: str
    project_id: str
    kind: str
    status: str
    error: str | None = None
    cost_estimate: int = 0
    charged_credits: int = 0
    created_at: datetime
    updated_at: datetime


class AdminTaskListResponse(BaseModel):
    tasks: list[AdminTaskSummary]


class AdminAssetSummary(BaseModel):
    id: str
    owner_id: str
    project_id: str
    kind: str
    url: str
    media_type: str
    review_status: str
    review_notes: str = ""
    reviewed_by: str | None = None
    reviewed_at: datetime | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class AdminAssetListResponse(BaseModel):
    assets: list[AdminAssetSummary]


class AdminAssetReviewUpdate(BaseModel):
    review_status: Literal["pending", "approved", "rejected"]
    review_notes: str = Field(default="", max_length=1000)

    @field_validator("review_notes")
    @classmethod
    def strip_notes(cls, value: str) -> str:
        return value.strip()
```

Keep existing `ModelSettingsUpdate` and `ModelSettingsResponse` in the same file.

- [ ] **Step 5: Add admin repository**

Create `src/services/admin_repository.py`:

```python
import json
from datetime import datetime, timezone
from typing import Any

from src.models.admin import AdminAssetSummary, AdminTaskSummary, AdminUserSummary
from src.services.database import SQLiteDatabase


class AdminRepository:
    def __init__(self, database: SQLiteDatabase):
        self.database = database

    def list_users(self, limit: int = 100) -> list[AdminUserSummary]:
        with self.database.connect() as connection:
            rows = connection.execute(
                """
                SELECT users.id, users.username, users.email, users.role, users.created_at, COALESCE(credit_accounts.balance, 0) AS credit_balance
                FROM users
                LEFT JOIN credit_accounts ON credit_accounts.user_id = users.id
                ORDER BY users.created_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [AdminUserSummary(id=row["id"], username=row["username"], email=row["email"], role=row["role"], credit_balance=row["credit_balance"], created_at=_dt(row["created_at"])) for row in rows]

    def list_tasks(self, status: str | None = None, kind: str | None = None, limit: int = 100) -> list[AdminTaskSummary]:
        query = """
            SELECT id, owner_id, project_id, kind, status, error, cost_estimate, charged_credits, created_at, updated_at
            FROM generation_tasks
            WHERE 1 = 1
        """
        values: tuple[Any, ...] = ()
        if status is not None:
            query = f"{query} AND status = ?"
            values = (*values, status)
        if kind is not None:
            query = f"{query} AND kind = ?"
            values = (*values, kind)
        query = f"{query} ORDER BY updated_at DESC LIMIT ?"
        values = (*values, limit)
        with self.database.connect() as connection:
            rows = connection.execute(query, values).fetchall()
        return [
            AdminTaskSummary(
                task_id=row["id"],
                owner_id=row["owner_id"],
                project_id=row["project_id"],
                kind=row["kind"],
                status=row["status"],
                error=row["error"],
                cost_estimate=row["cost_estimate"],
                charged_credits=row["charged_credits"],
                created_at=_dt(row["created_at"]),
                updated_at=_dt(row["updated_at"]),
            )
            for row in rows
        ]

    def list_review_assets(self, review_status: str | None = None, limit: int = 100) -> list[AdminAssetSummary]:
        query = """
            SELECT id, owner_id, project_id, kind, url, media_type, metadata_json, review_status, review_notes, reviewed_by, reviewed_at, created_at
            FROM assets
            WHERE 1 = 1
        """
        values: tuple[Any, ...] = ()
        if review_status is not None:
            query = f"{query} AND review_status = ?"
            values = (*values, review_status)
        query = f"{query} ORDER BY created_at DESC LIMIT ?"
        values = (*values, limit)
        with self.database.connect() as connection:
            rows = connection.execute(query, values).fetchall()
        return [_asset_summary(row) for row in rows]

    def update_asset_review(self, asset_id: str, review_status: str, review_notes: str, reviewed_by: str) -> AdminAssetSummary | None:
        now = _utc_now()
        with self.database.connect() as connection:
            connection.execute(
                """
                UPDATE assets
                SET review_status = ?, review_notes = ?, reviewed_by = ?, reviewed_at = ?
                WHERE id = ?
                """,
                (review_status, review_notes, reviewed_by, now, asset_id),
            )
            row = connection.execute(
                """
                SELECT id, owner_id, project_id, kind, url, media_type, metadata_json, review_status, review_notes, reviewed_by, reviewed_at, created_at
                FROM assets
                WHERE id = ?
                """,
                (asset_id,),
            ).fetchone()
        return _asset_summary(row) if row else None


def _asset_summary(row) -> AdminAssetSummary:
    return AdminAssetSummary(
        id=row["id"],
        owner_id=row["owner_id"],
        project_id=row["project_id"],
        kind=row["kind"],
        url=row["url"],
        media_type=row["media_type"],
        metadata=json.loads(row["metadata_json"]),
        review_status=row["review_status"],
        review_notes=row["review_notes"],
        reviewed_by=row["reviewed_by"],
        reviewed_at=_dt(row["reviewed_at"]) if row["reviewed_at"] else None,
        created_at=_dt(row["created_at"]),
    )


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _dt(value: str) -> datetime:
    return datetime.fromisoformat(value)
```

- [ ] **Step 6: Add admin dependency and routes**

Modify `src/dependencies.py` if not already done:

```python
from src.services.admin_repository import AdminRepository


def get_admin_repository(database: SQLiteDatabase = Depends(get_database)) -> AdminRepository:
    return AdminRepository(database)
```

Modify `src/api/admin_routes.py` imports:

```python
from fastapi import APIRouter, Depends, HTTPException, Query
from src.dependencies import get_admin_repository, get_database, require_admin_user
from src.models.admin import AdminAssetListResponse, AdminAssetReviewUpdate, AdminAssetSummary, AdminTaskListResponse, AdminUserListResponse, ModelSettingsResponse, ModelSettingsUpdate
from src.services.admin_repository import AdminRepository
```

Add routes:

```python
@router.get("/users", response_model=AdminUserListResponse)
def list_admin_users(
    limit: int = Query(default=100, ge=1, le=200),
    user: AuthUser = Depends(require_admin_user),
    repository: AdminRepository = Depends(get_admin_repository),
) -> AdminUserListResponse:
    return AdminUserListResponse(users=repository.list_users(limit=limit))


@router.get("/tasks", response_model=AdminTaskListResponse)
def list_admin_tasks(
    status: str | None = None,
    kind: str | None = None,
    limit: int = Query(default=100, ge=1, le=200),
    user: AuthUser = Depends(require_admin_user),
    repository: AdminRepository = Depends(get_admin_repository),
) -> AdminTaskListResponse:
    return AdminTaskListResponse(tasks=repository.list_tasks(status=status, kind=kind, limit=limit))


@router.get("/assets/review-queue", response_model=AdminAssetListResponse)
def list_admin_review_assets(
    review_status: str | None = None,
    limit: int = Query(default=100, ge=1, le=200),
    user: AuthUser = Depends(require_admin_user),
    repository: AdminRepository = Depends(get_admin_repository),
) -> AdminAssetListResponse:
    return AdminAssetListResponse(assets=repository.list_review_assets(review_status=review_status, limit=limit))


@router.post("/assets/{asset_id}/review", response_model=AdminAssetSummary)
def update_admin_asset_review(
    asset_id: str,
    request: AdminAssetReviewUpdate,
    user: AuthUser = Depends(require_admin_user),
    repository: AdminRepository = Depends(get_admin_repository),
) -> AdminAssetSummary:
    asset = repository.update_asset_review(asset_id, request.review_status, request.review_notes, user.id)
    if asset is None:
        raise HTTPException(status_code=404, detail="Asset not found")
    return asset
```

- [ ] **Step 7: Run admin review tests to verify GREEN**

Run:

```bash
.venv/bin/python -m pytest tests/test_admin_operations.py::test_uploaded_or_repository_created_assets_default_to_pending_review tests/test_admin_operations.py::test_admin_review_queue_requires_admin_and_can_approve_asset -q
```

Expected: `2 passed`.

- [ ] **Step 8: Commit checkpoint if executing in a git repo**

```bash
git add src/models/project.py src/services/project_repository.py src/models/admin.py src/services/admin_repository.py src/api/admin_routes.py src/dependencies.py tests/test_admin_operations.py
git commit -m "feat: add asset review admin controls"
```

Skip this checkpoint in `/Users/apple/Documents/tup` unless it becomes a git repository.

## Task 6: Admin Visibility for Users and Tasks

**Files:**
- Modify: `tests/test_admin_operations.py`
- Modify: `src/services/admin_repository.py`
- Modify: `src/api/admin_routes.py`

- [ ] **Step 1: Add failing admin visibility tests**

Append to `tests/test_admin_operations.py`:

```python
def test_admin_users_include_credit_balance(tmp_path):
    admin_client, settings = _client(tmp_path)
    user_client, _ = _client(tmp_path)
    _register(admin_client, "admin")
    _promote(settings, "admin")
    user_id = _register(user_client, "ada")
    from src.services.billing_repository import BillingRepository

    BillingRepository(SQLiteDatabase(settings.database_path)).get_or_create_account(user_id, 300)

    response = admin_client.get("/api/admin/users")

    assert response.status_code == 200
    users = {item["username"]: item for item in response.json()["users"]}
    assert users["ada"]["credit_balance"] == 300
    assert users["admin"]["role"] == "admin"


def test_admin_tasks_include_failed_errors_and_charge_fields(tmp_path):
    admin_client, settings = _client(tmp_path)
    user_client, _ = _client(tmp_path)
    _register(admin_client, "admin")
    _promote(settings, "admin")
    user_id = _register(user_client, "ada")
    project_id = user_client.post("/api/projects", json={"name": "Ops project"}).json()["id"]
    repository = ProjectRepository(SQLiteDatabase(settings.database_path))
    task = repository.create_task(user_id, project_id, AssetKind.image.value, {"prompt": "test"}, cost_estimate=10, charged_credits=10)
    repository.set_task_failed(task.task_id, "provider timeout")

    response = admin_client.get("/api/admin/tasks?status=failed")

    assert response.status_code == 200
    tasks = response.json()["tasks"]
    assert tasks[0]["task_id"] == task.task_id
    assert tasks[0]["error"] == "provider timeout"
    assert tasks[0]["charged_credits"] == 10
```

If `AssetKind.image.value` is awkward for task creation, use `TaskKind.image` by importing it from `src.models.project`.

- [ ] **Step 2: Run tests to verify RED or identify integration gaps**

Run:

```bash
.venv/bin/python -m pytest tests/test_admin_operations.py::test_admin_users_include_credit_balance tests/test_admin_operations.py::test_admin_tasks_include_failed_errors_and_charge_fields -q
```

Expected before Task 5 implementation: 404. After Task 5 implementation, use this run to catch query/model gaps.

- [ ] **Step 3: Fix query/model gaps only**

If `test_admin_tasks_include_failed_errors_and_charge_fields` fails because `ProjectRepository.create_task` was called with a string instead of `TaskKind`, adjust test imports:

```python
from src.models.project import AssetKind, TaskKind
```

and test task creation:

```python
task = repository.create_task(user_id, project_id, TaskKind.image, {"prompt": "test"}, cost_estimate=10, charged_credits=10)
```

If the admin task response is missing `cost_estimate` or `charged_credits`, ensure `AdminTaskSummary` and `AdminRepository.list_tasks()` include both fields exactly as described in Task 5.

- [ ] **Step 4: Run admin visibility tests to verify GREEN**

Run:

```bash
.venv/bin/python -m pytest tests/test_admin_operations.py::test_admin_users_include_credit_balance tests/test_admin_operations.py::test_admin_tasks_include_failed_errors_and_charge_fields -q
```

Expected: `2 passed`.

- [ ] **Step 5: Commit checkpoint if executing in a git repo**

```bash
git add tests/test_admin_operations.py src/services/admin_repository.py src/api/admin_routes.py src/models/admin.py
git commit -m "feat: add admin operations visibility"
```

Skip this checkpoint in `/Users/apple/Documents/tup` unless it becomes a git repository.

## Task 7: Frontend Account Credits and Review State

**Files:**
- Create: `frontend/src/api/account.js`
- Create: `frontend/src/account/AccountCreditsPanel.jsx`
- Modify: `frontend/src/workspace/ProjectWorkspace.jsx`
- Modify: `frontend/src/workspace/AssetGallery.jsx`
- Modify: `frontend/src/api/projects.js` only if field mapping is centralized there.

- [ ] **Step 1: Add account API client**

Create `frontend/src/api/account.js`:

```javascript
import { getJson } from "./client";

export function fetchAccountCredits() {
  return getJson("/api/account/credits");
}

export function fetchAccountTransactions(params = {}) {
  const search = new URLSearchParams();
  if (params.projectId) {
    search.set("project_id", params.projectId);
  }
  if (params.limit) {
    search.set("limit", String(params.limit));
  }
  const suffix = search.toString() ? `?${search.toString()}` : "";
  return getJson(`/api/account/transactions${suffix}`);
}
```

- [ ] **Step 2: Add credit panel component**

Create `frontend/src/account/AccountCreditsPanel.jsx`:

```jsx
import { Coins } from "lucide-react";

const ACTION_LABELS = {
  project_image: "项目出图",
  project_image_edit: "项目修图",
  project_video: "项目视频",
  canvas_image: "画布出图",
  canvas_image_edit: "画布修图",
  canvas_image_batch: "画布批量图",
  canvas_video: "画布视频",
};

export function AccountCreditsPanel({ credits }) {
  const account = credits?.account;
  const costs = Array.isArray(credits?.costs) ? credits.costs : [];
  const quotas = new Map((credits?.quotas || []).map((quota) => [quota.action_type, quota]));
  return (
    <section className="account-credits-panel" aria-label="账户积分">
      <div className="account-credit-balance"><Coins size={16} /><span>积分</span><strong>{account?.balance ?? "--"}</strong></div>
      <div className="account-credit-costs">
        {costs.filter((item) => item.action_type.startsWith("canvas_")).map((item) => {
          const quota = quotas.get(item.action_type);
          return (
            <span key={item.action_type}>
              {ACTION_LABELS[item.action_type] || item.action_type}: {item.cost} 点{quota ? ` · ${quota.used_count}/${quota.limit_count}` : ""}
            </span>
          );
        })}
      </div>
    </section>
  );
}
```

- [ ] **Step 3: Load credits in project workspace**

Modify `frontend/src/workspace/ProjectWorkspace.jsx` imports:

```javascript
import { fetchAccountCredits } from "../api/account";
import { AccountCreditsPanel } from "../account/AccountCreditsPanel";
```

Add state:

```javascript
const [credits, setCredits] = useState(null);
```

Modify `refreshProjectData()` to fetch credits:

```javascript
const [assetResult, taskResult, creditResult] = await Promise.allSettled([fetchProjectAssets(project.id), fetchProjectTasks(project.id), fetchAccountCredits()]);
```

After task handling:

```javascript
if (creditResult.status === "fulfilled") {
  setCredits(creditResult.value);
}
```

Render inside `.workspace-topbar-meta` before the asset/task counts:

```jsx
<AccountCreditsPanel credits={credits} />
```

- [ ] **Step 4: Show review state in asset gallery**

Modify `frontend/src/workspace/AssetGallery.jsx` to render `asset.review_status` on each asset card. Use existing card markup and add this small helper if there is no status mapping:

```jsx
function ReviewBadge({ status }) {
  const label = status === "approved" ? "已通过" : status === "rejected" ? "已拒绝" : "待审核";
  return <span className={`review-badge ${status || "pending"}`}>{label}</span>;
}
```

Place it next to the asset kind/media type metadata:

```jsx
<ReviewBadge status={asset.review_status || "pending"} />
```

For task cards, show charged credits if present:

```jsx
{task.charged_credits ? <span>{task.charged_credits} credits</span> : null}
```

- [ ] **Step 5: Run frontend build to verify GREEN**

Run:

```bash
npm run build
```

Expected: Vite build succeeds.

- [ ] **Step 6: Commit checkpoint if executing in a git repo**

```bash
git add frontend/src/api/account.js frontend/src/account/AccountCreditsPanel.jsx frontend/src/workspace/ProjectWorkspace.jsx frontend/src/workspace/AssetGallery.jsx
git commit -m "feat: show account credits in workspace"
```

Skip this checkpoint in `/Users/apple/Documents/tup` unless it becomes a git repository.

## Task 8: Frontend Admin Operations Page

**Files:**
- Modify: `frontend/src/api/admin.js`
- Create: `frontend/src/admin/AdminOperationsPage.jsx`
- Modify: `frontend/src/admin/AdminModelSettingsPage.jsx`
- Modify: `frontend/src/App.jsx`

- [ ] **Step 1: Extend admin API client**

Modify `frontend/src/api/admin.js`:

```javascript
import { getJson, postJson } from "./client";

export function fetchModelSettings() {
  return getJson("/api/admin/model-settings");
}

export function updateModelSettings(payload) {
  return postJson("/api/admin/model-settings", payload);
}

export function fetchAdminUsers() {
  return getJson("/api/admin/users");
}

export function fetchAdminTasks(params = {}) {
  const search = new URLSearchParams();
  if (params.status) {
    search.set("status", params.status);
  }
  if (params.kind) {
    search.set("kind", params.kind);
  }
  const suffix = search.toString() ? `?${search.toString()}` : "";
  return getJson(`/api/admin/tasks${suffix}`);
}

export function fetchReviewQueue(params = {}) {
  const search = new URLSearchParams();
  if (params.reviewStatus) {
    search.set("review_status", params.reviewStatus);
  }
  const suffix = search.toString() ? `?${search.toString()}` : "";
  return getJson(`/api/admin/assets/review-queue${suffix}`);
}

export function updateAssetReview(assetId, payload) {
  return postJson(`/api/admin/assets/${assetId}/review`, payload);
}
```

- [ ] **Step 2: Create admin operations page**

Create `frontend/src/admin/AdminOperationsPage.jsx`:

```jsx
import { useEffect, useState } from "react";
import { ArrowLeft, RefreshCw } from "lucide-react";

import { fetchAdminTasks, fetchAdminUsers, fetchReviewQueue, updateAssetReview } from "../api/admin";
import { AdminModelSettingsPage } from "./AdminModelSettingsPage";

const TABS = ["models", "users", "tasks", "reviews"];

export function AdminOperationsPage({ onBack }) {
  const [tab, setTab] = useState("models");
  const [users, setUsers] = useState([]);
  const [tasks, setTasks] = useState([]);
  const [assets, setAssets] = useState([]);
  const [status, setStatus] = useState("");

  useEffect(() => {
    if (tab !== "models") {
      refresh();
    }
  }, [tab]);

  async function refresh() {
    setStatus("");
    try {
      if (tab === "users") {
        const payload = await fetchAdminUsers();
        setUsers(payload.users || []);
      }
      if (tab === "tasks") {
        const payload = await fetchAdminTasks();
        setTasks(payload.tasks || []);
      }
      if (tab === "reviews") {
        const payload = await fetchReviewQueue();
        setAssets(payload.assets || []);
      }
    } catch (error) {
      setStatus(error?.message || "管理员数据加载失败");
    }
  }

  async function reviewAsset(assetId, reviewStatus) {
    try {
      await updateAssetReview(assetId, { review_status: reviewStatus, review_notes: reviewStatus === "approved" ? "approved in admin" : "rejected in admin" });
      await refresh();
    } catch (error) {
      setStatus(error?.message || "审核状态更新失败");
    }
  }

  return (
    <main className="project-shell admin-settings-shell">
      <header className="project-topbar">
        <div><h1>管理员后台</h1><span>模型配置、用户积分、任务状态和素材审核</span></div>
        <div className="project-actions">
          <button className="secondary-image-action" type="button" onClick={onBack}><ArrowLeft size={17} />返回项目</button>
          {tab !== "models" ? <button className="secondary-image-action" type="button" onClick={refresh}><RefreshCw size={17} />刷新</button> : null}
        </div>
      </header>
      <nav className="workspace-tabs" role="tablist" aria-label="管理员后台">
        {TABS.map((item) => <button key={item} type="button" role="tab" aria-selected={tab === item} className={tab === item ? "active" : ""} onClick={() => setTab(item)}>{tabLabel(item)}</button>)}
      </nav>
      {status ? <div className="admin-status error" role="status">{status}</div> : null}
      {tab === "models" ? <AdminModelSettingsPage onBack={onBack} embedded /> : null}
      {tab === "users" ? <AdminUsersTable users={users} /> : null}
      {tab === "tasks" ? <AdminTasksTable tasks={tasks} /> : null}
      {tab === "reviews" ? <AdminReviewQueue assets={assets} onReview={reviewAsset} /> : null}
    </main>
  );
}

function tabLabel(tab) {
  return { models: "模型配置", users: "用户积分", tasks: "任务", reviews: "审核队列" }[tab];
}

function AdminUsersTable({ users }) {
  return <section className="admin-settings-grid">{users.map((user) => <article className="project-create-card admin-settings-card" key={user.id}><strong>{user.username}</strong><span>{user.role}</span><span>{user.credit_balance} credits</span></article>)}</section>;
}

function AdminTasksTable({ tasks }) {
  return <section className="admin-settings-grid">{tasks.map((task) => <article className="project-create-card admin-settings-card" key={task.task_id}><strong>{task.kind}</strong><span>{task.status}</span><span>{task.charged_credits} credits</span>{task.error ? <small>{task.error}</small> : null}</article>)}</section>;
}

function AdminReviewQueue({ assets, onReview }) {
  return <section className="admin-settings-grid">{assets.map((asset) => <article className="project-create-card admin-settings-card" key={asset.id}><strong>{asset.kind}</strong><span>{asset.review_status}</span><small>{asset.url}</small><div className="project-actions"><button className="primary-image-action compact" type="button" onClick={() => onReview(asset.id, "approved")}>通过</button><button className="secondary-image-action compact" type="button" onClick={() => onReview(asset.id, "rejected")}>拒绝</button></div></article>)}</section>;
}
```

- [ ] **Step 3: Make model settings page embeddable**

Modify `frontend/src/admin/AdminModelSettingsPage.jsx` signature:

```jsx
export function AdminModelSettingsPage({ onBack, embedded = false }) {
```

Change the root return wrapper so embedded mode does not render a second page shell header. Replace the current top-level return with:

```jsx
  const content = (
    <>
      {status ? <div className={`admin-status ${statusKind}`} role="status" aria-live="polite">{status}</div> : null}
      {loading ? <section className="auth-card">正在加载模型配置</section> : null}
      {!loading ? (
        <section className="admin-settings-grid">
          {FIELD_GROUPS.map((group) => (
            <article className="project-create-card admin-settings-card" key={group.title}>
              <div className="panel-heading"><div><strong>{group.title}</strong><span>数据库覆盖值优先，清除后回退环境变量或默认值</span></div></div>
              <div className="admin-field-grid">
                {group.fields.map((key) => renderField(key, settings[key], drafts[key], Boolean(cleared[key]), updateDraft, clearOverride))}
              </div>
            </article>
          ))}
        </section>
      ) : null}
    </>
  );
  if (embedded) {
    return <section>{content}<div className="project-actions"><button className="primary-image-action compact" type="button" onClick={saveSettings} disabled={loading || saving}>{saving ? <Loader2 className="spinning" size={17} /> : <Save size={17} />}保存配置</button></div></section>;
  }
  return (
    <main className="project-shell admin-settings-shell">
      <header className="project-topbar">
        <div>
          <h1>模型配置</h1>
          <span>管理员可在这里配置 OpenAI 兼容图片、评估、提示词和视频模型</span>
        </div>
        <div className="project-actions">
          <button className="secondary-image-action" type="button" onClick={onBack}><ArrowLeft size={17} />返回项目</button>
          <button className="primary-image-action compact" type="button" onClick={saveSettings} disabled={loading || saving}>
            {saving ? <Loader2 className="spinning" size={17} /> : <Save size={17} />}
            保存配置
          </button>
        </div>
      </header>
      {content}
    </main>
  );
```

Keep helper functions unchanged.

- [ ] **Step 4: Route app admin view to operations page**

Modify `frontend/src/App.jsx` imports:

```javascript
import { AdminOperationsPage } from "./admin/AdminOperationsPage";
```

Remove or stop using direct `AdminModelSettingsPage` import.

Change admin branch:

```jsx
  if (view === "admin" && user.role === "admin") {
    return <AdminOperationsPage onBack={() => setView("projects")} />;
  }
```

- [ ] **Step 5: Run frontend build to verify GREEN**

Run:

```bash
npm run build
```

Expected: Vite build succeeds.

- [ ] **Step 6: Commit checkpoint if executing in a git repo**

```bash
git add frontend/src/api/admin.js frontend/src/admin/AdminOperationsPage.jsx frontend/src/admin/AdminModelSettingsPage.jsx frontend/src/App.jsx
git commit -m "feat: add admin operations console"
```

Skip this checkpoint in `/Users/apple/Documents/tup` unless it becomes a git repository.

## Task 9: Verification Pass

**Files:**
- Verify all files changed in Tasks 1-8.

- [ ] **Step 1: Run focused billing tests**

Run:

```bash
.venv/bin/python -m pytest tests/test_billing.py -q
```

Expected: all tests in `tests/test_billing.py` pass.

- [ ] **Step 2: Run admin operation tests**

Run:

```bash
.venv/bin/python -m pytest tests/test_admin_operations.py tests/test_admin_model_settings.py -q
```

Expected: all admin tests pass, including existing model settings tests.

- [ ] **Step 3: Run canvas/project regression tests**

Run:

```bash
.venv/bin/python -m pytest tests/test_canvas_routes.py tests/test_canvas_generation_lineage.py tests/test_video_router.py -q
```

Expected: all tests pass.

- [ ] **Step 4: Run auth/API regression tests**

Run:

```bash
.venv/bin/python -m pytest tests/test_api.py tests/test_auth.py -q
```

Expected: all tests pass.

- [ ] **Step 5: Run full backend suite**

Run:

```bash
.venv/bin/python -m pytest -q
```

Expected: full suite passes.

- [ ] **Step 6: Run frontend build**

Run:

```bash
npm run build
```

Expected: Vite build succeeds.

- [ ] **Step 7: Run manual mock-media SaaS control flow**

Run app:

```bash
USE_MOCK_IMAGES=true USE_MOCK_VIDEOS=true AUTH_REQUIRED=false ALLOW_PUBLIC_REGISTRATION=true API_KEY='' SECURE_SESSION_COOKIES=false INITIAL_CREDIT_BALANCE=200 npm run dev
```

Manual checklist:

1. Register and sign in as a normal user.
2. Create a project.
3. Confirm the project workspace header shows credit balance.
4. Create or open a canvas.
5. Run canvas image generation and confirm credits decrease.
6. Run canvas video generation and confirm credits decrease more.
7. Open media assets and confirm review status shows `pending`.
8. Sign in as an admin user or bootstrap admin via env.
9. Open admin console.
10. Confirm users tab shows the normal user and credit balance.
11. Confirm tasks tab shows generated tasks and charged credits.
12. Confirm review queue shows pending assets.
13. Approve one asset and confirm it moves to approved status.

- [ ] **Step 8: Final code review**

Use code review agents:

```text
Run python-reviewer on Python changes.
Run security-reviewer on billing, quota, admin, review, and ownership changes.
Run code-reviewer on full Phase 1C diff.
```

Address CRITICAL/HIGH findings before completing the phase.

- [ ] **Step 9: Commit checkpoint if executing in a git repo**

```bash
git add src frontend tests
git commit -m "feat: add SaaS billing and review controls"
```

Skip this checkpoint in `/Users/apple/Documents/tup` unless it becomes a git repository.

## Self-Review Notes

- Spec coverage:
  - Credits/quotas: Tasks 1-4 and 7.
  - Credit transactions: Tasks 1-4.
  - Admin visibility: Tasks 5, 6, and 8.
  - Review status: Tasks 5, 7, and 8.
  - Public payment/subscription automation remains out of scope per Phase 1 design.
- Placeholder scan: no placeholder implementation steps are left; each code-changing step includes concrete code snippets and commands.
- Type consistency:
  - `CreditAction` action names match settings fields, service maps, tests, and frontend labels.
  - Review status values are consistently `pending`, `approved`, and `rejected`.
  - Credit amounts are integers across settings, DB schema, models, service, tests, and UI.
