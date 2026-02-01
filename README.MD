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
- **Log file**: Details of the run including any errors (in `<output_folder>/log/`)

## Advanced Features

### Thinking Level Configuration

Control how much reasoning the AI uses when generating commentary:
- **Low**: Fastest, minimal reasoning
- **Medium** (default): Balanced speed and quality
- **High**: Most thorough reasoning, slower

Access via the **Prompts & Sources** button → **Thinking Level** dropdown.

### Dual Prompt System

The application supports two types of prompts:
- **User Prompt**: The main template with variables (`{ticker}`, `{security_name}`, `{period}`, `{preferred_sources}`)
- **System Prompt**: Developer-level instructions that guide the AI's behavior

Both are editable in the **Prompts & Sources** modal.

### Configuration Persistence

Your settings are automatically saved after each successful run:
- **macOS**: `~/Library/Application Support/Commentary/config.json`
- **Windows**: `%APPDATA%/Commentary/config.json`

Saved settings include: prompts, thinking level, preferred sources, and last output folder.

## Input File Requirements

FactSet Excel files must have:
- Sheet named `ContributionMasterRisk`
- Headers in row 7: `Ticker`, `Security Name`, `Port. Ending Weight`, `Contribution To Return`, `GICS`
- Data starting in row 10
- Period string in row 6
- Filename pattern: `PORTCODE_*_MMDDYYYY.xlsx` (PORTCODE extracted from text before first underscore)

## Testing with Sample Data

Two sample FactSet files are included for testing:
- `1_12312025_01282026.xlsx` — Portfolio code "1"
- `ABC_12312025_01282026.xlsx` — Portfolio code "ABC"

To verify your installation:
1. Run the application
2. Add both sample files
3. Select an output folder
4. Choose "Top/Bottom 5" mode
5. Click "Generate Commentary"

Expected output: Excel workbook with two sheets ("1" and "ABC"), each containing up to 10 securities (5 contributors + 5 detractors) with AI-generated commentary.

## Troubleshooting

### Common Errors

| Error | Cause | Solution |
|-------|-------|----------|
| "Sheet ContributionMasterRisk not found" | Input file missing required sheet | Verify Excel file is a valid FactSet export |
| "Invalid API key" | API key not set or incorrect | Check environment variable or enter key in Settings |
| "Rate limit exceeded" | Too many API requests | Wait and retry; app handles backoff automatically |
| "No valid securities found" | All rows filtered out (GICS = "NA") | Check input file has non-cash holdings |

### API Key Issues

1. **Environment variable not detected**: Restart terminal after setting `OPENAI_API_KEY`
2. **Keychain access denied**: Grant permission when prompted by your OS
3. **Key works in terminal but not app**: Ensure `.env` file is in project root

### Domain Validation

Preferred sources must be valid domain names:
- ✅ `reuters.com`, `bloomberg.com`
- ❌ `https://reuters.com`, `www.bloomberg.com`

The app automatically cleans common prefixes, but malformed entries are rejected.

## Folder Structure

```
commentary/
├── run_app.py              # Main entry point
├── requirements.txt        # Python dependencies
├── .env.example           # Example environment file
├── 1_12312025_01282026.xlsx      # Sample input file
├── ABC_12312025_01282026.xlsx    # Sample input file
├── src/
│   ├── __init__.py
│   ├── excel_parser.py    # Excel file parsing
│   ├── selection_engine.py # Ranking/selection logic
│   ├── prompt_manager.py  # Prompt template management
│   ├── openai_client.py   # OpenAI API client
│   ├── keystore.py        # System keychain integration
│   ├── output_generator.py # Excel output generation
│   ├── gui.py             # GUI application
│   └── ui_styles.py       # UI styling constants
├── docs/                   # Documentation
│   ├── GUI_GUIDE.md       # Visual GUI walkthrough
│   ├── DEVELOPER_GUIDE.md # Developer setup guide
│   └── CONFIGURATION.md   # Config file reference
└── log/                    # Run logs (created on first run)
```
