from fastapi.testclient import TestClient

from app.main import app


def test_health():
    r = TestClient(app).get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_openapi_has_core_routes():
    paths = TestClient(app).get("/openapi.json").json()["paths"]
    for p in ("/api/auth/login", "/api/feed/{client_id}", "/api/insights/{client_id}/{news_id}", "/api/chat",
              "/api/news", "/api/feedback/metrics"):
        assert p in paths


# TODO: сквозной сценарий на синтетических данных: login -> clients -> feed -> insight -> chat -> feedback
