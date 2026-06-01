import json
import sqlite3
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from src.models.billing import CreditAccountResponse, CreditAction, CreditTransactionResponse, QuotaUsageResponse
from src.models.task import TaskStatus
from src.services.database import SQLiteDatabase


class BillingRepository:
    def __init__(self, database: SQLiteDatabase):
        self.database = database

    def get_or_create_account(self, user_id: str, initial_balance: int) -> CreditAccountResponse:
        with self.database.connect() as connection:
            row = connection.execute(
                """
                SELECT user_id, balance, lifetime_granted, lifetime_spent, updated_at
                FROM credit_accounts
                WHERE user_id = ?
                """,
                (user_id,),
            ).fetchone()
            if row is None:
                now = _utc_now()
                connection.execute(
                    """
                    INSERT INTO credit_accounts (user_id, balance, lifetime_granted, lifetime_spent, updated_at)
                    VALUES (?, ?, ?, 0, ?)
                    """,
                    (user_id, initial_balance, initial_balance, now),
                )
                row = connection.execute(
                    """
                    SELECT user_id, balance, lifetime_granted, lifetime_spent, updated_at
                    FROM credit_accounts
                    WHERE user_id = ?
                    """,
                    (user_id,),
                ).fetchone()
        return _account_from_row(row)

    def debit(
        self,
        user_id: str,
        project_id: str | None,
        task_id: str | None,
        action_type: CreditAction,
        amount: int,
        metadata: dict[str, Any],
    ) -> CreditTransactionResponse:
        if amount <= 0:
            raise ValueError("Debit amount must be positive")
        transaction_id = str(uuid4())
        now = _utc_now()
        with self.database.connect() as connection:
            normalized_project_id = _owned_project_id(connection, user_id, project_id)
            normalized_task_id = _owned_task_id(connection, user_id, task_id)
            updated = connection.execute(
                """
                UPDATE credit_accounts
                SET balance = balance - ?, lifetime_spent = lifetime_spent + ?, updated_at = ?
                WHERE user_id = ? AND balance >= ?
                """,
                (amount, amount, now, user_id, amount),
            )
            if updated.rowcount == 0:
                if not _account_exists(connection, user_id):
                    raise ValueError("Credit account not found")
                raise ValueError("Insufficient credits")
            connection.execute(
                """
                INSERT INTO credit_transactions (
                    id, user_id, project_id, task_id, action_type, direction, amount, status, metadata_json, refund_of_transaction_id, created_at
                )
                VALUES (?, ?, ?, ?, ?, 'debit', ?, 'applied', ?, NULL, ?)
                """,
                (transaction_id, user_id, normalized_project_id, normalized_task_id, action_type, amount, _json(metadata), now),
            )
            row = connection.execute(
                """
                SELECT id, user_id, project_id, task_id, action_type, direction, amount, status, metadata_json, created_at
                FROM credit_transactions
                WHERE id = ?
                """,
                (transaction_id,),
            ).fetchone()
        return _transaction_from_row(row)

    def attach_task(self, user_id: str, transaction_id: str, task_id: str) -> None:
        with self.database.connect() as connection:
            normalized_task_id = _owned_task_id(connection, user_id, task_id)
            connection.execute(
                "UPDATE credit_transactions SET task_id = ? WHERE id = ? AND user_id = ?",
                (normalized_task_id, transaction_id, user_id),
            )

    def refund(self, user_id: str, original_transaction_id: str, task_id: str | None, reason: str) -> CreditTransactionResponse:
        with self.database.connect() as connection:
            normalized_task_id = _owned_task_id(connection, user_id, task_id)
        existing_refund = self.find_refund(user_id, original_transaction_id)
        if existing_refund is not None:
            return existing_refund

        with self.database.connect() as connection:
            original = connection.execute(
                """
                SELECT id, user_id, project_id, task_id, action_type, direction, amount, status, metadata_json, created_at
                FROM credit_transactions
                WHERE id = ? AND user_id = ?
                """,
                (original_transaction_id, user_id),
            ).fetchone()
            if original is None:
                raise ValueError("Original transaction not found")
            if original["direction"] != "debit":
                raise ValueError("Only debit transactions can be refunded")

            refund_id = str(uuid4())
            now = _utc_now()
            refund_metadata = {"reason": reason, "refund_of": original_transaction_id}
            refund_task_id = normalized_task_id or original["task_id"]
            try:
                connection.execute(
                    """
                    INSERT INTO credit_transactions (
                        id, user_id, project_id, task_id, action_type, direction, amount, status, metadata_json, refund_of_transaction_id, created_at
                    )
                    VALUES (?, ?, ?, ?, ?, 'credit', ?, 'applied', ?, ?, ?)
                    """,
                    (
                        refund_id,
                        user_id,
                        original["project_id"],
                        refund_task_id,
                        original["action_type"],
                        original["amount"],
                        _json(refund_metadata),
                        original_transaction_id,
                        now,
                    ),
                )
            except sqlite3.IntegrityError:
                existing_row = _refund_row_by_original_transaction(connection, user_id, original_transaction_id)
                if existing_row is None:
                    raise
                return _transaction_from_row(existing_row)
            connection.execute(
                "UPDATE credit_transactions SET status = 'refunded' WHERE id = ? AND user_id = ?",
                (original_transaction_id, user_id),
            )
            connection.execute(
                """
                UPDATE credit_accounts
                SET balance = balance + ?, updated_at = ?
                WHERE user_id = ?
                """,
                (original["amount"], now, user_id),
            )
            row = connection.execute(
                """
                SELECT id, user_id, project_id, task_id, action_type, direction, amount, status, metadata_json, created_at
                FROM credit_transactions
                WHERE id = ?
                """,
                (refund_id,),
            ).fetchone()
        return _transaction_from_row(row)

    def refund_recoverable_task(
        self,
        user_id: str,
        original_transaction_id: str,
        task_id: str,
        updated_before: datetime,
        error: str,
        reason: str,
    ) -> CreditTransactionResponse | None:
        now = _utc_now()
        with self.database.connect() as connection:
            normalized_task_id = _owned_task_id(connection, user_id, task_id)
            updated = connection.execute(
                """
                UPDATE generation_tasks
                SET status = ?, error = ?, updated_at = ?
                WHERE id = ? AND owner_id = ? AND status IN (?, ?) AND charged_credits > 0 AND updated_at < ?
                """,
                (
                    TaskStatus.failed,
                    error,
                    now,
                    normalized_task_id,
                    user_id,
                    TaskStatus.pending,
                    TaskStatus.running,
                    updated_before.isoformat(),
                ),
            )
            if updated.rowcount == 0:
                return None

            task = connection.execute(
                "SELECT project_id FROM generation_tasks WHERE id = ? AND owner_id = ?",
                (normalized_task_id, user_id),
            ).fetchone()
            if task is None:
                raise ValueError("Task not found")

            original = connection.execute(
                """
                SELECT id, user_id, project_id, task_id, action_type, direction, amount, status, metadata_json, created_at
                FROM credit_transactions
                WHERE id = ? AND user_id = ?
                """,
                (original_transaction_id, user_id),
            ).fetchone()
            if original is None:
                raise ValueError("Original transaction not found")
            if original["direction"] != "debit":
                raise ValueError("Only debit transactions can be refunded")
            if original["task_id"] is not None and original["task_id"] != normalized_task_id:
                raise ValueError("Credit transaction does not match task")
            if original["task_id"] is None and original["project_id"] != task["project_id"]:
                raise ValueError("Credit transaction does not match task")
            if original["task_id"] is None:
                connection.execute(
                    "UPDATE credit_transactions SET task_id = ? WHERE id = ? AND user_id = ? AND task_id IS NULL",
                    (normalized_task_id, original_transaction_id, user_id),
                )

            existing_row = _refund_row_by_original_transaction(connection, user_id, original_transaction_id)
            if existing_row is not None:
                return _transaction_from_row(existing_row)

            refund_id = str(uuid4())
            refund_metadata = {"reason": reason, "refund_of": original_transaction_id}
            try:
                connection.execute(
                    """
                    INSERT INTO credit_transactions (
                        id, user_id, project_id, task_id, action_type, direction, amount, status, metadata_json, refund_of_transaction_id, created_at
                    )
                    VALUES (?, ?, ?, ?, ?, 'credit', ?, 'applied', ?, ?, ?)
                    """,
                    (
                        refund_id,
                        user_id,
                        original["project_id"],
                        normalized_task_id,
                        original["action_type"],
                        original["amount"],
                        _json(refund_metadata),
                        original_transaction_id,
                        now,
                    ),
                )
            except sqlite3.IntegrityError:
                existing_row = _refund_row_by_original_transaction(connection, user_id, original_transaction_id)
                if existing_row is None:
                    raise
                return _transaction_from_row(existing_row)
            connection.execute(
                "UPDATE credit_transactions SET status = 'refunded' WHERE id = ? AND user_id = ?",
                (original_transaction_id, user_id),
            )
            connection.execute(
                """
                UPDATE credit_accounts
                SET balance = balance + ?, updated_at = ?
                WHERE user_id = ?
                """,
                (original["amount"], now, user_id),
            )
            row = connection.execute(
                """
                SELECT id, user_id, project_id, task_id, action_type, direction, amount, status, metadata_json, created_at
                FROM credit_transactions
                WHERE id = ?
                """,
                (refund_id,),
            ).fetchone()
        return _transaction_from_row(row)

    def increment_quota(self, user_id: str, action_type: CreditAction, period_key: str, limit_count: int) -> QuotaUsageResponse:
        if limit_count < 1:
            raise ValueError("Daily quota exceeded")
        now = _utc_now()
        quota_id = str(uuid4())
        with self.database.connect() as connection:
            connection.execute(
                """
                INSERT OR IGNORE INTO usage_quotas (id, user_id, scope, period_key, action_type, used_count, limit_count, updated_at)
                VALUES (?, ?, 'daily', ?, ?, 0, ?, ?)
                """,
                (quota_id, user_id, period_key, action_type, limit_count, now),
            )
            updated = connection.execute(
                """
                UPDATE usage_quotas
                SET used_count = used_count + 1, limit_count = ?, updated_at = ?
                WHERE user_id = ? AND action_type = ? AND scope = 'daily' AND period_key = ? AND used_count < ?
                """,
                (limit_count, now, user_id, action_type, period_key, limit_count),
            )
            if updated.rowcount == 0:
                raise ValueError("Daily quota exceeded")
            row = connection.execute(
                """
                SELECT id, user_id, action_type, scope, period_key, used_count, limit_count, updated_at
                FROM usage_quotas
                WHERE user_id = ? AND action_type = ? AND scope = 'daily' AND period_key = ?
                """,
                (user_id, action_type, period_key),
            ).fetchone()
        return _quota_from_row(row)

    def get_quota(self, user_id: str, action_type: CreditAction, period_key: str, limit_count: int) -> QuotaUsageResponse:
        with self.database.connect() as connection:
            row = connection.execute(
                """
                SELECT id, user_id, action_type, scope, period_key, used_count, limit_count, updated_at
                FROM usage_quotas
                WHERE user_id = ? AND action_type = ? AND scope = 'daily' AND period_key = ?
                """,
                (user_id, action_type, period_key),
            ).fetchone()
        if row is None:
            return QuotaUsageResponse(
                action_type=action_type,
                scope="daily",
                period_key=period_key,
                used_count=0,
                limit_count=limit_count,
            )
        return _quota_from_row(row)

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
        return _transaction_from_row(row)

    def find_refund(self, user_id: str, original_transaction_id: str) -> CreditTransactionResponse | None:
        with self.database.connect() as connection:
            row = _refund_row_by_original_transaction(connection, user_id, original_transaction_id)
        if row is None:
            return None
        metadata = json.loads(row["metadata_json"] or "{}")
        if metadata.get("refund_of") != original_transaction_id:
            return None
        return _transaction_from_row(row)

    def list_transactions(
        self,
        user_id: str,
        limit: int = 50,
        project_id: str | None = None,
    ) -> list[CreditTransactionResponse]:
        query = """
            SELECT id, user_id, project_id, task_id, action_type, direction, amount, status, metadata_json, created_at
            FROM credit_transactions
            WHERE user_id = ?
        """
        params: list[Any] = [user_id]
        if project_id is not None:
            query += " AND project_id = ?"
            params.append(project_id)
        query += " ORDER BY created_at DESC, id DESC LIMIT ?"
        params.append(limit)
        with self.database.connect() as connection:
            rows = connection.execute(query, tuple(params)).fetchall()
        return [_transaction_from_row(row) for row in rows]


