# CommentaryFlow — Claude Code Context

> **Note:** All other docs in this repo (`README.MD`, `CONTRIBUTING.md`, `SECURITY.md`)
> describe ContribNote (the original desktop app) and are scheduled for rewrite.
> Treat this file as the authoritative context.

## What this repo is

CommentaryFlow is a local-first portfolio commentary pipeline — FastAPI backend + vanilla JS SPA.
Writers upload FactSet Excel files, LLM generates Bronze commentary with ticker deduplication,
writers edit to Silver, compliance reviews, Gold is approved and exported for Snowflake.

## Environment
- Always use `.venv/bin/python` directly — shell `activate` doesn't persist between Bash tool calls
- Install deps: `.venv/bin/pip install -r requirements.txt`

## Run commands
- Start app: `.venv/bin/python -m commentaryflow.run` → opens browser at localhost:8000
- Verify imports: `.venv/bin/python -c "from commentaryflow.app import app"`
- Create Word/survey templates (one-time): `.venv/bin/python commentaryflow/create_templates.py`
- Run tests: `.venv/bin/python -m pytest tests/ -v`

## Repo structure
```
commentaryflow/     FastAPI app (all new feature code goes here)
  app.py            All routes
  auth.py           JWT auth — IT replaces with Azure AD
  db.py             SQLite schema and queries (zero ORM)
  dedup.py          Five-phase generation pipeline with ticker-pool deduplication
  export.py         Word/PDF export + Snowflake-ready CSV
  run.py            Entry point
  static/           Vanilla JS SPA (no build step)
  templates/        Portfolio-specific Word letterhead (.docx)
  surveys/          PM survey Excel template
src/                Shared pipeline core — DO NOT MODIFY
  openai_client.py  Async OpenAI Responses API client
  excel_parser.py   FactSet Excel parsing
  prompt_manager.py Prompt template management
  selection_engine.py Security ranking logic
tests/
  fixtures/         Sample FactSet .xlsx files for integration testing
```

## Key constraints
- `src/` modules are reused unchanged from Contribnote. Do not modify them.
- `dedup.py` uses `sys.path.insert(0, parent_dir)` to import `src/` — intentional.
- Do NOT use `passlib[bcrypt]` — incompatible with bcrypt>=4.x. Use `bcrypt` directly.
- Web search + JSON mode cannot be combined (OpenAI API limitation) — always plain text output.
- GICS == "NA", "—", or "--" → cash/fee row → always filtered out before generation.

## Auth / users
- Default seed users (created on first `db.init_db()`):
  - `writer1 / writer123` — Writer role
  - `compliance1 / compliance123` — Reviewer role
- API key stored in SQLite `app_settings` table (set via Settings UI or `OPENAI_API_KEY` env var)
- DB file `commentaryflow/commentaryflow.db` is gitignored; auto-created on first run

## FactSet Excel layout (for `src/excel_parser.py`)
- Sheet: `ContributionMasterRisk`; Period: row 6; Headers: row 7; Data: row 10+
- Filename: `PORTCODE_*.xlsx` — portcode = text before first underscore

## Branching
- `main` = Contribnote desktop app (do not merge into)
- `commentaryflow` = this app (soft fork, standalone going forward)
