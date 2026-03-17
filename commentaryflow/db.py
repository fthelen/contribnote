"""
SQLite database layer for CommentaryFlow.
Zero external ORM — uses sqlite3 directly for IT-friendly handoff.
"""

import sqlite3
import uuid
from pathlib import Path
from datetime import datetime
from contextlib import contextmanager
import bcrypt

DB_PATH = Path(__file__).parent / "commentaryflow.db"


@contextmanager
def get_conn():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id            TEXT PRIMARY KEY,
    username      TEXT UNIQUE NOT NULL,
    display_name  TEXT NOT NULL,
    role          TEXT NOT NULL CHECK(role IN ('writer','reviewer')),
    hashed_password TEXT NOT NULL,
    created_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS batch_runs (
    id                  TEXT PRIMARY KEY,
    status              TEXT NOT NULL DEFAULT 'pending',
    started_at          TEXT NOT NULL,
    completed_at        TEXT,
    total_portfolios    INTEGER DEFAULT 0,
    completed_portfolios INTEGER DEFAULT 0,
    error_count         INTEGER DEFAULT 0,
    settings            TEXT,
    started_by          TEXT
);

CREATE TABLE IF NOT EXISTS portfolio_commentary (
    commentary_id   TEXT PRIMARY KEY,
    portcode        TEXT NOT NULL,
    period_label    TEXT NOT NULL,
    period_start    TEXT,
    period_end      TEXT,
    status          TEXT NOT NULL DEFAULT 'not_started',
    batch_run_id    TEXT,
    source_file     TEXT,
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL,
    submitted_at    TEXT,
    submitted_by    TEXT,
    approved_at     TEXT,
    approved_by     TEXT,
    published_at    TEXT,
    FOREIGN KEY (batch_run_id) REFERENCES batch_runs(id)
);

CREATE TABLE IF NOT EXISTS ticker_pool (
    id                  TEXT PRIMARY KEY,
    ticker              TEXT NOT NULL,
    security_name       TEXT NOT NULL,
    period_label        TEXT NOT NULL,
    prompt_config_hash  TEXT NOT NULL,
    bronze_text         TEXT,
    citations_json      TEXT,
    status              TEXT NOT NULL DEFAULT 'pending',
    generation_model    TEXT,
    created_at          TEXT NOT NULL,
    UNIQUE(ticker, period_label, prompt_config_hash)
);

CREATE TABLE IF NOT EXISTS commentary_sections (
    id                      TEXT PRIMARY KEY,
    commentary_id           TEXT NOT NULL,
    section_key             TEXT NOT NULL,
    section_label           TEXT NOT NULL,
    section_type            TEXT NOT NULL CHECK(section_type IN ('overview','security','outlook')),
    ticker                  TEXT,
    security_name           TEXT,
    security_rank           INTEGER,
    security_type           TEXT,
    contribution_to_return  REAL,
    port_ending_weight      REAL,
    bronze_text             TEXT,
    silver_text             TEXT,
    gold_text               TEXT,
    status                  TEXT NOT NULL DEFAULT 'bronze',
    ticker_pool_id          TEXT,
    generated_at            TEXT,
    approved_at             TEXT,
    FOREIGN KEY (commentary_id) REFERENCES portfolio_commentary(commentary_id),
    FOREIGN KEY (ticker_pool_id) REFERENCES ticker_pool(id),
    UNIQUE(commentary_id, section_key)
);

CREATE TABLE IF NOT EXISTS citations (
    citation_id         TEXT PRIMARY KEY,
    commentary_id       TEXT NOT NULL,
    section_key         TEXT NOT NULL,
    tier                TEXT NOT NULL CHECK(tier IN ('bronze','silver','gold')),
    url                 TEXT NOT NULL,
    title               TEXT,
    domain              TEXT,
    display_number      INTEGER,
    source_origin       TEXT NOT NULL CHECK(source_origin IN ('llm_annotation','writer_added','writer_retained')),
    bronze_citation_id  TEXT,
    removed_in_silver   INTEGER DEFAULT 0,
    created_at          TEXT NOT NULL,
    created_by          TEXT,
    FOREIGN KEY (commentary_id) REFERENCES portfolio_commentary(commentary_id)
);

CREATE TABLE IF NOT EXISTS citation_flags (
    id              TEXT PRIMARY KEY,
    citation_id     TEXT NOT NULL,
    commentary_id   TEXT NOT NULL,
    section_key     TEXT NOT NULL,
    note            TEXT,
    created_by      TEXT,
    created_at      TEXT NOT NULL,
    FOREIGN KEY (citation_id) REFERENCES citations(citation_id)
);

