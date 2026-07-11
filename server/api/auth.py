from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from server.api.deps import OrgContext, current_org, get_session
from server.crypto import verify_password
from server.models import Membership, Org, User

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginBody(BaseModel):
    email: str
    password: str


def _me_payload(ctx: OrgContext) -> dict:
    return {
        "email": ctx.user.email,
        "orgId": str(ctx.org.id),
        "orgName": ctx.org.name,
        "role": ctx.role,
        "isPlatformAdmin": ctx.user.is_platform_admin,
    }


@router.post("/login")
def login(
    request: Request, body: LoginBody, session: Session = Depends(get_session)
) -> dict:
    user = session.scalars(
        select(User).where(func.lower(User.email) == body.email.lower())
    ).first()
    if user is None or not verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=401, detail="invalid credentials")
    membership = session.scalars(
        select(Membership)
        .where(Membership.user_id == user.id)
        .order_by(Membership.created_at)
    ).first()
    if membership is None:
        raise HTTPException(status_code=403,
                            detail="account has no organization")
    org = session.get(Org, membership.org_id)
    request.session["user_id"] = str(user.id)
    request.session["org_id"] = str(org.id)
    return _me_payload(OrgContext(user=user, org=org, role=membership.role))


@router.post("/logout")
def logout(request: Request) -> dict:
    request.session.clear()
    return {"ok": True}


@router.get("/me")
def me(ctx: OrgContext = Depends(current_org)) -> dict:
    return _me_payload(ctx)
