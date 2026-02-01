"""
Prompt Manager Module

Manages prompt templates for LLM requests with variable interpolation.
"""

from dataclasses import dataclass, field
from pathlib import Path
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


@dataclass
class PromptConfig:
    """Configuration for prompt generation."""
    template: str = DEFAULT_PROMPT_TEMPLATE
    preferred_sources: list[str] = field(default_factory=list)
    additional_instructions: str = ""
    thinking_level: str = "medium"
    prioritize_sources: bool = True  # Whether to inject source instructions into prompts


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
