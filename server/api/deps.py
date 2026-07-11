import uuid
from dataclasses import dataclass
from typing import Iterator

from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from server.models import Membership, Org, User
from server.security import require_user_id


def get_session(request: Request) -> Iterator[Session]:
    session: Session = request.app.state.session_factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def current_user(
    request: Request, session: Session = Depends(get_session)
) -> User:
    user = session.get(User, uuid.UUID(require_user_id(request)))
    if user is None:
        raise HTTPException(status_code=401, detail="authentication required")
    return user


@dataclass
class OrgContext:
    user: User
    org: Org
    role: str


def current_org(
    request: Request,
    session: Session = Depends(get_session),
    user: User = Depends(current_user),
) -> OrgContext:
    org_id = request.session.get("org_id")
    if not org_id:
        raise HTTPException(status_code=401, detail="no active organization")
    membership = session.scalars(
        select(Membership).where(Membership.user_id == user.id,
                                 Membership.org_id == uuid.UUID(org_id))
    ).first()
    if membership is None:
        raise HTTPException(status_code=401, detail="no active organization")
    org = session.get(Org, membership.org_id)
    if org is None or org.status == "disabled":
        raise HTTPException(status_code=403,
                            detail="this organization is disabled")
    return OrgContext(user=user, org=org, role=membership.role)


def require_org_admin(ctx: OrgContext = Depends(current_org)) -> OrgContext:
    if ctx.role != "admin":
        raise HTTPException(status_code=403, detail="organization admin required")
    return ctx


def require_platform_admin(user: User = Depends(current_user)) -> User:
    if not user.is_platform_admin:
        raise HTTPException(status_code=403, detail="platform admin required")
    return user


def scoped_run(
    run_id: uuid.UUID,
    ctx: OrgContext = Depends(current_org),
    session: Session = Depends(get_session),
):
    from server.models import Run

    run = session.get(Run, run_id)
    if run is None or run.org_id != ctx.org.id:
        raise HTTPException(status_code=404, detail="run not found")
    return run


def scoped_claim(
    claim_id: uuid.UUID,
    ctx: OrgContext = Depends(current_org),
    session: Session = Depends(get_session),
):
    from server.models import Claim

    claim = session.get(Claim, claim_id)
    if claim is None or claim.run.org_id != ctx.org.id:
        raise HTTPException(status_code=404, detail="claim not found")
    return claim
