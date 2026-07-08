from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import api_router
from app.core.config import Settings
from app.db.session import Database


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()

    app = FastAPI(title="Mica AgentOps API", version="0.1.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    database = Database(settings.database_url)
    database.init_db()

    app.state.settings = settings
    app.state.database = database

    app.include_router(api_router)

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
