"""Idempotent startup seeding: default org + platform-admin from env."""
from typing import Callable

from sqlalchemy import func, select

from server.config import Settings
from server.crypto import hash_password, verify_password
from server.models import Membership, Org, User

DEFAULT_ORG_NAME = "Overturn HQ"


def seed_platform(session_factory: Callable, settings: Settings) -> None:
    with session_factory() as session:
        org = session.scalars(
            select(Org).where(Org.name == DEFAULT_ORG_NAME)
        ).first()
        if org is None:
            org = Org(name=DEFAULT_ORG_NAME)
            session.add(org)
            session.flush()

        email = settings.admin_email.lower()
        user = session.scalars(
            select(User).where(func.lower(User.email) == email)
        ).first()
        if user is None:
            user = User(email=email,
                        password_hash=hash_password(settings.admin_password),
                        is_platform_admin=True)
            session.add(user)
            session.flush()
        else:
            if not verify_password(settings.admin_password, user.password_hash):
                user.password_hash = hash_password(settings.admin_password)
            user.is_platform_admin = True

        membership = session.scalars(
            select(Membership).where(Membership.user_id == user.id,
                                     Membership.org_id == org.id)
        ).first()
        if membership is None:
            session.add(Membership(user_id=user.id, org_id=org.id, role="admin"))
        session.commit()
