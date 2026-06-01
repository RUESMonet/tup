import json
from datetime import datetime, timedelta, timezone
import sqlite3
from pathlib import Path


class SQLiteDatabase:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.initialize()

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 5000")
        return connection

    def initialize(self) -> None:
        with self.connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS users (
                    id TEXT PRIMARY KEY,
                    username TEXT NOT NULL UNIQUE COLLATE NOCASE,
                    email TEXT NOT NULL UNIQUE COLLATE NOCASE,
                    password_hash TEXT NOT NULL,
                    role TEXT NOT NULL DEFAULT 'user' CHECK (role IN ('user', 'admin')),
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS sessions (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    token_hash TEXT NOT NULL UNIQUE,
                    created_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    revoked_at TEXT
                );

                CREATE TABLE IF NOT EXISTS projects (
                    id TEXT PRIMARY KEY,
                    owner_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    name TEXT NOT NULL,
                    description TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE UNIQUE INDEX IF NOT EXISTS idx_projects_id_owner ON projects(id, owner_id);

                CREATE TABLE IF NOT EXISTS assets (
                    id TEXT PRIMARY KEY,
                    owner_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                    kind TEXT NOT NULL,
                    url TEXT NOT NULL,
                    media_type TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    review_status TEXT NOT NULL DEFAULT 'pending' CHECK (review_status IN ('pending', 'approved', 'rejected')),
                    review_notes TEXT NOT NULL DEFAULT '',
                    reviewed_by TEXT REFERENCES users(id),
                    reviewed_at TEXT,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS generation_tasks (
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
                    refund_of_transaction_id TEXT REFERENCES credit_transactions(id) ON DELETE SET NULL,
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
                    limit_count INTEGER NOT NULL CHECK (limit_count >= 1),
                    updated_at TEXT NOT NULL,
                    UNIQUE(user_id, scope, period_key, action_type)
                );

                CREATE TABLE IF NOT EXISTS image_batches (
                    id TEXT PRIMARY KEY,
                    owner_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                    canvas_id TEXT NOT NULL REFERENCES canvases(id) ON DELETE CASCADE,
                    source_node_ids_json TEXT NOT NULL,
                    prompt_artifact_id TEXT REFERENCES prompt_artifacts(id) ON DELETE SET NULL,
                    task_id TEXT,
                    status TEXT NOT NULL,
                    prompt TEXT NOT NULL,
                    params_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY (canvas_id, owner_id, project_id) REFERENCES canvases(id, owner_id, project_id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS image_candidates (
                    id TEXT PRIMARY KEY,
                    owner_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                    canvas_id TEXT NOT NULL REFERENCES canvases(id) ON DELETE CASCADE,
                    batch_id TEXT NOT NULL REFERENCES image_batches(id) ON DELETE CASCADE,
                    asset_id TEXT NOT NULL REFERENCES assets(id) ON DELETE CASCADE,
                    task_id TEXT,
                    node_id TEXT REFERENCES canvas_nodes(id) ON DELETE SET NULL,
                    candidate_index INTEGER NOT NULL,
                    prompt TEXT NOT NULL,
                    score REAL,
                    status TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE (batch_id, candidate_index),
                    FOREIGN KEY (canvas_id, owner_id, project_id) REFERENCES canvases(id, owner_id, project_id) ON DELETE CASCADE,
                    FOREIGN KEY (node_id, canvas_id) REFERENCES canvas_nodes(id, canvas_id) ON DELETE SET NULL
                );

                CREATE TABLE IF NOT EXISTS image_selections (
                    id TEXT PRIMARY KEY,
                    owner_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                    canvas_id TEXT NOT NULL REFERENCES canvases(id) ON DELETE CASCADE,
                    batch_id TEXT NOT NULL REFERENCES image_batches(id) ON DELETE CASCADE,
                    candidate_id TEXT NOT NULL REFERENCES image_candidates(id) ON DELETE CASCADE,
                    node_id TEXT REFERENCES canvas_nodes(id) ON DELETE SET NULL,
                    selection_reason TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE (batch_id, candidate_id),
                    FOREIGN KEY (canvas_id, owner_id, project_id) REFERENCES canvases(id, owner_id, project_id) ON DELETE CASCADE,
                    FOREIGN KEY (node_id, canvas_id) REFERENCES canvas_nodes(id, canvas_id) ON DELETE SET NULL
                );

                CREATE TABLE IF NOT EXISTS conversations (
                    id TEXT PRIMARY KEY,
                    owner_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                    title TEXT NOT NULL,
                    summary TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS conversation_messages (
                    id TEXT PRIMARY KEY,
                    conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
                    role TEXT NOT NULL CHECK (role IN ('user', 'assistant', 'system')),
                    content TEXT NOT NULL,
                    asset_ids_json TEXT NOT NULL,
                    prompt_snapshot_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS character_sheets (
                    id TEXT PRIMARY KEY,
                    owner_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                    conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
                    name TEXT NOT NULL,
                    identity_anchors_json TEXT NOT NULL,
                    visual_traits_json TEXT NOT NULL,
                    locked_prompt_text TEXT NOT NULL,
                    source_asset_ids_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS canvases (
                    id TEXT PRIMARY KEY,
                    owner_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                    name TEXT NOT NULL,
                    description TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE (id, owner_id, project_id),
                    FOREIGN KEY (project_id, owner_id) REFERENCES projects(id, owner_id) ON DELETE CASCADE
                );

                CREATE UNIQUE INDEX IF NOT EXISTS idx_canvases_id_owner_project ON canvases(id, owner_id, project_id);

                CREATE TABLE IF NOT EXISTS canvas_nodes (
                    id TEXT PRIMARY KEY,
                    canvas_id TEXT NOT NULL REFERENCES canvases(id) ON DELETE CASCADE,
                    type TEXT NOT NULL,
                    title TEXT NOT NULL,
                    position_json TEXT NOT NULL,
                    size_json TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE (id, canvas_id)
                );

                CREATE UNIQUE INDEX IF NOT EXISTS idx_canvas_nodes_id_canvas ON canvas_nodes(id, canvas_id);

                CREATE TABLE IF NOT EXISTS canvas_edges (
                    id TEXT PRIMARY KEY,
                    canvas_id TEXT NOT NULL REFERENCES canvases(id) ON DELETE CASCADE,
                    source_node_id TEXT NOT NULL REFERENCES canvas_nodes(id) ON DELETE CASCADE,
                    target_node_id TEXT NOT NULL REFERENCES canvas_nodes(id) ON DELETE CASCADE,
                    type TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (source_node_id, canvas_id) REFERENCES canvas_nodes(id, canvas_id) ON DELETE CASCADE,
                    FOREIGN KEY (target_node_id, canvas_id) REFERENCES canvas_nodes(id, canvas_id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS branch_operations (
                    id TEXT PRIMARY KEY,
                    owner_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                    canvas_id TEXT NOT NULL REFERENCES canvases(id) ON DELETE CASCADE,
                    operation TEXT NOT NULL,
                    reason TEXT NOT NULL DEFAULT '',
                    scope TEXT NOT NULL DEFAULT 'single',
                    target_node_id TEXT REFERENCES canvas_nodes(id) ON DELETE SET NULL,
                    affected_node_ids_json TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (canvas_id, owner_id, project_id) REFERENCES canvases(id, owner_id, project_id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS prompt_artifacts (
                    id TEXT PRIMARY KEY,
                    owner_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                    canvas_id TEXT NOT NULL REFERENCES canvases(id) ON DELETE CASCADE,
                    node_id TEXT REFERENCES canvas_nodes(id) ON DELETE CASCADE,
                    kind TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (canvas_id, owner_id, project_id) REFERENCES canvases(id, owner_id, project_id) ON DELETE CASCADE,
                    FOREIGN KEY (node_id, canvas_id) REFERENCES canvas_nodes(id, canvas_id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS case_index_entries (
                    id TEXT PRIMARY KEY,
                    owner_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                    source TEXT NOT NULL,
                    profile TEXT NOT NULL,
                    title TEXT NOT NULL,
                    visual_dna_json TEXT NOT NULL,
                    prompt_spec_json TEXT NOT NULL,
                    embedding_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (project_id, owner_id) REFERENCES projects(id, owner_id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS model_settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    updated_by TEXT REFERENCES users(id)
                );
                """
            )
            _add_column_if_missing(connection, "users", "role", "TEXT NOT NULL DEFAULT 'user'")
            _add_column_if_missing(connection, "sessions", "expires_at", "TEXT")
            _add_column_if_missing(connection, "assets", "review_status", "TEXT NOT NULL DEFAULT 'pending' CHECK (review_status IN ('pending', 'approved', 'rejected'))")
            _add_column_if_missing(connection, "assets", "review_notes", "TEXT NOT NULL DEFAULT ''")
            _add_column_if_missing(connection, "assets", "reviewed_by", "TEXT REFERENCES users(id)")
            _add_column_if_missing(connection, "assets", "reviewed_at", "TEXT")
            _add_column_if_missing(connection, "generation_tasks", "cost_estimate", "INTEGER NOT NULL DEFAULT 0")
            _add_column_if_missing(connection, "generation_tasks", "charged_credits", "INTEGER NOT NULL DEFAULT 0")
            _add_column_if_missing(connection, "credit_transactions", "refund_of_transaction_id", "TEXT REFERENCES credit_transactions(id) ON DELETE SET NULL")
            _dedupe_credit_transaction_refunds(connection)
            connection.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_projects_id_owner ON projects(id, owner_id)")
            connection.execute("CREATE INDEX IF NOT EXISTS idx_assets_review_status_created_at ON assets(review_status, created_at)")
            connection.execute("CREATE INDEX IF NOT EXISTS idx_generation_tasks_status_kind_updated_at ON generation_tasks(status, kind, updated_at)")
            connection.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_credit_transactions_unique_refund ON credit_transactions(user_id, refund_of_transaction_id) WHERE refund_of_transaction_id IS NOT NULL")
            _install_canvas_owner_triggers(connection)
            _install_project_owner_scope_triggers(connection)
            connection.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_canvases_id_owner_project ON canvases(id, owner_id, project_id)")
            connection.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_canvas_nodes_id_canvas ON canvas_nodes(id, canvas_id)")
            _migrate_canvas_constraints(connection)
            _delete_legacy_secret_model_settings(connection)
            _dedupe_character_sheets(connection)
            connection.execute(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS idx_character_sheets_owner_conversation_name
                ON character_sheets(owner_id, conversation_id, name)
                """
            )
            connection.execute("CREATE INDEX IF NOT EXISTS idx_canvases_owner_project ON canvases(owner_id, project_id)")
            connection.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_canvases_id_owner_project ON canvases(id, owner_id, project_id)")
            connection.execute("CREATE INDEX IF NOT EXISTS idx_canvas_nodes_canvas ON canvas_nodes(canvas_id)")
            connection.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_canvas_nodes_id_canvas ON canvas_nodes(id, canvas_id)")
            connection.execute("CREATE INDEX IF NOT EXISTS idx_canvas_edges_canvas ON canvas_edges(canvas_id)")
            connection.execute("CREATE INDEX IF NOT EXISTS idx_branch_operations_canvas_created ON branch_operations(canvas_id, created_at)")
            connection.execute("CREATE INDEX IF NOT EXISTS idx_branch_operations_canvas_created_id ON branch_operations(canvas_id, created_at, id)")
            connection.execute("CREATE INDEX IF NOT EXISTS idx_branch_operations_canvas_target_created ON branch_operations(canvas_id, target_node_id, created_at, id)")
            connection.execute("CREATE INDEX IF NOT EXISTS idx_branch_operations_canvas_operation_scope_created ON branch_operations(canvas_id, operation, scope, created_at, id)")
            connection.execute("CREATE INDEX IF NOT EXISTS idx_branch_operations_canvas_operation_created_id ON branch_operations(canvas_id, operation, created_at, id)")
            connection.execute("CREATE INDEX IF NOT EXISTS idx_branch_operations_canvas_scope_created_id ON branch_operations(canvas_id, scope, created_at, id)")
            connection.execute("CREATE INDEX IF NOT EXISTS idx_image_batches_owner_canvas ON image_batches(owner_id, canvas_id)")
            connection.execute("CREATE INDEX IF NOT EXISTS idx_image_candidates_batch ON image_candidates(batch_id)")
            connection.execute("CREATE INDEX IF NOT EXISTS idx_image_candidates_asset ON image_candidates(asset_id)")
            connection.execute("CREATE INDEX IF NOT EXISTS idx_image_selections_batch ON image_selections(batch_id)")
            _install_image_lineage_triggers(connection)


def _install_canvas_owner_triggers(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        DELETE FROM canvases
        WHERE NOT EXISTS (
            SELECT 1 FROM projects
            WHERE projects.id = canvases.project_id AND projects.owner_id = canvases.owner_id
        )
        """
    )
    connection.executescript(
        """
        CREATE TRIGGER IF NOT EXISTS trg_canvases_project_owner_insert
        BEFORE INSERT ON canvases
        WHEN NOT EXISTS (SELECT 1 FROM projects WHERE id = NEW.project_id AND owner_id = NEW.owner_id)
        BEGIN
            SELECT RAISE(ABORT, 'Canvas project owner mismatch');
        END;
        CREATE TRIGGER IF NOT EXISTS trg_canvases_project_owner_update
        BEFORE UPDATE OF owner_id, project_id ON canvases
        WHEN NOT EXISTS (SELECT 1 FROM projects WHERE id = NEW.project_id AND owner_id = NEW.owner_id)
        BEGIN
            SELECT RAISE(ABORT, 'Canvas project owner mismatch');
        END;
        """
    )


def _install_project_owner_scope_triggers(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        DELETE FROM assets
        WHERE NOT EXISTS (
            SELECT 1 FROM projects
            WHERE projects.id = assets.project_id AND projects.owner_id = assets.owner_id
        )
        """
    )
    connection.execute(
        """
        DELETE FROM generation_tasks
        WHERE NOT EXISTS (
            SELECT 1 FROM projects
            WHERE projects.id = generation_tasks.project_id AND projects.owner_id = generation_tasks.owner_id
        )
        """
    )
    connection.executescript(
        """
        CREATE TRIGGER IF NOT EXISTS trg_assets_project_owner_insert
        BEFORE INSERT ON assets
        WHEN NOT EXISTS (SELECT 1 FROM projects WHERE id = NEW.project_id AND owner_id = NEW.owner_id)
        BEGIN
            SELECT RAISE(ABORT, 'Asset project owner mismatch');
        END;
        CREATE TRIGGER IF NOT EXISTS trg_assets_project_owner_update
        BEFORE UPDATE OF owner_id, project_id ON assets
        WHEN NOT EXISTS (SELECT 1 FROM projects WHERE id = NEW.project_id AND owner_id = NEW.owner_id)
        BEGIN
            SELECT RAISE(ABORT, 'Asset project owner mismatch');
        END;
        CREATE TRIGGER IF NOT EXISTS trg_generation_tasks_project_owner_insert
        BEFORE INSERT ON generation_tasks
        WHEN NOT EXISTS (SELECT 1 FROM projects WHERE id = NEW.project_id AND owner_id = NEW.owner_id)
        BEGIN
            SELECT RAISE(ABORT, 'Task project owner mismatch');
        END;
        CREATE TRIGGER IF NOT EXISTS trg_generation_tasks_project_owner_update
        BEFORE UPDATE OF owner_id, project_id ON generation_tasks
        WHEN NOT EXISTS (SELECT 1 FROM projects WHERE id = NEW.project_id AND owner_id = NEW.owner_id)
        BEGIN
            SELECT RAISE(ABORT, 'Task project owner mismatch');
        END;
        """
    )


def _install_image_lineage_triggers(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        DELETE FROM image_selections
        WHERE NOT EXISTS (
            SELECT 1 FROM image_candidates
            WHERE image_candidates.id = image_selections.candidate_id
              AND image_candidates.batch_id = image_selections.batch_id
              AND image_candidates.owner_id = image_selections.owner_id
              AND image_candidates.project_id = image_selections.project_id
              AND image_candidates.canvas_id = image_selections.canvas_id
        );
        DELETE FROM image_candidates
        WHERE NOT EXISTS (
            SELECT 1 FROM image_batches
            WHERE image_batches.id = image_candidates.batch_id
              AND image_batches.owner_id = image_candidates.owner_id
              AND image_batches.project_id = image_candidates.project_id
              AND image_batches.canvas_id = image_candidates.canvas_id
        ) OR NOT EXISTS (
            SELECT 1 FROM assets
            WHERE assets.id = image_candidates.asset_id
              AND assets.owner_id = image_candidates.owner_id
              AND assets.project_id = image_candidates.project_id
              AND assets.kind = 'image'
        );
        DELETE FROM image_batches
        WHERE NOT EXISTS (
            SELECT 1 FROM canvases
            WHERE canvases.id = image_batches.canvas_id
              AND canvases.owner_id = image_batches.owner_id
              AND canvases.project_id = image_batches.project_id
        );
        CREATE TRIGGER IF NOT EXISTS trg_image_batches_canvas_scope_insert
        BEFORE INSERT ON image_batches
        WHEN NOT EXISTS (SELECT 1 FROM canvases WHERE id = NEW.canvas_id AND owner_id = NEW.owner_id AND project_id = NEW.project_id)
        BEGIN
            SELECT RAISE(ABORT, 'Image batch canvas scope mismatch');
        END;
        CREATE TRIGGER IF NOT EXISTS trg_image_batches_canvas_scope_update
        BEFORE UPDATE OF owner_id, project_id, canvas_id ON image_batches
        WHEN NOT EXISTS (SELECT 1 FROM canvases WHERE id = NEW.canvas_id AND owner_id = NEW.owner_id AND project_id = NEW.project_id)
        BEGIN
            SELECT RAISE(ABORT, 'Image batch canvas scope mismatch');
        END;
        CREATE TRIGGER IF NOT EXISTS trg_image_candidates_batch_scope_insert
        BEFORE INSERT ON image_candidates
        WHEN NOT EXISTS (SELECT 1 FROM image_batches WHERE id = NEW.batch_id AND owner_id = NEW.owner_id AND project_id = NEW.project_id AND canvas_id = NEW.canvas_id)
        BEGIN
            SELECT RAISE(ABORT, 'Image candidate batch scope mismatch');
        END;
        CREATE TRIGGER IF NOT EXISTS trg_image_candidates_batch_scope_update
        BEFORE UPDATE OF owner_id, project_id, canvas_id, batch_id ON image_candidates
        WHEN NOT EXISTS (SELECT 1 FROM image_batches WHERE id = NEW.batch_id AND owner_id = NEW.owner_id AND project_id = NEW.project_id AND canvas_id = NEW.canvas_id)
        BEGIN
            SELECT RAISE(ABORT, 'Image candidate batch scope mismatch');
        END;
        CREATE TRIGGER IF NOT EXISTS trg_image_candidates_asset_scope_insert
        BEFORE INSERT ON image_candidates
        WHEN NOT EXISTS (SELECT 1 FROM assets WHERE id = NEW.asset_id AND owner_id = NEW.owner_id AND project_id = NEW.project_id AND kind = 'image')
        BEGIN
            SELECT RAISE(ABORT, 'Image candidate asset scope mismatch');
        END;
        CREATE TRIGGER IF NOT EXISTS trg_image_candidates_asset_scope_update
        BEFORE UPDATE OF owner_id, project_id, asset_id ON image_candidates
        WHEN NOT EXISTS (SELECT 1 FROM assets WHERE id = NEW.asset_id AND owner_id = NEW.owner_id AND project_id = NEW.project_id AND kind = 'image')
        BEGIN
            SELECT RAISE(ABORT, 'Image candidate asset scope mismatch');
        END;
        CREATE TRIGGER IF NOT EXISTS trg_image_selections_scope_insert
        BEFORE INSERT ON image_selections
        WHEN NOT EXISTS (SELECT 1 FROM image_candidates WHERE id = NEW.candidate_id AND batch_id = NEW.batch_id AND owner_id = NEW.owner_id AND project_id = NEW.project_id AND canvas_id = NEW.canvas_id)
        BEGIN
            SELECT RAISE(ABORT, 'Image selection candidate scope mismatch');
        END;
        CREATE TRIGGER IF NOT EXISTS trg_image_selections_scope_update
        BEFORE UPDATE OF owner_id, project_id, canvas_id, batch_id, candidate_id ON image_selections
        WHEN NOT EXISTS (SELECT 1 FROM image_candidates WHERE id = NEW.candidate_id AND batch_id = NEW.batch_id AND owner_id = NEW.owner_id AND project_id = NEW.project_id AND canvas_id = NEW.canvas_id)
        BEGIN
            SELECT RAISE(ABORT, 'Image selection candidate scope mismatch');
        END;
        """
    )


def _migrate_canvas_constraints(connection: sqlite3.Connection) -> None:
    if _table_sql(connection, "canvas_edges") and "FOREIGN KEY (source_node_id, canvas_id)" not in _table_sql(connection, "canvas_edges"):
        _rebuild_canvas_edges(connection)
    prompt_artifacts_sql = _table_sql(connection, "prompt_artifacts")
    if prompt_artifacts_sql and "FOREIGN KEY (canvas_id, owner_id, project_id)" not in prompt_artifacts_sql:
        _rebuild_prompt_artifacts(connection)
    case_index_sql = _table_sql(connection, "case_index_entries")
    if case_index_sql and "FOREIGN KEY (project_id, owner_id)" not in case_index_sql:
        _rebuild_case_index_entries(connection)


def _table_sql(connection: sqlite3.Connection, table: str) -> str:
    row = connection.execute("SELECT sql FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)).fetchone()
    return str(row["sql"] or "") if row else ""


def _rebuild_canvas_edges(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE canvas_edges_new (
            id TEXT PRIMARY KEY,
            canvas_id TEXT NOT NULL REFERENCES canvases(id) ON DELETE CASCADE,
            source_node_id TEXT NOT NULL REFERENCES canvas_nodes(id) ON DELETE CASCADE,
            target_node_id TEXT NOT NULL REFERENCES canvas_nodes(id) ON DELETE CASCADE,
            type TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY (source_node_id, canvas_id) REFERENCES canvas_nodes(id, canvas_id) ON DELETE CASCADE,
            FOREIGN KEY (target_node_id, canvas_id) REFERENCES canvas_nodes(id, canvas_id) ON DELETE CASCADE
        );
        INSERT INTO canvas_edges_new (id, canvas_id, source_node_id, target_node_id, type, payload_json, created_at)
        SELECT e.id, e.canvas_id, e.source_node_id, e.target_node_id, e.type, e.payload_json, e.created_at
        FROM canvas_edges e
        JOIN canvas_nodes source ON source.id = e.source_node_id AND source.canvas_id = e.canvas_id
        JOIN canvas_nodes target ON target.id = e.target_node_id AND target.canvas_id = e.canvas_id;
        DROP TABLE canvas_edges;
        ALTER TABLE canvas_edges_new RENAME TO canvas_edges;
        """
    )


def _rebuild_prompt_artifacts(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE prompt_artifacts_new (
            id TEXT PRIMARY KEY,
            owner_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            canvas_id TEXT NOT NULL REFERENCES canvases(id) ON DELETE CASCADE,
            node_id TEXT REFERENCES canvas_nodes(id) ON DELETE CASCADE,
            kind TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY (canvas_id, owner_id, project_id) REFERENCES canvases(id, owner_id, project_id) ON DELETE CASCADE,
            FOREIGN KEY (node_id, canvas_id) REFERENCES canvas_nodes(id, canvas_id) ON DELETE CASCADE
        );
        INSERT INTO prompt_artifacts_new (id, owner_id, project_id, canvas_id, node_id, kind, payload_json, created_at)
        SELECT a.id, a.owner_id, a.project_id, a.canvas_id, a.node_id, a.kind, a.payload_json, a.created_at
        FROM prompt_artifacts a
        JOIN canvases c ON c.id = a.canvas_id AND c.owner_id = a.owner_id AND c.project_id = a.project_id
        LEFT JOIN canvas_nodes n ON n.id = a.node_id AND n.canvas_id = a.canvas_id
        WHERE a.canvas_id IS NOT NULL AND (a.node_id IS NULL OR n.id IS NOT NULL);
        DROP TABLE prompt_artifacts;
        ALTER TABLE prompt_artifacts_new RENAME TO prompt_artifacts;
        """
    )


def _rebuild_case_index_entries(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE case_index_entries_new (
            id TEXT PRIMARY KEY,
            owner_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            source TEXT NOT NULL,
            profile TEXT NOT NULL,
            title TEXT NOT NULL,
            visual_dna_json TEXT NOT NULL,
            prompt_spec_json TEXT NOT NULL,
            embedding_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY (project_id, owner_id) REFERENCES projects(id, owner_id) ON DELETE CASCADE
        );
        INSERT INTO case_index_entries_new (id, owner_id, project_id, source, profile, title, visual_dna_json, prompt_spec_json, embedding_json, created_at)
        SELECT e.id, e.owner_id, e.project_id, e.source, e.profile, e.title, e.visual_dna_json, e.prompt_spec_json, e.embedding_json, e.created_at
        FROM case_index_entries e
        JOIN projects p ON p.id = e.project_id AND p.owner_id = e.owner_id;
        DROP TABLE case_index_entries;
        ALTER TABLE case_index_entries_new RENAME TO case_index_entries;
        """
    )


def _delete_legacy_secret_model_settings(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        DELETE FROM model_settings
        WHERE key IN ('OPENAI_API_KEY', 'OPENAI_IMAGE_API_KEY', 'OPENAI_EVALUATOR_API_KEY', 'VIDEO_API_KEY')
        """
    )


def _dedupe_character_sheets(connection: sqlite3.Connection) -> None:
    groups = connection.execute(
        """
        SELECT owner_id, conversation_id, name
        FROM character_sheets
        GROUP BY owner_id, conversation_id, name
        HAVING COUNT(*) > 1
        """
    ).fetchall()
    for group in groups:
        rows = connection.execute(
            """
            SELECT id, identity_anchors_json, visual_traits_json, locked_prompt_text, source_asset_ids_json, created_at, updated_at
            FROM character_sheets
            WHERE owner_id = ? AND conversation_id = ? AND name = ?
            ORDER BY updated_at DESC
            """,
            (group["owner_id"], group["conversation_id"], group["name"]),
        ).fetchall()
        if len(rows) < 2:
            continue
        keep = rows[0]
        anchors: list[str] = []
        traits: dict[str, object] = {}
        sources: list[str] = []
        locked = ""
        for row in reversed(rows):
            anchors.extend(str(item) for item in _json_list(row["identity_anchors_json"]))
            loaded_traits = _json_dict(row["visual_traits_json"])
            traits = {**traits, **loaded_traits}
            sources.extend(str(item) for item in _json_list(row["source_asset_ids_json"]))
            locked = row["locked_prompt_text"] or locked
        duplicate_ids = [row["id"] for row in rows[1:]]
        connection.executemany("DELETE FROM character_sheets WHERE id = ?", [(item,) for item in duplicate_ids])
        connection.execute(
            """
            UPDATE character_sheets
            SET identity_anchors_json = ?, visual_traits_json = ?, locked_prompt_text = ?, source_asset_ids_json = ?, updated_at = ?
            WHERE id = ?
            """,
            (
                json.dumps(list(dict.fromkeys(anchors)), ensure_ascii=False, separators=(",", ":")),
                json.dumps(traits, ensure_ascii=False, separators=(",", ":")),
                locked,
                json.dumps(list(dict.fromkeys(sources)), ensure_ascii=False, separators=(",", ":")),
                keep["updated_at"],
                keep["id"],
            ),
        )


def _dedupe_credit_transaction_refunds(connection: sqlite3.Connection) -> None:
    columns = {row["name"] for row in connection.execute("PRAGMA table_info(credit_transactions)")}
    if "refund_of_transaction_id" not in columns:
        return
    groups = connection.execute(
        """
        SELECT user_id, refund_of_transaction_id
        FROM credit_transactions
        WHERE refund_of_transaction_id IS NOT NULL AND direction = 'credit'
        GROUP BY user_id, refund_of_transaction_id
        HAVING COUNT(*) > 1
        """
    ).fetchall()
    for group in groups:
        rows = connection.execute(
            """
            SELECT id, amount, created_at
            FROM credit_transactions
            WHERE user_id = ? AND refund_of_transaction_id = ? AND direction = 'credit'
            ORDER BY created_at ASC, id ASC
            """
            ,
            (group["user_id"], group["refund_of_transaction_id"]),
        ).fetchall()
        if len(rows) < 2:
            continue
        duplicate_rows = rows[1:]
        duplicate_total = sum(int(row["amount"]) for row in duplicate_rows)
        connection.executemany("DELETE FROM credit_transactions WHERE id = ?", [(row["id"],) for row in duplicate_rows])
        connection.execute(
            """
            UPDATE credit_accounts
            SET balance = CASE WHEN balance >= ? THEN balance - ? ELSE 0 END
            WHERE user_id = ?
            """,
            (duplicate_total, duplicate_total, group["user_id"]),
        )
    connection.execute(
        """
        UPDATE credit_transactions
        SET status = 'refunded'
        WHERE direction = 'debit'
          AND id IN (
              SELECT DISTINCT refund_of_transaction_id
              FROM credit_transactions
              WHERE refund_of_transaction_id IS NOT NULL AND direction = 'credit'
          )
        """
    )


def _json_list(value: str) -> list[object]:
    payload = json.loads(value or "[]")
    return payload if isinstance(payload, list) else []


def _json_dict(value: str) -> dict[str, object]:
    payload = json.loads(value or "{}")
    return payload if isinstance(payload, dict) else {}


def _add_column_if_missing(connection: sqlite3.Connection, table: str, column: str, definition: str) -> None:
    columns = {row["name"] for row in connection.execute(f"PRAGMA table_info({table})")}
    if column not in columns:
        connection.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
    if table == "sessions" and column == "expires_at":
        expires_at = (datetime.now(timezone.utc) + timedelta(days=7)).isoformat()
        connection.execute("UPDATE sessions SET expires_at = ? WHERE expires_at IS NULL", (expires_at,))
