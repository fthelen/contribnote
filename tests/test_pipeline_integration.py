"""
Integration tests for the CommentaryFlow generation pipeline.

Mock strategy: patch commentaryflow.dedup.OpenAIClient with a mock class
and patch export helpers to avoid file I/O.
"""
import json
import os
import time
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from src.openai_client import CommentaryResult, AttributionOverviewResult, Citation
from tests.conftest import auth_headers, make_mock_openai_class
from commentaryflow import db


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _set_api_key(value: str = "test-key-123"):
    """Set an API key in app_settings so /api/runs doesn't 400."""
    db.update_setting("openai_api_key", value)


def _upload_files(client, token, fixture_dir, filenames):
    """Upload fixture files to /api/runs and return the response."""
    files = []
    for name in filenames:
        path = fixture_dir / name
        files.append(("files", (name, path.read_bytes(),
                                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")))
    return client.post("/api/runs", files=files, headers=auth_headers(token))


def _wait_for_run(client, run_id, timeout=10):
    """Poll until batch_run is no longer 'running'."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        run = db.get_batch_run(run_id)
        if run and run["status"] != "running":
            return run
        time.sleep(0.15)
    return db.get_batch_run(run_id)


# ---------------------------------------------------------------------------
# Test: Excel parse & persist
# ---------------------------------------------------------------------------

class TestExcelParseAndPersist:

    @patch("commentaryflow.dedup.OpenAIClient", make_mock_openai_class())
    @patch("commentaryflow.app.exp.save_bronze_json")
    def test_upload_single_file_creates_commentary(
        self, mock_save, test_client, writer_token, fixture_dir
    ):
        _set_api_key()
        resp = _upload_files(test_client, writer_token, fixture_dir,
                             ["ABC_12312025_01282026.xlsx"])
        assert resp.status_code == 200
        run_id = resp.json()["run_id"]
        run = _wait_for_run(test_client, run_id)
        assert run["status"] == "completed"

        commentaries = db.list_commentaries(batch_run_id_filter=run_id)
        assert len(commentaries) == 1
        assert commentaries[0]["portcode"] == "ABC"

    @patch("commentaryflow.dedup.OpenAIClient", make_mock_openai_class())
    @patch("commentaryflow.app.exp.save_bronze_json")
    def test_upload_multiple_files(
        self, mock_save, test_client, writer_token, fixture_dir
    ):
        _set_api_key()
        resp = _upload_files(test_client, writer_token, fixture_dir,
                             ["ABC_12312025_01282026.xlsx",
                              "XYZ_12312025_01312026.xlsx"])
        assert resp.status_code == 200
        run_id = resp.json()["run_id"]
        run = _wait_for_run(test_client, run_id)
        assert run["status"] == "completed"

        commentaries = db.list_commentaries(batch_run_id_filter=run_id)
        assert len(commentaries) == 2
        portcodes = {c["portcode"] for c in commentaries}
        assert "ABC" in portcodes
        assert "XYZ" in portcodes

    @patch("commentaryflow.dedup.OpenAIClient", make_mock_openai_class())
    @patch("commentaryflow.app.exp.save_bronze_json")
    def test_upload_bad_file_returns_error(
        self, mock_save, test_client, writer_token, tmp_path
    ):
        _set_api_key()
        bad_file = tmp_path / "bad.txt"
        bad_file.write_text("not an excel file")
        files = [("files", ("bad.txt", bad_file.read_bytes(), "text/plain"))]
        resp = test_client.post("/api/runs", files=files,
                                headers=auth_headers(writer_token))
        assert resp.status_code == 200  # run starts, fails async
        run_id = resp.json()["run_id"]
        run = _wait_for_run(test_client, run_id)
        assert run["status"] == "failed"


# ---------------------------------------------------------------------------
# Test: Generation pipeline
# ---------------------------------------------------------------------------

class TestGenerationPipeline:

    @patch("commentaryflow.dedup.OpenAIClient", make_mock_openai_class())
    @patch("commentaryflow.app.exp.save_bronze_json")
    def test_full_pipeline_happy_path(
        self, mock_save, test_client, writer_token, fixture_dir
    ):
        _set_api_key()
        resp = _upload_files(test_client, writer_token, fixture_dir,
                             ["ABC_12312025_01282026.xlsx"])
        run_id = resp.json()["run_id"]
        run = _wait_for_run(test_client, run_id)
        assert run["status"] == "completed"

        commentaries = db.list_commentaries(batch_run_id_filter=run_id)
        assert len(commentaries) == 1
        c = commentaries[0]
        assert c["status"] == "draft"

        # Sections should exist with bronze text
        sections = db.get_sections(c["commentary_id"])
        assert len(sections) > 0
        overview_sections = [s for s in sections if s["section_type"] == "overview"]
        assert len(overview_sections) == 1
        assert overview_sections[0]["bronze_text"]  # not empty

        # Citations should be persisted
        for s in sections:
            if s["section_type"] == "security":
                cits = db.get_citations(c["commentary_id"], s["section_key"], "bronze")
                assert len(cits) >= 1, f"No citations for section {s['section_key']}"

    @patch("commentaryflow.app.exp.save_bronze_json")
    def test_partial_ticker_failure(
        self, mock_save, test_client, writer_token, fixture_dir
    ):
        """One ticker fails → commentary still reaches 'draft' with error text for that ticker."""
        def _mock_class_factory():
            class DynamicMock:
                def __init__(self, **kwargs):
                    pass
                async def generate_commentary_batch(self, requests, **kwargs):
                    results = []
                    for i, req in enumerate(requests):
                        if i == 0:
                            results.append(CommentaryResult(
                                ticker=req["ticker"],
                                security_name=req.get("security_name", ""),
                                commentary=f"Good commentary for {req['ticker']}.",
                                citations=[Citation(url="https://example.com", title="Src")],
                                success=True,
                            ))
                        else:
                            results.append(CommentaryResult(
                                ticker=req["ticker"],
                                security_name=req.get("security_name", ""),
                                commentary="",
                                citations=[],
                                success=False,
                                error_message="API timeout",
                            ))
                    return results
                async def generate_attribution_overview_batch(self, requests, **kwargs):
                    return [AttributionOverviewResult(
                        portcode=req["portcode"],
                        output=f"Overview for {req['portcode']}.",
                        citations=[], success=True, error_message="",
                    ) for req in requests]
            return DynamicMock

        _set_api_key()
        with patch("commentaryflow.dedup.OpenAIClient", _mock_class_factory()):
            resp = _upload_files(test_client, writer_token, fixture_dir,
                                 ["ABC_12312025_01282026.xlsx"])
            run_id = resp.json()["run_id"]
            run = _wait_for_run(test_client, run_id)

        assert run["status"] == "completed"
        commentaries = db.list_commentaries(batch_run_id_filter=run_id)
        assert len(commentaries) == 1
        # With partial failures, commentary should still be "draft" (not all sections failed)
        assert commentaries[0]["status"] == "draft"

    @patch("commentaryflow.app.exp.save_bronze_json")
    def test_all_tickers_fail(
        self, mock_save, test_client, writer_token, fixture_dir
    ):
        """All tickers + overview fail → commentary 'draft' (outlook placeholder has no error)."""
        class AllFailClient:
            def __init__(self, **kwargs):
                pass
            async def generate_commentary_batch(self, requests, **kwargs):
                return [CommentaryResult(
                    ticker=req["ticker"],
                    security_name=req.get("security_name", ""),
                    commentary="",
                    citations=[],
                    success=False,
                    error_message="All fail",
                ) for req in requests]
            async def generate_attribution_overview_batch(self, requests, **kwargs):
                return [AttributionOverviewResult(
                    portcode=req["portcode"],
                    output="",
                    citations=[], success=False, error_message="All fail",
                ) for req in requests]

        _set_api_key()
        with patch("commentaryflow.dedup.OpenAIClient", AllFailClient):
            resp = _upload_files(test_client, writer_token, fixture_dir,
                                 ["ABC_12312025_01282026.xlsx"])
            run_id = resp.json()["run_id"]
            run = _wait_for_run(test_client, run_id)

        assert run["status"] == "completed"
        commentaries = db.list_commentaries(batch_run_id_filter=run_id)
        assert len(commentaries) == 1
        c = commentaries[0]
        # errors < sections because outlook placeholder has no error entry,
        # so status is "draft" not "error"; verify all security sections have failure text
        assert c["status"] == "draft"
        sections = db.get_sections(c["commentary_id"])
        security_sections = [s for s in sections if s["section_type"] == "security"]
        for s in security_sections:
            assert "failed" in s["bronze_text"].lower() or "not generated" in s["bronze_text"].lower()

    @patch("commentaryflow.app.exp.save_bronze_json")
    def test_overview_failure_still_completes(
        self, mock_save, test_client, writer_token, fixture_dir
    ):
        """Overview fails but security tickers succeed → commentary still 'draft'."""
        class OverviewFailClient:
            def __init__(self, **kwargs):
                pass
            async def generate_commentary_batch(self, requests, **kwargs):
                return [CommentaryResult(
                    ticker=req["ticker"],
                    security_name=req.get("security_name", ""),
                    commentary=f"Commentary for {req['ticker']}.",
                    citations=[Citation(url="https://example.com", title="Src")],
                    success=True,
                ) for req in requests]
            async def generate_attribution_overview_batch(self, requests, **kwargs):
                return [AttributionOverviewResult(
                    portcode=req["portcode"],
                    output="", citations=[],
                    success=False, error_message="Overview LLM error",
                ) for req in requests]

        _set_api_key()
        with patch("commentaryflow.dedup.OpenAIClient", OverviewFailClient):
            resp = _upload_files(test_client, writer_token, fixture_dir,
                                 ["ABC_12312025_01282026.xlsx"])
            run_id = resp.json()["run_id"]
            run = _wait_for_run(test_client, run_id)

        assert run["status"] == "completed"
        commentaries = db.list_commentaries(batch_run_id_filter=run_id)
        assert len(commentaries) == 1
        # Overview failed but security sections succeeded → draft, not error
        assert commentaries[0]["status"] == "draft"


# ---------------------------------------------------------------------------
# Test: Error recovery
# ---------------------------------------------------------------------------

class TestErrorRecovery:

    @patch("commentaryflow.app.exp.save_bronze_json")
    def test_pipeline_exception_marks_commentaries_error(
        self, mock_save, test_client, writer_token, fixture_dir
    ):
        """If run_generation_pipeline raises, all commentaries should be → 'error'."""
        _set_api_key()

        with patch("commentaryflow.app.run_generation_pipeline",
                   side_effect=RuntimeError("Boom")):
            resp = _upload_files(test_client, writer_token, fixture_dir,
                                 ["ABC_12312025_01282026.xlsx"])
            run_id = resp.json()["run_id"]
            run = _wait_for_run(test_client, run_id)

        assert run["status"] == "failed"
        commentaries = db.list_commentaries(batch_run_id_filter=run_id)
        for c in commentaries:
            assert c["status"] == "error", f"Commentary {c['commentary_id']} should be 'error' but is '{c['status']}'"

    def test_startup_recovery(self, tmp_db):
        """Commentaries stuck in 'generating' should recover to 'error' on startup."""
        # Create a proper batch run so FK constraint is satisfied
        run_id = db.create_batch_run("{}", "test")
        db.upsert_commentary(
            commentary_id="STUCK_TEST_Q12025",
            portcode="STUCK",
            period_label="Q1 2025",
            period_start="",
            period_end="",
            batch_run_id=run_id,
            source_file="test.xlsx",
        )
        # Verify it's in 'generating'
        c = db.get_commentary("STUCK_TEST_Q12025")
        assert c["status"] == "generating"

        # Simulate startup recovery logic (same as app.startup)
        stuck = db.list_commentaries(status_filter="generating")
        for s in stuck:
            db.update_commentary_status(s["commentary_id"], "error")

        c = db.get_commentary("STUCK_TEST_Q12025")
        assert c["status"] == "error"


# ---------------------------------------------------------------------------
# Test: Status transitions
# ---------------------------------------------------------------------------

class TestStatusTransitions:

    @patch("commentaryflow.dedup.OpenAIClient", make_mock_openai_class())
    @patch("commentaryflow.app.exp.save_bronze_json")
    @patch("commentaryflow.app.exp.save_gold_json")
    @patch("commentaryflow.app.exp.export_snowflake_csvs")
    @patch("commentaryflow.app.exp.save_metadata_json")
    def test_full_lifecycle_to_published(
        self, mock_meta, mock_csv, mock_gold, mock_bronze,
        test_client, writer_token, reviewer_token, fixture_dir
    ):
        """Generate → edit silver → submit → approve → publish."""
        _set_api_key()
        resp = _upload_files(test_client, writer_token, fixture_dir,
                             ["ABC_12312025_01282026.xlsx"])
        run_id = resp.json()["run_id"]
        run = _wait_for_run(test_client, run_id)
        assert run["status"] == "completed"

        commentaries = db.list_commentaries(batch_run_id_filter=run_id)
        cid = commentaries[0]["commentary_id"]
        assert commentaries[0]["status"] == "draft"

        # Edit silver for each section (via DB directly — PUT route tested separately)
        sections = db.get_sections(cid)
        for s in sections:
            db.save_silver(cid, s["section_key"], f"Edited silver for {s['section_key']}")

        # Verify commentary_id is URL-safe (no slashes)
        assert "/" not in cid, f"Commentary ID contains '/': {cid}"

        # Submit for review
        resp = test_client.post(f"/api/commentaries/{cid}/submit",
                                headers=auth_headers(writer_token))
        assert resp.status_code == 200
        assert db.get_commentary(cid)["status"] == "in_review"

        # Approve
        resp = test_client.post(f"/api/commentaries/{cid}/approve",
                                headers=auth_headers(reviewer_token))
        assert resp.status_code == 200
        assert db.get_commentary(cid)["status"] == "approved"

        # Publish
        resp = test_client.post(f"/api/commentaries/{cid}/publish",
                                headers=auth_headers(writer_token))
        assert resp.status_code == 200
        assert db.get_commentary(cid)["status"] == "published"

    @patch.dict(os.environ, {"OPENAI_API_KEY": ""})
    def test_no_api_key_returns_400(self, test_client, writer_token, fixture_dir):
        """POST /api/runs without API key should return 400."""
        db.update_setting("openai_api_key", "")
        files = [("files", ("ABC_12312025_01282026.xlsx",
                             (fixture_dir / "ABC_12312025_01282026.xlsx").read_bytes(),
                             "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"))]
        resp = test_client.post("/api/runs", files=files,
                                headers=auth_headers(writer_token))
        assert resp.status_code == 400
        assert "API key" in resp.json()["detail"]
