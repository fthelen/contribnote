"""
Tests for the Selection Engine Module.
"""
import pytest
from pathlib import Path

from src.excel_parser import SecurityRow, PortfolioData
from src.selection_engine import (
    SelectionMode,
    SecurityType,
    RankedSecurity,
    SelectionResult,
    classify_security,
    select_top_bottom,
    select_all_holdings,
    process_portfolio,
    process_portfolios,
)


# --- Helper Functions ---

def make_security(ticker: str, contribution: float, weight: float = 1.0, gics: str = "Tech") -> SecurityRow:
    """Helper to create a SecurityRow for testing."""
    return SecurityRow(
        ticker=ticker,
        security_name=f"{ticker} Inc.",
        port_ending_weight=weight,
        contribution_to_return=contribution,
        gics=gics
    )


def make_portfolio(securities: list[SecurityRow], portcode: str = "TEST") -> PortfolioData:
    """Helper to create a PortfolioData for testing."""
    return PortfolioData(
        portcode=portcode,
        period="12/31/2025 to 1/28/2026",
        securities=securities,
        source_file=Path(f"{portcode}_12312025_01282026.xlsx")
    )


# --- classify_security Tests ---

class TestClassifySecurity:
    """Tests for the classify_security function."""

    def test_positive_contribution_is_contributor(self):
        assert classify_security(0.15) == SecurityType.CONTRIBUTOR

    def test_negative_contribution_is_detractor(self):
        assert classify_security(-0.10) == SecurityType.DETRACTOR

    def test_zero_contribution_is_neutral(self):
        assert classify_security(0.0) == SecurityType.NEUTRAL

    def test_small_positive_is_contributor(self):
        assert classify_security(0.0001) == SecurityType.CONTRIBUTOR

    def test_small_negative_is_detractor(self):
        assert classify_security(-0.0001) == SecurityType.DETRACTOR


# --- RankedSecurity Tests ---

class TestRankedSecurity:
    """Tests for the RankedSecurity dataclass properties."""

    def test_property_accessors(self):
        """Should delegate properties to underlying security."""
        security = make_security("AAPL", 0.15, 5.25)
        ranked = RankedSecurity(
            security=security,
            rank=1,
            security_type=SecurityType.CONTRIBUTOR
        )
        
        assert ranked.ticker == "AAPL"
        assert ranked.security_name == "AAPL Inc."
        assert ranked.port_ending_weight == 5.25
        assert ranked.contribution_to_return == 0.15


# --- select_top_bottom Tests ---

class TestSelectTopBottom:
    """Tests for the select_top_bottom function."""

    def test_selects_top_n_contributors(self):
        """Should select top N contributors by contribution."""
        securities = [
            make_security("A", 0.10),
            make_security("B", 0.30),
            make_security("C", 0.20),
            make_security("D", 0.05),
        ]
        
        contributors, detractors = select_top_bottom(securities, n=2)
        
        assert len(contributors) == 2
        assert contributors[0].ticker == "B"  # Highest contribution
        assert contributors[0].rank == 1
        assert contributors[1].ticker == "C"  # Second highest
        assert contributors[1].rank == 2
        assert len(detractors) == 0  # No negatives

    def test_selects_top_n_detractors(self):
        """Should select top N detractors by most negative contribution."""
        securities = [
            make_security("A", -0.10),
            make_security("B", -0.30),
            make_security("C", -0.20),
            make_security("D", -0.05),
        ]
        
        contributors, detractors = select_top_bottom(securities, n=2)
        
        assert len(contributors) == 0  # No positives
        assert len(detractors) == 2
        assert detractors[0].ticker == "B"  # Most negative
        assert detractors[0].rank == 1
        assert detractors[1].ticker == "C"  # Second most negative
        assert detractors[1].rank == 2

    def test_mixed_contributors_and_detractors(self):
        """Should correctly split positive and negative contributions."""
        securities = [
            make_security("A", 0.25),
            make_security("B", -0.15),
            make_security("C", 0.10),
            make_security("D", -0.30),
            make_security("E", 0.05),
            make_security("F", -0.05),
        ]
        
        contributors, detractors = select_top_bottom(securities, n=2)
        
        # Top 2 contributors
        assert len(contributors) == 2
        assert contributors[0].ticker == "A"
        assert contributors[1].ticker == "C"
        
        # Top 2 detractors (most negative)
        assert len(detractors) == 2
        assert detractors[0].ticker == "D"
        assert detractors[1].ticker == "B"

    def test_tie_breaker_by_weight(self):
        """Should use weight as tie-breaker when contributions are equal."""
        securities = [
            make_security("A", 0.10, weight=5.0),
            make_security("B", 0.10, weight=10.0),  # Same contribution, higher weight
            make_security("C", 0.10, weight=2.0),
        ]
        
        contributors, _ = select_top_bottom(securities, n=3)
        
        # Should be sorted by contribution desc, then weight desc
        assert contributors[0].ticker == "B"  # Highest weight among tied
        assert contributors[1].ticker == "A"
        assert contributors[2].ticker == "C"

    def test_fewer_than_n_available(self):
        """Should return as many as available when fewer than N exist."""
        securities = [
            make_security("A", 0.10),
            make_security("B", -0.15),
        ]
        
        contributors, detractors = select_top_bottom(securities, n=5)
        
        assert len(contributors) == 1  # Only 1 positive
        assert len(detractors) == 1  # Only 1 negative

    def test_excludes_zero_contribution(self):
        """Should exclude zero contributions from both groups."""
        securities = [
            make_security("A", 0.10),
            make_security("B", 0.0),  # Neutral
            make_security("C", -0.10),
        ]
        
        contributors, detractors = select_top_bottom(securities, n=5)
        
        assert len(contributors) == 1
        assert len(detractors) == 1
        # B (neutral) should not appear in either list

    def test_empty_list(self):
        """Should handle empty securities list."""
        contributors, detractors = select_top_bottom([], n=5)
        
        assert contributors == []
        assert detractors == []


