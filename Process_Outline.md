# Process Outline: LLM Commentary for Contributors and Detractors (OpenAI Responses API)
1) Objective
Generate a single commentary paragraph per security for each portfolio’s selected contributors/detractors (or all holdings), using OpenAI’s Responses API and built-in web search citations, and deliver results in a single Excel workbook (one sheet per portfolio).
2) Run Mode (User-Selected Inputs)
Application: A GUI-based desktop application (tkinter) that collects run settings and executes the workflow.
User action: The user selects one or more FactSet report Excel files to process, selects an output folder/location, and starts a run.
Run timing: Runs on demand when initiated by the user.
Configuration persistence: User settings (prompts, thinking level, preferred sources, last output folder) are saved to `~/Library/Application Support/Commentary/config.json` (macOS) or `%APPDATA%/Commentary/config.json` (Windows).
3) Inputs
Source files (user-selected)
Format: Excel (.xlsx) exported from FactSet.
Selection: User selects any number of input workbooks (one workbook per portfolio).
Filename pattern (expected): PORTCODE_*_MMDDYYYY.xlsx
Example: 1_12312025_01282026.xlsx
PORTCODE = everything before the first underscore (_), alphanumeric.
The final MMDDYYYY token is available but not required for downstream logic since the period is read from the sheet.
Sheet & table layout
Tab name (always present): ContributionMasterRisk
Header row: row 7
Data starts: row 10
Period string: row 6, formatted like M/D/YYYY to M/D/YYYY (always present and consistent)
Relevant columns (by header text)
Ticker
Security Name
Port. Ending Weight
Contribution To Return
GICS

User parameters
Holdings selection mode:
- Top/Bottom only: generate commentary only for top contributors and top detractors.
- All holdings: generate commentary for all holdings in the table (still excluding cash/fees rows).
Top/Bottom count (when using Top/Bottom only): N = 5 or N = 10 (user-selected).
Output location: user selects the output folder/location for the generated workbook and logs.
Prompt template: user-editable at runtime (stored as a configurable template, not hard-coded).
Preferred source domains: user-provided allow-list of reputable sites to prioritize for web search.
Citations mode: require citations (default) vs. allow no-citation output (optional for speed/cost).
Output format: JSON (schema-enforced) vs. plain text (optional).
4) Data Extraction and Cleaning
For each input workbook (portfolio):
Open tab ContributionMasterRisk.
Read period from row 6 (e.g., 12/31/2025 to 1/28/2026). This period string will be passed into the LLM prompt as a variable.
Read table beginning at row 10 using the headers on row 7.
Stop condition: Stop reading rows at the first blank Ticker cell (table has no blank rows inside).
Filter out cash/fees: Exclude any row where GICS == "NA" (this excludes cash and fee rows such as FEE_USD).
Ensure numeric fields are parsed:
Contribution To Return (ranking basis)
Port. Ending Weight (tie-breaker)
5) Selection and Ranking Logic
The workflow supports two modes (user-selected):

A) Top/Bottom only (N contributors + N detractors)
- Contributors (Top N)
  - Sort by Contribution To Return descending
  - Keep rows where contribution is positive (if fewer than N positives exist, return as many as available)
  - For ties in Contribution To Return, sort by Port. Ending Weight descending
  - Assign ranks 1–N
- Detractors (Bottom N)
  - Sort by Contribution To Return ascending (most negative first)
  - Keep rows where contribution is negative (if fewer than N negatives exist, return as many as available)
  - Tie-breaker: Port. Ending Weight descending
  - Assign ranks 1–N (rank 1 = worst detractor)

B) All holdings
- Include all rows remaining after cleaning/filtering (excluding cash/fees where GICS == "NA").
- No contributor/detractor ranking is required.
- Labeling still applies based on sign:
  - Positive = Contributor
  - Negative = Detractor
  - Zero = Neutral (optional label; may also be left blank)
6) LLM Request Construction (OpenAI Responses API)
Granularity: one API request per security.
For each selected row:
- Create a unique request key for joining results back to rows.
  - Internal key (PII): PORTCODE|TICKER (used only inside the app).
  - API key (obfuscated): a random UUID or a salted HMAC/sha256 of the internal key.
  - Store a local mapping table: API_KEY -> PORTCODE|TICKER.
  - Do not send PORTCODE (or any other PII) in the API request.
- Provide as inputs:
  - Ticker
  - Security Name
  - Time Period (from row 6)

