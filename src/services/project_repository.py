import json
from datetime import datetime, timezone
from typing import Any, TypedDict
from uuid import uuid4

from src.models.project import AssetKind, AssetResponse, ProjectResponse, ProjectTaskResponse, TaskKind
from src.models.task import TaskStatus
from src.services.database import SQLiteDatabase


class RecoverableChargedTask(TypedDict):
    task_id: str
    owner_id: str
    credit_transaction_id: str


class CanvasCleanupTask(TypedDict):
    task_id: str
    owner_id: str


class ProjectRepository:
    def __init__(self, database: SQLiteDatabase):
        self.database = database

    def create_project(self, owner_id: str, name: str, description: str = "") -> ProjectResponse:
        project_id = str(uuid4())
        now = _utc_now()
        with self.database.connect() as connection:
            connection.execute(
                """
                INSERT INTO projects (id, owner_id, name, description, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (project_id, owner_id, name, description, now, now),
            )
        return ProjectResponse(id=project_id, name=name, description=description, created_at=_dt(now), updated_at=_dt(now))

    def list_projects(self, owner_id: str) -> list[ProjectResponse]:
        with self.database.connect() as connection:
            rows = connection.execute(
                "SELECT id, name, description, created_at, updated_at FROM projects WHERE owner_id = ? ORDER BY updated_at DESC",
                (owner_id,),
            ).fetchall()
        return [_project_response(row) for row in rows]

    def get_project(self, owner_id: str, project_id: str) -> ProjectResponse | None:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT id, name, description, created_at, updated_at FROM projects WHERE owner_id = ? AND id = ?",
                (owner_id, project_id),
            ).fetchone()
        return _project_response(row) if row else None

    def create_task(
        self,
        owner_id: str,
        project_id: str,
        kind: TaskKind,
        input_payload: dict[str, Any],
        cost_estimate: int = 0,
        charged_credits: int = 0,
    ) -> ProjectTaskResponse:
        task_id = str(uuid4())
        now = _utc_now()
        with self.database.connect() as connection:
            connection.execute(
                """
                INSERT INTO generation_tasks (
                    id, owner_id, project_id, kind, status, input_json, result_json, history_json, error,
                    cost_estimate, charged_credits, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, NULL, NULL, NULL, ?, ?, ?, ?)
                """,
                (task_id, owner_id, project_id, kind, TaskStatus.pending, _json(input_payload), cost_estimate, charged_credits, now, now),
            )
        return self.get_task(owner_id, task_id)

    def set_task_running(self, task_id: str) -> bool:
        now = _utc_now()
        with self.database.connect() as connection:
            updated = connection.execute(
                "UPDATE generation_tasks SET status = ?, updated_at = ? WHERE id = ? AND status = ?",
                (TaskStatus.running, now, task_id, TaskStatus.pending),
            )
        return updated.rowcount > 0

    def touch_task(self, task_id: str) -> bool:
        with self.database.connect() as connection:
            updated = connection.execute(
                "UPDATE generation_tasks SET updated_at = ? WHERE id = ? AND status = ?",
                (_utc_now(), task_id, TaskStatus.running),
            )
        return updated.rowcount > 0

    def set_task_succeeded(self, task_id: str, result: dict[str, Any], history: list[dict[str, Any]] | None = None) -> bool:
        now = _utc_now()
        with self.database.connect() as connection:
            updated = connection.execute(
                """
                UPDATE generation_tasks
                SET status = ?, result_json = ?, history_json = ?, error = NULL, updated_at = ?
                WHERE id = ? AND status IN (?, ?)
                """,
                (TaskStatus.succeeded, _json(result), _json(history or []), now, task_id, TaskStatus.pending, TaskStatus.running),
            )
        return updated.rowcount > 0

    def set_task_failed(self, task_id: str, error: str) -> bool:
        now = _utc_now()
        with self.database.connect() as connection:
            updated = connection.execute(
                "UPDATE generation_tasks SET status = ?, error = ?, updated_at = ? WHERE id = ? AND status IN (?, ?)",
                (TaskStatus.failed, error, now, task_id, TaskStatus.pending, TaskStatus.running),
            )
        return updated.rowcount > 0

    def get_task(self, owner_id: str, task_id: str) -> ProjectTaskResponse | None:
        with self.database.connect() as connection:
            row = connection.execute(
                """
                SELECT id, project_id, kind, status, input_json, result_json, error, cost_estimate, charged_credits, created_at, updated_at
                FROM generation_tasks
                WHERE owner_id = ? AND id = ?
                """,
                (owner_id, task_id),
            ).fetchone()
        return _task_response(row) if row else None

    def task_history(self, owner_id: str, task_id: str) -> list[dict[str, Any]] | None:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT history_json FROM generation_tasks WHERE owner_id = ? AND id = ?",
                (owner_id, task_id),
            ).fetchone()
        if row is None:
            return None
        return json.loads(row["history_json"] or "[]")

    def list_tasks(self, owner_id: str, project_id: str) -> list[ProjectTaskResponse]:
        with self.database.connect() as connection:
            rows = connection.execute(
                """
                SELECT id, project_id, kind, status, input_json, result_json, error, cost_estimate, charged_credits, created_at, updated_at
                FROM generation_tasks
                WHERE owner_id = ? AND project_id = ?
                ORDER BY updated_at DESC
                """,
                (owner_id, project_id),
            ).fetchall()
        return [_task_response(row) for row in rows]

    def list_recoverable_charged_tasks(self, updated_before: datetime) -> list[RecoverableChargedTask]:
        with self.database.connect() as connection:
            rows = connection.execute(
                """
                SELECT id, owner_id, input_json
                FROM generation_tasks
                WHERE status IN (?, ?) AND charged_credits > 0 AND updated_at < ?
                ORDER BY created_at ASC
                """,
                (TaskStatus.pending, TaskStatus.running, updated_before.isoformat()),
            ).fetchall()

        recoverable_tasks: list[RecoverableChargedTask] = []
        for row in rows:
            try:
                input_payload = json.loads(row["input_json"])
            except (TypeError, json.JSONDecodeError):
                continue
            if not isinstance(input_payload, dict):
                continue
            credit_transaction_id = input_payload.get("credit_transaction_id")
            if not isinstance(credit_transaction_id, str) or not credit_transaction_id:
                continue
            recoverable_tasks.append({"task_id": row["id"], "owner_id": row["owner_id"], "credit_transaction_id": credit_transaction_id})
        return recoverable_tasks

    def list_failed_canvas_cleanup_tasks(self) -> list[CanvasCleanupTask]:
        with self.database.connect() as connection:
            rows = connection.execute(
                """
                SELECT id, owner_id, input_json
                FROM generation_tasks
                WHERE status = ? AND charged_credits > 0
                ORDER BY created_at ASC
                """,
                (TaskStatus.failed,),
            ).fetchall()

        cleanup_tasks: list[CanvasCleanupTask] = []
        for row in rows:
            try:
                input_payload = json.loads(row["input_json"])
            except (TypeError, json.JSONDecodeError):
                continue
            if not isinstance(input_payload, dict):
                continue
            canvas_id = input_payload.get("canvas_id")
            if not isinstance(canvas_id, str) or not canvas_id:
                continue
            cleanup_tasks.append({"task_id": row["id"], "owner_id": row["owner_id"]})
        return cleanup_tasks

    def create_asset(
        self,
        owner_id: str,
        project_id: str,
        kind: AssetKind,
        url: str,
        media_type: str,
        metadata: dict[str, Any] | None = None,
    ) -> AssetResponse:
        asset_id = str(uuid4())
        now = _utc_now()
        with self.database.connect() as connection:
            connection.execute(
                """
                INSERT INTO assets (id, owner_id, project_id, kind, url, media_type, metadata_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (asset_id, owner_id, project_id, kind, url, media_type, _json(metadata or {}), now),
            )
        return AssetResponse(
            id=asset_id,
            project_id=project_id,
            kind=kind,
            url=url,
            media_type=media_type,
            metadata=metadata or {},
            review_status="pending",
            review_notes="",
            reviewed_by=None,
            reviewed_at=None,
            created_at=_dt(now),
        )

    def list_assets(self, owner_id: str, project_id: str) -> list[AssetResponse]:
        with self.database.connect() as connection:
            rows = connection.execute(
                """
                SELECT id, project_id, kind, url, media_type, metadata_json, review_status, review_notes, reviewed_by, reviewed_at, created_at
                FROM assets
                WHERE owner_id = ? AND project_id = ?
                ORDER BY created_at DESC
                """,
                (owner_id, project_id),
            ).fetchall()
        return [_asset_response(row) for row in rows]

    def get_asset(self, owner_id: str, project_id: str, asset_id: str) -> AssetResponse | None:
        with self.database.connect() as connection:
            row = connection.execute(
                """
                SELECT id, project_id, kind, url, media_type, metadata_json, review_status, review_notes, reviewed_by, reviewed_at, created_at
                FROM assets
                WHERE owner_id = ? AND project_id = ? AND id = ?
                """,
                (owner_id, project_id, asset_id),
            ).fetchone()
        return _asset_response(row) if row else None

    def asset_url_belongs_to_owner(self, owner_id: str, url: str) -> bool:
        with self.database.connect() as connection:
            row = connection.execute("SELECT 1 FROM assets WHERE owner_id = ? AND url = ? LIMIT 1", (owner_id, url)).fetchone()
        return row is not None


def _json(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _dt(value: str) -> datetime:
    return datetime.fromisoformat(value)


def _project_response(row) -> ProjectResponse:
    return ProjectResponse(id=row["id"], name=row["name"], description=row["description"], created_at=_dt(row["created_at"]), updated_at=_dt(row["updated_at"]))


def _task_response(row) -> ProjectTaskResponse:
    return ProjectTaskResponse(
        task_id=row["id"],
        project_id=row["project_id"],
        kind=row["kind"],
        status=row["status"],
        input=json.loads(row["input_json"]),
        result=json.loads(row["result_json"]) if row["result_json"] else None,
        error=row["error"],
        cost_estimate=row["cost_estimate"],
        charged_credits=row["charged_credits"],
        created_at=_dt(row["created_at"]),
        updated_at=_dt(row["updated_at"]),
    )


def _asset_response(row) -> AssetResponse:
    reviewed_at = row["reviewed_at"]
    return AssetResponse(
        id=row["id"],
        project_id=row["project_id"],
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