# --- select_all_holdings Tests ---

class TestSelectAllHoldings:
    """Tests for the select_all_holdings function."""

    def test_includes_all_securities(self):
        """Should include all securities."""
        securities = [
            make_security("A", 0.10),
            make_security("B", -0.15),
            make_security("C", 0.0),
        ]
        
        result = select_all_holdings(securities)
        
        assert len(result) == 3

    def test_sorted_by_absolute_contribution(self):
        """Should sort by absolute contribution descending."""
        securities = [
            make_security("A", 0.05),
            make_security("B", -0.20),  # Highest absolute
            make_security("C", 0.10),
        ]
        
        result = select_all_holdings(securities)
        
        assert result[0].ticker == "B"  # abs(-0.20) = 0.20
        assert result[1].ticker == "C"  # abs(0.10) = 0.10
        assert result[2].ticker == "A"  # abs(0.05) = 0.05

    def test_rank_is_none(self):
        """Rank should be None in all-holdings mode."""
        securities = [make_security("A", 0.10)]
        
        result = select_all_holdings(securities)
        
        assert result[0].rank is None

    def test_classifies_security_types(self):
        """Should correctly classify contributor/detractor/neutral."""
        securities = [
            make_security("A", 0.10),
            make_security("B", -0.10),
            make_security("C", 0.0),
        ]
        
        result = select_all_holdings(securities)
        
        # Find each by ticker to check type
        by_ticker = {r.ticker: r for r in result}
        assert by_ticker["A"].security_type == SecurityType.CONTRIBUTOR
        assert by_ticker["B"].security_type == SecurityType.DETRACTOR
        assert by_ticker["C"].security_type == SecurityType.NEUTRAL

    def test_empty_list(self):
        """Should handle empty securities list."""
        result = select_all_holdings([])
        assert result == []


# --- process_portfolio Tests ---

class TestProcessPortfolio:
    """Tests for the process_portfolio function."""

    def test_top_bottom_mode(self):
        """Should process portfolio in TOP_BOTTOM mode."""
        securities = [
            make_security("A", 0.25),
            make_security("B", 0.15),
            make_security("C", -0.20),
            make_security("D", -0.10),
            make_security("FEE", -0.01, gics="NA"),  # Should be filtered
        ]
        portfolio = make_portfolio(securities)
        
        result = process_portfolio(portfolio, SelectionMode.TOP_BOTTOM, n=2)
        
        assert result.portcode == "TEST"
        assert result.mode == SelectionMode.TOP_BOTTOM
        # Should have 2 contributors + 2 detractors (FEE filtered out)
        assert len(result.ranked_securities) == 4
        # Contributors first
        assert result.ranked_securities[0].ticker == "A"
        assert result.ranked_securities[1].ticker == "B"
        # Then detractors
        assert result.ranked_securities[2].ticker == "C"
        assert result.ranked_securities[3].ticker == "D"

    def test_all_holdings_mode(self):
        """Should process portfolio in ALL_HOLDINGS mode."""
        securities = [
            make_security("A", 0.25),
            make_security("B", -0.15),
            make_security("CASH", 0.0, gics="NA"),  # Should be filtered
        ]
        portfolio = make_portfolio(securities)
        
        result = process_portfolio(portfolio, SelectionMode.ALL_HOLDINGS)
        
        assert result.mode == SelectionMode.ALL_HOLDINGS
        assert len(result.ranked_securities) == 2  # CASH filtered out
        # All ranks should be None
        for sec in result.ranked_securities:
            assert sec.rank is None

    def test_preserves_portfolio_metadata(self):
        """Should preserve portcode, period, and source file."""
        portfolio = make_portfolio([make_security("A", 0.10)], portcode="MYPORT")
        
        result = process_portfolio(portfolio, SelectionMode.ALL_HOLDINGS)
        
        assert result.portcode == "MYPORT"
        assert result.period == "12/31/2025 to 1/28/2026"
        assert "MYPORT" in result.source_file


# --- process_portfolios Tests ---

class TestProcessPortfolios:
    """Tests for the process_portfolios function."""

    def test_processes_multiple_portfolios(self):
        """Should process multiple portfolios."""
        portfolios = [
            make_portfolio([make_security("A", 0.10)], portcode="PORT1"),
            make_portfolio([make_security("B", 0.20)], portcode="PORT2"),
        ]
        
        results = process_portfolios(portfolios, SelectionMode.ALL_HOLDINGS)
        
        assert len(results) == 2
        assert results[0].portcode == "PORT1"
        assert results[1].portcode == "PORT2"

    def test_empty_list(self):
        """Should handle empty portfolios list."""
        results = process_portfolios([], SelectionMode.TOP_BOTTOM)
        assert results == []
