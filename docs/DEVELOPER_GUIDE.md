# Developer Guide

This guide covers setup, architecture, and contribution guidelines for the Commentary Generator.

## Prerequisites

- **Python**: 3.11 or higher
- **Operating System**: macOS or Windows (Linux untested)
- **OpenAI API Key**: With access to GPT-5.2 and Responses API

## Development Setup

### 1. Clone the Repository

```bash
git clone https://github.com/fthelen/commentary.git
cd commentary
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
│  • File selection      • Settings modal    • Progress tracking  │
│  • Output folder       • Prompt editor     • Config persistence │
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

**Key Functions:**
- `parse_factset_file(path)` → `PortfolioData`
- `extract_portcode(filename)` → `str`

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
- `{preferred_sources}` — Comma-separated domain list

**Key Functions:**
- `build_prompt(template, security, period, sources)` → `str`
- `get_default_template()` → `str`
- `get_default_sources()` → `list[str]`

### `openai_client.py`

Async OpenAI Responses API client with full feature set.

**Key Classes:**
- `CommentaryResult` — Response container with commentary and citations
- `OpenAIClient` — Main client class

**Key Features:**
- Bounded concurrency via `asyncio.Semaphore` (default: 20)
- Exponential backoff: 1s initial, 60s max, ±20% jitter
- PII protection: UUID keys with local mapping
- Citation cleaning: removes inline URLs, creates footnotes

**Key Methods:**
- `generate_commentary(security, period, prompt, sources)` → `CommentaryResult`
- `generate_batch(securities, ...)` → `list[CommentaryResult]`

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
- macOS: Keychain Access (service: "Commentary")
- Windows: Credential Manager

### `gui.py`

Full tkinter GUI implementation.

**Key Classes:**
- `CommentaryApp` — Main application window
- `SettingsModal` — API key configuration dialog
- `PromptsModal` — Prompt editor with tabs

**Config Persistence:**
- Location: `~/Library/Application Support/Commentary/config.json` (macOS)
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

- **Formatter**: Black (default settings)
- **Linter**: Ruff
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
