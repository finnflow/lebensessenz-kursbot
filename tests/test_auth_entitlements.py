import uuid
from typing import Dict

from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def _unique_email(prefix: str) -> str:
    """Generate a unique email address for tests."""
    return f"{prefix}-{uuid.uuid4().hex}@example.com"


def _register_and_login(prefix: str = "user") -> Dict[str, str]:
    """
    Helper:
    - registriert einen neuen User mit zufälliger E-Mail
    - loggt ihn ein
    - gibt dict mit email, password, token zurück
    """
    email = _unique_email(prefix)
    password = "TestPass123"

    # Register
    r = client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": password},
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["email"] == email

    # Login
    r = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": password},
    )
    assert r.status_code == 200, r.text
    token = r.json()["access_token"]
    assert isinstance(token, str) and len(token) > 20

    return {"email": email, "password": password, "token": token}


def test_register_login_me_flow():
    """Voller Happy-Path: register → login → me."""
    creds = _register_and_login(prefix="auth-flow")

    # /me mit gültigem Token
    r = client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {creds['token']}"},
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["email"] == creds["email"]
    assert "id" in data
    assert "created_at" in data

    # falsches Passwort → 401
    r = client.post(
        "/api/v1/auth/login",
        json={"email": creds["email"], "password": "wrong-pass"},
    )
    assert r.status_code == 401
    assert "Invalid email or password" in r.text


def test_me_requires_token():
    """GET /me ohne oder mit kaputtem Token sollte 401 liefern."""
    # ohne Token
    r = client.get("/api/v1/auth/me")
    assert r.status_code == 403 or r.status_code == 401

    # mit kaputtem Token
    r = client.get(
        "/api/v1/auth/me",
        headers={"Authorization": "Bearer invalid-token"},
    )
    assert r.status_code == 401
    assert "Invalid or expired token" in r.text


def test_entitlements_flow_selfstart_dev_grant(monkeypatch):
    """
    Entitlements:
    - initial: []
    - nach POST /dev/grant-selfstart: SELFSTART active
    """
    # Sicherstellen, dass wir im "dev"-Modus sind (APP_ENV != prod)
    monkeypatch.setenv("APP_ENV", "dev")

    creds = _register_and_login(prefix="entitlements")

    # initial: keine Entitlements
    r = client.get(
        "/api/v1/entitlements/me",
        headers={"Authorization": f"Bearer {creds['token']}"},
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert "entitlements" in data
    assert data["entitlements"] == []

    # Dev-Grant setzen
    r = client.post(
        "/api/v1/dev/grant-selfstart",
        headers={"Authorization": f"Bearer {creds['token']}"},
    )
    assert r.status_code == 200, r.text
    data = r.json()
    ents = data["entitlements"]
    assert len(ents) == 1
    assert ents[0]["product"] == "SELFSTART"
    assert ents[0]["status"] == "active"

    # Nochmals /entitlements/me prüfen
    r = client.get(
        "/api/v1/entitlements/me",
        headers={"Authorization": f"Bearer {creds['token']}"},
    )
    assert r.status_code == 200, r.text
    data = r.json()
    ents = data["entitlements"]
    assert len(ents) == 1
    assert ents[0]["product"] == "SELFSTART"
    assert ents[0]["status"] == "active"


def test_entitlements_require_auth():
    """/entitlements/me ohne Token sollte nicht durchgehen."""
    r = client.get("/api/v1/entitlements/me")
    assert r.status_code == 403 or r.status_code == 401
