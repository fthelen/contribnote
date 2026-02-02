# AI Agent Guide

> **Purpose**: This file helps AI coding agents (GitHub Copilot, Cursor, Claude, etc.) understand this repository quickly and make accurate changes.

## Project Overview

**ContribNote** is a Python desktop application that generates LLM-powered financial commentary for portfolio contributors and detractors. It reads FactSet Excel exports, calls OpenAI's Responses API with web search for citations, and outputs formatted Excel workbooks.

### Tech Stack

- **Language**: Python 3.11+
- **GUI**: tkinter
- **Excel**: openpyxl
- **HTTP**: httpx (async)
- **API**: OpenAI Responses API (GPT-5.2)
- **Secrets**: keyring (system keychain)
- **Testing**: pytest

## Architecture

```
run_app.py              # Entry point
src/
├── gui.py              # tkinter GUI, main application window
├── excel_parser.py     # Parse FactSet Excel files
├── selection_engine.py # Rank securities, select top/bottom
├── prompt_manager.py   # Build prompts with variable interpolation
├── openai_client.py    # Async OpenAI API client
├── output_generator.py # Create Excel workbooks and logs
├── keystore.py         # System keychain for API key storage
└── ui_styles.py        # Centralized UI styling constants
tests/
├── test_excel_parser.py
├── test_selection_engine.py
├── test_prompt_manager.py
└── test_output_generator.py
```

## Key Concepts

### FactSet Excel Layout

Files follow a strict layout:
- **Sheet**: `ContributionMasterRisk`
- **Row 6**: Period string (e.g., "12/31/2025 to 1/28/2026")
- **Row 7**: Headers (Ticker, Security Name, Port. Ending Weight, Contribution To Return, GICS)
- **Row 10+**: Data rows (stop at first blank Ticker)
- **Filename**: `PORTCODE_*_MMDDYYYY.xlsx` (PORTCODE = text before first underscore)

### Selection Modes

1. **Top/Bottom N**: Select N contributors (positive contribution) + N detractors (negative contribution)
   - Sort by Contribution To Return
   - Tie-breaker: Port. Ending Weight descending
2. **All Holdings**: Process all securities (exclude cash/fees where GICS == "NA")

### OpenAI API Usage

- Uses **Responses API** with `web_search` tool for citations
- **Important**: Web search cannot be combined with JSON mode—output is always plain text
- Citations extracted from `url_citation` annotations
- Rate limiting via asyncio.Semaphore (default 20 concurrent)
- PII protection: UUIDs map to PORTCODE|TICKER internally

## Data Flow

```
Input Excel → excel_parser → selection_engine → prompt_manager → openai_client → output_generator → Output Excel
```

## Common Tasks

### Adding a New Column to Output

1. Add field to `OutputRow` in [output_generator.py](src/output_generator.py)
2. Update `merge_results()` to populate the field
3. Add header to `headers` list in `create_output_workbook()`
4. Add column width to `column_widths` list
5. Write cell data in the data row loop

### Modifying Selection Logic

- Edit [selection_engine.py](src/selection_engine.py)
- `select_top_bottom()` for ranked mode
- `select_all_holdings()` for all mode
- Run tests: `python -m pytest tests/test_selection_engine.py -v`

### Changing Prompt Template

- Default template in [prompt_manager.py](src/prompt_manager.py)
- Variables: `{ticker}`, `{security_name}`, `{period}`, `{source_instructions}`
- User can override via GUI

### Adding API Parameters

- Modify `_make_request()` in [openai_client.py](src/openai_client.py)
- Update request body structure
- Handle new response fields in parsing

## Testing

```bash
# Run all tests
python -m pytest tests/ -v

# Run specific module tests
python -m pytest tests/test_selection_engine.py -v

# Run with coverage (if pytest-cov installed)
python -m pytest tests/ --cov=src --cov-report=term-missing
```

### Test Patterns

- Use `@patch` to mock `openpyxl.load_workbook` for Excel tests
- Use `tempfile.TemporaryDirectory()` for file output tests
- Helper functions create test data (`make_security()`, `make_portfolio()`, etc.)

## Configuration Files

| File | Purpose |
|------|---------|
| `requirements.txt` | Python dependencies |
| `.env.example` | Template for environment variables |
| `config.json` | User settings (created at runtime in app support folder) |

### Config Locations

- **macOS**: `~/Library/Application Support/Commentary/config.json`
- **Windows**: `%APPDATA%/Commentary/config.json`

## Important Constraints

1. **No JSON mode with web search**: OpenAI API limitation—use plain text output
2. **Excel sheet name limit**: 31 characters max (truncate PORTCODE if needed)
3. **GICS == "NA"**: Indicates cash/fee rows—always filter these out
4. **Period from row 6**: Always read from cell A6, not filename

## Code Style

- **Formatter**: Black
- **Type hints**: Required for all public functions
- **Docstrings**: Google style
- **Imports**: Standard library → third-party → local

## Key Files to Read First

1. [Process_Outline.md](Process_Outline.md) — Full workflow specification
2. [docs/DEVELOPER_GUIDE.md](docs/DEVELOPER_GUIDE.md) — Architecture and module reference
3. [src/openai_client.py](src/openai_client.py) — Core API integration
4. [src/selection_engine.py](src/selection_engine.py) — Business logic for ranking

## Recent Changes

- Removed JSON mode references (web search requires plain text)
- Added comprehensive test suite (77 tests across 4 modules)
