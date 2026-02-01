# Copilot Instructions: Commentary Generator

## Project Overview

This is a **Python-based LLM-powered financial commentary generator** that processes FactSet Excel reports to generate AI-written commentary for portfolio contributors and detractors. The project uses OpenAI's Responses API with web search citations.

**Status**: Fully implemented and operational. See [Process_Outline.md](../Process_Outline.md) for the technical specification.

## Technology Stack

- **Language**: Python 3.11+
- **Excel I/O**: `openpyxl` for reading/writing `.xlsx` files
- **HTTP Client**: `httpx` with async support for concurrent API calls
- **Configuration**: Environment variables for secrets, YAML/JSON for app config
- **Secure Storage**: `keyring` for OS keychain access (GUI-entered API key)

## Architecture

```
User Input (Excel files) → Data Extraction → LLM API Calls → Output Workbook
```

### Implemented Modules
1. **Input Parser** (`excel_parser.py`): Reads FactSet Excel files with `openpyxl`, extracts PORTCODE from filename
2. **Selection Engine** (`selection_engine.py`): Ranks securities by contribution (top N contributors/detractors or all holdings)
3. **LLM Client** (`openai_client.py`): OpenAI Responses API with web search citations, async polling, rate limiting
4. **Prompt Manager** (`prompt_manager.py`): Templates with variable interpolation (`{ticker}`, `{security_name}`, `{period}`, `{preferred_sources}`)
5. **Output Generator** (`output_generator.py`): Excel workbook with one sheet per portfolio, formatted columns, log files
6. **GUI** (`gui.py`): Full tkinter interface with settings modal, prompt editor, progress tracking
7. **Keystore** (`keystore.py`): System keychain integration via `keyring`

## FactSet Excel File Format

**Critical layout assumptions** (must be strictly followed):
- Tab name: `ContributionMasterRisk`
- Header row: **row 7**
- Data starts: **row 10**
- Period string: **row 6** (format: `M/D/YYYY to M/D/YYYY`)
- End-of-table marker: first blank `Ticker` cell
- Filter out: rows where `GICS == "NA"` (cash/fees)

**Required columns** (by header text, not position):
- `Ticker`, `Security Name`, `Port. Ending Weight`, `Contribution To Return`, `GICS`

**Filename pattern**: `PORTCODE_*_MMDDYYYY.xlsx` (extract PORTCODE from text before first underscore)

## OpenAI API Integration

**Environment Variable**: `OPENAI_API_KEY` (primary)

**Key Storage Policy**:
- Prefer `OPENAI_API_KEY` when set
- Otherwise use system keychain via `keyring`
- Do not persist API keys in JSON/YAML config files

**Model**: GPT-5.2 via Responses API (not Chat Completions)
- Enable `web_search` tool for citations
- **IMPORTANT**: Web search CANNOT be combined with JSON mode - use plain text output
- Citations are extracted from `url_citation` annotations in the response
- Reasoning effort: user-configurable (`low`, `medium`, `high`) via GUI
- Text verbosity: `low` (one paragraph per security)

**Rate Limiting** (per OpenAI guidelines):
- Use `asyncio.Semaphore` for bounded concurrency (hardcoded default: 20)
- Respect `Retry-After` headers on 429 responses
- Implement exponential backoff: start 1s, max 60s, jitter ±20%
- Track tokens-per-minute (TPM) and requests-per-minute (RPM) from response headers
- Expected batch sizes: 10-100 securities per run

**PII Protection**: Never send portfolio codes to API - use obfuscated UUID keys with local mapping.

**Response format**:
```json
{
  "commentary": "string (single paragraph)",
  "citations": [{ "url": "...", "title": "..." }]
}
```

## Prompt Management

Prompts are **stored in the application** with user-insertable variables using Python string formatting.

**Template variables** (automatically injected):
- `{ticker}` - Security ticker symbol
- `{security_name}` - Full security name
- `{period}` - Time period from Excel (e.g., "12/31/2025 to 1/28/2026")
- `{preferred_sources}` - User's domain allow-list, comma-separated

**Example template**:
```
Write a single paragraph explaining the recent performance of {security_name} ({ticker}) 
during the period {period}. Prioritize sources from: {preferred_sources}.
```

**User customization**:
- Full template override (replace entire prompt)
- Append mode (add instructions to base template)
- Templates stored as plain text files or in config

## User-Configurable Parameters

These must be runtime-configurable (not hardcoded):
- Holdings mode: `Top/Bottom N` vs `All holdings`
- Top/Bottom count: `5` or `10`
- Prompt template (user-editable)
- Preferred source domains (allow-list for web search)
- Citations mode: required (default) vs optional
- Output format: JSON (default) vs plain text

## Output Workbook Format

**Filename**: `ContributorDetractorCommentary_YYYY-MM-DD_HHMM.xlsx`
**Structure**: One sheet per portfolio (sheet name = PORTCODE, max 31 chars)

**Columns**: `Ticker`, `Security Name`, `Rank`, `Contributor/Detractor`, `Contribution To Return`, `Port. Ending Weight`, `Commentary`, `Sources`

**Sources format**:
```
[1] https://example.com/article1
[2] https://example.com/article2
```

## Error Handling Patterns

- **API failures**: Retry with exponential backoff
- **Validation failures**: Write error message directly into Commentary cell (don't skip row)
- **Logging**: One log file per run in `<OUTPUT_FOLDER>/log/` with timestamp, files processed, errors by `PORTCODE|TICKER`

## Testing Considerations

Sample input files are provided in the repo root:
- `1_12312025_01282026.xlsx`
- `ABC_12312025_01282026.xlsx`
