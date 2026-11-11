import os, tempfile
os.environ.setdefault("DATABASE_URL", f"sqlite:///{tempfile.mkdtemp()}/t.db")
os.environ["FORCE_DEMO_PAYPAL"] = "true"
os.environ["GEMINI_API_KEY"] = ""
import pytest
from fastapi.testclient import TestClient
from app.db import Base, engine
from app.main import app
from app import deps


@pytest.fixture(autouse=True)
def fresh():
    deps._clients.clear(); deps._hits.clear()
    Base.metadata.drop_all(engine); Base.metadata.create_all(engine)
    yield
    app.dependency_overrides.clear()


@pytest.fixture
def client(): return TestClient(app)


def signup(client, email="a@example.com"):
    r = client.post("/api/v1/auth/register", json={"email": email, "password": "supersecret1", "name": "A"})
    assert r.status_code == 201, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


@pytest.fixture
def auth(client): return signup(client)


@pytest.fixture
def synced(client, auth):
    r = client.post("/api/v1/paypal/sync", headers=auth); assert r.status_code == 200, r.text
    return auth
