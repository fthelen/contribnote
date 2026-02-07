# Developer Guide

This guide covers setup, architecture, and contribution guidelines for ContribNote.

## Prerequisites

- **Python**: 3.11 or higher
- **Operating System**: macOS or Windows (Linux untested)
- **OpenAI API Key**: With access to GPT-5.2 and Responses API

## Development Setup

### 1. Clone the Repository

```bash
git clone https://github.com/fthelen/commentary.git contribnote
cd contribnote
```

### 2. Create Virtual Environment

```bash
python3.11 -m venv .venv
source .venv/bin/activate  # macOS/Linux
# or
.venv\Scripts\activate     # Windows
```

### 3. Install Dependencies

```bash
pip install -r requirements.txt
```

### 4. Configure API Key

For development, use an environment variable:

```bash
export OPENAI_API_KEY="sk-your-key-here"
```

Or create a `.env` file:

```bash
cp .env.example .env
# Edit .env and add your key
```

### 5. Run the Application

```bash
python run_app.py
```

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                         GUI (gui.py)                            │
│  • File selection      • API Settings dialog    • Progress tracking  │
│  • Output folder       • Contribution Settings dialog               │
│                         • Attribution Settings dialog   • Config persistence │
└─────────────────────────────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│                    Orchestration Layer                          │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────┐  │
│  │ excel_parser │  │  selection   │  │   prompt_manager     │  │
│  │              │  │   _engine    │  │                      │  │
│  │ • Parse XLSX │  │ • Rank secs  │  │ • Template variables │  │
│  │ • Extract    │  │ • Top/Bottom │  │ • Source injection   │  │
│  │   period     │  │ • All mode   │  │                      │  │
│  └──────────────┘  └──────────────┘  └──────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│                   API Layer (openai_client.py)                  │
│  • Async HTTP with httpx       • Responses API polling          │
│  • Rate limiting (Semaphore)   • Exponential backoff            │
│  • PII obfuscation (UUID)      • Citation extraction            │
└─────────────────────────────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│                 Output Layer (output_generator.py)              │
│  • Excel workbook creation     • Professional formatting        │
│  • One sheet per portfolio     • Log file generation            │
└─────────────────────────────────────────────────────────────────┘
```

---

## Module Reference

### `excel_parser.py`

Parses FactSet Excel exports with strict layout assumptions.

**Key Classes:**
- `SecurityRow` — Dataclass for a single security's data
- `PortfolioData` — Container for portfolio metadata and securities
- `AttributionRow` / `AttributionTable` — Highest-level attribution rows and totals for sector/country tabs

**Key Functions:**
- `parse_factset_file(path)` → `PortfolioData`
- `extract_portcode(filename)` → `str`
- `format_attribution_table_markdown(table, empty_message)` → `str` for prompt injection

**Attribution Parsing Rules:**
- Metric headers are read from row 7 (column B onward), including effects columns.
- Top-level attribution rows are selected by taking the minimum outline level among non-empty, non-`Total` rows in column A.
- The first-column markdown header is normalized by sheet name (`Country` for `AttributionbyCountryMasterRisk`, `Sector` for `AttributionbySector`, otherwise `Category`).
- Prompt injection formatting is a single markdown table per attribution sheet, with `Total` appended as the final row when present.

**Layout Constants:**
```python
HEADER_ROW = 7
DATA_START_ROW = 10
PERIOD_ROW = 6
SHEET_NAME = "ContributionMasterRisk"
```

### `selection_engine.py`

Implements ranking logic for contributor/detractor selection.

**Key Classes:**
- `RankedSecurity` — Security with rank and classification
- `SelectionResult` — Container for selected securities

**Key Functions:**
- `select_top_bottom(securities, n)` → `SelectionResult`
- `select_all_holdings(securities)` → `SelectionResult`

**Ranking Rules:**
1. Sort by `Contribution To Return` (desc for contributors, asc for detractors)
2. Tie-breaker: `Port. Ending Weight` descending
3. Contributors: positive contribution only
4. Detractors: negative contribution only

### `prompt_manager.py`

Manages prompt templates with variable interpolation.

**Template Variables:**
- `{ticker}` — Security ticker
- `{security_name}` — Full name
- `{period}` — Time period string
- `{source_instructions}` — Source guidance text
- `{preferred_sources}` — Comma-separated domain list (optional)

**Key Functions:**
- `build_prompt(ticker, security_name, period, template_override=None)` → `str`
- `set_template(template)` → `None`
- `set_preferred_sources(sources)` → `None`
- `get_default_preferred_sources()` → `list[str]`

**Attribution Overview Prompting:**
- `AttributionPromptConfig` — Separate config for attribution workflow
- `AttributionPromptManager.build_prompt(portcode, period, sector_attrib, country_attrib, ...)`

### `openai_client.py`

Async OpenAI Responses API client with full feature set.

**Key Classes:**
- `CommentaryResult` — Response container with commentary and citations
- `AttributionOverviewResult` — Portfolio-level attribution overview output + citations
- `OpenAIClient` — Main client class

**Key Features:**
- Bounded concurrency via `asyncio.Semaphore` (default: 20)
- Exponential backoff: 1s initial, 60s max, ±20% jitter
- Response controls: `thinking_level`, `text_verbosity`, `require_citations`
- PII protection: UUID keys with local mapping
- Citation cleaning: removes inline URLs, creates footnotes

**Model Reasoning Levels:**
- `gpt-5.2-2025-12-11`: supports `none`, `low`, `medium`, `high`, `xhigh` (default: `none`)
- `gpt-5.2-pro-2025-12-11`: supports `medium`, `high`, `xhigh` (no `none` or `low`)
- `gpt-5-nano-2025-08-07`: supports `low`, `medium`, `high`
- The GUI reasoning dropdown adapts to the selected model, and the client normalizes any unsupported `thinking_level` values to a valid default.

**Key Methods:**
- `generate_commentary(ticker, security_name, prompt, ...)` → `CommentaryResult`
- `generate_commentary_batch(requests, ...)` → `list[CommentaryResult]`
- `generate_attribution_overview(portcode, prompt, ...)` → `AttributionOverviewResult`
- `generate_attribution_overview_batch(requests, ...)` → `list[AttributionOverviewResult]`

### `output_generator.py`

Creates formatted Excel workbooks and log files.

**Key Functions:**
- `generate_workbook(results, output_path)` → `Path`
- `generate_log(run_info, log_path)` → `Path`

**Excel Formatting:**
- Header row: bold, gray background, borders
- Commentary column: text wrap enabled
- Numeric columns: 2 decimal places
- Error cells: red text color

### `keystore.py`

System keychain integration for secure API key storage.

**Key Functions:**
- `get_api_key()` → `str | None`
- `set_api_key(key)` → `bool`
- `delete_api_key()` → `bool`

**Storage Locations:**
- macOS: Keychain Access (service: "ContribNote")
- Windows: Credential Manager

### `gui.py`

Full tkinter GUI implementation.

**Key Classes:**
- `CommentaryGeneratorApp` — Main application window
- `SettingsModal` — API key configuration dialog
- `PromptEditorModal` — Contribution settings prompt/model editor
- `AttributionWorkflowModal` — Attribution settings prompt/model editor

**Config Persistence:**
- Location: `~/.contribnote/config.json` (macOS/Linux) or `%APPDATA%/ContribNote/config.json` (Windows)
- Saved on successful run completion
- See [CONFIGURATION.md](CONFIGURATION.md) for schema

### `ui_styles.py`

Centralized styling constants for consistent UI.

**Classes:**
- `Spacing` — Padding and margin values
- `Typography` — Font families and sizes
- `Dimensions` — Window and widget sizes

---

## Testing

### Running Tests

```bash
# Run all tests
python -m pytest tests/ -v

