"""FastAPI app factory. Production entry: `uvicorn server.app:app`."""
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import APIRouter, Depends, FastAPI
from starlette.middleware.sessions import SessionMiddleware
from starlette.staticfiles import StaticFiles

from server.api import auth, claims, demo, runs
from server.api.deps import current_org
from server.config import Settings, get_settings
from server.db import make_engine, make_session_factory


def create_app(settings: Settings, session_factory) -> FastAPI:
    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        from server.seed import seed_platform
        seed_platform(session_factory, settings)
        if settings.demo_mode:
            from server.demo import seed_demo
            seed_demo(session_factory)
        yield

    app = FastAPI(title="Overturn", version="0.1.0", lifespan=lifespan)
    app.state.settings = settings
    app.state.session_factory = session_factory
    app.add_middleware(
        SessionMiddleware, secret_key=settings.secret_key, https_only=settings.secure_cookies
    )

    api = APIRouter(prefix="/api/v1")
    api.include_router(auth.router)
    # Task 3 moves org-scoping into the routers themselves; for now, gate
    # tenant-owned resources at inclusion time so disabled/missing orgs are
    # rejected without touching runs.py/claims.py (still on the Phase 1
    # `require_user` shim — see server/security.py).
    api.include_router(runs.router, dependencies=[Depends(current_org)])
    api.include_router(claims.router, dependencies=[Depends(current_org)])
    api.include_router(demo.router)
    app.include_router(api)

    spa_dir = Path(settings.spa_dir) if settings.spa_dir else (
        Path(__file__).resolve().parent.parent / "frontend" / "dist-app"
    )
    if spa_dir.is_dir():
        app.mount("/", StaticFiles(directory=spa_dir, html=True), name="spa")
    return app


def build_app() -> FastAPI:
    settings = get_settings()
    return create_app(
        settings=settings,
        session_factory=make_session_factory(make_engine(settings.database_url)),
    )


app = None  # populated lazily for uvicorn: `uvicorn server.app:app --factory` not needed
try:  # pragma: no cover - production path only
    app = build_app()
except Exception:  # missing env in dev/test contexts is fine; tests use create_app
    app = None
