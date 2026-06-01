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