# Run tests for a specific module
python -m pytest tests/test_selection_engine.py -v

# Run with short traceback
python -m pytest tests/ -v --tb=short
```

### Test Coverage

| Module | Test File | Description |
|--------|-----------|-------------|
| `excel_parser.py` | `test_excel_parser.py` | SecurityRow, PortfolioData, file parsing |
| `selection_engine.py` | `test_selection_engine.py` | Ranking logic, top/bottom, all holdings |
| `prompt_manager.py` | `test_prompt_manager.py` | Template interpolation, config |
| `output_generator.py` | `test_output_generator.py` | Excel output, log files, result merging |
| `gui.py` (config) | `test_gui_config.py` | Config load/save keys including attribution workflow |

### Sample Files

Two sample FactSet files are included:
- `1_12312025_01282026.xlsx` — Portfolio "1"
- `ABC_12312025_01282026.xlsx` — Portfolio "ABC"

### Manual Testing Checklist

1. **Basic Run**
   - Load both sample files
   - Select Top/Bottom 5 mode
   - Generate commentary
   - Verify output has 2 sheets

2. **All Holdings Mode**
   - Switch to All Holdings
   - Verify all securities processed

3. **Error Handling**
   - Remove API key, verify error message
   - Use invalid file, verify graceful failure

4. **Config Persistence**
   - Change prompt template
   - Close and reopen app
   - Verify template persisted

---

## Code Style

- **Formatter**: Black (optional, default settings)
- **Linter**: Ruff (optional, default settings)
- **Type Hints**: Required for all public functions
- **Docstrings**: Google style

### Example

```python
def parse_factset_file(file_path: Path) -> PortfolioData:
    """Parse a FactSet Excel export file.
    
    Args:
        file_path: Path to the .xlsx file.
        
    Returns:
        PortfolioData containing securities and metadata.
        
    Raises:
        ValueError: If required sheet or columns are missing.
    """
```

---

## AI Coding Agents

For AI assistants (GitHub Copilot, Cursor, Claude, etc.), see [agents.md](../agents.md) in the repo root. It provides:
- Quick architecture overview
- Common task patterns
- Key constraints and gotchas
- Files to read first

## Contributing

1. Create a feature branch from `main`
2. Make changes with appropriate tests
3. Run formatter and linter
4. Submit pull request with clear description

### Commit Messages

Use conventional commits:
- `feat:` New feature
- `fix:` Bug fix
- `docs:` Documentation only
- `refactor:` Code change without behavior change
- `test:` Adding or updating tests
