# Configuration Reference

ContribNote stores user settings in a JSON configuration file that persists between sessions.

## File Location

| Platform | Path |
|----------|------|
| macOS | `~/.contribnote/config.json` |
| Windows | `%APPDATA%\ContribNote\config.json` |
| Linux | `~/.config/contribnote/config.json` |

The directory is created automatically on first run.

## Configuration Schema

```json
{
  "prompt_template": "string",
  "developer_prompt": "string",
  "thinking_level": "low" | "medium" | "high" | "xhigh",
  "model": "string",
  "text_verbosity": "low" | "medium" | "high",
  "preferred_sources": ["string"],
  "require_citations": true | false,
  "prioritize_sources": true | false,
  "run_attribution_overview": true | false,
  "attribution_prompt_template": "string",
  "attribution_developer_prompt": "string",
  "attribution_thinking_level": "low" | "medium" | "high" | "xhigh",
  "attribution_model": "string",
  "attribution_text_verbosity": "low" | "medium" | "high",
  "output_folder": "string"
}
```

## Field Reference

### `prompt_template`

**Type:** `string`

The main prompt template sent to the AI for each security. Supports variable interpolation.

**Available Variables:**
| Variable | Description | Injected From |
|----------|-------------|---------------|
| `{ticker}` | Security ticker symbol | Excel row |
| `{security_name}` | Full security name | Excel row |
| `{period}` | Time period | Excel row 6 |
| `{source_instructions}` | Source guidance text | Derived from `preferred_sources` |

**Default:**
```
Write a single paragraph explaining the recent performance of {security_name} ({ticker}) during the period {period}. Focus on key events, earnings, or market factors that influenced the stock.

{source_instructions}
```

**Example Custom Prompt:**
```
Analyze {security_name} ({ticker}) for the period {period}. Include:
- Key price drivers
- Recent news events
- Analyst sentiment

{source_instructions}

Keep response under 150 words.
```

---

### `developer_prompt`

**Type:** `string`

System-level instructions sent as the developer/system message. Controls AI tone, format constraints, and behavioral guidelines.

**Default:**
```
You are a financial analyst assistant. Provide concise, factual commentary suitable for institutional investment reports. Avoid speculation and clearly attribute information to sources when available.
```

**Example Custom Prompt:**
```
You are a senior equity analyst at a large asset manager. Write in a professional, formal tone. Always mention specific dates and figures when available. Do not use phrases like "I think" or "it seems."
```

---

### `thinking_level`

**Type:** `"low"` | `"medium"` | `"high"` | `"xhigh"`

Controls the AI's reasoning effort before responding.

| Value | Behavior | Timeout | Use Case |
|-------|----------|---------|----------|
| `low` | Minimal reasoning | 30s | Quick drafts |
| `medium` | Balanced | 60s | Default |
| `high` | Thorough reasoning | 120s | Complex analysis |
| `xhigh` | Most thorough | 180s | Highest complexity |

**Default:** `"medium"`

---

### `text_verbosity`

**Type:** `"low"` | `"medium"` | `"high"`

Controls response length and detail.

**Default:** `"low"`

---

### `run_attribution_overview`

**Type:** `boolean`

Controls whether the optional portfolio-level attribution overview workflow runs.

**Default:** `false`

---

### `attribution_prompt_template`

**Type:** `string`

Template used for the portfolio-level attribution overview request.

**Available Variables:**
| Variable | Description |
|----------|-------------|
| `{portcode}` | Portfolio code |
| `{period}` | Portfolio period |
| `{sector_attrib}` | Markdown-formatted sector attribution table |
| `{country_attrib}` | Markdown-formatted country attribution table |
| `{source_instructions}` | Source guidance text |

---

### `attribution_developer_prompt`

**Type:** `string`

System/developer instructions for attribution overview requests.

---

### `attribution_thinking_level`

**Type:** `"low"` | `"medium"` | `"high"` | `"xhigh"` (or model-specific supported values)

Reasoning effort for attribution overview requests.

---

### `attribution_model`

**Type:** `string`

Model ID used for attribution overview requests.

---

### `attribution_text_verbosity`

**Type:** `"low"` | `"medium"` | `"high"`

Verbosity level for attribution overview responses.

---

### `preferred_sources`

**Type:** `array of strings`

List of trusted financial news domains. The AI prioritizes these when performing web searches.

**Format Rules:**
- Domain names only (no protocol or path)
- No `https://`, `http://`, or `www.` prefix
- One domain per array element

**Default:**
```json
[
  "reuters.com",
  "bloomberg.com",
  "wsj.com",
  "ft.com",
  "cnbc.com",
  "marketwatch.com",
  "seekingalpha.com"
]
```

**Example Custom List:**
```json
[
  "reuters.com",
  "bloomberg.com",
  "company-website.com",
  "industry-publication.com"
]
```

---

### `output_folder`

**Type:** `string`

Absolute path to the last selected output folder. Used to pre-populate the output folder field on app launch.

**Example:**
```json
"/Users/username/Documents/Commentary Output"
```

**Note:** If the path no longer exists, the field is ignored and the user must select a new folder.

---

## Complete Example

```json
{
  "prompt_template": "Write a single paragraph explaining the recent performance of {security_name} ({ticker}) during the period {period}. Focus on key events, earnings, or market factors that influenced the stock.\n\n{source_instructions}",
  "developer_prompt": "You are a financial analyst assistant. Provide concise, factual commentary suitable for institutional investment reports. Avoid speculation and clearly attribute information to sources when available.",
  "thinking_level": "medium",
  "model": "gpt-5.2-2025-12-11",
  "text_verbosity": "low",
  "preferred_sources": [
    "reuters.com",
    "bloomberg.com",
    "wsj.com",
    "ft.com",
    "cnbc.com",
    "marketwatch.com",
    "seekingalpha.com"
  ],
  "require_citations": true,
  "prioritize_sources": true,
  "run_attribution_overview": false,
  "attribution_prompt_template": "You are preparing a portfolio-level attribution overview for {portcode} covering period {period}.\n\nSector attribution data:\n{sector_attrib}\n\nCountry attribution data:\n{country_attrib}\n\n{source_instructions}",
  "attribution_developer_prompt": "Write a concise, factual attribution overview at the portfolio level.",
  "attribution_thinking_level": "medium",
  "attribution_model": "gpt-5.2-2025-12-11",
  "attribution_text_verbosity": "low",
  "output_folder": "/Users/francisthelen/Documents/Commentary"
}
```

---

## Manual Editing

You can edit the config file directly, but note:

1. **Close the application first** — changes may be overwritten
2. **Validate JSON syntax** — malformed JSON causes config reset
3. **Use absolute paths** — relative paths are not supported
4. **Restart app** — changes take effect on next launch

### Resetting to Defaults

Delete the config file to reset all settings:

```bash
# macOS
rm ~/.contribnote/config.json

# Windows (PowerShell)
Remove-Item "$env:APPDATA\ContribNote\config.json"
```

---

## API Key Storage

**Note:** The API key is NOT stored in this config file for security reasons.

API keys are stored in the system keychain:
- **macOS:** Keychain Access → "ContribNote" service
- **Windows:** Credential Manager → "ContribNote"

To clear a stored API key:
```bash
# macOS
security delete-generic-password -s "ContribNote"

# Windows (PowerShell)
cmdkey /delete:ContribNote
```

Or use the Settings dialog in the app to clear the key field.