Model and speed/cost settings
Use OpenAI's Responses API with GPT-5.2.
Request settings:
- model: gpt-5.2
- reasoning: { effort: user-configurable } — selectable in GUI as "low", "medium" (default), or "high"
- text: { verbosity: "low" } (one paragraph; reduces token usage)
- Note: `max_output_tokens` is not enforced; model defaults apply

Citations and reputable-site prioritization
Preferred approach: use built-in web search citations from the Responses API.
- Enable the web_search tool when citations are required.
- **IMPORTANT**: Web search CANNOT be combined with JSON mode (documented API limitation). Use plain text output and extract citations from annotations.
- Apply the user-provided reputable-domain list as a web search allow-list (domain filtering).
- Include citations metadata in the response by reading `message.content[0].annotations` (url_citation objects).
- Optionally include the complete URL list returned by web_search using `include: ["web_search_call.action.sources"]`.

Prompt management (user control)
- Store the prompt as a configurable template (editable without code changes).
- At run time, allow the user to supply:
  - A prompt override (full template replacement), or
  - Additional prompt instructions appended to the base template.
- Inject the reputable-domain list into the prompt (human-readable) in addition to using it for web search filtering (e.g., “Prioritize sources from: …”).

Output format and parsing
**Note**: When using web search (the default), JSON mode is NOT available. The model returns plain text commentary.
- Commentary is returned as plain text in the response message.
- Citations are extracted from the built-in `url_citation` annotations (not from parsed JSON).
- If web search is disabled, JSON mode with Structured Outputs can be used as a fallback.

Citations extraction and spreadsheet population
- Preferred: extract URLs/titles from the built-in `url_citation` annotations in the message output and render the spreadsheet “Sources” column from those annotations.
- If the commentary includes inline markers like [1], [2], assign numbering in order of first appearance of url_citation annotations and render:
  - Commentary: the paragraph text
  - Sources: newline-separated list like `[1] <url>`, `[2] <url>`
7) Execution Flow (Synchronous Responses API)
For each portfolio file:
- Build the list of rows to process based on the user-selected mode:
  - Top/Bottom only: 2N rows (N contributors + N detractors), when available
  - All holdings: all rows remaining after filtering

Request execution:
- Issue one Responses API call per security.
- Run calls concurrently (bounded concurrency) to reduce total wall-clock time.
- Collect each response and join results back to the originating security row using the request key PORTCODE|TICKER.

Operational behavior:
- Implement retry with backoff for transient API errors.
- Capture per-request failures and write errors in-place (see validation rules).
8) Response Validation Rules (No Link Fetching)
Each model response must satisfy (based on chosen output format):

If JSON mode (schema-enforced):
- Response parses as valid JSON matching the schema.
- `commentary` is non-empty.
- If citations are required: the response includes at least one built-in `url_citation` annotation OR at least one citation URL in a `citations` array.

If plain-text mode:
- Commentary text is non-empty.
- If citations are required: at least one built-in `url_citation` annotation is present.

If validation fails:
- Write an error message into the Commentary cell for that security (instead of commentary).
- Record the validation failure in the run log.

No URL resolution or content fetching is performed by this workflow beyond the built-in web_search tool.
9) Output Workbook Generation
One output workbook per run
Output location: Written to the user-selected output folder/location.
Filename format:
ContributorDetractorCommentary_YYYY-MM-DD_HHMM.xlsx
Workbook structure
One sheet per portfolio:
Sheet name = PORTCODE (trim to 31 characters if needed; collisions assumed impossible)
Row layout: one security per row
Ordering: in Top/Bottom mode, contributors rank 1–N first, then detractors rank 1–N. In All-holdings mode, preserve the post-cleaning row order (or optionally sort by absolute Contribution To Return descending).
Columns (confirmed)
Ticker
Security Name
Rank
Contributor/Detractor
Contribution To Return (2 decimals)
Port. Ending Weight (2 decimals)
Commentary (or error text)
Sources (newline-separated, each line includes citation number + URL)
Sources cell format
Preserve as returned by the model (no dedupe).
Expected format:
[1] https://...
[2] https://...
10) Logging
Create one log file per run in a log subfolder under the user-selected output folder/location (e.g., <OUTPUT_FOLDER>/log/).
Log should include:
Run timestamp
List of input files processed
Output workbook path/name
Any validation errors (by PORTCODE|TICKER), plus short error reason
11) Operational Notes / Assumptions
FactSet layout is consistent across all portfolios:
Tab exists
Headers at row 7
Data begins row 10
Ticker blank denotes end-of-table
The prompt will define source quality expectations; automation only enforces minimum “has citations + has URLs.”
Failures are expected early in rollout; process favors transparency (errors in place) over retries until failure modes are understood.
