from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, Field, field_validator


Username = Annotated[str, Field(min_length=1, max_length=64)]
Password = Annotated[str, Field(min_length=8, max_length=256)]


class UserRecord(BaseModel):
    id: str
    username: str
    email: str
    role: Literal["user", "admin"]
    created_at: datetime


class AuthUser(BaseModel):
    id: str
    username: str
    email: str
    role: Literal["user", "admin"]
    created_at: datetime


class RegisterRequest(BaseModel):
    username: Username
    email: str = Field(min_length=3, max_length=254)
    password: Password

    @field_validator("username", "email")
    @classmethod
    def strip_required_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Value is required")
        return normalized

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str) -> str:
        normalized = value.lower()
        if "@" not in normalized or normalized.startswith("@") or normalized.endswith("@"):
            raise ValueError("Invalid email address")
        return normalized


class LoginRequest(BaseModel):
    username: Username
    password: Password

    @field_validator("username")
    @classmethod
    def strip_username(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Username is required")
        return normalized


class AuthResponse(BaseModel):
    user: AuthUser


class CurrentUserResponse(BaseModel):
    user: AuthUser


class LogoutResponse(BaseModel):
    ok: bool = True
