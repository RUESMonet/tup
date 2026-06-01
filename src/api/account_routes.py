from fastapi import APIRouter, Depends, Query

from src.dependencies import get_billing_service, require_current_user
from src.models.auth import AuthUser
from src.models.billing import AccountCreditsResponse, CreditTransactionListResponse
from src.services.billing_service import BillingService


router = APIRouter(prefix="/api/account", tags=["account"])


@router.get("/credits", response_model=AccountCreditsResponse)
def get_account_credits(
    user: AuthUser = Depends(require_current_user),
    billing: BillingService = Depends(get_billing_service),
) -> AccountCreditsResponse:
    account = billing.repository.get_or_create_account(user.id, billing.settings.initial_credit_balance)
    return AccountCreditsResponse(account=account, quotas=billing.quotas_for_user(user.id), costs=billing.costs())


@router.get("/transactions", response_model=CreditTransactionListResponse)
def list_account_transactions(
    project_id: str | None = None,
    limit: int = Query(default=50, ge=1, le=100),
    user: AuthUser = Depends(require_current_user),
    billing: BillingService = Depends(get_billing_service),
) -> CreditTransactionListResponse:
    billing.repository.get_or_create_account(user.id, billing.settings.initial_credit_balance)
    return CreditTransactionListResponse(
        transactions=billing.repository.list_transactions(user.id, limit=limit, project_id=project_id)
    )
