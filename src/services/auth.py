from datetime import datetime, timedelta, timezone
from hashlib import pbkdf2_hmac, sha256
from hmac import compare_digest
import secrets
import sqlite3
from uuid import uuid4

from src.models.auth import AuthUser, RegisterRequest
from src.services.database import SQLiteDatabase


_PASSWORD_ITERATIONS = 210_000


class DuplicateAccountError(ValueError):
    pass


class InvalidCredentialsError(ValueError):
    pass


class AuthService:
    def __init__(self, database: SQLiteDatabase, session_max_age_seconds: int):
        self.database = database
        self.session_max_age_seconds = session_max_age_seconds

    def register(self, request: RegisterRequest) -> tuple[AuthUser, str]:
        user_id = str(uuid4())
        created_at = _utc_now()
        password_hash = _hash_password(request.password)
        try:
            with self.database.connect() as connection:
                connection.execute(
                    """
                    INSERT INTO users (id, username, email, password_hash, role, created_at)
                    VALUES (?, ?, ?, ?, 'user', ?)
                    """,
                    (user_id, request.username, request.email, password_hash, created_at),
                )
        except sqlite3.IntegrityError as exc:
            raise DuplicateAccountError("Username or email already exists") from exc

        user = AuthUser(id=user_id, username=request.username, email=request.email, role="user", created_at=datetime.fromisoformat(created_at))
        token = self.create_session(user_id)
        return user, token

    def login(self, username: str, password: str) -> tuple[AuthUser, str]:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT id, username, email, password_hash, role, created_at FROM users WHERE username = ? COLLATE NOCASE OR email = ? COLLATE NOCASE",
                (username, username),
            ).fetchone()
        if row is None or not _verify_password(password, row["password_hash"]):
            raise InvalidCredentialsError("Invalid username or password")

        token = self.create_session(row["id"])
        return _user_from_row(row), token

    def create_session(self, user_id: str) -> str:
        token = secrets.token_urlsafe(32)
        now = _utc_now()
        expires_at = (datetime.now(timezone.utc) + timedelta(seconds=self.session_max_age_seconds)).isoformat()
        with self.database.connect() as connection:
            connection.execute(
                """
                INSERT INTO sessions (id, user_id, token_hash, created_at, expires_at, revoked_at)
                VALUES (?, ?, ?, ?, ?, NULL)
                """,
                (str(uuid4()), user_id, _hash_token(token), now, expires_at),
            )
        return token

    def current_user(self, token: str) -> AuthUser | None:
        with self.database.connect() as connection:
            row = connection.execute(
                """
                SELECT users.id, users.username, users.email, users.role, users.created_at
                FROM sessions
                JOIN users ON users.id = sessions.user_id
                WHERE sessions.token_hash = ? AND sessions.revoked_at IS NULL AND sessions.expires_at > ?
                """,
                (_hash_token(token), _utc_now()),
            ).fetchone()
        return _user_from_row(row) if row else None

    def logout(self, token: str) -> None:
        with self.database.connect() as connection:
            connection.execute(
                "UPDATE sessions SET revoked_at = ? WHERE token_hash = ? AND revoked_at IS NULL",
                (_utc_now(), _hash_token(token)),
            )

    def ensure_bootstrap_admin(self, username: str, email: str, password: str) -> AuthUser | None:
        now = _utc_now()
        password_hash = _hash_password(password)
        with self.database.connect() as connection:
            existing_admin = connection.execute("SELECT id, username, email, role, created_at FROM users WHERE role = 'admin' LIMIT 1").fetchone()
            if existing_admin is not None:
                return _user_from_row(existing_admin)
            existing_user = connection.execute(
                "SELECT id FROM users WHERE username = ? COLLATE NOCASE OR email = ? COLLATE NOCASE",
                (username, email),
            ).fetchone()
            if existing_user is not None:
                raise ValueError("Bootstrap admin username or email already belongs to a non-admin user")
            user_id = str(uuid4())
            connection.execute(
                """
                INSERT INTO users (id, username, email, password_hash, role, created_at)
                VALUES (?, ?, ?, ?, 'admin', ?)
                """,
                (user_id, username, email, password_hash, now),
            )
            user_row = connection.execute("SELECT id, username, email, role, created_at FROM users WHERE id = ?", (user_id,)).fetchone()
        return _user_from_row(user_row)


def _hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = pbkdf2_hmac("sha256", password.encode("utf-8"), salt, _PASSWORD_ITERATIONS)
    return f"pbkdf2_sha256${_PASSWORD_ITERATIONS}${salt.hex()}${digest.hex()}"


def _verify_password(password: str, stored_hash: str) -> bool:
    try:
        algorithm, iterations, salt_hex, digest_hex = stored_hash.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        digest = pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt_hex), int(iterations))
    except ValueError:
        return False
    return compare_digest(digest.hex(), digest_hex)


def _hash_token(token: str) -> str:
    return sha256(token.encode("utf-8")).hexdigest()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _user_from_row(row) -> AuthUser:
    return AuthUser(
        id=row["id"],
        username=row["username"],
        email=row["email"],
        role=row["role"],
        created_at=datetime.fromisoformat(row["created_at"]),
    )
