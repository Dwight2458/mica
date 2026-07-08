from __future__ import annotations

from fastapi import APIRouter

from app.api.routes import agent_runs, approvals, commands, docker, events, runs

api_router = APIRouter(prefix="/api")
api_router.include_router(agent_runs.router, tags=["agent-runs"])
api_router.include_router(approvals.router, tags=["approvals"])
api_router.include_router(commands.router, tags=["commands"])
api_router.include_router(docker.router, tags=["docker"])
api_router.include_router(events.router, tags=["events"])
api_router.include_router(runs.router, tags=["runs"])
