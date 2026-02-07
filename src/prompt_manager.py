"""
Prompt Manager Module

Manages prompt templates for LLM requests with variable interpolation.
"""

from dataclasses import dataclass, field
from typing import Optional


# Default prompt template for generating security commentary
DEFAULT_PROMPT_TEMPLATE = """You are a financial analyst assistant. Write a single, concise paragraph explaining the recent performance of {security_name} ({ticker}) during the period {period}.

Focus on:
- Key business developments, earnings, or news that drove the stock's performance
- Industry or sector trends affecting the company
- Any significant company-specific events (product launches, management changes, M&A activity)

Requirements:
- Write exactly ONE paragraph (3-5 sentences)
- Be factual and cite specific events when possible
- Use professional financial language
- Do not speculate beyond what can be verified through news sources

{source_instructions}"""


SOURCE_INSTRUCTIONS_WITH_PRIORITY = """Prioritize information from these reputable sources: {preferred_sources}. Include citations for key facts."""

SOURCE_INSTRUCTIONS_DEFAULT = """Include citations from reputable financial news sources for key facts."""

DEFAULT_ATTRIBUTION_PROMPT_TEMPLATE = """You are preparing a portfolio-level attribution overview for {portcode} covering period {period}.

Use the supplied attribution data exactly as provided.

Sector attribution data:
{sector_attrib}

Country attribution data:
{country_attrib}

Write one concise paragraph highlighting the most material contributors to attribution and key differences vs benchmark.

{source_instructions}"""

DEFAULT_ATTRIBUTION_DEVELOPER_PROMPT = (
    "Write a concise, factual attribution overview at the portfolio level. "
    "Prioritize material drivers and avoid speculation."
)


@dataclass
class PromptConfig:
    """Configuration for prompt generation."""
    template: str = DEFAULT_PROMPT_TEMPLATE
    preferred_sources: list[str] = field(default_factory=list)
    additional_instructions: str = ""
    thinking_level: str = "medium"
    prioritize_sources: bool = True  # Whether to inject source instructions into prompts


@dataclass
class AttributionPromptConfig:
    """Configuration for portfolio-level attribution prompt generation."""
    template: str = DEFAULT_ATTRIBUTION_PROMPT_TEMPLATE
    preferred_sources: list[str] = field(default_factory=list)
    additional_instructions: str = ""
    thinking_level: str = "medium"
    prioritize_sources: bool = True


class PromptManager:
    """Manages prompt template generation and customization."""
    
    def __init__(self, config: Optional[PromptConfig] = None):
        """
        Initialize the prompt manager.
        
        Args:
            config: Optional configuration for prompt generation
        """
        self.config = config or PromptConfig()
    
    def get_source_instructions(self) -> str:
        """Generate source instructions based on configuration."""
        # Return empty string if source prioritization is disabled
        if not self.config.prioritize_sources:
            return ""
        
        if self.config.preferred_sources:
            sources_str = ", ".join(self.config.preferred_sources)
            return SOURCE_INSTRUCTIONS_WITH_PRIORITY.format(preferred_sources=sources_str)
        return SOURCE_INSTRUCTIONS_DEFAULT
    
    def build_prompt(
        self,
        ticker: str,
        security_name: str,
        period: str,
        template_override: Optional[str] = None
    ) -> str:
        """
        Build a prompt for a specific security.
        
        Args:
            ticker: Security ticker symbol
            security_name: Full security name
            period: Time period string
            template_override: Optional custom template to use
            
        Returns:
            Formatted prompt string
        """
        template = template_override or self.config.template
        
        # Build source instructions
        source_instructions = self.get_source_instructions()
        
        # Format the template
        prompt = template.format(
            ticker=ticker,
            security_name=security_name,
            period=period,
            source_instructions=source_instructions,
            preferred_sources=", ".join(self.config.preferred_sources) if self.config.preferred_sources else ""
        )
        
        # Append additional instructions if provided
        if self.config.additional_instructions:
            prompt += f"\n\nAdditional instructions: {self.config.additional_instructions}"
        
        return prompt
    
    def set_template(self, template: str) -> None:
        """Set a custom prompt template."""
        self.config.template = template
    
    def set_preferred_sources(self, sources: list[str]) -> None:
        """Set preferred source domains."""
        self.config.preferred_sources = sources
    
    def set_additional_instructions(self, instructions: str) -> None:
        """Set additional instructions to append to prompts."""
        self.config.additional_instructions = instructions
    
    def reset_to_default(self) -> None:
        """Reset template to default."""
        self.config.template = DEFAULT_PROMPT_TEMPLATE
        self.config.additional_instructions = ""


class AttributionPromptManager:
    """Manages prompt templates for portfolio-level attribution overviews."""

    def __init__(self, config: Optional[AttributionPromptConfig] = None):
        self.config = config or AttributionPromptConfig()

    def get_source_instructions(self) -> str:
        """Generate source instructions based on configuration."""
        if not self.config.prioritize_sources:
            return ""
        if self.config.preferred_sources:
            sources_str = ", ".join(self.config.preferred_sources)
            return SOURCE_INSTRUCTIONS_WITH_PRIORITY.format(preferred_sources=sources_str)
        return SOURCE_INSTRUCTIONS_DEFAULT

    def build_prompt(
        self,
        portcode: str,
        period: str,
        sector_attrib: str,
        country_attrib: str,
        template_override: Optional[str] = None
    ) -> str:
        """
        Build a portfolio-level attribution prompt.

        Args:
            portcode: Portfolio identifier
            period: Reporting period
            sector_attrib: Markdown-formatted sector attribution context
            country_attrib: Markdown-formatted country attribution context
            template_override: Optional custom template

        Returns:
            Formatted prompt string
        """
        template = template_override or self.config.template
        source_instructions = self.get_source_instructions()

        prompt = template.format(
            portcode=portcode,
            period=period,
            sector_attrib=sector_attrib,
            country_attrib=country_attrib,
            source_instructions=source_instructions,
            preferred_sources=", ".join(self.config.preferred_sources) if self.config.preferred_sources else ""
        )

        if self.config.additional_instructions:
            prompt += f"\n\nAdditional instructions: {self.config.additional_instructions}"

        return prompt


def get_default_preferred_sources() -> list[str]:
    """Return a default list of reputable financial news sources."""
    return [
        "reuters.com",
        "bloomberg.com",
        "wsj.com",
        "ft.com",
        "cnbc.com",
        "seekingalpha.com",
        "marketwatch.com",
        "finance.yahoo.com"
    ]
