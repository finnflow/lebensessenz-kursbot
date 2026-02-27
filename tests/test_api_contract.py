"""
API contract integration tests.

Uses FastAPI TestClient — no running server required.
Tests cover /api/v1 routes and the centralised error envelope.
"""
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def test_health():
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    data = response.json()
    assert data == {"ok": True}


def test_config():
    response = client.get("/api/v1/config")
    assert response.status_code == 200
    data = response.json()

    assert "model" in data
    assert "rag" in data
    assert "features" in data

    assert "top_k" in data["rag"]
    assert "max_history_messages" in data["rag"]
    assert "summary_threshold" in data["rag"]


def test_chat_success():
    payload = {
        "guestId": "contract-test",
        "message": "Testnachricht",
    }

    response = client.post("/api/v1/chat", json=payload)
    assert response.status_code == 200

    data = response.json()

    assert "conversationId" in data
    assert "answer" in data
    assert "sources" in data


def test_chat_validation_error():
    payload = {
        "guestId": "contract-test",
        # "message" intentionally omitted
    }

    response = client.post("/api/v1/chat", json=payload)
    assert response.status_code == 422

    data = response.json()

    assert "error" in data
    assert "code" in data["error"]
    assert data["error"]["code"] == "VALIDATION_ERROR"
    assert "message" in data["error"]
