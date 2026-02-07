"""
Regression tests for GUI progress unification and completion dialog behavior.
"""

import asyncio
import queue
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

pytest.importorskip("tkinter")

import src.gui as gui_module
from src.excel_parser import AttributionRow, AttributionTable
from src.gui import (
    CommentaryGeneratorApp,
    DEFAULT_ATTRIBUTION_PROMPT_TEMPLATE,
    DEFAULT_MODEL,
    DEFAULT_PROMPT_TEMPLATE,
    _make_overall_progress_callback,
)
from src.openai_client import AttributionOverviewResult, Citation, CommentaryResult


class DummyVar:
    """Simple stand-in for tkinter variable objects in tests."""

    def __init__(self, value=""):
        self._value = value

    def get(self):
        return self._value

    def set(self, value):
        self._value = value


class DummyRoot:
    """Simple stand-in for a Tk root object with immediate callbacks."""

    def after(self, _delay_ms, callback):
        callback()


class DummyRootNoopAfter:
    """Simple stand-in for Tk root where after() records without immediate execution."""

    def __init__(self):
        self.after_calls: list[tuple[int, object]] = []

    def after(self, delay_ms, callback):
        self.after_calls.append((delay_ms, callback))


def test_make_overall_progress_callback_maps_phase_progress_to_run_total():
    events: list[tuple[str, int, int]] = []
    callback = _make_overall_progress_callback(
        update_progress_fn=lambda item, completed, total: events.append((item, completed, total)),
        offset=2,
        overall_total=5,
    )

    callback("ATTRIBUTION", 1, 3)
    callback("ATTRIBUTION", 3, 3)

    assert events == [
        ("ATTRIBUTION", 3, 5),
        ("ATTRIBUTION", 5, 5),
    ]


def test_async_generate_includes_attribution_in_progress_and_totals(tmp_path, monkeypatch):
    progress_events: list[tuple[str, int, int]] = []

    app = CommentaryGeneratorApp.__new__(CommentaryGeneratorApp)
    app.root = DummyRoot()
    app.input_files = [Path("input.xlsx")]
    app.run_attribution_overview = True
    app.mode_var = DummyVar("top_bottom")
    app.count_var = DummyVar("5")
    app.sources_var = DummyVar("reuters.com")
    app.prompt_text_content = DEFAULT_PROMPT_TEMPLATE
    app.developer_prompt_content = "dev prompt"
    app.thinking_level = "low"
    app.text_verbosity = "low"
    app.model_id = DEFAULT_MODEL
    app.api_key = "test-key"
    app.prioritize_sources = True
    app.require_citations = True
    app._cancel_event = None
    app.attribution_prompt_text_content = DEFAULT_ATTRIBUTION_PROMPT_TEMPLATE
    app.attribution_developer_prompt_content = "attribution dev prompt"
    app.attribution_thinking_level = "low"
    app.attribution_text_verbosity = "low"
    app.attribution_model_id = DEFAULT_MODEL
    app.output_folder = tmp_path
    app.status_var = DummyVar("Ready")
    app.progress_var = DummyVar(0)
    app.update_progress = lambda item, completed, total: progress_events.append((item, completed, total))
    app._enqueue_ui_callback = lambda callback: callback()

    sector_table = AttributionTable(
        sheet_name="AttributionbySector",
        category_header="Sector",
        metric_headers=["Portfolio Return"],
        top_level_rows=[AttributionRow(category="Health Care", metrics={"Portfolio Return": 1.2})],
        total_row=AttributionRow(category="Total", metrics={"Portfolio Return": 1.2}),
    )

    portfolios = [
        SimpleNamespace(
            portcode="PORT1",
            period="12/31/2025 to 1/28/2026",
            attribution_warnings=[],
            sector_attribution=sector_table,
            country_attribution=None,
        ),
        SimpleNamespace(
            portcode="PORT2",
            period="12/31/2025 to 1/28/2026",
            attribution_warnings=[],
            sector_attribution=None,
            country_attribution=None,
        ),
    ]

    selections = [
        SimpleNamespace(
            portcode="PORT1",
            period="12/31/2025 to 1/28/2026",
            ranked_securities=[SimpleNamespace(ticker="AAPL", security_name="Apple Inc.")],
        ),
        SimpleNamespace(
            portcode="PORT2",
            period="12/31/2025 to 1/28/2026",
            ranked_securities=[SimpleNamespace(ticker="MSFT", security_name="Microsoft Corp.")],
        ),
    ]

    class FakeOpenAIClient:
        def __init__(self, *args, progress_callback=None, **kwargs):
            self.progress_callback = progress_callback

        async def generate_commentary_batch(self, requests, **kwargs):
            total = len(requests)
            results: list[CommentaryResult] = []
            for idx, req in enumerate(requests, 1):
                if self.progress_callback:
                    self.progress_callback(req["ticker"], idx, total)
                results.append(
                    CommentaryResult(
                        ticker=req["ticker"],
                        security_name=req["security_name"],
                        commentary=f"Commentary for {req['ticker']}",
                        citations=[Citation(url="https://example.com/source")],
                        success=True,
                    )
                )
            return results

        async def generate_attribution_overview_batch(self, requests, **kwargs):
            total = len(requests)
            results: list[AttributionOverviewResult] = []
            for idx, req in enumerate(requests, 1):
                if self.progress_callback:
                    self.progress_callback(req["portcode"], idx, total)
                results.append(
                    AttributionOverviewResult(
                        portcode=req["portcode"],
                        output=f"Overview for {req['portcode']}",
                        citations=[Citation(url="https://example.com/overview")],
                        success=True,
                    )
                )
            return results

    monkeypatch.setattr(gui_module, "parse_multiple_files", lambda _files: portfolios)
    monkeypatch.setattr(gui_module, "process_portfolios", lambda _portfolios, _mode, _n: selections)
    monkeypatch.setattr(gui_module, "OpenAIClient", FakeOpenAIClient)
    monkeypatch.setattr(gui_module, "create_output_workbook", lambda *args, **kwargs: tmp_path / "output.xlsx")
    monkeypatch.setattr(gui_module, "create_log_file", lambda *args, **kwargs: tmp_path / "run_log.txt")

    result = asyncio.run(app._async_generate())

    assert result["total_commentary_requests"] == 2
    assert result["total_attribution_requests"] == 1
    assert result["total_requests"] == 3
    assert result["total_securities"] == 2

    completed_values = [event[1] for event in progress_events]
    total_values = [event[2] for event in progress_events]
    assert completed_values == [1, 2, 3]
    assert total_values == [3, 3, 3]


