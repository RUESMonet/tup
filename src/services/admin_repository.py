import json
from datetime import datetime, timezone

from src.models.admin import AdminAssetSummary, AdminTaskSummary, AdminUserSummary
from src.models.billing import ReviewStatus
from src.models.project import TaskKind
from src.models.task import TaskStatus
from src.services.database import SQLiteDatabase


class AdminRepository:
    def __init__(self, database: SQLiteDatabase):
        self.database = database

    def list_users(self, limit: int = 50) -> list[AdminUserSummary]:
        with self.database.connect() as connection:
            rows = connection.execute(
                """
                SELECT users.id, users.username, users.email, users.role, users.created_at,
                       COALESCE(credit_accounts.balance, 0) AS credit_balance
                FROM users
                LEFT JOIN credit_accounts ON credit_accounts.user_id = users.id
                ORDER BY users.created_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [_user_summary(row) for row in rows]

    def list_tasks(self, status: TaskStatus | None = None, kind: TaskKind | None = None, limit: int = 50) -> list[AdminTaskSummary]:
        query = """
            SELECT generation_tasks.id, generation_tasks.owner_id, users.username AS owner_username,
                   generation_tasks.project_id, generation_tasks.kind, generation_tasks.status,
                   generation_tasks.error, generation_tasks.cost_estimate, generation_tasks.charged_credits,
                   generation_tasks.created_at, generation_tasks.updated_at
            FROM generation_tasks
            JOIN users ON users.id = generation_tasks.owner_id
        """
        conditions: list[str] = []
        parameters: list[object] = []
        if status is not None:
            conditions.append("generation_tasks.status = ?")
            parameters.append(status)
        if kind is not None:
            conditions.append("generation_tasks.kind = ?")
            parameters.append(kind)
        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        query += " ORDER BY generation_tasks.updated_at DESC LIMIT ?"
        parameters.append(limit)

        with self.database.connect() as connection:
            rows = connection.execute(query, tuple(parameters)).fetchall()
        return [_task_summary(row) for row in rows]

    def list_assets_for_review(self, review_status: ReviewStatus | None = None, limit: int = 50) -> list[AdminAssetSummary]:
        query = """
            SELECT assets.id, assets.owner_id, users.username AS owner_username,
                   assets.project_id, projects.name AS project_name, assets.kind, assets.url, assets.media_type,
                   assets.metadata_json, assets.review_status, assets.review_notes, assets.reviewed_by,
                   assets.reviewed_at, assets.created_at
            FROM assets
            JOIN users ON users.id = assets.owner_id
            JOIN projects ON projects.id = assets.project_id
        """
        parameters: tuple[object, ...]
        if review_status is None:
            query += " ORDER BY assets.created_at DESC LIMIT ?"
            parameters = (limit,)
        else:
            query += " WHERE assets.review_status = ? ORDER BY assets.created_at DESC LIMIT ?"
            parameters = (review_status, limit)

        with self.database.connect() as connection:
            rows = connection.execute(query, parameters).fetchall()
        return [_asset_summary(row) for row in rows]

    def update_asset_review(self, asset_id: str, review_status: ReviewStatus, review_notes: str, reviewed_by: str) -> AdminAssetSummary | None:
        reviewer_id = reviewed_by
        reviewed_at = _utc_now()
        if review_status == "pending":
            reviewer_id = None
            reviewed_at = None
        with self.database.connect() as connection:
            updated = connection.execute(
                """
                UPDATE assets
                SET review_status = ?, review_notes = ?, reviewed_by = ?, reviewed_at = ?
                WHERE id = ?
                """,
                (review_status, review_notes, reviewer_id, reviewed_at, asset_id),
            )
            if updated.rowcount <= 0:
                return None
            row = connection.execute(
                """
                SELECT assets.id, assets.owner_id, users.username AS owner_username,
                       assets.project_id, projects.name AS project_name, assets.kind, assets.url, assets.media_type,
                       assets.metadata_json, assets.review_status, assets.review_notes, assets.reviewed_by,
                       assets.reviewed_at, assets.created_at
                FROM assets
                JOIN users ON users.id = assets.owner_id
                JOIN projects ON projects.id = assets.project_id
                WHERE assets.id = ?
                """,
                (asset_id,),
            ).fetchone()
        return _asset_summary(row) if row else None


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _dt(value: str) -> datetime:
    return datetime.fromisoformat(value)


def _user_summary(row) -> AdminUserSummary:
    return AdminUserSummary(
        id=row["id"],
        username=row["username"],
        email=row["email"],
        role=row["role"],
        credit_balance=row["credit_balance"],
        created_at=_dt(row["created_at"]),
    )


def _task_summary(row) -> AdminTaskSummary:
    return AdminTaskSummary(
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
        owner_username=row["owner_username"],
    )


def _asset_summary(row) -> AdminAssetSummary:
    reviewed_at = row["reviewed_at"]
    return AdminAssetSummary(
        id=row["id"],
        owner_id=row["owner_id"],
        owner_username=row["owner_username"],
        project_id=row["project_id"],
        project_name=row["project_name"],
        kind=row["kind"],
        url=row["url"],
        media_type=row["media_type"],
        metadata=_json_dict_or_empty(row["metadata_json"]),
        review_status=row["review_status"],
        review_notes=row["review_notes"],
        reviewed_by=row["reviewed_by"],
        reviewed_at=_dt(reviewed_at) if reviewed_at else None,
        created_at=_dt(row["created_at"]),
    )


def _json_dict_or_empty(value: str | None) -> dict[str, object]:
    try:
        payload = json.loads(value or "{}")
    except (TypeError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}
