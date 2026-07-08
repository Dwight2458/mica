from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app


@pytest.fixture()
def client(tmp_path: Path) -> TestClient:
    settings = Settings(database_url=f"sqlite:///{tmp_path / 'mica.db'}")
    return TestClient(create_app(settings))
