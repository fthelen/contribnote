"""
Ticker Pool Deduplication Engine.

Five-phase pipeline:
  Phase 1: Parse Excel files → PortfolioData
  Phase 2: Select securities per portfolio → SelectionResult
  Phase 3: Build global ticker pool → find what's new vs cached
  Phase 4: Generate only the unique new tickers
  Phase 5: Map Bronze results back to each portfolio

~68% LLM call reduction for batches with high ticker overlap.
"""

import hashlib
import json
import asyncio
import logging
from pathlib import Path
from dataclasses import dataclass

# Reuse Contribnote core (unchanged)
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.excel_parser import PortfolioData, SecurityRow
from src.selection_engine import SelectionResult, SelectionMode, process_portfolios, RankedSecurity
from src.openai_client import OpenAIClient, CommentaryResult, Citation
from src.prompt_manager import PromptManager, PromptConfig, AttributionPromptManager, AttributionPromptConfig

from . import db

logger = logging.getLogger(__name__)


@dataclass
class GenerationSettings:
    model: str
    thinking_level: str
    text_verbosity: str
    require_citations: bool
    use_web_search: bool
    selection_mode: SelectionMode
    top_n: int
    prompt_config: PromptConfig
    attribution_prompt_config: AttributionPromptConfig
    include_attribution_overview: bool = True


@dataclass
class PortfolioBronze:
    commentary_id: str
    portcode: str
    period_label: str
    sections: list[dict]          # ready for db.upsert_section
    citations_by_section: dict    # section_key → list[dict]
    overview_result: dict | None  # attribution overview LLM result
    errors: list[str]


