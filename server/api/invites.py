import secrets
import uuid
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from server.api.deps import OrgContext, get_session, require_org_admin
from server.crypto import hash_password, verify_password
from server.models import Invite, Membership, Org, User, utcnow

org_router = APIRouter(prefix="/org/invites", tags=["invites"])
public_router = APIRouter(prefix="/invites", tags=["invites"])

INVITE_TTL_DAYS = 7


def _invite_payload(inv: Invite, request: Request) -> dict:
    return {
        "id": str(inv.id),
        "token": inv.token,
        "inviteUrl": f"{request.base_url}#/invite/{inv.token}",
        "role": inv.role,
        "email": inv.email,
        "expiresAt": inv.expires_at.isoformat(),
    }


class InviteBody(BaseModel):
    role: str = "member"
    email: str | None = None


@org_router.post("")
def create_invite(
    request: Request,
    body: InviteBody,
    ctx: OrgContext = Depends(require_org_admin),
    session: Session = Depends(get_session),
) -> dict:
    if body.role not in ("admin", "member"):
        raise HTTPException(422, detail="role must be admin or member")
    inv = Invite(
        token=secrets.token_urlsafe(32),
        org_id=ctx.org.id,
        role=body.role,
        email=body.email.lower() if body.email else None,
        created_by=ctx.user.id,
        expires_at=utcnow() + timedelta(days=INVITE_TTL_DAYS),
    )
    session.add(inv)
    session.flush()
    return _invite_payload(inv, request)


@org_router.get("")
def list_invites(
    request: Request,
    ctx: OrgContext = Depends(require_org_admin),
    session: Session = Depends(get_session),
) -> list[dict]:
    invites = session.scalars(
        select(Invite).where(
            Invite.org_id == ctx.org.id,
            Invite.used_at.is_(None),
            Invite.expires_at > utcnow(),
        ).order_by(Invite.created_at)
    ).all()
    return [_invite_payload(i, request) for i in invites]


@org_router.delete("/{invite_id}")
def revoke_invite(
    invite_id: uuid.UUID,
    ctx: OrgContext = Depends(require_org_admin),
    session: Session = Depends(get_session),
) -> dict:
    inv = session.get(Invite, invite_id)
    if inv is None or inv.org_id != ctx.org.id:
        raise HTTPException(404, detail="invite not found")
    if inv.used_at is not None:
        raise HTTPException(409, detail="invite already used")
    session.delete(inv)
    return {"revoked": str(invite_id)}


def _live_invite(session: Session, token: str) -> Invite:
    inv = session.scalars(select(Invite).where(Invite.token == token)).first()
    if inv is None:
        raise HTTPException(404, detail="invite not found")
    if inv.used_at is not None or inv.expires_at <= utcnow():
        raise HTTPException(410, detail="invite expired or already used")
    return inv


@public_router.get("/{token}")
def peek_invite(token: str, session: Session = Depends(get_session)) -> dict:
    inv = _live_invite(session, token)
    org = session.get(Org, inv.org_id)
    return {
        "orgName": org.name, "role": inv.role, "email": inv.email,
        "expiresAt": inv.expires_at.isoformat(),
    }


class AcceptBody(BaseModel):
    email: str
    password: str


@public_router.post("/{token}/accept")
def accept_invite(
    token: str,
    body: AcceptBody,
    request: Request,
    session: Session = Depends(get_session),
) -> dict:
    from server.api.auth import _me_payload
    from server.api.deps import OrgContext as Ctx

    inv = _live_invite(session, token)
    email = body.email.lower()

    user = session.scalars(
        select(User).where(func.lower(User.email) == email)
    ).first()
    if user is None:
        # New user: check password length
        if len(body.password) < 8:
            raise HTTPException(422, detail="password must be at least 8 characters")
        user = User(email=email, password_hash=hash_password(body.password))
        session.add(user)
        session.flush()
    else:
        # Existing user: verify password first
        if not verify_password(body.password, user.password_hash):
            raise HTTPException(
                401, detail="an account with this email exists; enter its password"
            )
        existing = session.scalars(
            select(Membership).where(Membership.user_id == user.id,
                                     Membership.org_id == inv.org_id)
        ).first()
        if existing is not None:
            raise HTTPException(409, detail="already a member of this organization")

    session.add(Membership(user_id=user.id, org_id=inv.org_id, role=inv.role))
    inv.used_at = utcnow()
    inv.used_by = user.id
    org = session.get(Org, inv.org_id)

    request.session["user_id"] = str(user.id)
    request.session["org_id"] = str(org.id)
    return _me_payload(Ctx(user=user, org=org, role=inv.role))
