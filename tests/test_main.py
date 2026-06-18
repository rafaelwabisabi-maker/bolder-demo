"""
Tests for the screener API. No network, no real API key.

What they pin (each is a real failure mode, not a hypothetical):
- /health is public and returns 200
- /screen rejects missing (401) and wrong (403) Bearer tokens
- /screen happy path returns the structured result
- /screen returns 502 (not an opaque 500) when the model returns non-JSON
  — this is the exact thing the README promises ("failures are explicit")
"""
import importlib
import json

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def app_main(monkeypatch):
    monkeypatch.setenv("API_KEY", "test-token")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    import main
    importlib.reload(main)
    return main


def _fake_anthropic(text: str):
    """Build a fake anthropic.Anthropic whose message returns `text`."""
    class _Block:
        def __init__(self, t): self.text = t

    class _Msg:
        def __init__(self, t): self.content = [_Block(t)]

    class _Messages:
        def create(self, **_): return _Msg(text)

    class _Client:
        def __init__(self, *a, **k): self.messages = _Messages()

    return _Client


def test_health_is_public(app_main):
    r = TestClient(app_main.app).get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_screen_missing_auth_401(app_main):
    r = TestClient(app_main.app).post(
        "/screen",
        json={"candidate_name": "A", "candidate_summary": "x", "role_requirements": "y"},
    )
    assert r.status_code == 401


def test_screen_wrong_token_403(app_main):
    r = TestClient(app_main.app).post(
        "/screen",
        headers={"Authorization": "Bearer wrong"},
        json={"candidate_name": "A", "candidate_summary": "x", "role_requirements": "y"},
    )
    assert r.status_code == 403


def test_screen_happy_path(app_main, monkeypatch):
    good = json.dumps({
        "fit_score": 8, "rating": "A", "dealbreakers": [],
        "strengths": ["12y ops"], "gaps": [], "recommendation": "ADVANCE",
        "reasoning": "Strong operational fit.",
    })
    monkeypatch.setattr(app_main.anthropic, "Anthropic", _fake_anthropic(good))
    r = TestClient(app_main.app).post(
        "/screen",
        headers={"Authorization": "Bearer test-token"},
        json={"candidate_name": "Ana", "candidate_summary": "12y ops", "role_requirements": "ops mgr"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["rating"] == "A"
    assert body["recommendation"] == "ADVANCE"


def test_screen_non_json_returns_502(app_main, monkeypatch):
    monkeypatch.setattr(app_main.anthropic, "Anthropic", _fake_anthropic("sorry, I can't do that"))
    r = TestClient(app_main.app).post(
        "/screen",
        headers={"Authorization": "Bearer test-token"},
        json={"candidate_name": "Ana", "candidate_summary": "x", "role_requirements": "y"},
    )
    assert r.status_code == 502