def _json(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _dt(value: str) -> datetime:
    return datetime.fromisoformat(value)


def _account_exists(connection: sqlite3.Connection, user_id: str) -> bool:
    row = connection.execute("SELECT 1 FROM credit_accounts WHERE user_id = ?", (user_id,)).fetchone()
    return row is not None


def _owned_project_id(connection: sqlite3.Connection, user_id: str, project_id: str | None) -> str | None:
    if project_id is None:
        return None
    row = connection.execute("SELECT id FROM projects WHERE id = ? AND owner_id = ?", (project_id, user_id)).fetchone()
    if row is None:
        raise ValueError("Project not found")
    return row["id"]


def _owned_task_id(connection: sqlite3.Connection, user_id: str, task_id: str | None) -> str | None:
    if task_id is None:
        return None
    row = connection.execute("SELECT id FROM generation_tasks WHERE id = ? AND owner_id = ?", (task_id, user_id)).fetchone()
    if row is None:
        raise ValueError("Task not found")
    return row["id"]


def _refund_row_by_original_transaction(
    connection: sqlite3.Connection, user_id: str, original_transaction_id: str
) -> sqlite3.Row | None:
    return connection.execute(
        """
        SELECT id, user_id, project_id, task_id, action_type, direction, amount, status, metadata_json, created_at
        FROM credit_transactions
        WHERE user_id = ? AND refund_of_transaction_id = ?
        LIMIT 1
        """,
        (user_id, original_transaction_id),
    ).fetchone()


def _account_from_row(row: Any) -> CreditAccountResponse:
    return CreditAccountResponse(
        user_id=row["user_id"],
        balance=row["balance"],
        lifetime_granted=row["lifetime_granted"],
        lifetime_spent=row["lifetime_spent"],
        updated_at=_dt(row["updated_at"]),
    )


def _transaction_from_row(row: Any) -> CreditTransactionResponse:
    return CreditTransactionResponse(
        id=row["id"],
        user_id=row["user_id"],
        project_id=row["project_id"],
        task_id=row["task_id"],
        action_type=row["action_type"],
        direction=row["direction"],
        amount=row["amount"],
        status=row["status"],
        metadata=json.loads(row["metadata_json"] or "{}"),
        created_at=_dt(row["created_at"]),
    )


def _quota_from_row(row: Any) -> QuotaUsageResponse:
    return QuotaUsageResponse(
        action_type=row["action_type"],
        scope=row["scope"],
        period_key=row["period_key"],
        used_count=row["used_count"],
        limit_count=row["limit_count"],
    )
