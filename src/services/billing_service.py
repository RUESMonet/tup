from datetime import datetime, timezone
from typing import Any

from src.config import Settings
from src.models.billing import CreditAction, CreditCostResponse, CreditTransactionResponse, QuotaUsageResponse
from src.services.billing_repository import BillingRepository


CREDIT_COST_FIELDS: dict[CreditAction, str] = {
    "project_image": "project_image_credit_cost",
    "project_image_edit": "project_image_edit_credit_cost",
    "project_video": "project_video_credit_cost",
    "canvas_image": "canvas_image_credit_cost",
    "canvas_image_edit": "canvas_image_edit_credit_cost",
    "canvas_image_batch": "canvas_image_batch_credit_cost",
    "canvas_video": "canvas_video_credit_cost",
}

DAILY_QUOTA_FIELDS: dict[CreditAction, str] = {
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
        return [
            CreditCostResponse(
                action_type=action_type,
                cost=self.cost_for(action_type),
                daily_quota=self.daily_quota_for(action_type),
            )
            for action_type in CREDIT_COST_FIELDS
        ]

    def quotas_for_user(self, user_id: str) -> list[QuotaUsageResponse]:
        period_key = self.current_daily_period_key()
        return [
            self.repository.get_quota(user_id, action_type, period_key, self.daily_quota_for(action_type))
            for action_type in DAILY_QUOTA_FIELDS
        ]

    def charge_for_action(
        self,
        user_id: str,
        project_id: str | None,
        action_type: CreditAction,
        metadata: dict[str, Any],
    ) -> CreditTransactionResponse:
        self.repository.get_or_create_account(user_id, self.settings.initial_credit_balance)
        period_key = self.current_daily_period_key()
        transaction = self.repository.debit(
            user_id=user_id,
            project_id=project_id,
            task_id=None,
            action_type=action_type,
            amount=self.cost_for(action_type),
            metadata=metadata,
        )
        try:
            self.repository.increment_quota(
                user_id,
                action_type,
                period_key,
                self.daily_quota_for(action_type),
            )
        except ValueError as error:
            self.repository.refund(
                user_id=user_id,
                original_transaction_id=transaction.id,
                task_id=None,
                reason="quota increment failed",
            )
            raise error
        return transaction

    def attach_task(self, user_id: str, transaction_id: str, task_id: str) -> None:
        self.repository.attach_task(user_id, transaction_id, task_id)

    def refund_failed_task(self, user_id: str, transaction_id: str | None, task_id: str | None, reason: str) -> None:
        if transaction_id is None:
            return
        self.repository.refund(user_id=user_id, original_transaction_id=transaction_id, task_id=task_id, reason=reason)

    def recover_stale_task(self, user_id: str, transaction_id: str, task_id: str, updated_before: datetime, error: str, reason: str) -> bool:
        return self.repository.refund_recoverable_task(
            user_id=user_id,
            original_transaction_id=transaction_id,
            task_id=task_id,
            updated_before=updated_before,
            error=error,
            reason=reason,
        ) is not None

    def cost_for(self, action_type: CreditAction) -> int:
        return int(getattr(self.settings, CREDIT_COST_FIELDS[action_type]))

    def daily_quota_for(self, action_type: CreditAction) -> int:
        return int(getattr(self.settings, DAILY_QUOTA_FIELDS[action_type]))

    def current_daily_period_key(self) -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%d")
