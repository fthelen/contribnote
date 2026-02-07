# GUI User Guide

This guide provides a complete walkthrough of the Commentary Generator interface.

## Main Window

![Main Window](screenshots/main_window.png)
*Screenshot placeholder: Add main_window.png showing the full application interface*

### Components

#### 1. API Key Status
Located at the top of the window. Shows whether an API key is configured:
- **Green checkmark**: Key detected (from environment variable or keychain)
- **Red X**: No key configured — click **Settings** to add one

#### 2. Input Files Panel
**Add Files** — Opens file picker to select FactSet Excel files (`.xlsx`)
- Multiple files can be selected at once
- Each file represents one portfolio

**Remove** — Removes selected file(s) from the list

**Clear All** — Removes all files from the list

Files display with their full path. The PORTCODE is extracted from each filename automatically.

#### 3. Output Folder
**Browse** — Select where to save the generated Excel workbook and log files

The last used output folder is remembered between sessions.

#### 4. Holdings Mode
Choose how many securities to process per portfolio:

| Mode | Description |
|------|-------------|
| **Top/Bottom 5** | 5 top contributors + 5 top detractors (up to 10 total) |
| **Top/Bottom 10** | 10 top contributors + 10 top detractors (up to 20 total) |
| **All Holdings** | Every security in the portfolio (excluding cash/fees) |

#### 5. Attribution Overview
`Run Attribution Overview` enables an optional portfolio-level workflow that:
- Parses attribution tabs (`AttributionbySector`, optional `AttributionbyCountryMasterRisk`)
- Runs a separate attribution prompt/model configuration
- Writes one `overview` row above the security-level table

#### 6. Action Buttons
- **Settings** — Opens API key configuration modal
- **Prompts & Sources** — Opens prompt editor and source configuration
- **Attribution Workflow** — Opens separate attribution prompt/model settings
- **Generate Commentary** — Starts the commentary generation process

#### 7. Progress Area
During generation:
- Progress bar shows overall completion
- Status text shows current operation (e.g., "Processing AAPL...")
- Cancel button allows stopping mid-run

---

## Settings Modal

![Settings Modal](screenshots/settings_modal.png)
*Screenshot placeholder: Add settings_modal.png showing the API key dialog*

### API Key Configuration

Enter your OpenAI API key here if not using an environment variable.

**Security Features:**
- Key is masked by default (shows `••••••••`)
- **Hold to Show** button reveals the key while pressed
- Key is stored in your system's secure keychain:
  - macOS: Keychain Access
  - Windows: Credential Manager

**Priority Order:**
1. `OPENAI_API_KEY` environment variable (if set)
2. System keychain (if key was entered in Settings)

---

## Prompts & Sources Modal

![Prompts Modal](screenshots/prompts_modal.png)
*Screenshot placeholder: Add prompts_modal.png showing the tabbed interface*

This modal lets you configure reasoning effort, text verbosity, preferred sources, and prompts.

### User Prompt (Template)

The main prompt template sent to the AI. Supports these variables:

| Variable | Description | Example |
|----------|-------------|---------|
| `{ticker}` | Security ticker symbol | AAPL |
| `{security_name}` | Full security name | Apple Inc. |
| `{period}` | Time period from Excel | 12/31/2025 to 1/28/2026 |
| `{source_instructions}` | Source guidance text | Prioritize information from these reputable sources: ... |

**Default Template:**
```
Write a single paragraph explaining the recent performance of {security_name} ({ticker}) 
during the period {period}. Focus on key events, earnings, or market factors that 
influenced the stock.

{source_instructions}
```

### System Prompt (Instructions)

Developer-level instructions that guide the AI's overall behavior. This is sent as the system message and affects tone, format, and constraints.

**Default System Prompt:**
```
You are a financial analyst assistant. Provide concise, factual commentary 
suitable for institutional investment reports. Avoid speculation and clearly 
attribute information to sources when available.
```

### Reasoning Effort

