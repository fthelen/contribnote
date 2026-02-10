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

DEFAULT_ATTRIBUTION_PROMPT_TEMPLATE = """Write a single cohesive portfolio attribution paragraph for {period}. If country attribution is not provided, assume the United States is the focus country.

{source_instructions}

Country Attribution:
{country_attrib}

Sector Attribution:
{sector_attrib}

Focus on:
- The market backdrop relevant to the period
- The main sector or country winners and laggards relevant to portfolio attribution
- Portfolio versus benchmark direction and relative outcome
- The primary allocation and selection drivers shown in the attribution inputs
- DO NOT mention Cash or Fees as attribution drivers, even if they are material contributors in the attribution context.

Requirements:
- Write exactly ONE paragraph (9-12 sentences) with natural transitions
- Only 1-2 senteces on relative performance.
- Keep the prose cohesive and continuous; do not use headings, labels, bullets, or line breaks
- Do not add notes, disclaimers, or postscript text
- Use plain, client-facing language and avoid jargon
- Prefer qualitative descriptions over exact numbers; include precise performance figures only when unavoidable
- Do not invent portfolio, benchmark, sector, or country performance figures
- If a claim cannot be supported, omit it"""

DEFAULT_ATTRIBUTION_DEVELOPER_PROMPT = """Write a single cohesive paragraph that explains portfolio-level attribution in clear client-facing language. Keep the analysis factual, focused on material drivers, and grounded in the provided sector and country attribution inputs. Avoid speculation, section labels, and note-style add-ons, and keep the prose continuous rather than segmented. Never fabricate exact portfolio, benchmark, sector, or country performance figures."""


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
    # Global wire + business press
    "reuters.com",
    "bloomberg.com",
    "wsj.com",
    "ft.com",
    "economist.com",
    "theinformation.com",
    "nikkei.com",
    "asia.nikkei.com",
    "barrons.com",
    "forbes.com",
    "fortune.com",
    "businessinsider.com",
    "cnbc.com",
    "foxbusiness.com",

    # Market data, terminals, and reference
    "tradingeconomics.com",
    "lseg.com",                  # London Stock Exchange Group
    "spglobal.com",              # S&P Global / ratings / data
    "moodys.com",
    "fitchratings.com",
    "morningstar.com",
    "factset.com",
    "refinitiv.com",
    "msci.com",
    "worldbank.org",
    "imf.org",
    "oecd.org",
    "bis.org",
    "ecb.europa.eu",
    "bankofengland.co.uk",
    "federalreserve.gov",
    "bea.gov",                   # US GDP, income, etc.
    "bls.gov",                   # US inflation/jobs
    "census.gov",

    # Company filings and corporate disclosures
    "sec.gov",
    "edgar.sec.gov",
    "companieshouse.gov.uk",     # UK filings
    "sedarplus.ca",              # Canada filings
    "asx.com.au",
    "hkexnews.hk",
    "jpx.co.jp",
    "sgx.com",
    "eur-lex.europa.eu",         # EU regs/directives

    # Energy, commodities, shipping, and supply chain
    "spglobal.com/commodityinsights",
    "iea.org",
    "eia.gov",
    "opec.org",
    "argusmedia.com",
    "platts.com",
    "woodmac.com",
    "bimco.org",
    "clarksons.com",
    "freightwaves.com",

    # Tech/business strategy (useful for macro + sector commentary)
    "theverge.com",
    "wired.com",
    "technologyreview.com",
    "stratechery.com",
    "substack.com",

    # Long-form analysis / think tanks
    "brookings.edu",
    "piie.com",
    "chathamhouse.org",
    "csis.org",
    "cfr.org",

    # US-focused but still widely cited
    "nytimes.com",
    "washingtonpost.com",
    "apnews.com",
    "theguardian.com",
    "latimes.com",

    # Europe
    "handelsblatt.com",          # Germany
    "lesechos.fr",               # France
    "lemonde.fr",
    "ilsole24ore.com",           # Italy
    "elmundo.es",                # Spain
    "expansion.com",             # Spain business
    "thelocal.com",
    "dw.com",

    # Asia-Pacific
    "scmp.com",                  # Hong Kong / China coverage
    "thehindu.com",
    "livemint.com",
    "theaustralian.com.au",
    "afr.com",                   # Australian Financial Review
    "straitstimes.com",
    "channelnewsasia.com",
    "koreajoongangdaily.joins.com",
    "koreaherald.com",

    # Middle East / Africa / LatAm
    "arabnews.com",
    "thenationalnews.com",
    "aljazeera.com",
    "mg.co.za",                  # South Africa
    "dailymaverick.co.za",
    "valor.globo.com",           # Brazil business
    "folha.uol.com.br",
    "reforma.com",               # Mexico (El Financiero alternatives exist too)
    "eleconomista.com.mx",

    # Investor/markets commentary
    "seekingalpha.com",
    "marketwatch.com",
    "finance.yahoo.com",
    "investing.com",
    "tipranks.com",
    "themotleyfool.com",

    # Crypto / digital assets (if relevant)
    "coindesk.com",
    "cointelegraph.com",
    "theblock.co",
]
