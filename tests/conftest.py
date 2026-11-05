import os
import tempfile
from pathlib import Path

import pytest

_tmp = tempfile.mkdtemp()
os.environ["DB_PATH"] = str(Path(_tmp) / "test.db")
os.environ["SCREENER"] = "mock"
os.environ["OPENSANCTIONS_API_KEY"] = ""
os.environ["ANTHROPIC_API_KEY"] = ""

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture()
def client():
    from fastapi.testclient import TestClient

    from app import db
    from app.main import app

    if db.settings.db_path.exists():
        db.settings.db_path.unlink()
    with TestClient(app) as c:
        yield c


@pytest.fixture()
def sample_csv() -> bytes:
    return (ROOT / "sample_data" / "beneficiaries_sample.csv").read_bytes()
