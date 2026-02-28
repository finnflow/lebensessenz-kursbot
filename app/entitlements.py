import os
from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app.auth import get_current_user
from app.database import get_entitlements_for_user, grant_entitlement

router = APIRouter(prefix="/api/v1", tags=["entitlements"])

SELFSTART_PRODUCT = "SELFSTART"
APP_ENV = os.getenv("APP_ENV", "dev")


class Entitlement(BaseModel):
    product: str
    status: str


class EntitlementsResponse(BaseModel):
    entitlements: List[Entitlement]


@router.get("/entitlements/me", response_model=EntitlementsResponse)
def get_my_entitlements(current_user: dict = Depends(get_current_user)) -> EntitlementsResponse:
    rows = get_entitlements_for_user(current_user["id"])
    entitlements = [
        Entitlement(product=row["product"], status=row["status"])
        for row in rows
    ]
    return EntitlementsResponse(entitlements=entitlements)


@router.post("/dev/grant-selfstart", response_model=EntitlementsResponse)
def grant_selfstart(current_user: dict = Depends(get_current_user)) -> EntitlementsResponse:
    """
    DEV-only Endpoint:
    - setzt das SELFSTART-Entitlement für den aktuell eingeloggten User.
    - NICHT in Production verwenden.
    """
    if APP_ENV.lower() == "prod":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Dev grant endpoint is disabled in production",
        )

    grant_entitlement(user_id=current_user["id"], product=SELFSTART_PRODUCT, status="active")
    rows = get_entitlements_for_user(current_user["id"])
    entitlements = [
        Entitlement(product=row["product"], status=row["status"])
        for row in rows
    ]
    return EntitlementsResponse(entitlements=entitlements)
