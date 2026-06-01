import json
import sqlite3
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from src.models.canvas import BranchOperationResponse, BranchOperationSummaryResponse, CanvasDetailResponse, CanvasEdgeResponse, CanvasImageBatchResponse, CanvasImageCandidateResponse, CanvasNodeResponse, CanvasPosition, CanvasResponse, CanvasSize, PromptArtifactResponse
from src.services.database import SQLiteDatabase


MAX_PROMPT_ARTIFACT_BYTES = 60_000
MAX_PROMPT_ARTIFACT_DEPTH = 12
MAX_CASE_INDEX_BYTES = 40_000
MAX_CASE_INDEX_TERMS = 80
MAX_CASE_INDEX_ENTRIES_PER_PROJECT = 500
MAX_GENERATED_NODE_PAYLOAD_BYTES = 20_000
MAX_GENERATED_FINAL_PROMPT_CHARS = 12_000
MAX_IMAGE_CANDIDATE_METADATA_BYTES = 12_000
MAX_IMAGE_CANDIDATE_METADATA_DEPTH = 6
MAX_BRANCH_OPERATION_PAYLOAD_BYTES = 8_000
MAX_BRANCH_OPERATION_PAYLOAD_DEPTH = 4
BRANCH_OPERATION_TYPES = {"materialize", "archive", "restore", "pin", "unpin", "approve", "revoke", "select", "reject", "candidate"}
BRANCH_OPERATION_SCOPES = {"single", "subtree", "path"}