async def run_generation_pipeline(
    portfolios: list[PortfolioData],
    settings: GenerationSettings,
    batch_run_id: str,
    source_files: dict[str, str],
    api_key: str,
    progress_callback=None,
    cancel_event: asyncio.Event | None = None,
) -> list[PortfolioBronze]:
    """
    Main entry point. Returns list of PortfolioBronze, one per portfolio.
    progress_callback(msg: str) is called with human-readable status updates.
    """

    def emit(msg: str):
        if progress_callback:
            progress_callback(msg)
        logger.info(msg)

    cancel_event = cancel_event or asyncio.Event()

    # ---- Phase 2: Selection -------------------------------------------------
    emit("Selecting securities per portfolio…")
    selections = process_portfolios(
        portfolios,
        settings.selection_mode,
        settings.top_n,
    )

    # ---- Phase 3: Build ticker pool -----------------------------------------
    emit("Building ticker pool…")
    config_hash = _prompt_config_hash(settings.prompt_config)

    pool_entries: dict[tuple, dict | None] = {}  # (ticker, period, hash) → pool row
    to_generate: list[tuple] = []                # (ticker, security_name, period)

    for sel in selections:
        for rs in sel.ranked_securities:
            if rs.security.is_cash_or_fee():
                continue
            key = (rs.ticker, sel.period, config_hash)
            if key not in pool_entries:
                existing = db.get_ticker_pool_entry(rs.ticker, sel.period, config_hash)
                pool_entries[key] = existing
                if existing is None or existing["status"] == "failed":
                    to_generate.append((rs.ticker, rs.security_name, sel.period))

    unique_tickers = len(to_generate)
    total_needed = sum(
        sum(1 for rs in sel.ranked_securities if not rs.security.is_cash_or_fee())
        for sel in selections
    )
    emit(f"Ticker pool: {unique_tickers} unique calls needed (vs {total_needed} without dedup)")

    # ---- Phase 4: Generate unique set ---------------------------------------
    client = OpenAIClient(
        api_key=api_key,
        model=settings.model,
        progress_callback=lambda ticker, completed, total: emit(f"  [{ticker}] {completed}/{total}"),
    )

    pm = PromptManager(config=settings.prompt_config)

    if to_generate:
        emit(f"Generating {unique_tickers} ticker(s)…")
        requests = []
        for ticker, security_name, period in to_generate:
            prompt = pm.build_prompt(ticker=ticker, security_name=security_name, period=period)
            requests.append({
                "ticker": ticker,
                "security_name": security_name,
                "prompt": prompt,
                "portcode": "POOL",
            })

        results: list[CommentaryResult] = await client.generate_commentary_batch(
            requests=requests,
            use_web_search=settings.use_web_search,
            thinking_level=settings.thinking_level,
            text_verbosity=settings.text_verbosity,
            require_citations=settings.require_citations,
            cancel_event=cancel_event,
        )

        # Store results in ticker pool
        for result in results:
            key = (result.ticker, _get_period_for_ticker(result.ticker, to_generate), config_hash)
            if result.success:
                citations_json = json.dumps([
                    {"url": c.url, "title": c.title} for c in result.citations
                ])
                pool_id = db.insert_ticker_pool_entry(
                    ticker=result.ticker,
                    security_name=result.security_name,
                    period_label=key[1],
                    prompt_config_hash=config_hash,
                    bronze_text=result.commentary,
                    citations_json=citations_json,
                    model=settings.model,
                )
                pool_entries[key] = db.get_ticker_pool_entry(result.ticker, key[1], config_hash)
            else:
                db.mark_ticker_pool_failed(result.ticker, key[1], config_hash)
                logger.warning(f"Ticker generation failed: {result.ticker} — {result.error_message}")

    # ---- Phase 4b: Attribution overviews (per portfolio, not deduplicated) --
    overview_results: dict[str, dict] = {}
    if settings.include_attribution_overview:
        emit("Generating attribution overviews…")
        apm = AttributionPromptManager(config=settings.attribution_prompt_config)

        overview_requests = []
        for portfolio, sel in zip(portfolios, selections):
            from src.excel_parser import format_attribution_table_markdown
            sector_md = format_attribution_table_markdown(
                portfolio.sector_attribution, "No sector attribution available."
            )
            country_md = format_attribution_table_markdown(
                portfolio.country_attribution, "No country attribution available."
            )
            prompt = apm.build_prompt(
                portcode=portfolio.portcode,
                period=sel.period,
                sector_attrib=sector_md,
                country_attrib=country_md,
            )
            overview_requests.append({
                "portcode": portfolio.portcode,
                "prompt": prompt,
            })

        ov_results = await client.generate_attribution_overview_batch(
            requests=overview_requests,
            use_web_search=settings.use_web_search,
            thinking_level=settings.thinking_level,
            text_verbosity=settings.text_verbosity,
            require_citations=settings.require_citations,
            cancel_event=cancel_event,
        )
        for ov in ov_results:
            if not ov.success:
                logger.warning(f"Overview generation failed: {ov.portcode} — {ov.error_message}")
            overview_results[ov.portcode] = {
                "text": ov.output if ov.success else None,
                "citations": [{"url": c.url, "title": c.title} for c in ov.citations] if ov.success else [],
                "success": ov.success,
                "error": ov.error_message,
            }

    # ---- Phase 5: Map Bronze back to portfolios -----------------------------
    emit("Assembling Bronze files…")
    bronze_results: list[PortfolioBronze] = []

    for portfolio, sel in zip(portfolios, selections):
        commentary_id = f"{portfolio.portcode}_{_normalize_period(sel.period)}"
        errors = []
        sections = []
        citations_by_section = {}

        # Overview section
        ov = overview_results.get(portfolio.portcode)
        overview_text = ov["text"] if ov and ov["success"] else None
        if not overview_text:
            overview_text = f"Attribution overview generation failed: {ov['error'] if ov else 'not run'}"
            errors.append(f"Overview: {ov['error'] if ov else 'skipped'}")

        sections.append({
            "section_key": "overview",
            "section_label": "Overview",
            "section_type": "overview",
            "bronze_text": overview_text,
        })
        if ov and ov.get("citations"):
            citations_by_section["overview"] = _build_citation_records(
                ov["citations"], commentary_id, "overview"
            )

        # Security sections
        rank = 1
        for rs in sel.ranked_securities:
            if rs.security.is_cash_or_fee():
                continue
            key = (rs.ticker, sel.period, config_hash)
            pool_entry = pool_entries.get(key)

            bronze_text = None
            cit_records = []
            pool_id = None

            if pool_entry and pool_entry["status"] == "done":
                bronze_text = pool_entry["bronze_text"]
                pool_id = pool_entry["id"]
                raw_cits = json.loads(pool_entry["citations_json"] or "[]")
                cit_records = _build_citation_records(raw_cits, commentary_id, rs.ticker)
            elif pool_entry and pool_entry["status"] == "failed":
                bronze_text = f"[Generation failed for {rs.ticker}]"
                errors.append(f"{rs.ticker}: generation failed")
            else:
                bronze_text = f"[Not generated: {rs.ticker}]"
                errors.append(f"{rs.ticker}: not in pool")

            sections.append({
                "section_key": rs.ticker,
                "section_label": f"{rs.ticker} — {rs.security_name}",
                "section_type": "security",
                "bronze_text": bronze_text,
                "ticker": rs.ticker,
                "security_name": rs.security_name,
                "security_rank": rank,
                "security_type": rs.security_type.value if rs.security_type else None,
                "contribution": rs.contribution_to_return,
                "weight": rs.port_ending_weight,
                "ticker_pool_id": pool_id,
            })
            if cit_records:
                citations_by_section[rs.ticker] = cit_records
            rank += 1

        # Outlook section (placeholder — filled by PM survey or blank)
        sections.append({
            "section_key": "outlook",
            "section_label": "Outlook",
            "section_type": "outlook",
            "bronze_text": "",
        })

        bronze_results.append(PortfolioBronze(
            commentary_id=commentary_id,
            portcode=portfolio.portcode,
            period_label=sel.period,
            sections=sections,
            citations_by_section=citations_by_section,
            overview_result=ov,
            errors=errors,
        ))

    emit(f"Pipeline complete. {len(bronze_results)} portfolio(s) processed.")
    return bronze_results


