import uuid
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from server.api.deps import (
    OrgContext, current_org, get_session, require_org_admin,
)
from server.crypto import last4
from server.models import Membership, User

router = APIRouter(prefix="/org", tags=["org"])


@router.get("")
def org_info(ctx: OrgContext = Depends(current_org)) -> dict:
    return {
        "id": str(ctx.org.id),
        "name": ctx.org.name,
        "role": ctx.role,
        "hasApiKey": ctx.org.anthropic_key_encrypted is not None,
        "apiKeyLast4": ctx.org.anthropic_key_last4,
    }


class ApiKeyBody(BaseModel):
    key: str


@router.put("/api-key")
def set_api_key(
    request: Request,
    body: ApiKeyBody,
    ctx: OrgContext = Depends(require_org_admin),
    session: Session = Depends(get_session),
) -> dict:
    key = body.key.strip()
    if not key.startswith("sk-ant-") or len(key) < 20:
        raise HTTPException(422, detail="that does not look like an Anthropic API key")
    org = session.get(type(ctx.org), ctx.org.id)
    org.anthropic_key_encrypted = request.app.state.key_vault.encrypt(key)
    org.anthropic_key_last4 = last4(key)
    return {"hasApiKey": True, "apiKeyLast4": org.anthropic_key_last4}


@router.delete("/api-key")
def clear_api_key(
    ctx: OrgContext = Depends(require_org_admin),
    session: Session = Depends(get_session),
) -> dict:
    org = session.get(type(ctx.org), ctx.org.id)
    org.anthropic_key_encrypted = None
    org.anthropic_key_last4 = None
    return {"hasApiKey": False}


def _admin_count(session: Session, org_id: uuid.UUID) -> int:
    return len(session.scalars(
        select(Membership).where(Membership.org_id == org_id,
                                 Membership.role == "admin")
    ).all())


def _membership_or_404(session: Session, org_id: uuid.UUID,
                       user_id: uuid.UUID) -> Membership:
    m = session.scalars(
        select(Membership).where(Membership.org_id == org_id,
                                 Membership.user_id == user_id)
    ).first()
    if m is None:
        raise HTTPException(404, detail="member not found")
    return m


@router.get("/members")
def list_members(
    ctx: OrgContext = Depends(require_org_admin),
    session: Session = Depends(get_session),
) -> list[dict]:
    rows = session.execute(
        select(Membership, User)
        .join(User, User.id == Membership.user_id)
        .where(Membership.org_id == ctx.org.id)
        .order_by(Membership.created_at)
    ).all()
    return [
        {
            "userId": str(u.id), "email": u.email, "role": m.role,
            "joinedAt": m.created_at.isoformat(),
        }
        for m, u in rows
    ]


class RoleBody(BaseModel):
    role: str


@router.patch("/members/{user_id}")
def change_role(
    user_id: uuid.UUID,
    body: RoleBody,
    ctx: OrgContext = Depends(require_org_admin),
    session: Session = Depends(get_session),
) -> dict:
    if body.role not in ("admin", "member"):
        raise HTTPException(422, detail="role must be admin or member")
    m = _membership_or_404(session, ctx.org.id, user_id)
    if m.role == "admin" and body.role == "member" \
            and _admin_count(session, ctx.org.id) == 1:
        raise HTTPException(409, detail="cannot demote the last admin")
    m.role = body.role
    return {"userId": str(user_id), "role": m.role}


@router.delete("/members/{user_id}")
def remove_member(
    user_id: uuid.UUID,
    ctx: OrgContext = Depends(require_org_admin),
    session: Session = Depends(get_session),
) -> dict:
    m = _membership_or_404(session, ctx.org.id, user_id)
    if m.role == "admin" and _admin_count(session, ctx.org.id) == 1:
        raise HTTPException(409, detail="cannot remove the last admin")
    session.delete(m)
    return {"removed": str(user_id)}
