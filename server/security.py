import hashlib
import hmac

from fastapi import HTTPException, Request


def constant_time_equals(supplied: str, expected: str) -> bool:
    return hmac.compare_digest(
        hashlib.sha256(supplied.encode()).digest(),
        hashlib.sha256(expected.encode()).digest(),
    )


def require_user(request: Request) -> str:
    user = request.session.get("user")
    if not user:
        raise HTTPException(status_code=401, detail="authentication required")
    return user
