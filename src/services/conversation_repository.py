import json
from datetime import datetime, timezone
from typing import Any, Literal
from uuid import uuid4

from src.models.conversation import CharacterSheetResponse, ConversationDetailResponse, ConversationMessageResponse, ConversationResponse
from src.services.database import SQLiteDatabase


class ConversationRepository:
    def __init__(self, database: SQLiteDatabase):
        self.database = database

    def create_conversation(self, owner_id: str, project_id: str, title: str, summary: str = "") -> ConversationResponse:
        conversation_id = str(uuid4())
        now = _utc_now()
        with self.database.connect() as connection:
            connection.execute(
                """
                INSERT INTO conversations (id, owner_id, project_id, title, summary, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (conversation_id, owner_id, project_id, title or "Untitled conversation", summary, now, now),
            )
        conversation = self.get_conversation(owner_id, conversation_id)
        if conversation is None:
            raise RuntimeError("failed to create conversation")
        return conversation

    def list_conversations(self, owner_id: str, project_id: str) -> list[ConversationResponse]:
        with self.database.connect() as connection:
            rows = connection.execute(
                """
                SELECT id, project_id, title, summary, created_at, updated_at
                FROM conversations
                WHERE owner_id = ? AND project_id = ?
                ORDER BY updated_at DESC
                """,
                (owner_id, project_id),
            ).fetchall()
        return [_conversation_response(row) for row in rows]

    def get_conversation(self, owner_id: str, conversation_id: str) -> ConversationResponse | None:
        with self.database.connect() as connection:
            row = connection.execute(
                """
                SELECT id, project_id, title, summary, created_at, updated_at
                FROM conversations
                WHERE owner_id = ? AND id = ?
                """,
                (owner_id, conversation_id),
            ).fetchone()
        return _conversation_response(row) if row else None

    def conversation_detail(self, owner_id: str, conversation_id: str) -> ConversationDetailResponse | None:
        conversation = self.get_conversation(owner_id, conversation_id)
        if conversation is None:
            return None
        return ConversationDetailResponse(
            **conversation.model_dump(),
            messages=self.list_messages(owner_id, conversation_id),
            character_sheets=self.list_character_sheets(owner_id, conversation_id),
        )

    def add_message(
        self,
        owner_id: str,
        conversation_id: str,
        role: Literal["user", "assistant", "system"],
        content: str,
        asset_ids: list[str] | None = None,
        prompt_snapshot: dict[str, Any] | None = None,
    ) -> ConversationMessageResponse | None:
        conversation = self.get_conversation(owner_id, conversation_id)
        if conversation is None:
            return None
        message_id = str(uuid4())
        now = _utc_now()
        with self.database.connect() as connection:
            connection.execute(
                """
                INSERT INTO conversation_messages (id, conversation_id, role, content, asset_ids_json, prompt_snapshot_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (message_id, conversation_id, role, content, _json(asset_ids or []), _json(prompt_snapshot or {}), now),
            )
            connection.execute("UPDATE conversations SET updated_at = ? WHERE id = ?", (now, conversation_id))
        return self.get_message(owner_id, message_id)

    def get_message(self, owner_id: str, message_id: str) -> ConversationMessageResponse | None:
        with self.database.connect() as connection:
            row = connection.execute(
                """
                SELECT m.id, m.conversation_id, m.role, m.content, m.asset_ids_json, m.prompt_snapshot_json, m.created_at
                FROM conversation_messages m
                JOIN conversations c ON c.id = m.conversation_id
                WHERE c.owner_id = ? AND m.id = ?
                """,
                (owner_id, message_id),
            ).fetchone()
        return _message_response(row) if row else None

    def list_messages(self, owner_id: str, conversation_id: str, limit: int | None = None) -> list[ConversationMessageResponse]:
        query = """
            SELECT m.id, m.conversation_id, m.role, m.content, m.asset_ids_json, m.prompt_snapshot_json, m.created_at
            FROM conversation_messages m
            JOIN conversations c ON c.id = m.conversation_id
            WHERE c.owner_id = ? AND m.conversation_id = ?
            ORDER BY m.created_at ASC
        """
        params: tuple[Any, ...] = (owner_id, conversation_id)
        if limit is not None:
            query += " LIMIT ?"
            params = (owner_id, conversation_id, limit)
        with self.database.connect() as connection:
            rows = connection.execute(query, params).fetchall()
        return [_message_response(row) for row in rows]

    def upsert_character_sheet(
        self,
        owner_id: str,
        project_id: str,
        conversation_id: str,
        name: str,
        identity_anchors: list[str],
        visual_traits: dict[str, Any],
        locked_prompt_text: str,
        source_asset_ids: list[str] | None = None,
    ) -> CharacterSheetResponse:
        now = _utc_now()
        with self.database.connect() as connection:
            row = connection.execute(
                """
                SELECT id, project_id, conversation_id, name, identity_anchors_json, visual_traits_json, locked_prompt_text, source_asset_ids_json, created_at, updated_at
                FROM character_sheets
                WHERE owner_id = ? AND conversation_id = ? AND name = ?
                """,
                (owner_id, conversation_id, name),
            ).fetchone()
            existing = _character_sheet_response(row) if row else None
            anchors = list(dict.fromkeys([*(existing.identity_anchors if existing else []), *identity_anchors]))
            traits = {**(existing.visual_traits if existing else {}), **visual_traits}
            locked = locked_prompt_text or (existing.locked_prompt_text if existing else "")
            sources = source_asset_ids or (existing.source_asset_ids if existing else [])
            sheet_id = existing.id if existing else str(uuid4())
            created_at = existing.created_at.isoformat() if existing else now
            connection.execute(
                """
                INSERT INTO character_sheets (id, owner_id, project_id, conversation_id, name, identity_anchors_json, visual_traits_json, locked_prompt_text, source_asset_ids_json, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(owner_id, conversation_id, name) DO UPDATE SET
                    identity_anchors_json = excluded.identity_anchors_json,
                    visual_traits_json = excluded.visual_traits_json,
                    locked_prompt_text = excluded.locked_prompt_text,
                    source_asset_ids_json = excluded.source_asset_ids_json,
                    updated_at = excluded.updated_at
                """,
                (sheet_id, owner_id, project_id, conversation_id, name, _json(anchors), _json(traits), locked, _json(sources), created_at, now),
            )
        return self.list_character_sheets(owner_id, conversation_id)[0]

    def list_character_sheets(self, owner_id: str, conversation_id: str) -> list[CharacterSheetResponse]:
        with self.database.connect() as connection:
            rows = connection.execute(
                """
                SELECT id, project_id, conversation_id, name, identity_anchors_json, visual_traits_json, locked_prompt_text, source_asset_ids_json, created_at, updated_at
                FROM character_sheets
                WHERE owner_id = ? AND conversation_id = ?
                ORDER BY updated_at DESC
                """,
                (owner_id, conversation_id),
            ).fetchall()
        return [_character_sheet_response(row) for row in rows]


def _json(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _dt(value: str) -> datetime:
    return datetime.fromisoformat(value)


def _conversation_response(row) -> ConversationResponse:
    return ConversationResponse(id=row["id"], project_id=row["project_id"], title=row["title"], summary=row["summary"], created_at=_dt(row["created_at"]), updated_at=_dt(row["updated_at"]))


def _message_response(row) -> ConversationMessageResponse:
    return ConversationMessageResponse(
        id=row["id"],
        conversation_id=row["conversation_id"],
        role=row["role"],
        content=row["content"],
        asset_ids=json.loads(row["asset_ids_json"]),
        prompt_snapshot=json.loads(row["prompt_snapshot_json"]),
        created_at=_dt(row["created_at"]),
    )


def _character_sheet_response(row) -> CharacterSheetResponse:
    return CharacterSheetResponse(
        id=row["id"],
        project_id=row["project_id"],
        conversation_id=row["conversation_id"],
        name=row["name"],
        identity_anchors=json.loads(row["identity_anchors_json"]),
        visual_traits=json.loads(row["visual_traits_json"]),
        locked_prompt_text=row["locked_prompt_text"],
        source_asset_ids=json.loads(row["source_asset_ids_json"]),
        created_at=_dt(row["created_at"]),
        updated_at=_dt(row["updated_at"]),
    )