CREATE TABLE IF NOT EXISTS reviewer_annotations (
    id              TEXT PRIMARY KEY,
    commentary_id   TEXT NOT NULL,
    section_key     TEXT NOT NULL,
    note            TEXT NOT NULL,
    created_by      TEXT NOT NULL,
    created_at      TEXT NOT NULL,
    FOREIGN KEY (commentary_id) REFERENCES portfolio_commentary(commentary_id)
);

CREATE TABLE IF NOT EXISTS app_settings (
    key     TEXT PRIMARY KEY,
    value   TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_sections_commentary ON commentary_sections(commentary_id);
CREATE INDEX IF NOT EXISTS idx_citations_commentary ON citations(commentary_id, section_key, tier);
CREATE INDEX IF NOT EXISTS idx_ticker_pool_key ON ticker_pool(ticker, period_label, prompt_config_hash);
CREATE INDEX IF NOT EXISTS idx_portfolio_status ON portfolio_commentary(status);
CREATE INDEX IF NOT EXISTS idx_portfolio_period ON portfolio_commentary(period_label);
"""


def init_db():
    with get_conn() as conn:
        conn.executescript(SCHEMA)
        _seed_users(conn)
        _seed_settings(conn)


def _seed_users(conn):
    existing = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    if existing > 0:
        return
    now = _now()
    users = [
        (str(uuid.uuid4()), "writer1", "Alex Writer", "writer",
         _hash_password("writer123"), now),
        (str(uuid.uuid4()), "compliance1", "Sam Compliance", "reviewer",
         _hash_password("compliance123"), now),
    ]
    conn.executemany(
        "INSERT INTO users (id, username, display_name, role, hashed_password, created_at) VALUES (?,?,?,?,?,?)",
        users
    )


def _seed_settings(conn):
    defaults = {
        "openai_api_key": "",
        "default_model": "gpt-5.2-2025-12-11",
        "thinking_level": "medium",
        "text_verbosity": "medium",
        "selection_mode": "top_bottom",
        "top_n": "5",
        "require_citations": "true",
        "use_web_search": "true",
    }
    for k, v in defaults.items():
        conn.execute(
            "INSERT OR IGNORE INTO app_settings (key, value) VALUES (?, ?)", (k, v)
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now() -> str:
    return datetime.utcnow().isoformat()


def new_id() -> str:
    return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# User queries
# ---------------------------------------------------------------------------

def get_user_by_username(username: str) -> dict | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM users WHERE username = ?", (username,)
        ).fetchone()
        return dict(row) if row else None


def get_user_by_id(user_id: str) -> dict | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM users WHERE id = ?", (user_id,)
        ).fetchone()
        return dict(row) if row else None


def _hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode(), hashed.encode())


# ---------------------------------------------------------------------------
# Settings queries
# ---------------------------------------------------------------------------

def get_settings() -> dict:
    with get_conn() as conn:
        rows = conn.execute("SELECT key, value FROM app_settings").fetchall()
        return {r["key"]: r["value"] for r in rows}


def update_setting(key: str, value: str):
    with get_conn() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO app_settings (key, value) VALUES (?, ?)",
            (key, value)
        )


# ---------------------------------------------------------------------------
# Batch run queries
# ---------------------------------------------------------------------------

def create_batch_run(settings_json: str, started_by: str) -> str:
    run_id = new_id()
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO batch_runs (id, status, started_at, settings, started_by)
               VALUES (?, 'running', ?, ?, ?)""",
            (run_id, _now(), settings_json, started_by)
        )
    return run_id


def update_batch_run(run_id: str, **kwargs):
    if not kwargs:
        return
    set_clause = ", ".join(f"{k} = ?" for k in kwargs)
    values = list(kwargs.values()) + [run_id]
    with get_conn() as conn:
        conn.execute(
            f"UPDATE batch_runs SET {set_clause} WHERE id = ?", values
        )


def get_batch_run(run_id: str) -> dict | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM batch_runs WHERE id = ?", (run_id,)
        ).fetchone()
        return dict(row) if row else None


# ---------------------------------------------------------------------------
# Portfolio commentary queries
# ---------------------------------------------------------------------------

