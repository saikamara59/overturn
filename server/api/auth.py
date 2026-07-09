from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from server.security import constant_time_equals, require_user

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginBody(BaseModel):
    email: str
    password: str


@router.post("/login")
def login(request: Request, body: LoginBody) -> dict:
    settings = request.app.state.settings
    ok = (
        constant_time_equals(body.email, settings.admin_email)
        and constant_time_equals(body.password, settings.admin_password)
    )
    if not ok:
        raise HTTPException(status_code=401, detail="invalid credentials")
    request.session["user"] = body.email
    return {"email": body.email}


@router.post("/logout")
def logout(request: Request) -> dict:
    request.session.clear()
    return {"ok": True}


@router.get("/me")
def me(user: str = Depends(require_user)) -> dict:
    return {"email": user}