async def generate_outlook_from_survey(
    portcode: str,
    period: str,
    survey_answers: dict,
    api_key: str,
    settings: GenerationSettings,
    cancel_event: asyncio.Event | None = None,
) -> dict:
    """Generate Outlook paragraph from PM survey answers."""
    survey_text = "\n".join(
        f"Q: {q}\nA: {a}" for q, a in survey_answers.items() if a
    )
    prompt = (
        f"Write a professional portfolio outlook paragraph for portfolio {portcode}, "
        f"period {period}, based on these PM survey responses:\n\n{survey_text}\n\n"
        "The paragraph should synthesize the PM's views into polished institutional commentary. "
        "One paragraph, 100-150 words."
    )

    client = OpenAIClient(api_key=api_key, model=settings.model)
    from src.openai_client import CommentaryResult
    import httpx

    async with httpx.AsyncClient(timeout=60) as http_client:
        result: CommentaryResult = await client.generate_commentary(
            ticker="OUTLOOK",
            security_name="Portfolio Outlook",
            prompt=prompt,
            portcode=portcode,
            use_web_search=False,
            thinking_level=settings.thinking_level,
            text_verbosity=settings.text_verbosity,
            require_citations=False,
            client=http_client,
            cancel_event=cancel_event or asyncio.Event(),
        )

    return {
        "text": result.commentary if result.success else None,
        "citations": [],
        "success": result.success,
        "error": result.error_message,
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _prompt_config_hash(config: PromptConfig) -> str:
    """Stable hash of prompt configuration for dedup key."""
    data = json.dumps({
        "template": config.template,
        "preferred_sources": sorted(config.preferred_sources),
        "additional_instructions": config.additional_instructions or "",
        "thinking_level": config.thinking_level,
        "prioritize_sources": config.prioritize_sources,
    }, sort_keys=True)
    return hashlib.sha256(data.encode()).hexdigest()[:16]


def _get_period_for_ticker(ticker: str, to_generate: list[tuple]) -> str:
    for t, _name, period in to_generate:
        if t == ticker:
            return period
    return ""


def _normalize_period(period: str) -> str:
    """Turn 'Q4 2025', '2025-Q4', or '12/31/2025 to 1/28/2026' into URL-safe IDs."""
    import re
    normalised = re.sub(r"[^A-Za-z0-9]", "", period).upper()
    if not normalised:
        raise ValueError(f"Period '{period}' normalises to empty string — cannot build commentary ID")
    return normalised


def _build_citation_records(raw_cits: list[dict], commentary_id: str,
                              section_key: str) -> list[dict]:
    from urllib.parse import urlparse
    records = []
    for i, cit in enumerate(raw_cits, 1):
        url = cit.get("url", "")
        title = cit.get("title", "")
        try:
            domain = urlparse(url).netloc.replace("www.", "")
        except Exception:
            domain = ""
        records.append({
            "commentary_id": commentary_id,
            "section_key": section_key,
            "tier": "bronze",
            "url": url,
            "title": title,
            "domain": domain,
            "display_number": i,
            "source_origin": "llm_annotation",
            "bronze_citation_id": None,
            "created_by": "system",
        })
    return records
