"""
Tests for the Prompt Manager Module.
"""
import pytest

from src.prompt_manager import (
    DEFAULT_PROMPT_TEMPLATE,
    SOURCE_INSTRUCTIONS_WITH_PRIORITY,
    SOURCE_INSTRUCTIONS_DEFAULT,
    PromptConfig,
    PromptManager,
    get_default_preferred_sources,
)


# --- PromptConfig Tests ---

class TestPromptConfig:
    """Tests for the PromptConfig dataclass."""

    def test_default_values(self):
        """Should have sensible defaults."""
        config = PromptConfig()
        
        assert config.template == DEFAULT_PROMPT_TEMPLATE
        assert config.preferred_sources == []
        assert config.additional_instructions == ""
        assert config.thinking_level == "medium"
        assert config.prioritize_sources is True

    def test_custom_values(self):
        """Should accept custom values."""
        config = PromptConfig(
            template="Custom template",
            preferred_sources=["example.com"],
            additional_instructions="Be brief",
            thinking_level="high",
            prioritize_sources=False
        )
        
        assert config.template == "Custom template"
        assert config.preferred_sources == ["example.com"]
        assert config.additional_instructions == "Be brief"
        assert config.thinking_level == "high"
        assert config.prioritize_sources is False


# --- PromptManager Tests ---

class TestPromptManager:
    """Tests for the PromptManager class."""

    def test_init_with_default_config(self):
        """Should initialize with default config when none provided."""
        manager = PromptManager()
        
        assert manager.config.template == DEFAULT_PROMPT_TEMPLATE

    def test_init_with_custom_config(self):
        """Should use provided config."""
        config = PromptConfig(template="Custom")
        manager = PromptManager(config=config)
        
        assert manager.config.template == "Custom"

    def test_get_source_instructions_with_preferred_sources(self):
        """Should return prioritized source instructions when sources provided."""
        config = PromptConfig(preferred_sources=["reuters.com", "bloomberg.com"])
        manager = PromptManager(config=config)
        
        instructions = manager.get_source_instructions()
        
        assert "reuters.com" in instructions
        assert "bloomberg.com" in instructions
        assert "Prioritize" in instructions

    def test_get_source_instructions_without_preferred_sources(self):
        """Should return default instructions when no sources provided."""
        manager = PromptManager()
        
        instructions = manager.get_source_instructions()
        
        assert instructions == SOURCE_INSTRUCTIONS_DEFAULT

    def test_get_source_instructions_disabled(self):
        """Should return empty string when prioritize_sources is False."""
        config = PromptConfig(prioritize_sources=False)
        manager = PromptManager(config=config)
        
        instructions = manager.get_source_instructions()
        
        assert instructions == ""

    def test_build_prompt_basic(self):
        """Should build prompt with variable interpolation."""
        manager = PromptManager()
        
        prompt = manager.build_prompt(
            ticker="AAPL",
            security_name="Apple Inc.",
            period="12/31/2025 to 1/28/2026"
        )
        
        assert "AAPL" in prompt
        assert "Apple Inc." in prompt
        assert "12/31/2025 to 1/28/2026" in prompt

    def test_build_prompt_with_template_override(self):
        """Should use template override when provided."""
        manager = PromptManager()
        custom_template = "Analyze {ticker} ({security_name}) for {period}. {source_instructions}"
        
        prompt = manager.build_prompt(
            ticker="MSFT",
            security_name="Microsoft Corp.",
            period="Q4 2025",
            template_override=custom_template
        )
        
        assert prompt.startswith("Analyze MSFT")
        assert "Microsoft Corp." in prompt
        assert "Q4 2025" in prompt

    def test_build_prompt_with_additional_instructions(self):
        """Should append additional instructions."""
        config = PromptConfig(additional_instructions="Keep it under 100 words")
        manager = PromptManager(config=config)
        
        prompt = manager.build_prompt(
            ticker="AAPL",
            security_name="Apple Inc.",
            period="Q4 2025"
        )
        
        assert "Additional instructions: Keep it under 100 words" in prompt

    def test_build_prompt_with_preferred_sources(self):
        """Should include preferred sources in prompt."""
        config = PromptConfig(preferred_sources=["wsj.com", "ft.com"])
        manager = PromptManager(config=config)
        
        prompt = manager.build_prompt(
            ticker="AAPL",
            security_name="Apple Inc.",
            period="Q4 2025"
        )
        
        assert "wsj.com" in prompt
        assert "ft.com" in prompt

    def test_set_template(self):
        """Should update the template."""
        manager = PromptManager()
        new_template = "New template: {ticker}"
        
        manager.set_template(new_template)
        
        assert manager.config.template == new_template

    def test_set_preferred_sources(self):
        """Should update preferred sources."""
        manager = PromptManager()
        sources = ["source1.com", "source2.com"]
        
        manager.set_preferred_sources(sources)
        
        assert manager.config.preferred_sources == sources

    def test_set_additional_instructions(self):
        """Should update additional instructions."""
        manager = PromptManager()
        
        manager.set_additional_instructions("Be concise")
        
        assert manager.config.additional_instructions == "Be concise"

    def test_reset_to_default(self):
        """Should reset template and additional instructions to defaults."""
        config = PromptConfig(
            template="Custom template",
            additional_instructions="Custom instructions"
        )
        manager = PromptManager(config=config)
        
        manager.reset_to_default()
        
        assert manager.config.template == DEFAULT_PROMPT_TEMPLATE
        assert manager.config.additional_instructions == ""


# --- get_default_preferred_sources Tests ---

class TestGetDefaultPreferredSources:
    """Tests for the get_default_preferred_sources function."""

    def test_returns_list_of_domains(self):
        """Should return a non-empty list of domain strings."""
        sources = get_default_preferred_sources()
        
        assert isinstance(sources, list)
        assert len(sources) > 0
        for source in sources:
            assert isinstance(source, str)
            assert "." in source  # Should be domain names

    def test_includes_major_financial_sources(self):
        """Should include major financial news sources."""
        sources = get_default_preferred_sources()
        
        # Check for some expected sources
        assert "reuters.com" in sources
        assert "bloomberg.com" in sources
        assert "wsj.com" in sources
