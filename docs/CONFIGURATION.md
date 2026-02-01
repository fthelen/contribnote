# Configuration Reference

The Commentary Generator stores user settings in a JSON configuration file that persists between sessions.

## File Location

| Platform | Path |
|----------|------|
| macOS | `~/.commentary/config.json` |
| Windows | `%APPDATA%\Commentary\config.json` |
| Linux | `~/.config/Commentary/config.json` |

The directory is created automatically on first run.

## Configuration Schema

```json
{
  "prompt_template": "string",
  "developer_prompt": "string",
  "thinking_level": "low" | "medium" | "high" | "xhigh",
  "text_verbosity": "low" | "medium" | "high",
  "preferred_sources": ["string"],
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
rm ~/Library/Application\ Support/Commentary/config.json

# Windows (PowerShell)
Remove-Item "$env:APPDATA\Commentary\config.json"
```

---

## API Key Storage

**Note:** The API key is NOT stored in this config file for security reasons.

API keys are stored in the system keychain:
- **macOS:** Keychain Access → "Commentary" service
- **Windows:** Credential Manager → "Commentary"

To clear a stored API key:
```bash
# macOS
security delete-generic-password -s "Commentary"

# Windows (PowerShell)
cmdkey /delete:Commentary
```

Or use the Settings dialog in the app to clear the key field.
