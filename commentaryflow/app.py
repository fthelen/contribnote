"""
CommentaryFlow FastAPI application.
All routes live here — auth, batch runs, commentary, sections, citations, export.
"""

import asyncio
import json
import logging
import os
import sys
import tempfile
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

import httpx
from fastapi import (
    BackgroundTasks, Depends, FastAPI, File, Form, HTTPException,
    Request, UploadFile, status
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.security import OAuth2PasswordRequestForm
from fastapi.staticfiles import StaticFiles

# Bootstrap path so src/ is importable
sys.path.insert(0, str(Path(__file__).parent.parent))

from . import db, auth, export as exp
from .dedup import (
    GenerationSettings, run_generation_pipeline,
    generate_outlook_from_survey, _normalize_period, _prompt_config_hash
)
from src.excel_parser import parse_excel_file, parse_multiple_files
from src.selection_engine import SelectionMode
from src.prompt_manager import PromptConfig, AttributionPromptConfig, get_default_preferred_sources

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# App setup
# ---------------------------------------------------------------------------

app = FastAPI(title="CommentaryFlow", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:8000", "http://127.0.0.1:8000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve static SPA
STATIC_DIR = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.on_event("startup")
async def startup():
    db.init_db()
    # Recover any commentaries stuck in 'generating' from a previous crashed/killed session
    stuck = db.list_commentaries(status_filter="generating")
    for c in stuck:
        db.update_commentary_status(c["commentary_id"], "error")
        logger.warning(f"Recovered stuck commentary {c['commentary_id']} → error")
    if stuck:
        logger.info(f"Recovered {len(stuck)} stuck commentary(s) from previous session")
    logger.info("CommentaryFlow started. DB initialized.")


# ---------------------------------------------------------------------------
# In-memory SSE event queues keyed by run_id
# ---------------------------------------------------------------------------

_sse_queues: dict[str, asyncio.Queue] = {}
_cancel_events: dict[str, asyncio.Event] = {}


# ---------------------------------------------------------------------------
# Root — serve SPA
# ---------------------------------------------------------------------------

@app.get("/")
async def serve_spa():
    return FileResponse(str(STATIC_DIR / "index.html"))


# ---------------------------------------------------------------------------
# Auth routes
# ---------------------------------------------------------------------------

@app.post("/auth/token")
async def login(form_data: OAuth2PasswordRequestForm = Depends()):
    user = auth.authenticate_user(form_data.username, form_data.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    token = auth.create_access_token({
        "sub": user["id"],
        "role": user["role"],
        "display_name": user["display_name"],
    })
    return {
        "access_token": token,
        "token_type": "bearer",
        "role": user["role"],
        "display_name": user["display_name"],
    }


@app.get("/auth/me")
async def get_me(current_user: dict = Depends(auth.get_current_user)):
    return {
        "id": current_user["id"],
        "username": current_user["username"],
        "display_name": current_user["display_name"],
        "role": current_user["role"],
    }


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------

@app.get("/api/settings")
async def get_settings(current_user: dict = Depends(auth.get_current_user)):
    settings = db.get_settings()
    # Never expose the API key value in full
    if settings.get("openai_api_key"):
        settings["openai_api_key_set"] = True
        settings["openai_api_key"] = "••••••••"
    else:
        settings["openai_api_key_set"] = False
    return settings


@app.put("/api/settings")
async def update_settings(
    payload: dict,
    current_user: dict = Depends(auth.require_writer)
):
    allowed_keys = {
        "openai_api_key", "default_model", "thinking_level",
        "text_verbosity", "selection_mode", "top_n",
        "require_citations", "use_web_search",
    }
    for key, value in payload.items():
        if key in allowed_keys:
            db.update_setting(key, str(value))
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Template management
# ---------------------------------------------------------------------------

TEMPLATES_DIR = Path(__file__).parent / "templates"


@app.get("/api/templates")
async def list_templates(current_user: dict = Depends(auth.get_current_user)):
    portfolio_dir = TEMPLATES_DIR / "portfolios"
    portfolio_dir.mkdir(parents=True, exist_ok=True)
    templates = []
    for f in portfolio_dir.glob("*.docx"):
        templates.append({"portcode": f.stem, "filename": f.name})
    has_base = (TEMPLATES_DIR / "base_letterhead.docx").exists()
    return {"portfolios": templates, "has_base_letterhead": has_base}


@app.post("/api/templates/{portcode}")
async def upload_template(
    portcode: str,
    file: UploadFile = File(...),
    current_user: dict = Depends(auth.require_writer)
):
    if not file.filename.endswith(".docx"):
        raise HTTPException(400, "Only .docx files accepted")
    dest = TEMPLATES_DIR / "portfolios" / f"{portcode.upper()}.docx"
    dest.parent.mkdir(parents=True, exist_ok=True)
    content = await file.read()
    dest.write_bytes(content)
    return {"status": "uploaded", "portcode": portcode.upper()}


@app.post("/api/templates/base")
async def upload_base_template(
    file: UploadFile = File(...),
    current_user: dict = Depends(auth.require_writer)
):
    if not file.filename.endswith(".docx"):
        raise HTTPException(400, "Only .docx files accepted")
    dest = TEMPLATES_DIR / "base_letterhead.docx"
    content = await file.read()
    dest.write_bytes(content)
    return {"status": "uploaded", "path": "base_letterhead.docx"}


# ---------------------------------------------------------------------------
# Batch runs — file upload + generation
# ---------------------------------------------------------------------------

@app.post("/api/runs")
async def start_run(
    background_tasks: BackgroundTasks,
    files: list[UploadFile] = File(...),
    survey_file: Optional[UploadFile] = File(None),
    settings_json: str = Form("{}"),
    current_user: dict = Depends(auth.require_writer)
):
    """
    Start a new generation batch.
    Files: one or more FactSet Excel files (one per portfolio).
    Optional survey_file: PM survey Excel.
    settings_json: JSON string with overrides for generation settings.
    """
    if not files:
        raise HTTPException(400, "No files uploaded")

    # Save uploaded files to temp dir
    tmp_dir = Path(tempfile.mkdtemp(prefix="cf_run_"))
    saved_paths = []
    for f in files:
        dest = tmp_dir / f.filename
        content = await f.read()
        dest.write_bytes(content)
        saved_paths.append(dest)

    survey_path = None
    if survey_file:
        survey_dest = tmp_dir / survey_file.filename
        content = await survey_file.read()
        survey_dest.write_bytes(content)
        survey_path = survey_dest

    overrides = json.loads(settings_json)

    # Build settings from DB defaults + overrides
    app_settings = db.get_settings()
    api_key = overrides.get("openai_api_key") or app_settings.get("openai_api_key") or os.getenv("OPENAI_API_KEY", "")
    if not api_key:
        raise HTTPException(400, "OpenAI API key not configured. Go to Settings.")

    gen_settings = _build_generation_settings(app_settings, overrides)
    run_id = db.create_batch_run(json.dumps(overrides), current_user["username"])

    queue: asyncio.Queue = asyncio.Queue()
    cancel_ev = asyncio.Event()
    _sse_queues[run_id] = queue
    _cancel_events[run_id] = cancel_ev

    background_tasks.add_task(
        _run_generation_task,
        run_id=run_id,
        file_paths=saved_paths,
        survey_path=survey_path,
        gen_settings=gen_settings,
        api_key=api_key,
        queue=queue,
        cancel_event=cancel_ev,
        started_by=current_user["username"],
    )

    return {"run_id": run_id, "status": "started"}


@app.get("/api/runs/{run_id}")
async def get_run(run_id: str, current_user: dict = Depends(auth.get_current_user)):
    run = db.get_batch_run(run_id)
    if not run:
        raise HTTPException(404, "Run not found")
    return run


@app.get("/api/runs/{run_id}/stream")
async def stream_run_events(run_id: str, request: Request):
    """SSE endpoint for live progress updates."""
    queue = _sse_queues.get(run_id)
    if not queue:
        # Run may have already completed — return empty stream
        async def empty():
            yield "data: {\"type\":\"done\"}\n\n"
        return StreamingResponse(empty(), media_type="text/event-stream")

    async def event_generator():
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    msg = await asyncio.wait_for(queue.get(), timeout=30)
                    yield f"data: {json.dumps(msg)}\n\n"
                    if msg.get("type") == "done":
                        break
                except asyncio.TimeoutError:
                    yield "data: {\"type\":\"ping\"}\n\n"
        finally:
            _sse_queues.pop(run_id, None)

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@app.post("/api/runs/{run_id}/cancel")
async def cancel_run(run_id: str, current_user: dict = Depends(auth.require_writer)):
    ev = _cancel_events.get(run_id)
    if ev:
        ev.set()
        db.update_batch_run(run_id, status="cancelled")
        return {"status": "cancelled"}
    raise HTTPException(404, "Run not found or already finished")


# ---------------------------------------------------------------------------
# Commentaries
# ---------------------------------------------------------------------------

@app.get("/api/commentaries")
async def list_commentaries(
    status: Optional[str] = None,
    period: Optional[str] = None,
    current_user: dict = Depends(auth.get_current_user)
):
    items = db.list_commentaries(status_filter=status, period_filter=period)
    # Annotate each with section counts
    for item in items:
        counts = db.count_sections_for_commentary(item["commentary_id"])
        item["section_counts"] = counts
    return {"commentaries": items, "periods": db.get_distinct_periods()}


@app.get("/api/commentaries/{commentary_id}")
async def get_commentary(
    commentary_id: str,
    current_user: dict = Depends(auth.get_current_user)
):
    commentary = db.get_commentary(commentary_id)
    if not commentary:
        raise HTTPException(404, "Commentary not found")
    sections = db.get_sections(commentary_id)
    annotations = db.get_annotations(commentary_id)

    # Attach citation count per section
    for s in sections:
        bronze_cits = db.get_citations(commentary_id, s["section_key"], "bronze")
        silver_cits = db.get_citations(commentary_id, s["section_key"], "silver")
        s["bronze_citation_count"] = len(bronze_cits)
        s["silver_citation_count"] = len(silver_cits)

        # Shared ticker info
        if s.get("ticker") and s["section_type"] == "security":
            shared = db.get_sections_sharing_ticker(
                s["ticker"], commentary["period_label"], commentary_id
            )
            s["shared_portfolio_count"] = len(shared)
            s["shared_portfolios"] = [
                {"commentary_id": sh["commentary_id"], "portcode": sh["portcode"]}
                for sh in shared
            ]
        else:
            s["shared_portfolio_count"] = 0
            s["shared_portfolios"] = []

    return {
        "commentary": commentary,
        "sections": sections,
        "annotations": annotations,
        "section_counts": db.count_sections_for_commentary(commentary_id),
    }


@app.post("/api/commentaries/{commentary_id}/submit")
async def submit_commentary(
    commentary_id: str,
    current_user: dict = Depends(auth.require_writer)
):
    commentary = db.get_commentary(commentary_id)
    if not commentary:
        raise HTTPException(404)
    if commentary["status"] not in ("draft", "changes_requested"):
        raise HTTPException(400, f"Cannot submit from status: {commentary['status']}")
    db.update_commentary_status(
        commentary_id, "in_review", submitted_by=current_user["username"]
    )
    return {"status": "in_review"}


@app.post("/api/commentaries/{commentary_id}/approve")
async def approve_commentary(
    commentary_id: str,
    current_user: dict = Depends(auth.require_reviewer)
):
    commentary = db.get_commentary(commentary_id)
    if not commentary:
        raise HTTPException(404)
    if commentary["status"] != "in_review":
        raise HTTPException(400, f"Cannot approve from status: {commentary['status']}")

    # Approve all sections and snapshot gold citations
    sections = db.get_sections(commentary_id)
    for s in sections:
        db.approve_section(commentary_id, s["section_key"], current_user["username"])
        db.snapshot_gold_citations(commentary_id, s["section_key"])

    db.update_commentary_status(
        commentary_id, "approved", approved_by=current_user["username"]
    )

    # Generate Gold files
    try:
        gold_sections = db.get_sections(commentary_id)
        exp.save_gold_json(commentary_id, gold_sections)
        exp.export_snowflake_csvs(commentary_id)
        exp.save_metadata_json(commentary_id, {
            "commentary_id": commentary_id,
            "portcode": commentary["portcode"],
            "period_label": commentary["period_label"],
            "approved_at": commentary.get("approved_at"),
            "approved_by": commentary.get("approved_by"),
        })
    except Exception as e:
        logger.error(f"Gold export error for {commentary_id}: {e}")

    return {"status": "approved"}


@app.post("/api/commentaries/{commentary_id}/reject")
async def reject_commentary(
    commentary_id: str,
    payload: dict = {},
    current_user: dict = Depends(auth.require_reviewer)
):
    commentary = db.get_commentary(commentary_id)
    if not commentary:
        raise HTTPException(404)
    if commentary["status"] != "in_review":
        raise HTTPException(400, f"Cannot reject from status: {commentary['status']}")
    db.update_commentary_status(commentary_id, "changes_requested")
    # Optionally save a general annotation
    note = payload.get("note") if payload else None
    if note:
        db.add_annotation(commentary_id, "general", note, current_user["username"])
    return {"status": "changes_requested"}


@app.post("/api/commentaries/{commentary_id}/publish")
async def publish_commentary(
    commentary_id: str,
    current_user: dict = Depends(auth.get_current_user)
):
    commentary = db.get_commentary(commentary_id)
    if not commentary:
        raise HTTPException(404)
    if commentary["status"] != "approved":
        raise HTTPException(400, f"Commentary must be approved before publishing")
    db.update_commentary_status(commentary_id, "published")
    return {"status": "published"}


# ---------------------------------------------------------------------------
# Sections
# ---------------------------------------------------------------------------

@app.get("/api/commentaries/{commentary_id}/sections/{section_key}")
async def get_section(
    commentary_id: str,
    section_key: str,
    current_user: dict = Depends(auth.get_current_user)
):
    section = db.get_section(commentary_id, section_key)
    if not section:
        raise HTTPException(404, "Section not found")

    bronze_cits = db.get_citations(commentary_id, section_key, "bronze")
    silver_cits = db.get_citations(commentary_id, section_key, "silver")
    flags = db.get_citation_flags(commentary_id, section_key)

    commentary = db.get_commentary(commentary_id)
    shared = []
    if section.get("ticker") and section["section_type"] == "security":
        shared = db.get_sections_sharing_ticker(
            section["ticker"], commentary["period_label"], commentary_id
        )

    return {
        "section": section,
        "bronze_citations": bronze_cits,
        "silver_citations": silver_cits,
        "citation_flags": flags,
        "shared_portfolios": [
            {"commentary_id": s["commentary_id"], "portcode": s["portcode"]}
            for s in shared
        ],
    }


@app.put("/api/commentaries/{commentary_id}/sections/{section_key}")
async def save_silver_section(
    commentary_id: str,
    section_key: str,
    payload: dict,
    current_user: dict = Depends(auth.require_writer)
):
    commentary = db.get_commentary(commentary_id)
    if not commentary:
        raise HTTPException(404)
    if commentary["status"] in ("in_review", "approved", "published"):
        raise HTTPException(400, "Commentary is locked for editing")

    silver_text = payload.get("silver_text", "")
    db.save_silver(commentary_id, section_key, silver_text)

    # Seed silver citations if first save
    db.seed_silver_citations(commentary_id, section_key)

    # Update commentary status to draft if it was just not_started
    if commentary["status"] == "not_started":
        db.update_commentary_status(commentary_id, "draft")

    return {"status": "saved", "section_key": section_key}


@app.post("/api/commentaries/{commentary_id}/sections/{section_key}/approve")
async def approve_section(
    commentary_id: str,
    section_key: str,
    current_user: dict = Depends(auth.require_reviewer)
):
    db.approve_section(commentary_id, section_key, current_user["username"])
    db.snapshot_gold_citations(commentary_id, section_key)
    return {"status": "approved"}


@app.post("/api/commentaries/{commentary_id}/sections/{section_key}/annotate")
async def annotate_section(
    commentary_id: str,
    section_key: str,
    payload: dict,
    current_user: dict = Depends(auth.require_reviewer)
):
    note = payload.get("note", "").strip()
    if not note:
        raise HTTPException(400, "Note is required")
    ann_id = db.add_annotation(commentary_id, section_key, note, current_user["username"])
    return {"annotation_id": ann_id}


@app.post("/api/commentaries/{commentary_id}/sections/{section_key}/copy-to-portfolios")
async def copy_silver_to_portfolios(
    commentary_id: str,
    section_key: str,
    payload: dict,
    current_user: dict = Depends(auth.require_writer)
):
    """Copy this section's Silver text to the same ticker section in other portfolios."""
    target_ids: list[str] = payload.get("commentary_ids", [])
    if not target_ids:
        raise HTTPException(400, "No target commentary IDs provided")

    source_section = db.get_section(commentary_id, section_key)
    if not source_section:
        raise HTTPException(404, "Source section not found")

    silver_text = source_section.get("silver_text") or source_section.get("bronze_text", "")

    results = []
    for target_id in target_ids:
        target_section = db.get_section(target_id, section_key)
        if target_section:
            db.save_silver(target_id, section_key, silver_text)
            results.append({"commentary_id": target_id, "status": "copied"})
        else:
            results.append({"commentary_id": target_id, "status": "section_not_found"})

    return {"results": results}


# ---------------------------------------------------------------------------
# Citations
# ---------------------------------------------------------------------------

@app.get("/api/commentaries/{commentary_id}/sections/{section_key}/citations")
async def get_citations(
    commentary_id: str,
    section_key: str,
    tier: str = "silver",
    current_user: dict = Depends(auth.get_current_user)
):
    cits = db.get_citations(commentary_id, section_key, tier)
    return {"citations": cits, "tier": tier}


@app.post("/api/commentaries/{commentary_id}/sections/{section_key}/citations")
async def add_citation(
    commentary_id: str,
    section_key: str,
    payload: dict,
    current_user: dict = Depends(auth.require_writer)
):
    url = payload.get("url", "").strip()
    if not url:
        raise HTTPException(400, "URL required")

    title = payload.get("title", "")
    try:
        domain = urlparse(url).netloc.replace("www.", "")
    except Exception:
        domain = ""

    # Compute next display number
    existing = db.get_citations(commentary_id, section_key, "silver")
    next_num = max((c["display_number"] for c in existing), default=0) + 1

    cit_id = db.insert_citation(
        commentary_id=commentary_id,
        section_key=section_key,
        tier="silver",
        url=url,
        title=title,
        domain=domain,
        display_number=next_num,
        source_origin="writer_added",
        bronze_citation_id=None,
        created_by=current_user["username"],
    )
    return {"citation_id": cit_id, "display_number": next_num}


@app.delete("/api/commentaries/{commentary_id}/sections/{section_key}/citations/{citation_id}")
async def remove_citation(
    commentary_id: str,
    section_key: str,
    citation_id: str,
    current_user: dict = Depends(auth.require_writer)
):
    cit = db.get_citation(citation_id)
    if not cit or cit["commentary_id"] != commentary_id:
        raise HTTPException(404, "Citation not found")
    if cit["tier"] == "bronze":
        raise HTTPException(400, "Cannot remove Bronze citations. Edit Silver instead.")
    db.remove_citation(citation_id)
    return {"status": "removed"}


@app.post("/api/commentaries/{commentary_id}/sections/{section_key}/citations/{citation_id}/flag")
async def flag_citation(
    commentary_id: str,
    section_key: str,
    citation_id: str,
    payload: dict,
    current_user: dict = Depends(auth.require_reviewer)
):
    note = payload.get("note", "").strip()
    flag_id = db.flag_citation(citation_id, commentary_id, section_key, note, current_user["username"])
    return {"flag_id": flag_id}


@app.get("/api/citations/fetch-meta")
async def fetch_citation_meta(
    url: str,
    current_user: dict = Depends(auth.require_writer)
):
    """Fetch title and domain for a URL (used by writer when adding a source)."""
    try:
        domain = urlparse(url).netloc.replace("www.", "")
        async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
            resp = await client.get(url, headers={"User-Agent": "Mozilla/5.0"})
            title = _extract_title_from_html(resp.text)
        return {"url": url, "title": title, "domain": domain}
    except Exception as e:
        domain = urlparse(url).netloc.replace("www.", "") if url else ""
        return {"url": url, "title": "", "domain": domain, "error": str(e)}


# ---------------------------------------------------------------------------
# Export routes
# ---------------------------------------------------------------------------

@app.get("/api/commentaries/{commentary_id}/export/word")
async def download_word(
    commentary_id: str,
    current_user: dict = Depends(auth.get_current_user)
):
    try:
        path = exp.export_word(commentary_id)
        return FileResponse(
            str(path),
            media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            filename=path.name
        )
    except Exception as e:
        raise HTTPException(500, f"Word export failed: {e}")


@app.get("/api/commentaries/{commentary_id}/export/pdf")
async def download_pdf(
    commentary_id: str,
    current_user: dict = Depends(auth.get_current_user)
):
    try:
        path = exp.export_pdf(commentary_id)
        suffix = path.suffix
        media = "application/pdf" if suffix == ".pdf" else "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        return FileResponse(str(path), media_type=media, filename=path.name)
    except Exception as e:
        raise HTTPException(500, f"PDF export failed: {e}")


@app.get("/api/commentaries/{commentary_id}/export/csv")
async def download_csv(
    commentary_id: str,
    current_user: dict = Depends(auth.get_current_user)
):
    try:
        sections_path, citations_path = exp.export_snowflake_csvs(commentary_id)
        # Return sections CSV; citations available separately
        return FileResponse(
            str(sections_path),
            media_type="text/csv",
            filename=sections_path.name
        )
    except Exception as e:
        raise HTTPException(500, f"CSV export failed: {e}")


@app.get("/api/commentaries/{commentary_id}/export/citations-csv")
async def download_citations_csv(
    commentary_id: str,
    current_user: dict = Depends(auth.get_current_user)
):
    try:
        _, citations_path = exp.export_snowflake_csvs(commentary_id)
        return FileResponse(
            str(citations_path),
            media_type="text/csv",
            filename=citations_path.name
        )
    except Exception as e:
        raise HTTPException(500, f"CSV export failed: {e}")


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------

@app.get("/api/search")
async def search(
    q: str,
    current_user: dict = Depends(auth.get_current_user)
):
    if not q or len(q.strip()) < 2:
        return {"results": []}
    results = db.search_commentaries(q.strip())
    return {"results": results}


# ---------------------------------------------------------------------------
# Survey upload + Outlook generation
# ---------------------------------------------------------------------------

@app.post("/api/commentaries/{commentary_id}/survey")
async def upload_survey(
    commentary_id: str,
    file: UploadFile = File(...),
    current_user: dict = Depends(auth.require_writer)
):
    """
    Upload PM survey Excel and generate Outlook section.
    Survey must have questions in col A, PM answers in col B.
    """
    commentary = db.get_commentary(commentary_id)
    if not commentary:
        raise HTTPException(404)

    import openpyxl
    content = await file.read()
    tmp = Path(tempfile.mktemp(suffix=".xlsx"))
    tmp.write_bytes(content)

    try:
        wb = openpyxl.load_workbook(tmp, data_only=True)
        ws = wb.active
        answers = {}
        for row in ws.iter_rows(min_row=1, values_only=True):
            if row[0] and row[1]:
                answers[str(row[0])] = str(row[1])
    finally:
        tmp.unlink(missing_ok=True)

    if not answers:
        raise HTTPException(400, "No survey answers found. Expected Q in col A, A in col B.")

    app_settings = db.get_settings()
    api_key = app_settings.get("openai_api_key") or os.getenv("OPENAI_API_KEY", "")
    if not api_key:
        raise HTTPException(400, "OpenAI API key not configured")

    gen_settings = _build_generation_settings(app_settings, {})

    result = await generate_outlook_from_survey(
        portcode=commentary["portcode"],
        period=commentary["period_label"],
        survey_answers=answers,
        api_key=api_key,
        settings=gen_settings,
    )

    if result["success"]:
        db.save_silver(commentary_id, "outlook", result["text"])
        return {"status": "ok", "outlook_text": result["text"]}
    else:
        raise HTTPException(500, f"Outlook generation failed: {result['error']}")


@app.get("/{full_path:path}")
async def serve_spa_routes(full_path: str):
    return FileResponse(str(STATIC_DIR / "index.html"))


# ---------------------------------------------------------------------------
# Background task: generation pipeline
# ---------------------------------------------------------------------------

async def _run_generation_task(
    run_id: str,
    file_paths: list[Path],
    survey_path: Optional[Path],
    gen_settings: GenerationSettings,
    api_key: str,
    queue: asyncio.Queue,
    cancel_event: asyncio.Event,
    started_by: str,
):
    async def emit(msg_type: str, **kwargs):
        await queue.put({"type": msg_type, **kwargs})

    try:
        await emit("status", message="Parsing Excel files…")
        try:
            portfolios = parse_multiple_files(file_paths)
        except Exception as parse_err:
            logger.exception(f"Run {run_id}: Excel parse error: {parse_err}")
            db.update_batch_run(run_id, status="failed")
            await emit("error", message=f"Failed to parse uploaded files: {parse_err}")
            return
        if not portfolios:
            await emit("error", message="No portfolios parsed from uploaded files")
            db.update_batch_run(run_id, status="failed")
            return

        db.update_batch_run(run_id, total_portfolios=len(portfolios))
        await emit("status", message=f"Parsed {len(portfolios)} portfolio(s)")

        # Register each portfolio in DB
        source_files = {}
        for p in portfolios:
            from .dedup import _normalize_period
            commentary_id = f"{p.portcode}_{_normalize_period(p.period)}"
            db.upsert_commentary(
                commentary_id=commentary_id,
                portcode=p.portcode,
                period_label=p.period,
                period_start="",
                period_end="",
                batch_run_id=run_id,
                source_file=str(p.source_file),
            )
            source_files[p.portcode] = str(p.source_file)

        await emit("portfolios", portfolios=[
            {"portcode": p.portcode, "period": p.period,
             "commentary_id": f"{p.portcode}_{_normalize_period(p.period)}"}
            for p in portfolios
        ])

        def progress_cb(msg: str):
            asyncio.get_running_loop().call_soon_threadsafe(
                queue.put_nowait, {"type": "progress", "message": msg}
            )

        bronze_results = await run_generation_pipeline(
            portfolios=portfolios,
            settings=gen_settings,
            batch_run_id=run_id,
            source_files=source_files,
            api_key=api_key,
            progress_callback=progress_cb,
            cancel_event=cancel_event,
        )

        # Persist Bronze to DB
        completed = 0
        errors_total = 0
        for br in bronze_results:
            for section in br.sections:
                db.upsert_section(
                    commentary_id=br.commentary_id,
                    section_key=section["section_key"],
                    section_label=section["section_label"],
                    section_type=section["section_type"],
                    bronze_text=section.get("bronze_text", ""),
                    ticker=section.get("ticker"),
                    security_name=section.get("security_name"),
                    security_rank=section.get("security_rank"),
                    security_type=section.get("security_type"),
                    contribution=section.get("contribution"),
                    weight=section.get("weight"),
                    ticker_pool_id=section.get("ticker_pool_id"),
                )

            for section_key, cit_records in br.citations_by_section.items():
                for cit in cit_records:
                    db.insert_citation(
                        commentary_id=br.commentary_id,
                        section_key=cit["section_key"],
                        tier=cit["tier"],
                        url=cit["url"],
                        title=cit.get("title", ""),
                        domain=cit.get("domain", ""),
                        display_number=cit["display_number"],
                        source_origin=cit["source_origin"],
                        bronze_citation_id=None,
                        created_by="system",
                    )

            # Save Bronze JSON
            exp.save_bronze_json(br.commentary_id, br.sections)

            status = "error" if len(br.errors) == len(br.sections) else "draft"
            db.update_commentary_status(br.commentary_id, status)

            completed += 1
            errors_total += len(br.errors)
            db.update_batch_run(run_id, completed_portfolios=completed)
            await emit("portfolio_done", commentary_id=br.commentary_id,
                       portcode=br.portcode, errors=br.errors)

        # Handle survey → outlook if provided
        if survey_path:
            await emit("status", message="Processing PM survey…")
            # We generate outlook for each portfolio from survey
            # (Survey assumed to apply to all portfolios in batch, or parsed per portcode)
            pass  # TODO: per-commentary survey logic if needed

        db.update_batch_run(
            run_id,
            status="completed",
            completed_at=db._now(),
            error_count=errors_total,
        )
        await emit("done", completed=completed, errors=errors_total)

    except asyncio.CancelledError:
        _cleanup_stuck_commentaries(run_id, "cancelled")
        db.update_batch_run(run_id, status="cancelled")
        await emit("cancelled")
        raise  # re-raise so finally doesn't overwrite "cancelled" → "error"
    except Exception as e:
        logger.exception(f"Run {run_id} failed: {e}")
        _cleanup_stuck_commentaries(run_id, "error")
        db.update_batch_run(run_id, status="failed")
        await emit("error", message=str(e))
    finally:
        # Safety net: any commentaries still in 'generating' (e.g. from Exception path) → error
        _cleanup_stuck_commentaries(run_id, "error")
        _cancel_events.pop(run_id, None)


def _cleanup_stuck_commentaries(run_id: str, target_status: str):
    """Move any commentaries still in 'generating' for this run to target_status."""
    stuck = db.list_commentaries(status_filter="generating", batch_run_id_filter=run_id)
    for c in stuck:
        db.update_commentary_status(c["commentary_id"], target_status)
        logger.warning(f"Cleaned up stuck commentary {c['commentary_id']} → {target_status}")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _build_generation_settings(app_settings: dict, overrides: dict) -> GenerationSettings:
    def get(key, default=""):
        return overrides.get(key) or app_settings.get(key) or default

    mode_str = get("selection_mode", "top_bottom")
    mode = SelectionMode.ALL_HOLDINGS if mode_str == "all_holdings" else SelectionMode.TOP_BOTTOM

    preferred_sources = get_default_preferred_sources()
    prompt_config = PromptConfig(
        preferred_sources=preferred_sources,
        additional_instructions=get("additional_instructions"),
        thinking_level=get("thinking_level", "medium"),
        prioritize_sources=True,
    )
    attrib_config = AttributionPromptConfig(
        preferred_sources=preferred_sources,
        additional_instructions=get("additional_instructions"),
        thinking_level=get("thinking_level", "medium"),
        prioritize_sources=True,
    )

    return GenerationSettings(
        model=get("default_model", "gpt-4o"),
        thinking_level=get("thinking_level", "medium"),
        text_verbosity=get("text_verbosity", "medium"),
        require_citations=get("require_citations", "true").lower() == "true",
        use_web_search=get("use_web_search", "true").lower() == "true",
        selection_mode=mode,
        top_n=int(get("top_n", "5")),
        prompt_config=prompt_config,
        attribution_prompt_config=attrib_config,
        include_attribution_overview=True,
    )


def _extract_title_from_html(html: str) -> str:
    import re
    match = re.search(r"<title[^>]*>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
    if match:
        title = match.group(1).strip()
        title = re.sub(r"\s+", " ", title)
        return title[:200]
    return ""
