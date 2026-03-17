"""
Shared fixtures for CommentaryFlow integration tests.
"""
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from src.openai_client import CommentaryResult, AttributionOverviewResult, Citation


@pytest.fixture()
def tmp_db(monkeypatch):
    """Isolate each test with a fresh temporary database."""
    from commentaryflow import db
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    monkeypatch.setattr(db, "DB_PATH", Path(tmp.name))
    db.init_db()
    yield Path(tmp.name)
    Path(tmp.name).unlink(missing_ok=True)


@pytest.fixture()
def test_client(tmp_db):
    """FastAPI TestClient with isolated DB (startup event skipped — tmp_db already inits)."""
    from commentaryflow.app import app
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client


@pytest.fixture()
def writer_token(test_client):
    """Obtain a bearer token for the writer1 seed user."""
    resp = test_client.post("/auth/token", data={"username": "writer1", "password": "writer123"})
    assert resp.status_code == 200, f"Writer login failed: {resp.text}"
    return resp.json()["access_token"]


@pytest.fixture()
def reviewer_token(test_client):
    """Obtain a bearer token for the compliance1 seed user."""
    resp = test_client.post("/auth/token", data={"username": "compliance1", "password": "compliance123"})
    assert resp.status_code == 200, f"Reviewer login failed: {resp.text}"
    return resp.json()["access_token"]


def auth_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture()
def fixture_dir():
    return Path(__file__).parent / "fixtures"


def make_mock_openai_class(
    ticker_results: list[CommentaryResult] | None = None,
    overview_results: list[AttributionOverviewResult] | None = None,
):
    """
    Factory returning a mock OpenAIClient class.

    The returned class's generate_commentary_batch / generate_attribution_overview_batch
    return the provided results (or sensible defaults).
    """
    class MockOpenAIClient:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        async def generate_commentary_batch(self, requests, **kwargs):
            if ticker_results is not None:
                return ticker_results
            # Build default success results from requests
            results = []
            for req in requests:
                results.append(CommentaryResult(
                    ticker=req["ticker"],
                    security_name=req.get("security_name", req["ticker"]),
                    commentary=f"Mock commentary for {req['ticker']}.",
                    citations=[Citation(url="https://example.com", title="Example")],
                    success=True,
                    error_message="",
                ))
            return results

        async def generate_attribution_overview_batch(self, requests, **kwargs):
            if overview_results is not None:
                return overview_results
            results = []
            for req in requests:
                results.append(AttributionOverviewResult(
                    portcode=req["portcode"],
                    output=f"Mock overview for {req['portcode']}.",
                    citations=[Citation(url="https://example.com/ov", title="Overview Source")],
                    success=True,
                    error_message="",
                ))
            return results

    return MockOpenAIClient
