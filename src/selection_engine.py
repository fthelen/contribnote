"""
Selection Engine Module

Implements ranking logic for selecting top contributors and detractors,
or processing all holdings.
"""

from dataclasses import dataclass
from enum import Enum
from typing import Optional

from .excel_parser import SecurityRow, PortfolioData


class SelectionMode(Enum):
    """Holdings selection mode."""
    TOP_BOTTOM = "top_bottom"  # Top N contributors + Bottom N detractors
    ALL_HOLDINGS = "all_holdings"  # All holdings


class SecurityType(Enum):
    """Classification of a security by contribution."""
    CONTRIBUTOR = "Contributor"
    DETRACTOR = "Detractor"
    NEUTRAL = "Neutral"


@dataclass
class RankedSecurity:
    """A security with its rank and classification."""
    security: SecurityRow
    rank: Optional[int]  # None for ALL_HOLDINGS mode
    security_type: SecurityType
    
    @property
    def ticker(self) -> str:
        return self.security.ticker
    
    @property
    def security_name(self) -> str:
        return self.security.security_name
    
    @property
    def port_ending_weight(self) -> float:
        return self.security.port_ending_weight
    
    @property
    def contribution_to_return(self) -> float:
        return self.security.contribution_to_return


@dataclass
class SelectionResult:
    """Result of the selection process for a portfolio."""
    portcode: str
    period: str
    ranked_securities: list[RankedSecurity]
    mode: SelectionMode
    source_file: str


def classify_security(contribution: float) -> SecurityType:
    """Classify a security based on its contribution to return."""
    if contribution > 0:
        return SecurityType.CONTRIBUTOR
    elif contribution < 0:
        return SecurityType.DETRACTOR
    else:
        return SecurityType.NEUTRAL


def select_top_bottom(
    securities: list[SecurityRow],
    n: int = 5
) -> tuple[list[RankedSecurity], list[RankedSecurity]]:
    """
    Select top N contributors and bottom N detractors.
    
    Args:
        securities: List of securities (already filtered for cash/fees)
        n: Number of top/bottom securities to select
        
    Returns:
        Tuple of (contributors, detractors) as RankedSecurity lists
    """
    # Separate positive and negative contributors
    positive = [s for s in securities if s.contribution_to_return > 0]
    negative = [s for s in securities if s.contribution_to_return < 0]
    
    # Sort contributors: by contribution descending, then by weight descending (tie-breaker)
    positive.sort(key=lambda s: (-s.contribution_to_return, -s.port_ending_weight))
    
    # Sort detractors: by contribution ascending (most negative first), 
    # then by weight descending (tie-breaker)
    negative.sort(key=lambda s: (s.contribution_to_return, -s.port_ending_weight))
    
    # Take top N from each group
    top_contributors = positive[:n]
    top_detractors = negative[:n]
    
    # Create ranked securities
    contributors = [
        RankedSecurity(
            security=sec,
            rank=i + 1,
            security_type=SecurityType.CONTRIBUTOR
        )
        for i, sec in enumerate(top_contributors)
    ]
    
    detractors = [
        RankedSecurity(
            security=sec,
            rank=i + 1,
            security_type=SecurityType.DETRACTOR
        )
        for i, sec in enumerate(top_detractors)
    ]
    
    return contributors, detractors


def select_all_holdings(securities: list[SecurityRow]) -> list[RankedSecurity]:
    """
    Process all holdings without ranking.
    
    Args:
        securities: List of securities (already filtered for cash/fees)
        
    Returns:
        List of RankedSecurity objects (rank is None)
    """
    # Sort by absolute contribution descending for display order
    sorted_securities = sorted(
        securities,
        key=lambda s: abs(s.contribution_to_return),
        reverse=True
    )
    
    return [
        RankedSecurity(
            security=sec,
            rank=None,
            security_type=classify_security(sec.contribution_to_return)
        )
        for sec in sorted_securities
    ]


def process_portfolio(
    portfolio: PortfolioData,
    mode: SelectionMode,
    n: int = 5
) -> SelectionResult:
    """
    Process a portfolio and select securities based on mode.
    
    Args:
        portfolio: Parsed portfolio data
        mode: Selection mode (TOP_BOTTOM or ALL_HOLDINGS)
        n: Number of top/bottom securities (only for TOP_BOTTOM mode)
        
    Returns:
        SelectionResult with ranked securities
    """
    # Filter out cash/fees
    filtered = portfolio.get_filtered_securities()
    
    if mode == SelectionMode.TOP_BOTTOM:
        contributors, detractors = select_top_bottom(filtered, n)
        # Combine: contributors first, then detractors
        ranked = contributors + detractors
    else:
        ranked = select_all_holdings(filtered)
    
    return SelectionResult(
        portcode=portfolio.portcode,
        period=portfolio.period,
        ranked_securities=ranked,
        mode=mode,
        source_file=str(portfolio.source_file)
    )


def process_portfolios(
    portfolios: list[PortfolioData],
    mode: SelectionMode,
    n: int = 5
) -> list[SelectionResult]:
    """
    Process multiple portfolios.
    
    Args:
        portfolios: List of parsed portfolio data
        mode: Selection mode
        n: Number of top/bottom securities
        
    Returns:
        List of SelectionResult objects
    """
    return [process_portfolio(p, mode, n) for p in portfolios]