class CanvasRepository:
    def __init__(self, database: SQLiteDatabase):
        self.database = database

    def create_canvas(self, owner_id: str, project_id: str, name: str, description: str = "") -> CanvasResponse | None:
        canvas_id = str(uuid4())
        now = _utc_now()
        with self.database.connect() as connection:
            _begin_write(connection)
            project = connection.execute("SELECT 1 FROM projects WHERE owner_id = ? AND id = ?", (owner_id, project_id)).fetchone()
            if project is None:
                return None
            connection.execute(
                """
                INSERT INTO canvases (id, owner_id, project_id, name, description, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (canvas_id, owner_id, project_id, name, description, now, now),
            )
        return CanvasResponse(id=canvas_id, project_id=project_id, name=name, description=description, created_at=_dt(now), updated_at=_dt(now))

    def list_canvases(self, owner_id: str, project_id: str) -> list[CanvasResponse] | None:
        with self.database.connect() as connection:
            project = connection.execute("SELECT 1 FROM projects WHERE owner_id = ? AND id = ?", (owner_id, project_id)).fetchone()
            if project is None:
                return None
            rows = connection.execute(
                """
                SELECT id, project_id, name, description, created_at, updated_at
                FROM canvases
                WHERE owner_id = ? AND project_id = ?
                ORDER BY updated_at DESC
                """,
                (owner_id, project_id),
            ).fetchall()
        return [_canvas_response(row) for row in rows]

    def get_canvas(self, owner_id: str, canvas_id: str) -> CanvasDetailResponse | None:
        with self.database.connect() as connection:
            row = connection.execute(
                """
                SELECT id, project_id, name, description, created_at, updated_at
                FROM canvases
                WHERE owner_id = ? AND id = ?
                """,
                (owner_id, canvas_id),
            ).fetchone()
            if row is None:
                return None
            node_rows = connection.execute(
                """
                SELECT id, canvas_id, type, title, position_json, size_json, payload_json, created_at, updated_at
                FROM canvas_nodes
                WHERE canvas_id = ?
                ORDER BY created_at ASC
                """,
                (canvas_id,),
            ).fetchall()
            edge_rows = connection.execute(
                """
                SELECT id, canvas_id, source_node_id, target_node_id, type, payload_json, created_at
                FROM canvas_edges
                WHERE canvas_id = ?
                ORDER BY created_at ASC
                """,
                (canvas_id,),
            ).fetchall()
            operation_rows = connection.execute(
                """
                SELECT bo.id, bo.canvas_id, bo.operation, bo.reason, bo.scope, bo.target_node_id, bo.affected_node_ids_json, bo.payload_json, bo.owner_id, u.username AS actor_display, bo.created_at
                FROM branch_operations bo
                LEFT JOIN users u ON u.id = bo.owner_id
                WHERE bo.owner_id = ? AND bo.canvas_id = ?
                ORDER BY bo.created_at DESC, bo.id DESC
                LIMIT 80
                """,
                (owner_id, canvas_id),
            ).fetchall()
        canvas = _canvas_response(row)
        return CanvasDetailResponse(**canvas.model_dump(), nodes=[_node_response(item) for item in node_rows], edges=[_edge_response(item) for item in edge_rows], branch_operations=[_branch_operation_response(item) for item in operation_rows])

    def list_branch_operations_for_node_ids(self, owner_id: str, canvas_id: str, node_ids: set[str]) -> list[BranchOperationResponse] | None:
        if not node_ids:
            return []
        scoped_node_ids = sorted(node_ids)
        placeholders = ",".join("?" for _ in scoped_node_ids)
        with self.database.connect() as connection:
            canvas = connection.execute("SELECT 1 FROM canvases WHERE owner_id = ? AND id = ?", (owner_id, canvas_id)).fetchone()
            if canvas is None:
                return None
            rows = connection.execute(
                f"""
                SELECT bo.id, bo.canvas_id, bo.operation, bo.reason, bo.scope, bo.target_node_id, bo.affected_node_ids_json, bo.payload_json, bo.owner_id, u.username AS actor_display, bo.created_at
                FROM branch_operations bo
                LEFT JOIN users u ON u.id = bo.owner_id
                WHERE bo.owner_id = ?
                  AND bo.canvas_id = ?
                  AND (
                    bo.target_node_id IN ({placeholders})
                    OR EXISTS (
                      SELECT 1
                      FROM json_each(bo.affected_node_ids_json)
                      WHERE json_each.value IN ({placeholders})
                    )
                  )
                ORDER BY bo.created_at DESC, bo.id DESC
                """,
                (owner_id, canvas_id, *scoped_node_ids, *scoped_node_ids),
            ).fetchall()
        return [_branch_operation_response(row) for row in rows]

    def create_branch_operation(
        self,
        owner_id: str,
        canvas_id: str,
        operation: str,
        reason: str,
        scope: str,
        target_node_id: str | None,
        affected_node_ids: list[str],
        payload: dict[str, Any],
    ) -> BranchOperationResponse | None:
        operation = operation.strip()
        scope = scope.strip()
        if operation not in BRANCH_OPERATION_TYPES or scope not in BRANCH_OPERATION_SCOPES:
            raise ValueError("Invalid branch operation")
        affected_node_ids = list(dict.fromkeys(str(item) for item in affected_node_ids if item))[:200]
        payload = _branch_operation_payload(payload)
        operation_id = str(uuid4())
        now = _utc_now()
        with self.database.connect() as connection:
            _begin_write(connection)
            canvas = connection.execute("SELECT project_id FROM canvases WHERE owner_id = ? AND id = ?", (owner_id, canvas_id)).fetchone()
            if canvas is None:
                return None
            connection.execute(
                """
                INSERT INTO branch_operations (id, owner_id, project_id, canvas_id, operation, reason, scope, target_node_id, affected_node_ids_json, payload_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (operation_id, owner_id, canvas["project_id"], canvas_id, operation, reason[:500], scope, target_node_id, _json(affected_node_ids[:200]), _json(payload), now),
            )
            row = connection.execute(
                """
                SELECT bo.id, bo.canvas_id, bo.operation, bo.reason, bo.scope, bo.target_node_id, bo.affected_node_ids_json, bo.payload_json, bo.owner_id, u.username AS actor_display, bo.created_at
                FROM branch_operations bo
                LEFT JOIN users u ON u.id = bo.owner_id
                WHERE bo.id = ?
                """,
                (operation_id,),
            ).fetchone()
        return _branch_operation_response(row)

    def update_node_payload_and_create_branch_operation(
        self,
        owner_id: str,
        canvas_id: str,
        node_id: str,
        node_payload: dict[str, Any],
        operation: str,
        reason: str,
        scope: str,
        target_node_id: str | None,
        affected_node_ids: list[str],
        operation_payload: dict[str, Any],
    ) -> CanvasNodeResponse | None:
        operation = operation.strip()
        scope = scope.strip()
        if operation not in BRANCH_OPERATION_TYPES or scope not in BRANCH_OPERATION_SCOPES:
            raise ValueError("Invalid branch operation")
        affected_node_ids = list(dict.fromkeys(str(item) for item in affected_node_ids if item))[:200]
        operation_payload = _branch_operation_payload(operation_payload)
        operation_id = str(uuid4())
        now = _utc_now()
        with self.database.connect() as connection:
            _begin_write(connection)
            canvas = connection.execute("SELECT project_id FROM canvases WHERE owner_id = ? AND id = ?", (owner_id, canvas_id)).fetchone()
            if canvas is None:
                return None
            existing = connection.execute("SELECT id FROM canvas_nodes WHERE canvas_id = ? AND id = ?", (canvas_id, node_id)).fetchone()
            if existing is None:
                return None
            connection.execute("UPDATE canvas_nodes SET payload_json = ?, updated_at = ? WHERE id = ?", (_json(node_payload), now, node_id))
            connection.execute(
                """
                INSERT INTO branch_operations (id, owner_id, project_id, canvas_id, operation, reason, scope, target_node_id, affected_node_ids_json, payload_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (operation_id, owner_id, canvas["project_id"], canvas_id, operation, reason[:500], scope, target_node_id, _json(affected_node_ids), _json(operation_payload), now),
            )
            connection.execute("UPDATE canvases SET updated_at = ? WHERE id = ?", (now, canvas_id))
            row = connection.execute(
                """
                SELECT id, canvas_id, type, title, position_json, size_json, payload_json, created_at, updated_at
                FROM canvas_nodes WHERE id = ?
                """,
                (node_id,),
            ).fetchone()
        return _node_response(row)

    def update_node_payloads_and_create_branch_operations(
        self,
        owner_id: str,
        canvas_id: str,
        payloads_by_node_id: dict[str, dict[str, Any]],
        branch_operations: list[dict[str, Any]],
    ) -> list[CanvasNodeResponse] | None:
        node_ids = list(payloads_by_node_id)
        if not node_ids:
            return []
        now = _utc_now()
        with self.database.connect() as connection:
            _begin_write(connection)
            canvas = connection.execute("SELECT project_id FROM canvases WHERE owner_id = ? AND id = ?", (owner_id, canvas_id)).fetchone()
            if canvas is None:
                return None
            placeholders = ",".join("?" for _ in node_ids)
            existing = connection.execute(f"SELECT id FROM canvas_nodes WHERE canvas_id = ? AND id IN ({placeholders})", (canvas_id, *node_ids)).fetchall()
            if {row["id"] for row in existing} != set(node_ids):
                return None
            connection.executemany(
                "UPDATE canvas_nodes SET payload_json = ?, updated_at = ? WHERE id = ?",
                [(_json(payloads_by_node_id[node_id]), now, node_id) for node_id in node_ids],
            )
            operation_rows = []
            for item in branch_operations:
                operation = str(item.get("operation") or "").strip()
                scope = str(item.get("scope") or "").strip()
                if operation not in BRANCH_OPERATION_TYPES or scope not in BRANCH_OPERATION_SCOPES:
                    raise ValueError("Invalid branch operation")
                affected_node_ids = list(dict.fromkeys(str(node_id) for node_id in list(item.get("affected_node_ids") or []) if node_id))[:200]
                operation_rows.append(
                    (
                        str(uuid4()),
                        owner_id,
                        canvas["project_id"],
                        canvas_id,
                        operation,
                        str(item.get("reason") or "")[:500],
                        scope,
                        item.get("target_node_id"),
                        _json(affected_node_ids),
                        _json(_branch_operation_payload(dict(item.get("payload") or {}))),
                        now,
                    )
                )
            if operation_rows:
                connection.executemany(
                    """
                    INSERT INTO branch_operations (id, owner_id, project_id, canvas_id, operation, reason, scope, target_node_id, affected_node_ids_json, payload_json, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    operation_rows,
                )
            connection.execute("UPDATE canvases SET updated_at = ? WHERE id = ?", (now, canvas_id))
            rows = connection.execute(
                f"""
                SELECT id, canvas_id, type, title, position_json, size_json, payload_json, created_at, updated_at
                FROM canvas_nodes
                WHERE canvas_id = ? AND id IN ({placeholders})
                ORDER BY created_at ASC
                """,
                (canvas_id, *node_ids),
            ).fetchall()
        return [_node_response(row) for row in rows]

    def list_branch_operations(
        self,
        owner_id: str,
        canvas_id: str,
        operation: str | None = None,
        scope: str | None = None,
        target_node_id: str | None = None,
        limit: int = 40,
        offset: int = 0,
    ) -> tuple[list[BranchOperationResponse], int, BranchOperationSummaryResponse] | None:
        if operation is not None and operation not in BRANCH_OPERATION_TYPES:
            raise ValueError("Invalid branch operation")
        if scope is not None and scope not in BRANCH_OPERATION_SCOPES:
            raise ValueError("Invalid branch operation scope")
        limit = max(1, min(limit, 100))
        offset = max(0, offset)
        filters = ["bo.owner_id = ?", "bo.canvas_id = ?"]
        values: list[Any] = [owner_id, canvas_id]
        if operation is not None:
            filters.append("bo.operation = ?")
            values.append(operation)
        if scope is not None:
            filters.append("bo.scope = ?")
            values.append(scope)
        if target_node_id is not None:
            filters.append("bo.target_node_id = ?")
            values.append(target_node_id)
        where_clause = " AND ".join(filters)
        with self.database.connect() as connection:
            canvas = connection.execute("SELECT 1 FROM canvases WHERE owner_id = ? AND id = ?", (owner_id, canvas_id)).fetchone()
            if canvas is None:
                return None
            total = connection.execute(f"SELECT COUNT(*) AS total FROM branch_operations bo WHERE {where_clause}", tuple(values)).fetchone()["total"]
            rows = connection.execute(
                f"""
                SELECT bo.id, bo.canvas_id, bo.operation, bo.reason, bo.scope, bo.target_node_id, bo.affected_node_ids_json, bo.payload_json, bo.owner_id, u.username AS actor_display, bo.created_at
                FROM branch_operations bo
                LEFT JOIN users u ON u.id = bo.owner_id
                WHERE {where_clause}
                ORDER BY bo.created_at DESC, bo.id DESC
                LIMIT ? OFFSET ?
                """,
                (*values, limit, offset),
            ).fetchall()
            summary = _branch_operation_summary(connection, "bo.owner_id = ? AND bo.canvas_id = ?", [owner_id, canvas_id])
        return [_branch_operation_response(row) for row in rows], int(total), summary

    def create_node(
        self,
        owner_id: str,
        canvas_id: str,
        node_type: str,
        title: str,
        position: dict[str, float],
        size: dict[str, float],
        payload: dict[str, Any],
    ) -> CanvasNodeResponse | None:
        node_id = str(uuid4())
        now = _utc_now()
        with self.database.connect() as connection:
            _begin_write(connection)
            canvas = connection.execute("SELECT 1 FROM canvases WHERE owner_id = ? AND id = ?", (owner_id, canvas_id)).fetchone()
            if canvas is None:
                return None
            connection.execute(
                """
                INSERT INTO canvas_nodes (id, canvas_id, type, title, position_json, size_json, payload_json, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (node_id, canvas_id, node_type, title, _json(position), _json(size), _json(payload), now, now),
            )
            connection.execute("UPDATE canvases SET updated_at = ? WHERE id = ?", (now, canvas_id))
            row = connection.execute(
                """
                SELECT id, canvas_id, type, title, position_json, size_json, payload_json, created_at, updated_at
                FROM canvas_nodes WHERE id = ?
                """,
                (node_id,),
            ).fetchone()
        return _node_response(row)

    def update_node(self, owner_id: str, canvas_id: str, node_id: str, updates: dict[str, Any]) -> CanvasNodeResponse | None:
        now = _utc_now()
        with self.database.connect() as connection:
            _begin_write(connection)
            row = connection.execute(
                """
                SELECT n.id
                FROM canvas_nodes n
                JOIN canvases c ON c.id = n.canvas_id
                WHERE c.owner_id = ? AND n.canvas_id = ? AND n.id = ?
                """,
                (owner_id, canvas_id, node_id),
            ).fetchone()
            if row is None:
                return None
            assignments: list[str] = []
            values: list[Any] = []
            if "title" in updates:
                assignments.append("title = ?")
                values.append(updates["title"])
            if "position" in updates:
                assignments.append("position_json = ?")
                values.append(_json(updates["position"]))
            if "size" in updates:
                assignments.append("size_json = ?")
                values.append(_json(updates["size"]))
            if "payload" in updates:
                assignments.append("payload_json = ?")
                values.append(_json(updates["payload"]))
            if assignments:
                assignments.append("updated_at = ?")
                values.extend([now, node_id])
                connection.execute(f"UPDATE canvas_nodes SET {', '.join(assignments)} WHERE id = ?", tuple(values))
                connection.execute("UPDATE canvases SET updated_at = ? WHERE id = ?", (now, canvas_id))
            updated = connection.execute(
                """
                SELECT id, canvas_id, type, title, position_json, size_json, payload_json, created_at, updated_at
                FROM canvas_nodes WHERE id = ?
                """,
                (node_id,),
            ).fetchone()
        return _node_response(updated)

    def update_node_payloads(self, owner_id: str, canvas_id: str, payloads_by_node_id: dict[str, dict[str, Any]]) -> list[CanvasNodeResponse] | None:
        now = _utc_now()
        node_ids = list(payloads_by_node_id)
        if not node_ids:
            return []
        with self.database.connect() as connection:
            _begin_write(connection)
            canvas = connection.execute("SELECT 1 FROM canvases WHERE owner_id = ? AND id = ?", (owner_id, canvas_id)).fetchone()
            if canvas is None:
                return None
            placeholders = ",".join("?" for _ in node_ids)
            existing = connection.execute(f"SELECT id FROM canvas_nodes WHERE canvas_id = ? AND id IN ({placeholders})", (canvas_id, *node_ids)).fetchall()
            if {row["id"] for row in existing} != set(node_ids):
                return None
            connection.executemany(
                "UPDATE canvas_nodes SET payload_json = ?, updated_at = ? WHERE id = ?",
                [(_json(payloads_by_node_id[node_id]), now, node_id) for node_id in node_ids],
            )
            connection.execute("UPDATE canvases SET updated_at = ? WHERE id = ?", (now, canvas_id))
            rows = connection.execute(
                f"""
                SELECT id, canvas_id, type, title, position_json, size_json, payload_json, created_at, updated_at
                FROM canvas_nodes
                WHERE canvas_id = ? AND id IN ({placeholders})
                ORDER BY created_at ASC
                """,
                (canvas_id, *node_ids),
            ).fetchall()
        return [_node_response(row) for row in rows]

    def materialize_repair_version(
        self,
        owner_id: str,
        canvas_id: str,
        batch_id: str,
        title: str,
        position: dict[str, float],
        size: dict[str, float],
        payload: dict[str, Any],
        source_node_ids: list[str],
        parent_batch_id: str,
        materialize_reason: str | None = None,
    ) -> CanvasNodeResponse | None:
        node_id = str(uuid4())
        now = _utc_now()
        with self.database.connect() as connection:
            _begin_write(connection)
            canvas = connection.execute("SELECT project_id FROM canvases WHERE owner_id = ? AND id = ?", (owner_id, canvas_id)).fetchone()
            if canvas is None:
                return None
            node_rows = connection.execute(
                """
                SELECT id, canvas_id, type, title, position_json, size_json, payload_json, created_at, updated_at
                FROM canvas_nodes
                WHERE canvas_id = ? AND type = 'repair_version'
                ORDER BY created_at ASC
                """,
                (canvas_id,),
            ).fetchall()
            existing_node = None
            parent_node_id = ""
            child_node_ids: list[str] = []
            for row in node_rows:
                row_payload = json.loads(row["payload_json"])
                if row_payload.get("batch_id") == batch_id:
                    existing_node = row
                if parent_batch_id and row_payload.get("batch_id") == parent_batch_id:
                    parent_node_id = row["id"]
                if row_payload.get("repair_parent_batch_id") == batch_id:
                    child_node_ids.append(row["id"])
            placeholders = ",".join("?" for _ in source_node_ids)
            source_rows = connection.execute(f"SELECT id FROM canvas_nodes WHERE canvas_id = ? AND id IN ({placeholders})", (canvas_id, *source_node_ids)).fetchall()
            if {row["id"] for row in source_rows} != set(source_node_ids):
                return None
            created_node = existing_node is None
            if created_node:
                connection.execute(
                    """
                    INSERT INTO canvas_nodes (id, canvas_id, type, title, position_json, size_json, payload_json, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (node_id, canvas_id, "repair_version", title, _json(position), _json(size), _json(payload), now, now),
                )
            else:
                node_id = existing_node["id"]
            edge_rows = connection.execute(
                """
                SELECT source_node_id, target_node_id, type
                FROM canvas_edges
                WHERE canvas_id = ? AND (target_node_id = ? OR source_node_id = ?) AND type IN ('repair_version_source', 'repair_version_child')
                """,
                (canvas_id, node_id, node_id),
            ).fetchall()
            existing_edges = {(row["source_node_id"], row["target_node_id"], row["type"]) for row in edge_rows}
            edge_inserts = [
                (str(uuid4()), canvas_id, source_node_id, node_id, "repair_version_source", _json({"role": "repair_version_source", "batch_id": batch_id}), now)
                for source_node_id in source_node_ids
                if (source_node_id, node_id, "repair_version_source") not in existing_edges
            ]
            if parent_node_id and (parent_node_id, node_id, "repair_version_child") not in existing_edges:
                edge_inserts.append((str(uuid4()), canvas_id, parent_node_id, node_id, "repair_version_child", _json({"role": "repair_version_child", "batch_id": batch_id, "repair_parent_batch_id": parent_batch_id}), now))
            edge_inserts.extend(
                (str(uuid4()), canvas_id, node_id, child_node_id, "repair_version_child", _json({"role": "repair_version_child", "batch_id": batch_id}), now)
                for child_node_id in child_node_ids
                if (node_id, child_node_id, "repair_version_child") not in existing_edges
            )
            if edge_inserts:
                connection.executemany(
                    """
                    INSERT INTO canvas_edges (id, canvas_id, source_node_id, target_node_id, type, payload_json, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    edge_inserts,
                )
            if created_node and materialize_reason is not None:
                connection.execute(
                    """
                    INSERT INTO branch_operations (id, owner_id, project_id, canvas_id, operation, reason, scope, target_node_id, affected_node_ids_json, payload_json, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        str(uuid4()),
                        owner_id,
                        canvas["project_id"],
                        canvas_id,
                        "materialize",
                        materialize_reason[:500],
                        "single",
                        node_id,
                        _json([node_id, *source_node_ids]),
                        _json(_branch_operation_payload({"batch_id": batch_id, "parent_batch_id": parent_batch_id})),
                        now,
                    ),
                )
            connection.execute("UPDATE canvases SET updated_at = ? WHERE id = ?", (now, canvas_id))
            row = connection.execute(
                """
                SELECT id, canvas_id, type, title, position_json, size_json, payload_json, created_at, updated_at
                FROM canvas_nodes WHERE id = ?
                """,
                (node_id,),
            ).fetchone()
        return _node_response(row)

    def update_node_positions(self, owner_id: str, canvas_id: str, positions: list[dict[str, Any]]) -> list[CanvasNodeResponse] | None:
        now = _utc_now()
        node_ids = [item["id"] for item in positions]
        with self.database.connect() as connection:
            _begin_write(connection)
            canvas = connection.execute("SELECT 1 FROM canvases WHERE owner_id = ? AND id = ?", (owner_id, canvas_id)).fetchone()
            if canvas is None:
                return None
            placeholders = ",".join("?" for _ in node_ids)
            existing = connection.execute(f"SELECT id FROM canvas_nodes WHERE canvas_id = ? AND id IN ({placeholders})", (canvas_id, *node_ids)).fetchall()
            if {row["id"] for row in existing} != set(node_ids):
                return None
            connection.executemany(
                "UPDATE canvas_nodes SET position_json = ?, updated_at = ? WHERE id = ?",
                [(_json(item["position"]), now, item["id"]) for item in positions],
            )
            connection.execute("UPDATE canvases SET updated_at = ? WHERE id = ?", (now, canvas_id))
            rows = connection.execute(
                f"""
                SELECT id, canvas_id, type, title, position_json, size_json, payload_json, created_at, updated_at
                FROM canvas_nodes
                WHERE canvas_id = ? AND id IN ({placeholders})
                ORDER BY created_at ASC
                """,
                (canvas_id, *node_ids),
            ).fetchall()
        return [_node_response(row) for row in rows]

    def delete_node(self, owner_id: str, canvas_id: str, node_id: str) -> bool:
        now = _utc_now()
        with self.database.connect() as connection:
            _begin_write(connection)
            cursor = connection.execute(
                """
                DELETE FROM canvas_nodes
                WHERE id = ? AND canvas_id = ? AND EXISTS (SELECT 1 FROM canvases WHERE id = ? AND owner_id = ?)
                """,
                (node_id, canvas_id, canvas_id, owner_id),
            )
            if cursor.rowcount:
                connection.execute("UPDATE canvases SET updated_at = ? WHERE id = ?", (now, canvas_id))
        return bool(cursor.rowcount)

    def create_edge(
        self,
        owner_id: str,
        canvas_id: str,
        source_node_id: str,
        target_node_id: str,
        edge_type: str,
        payload: dict[str, Any],
    ) -> CanvasEdgeResponse | None:
        edge_id = str(uuid4())
        now = _utc_now()
        with self.database.connect() as connection:
            _begin_write(connection)
            canvas = connection.execute("SELECT 1 FROM canvases WHERE owner_id = ? AND id = ?", (owner_id, canvas_id)).fetchone()
            if canvas is None:
                return None
            rows = connection.execute(
                "SELECT id FROM canvas_nodes WHERE canvas_id = ? AND id IN (?, ?)",
                (canvas_id, source_node_id, target_node_id),
            ).fetchall()
            if {row["id"] for row in rows} != {source_node_id, target_node_id}:
                raise ValueError("Canvas edges must connect nodes on the same canvas")
            connection.execute(
                """
                INSERT INTO canvas_edges (id, canvas_id, source_node_id, target_node_id, type, payload_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (edge_id, canvas_id, source_node_id, target_node_id, edge_type, _json(payload), now),
            )
            connection.execute("UPDATE canvases SET updated_at = ? WHERE id = ?", (now, canvas_id))
            row = connection.execute(
                """
                SELECT id, canvas_id, source_node_id, target_node_id, type, payload_json, created_at
                FROM canvas_edges WHERE id = ?
                """,
                (edge_id,),
            ).fetchone()
        return _edge_response(row)

    def delete_edge(self, owner_id: str, canvas_id: str, edge_id: str) -> bool:
        now = _utc_now()
        with self.database.connect() as connection:
            _begin_write(connection)
            cursor = connection.execute(
                """
                DELETE FROM canvas_edges
                WHERE id = ? AND canvas_id = ? AND EXISTS (SELECT 1 FROM canvases WHERE id = ? AND owner_id = ?)
                """,
                (edge_id, canvas_id, canvas_id, owner_id),
            )
            if cursor.rowcount:
                connection.execute("UPDATE canvases SET updated_at = ? WHERE id = ?", (now, canvas_id))
        return bool(cursor.rowcount)

    def create_generated_image_result(
        self,
        owner_id: str,
        project_id: str,
        canvas_id: str,
        source_node_ids: list[str],
        image_url: str,
        media_type: str,
        task_id: str,
        final_prompt: str,
        position: dict[str, float],
    ) -> tuple[CanvasNodeResponse, str] | None:
        asset_id = str(uuid4())
        node_id = str(uuid4())
        now = _utc_now()
        with self.database.connect() as connection:
            _begin_write(connection)
            canvas = connection.execute(
                """
                SELECT project_id
                FROM canvases
                WHERE owner_id = ? AND id = ?
                """,
                (owner_id, canvas_id),
            ).fetchone()
            if canvas is None or canvas["project_id"] != project_id:
                return None
            placeholders = ",".join("?" for _ in source_node_ids)
            rows = connection.execute(
                f"SELECT id FROM canvas_nodes WHERE canvas_id = ? AND id IN ({placeholders})",
                (canvas_id, *source_node_ids),
            ).fetchall()
            if {row["id"] for row in rows} != set(source_node_ids):
                return None
            connection.execute(
                """
                INSERT INTO assets (id, owner_id, project_id, kind, url, media_type, metadata_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    asset_id,
                    owner_id,
                    project_id,
                    "image",
                    image_url,
                    media_type,
                    _json({"task_id": task_id, "canvas_id": canvas_id, "source": "canvas_generation", "source_node_ids": source_node_ids}),
                    now,
                ),
            )
            generated_payload = _generated_node_payload(asset_id, source_node_ids, media_type, task_id, final_prompt)
            connection.execute(
                """
                INSERT INTO canvas_nodes (id, canvas_id, type, title, position_json, size_json, payload_json, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    node_id,
                    canvas_id,
                    "generated_image",
                    "Generated image",
                    _json(position),
                    _json({"width": 320, "height": 220}),
                    _json(generated_payload),
                    now,
                    now,
                ),
            )
            connection.executemany(
                """
                INSERT INTO canvas_edges (id, canvas_id, source_node_id, target_node_id, type, payload_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (str(uuid4()), canvas_id, source_node_id, node_id, "lineage", _json({"task_id": task_id, "asset_id": asset_id, "source": "canvas_generation"}), now)
                    for source_node_id in source_node_ids
                ],
            )
            connection.execute("UPDATE canvases SET updated_at = ? WHERE id = ?", (now, canvas_id))
            row = connection.execute(
                """
                SELECT id, canvas_id, type, title, position_json, size_json, payload_json, created_at, updated_at
                FROM canvas_nodes WHERE id = ?
                """,
                (node_id,),
            ).fetchone()
        return _node_response(row), asset_id

    def create_edited_image_result(
        self,
        owner_id: str,
        project_id: str,
        canvas_id: str,
        source_node_ids: list[str],
        source_asset_ids: list[str],
        mask_asset_id: str | None,
        image_url: str,
        media_type: str,
        task_id: str,
        edit_prompt: str,
        final_prompt: str,
        action_type: str,
        position: dict[str, float],
    ) -> tuple[CanvasNodeResponse, str] | None:
        asset_id = str(uuid4())
        node_id = str(uuid4())
        now = _utc_now()
        with self.database.connect() as connection:
            _begin_write(connection)
            canvas = connection.execute("SELECT project_id FROM canvases WHERE owner_id = ? AND id = ?", (owner_id, canvas_id)).fetchone()
            if canvas is None or canvas["project_id"] != project_id:
                return None
            placeholders = ",".join("?" for _ in source_node_ids)
            rows = connection.execute(f"SELECT id, type, payload_json FROM canvas_nodes WHERE canvas_id = ? AND id IN ({placeholders})", (canvas_id, *source_node_ids)).fetchall()
            if {row["id"] for row in rows} != set(source_node_ids):
                return None
            bound_asset_ids: set[str] = set()
            for row in rows:
                row_payload = json.loads(row["payload_json"])
                if row["type"] in {"asset", "selected_image", "edited_image", "generated_image"} and row_payload.get("asset_id"):
                    if row["type"] != "asset" or str(row_payload.get("asset_kind") or "").lower() == "image" or str(row_payload.get("media_type") or "").startswith("image/"):
                        bound_asset_ids.add(str(row_payload.get("asset_id")))
                if row["type"] == "generated_video" and row_payload.get("source_asset_id"):
                    bound_asset_ids.add(str(row_payload.get("source_asset_id")))
                if row["type"] == "repair_version" and row_payload.get("source_image_asset_id"):
                    bound_asset_ids.add(str(row_payload.get("source_image_asset_id")))
            if not source_asset_ids or not set(source_asset_ids).issubset(bound_asset_ids):
                return None
            if mask_asset_id is not None and mask_asset_id not in bound_asset_ids:
                return None
            asset_inputs = list(dict.fromkeys([*source_asset_ids, *([mask_asset_id] if mask_asset_id else [])]))
            asset_placeholders = ",".join("?" for _ in asset_inputs)
            asset_rows = connection.execute(f"SELECT id FROM assets WHERE owner_id = ? AND project_id = ? AND kind = ? AND id IN ({asset_placeholders})", (owner_id, project_id, "image", *asset_inputs)).fetchall()
            if {row["id"] for row in asset_rows} != set(asset_inputs):
                return None
            connection.execute(
                """
                INSERT INTO assets (id, owner_id, project_id, kind, url, media_type, metadata_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    asset_id,
                    owner_id,
                    project_id,
                    "image",
                    image_url,
                    media_type,
                    _json({"task_id": task_id, "canvas_id": canvas_id, "source": "canvas_image_edit", "source_node_ids": source_node_ids, "source_asset_ids": source_asset_ids, "mask_asset_id": mask_asset_id, "action_type": action_type}),
                    now,
                ),
            )
            node_payload = _edited_image_node_payload(asset_id, source_node_ids, source_asset_ids, mask_asset_id, image_url, media_type, task_id, edit_prompt, final_prompt, action_type)
            connection.execute(
                """
                INSERT INTO canvas_nodes (id, canvas_id, type, title, position_json, size_json, payload_json, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (node_id, canvas_id, "edited_image", "Edited image", _json(position), _json({"width": 320, "height": 220}), _json(node_payload), now, now),
            )
            connection.executemany(
                """
                INSERT INTO canvas_edges (id, canvas_id, source_node_id, target_node_id, type, payload_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        str(uuid4()),
                        canvas_id,
                        source_node_id,
                        node_id,
                        "image_edit",
                        _json({"task_id": task_id, "asset_id": asset_id, "source_asset_ids": source_asset_ids, "mask_asset_id": mask_asset_id, "action_type": action_type}),
                        now,
                    )
                    for source_node_id in source_node_ids
                ],
            )
            connection.execute("UPDATE canvases SET updated_at = ? WHERE id = ?", (now, canvas_id))
            row = connection.execute(
                """
                SELECT id, canvas_id, type, title, position_json, size_json, payload_json, created_at, updated_at
                FROM canvas_nodes WHERE id = ?
                """,
                (node_id,),
            ).fetchone()
        return _node_response(row), asset_id

    def create_generated_video_result(
        self,
        owner_id: str,
        project_id: str,
        canvas_id: str,
        source_node_ids: list[str],
        source_asset_id: str,
        prompt_artifact_id: str | None,
        video_url: str,
        media_type: str,
        task_id: str,
        prompt: str,
        position: dict[str, float],
    ) -> tuple[CanvasNodeResponse, str] | None:
        asset_id = str(uuid4())
        node_id = str(uuid4())
        now = _utc_now()
        with self.database.connect() as connection:
            _begin_write(connection)
            canvas = connection.execute("SELECT project_id FROM canvases WHERE owner_id = ? AND id = ?", (owner_id, canvas_id)).fetchone()
            if canvas is None or canvas["project_id"] != project_id:
                return None
            source_node_types: dict[str, str] = {}
            if source_node_ids:
                placeholders = ",".join("?" for _ in source_node_ids)
                rows = connection.execute(f"SELECT id, type FROM canvas_nodes WHERE canvas_id = ? AND id IN ({placeholders})", (canvas_id, *source_node_ids)).fetchall()
                if {row["id"] for row in rows} != set(source_node_ids):
                    return None
                source_node_types = {row["id"]: row["type"] for row in rows}
            source_asset = connection.execute("SELECT 1 FROM assets WHERE owner_id = ? AND project_id = ? AND id = ? AND kind = ?", (owner_id, project_id, source_asset_id, "image")).fetchone()
            if source_asset is None:
                return None
            connection.execute(
                """
                INSERT INTO assets (id, owner_id, project_id, kind, url, media_type, metadata_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (asset_id, owner_id, project_id, "video", video_url, media_type, _json({"task_id": task_id, "canvas_id": canvas_id, "source": "canvas_video_generation", "source_asset_id": source_asset_id, "prompt_artifact_id": prompt_artifact_id, "source_node_ids": source_node_ids}), now),
            )
            connection.execute(
                """
                INSERT INTO canvas_nodes (id, canvas_id, type, title, position_json, size_json, payload_json, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (node_id, canvas_id, "generated_video", "Generated video", _json(position), _json({"width": 320, "height": 220}), _json(_generated_video_node_payload(asset_id, source_node_ids, source_asset_id, prompt_artifact_id, media_type, task_id, prompt)), now, now),
            )
            connection.executemany(
                """
                INSERT INTO canvas_edges (id, canvas_id, source_node_id, target_node_id, type, payload_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                [(str(uuid4()), canvas_id, source_node_id, node_id, "video_remix" if source_node_types.get(source_node_id) == "generated_video" else "video_from_image", _json({"task_id": task_id, "video_asset_id": asset_id, "source_asset_id": source_asset_id}), now) for source_node_id in source_node_ids],
            )
            connection.execute("UPDATE canvases SET updated_at = ? WHERE id = ?", (now, canvas_id))
            row = connection.execute(
                """
                SELECT id, canvas_id, type, title, position_json, size_json, payload_json, created_at, updated_at
                FROM canvas_nodes WHERE id = ?
                """,
                (node_id,),
            ).fetchone()
        return _node_response(row), asset_id

    def create_image_batch(
        self,
        owner_id: str,
        canvas_id: str,
        source_node_ids: list[str],
        prompt_artifact_id: str | None,
        task_id: str | None,
        prompt: str,
        params: dict[str, Any],
        status: str = "pending",
    ) -> CanvasImageBatchResponse | None:
        batch_id = str(uuid4())
        now = _utc_now()
        with self.database.connect() as connection:
            _begin_write(connection)
            canvas = connection.execute(
                """
                SELECT id, project_id
                FROM canvases
                WHERE owner_id = ? AND id = ?
                """,
                (owner_id, canvas_id),
            ).fetchone()
            if canvas is None:
                return None
            if source_node_ids:
                placeholders = ",".join("?" for _ in source_node_ids)
                rows = connection.execute(f"SELECT id FROM canvas_nodes WHERE canvas_id = ? AND id IN ({placeholders})", (canvas_id, *source_node_ids)).fetchall()
                if {row["id"] for row in rows} != set(source_node_ids):
                    return None
            if prompt_artifact_id is not None:
                artifact = connection.execute("SELECT 1 FROM prompt_artifacts WHERE owner_id = ? AND canvas_id = ? AND id = ?", (owner_id, canvas_id, prompt_artifact_id)).fetchone()
                if artifact is None:
                    return None
            connection.execute(
                """
                INSERT INTO image_batches (id, owner_id, project_id, canvas_id, source_node_ids_json, prompt_artifact_id, task_id, status, prompt, params_json, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (batch_id, owner_id, canvas["project_id"], canvas_id, _json(source_node_ids), prompt_artifact_id, task_id, status, prompt, _json(params), now, now),
            )
            connection.execute("UPDATE canvases SET updated_at = ? WHERE id = ?", (now, canvas_id))
            row = _image_batch_row(connection, owner_id, canvas_id, batch_id)
            candidate_rows = _image_candidate_rows(connection, batch_id)
        return _image_batch_response(row, candidate_rows)

    def create_image_candidate(
        self,
        owner_id: str,
        batch_id: str,
        asset_id: str,
        task_id: str | None,
        index: int,
        prompt: str,
        score: float | None,
        metadata: dict[str, Any],
        status: str = "candidate",
    ) -> CanvasImageCandidateResponse | None:
        if index < 0:
            raise ValueError("Image candidate index cannot be negative")
        _validate_image_candidate_metadata(metadata)
        candidate_id = str(uuid4())
        now = _utc_now()
        with self.database.connect() as connection:
            _begin_write(connection)
            batch = connection.execute(
                """
                SELECT id, project_id, canvas_id
                FROM image_batches
                WHERE owner_id = ? AND id = ?
                """,
                (owner_id, batch_id),
            ).fetchone()
            if batch is None:
                return None
            asset = connection.execute(
                """
                SELECT 1
                FROM assets
                WHERE owner_id = ? AND project_id = ? AND id = ? AND kind = 'image'
                """,
                (owner_id, batch["project_id"], asset_id),
            ).fetchone()
            if asset is None:
                return None
            connection.execute(
                """
                INSERT INTO image_candidates (id, owner_id, project_id, canvas_id, batch_id, asset_id, task_id, node_id, candidate_index, prompt, score, status, metadata_json, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, NULL, ?, ?, ?, ?, ?, ?, ?)
                """,
                (candidate_id, owner_id, batch["project_id"], batch["canvas_id"], batch_id, asset_id, task_id, index, prompt, score, status, _json(metadata), now, now),
            )
            connection.execute("UPDATE image_batches SET updated_at = ? WHERE id = ?", (now, batch_id))
            row = _image_candidate_row(connection, owner_id, candidate_id)
        return _image_candidate_response(row)

    def list_image_batches(self, owner_id: str, canvas_id: str, batch_limit: int | None = None, candidate_limit: int | None = None) -> list[CanvasImageBatchResponse] | None:
        with self.database.connect() as connection:
            canvas = connection.execute("SELECT 1 FROM canvases WHERE owner_id = ? AND id = ?", (owner_id, canvas_id)).fetchone()
            if canvas is None:
                return None
            query = """
                SELECT id, canvas_id, project_id, source_node_ids_json, prompt_artifact_id, task_id, status, prompt, params_json, created_at, updated_at
                FROM image_batches
                WHERE owner_id = ? AND canvas_id = ?
                ORDER BY created_at DESC
                """
            values: tuple[Any, ...] = (owner_id, canvas_id)
            if batch_limit is not None:
                query = f"{query} LIMIT ?"
                values = (*values, batch_limit)
            rows = connection.execute(query, values).fetchall()
            candidates_by_batch = {row["id"]: _image_candidate_rows(connection, row["id"], candidate_limit) for row in rows}
        return [_image_batch_response(row, candidates_by_batch[row["id"]]) for row in rows]

    def get_image_batch(self, owner_id: str, canvas_id: str, batch_id: str) -> CanvasImageBatchResponse | None:
        with self.database.connect() as connection:
            row = _image_batch_row(connection, owner_id, canvas_id, batch_id)
            if row is None:
                return None
            candidate_rows = _image_candidate_rows(connection, batch_id)
        return _image_batch_response(row, candidate_rows)

    def get_image_candidate(self, owner_id: str, canvas_id: str, candidate_id: str) -> CanvasImageCandidateResponse | None:
        with self.database.connect() as connection:
            row = connection.execute(
                """
                SELECT id, batch_id, canvas_id, asset_id, task_id, node_id, candidate_index, prompt, score, status, metadata_json, created_at, updated_at
                FROM image_candidates
                WHERE owner_id = ? AND canvas_id = ? AND id = ?
                """,
                (owner_id, canvas_id, candidate_id),
            ).fetchone()
        return _image_candidate_response(row) if row else None

    def set_image_batch_status(self, owner_id: str, batch_id: str, status: str) -> CanvasImageBatchResponse | None:
        now = _utc_now()
        with self.database.connect() as connection:
            _begin_write(connection)
            batch = connection.execute("SELECT canvas_id FROM image_batches WHERE owner_id = ? AND id = ?", (owner_id, batch_id)).fetchone()
            if batch is None:
                return None
            connection.execute("UPDATE image_batches SET status = ?, updated_at = ? WHERE id = ?", (status, now, batch_id))
            row = _image_batch_row(connection, owner_id, batch["canvas_id"], batch_id)
            candidate_rows = _image_candidate_rows(connection, batch_id)
        return _image_batch_response(row, candidate_rows)

    def cleanup_generated_media_for_task(self, owner_id: str, canvas_id: str, task_id: str) -> None:
        now = _utc_now()
        with self.database.connect() as connection:
            _begin_write(connection)
            node_rows = connection.execute(
                """
                SELECT id
                FROM canvas_nodes
                WHERE canvas_id = ?
                  AND type IN ('generated_image', 'edited_image', 'generated_video')
                  AND json_extract(payload_json, '$.task_id') = ?
                  AND EXISTS (SELECT 1 FROM canvases WHERE id = ? AND owner_id = ?)
                """,
                (canvas_id, task_id, canvas_id, owner_id),
            ).fetchall()
            asset_rows = connection.execute(
                """
                SELECT id
                FROM assets
                WHERE owner_id = ?
                  AND json_extract(metadata_json, '$.canvas_id') = ?
                  AND json_extract(metadata_json, '$.task_id') = ?
                """,
                (owner_id, canvas_id, task_id),
            ).fetchall()
            if node_rows:
                connection.executemany("DELETE FROM canvas_nodes WHERE canvas_id = ? AND id = ?", [(canvas_id, row["id"]) for row in node_rows])
            if asset_rows:
                connection.executemany("DELETE FROM assets WHERE owner_id = ? AND id = ?", [(owner_id, row["id"]) for row in asset_rows])
            if node_rows or asset_rows:
                connection.execute("UPDATE canvases SET updated_at = ? WHERE id = ?", (now, canvas_id))

    def cleanup_image_batch_candidates(self, owner_id: str, batch_id: str) -> None:
        now = _utc_now()
        with self.database.connect() as connection:
            _begin_write(connection)
            batch = connection.execute("SELECT canvas_id FROM image_batches WHERE owner_id = ? AND id = ?", (owner_id, batch_id)).fetchone()
            if batch is None:
                return
            candidate_rows = connection.execute(
                "SELECT id, asset_id, node_id FROM image_candidates WHERE owner_id = ? AND batch_id = ?",
                (owner_id, batch_id),
            ).fetchall()
            if candidate_rows:
                node_ids = [row["node_id"] for row in candidate_rows if row["node_id"]]
                asset_ids = [row["asset_id"] for row in candidate_rows if row["asset_id"]]
                connection.execute("DELETE FROM image_selections WHERE owner_id = ? AND batch_id = ?", (owner_id, batch_id))
                if node_ids:
                    connection.executemany("DELETE FROM canvas_nodes WHERE canvas_id = ? AND id = ?", [(batch["canvas_id"], node_id) for node_id in node_ids])
                connection.execute("DELETE FROM image_candidates WHERE owner_id = ? AND batch_id = ?", (owner_id, batch_id))
                if asset_ids:
                    connection.executemany("DELETE FROM assets WHERE owner_id = ? AND id = ?", [(owner_id, asset_id) for asset_id in asset_ids])
                connection.execute("UPDATE canvases SET updated_at = ? WHERE id = ?", (now, batch["canvas_id"]))

    def cleanup_task_side_effects(self, owner_id: str, task_id: str) -> None:
        now = _utc_now()
        with self.database.connect() as connection:
            _begin_write(connection)
            batch_rows = connection.execute(
                "SELECT id, canvas_id FROM image_batches WHERE owner_id = ? AND task_id = ?",
                (owner_id, task_id),
            ).fetchall()
            for batch in batch_rows:
                candidate_rows = connection.execute(
                    "SELECT asset_id, node_id FROM image_candidates WHERE owner_id = ? AND batch_id = ?",
                    (owner_id, batch["id"]),
                ).fetchall()
                node_ids = [row["node_id"] for row in candidate_rows if row["node_id"]]
                asset_ids = [row["asset_id"] for row in candidate_rows if row["asset_id"]]
                connection.execute("DELETE FROM image_selections WHERE owner_id = ? AND batch_id = ?", (owner_id, batch["id"]))
                if node_ids:
                    connection.executemany("DELETE FROM canvas_nodes WHERE canvas_id = ? AND id = ?", [(batch["canvas_id"], node_id) for node_id in node_ids])
                connection.execute("DELETE FROM image_candidates WHERE owner_id = ? AND batch_id = ?", (owner_id, batch["id"]))
                if asset_ids:
                    connection.executemany("DELETE FROM assets WHERE owner_id = ? AND id = ?", [(owner_id, asset_id) for asset_id in asset_ids])
                connection.execute("UPDATE image_batches SET status = ?, updated_at = ? WHERE id = ?", ("failed", now, batch["id"]))
                connection.execute("UPDATE canvases SET updated_at = ? WHERE id = ?", (now, batch["canvas_id"]))

            node_rows = connection.execute(
                """
                SELECT n.id, n.canvas_id
                FROM canvas_nodes n
                JOIN canvases c ON c.id = n.canvas_id
                WHERE c.owner_id = ?
                  AND n.type IN ('generated_image', 'edited_image', 'generated_video')
                  AND json_extract(n.payload_json, '$.task_id') = ?
                """,
                (owner_id, task_id),
            ).fetchall()
            if node_rows:
                connection.executemany("DELETE FROM canvas_nodes WHERE canvas_id = ? AND id = ?", [(row["canvas_id"], row["id"]) for row in node_rows])
                touched_canvas_ids = sorted({row["canvas_id"] for row in node_rows})
                connection.executemany("UPDATE canvases SET updated_at = ? WHERE id = ?", [(now, canvas_id) for canvas_id in touched_canvas_ids])

            asset_rows = connection.execute(
                """
                SELECT id
                FROM assets
                WHERE owner_id = ?
                  AND json_extract(metadata_json, '$.task_id') = ?
                  AND json_extract(metadata_json, '$.canvas_id') IS NOT NULL
                """,
                (owner_id, task_id),
            ).fetchall()
            if asset_rows:
                connection.executemany("DELETE FROM assets WHERE owner_id = ? AND id = ?", [(owner_id, row["id"]) for row in asset_rows])

    def cleanup_generated_media(self, owner_id: str, canvas_id: str, node_id: str | None, asset_id: str | None) -> None:
        now = _utc_now()
        with self.database.connect() as connection:
            _begin_write(connection)
            deleted = False
            if node_id:
                result = connection.execute(
                    "DELETE FROM canvas_nodes WHERE canvas_id = ? AND id = ? AND EXISTS (SELECT 1 FROM canvases WHERE id = ? AND owner_id = ?)",
                    (canvas_id, node_id, canvas_id, owner_id),
                )
                deleted = deleted or result.rowcount > 0
            if asset_id:
                result = connection.execute(
                    "DELETE FROM assets WHERE owner_id = ? AND id = ?",
                    (owner_id, asset_id),
                )
                deleted = deleted or result.rowcount > 0
            if deleted:
                connection.execute("UPDATE canvases SET updated_at = ? WHERE id = ?", (now, canvas_id))

    def cleanup_image_batch_candidates_by_ids(self, owner_id: str, batch_id: str, candidate_ids: list[str], asset_ids: list[str] | None = None) -> None:
        asset_ids = asset_ids or []
        if not candidate_ids and not asset_ids:
            return
        now = _utc_now()
        with self.database.connect() as connection:
            _begin_write(connection)
            batch = connection.execute("SELECT canvas_id FROM image_batches WHERE owner_id = ? AND id = ?", (owner_id, batch_id)).fetchone()
            if batch is None:
                return
            candidate_asset_ids: list[str] = []
            if candidate_ids:
                placeholders = ",".join("?" for _ in candidate_ids)
                rows = connection.execute(
                    f"SELECT id, asset_id, node_id FROM image_candidates WHERE owner_id = ? AND batch_id = ? AND id IN ({placeholders})",
                    (owner_id, batch_id, *candidate_ids),
                ).fetchall()
                if rows:
                    selected_candidate_ids = [row["id"] for row in rows]
                    node_ids = [row["node_id"] for row in rows if row["node_id"]]
                    candidate_asset_ids = [row["asset_id"] for row in rows if row["asset_id"]]
                    delete_placeholders = ",".join("?" for _ in selected_candidate_ids)
                    connection.execute(
                        f"DELETE FROM image_selections WHERE owner_id = ? AND batch_id = ? AND candidate_id IN ({delete_placeholders})",
                        (owner_id, batch_id, *selected_candidate_ids),
                    )
                    if node_ids:
                        connection.executemany("DELETE FROM canvas_nodes WHERE canvas_id = ? AND id = ?", [(batch["canvas_id"], node_id) for node_id in node_ids])
                    connection.execute(
                        f"DELETE FROM image_candidates WHERE owner_id = ? AND batch_id = ? AND id IN ({delete_placeholders})",
                        (owner_id, batch_id, *selected_candidate_ids),
                    )
            delete_asset_ids = sorted({*asset_ids, *candidate_asset_ids})
            if delete_asset_ids:
                connection.executemany("DELETE FROM assets WHERE owner_id = ? AND id = ?", [(owner_id, asset_id) for asset_id in delete_asset_ids])
            connection.execute("UPDATE canvases SET updated_at = ? WHERE id = ?", (now, batch["canvas_id"]))

    def set_image_candidate_status(
        self,
        owner_id: str,
        canvas_id: str,
        batch_id: str,
        candidate_id: str,
        candidate_status: str,
        reason: str,
        position: dict[str, float] | None = None,
    ) -> CanvasImageCandidateResponse | None:
        now = _utc_now()
        with self.database.connect() as connection:
            _begin_write(connection)
            candidate = connection.execute(
                """
                SELECT c.id, c.asset_id, c.node_id, c.status, c.prompt, c.score, c.metadata_json, b.project_id, b.canvas_id, b.source_node_ids_json
                FROM image_candidates c
                JOIN image_batches b ON b.id = c.batch_id
                WHERE c.owner_id = ? AND b.owner_id = ? AND b.canvas_id = ? AND b.id = ? AND c.id = ?
                """,
                (owner_id, owner_id, canvas_id, batch_id, candidate_id),
            ).fetchone()
            if candidate is None:
                return None
            node_id = candidate["node_id"]
            previous_node_id = node_id
            previous_status = candidate["status"]
            source_node_ids = json.loads(candidate["source_node_ids_json"])
            if candidate_status == "selected" and node_id is None:
                node_id = str(uuid4())
                node_payload = _selected_image_node_payload(batch_id, candidate_id, candidate["asset_id"], candidate["prompt"], candidate["score"], json.loads(candidate["metadata_json"]))
                connection.execute(
                    """
                    INSERT INTO canvas_nodes (id, canvas_id, type, title, position_json, size_json, payload_json, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (node_id, canvas_id, "selected_image", "Selected image", _json(position or {"x": 480, "y": 0}), _json({"width": 320, "height": 220}), _json(node_payload), now, now),
                )
                connection.executemany(
                    """
                    INSERT INTO canvas_edges (id, canvas_id, source_node_id, target_node_id, type, payload_json, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    [
                        (str(uuid4()), canvas_id, source_node_id, node_id, "selected_candidate", _json({"batch_id": batch_id, "candidate_id": candidate_id, "asset_id": candidate["asset_id"]}), now)
                        for source_node_id in source_node_ids
                    ],
                )
                connection.execute(
                    """
                    INSERT OR IGNORE INTO image_selections (id, owner_id, project_id, canvas_id, batch_id, candidate_id, node_id, selection_reason, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (str(uuid4()), owner_id, candidate["project_id"], canvas_id, batch_id, candidate_id, node_id, reason, now),
                )
            elif candidate_status != "selected" and node_id is not None:
                connection.execute(
                    """
                    DELETE FROM image_selections
                    WHERE owner_id = ? AND canvas_id = ? AND batch_id = ? AND candidate_id = ?
                    """,
                    (owner_id, canvas_id, batch_id, candidate_id),
                )
                connection.execute("DELETE FROM canvas_nodes WHERE canvas_id = ? AND id = ?", (canvas_id, node_id))
                node_id = None
            connection.execute(
                """
                UPDATE image_candidates
                SET status = ?, node_id = ?, updated_at = ?
                WHERE id = ?
                """,
                (candidate_status, node_id, now, candidate_id),
            )
            if previous_status != candidate_status:
                operation = "select" if candidate_status == "selected" else "reject" if candidate_status == "rejected" else "candidate"
                affected_node_ids = list(dict.fromkeys([item for item in [node_id or previous_node_id, *source_node_ids] if item]))
                connection.execute(
                    """
                    INSERT INTO branch_operations (id, owner_id, project_id, canvas_id, operation, reason, scope, target_node_id, affected_node_ids_json, payload_json, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        str(uuid4()),
                        owner_id,
                        candidate["project_id"],
                        canvas_id,
                        operation,
                        reason[:500],
                        "single",
                        node_id or previous_node_id,
                        _json(affected_node_ids),
                        _json(_branch_operation_payload({"batch_id": batch_id, "candidate_id": candidate_id, "asset_id": candidate["asset_id"], "from_status": previous_status, "to_status": candidate_status, "node_id": node_id or previous_node_id})),
                        now,
                    ),
                )
            connection.execute("UPDATE image_batches SET updated_at = ? WHERE id = ?", (now, batch_id))
            connection.execute("UPDATE canvases SET updated_at = ? WHERE id = ?", (now, canvas_id))
            row = _image_candidate_row(connection, owner_id, candidate_id)
        return _image_candidate_response(row)

    def create_prompt_artifact(
        self,
        owner_id: str,
        canvas_id: str,
        node_id: str | None,
        kind: str,
        payload: dict[str, Any],
    ) -> PromptArtifactResponse | None:
        _validate_prompt_artifact_payload(payload)
        artifact_id = str(uuid4())
        now = _utc_now()
        with self.database.connect() as connection:
            _begin_write(connection)
            canvas = connection.execute(
                """
                SELECT id, project_id
                FROM canvases
                WHERE owner_id = ? AND id = ?
                """,
                (owner_id, canvas_id),
            ).fetchone()
            if canvas is None:
                return None
            if node_id is not None:
                node = connection.execute("SELECT 1 FROM canvas_nodes WHERE canvas_id = ? AND id = ?", (canvas_id, node_id)).fetchone()
                if node is None:
                    return None
            connection.execute(
                """
                INSERT INTO prompt_artifacts (id, owner_id, project_id, canvas_id, node_id, kind, payload_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (artifact_id, owner_id, canvas["project_id"], canvas_id, node_id, kind, _json(payload), now),
            )
            connection.execute("UPDATE canvases SET updated_at = ? WHERE id = ?", (now, canvas_id))
            row = connection.execute(
                """
                SELECT id, canvas_id, node_id, kind, payload_json, created_at
                FROM prompt_artifacts
                WHERE id = ?
                """,
                (artifact_id,),
            ).fetchone()
        return _artifact_response(row)

    def get_prompt_artifact(self, owner_id: str, canvas_id: str, artifact_id: str) -> PromptArtifactResponse | None:
        with self.database.connect() as connection:
            row = connection.execute(
                """
                SELECT id, canvas_id, node_id, kind, payload_json, created_at
                FROM prompt_artifacts
                WHERE owner_id = ? AND canvas_id = ? AND id = ?
                """,
                (owner_id, canvas_id, artifact_id),
            ).fetchone()
        return _artifact_response(row) if row else None

    def list_prompt_artifacts(
        self,
        owner_id: str,
        canvas_id: str,
        node_id: str | None = None,
        kind: str | None = None,
        limit: int = 50,
    ) -> list[PromptArtifactResponse] | None:
        if limit < 1 or limit > 100:
            raise ValueError("Prompt artifact limit must be between 1 and 100")
        with self.database.connect() as connection:
            canvas = connection.execute("SELECT 1 FROM canvases WHERE owner_id = ? AND id = ?", (owner_id, canvas_id)).fetchone()
            if canvas is None:
                return None
            filters = ["owner_id = ?", "canvas_id = ?"]
            values: list[Any] = [owner_id, canvas_id]
            if node_id is not None:
                filters.append("node_id = ?")
                values.append(node_id)
            if kind is not None:
                filters.append("kind = ?")
                values.append(kind)
            values.append(limit)
            rows = connection.execute(
                f"""
                SELECT id, canvas_id, node_id, kind, payload_json, created_at
                FROM prompt_artifacts
                WHERE {' AND '.join(filters)}
                ORDER BY created_at DESC
                LIMIT ?
                """,
                tuple(values),
            ).fetchall()
        return [_artifact_response(row) for row in rows]

    def create_case_index_entry(self, owner_id: str, project_id: str, case_payload: dict[str, Any], search_terms: list[str]) -> dict[str, Any] | None:
        _validate_case_index_payload(case_payload, search_terms)
        artifact_id = str(case_payload.get("artifact_id") or "")
        entry_id = str(uuid4())
        now = _utc_now()
        with self.database.connect() as connection:
            _begin_write(connection)
            project = connection.execute("SELECT 1 FROM projects WHERE owner_id = ? AND id = ?", (owner_id, project_id)).fetchone()
            if project is None:
                return None
            existing_rows = connection.execute(
                """
                SELECT id, source, profile, title, visual_dna_json, prompt_spec_json, embedding_json, created_at
                FROM case_index_entries
                WHERE owner_id = ? AND project_id = ?
                ORDER BY created_at DESC
                """,
                (owner_id, project_id),
            ).fetchall()
            if artifact_id:
                for row in existing_rows:
                    embedding = json.loads(row["embedding_json"])
                    if embedding.get("artifact_id") == artifact_id:
                        return _case_index_response(row)
            if len(existing_rows) >= MAX_CASE_INDEX_ENTRIES_PER_PROJECT:
                raise ValueError("Project case memory exceeds the entry limit")
            connection.execute(
                """
                INSERT INTO case_index_entries (id, owner_id, project_id, source, profile, title, visual_dna_json, prompt_spec_json, embedding_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    entry_id,
                    owner_id,
                    project_id,
                    str(case_payload.get("source") or "project_case_memory"),
                    str(case_payload.get("profile") or "professional_design"),
                    str(case_payload.get("title") or "Untitled case"),
                    _json(case_payload.get("visual_dna") or {}),
                    _json(case_payload.get("prompt_spec") or {}),
                    _json({"artifact_id": artifact_id, "terms": search_terms[:MAX_CASE_INDEX_TERMS], "quality_score": case_payload.get("quality_score", 0), "takeaways": case_payload.get("takeaways") or []}),
                    now,
                ),
            )
        return {key: value for key, value in {**case_payload, "id": entry_id}.items() if key != "artifact_id"}

    def list_case_index_entries(self, owner_id: str, project_id: str) -> list[dict[str, Any]] | None:
        with self.database.connect() as connection:
            project = connection.execute("SELECT 1 FROM projects WHERE owner_id = ? AND id = ?", (owner_id, project_id)).fetchone()
            if project is None:
                return None
            rows = connection.execute(
                """
                SELECT id, source, profile, title, visual_dna_json, prompt_spec_json, embedding_json, created_at
                FROM case_index_entries
                WHERE owner_id = ? AND project_id = ?
                ORDER BY created_at DESC
                """,
                (owner_id, project_id),
            ).fetchall()
        return [_case_index_response(row) for row in rows]


def _image_batch_row(connection: sqlite3.Connection, owner_id: str, canvas_id: str, batch_id: str) -> sqlite3.Row:
    return connection.execute(
        """
        SELECT id, canvas_id, project_id, source_node_ids_json, prompt_artifact_id, task_id, status, prompt, params_json, created_at, updated_at
        FROM image_batches
        WHERE owner_id = ? AND canvas_id = ? AND id = ?
        """,
        (owner_id, canvas_id, batch_id),
    ).fetchone()


def _image_candidate_row(connection: sqlite3.Connection, owner_id: str, candidate_id: str) -> sqlite3.Row:
    return connection.execute(
        """
        SELECT id, batch_id, canvas_id, asset_id, task_id, node_id, candidate_index, prompt, score, status, metadata_json, created_at, updated_at
        FROM image_candidates
        WHERE owner_id = ? AND id = ?
        """,
        (owner_id, candidate_id),
    ).fetchone()


def _image_candidate_rows(connection: sqlite3.Connection, batch_id: str, limit: int | None = None) -> list[sqlite3.Row]:
    query = """
        SELECT id, batch_id, canvas_id, asset_id, task_id, node_id, candidate_index, prompt, score, status, metadata_json, created_at, updated_at
        FROM image_candidates
        WHERE batch_id = ?
        ORDER BY candidate_index ASC
        """
    values: tuple[Any, ...] = (batch_id,)
    if limit is not None:
        query = f"{query} LIMIT ?"
        values = (*values, limit)
    return connection.execute(query, values).fetchall()


def _image_batch_response(row: sqlite3.Row, candidate_rows: list[sqlite3.Row]) -> CanvasImageBatchResponse:
    return CanvasImageBatchResponse(
        id=row["id"],
        canvas_id=row["canvas_id"],
        project_id=row["project_id"],
        source_node_ids=json.loads(row["source_node_ids_json"]),
        prompt_artifact_id=row["prompt_artifact_id"],
        task_id=row["task_id"],
        status=row["status"],
        prompt=row["prompt"],
        params=json.loads(row["params_json"]),
        candidates=[_image_candidate_response(candidate) for candidate in candidate_rows],
        created_at=_dt(row["created_at"]),
        updated_at=_dt(row["updated_at"]),
    )


def _image_candidate_response(row: sqlite3.Row) -> CanvasImageCandidateResponse:
    return CanvasImageCandidateResponse(
        id=row["id"],
        batch_id=row["batch_id"],
        canvas_id=row["canvas_id"],
        asset_id=row["asset_id"],
        task_id=row["task_id"],
        node_id=row["node_id"],
        index=row["candidate_index"],
        prompt=row["prompt"],
        score=row["score"],
        status=row["status"],
        metadata=json.loads(row["metadata_json"]),
        created_at=_dt(row["created_at"]),
        updated_at=_dt(row["updated_at"]),
    )


def _selected_image_node_payload(batch_id: str, candidate_id: str, asset_id: str, prompt: str, score: float | None, metadata: dict[str, Any]) -> dict[str, Any]:
    return {
        "asset_id": asset_id,
        "batch_id": batch_id,
        "candidate_id": candidate_id,
        "role": "selected_image",
        "source": "image_batch_selection",
        "prompt": prompt[:MAX_GENERATED_FINAL_PROMPT_CHARS],
        "score": score,
        "image_url": metadata.get("image_url"),
        "media_type": metadata.get("media_type"),
    }


def _edited_image_node_payload(asset_id: str, source_node_ids: list[str], source_asset_ids: list[str], mask_asset_id: str | None, image_url: str, media_type: str, task_id: str, edit_prompt: str, final_prompt: str, action_type: str) -> dict[str, Any]:
    payload = {
        "asset_id": asset_id,
        "source_node_ids": source_node_ids,
        "source_asset_ids": source_asset_ids,
        "mask_asset_id": mask_asset_id,
        "image_url": image_url,
        "media_type": media_type,
        "role": "edited_image",
        "source": "canvas_image_edit",
        "task_id": task_id,
        "edit_prompt": edit_prompt[:MAX_GENERATED_FINAL_PROMPT_CHARS],
        "final_prompt": final_prompt[:MAX_GENERATED_FINAL_PROMPT_CHARS],
        "action_type": action_type,
    }
    if len(_json(payload).encode("utf-8")) > MAX_GENERATED_NODE_PAYLOAD_BYTES:
        payload = {**payload, "edit_prompt": "", "final_prompt": ""}
    return payload


def _generated_video_node_payload(asset_id: str, source_node_ids: list[str], source_asset_id: str, prompt_artifact_id: str | None, media_type: str, task_id: str, prompt: str) -> dict[str, Any]:
    return {
        "asset_id": asset_id,
        "source_node_ids": source_node_ids,
        "source_asset_id": source_asset_id,
        "prompt_artifact_id": prompt_artifact_id,
        "media_type": media_type,
        "role": "generated_video",
        "source": "canvas_video_generation",
        "task_id": task_id,
        "motion_prompt": prompt[:MAX_GENERATED_FINAL_PROMPT_CHARS],
    }


def _json(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def _branch_operation_payload(payload: dict[str, Any]) -> dict[str, Any]:
    if _payload_depth(payload) > MAX_BRANCH_OPERATION_PAYLOAD_DEPTH:
        return {}
    encoded = _json(payload)
    if len(encoded.encode("utf-8")) > MAX_BRANCH_OPERATION_PAYLOAD_BYTES:
        return {}
    return payload


def _validate_prompt_artifact_payload(payload: dict[str, Any]) -> None:
    if _payload_depth(payload) > MAX_PROMPT_ARTIFACT_DEPTH:
        raise ValueError("Compiled prompt artifact is too deeply nested")
    encoded = _json(payload)
    if len(encoded.encode("utf-8")) > MAX_PROMPT_ARTIFACT_BYTES:
        raise ValueError("Compiled prompt artifact exceeds the size limit")


def _validate_case_index_payload(payload: dict[str, Any], search_terms: list[str]) -> None:
    encoded = _json({"payload": payload, "terms": search_terms[:MAX_CASE_INDEX_TERMS]})
    if len(encoded.encode("utf-8")) > MAX_CASE_INDEX_BYTES:
        raise ValueError("Case memory entry exceeds the size limit")


def _validate_image_candidate_metadata(metadata: dict[str, Any]) -> None:
    if _payload_depth(metadata) > MAX_IMAGE_CANDIDATE_METADATA_DEPTH:
        raise ValueError("Image candidate metadata is too deeply nested")
    if len(_json(metadata).encode("utf-8")) > MAX_IMAGE_CANDIDATE_METADATA_BYTES:
        raise ValueError("Image candidate metadata exceeds the size limit")


def _generated_node_payload(asset_id: str, source_node_ids: list[str], media_type: str, task_id: str, final_prompt: str) -> dict[str, Any]:
    payload = {
        "asset_id": asset_id,
        "source_node_ids": source_node_ids,
        "media_type": media_type,
        "role": "generated_result",
        "task_id": task_id,
        "source": "canvas_generation",
        "final_prompt": final_prompt[:MAX_GENERATED_FINAL_PROMPT_CHARS],
    }
    if len(_json(payload).encode("utf-8")) > MAX_GENERATED_NODE_PAYLOAD_BYTES:
        payload = {**payload, "final_prompt": ""}
    return payload


def _payload_depth(value: Any, depth: int = 0) -> int:
    if isinstance(value, dict):
        if not value:
            return depth + 1
        return max(_payload_depth(item, depth + 1) for item in value.values())
    if isinstance(value, list):
        if not value:
            return depth + 1
        return max(_payload_depth(item, depth + 1) for item in value)
    return depth


def _begin_write(connection: sqlite3.Connection) -> None:
    connection.execute("BEGIN IMMEDIATE")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _dt(value: str) -> datetime:
    return datetime.fromisoformat(value)


def _canvas_response(row: sqlite3.Row) -> CanvasResponse:
    return CanvasResponse(id=row["id"], project_id=row["project_id"], name=row["name"], description=row["description"], created_at=_dt(row["created_at"]), updated_at=_dt(row["updated_at"]))


def _node_response(row: sqlite3.Row) -> CanvasNodeResponse:
    return CanvasNodeResponse(
        id=row["id"],
        canvas_id=row["canvas_id"],
        type=row["type"],
        title=row["title"],
        position=CanvasPosition(**json.loads(row["position_json"])),
        size=CanvasSize(**json.loads(row["size_json"])),
        payload=json.loads(row["payload_json"]),
        created_at=_dt(row["created_at"]),
        updated_at=_dt(row["updated_at"]),
    )


def _branch_operation_summary(connection: sqlite3.Connection, where_clause: str, values: list[Any]) -> BranchOperationSummaryResponse:
    operation_rows = connection.execute(
        f"SELECT bo.operation, COUNT(*) AS count FROM branch_operations bo WHERE {where_clause} GROUP BY bo.operation",
        tuple(values),
    ).fetchall()
    scope_rows = connection.execute(
        f"SELECT bo.scope, COUNT(*) AS count FROM branch_operations bo WHERE {where_clause} GROUP BY bo.scope",
        tuple(values),
    ).fetchall()
    latest_by_type = {}
    for operation in ("materialize", "pin", "unpin", "archive", "restore", "approve", "revoke", "select", "reject", "candidate"):
        row = connection.execute(
            f"""
            SELECT bo.id, bo.canvas_id, bo.operation, bo.reason, bo.scope, bo.target_node_id, bo.affected_node_ids_json, bo.payload_json, bo.owner_id, u.username AS actor_display, bo.created_at
            FROM branch_operations bo
            LEFT JOIN users u ON u.id = bo.owner_id
            WHERE {where_clause} AND bo.operation = ?
            ORDER BY bo.created_at DESC, bo.id DESC
            LIMIT 1
            """,
            (*values, operation),
        ).fetchone()
        latest_by_type[operation] = _branch_operation_response(row) if row else None
    return BranchOperationSummaryResponse(
        operation_counts={row["operation"]: int(row["count"]) for row in operation_rows},
        scope_counts={row["scope"]: int(row["count"]) for row in scope_rows},
        latest_materialize=latest_by_type["materialize"],
        latest_pin=latest_by_type["pin"],
        latest_unpin=latest_by_type["unpin"],
        latest_archive=latest_by_type["archive"],
        latest_restore=latest_by_type["restore"],
        latest_approve=latest_by_type["approve"],
        latest_revoke=latest_by_type["revoke"],
        latest_select=latest_by_type["select"],
        latest_reject=latest_by_type["reject"],
        latest_candidate=latest_by_type["candidate"],
    )


def _branch_operation_response(row: sqlite3.Row) -> BranchOperationResponse:
    return BranchOperationResponse(
        id=row["id"],
        canvas_id=row["canvas_id"],
        operation=row["operation"],
        reason=row["reason"],
        scope=row["scope"],
        target_node_id=row["target_node_id"],
        affected_node_ids=json.loads(row["affected_node_ids_json"]),
        payload=json.loads(row["payload_json"]),
        actor_id=row["owner_id"] if "owner_id" in row.keys() else "",
        actor_display=row["actor_display"] if "actor_display" in row.keys() and row["actor_display"] else "Owner",
        created_at=_dt(row["created_at"]),
    )


def _edge_response(row: sqlite3.Row) -> CanvasEdgeResponse:
    return CanvasEdgeResponse(
        id=row["id"],
        canvas_id=row["canvas_id"],
        source_node_id=row["source_node_id"],
        target_node_id=row["target_node_id"],
        type=row["type"],
        payload=json.loads(row["payload_json"]),
        created_at=_dt(row["created_at"]),
    )


def _artifact_response(row: sqlite3.Row) -> PromptArtifactResponse:
    return PromptArtifactResponse(
        id=row["id"],
        canvas_id=row["canvas_id"],
        node_id=row["node_id"],
        kind=row["kind"],
        payload=json.loads(row["payload_json"]),
        created_at=_dt(row["created_at"]),
    )


def _case_index_response(row: sqlite3.Row) -> dict[str, Any]:
    embedding = json.loads(row["embedding_json"])
    return {
        "id": row["id"],
        "source": row["source"],
        "profile": row["profile"],
        "title": row["title"],
        "visual_dna": json.loads(row["visual_dna_json"]),
        "prompt_spec": json.loads(row["prompt_spec_json"]),
        "quality_score": float(embedding.get("quality_score") or 0),
        "takeaways": embedding.get("takeaways") or [],
        "terms": embedding.get("terms") or [],
    }