def test_schedule_progress_queue_drain_runs_queued_ui_callbacks():
    app = CommentaryGeneratorApp.__new__(CommentaryGeneratorApp)
    app.root = DummyRootNoopAfter()
    app.progress_var = DummyVar(0)
    app.status_var = DummyVar("Ready")
    app._progress_queue = queue.SimpleQueue()
    app._ui_callback_queue = queue.SimpleQueue()

    app._progress_queue.put(("AAPL", 1, 2))
    app._ui_callback_queue.put(lambda: app.status_var.set("Complete!"))

    app._schedule_progress_queue_drain()

    assert app.progress_var.get() == 50.0
    assert app.status_var.get() == "Complete!"
    assert len(app.root.after_calls) == 1


def test_on_generation_complete_shows_success_popup_with_parent_even_with_errors():
    app = CommentaryGeneratorApp.__new__(CommentaryGeneratorApp)
    app.save_config = lambda: None
    app.progress_var = DummyVar(0)
    app.status_var = DummyVar("Ready")
    app.root = object()

    result = {
        "output_path": Path("/tmp/output.xlsx"),
        "log_path": Path("/tmp/run_log.txt"),
        "total_commentary_requests": 10,
        "total_attribution_requests": 2,
        "total_requests": 12,
        "errors": 3,
        "duration": 9.8,
    }

    with (
        patch("src.gui.messagebox.showinfo") as showinfo,
        patch("src.gui.messagebox.showerror") as showerror,
    ):
        app._on_generation_complete(result)

    showinfo.assert_called_once()
    showerror.assert_not_called()
    assert showinfo.call_args.kwargs["parent"] is app.root
    message_text = showinfo.call_args.args[1]
    assert "Commentary requests processed: 10" in message_text
    assert "Attribution requests processed: 2" in message_text
    assert "Total requests processed: 12" in message_text
    assert "Errors: 3" in message_text
    assert app.status_var.get() == "Ready"
    assert app.progress_var.get() == 0