def upsert_commentary(commentary_id: str, portcode: str, period_label: str,
                      period_start: str, period_end: str,
                      batch_run_id: str, source_file: str) -> str:
    now = _now()
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO portfolio_commentary
               (commentary_id, portcode, period_label, period_start, period_end,
                status, batch_run_id, source_file, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, 'generating', ?, ?, ?, ?)
               ON CONFLICT(commentary_id) DO UPDATE SET
                 status='generating', updated_at=excluded.updated_at,
                 batch_run_id=excluded.batch_run_id""",
            (commentary_id, portcode, period_label, period_start, period_end,
             batch_run_id, source_file, now, now)
        )
    return commentary_id


def update_commentary_status(commentary_id: str, status: str, **extra):
    now = _now()
    fields = {"status": status, "updated_at": now}
    if status == "in_review":
        fields["submitted_at"] = now
    if status == "approved":
        fields["approved_at"] = now
    if status == "published":
        fields["published_at"] = now
    fields.update(extra)
    set_clause = ", ".join(f"{k} = ?" for k in fields)
    values = list(fields.values()) + [commentary_id]
    with get_conn() as conn:
        conn.execute(
            f"UPDATE portfolio_commentary SET {set_clause} WHERE commentary_id = ?",
            values
        )


def get_commentary(commentary_id: str) -> dict | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM portfolio_commentary WHERE commentary_id = ?",
            (commentary_id,)
        ).fetchone()
        return dict(row) if row else None


def list_commentaries(status_filter: str | None = None,
                      period_filter: str | None = None) -> list[dict]:
    with get_conn() as conn:
        sql = "SELECT * FROM portfolio_commentary WHERE 1=1"
        params = []
        if status_filter:
            sql += " AND status = ?"
            params.append(status_filter)
        if period_filter:
            sql += " AND period_label = ?"
            params.append(period_filter)
        sql += " ORDER BY created_at DESC"
        rows = conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]


def get_distinct_periods() -> list[str]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT DISTINCT period_label FROM portfolio_commentary ORDER BY period_label DESC"
        ).fetchall()
        return [r[0] for r in rows]


# ---------------------------------------------------------------------------
# Section queries
# ---------------------------------------------------------------------------

def upsert_section(commentary_id: str, section_key: str, section_label: str,
                   section_type: str, bronze_text: str,
                   ticker: str | None = None, security_name: str | None = None,
                   security_rank: int | None = None, security_type: str | None = None,
                   contribution: float | None = None, weight: float | None = None,
                   ticker_pool_id: str | None = None) -> str:
    section_id = new_id()
    now = _now()
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO commentary_sections
               (id, commentary_id, section_key, section_label, section_type,
                ticker, security_name, security_rank, security_type,
                contribution_to_return, port_ending_weight,
                bronze_text, status, ticker_pool_id, generated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'bronze', ?, ?)
               ON CONFLICT(commentary_id, section_key) DO UPDATE SET
                 bronze_text=excluded.bronze_text,
                 ticker_pool_id=excluded.ticker_pool_id,
                 generated_at=excluded.generated_at""",
            (section_id, commentary_id, section_key, section_label, section_type,
             ticker, security_name, security_rank, security_type,
             contribution, weight, bronze_text, ticker_pool_id, now)
        )
    return section_id


def get_sections(commentary_id: str) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT * FROM commentary_sections
               WHERE commentary_id = ?
               ORDER BY section_type DESC, security_rank ASC NULLS LAST""",
            (commentary_id,)
        ).fetchall()
        return [dict(r) for r in rows]


def get_section(commentary_id: str, section_key: str) -> dict | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM commentary_sections WHERE commentary_id = ? AND section_key = ?",
            (commentary_id, section_key)
        ).fetchone()
        return dict(row) if row else None


def save_silver(commentary_id: str, section_key: str, silver_text: str):
    with get_conn() as conn:
        conn.execute(
            """UPDATE commentary_sections
               SET silver_text = ?, status = 'silver',
                   commentary_id = commentary_id
               WHERE commentary_id = ? AND section_key = ?""",
            (silver_text, commentary_id, section_key)
        )
        conn.execute(
            "UPDATE portfolio_commentary SET updated_at = ? WHERE commentary_id = ?",
            (_now(), commentary_id)
        )


def approve_section(commentary_id: str, section_key: str, approved_by: str):
    now = _now()
    with get_conn() as conn:
        row = conn.execute(
            "SELECT silver_text, bronze_text FROM commentary_sections WHERE commentary_id=? AND section_key=?",
            (commentary_id, section_key)
        ).fetchone()
        gold_text = row["silver_text"] or row["bronze_text"] if row else None
        conn.execute(
            """UPDATE commentary_sections
               SET gold_text=?, status='approved', approved_at=?
               WHERE commentary_id=? AND section_key=?""",
            (gold_text, now, commentary_id, section_key)
        )


def get_sections_sharing_ticker(ticker: str, period_label: str,
                                 exclude_commentary_id: str) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT cs.*, pc.portcode FROM commentary_sections cs
               JOIN portfolio_commentary pc ON cs.commentary_id = pc.commentary_id
               WHERE cs.ticker = ? AND pc.period_label = ?
                 AND cs.commentary_id != ?""",
            (ticker, period_label, exclude_commentary_id)
        ).fetchall()
        return [dict(r) for r in rows]


