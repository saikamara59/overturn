import secrets
import uuid
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from server.api.deps import get_session, require_platform_admin
from server.api.invites import INVITE_TTL_DAYS, _invite_payload
from server.models import Invite, Membership, Org, Run, User, utcnow

router = APIRouter(prefix="/admin", tags=["platform-admin"])


@router.get("/orgs")
def list_orgs(
    _admin: User = Depends(require_platform_admin),
    session: Session = Depends(get_session),
) -> list[dict]:
    orgs = session.scalars(select(Org).order_by(Org.created_at)).all()
    out = []
    for org in orgs:
        members = session.scalar(
            select(func.count()).select_from(Membership)
            .where(Membership.org_id == org.id))
        runs = session.scalar(
            select(func.count()).select_from(Run).where(Run.org_id == org.id))
        out.append({
            "id": str(org.id), "name": org.name, "status": org.status,
            "members": members, "runs": runs,
        })
    return out


class OrgBody(BaseModel):
    name: str


@router.post("/orgs")
def create_org(
    request: Request,
    body: OrgBody,
    admin: User = Depends(require_platform_admin),
    session: Session = Depends(get_session),
) -> dict:
    name = body.name.strip()
    if not name:
        raise HTTPException(422, detail="name required")
    if session.scalars(select(Org).where(Org.name == name)).first():
        raise HTTPException(409, detail="an organization with that name exists")
    org = Org(name=name)
    session.add(org)
    session.flush()
    inv = Invite(
        token=secrets.token_urlsafe(32), org_id=org.id, role="admin",
        created_by=admin.id, expires_at=utcnow() + timedelta(days=INVITE_TTL_DAYS),
    )
    session.add(inv)
    session.flush()
    payload = _invite_payload(inv, request)
    return {
        "org": {"id": str(org.id), "name": org.name, "status": org.status},
        "inviteUrl": payload["inviteUrl"],
        "token": inv.token,
    }


class StatusBody(BaseModel):
    status: str


@router.patch("/orgs/{org_id}")
def set_org_status(
    org_id: uuid.UUID,
    body: StatusBody,
    _admin: User = Depends(require_platform_admin),
    session: Session = Depends(get_session),
) -> dict:
    if body.status not in ("active", "disabled"):
        raise HTTPException(422, detail="status must be active or disabled")
    org = session.get(Org, org_id)
    if org is None:
        raise HTTPException(404, detail="org not found")
    org.status = body.status
    return {"id": str(org.id), "status": org.status}