Controls how much reasoning the AI performs before responding:

| Level | Speed | Quality | Use Case |
|-------|-------|---------|----------|
| **Low** | Fastest | Basic | Quick drafts, simple securities |
| **Medium** | Balanced | Good | Default for most runs |
| **High** | Slowest | Best | Complex situations, final reports |
| **XHigh** | Slowest | Best+ | Most complex situations |

### Text Verbosity

Controls response length and detail:

| Level | Typical Output | Use Case |
|-------|----------------|---------|
| **Low** | Short, concise | Default for most runs |
| **Medium** | More detail | Deeper context |
| **High** | Most detail | Maximum depth |

### Source Instructions Preview

Shows the exact source guidance text that will be injected into the prompt based on your preferred sources.

### Preferred Sources

A list of trusted financial news domains. The AI prioritizes these when searching for information.

**Default Sources:**
- reuters.com
- bloomberg.com
- wsj.com
- ft.com
- cnbc.com
- marketwatch.com
- seekingalpha.com

**Adding/Editing Sources:**
- Enter domain names only (no `https://` or `www.`)
- Comma-separated domain list
- Invalid formats are highlighted in red

---

## Generation Process

### Starting a Run

1. Ensure API key is configured (green checkmark)
2. Add one or more input files
3. Select output folder
4. Choose holdings mode
5. Optionally enable **Run Attribution Overview**
6. Optionally configure **Attribution Workflow**
7. Click **Generate Commentary**

### During Generation

![Progress](screenshots/progress.png)
*Screenshot placeholder: Add progress.png showing the progress bar and status*

The status area shows:
- **Progress bar**: Overall completion percentage
- **Current file**: Which portfolio is being processed
- **Current security**: Which ticker is being analyzed
- **Elapsed time**: How long the run has taken

When attribution workflow is enabled, progress also includes one overview request per portfolio.

### Completion

![Complete](screenshots/complete.png)
*Screenshot placeholder: Add complete.png showing completion message*

On success:
- Dialog shows output file location
- **Open Folder** button to view results
- Log file created in `<output_folder>/log/`

On partial failure:
- Completed securities have commentary
- Failed securities show error message in Commentary column
- Log file contains detailed error information

---

## Output Files

### Excel Workbook

**Filename:** `ContributorDetractorCommentary_YYYY-MM-DD_HHMM.xlsx`

**Structure:** One sheet per portfolio (sheet name = PORTCODE)

When attribution workflow is enabled, each sheet starts with:
- Row 1: `Category | Output | Sources`
- Row 2: `overview | <overview text or warning> | <sources>`
- Row 3: blank separator row
- Row 4+: existing security-level table

**Columns:**
| Column | Description |
|--------|-------------|
| Ticker | Security ticker symbol |
| Security Name | Full company name |
| Rank | Position in contributor/detractor list |
| Contributor/Detractor | Classification based on return contribution |
| Contribution To Return | Numeric contribution (2 decimals) |
| Port. Ending Weight | Portfolio weight percentage (2 decimals) |
| Commentary | AI-generated paragraph (or error message) |
| Sources | Numbered citation URLs |

### Log File

**Location:** `<output_folder>/log/run_log_YYYY-MM-DD_HHMMSS.txt`

**Contents:**
- Run timestamp and duration
- List of input files processed
- Output workbook path
- Any errors (by PORTCODE|TICKER)

---

## Adding Screenshots

To complete this guide, capture screenshots of:

1. **main_window.png** — Full application with sample files loaded
2. **settings_modal.png** — API key dialog with masked key
3. **prompts_modal.png** — Prompts & Sources with User Prompt tab active
4. **progress.png** — Mid-run showing progress bar and status
5. **complete.png** — Completion dialog with success message

Save screenshots to `docs/screenshots/` folder.

**macOS Screenshot Tips:**
- `Cmd + Shift + 4` then `Space` to capture a window
- Hold `Option` while clicking to remove window shadow