def count_sections_for_commentary(commentary_id: str) -> dict:
    with get_conn() as conn:
        total = conn.execute(
            "SELECT COUNT(*) FROM commentary_sections WHERE commentary_id = ?",
            (commentary_id,)
        ).fetchone()[0]
        edited = conn.execute(
            """SELECT COUNT(*) FROM commentary_sections
               WHERE commentary_id = ? AND silver_text IS NOT NULL""",
            (commentary_id,)
        ).fetchone()[0]
        approved = conn.execute(
            """SELECT COUNT(*) FROM commentary_sections
               WHERE commentary_id = ? AND status = 'approved'""",
            (commentary_id,)
        ).fetchone()[0]
        return {"total": total, "edited": edited, "approved": approved}


# ---------------------------------------------------------------------------
# Ticker pool queries
# ---------------------------------------------------------------------------

def get_ticker_pool_entry(ticker: str, period_label: str,
                           prompt_config_hash: str) -> dict | None:
    with get_conn() as conn:
        row = conn.execute(
            """SELECT * FROM ticker_pool
               WHERE ticker=? AND period_label=? AND prompt_config_hash=?""",
            (ticker, period_label, prompt_config_hash)
        ).fetchone()
        return dict(row) if row else None


def insert_ticker_pool_entry(ticker: str, security_name: str, period_label: str,
                              prompt_config_hash: str, bronze_text: str,
                              citations_json: str, model: str) -> str:
    pool_id = new_id()
    with get_conn() as conn:
        conn.execute(
            """INSERT OR REPLACE INTO ticker_pool
               (id, ticker, security_name, period_label, prompt_config_hash,
                bronze_text, citations_json, status, generation_model, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, 'done', ?, ?)""",
            (pool_id, ticker, security_name, period_label, prompt_config_hash,
             bronze_text, citations_json, model, _now())
        )
    return pool_id


def mark_ticker_pool_failed(ticker: str, period_label: str, prompt_config_hash: str):
    with get_conn() as conn:
        conn.execute(
            """UPDATE ticker_pool SET status='failed'
               WHERE ticker=? AND period_label=? AND prompt_config_hash=?""",
            (ticker, period_label, prompt_config_hash)
        )


# ---------------------------------------------------------------------------
# Citation queries
# ---------------------------------------------------------------------------

def get_citations(commentary_id: str, section_key: str, tier: str) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT * FROM citations
               WHERE commentary_id=? AND section_key=? AND tier=?
                 AND removed_in_silver=0
               ORDER BY display_number ASC""",
            (commentary_id, section_key, tier)
        ).fetchall()
        return [dict(r) for r in rows]


def get_all_citations_for_section(commentary_id: str, section_key: str) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT * FROM citations
               WHERE commentary_id=? AND section_key=?
               ORDER BY tier, display_number ASC""",
            (commentary_id, section_key)
        ).fetchall()
        return [dict(r) for r in rows]


