import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from app.db import Database  # noqa: E402
from app.engine import SessionService  # noqa: E402
from app.llm import LLMSettings  # noqa: E402
from app.main import create_app  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402


@pytest.fixture()
def svc(tmp_path):
    settings = LLMSettings()
    settings.mode = "deterministic"
    settings.stream_ms = 0
    database = Database(str(tmp_path / "puente.db"))
    database.migrate()
    return SessionService(database, settings)


@pytest.fixture()
def client(tmp_path):
    application = create_app(str(tmp_path / "api.db"))
    application.state.svc.settings.mode = "deterministic"
    application.state.svc.settings.stream_ms = 0
    with TestClient(application) as test_client:
        yield test_client
