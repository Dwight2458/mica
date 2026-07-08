from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.commands import CommandRecordRead
from app.schemas.runs import RunRecordRead


class DockerExecuteRequest(BaseModel):
    workspace: str
    command: list[str] = Field(min_length=1)
    image: str = "python:3.12-slim"
    network_mode: Literal["none", "bridge"] = "none"
    allow_host_callback: bool = False
    inject_proxy: bool = False
    api_base_url: str = "http://host.docker.internal:8000/api"


class DockerRunResultRead(BaseModel):
    exit_code: int
    stdout: str
    stderr: str
    duration_ms: int
    image: str
    workspace: str
    network_mode: str
    command: list[str]


class DockerExecuteResponse(BaseModel):
    run: RunRecordRead
    command: CommandRecordRead
    result: DockerRunResultRead
