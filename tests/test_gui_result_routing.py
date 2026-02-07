"""
Regression tests for commentary result routing by request order.
"""

import pytest

pytest.importorskip("tkinter")

from src.gui import _organize_commentary_results_by_request
from src.openai_client import CommentaryResult


def make_result(
    ticker: str,
    commentary: str,
    success: bool = True,
    error_message: str = "",
) -> CommentaryResult:
    """Create a CommentaryResult for routing tests."""
    return CommentaryResult(
        ticker=ticker,
        security_name=f"{ticker} Inc.",
        commentary=commentary,
        citations=[],
        success=success,
        error_message=error_message,
    )


def test_duplicate_tickers_are_routed_to_correct_portfolios():
    requests = [
        {"portcode": "XYZ", "ticker": "AAPL", "prompt": "p1", "security_name": "Apple"},
        {"portcode": "ONE", "ticker": "AAPL", "prompt": "p2", "security_name": "Apple"},
    ]
    results = [
        make_result("AAPL", "XYZ commentary"),
        make_result("AAPL", "ONE commentary"),
    ]

    commentary_results, errors = _organize_commentary_results_by_request(requests, results)

    assert commentary_results["XYZ"]["AAPL"].commentary == "XYZ commentary"
    assert commentary_results["ONE"]["AAPL"].commentary == "ONE commentary"
    assert errors == {}


def test_duplicate_ticker_error_is_attributed_to_matching_portfolio():
    requests = [
        {"portcode": "XYZ", "ticker": "MSFT", "prompt": "p1", "security_name": "Microsoft"},
        {"portcode": "ONE", "ticker": "MSFT", "prompt": "p2", "security_name": "Microsoft"},
    ]
    results = [
        make_result("MSFT", "ok commentary", success=True),
        make_result(
            "MSFT",
            "",
            success=False,
            error_message="No citations found in response (citations are required)",
        ),
    ]

    commentary_results, errors = _organize_commentary_results_by_request(requests, results)

    assert commentary_results["XYZ"]["MSFT"].success is True
    assert commentary_results["ONE"]["MSFT"].success is False
    assert "XYZ|MSFT" not in errors
    assert errors["ONE|MSFT"] == ["No citations found in response (citations are required)"]


def test_all_returned_requests_have_portfolio_entries_without_collisions():
    requests = [
        {"portcode": "XYZ", "ticker": "AAPL", "prompt": "p1", "security_name": "Apple"},
        {"portcode": "XYZ", "ticker": "NVDA", "prompt": "p2", "security_name": "NVIDIA"},
        {"portcode": "ONE", "ticker": "AAPL", "prompt": "p3", "security_name": "Apple"},
    ]
    results = [
        make_result("AAPL", "XYZ AAPL"),
        make_result("NVDA", "XYZ NVDA"),
        make_result("AAPL", "ONE AAPL"),
    ]

    commentary_results, errors = _organize_commentary_results_by_request(requests, results)

    assert errors == {}
    assert set(commentary_results.keys()) == {"XYZ", "ONE"}
    assert set(commentary_results["XYZ"].keys()) == {"AAPL", "NVDA"}
    assert set(commentary_results["ONE"].keys()) == {"AAPL"}
    assert commentary_results["ONE"]["AAPL"].commentary == "ONE AAPL"
