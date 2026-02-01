# Commentary Generator

LLM-powered financial commentary generator for portfolio contributors and detractors.

## Quick Start

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

### 2. Set Your OpenAI API Key

Preferred: set it as an environment variable (best for enterprise deployment):
```bash
export OPENAI_API_KEY="sk-your-api-key-here"
```

Or create a `.env` file (copy from `.env.example`) for local development:
```bash
cp .env.example .env
# Then edit .env and add your API key
```

If you enter a key in the app's settings, it will be stored in your system keychain
(macOS Keychain / Windows Credential Manager) and used when `OPENAI_API_KEY` is not set.

### 3. Run the Application

```bash
python run_app.py
```

## Using the Application

1. **Enter your OpenAI API key** (if not set via environment variable)
2. **Add input files**: Click "Add Files" to select your FactSet Excel files
3. **Select output folder**: Choose where to save the generated commentary
4. **Configure settings**:
   - **Holdings Mode**: Select "Top/Bottom N" or "All Holdings"
   - **Top/Bottom Count**: Choose 5 or 10 (only for Top/Bottom mode)
   - **Require Citations**: Check to require source citations
   - **Preferred Sources**: Edit the list of preferred financial news domains
5. **Customize prompt** (optional): Edit the prompt template if needed
6. **Click "Generate Commentary"** to start

## Output

The application generates:
- **Excel workbook**: One sheet per portfolio with commentary and sources
- **Log file**: Details of the run including any errors

## Input File Requirements

FactSet Excel files must have:
- Sheet named `ContributionMasterRisk`
- Headers in row 7: `Ticker`, `Security Name`, `Port. Ending Weight`, `Contribution To Return`, `GICS`
- Data starting in row 10
- Period string in row 6

## Folder Structure

```
commentary/
├── run_app.py              # Main entry point
├── requirements.txt        # Python dependencies
├── .env.example           # Example environment file
├── src/
│   ├── __init__.py
│   ├── excel_parser.py    # Excel file parsing
│   ├── selection_engine.py # Ranking/selection logic
│   ├── prompt_manager.py  # Prompt template management
│   ├── openai_client.py   # OpenAI API client
│   ├── keystore.py        # System keychain integration
│   ├── output_generator.py # Excel output generation
│   └── gui.py             # GUI application
└── [your Excel files]
```