def insert_citation(commentary_id: str, section_key: str, tier: str,
                    url: str, title: str, domain: str, display_number: int,
                    source_origin: str, bronze_citation_id: str | None,
                    created_by: str) -> str:
    citation_id = new_id()
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO citations
               (citation_id, commentary_id, section_key, tier, url, title, domain,
                display_number, source_origin, bronze_citation_id, removed_in_silver,
                created_at, created_by)
               VALUES (?,?,?,?,?,?,?,?,?,?,0,?,?)""",
            (citation_id, commentary_id, section_key, tier, url, title, domain,
             display_number, source_origin, bronze_citation_id, _now(), created_by)
        )
    return citation_id


def remove_citation(citation_id: str):
    with get_conn() as conn:
        conn.execute(
            "UPDATE citations SET removed_in_silver=1 WHERE citation_id=?",
            (citation_id,)
        )


def seed_silver_citations(commentary_id: str, section_key: str):
    """Copy bronze citations to silver tier for a section (on first silver save)."""
    bronze_cits = get_citations(commentary_id, section_key, "bronze")
    with get_conn() as conn:
        existing = conn.execute(
            "SELECT COUNT(*) FROM citations WHERE commentary_id=? AND section_key=? AND tier='silver'",
            (commentary_id, section_key)
        ).fetchone()[0]
        if existing > 0:
            return
        for cit in bronze_cits:
            new_cit_id = new_id()
            conn.execute(
                """INSERT INTO citations
                   (citation_id, commentary_id, section_key, tier, url, title, domain,
                    display_number, source_origin, bronze_citation_id, removed_in_silver,
                    created_at, created_by)
                   VALUES (?,?,?,?,?,?,?,?,?,?,0,?,?)""",
                (new_cit_id, commentary_id, section_key, "silver",
                 cit["url"], cit["title"], cit["domain"], cit["display_number"],
                 "writer_retained", cit["citation_id"], _now(), "system")
            )


def snapshot_gold_citations(commentary_id: str, section_key: str):
    """Copy silver citations to gold at approval."""
    silver_cits = get_citations(commentary_id, section_key, "silver")
    with get_conn() as conn:
        conn.execute(
            "DELETE FROM citations WHERE commentary_id=? AND section_key=? AND tier='gold'",
            (commentary_id, section_key)
        )
        for cit in silver_cits:
            new_cit_id = new_id()
            conn.execute(
                """INSERT INTO citations
                   (citation_id, commentary_id, section_key, tier, url, title, domain,
                    display_number, source_origin, bronze_citation_id, removed_in_silver,
                    created_at, created_by)
                   VALUES (?,?,?,?,?,?,?,?,?,?,0,?,?)""",
                (new_cit_id, commentary_id, section_key, "gold",
                 cit["url"], cit["title"], cit["domain"], cit["display_number"],
                 cit["source_origin"], cit["bronze_citation_id"], _now(), "system")
            )


def get_citation(citation_id: str) -> dict | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM citations WHERE citation_id=?", (citation_id,)
        ).fetchone()
        return dict(row) if row else None


def flag_citation(citation_id: str, commentary_id: str, section_key: str,
                  note: str, created_by: str) -> str:
    flag_id = new_id()
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO citation_flags
               (id, citation_id, commentary_id, section_key, note, created_by, created_at)
               VALUES (?,?,?,?,?,?,?)""",
            (flag_id, citation_id, commentary_id, section_key, note, created_by, _now())
        )
    return flag_id


def get_citation_flags(commentary_id: str, section_key: str) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT cf.*, c.url, c.title FROM citation_flags cf
               JOIN citations c ON cf.citation_id = c.citation_id
               WHERE cf.commentary_id=? AND cf.section_key=?""",
            (commentary_id, section_key)
        ).fetchall()
        return [dict(r) for r in rows]


def section_has_flagged_citations(commentary_id: str, section_key: str) -> bool:
    with get_conn() as conn:
        count = conn.execute(
            """SELECT COUNT(*) FROM citation_flags cf
               WHERE cf.commentary_id=? AND cf.section_key=?""",
            (commentary_id, section_key)
        ).fetchone()[0]
        return count > 0


# ---------------------------------------------------------------------------
# Reviewer annotations
# ---------------------------------------------------------------------------

def add_annotation(commentary_id: str, section_key: str,
                   note: str, created_by: str) -> str:
    ann_id = new_id()
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO reviewer_annotations
               (id, commentary_id, section_key, note, created_by, created_at)
               VALUES (?,?,?,?,?,?)""",
            (ann_id, commentary_id, section_key, note, created_by, _now())
        )
    return ann_id


def get_annotations(commentary_id: str) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT * FROM reviewer_annotations WHERE commentary_id=?
               ORDER BY created_at ASC""",
            (commentary_id,)
        ).fetchall()
        return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------

def search_commentaries(query: str) -> list[dict]:
    """Full-text search across portcodes, period labels, ticker names, and text."""
    like = f"%{query}%"
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT DISTINCT pc.commentary_id, pc.portcode, pc.period_label, pc.status
               FROM portfolio_commentary pc
               LEFT JOIN commentary_sections cs ON cs.commentary_id = pc.commentary_id
               WHERE pc.portcode LIKE ? OR pc.period_label LIKE ?
                  OR cs.ticker LIKE ? OR cs.security_name LIKE ?
                  OR cs.bronze_text LIKE ? OR cs.silver_text LIKE ?
               ORDER BY pc.created_at DESC LIMIT 50""",
            (like, like, like, like, like, like)
        ).fetchall()
        return [dict(r) for r in rows]
