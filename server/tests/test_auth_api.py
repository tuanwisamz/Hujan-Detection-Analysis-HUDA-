"""JWT verification, admin gating, error envelope, rate limits, settings validation."""

import time

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

from app import auth, repo
from app.errors import ApiError
from app.main import app
from app.models import AppSettings
from app.ratelimit import RateLimit

ISSUER = "https://test.clerk.accounts.dev"
KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)


class FakeJwk:
    def __init__(self, key):
        self.key = key


class FakeJwkClient:
    def get_signing_key_from_jwt(self, token):
        return FakeJwk(KEY.public_key())


def token(**overrides):
    claims = {"sub": "user_1", "iss": ISSUER, "exp": int(time.time()) + 60, "azp": "http://localhost:5173"}
    claims.update(overrides)
    return jwt.encode(claims, KEY, algorithm="RS256")


def test_valid_token():
    assert auth.verify_token(token(), FakeJwkClient())["sub"] == "user_1"


@pytest.mark.parametrize("overrides", [
    {"exp": int(time.time()) - 120},
    {"iss": "https://evil.example"},
    {"azp": "https://evil.example"},
])
def test_rejected_tokens(overrides):
    with pytest.raises(ApiError) as exc:
        auth.verify_token(token(**overrides), FakeJwkClient())
    assert exc.value.status == 401


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(auth, "_jwk_client", lambda: FakeJwkClient())
    roles = {"user_1": "user", "admin_1": "admin"}
    monkeypatch.setattr(repo, "get_profile", lambda uid: {"id": uid, "role": roles.get(uid, "user")})
    return TestClient(app, raise_server_exceptions=False)


def test_health_is_public_and_survives_db_down(client):
    r = client.get("/api/v1/health")
    assert r.status_code == 200 and r.json()["status"] == "ok"
    assert r.json()["model_version"] == "rules_only"


def test_missing_token_uses_error_envelope(client):
    r = client.get("/api/v1/live/summary")
    assert r.status_code == 401
    body = r.json()["error"]
    assert body["code"] == "UNAUTHENTICATED" and body["request_id"]


def test_user_cannot_reach_admin_routes(client):
    r = client.get("/api/v1/admin/settings", headers={"Authorization": f"Bearer {token()}"})
    assert r.status_code == 403 and r.json()["error"]["code"] == "FORBIDDEN"


def test_admin_settings_validation(client, monkeypatch):
    monkeypatch.setattr(repo, "get_app_settings", lambda: AppSettings())
    saved = {}
    monkeypatch.setattr(repo, "save_app_settings", lambda values, by: saved.update(values))
    monkeypatch.setattr(repo, "log_event", lambda *a, **k: None)
    headers = {"Authorization": f"Bearer {token(sub='admin_1')}"}
    bad = client.patch("/api/v1/admin/settings", headers=headers,
                       json={"thresholds": {"amber_rate_mmh": 40, "red_rate_mmh": 30}})
    assert bad.status_code == 422 and bad.json()["error"]["code"] == "VALIDATION_ERROR"
    ok = client.patch("/api/v1/admin/settings", headers=headers, json={"cooldown_min": 45})
    assert ok.status_code == 200 and ok.json()["cooldown_min"] == 45 and saved == {"cooldown_min": 45}


def test_ingest_requires_cron_secret(client):
    r = client.post("/api/v1/internal/ingest", headers={"X-Cron-Secret": "wrong"})
    assert r.status_code == 401


def test_ingest_skips_when_run_too_recent(client, monkeypatch):
    monkeypatch.setattr(repo, "start_run", lambda *a, **k: None)
    r = client.post("/api/v1/internal/ingest", headers={"X-Cron-Secret": "test-cron-secret"})
    assert r.status_code == 202 and r.json() == {"run_id": None, "status": "skipped"}


def test_rate_limit_window():
    limit = RateLimit(2)
    limit.hit("u", now=0)
    limit.hit("u", now=1)
    with pytest.raises(ApiError) as exc:
        limit.hit("u", now=2)
    assert exc.value.status == 429
    limit.hit("u", now=61)  # window slid
    limit.hit("other", now=2)  # per user


def test_editing_one_language_keeps_the_other(client, monkeypatch):
    from app.api import admin
    monkeypatch.setattr(admin, "_load", lambda wid: ({"id": wid, "status": "draft"}, {"id": "z1", "name": "Elmina"}))
    monkeypatch.setattr(admin, "_audit", lambda *a, **k: None)
    written = {}
    monkeypatch.setattr(repo, "update_warning", lambda wid, fields: written.update(fields) or {"id": wid, **fields})
    headers = {"Authorization": f"Bearer {token(sub='admin_1')}"}
    r = client.patch("/api/v1/admin/warnings/w1", headers=headers, json={"message_en": "Fixed text."})
    assert r.status_code == 200 and written == {"message_en": "Fixed text."}
    empty = client.patch("/api/v1/admin/warnings/w1", headers=headers, json={})
    assert empty.status_code == 422


@pytest.mark.parametrize("method, path", [
    ("get", "/api/v1/admin/sensors"),
    ("patch", "/api/v1/admin/sensors/jps-rain:3717101"),
    ("get", "/api/v1/admin/sirens"),
    ("post", "/api/v1/admin/sirens"),
    ("post", "/api/v1/admin/sirens/s1/sound"),
    ("post", "/api/v1/admin/sirens/s1/test"),
    ("get", "/api/v1/admin/siren-activations"),
    ("post", "/api/v1/admin/siren-activations/a1/approve"),
])
def test_sensor_routes_are_admin_only(client, method, path):
    r = getattr(client, method)(path, headers={"Authorization": f"Bearer {token()}"}, **({"json": {}} if method in ("patch", "post") else {}))
    assert r.status_code == 403


def test_station_patch_needs_lat_and_lon_together(client, monkeypatch):
    monkeypatch.setattr(repo, "get_station", lambda sid: {"id": sid, "name": "Bukit Fraser"})
    saved = {}
    monkeypatch.setattr(repo, "update_station", lambda sid, patch: saved.update(patch) or {"id": sid, **patch})
    monkeypatch.setattr(repo, "log_event", lambda *a, **k: None)
    headers = {"Authorization": f"Bearer {token(sub='admin_1')}"}
    assert client.patch("/api/v1/admin/sensors/jps-rain:3717101", headers=headers, json={"lat": 3.7}).status_code == 422
    r = client.patch("/api/v1/admin/sensors/jps-rain:3717101", headers=headers, json={"lat": 3.71, "lon": 101.74})
    assert r.status_code == 200 and saved["location_quality"] == "verified" and saved["location_source"] == "admin"
