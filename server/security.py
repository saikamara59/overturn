from fastapi import HTTPException, Request


def require_user_id(request: Request) -> str:
    user_id = request.session.get("user_id")
    if not user_id:
        raise HTTPException(status_code=401, detail="authentication required")
    return user_id


def require_user(request: Request) -> str:  # Phase 1 shim; removed in Task 3
    return require_user_id(request)
