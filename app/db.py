"""SQLite storage. Plain sqlite3 — no ORM needed at this size."""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from .config import settings

SCHEMA = """
CREATE TABLE IF NOT EXISTS batches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    donor_name TEXT,
    source_file TEXT,
    created_at TEXT NOT NULL,
    profile TEXT NOT NULL DEFAULT 'multi',  -- eu | multi
    contract_ref TEXT                       -- donor contract / grant reference
);

CREATE TABLE IF NOT EXISTS persons (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    batch_id INTEGER NOT NULL REFERENCES batches(id) ON DELETE CASCADE,
    ref_id TEXT NOT NULL,           -- beneficiary ID shown in donor report
    name TEXT NOT NULL,
    alt_names TEXT NOT NULL DEFAULT '[]',  -- JSON list: local script / other spellings
    birth_date TEXT,
    country TEXT,
    entity_type TEXT NOT NULL DEFAULT 'Person'  -- Person | Organization
);

CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    batch_id INTEGER NOT NULL REFERENCES batches(id) ON DELETE CASCADE,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    status TEXT NOT NULL,           -- running | done | failed
    screener TEXT NOT NULL,
    datasets TEXT NOT NULL,         -- JSON list
    data_version TEXT,
    total INTEGER NOT NULL DEFAULT 0,
    processed INTEGER NOT NULL DEFAULT 0,
    error TEXT,
    summary TEXT                    -- optional Claude executive summary
);

CREATE TABLE IF NOT EXISTS results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    person_id INTEGER NOT NULL REFERENCES persons(id) ON DELETE CASCADE,
    status TEXT NOT NULL,           -- clear | possible | strong
    top_score REAL NOT NULL DEFAULT 0,
    candidates TEXT NOT NULL DEFAULT '[]',  -- JSON list of candidate matches
    review_decision TEXT,           -- cleared | escalated | NULL (pending)
    review_note TEXT,
    reviewer TEXT,
    reviewed_at TEXT,
    ai_summary TEXT,
    UNIQUE(run_id, person_id)
);
"""


def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def init_db(path: Path | None = None) -> None:
    path = path or settings.db_path
    path.parent.mkdir(parents=True, exist_ok=True)
    with connect(path) as conn:
        conn.executescript(SCHEMA)
        # Migrations for databases created by older versions
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(batches)")}
        if "profile" not in cols:
            conn.execute("ALTER TABLE batches ADD COLUMN profile TEXT NOT NULL DEFAULT 'multi'")
        if "contract_ref" not in cols:
            conn.execute("ALTER TABLE batches ADD COLUMN contract_ref TEXT")


@contextmanager
def connect(path: Path | None = None) -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(path or settings.db_path, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def row(r: sqlite3.Row | None) -> dict[str, Any] | None:
    if r is None:
        return None
    d = dict(r)
    for key in ("alt_names", "datasets", "candidates"):
        if key in d and isinstance(d[key], str):
            d[key] = json.loads(d[key])
    return d


def rows(rs: list[sqlite3.Row]) -> list[dict[str, Any]]:
    return [row(r) for r in rs]  # type: ignore[misc]


# ---------- batches & persons ----------

def create_batch(name: str, donor_name: str | None, source_file: str | None,
                 persons: list[dict[str, Any]], profile: str = "multi",
                 contract_ref: str | None = None) -> int:
    with connect() as conn:
        cur = conn.execute(
            "INSERT INTO batches (name, donor_name, source_file, created_at, profile, contract_ref)"
            " VALUES (?,?,?,?,?,?)",
            (name, donor_name, source_file, now(), profile, contract_ref),
        )
        batch_id = cur.lastrowid
        conn.executemany(
            "INSERT INTO persons (batch_id, ref_id, name, alt_names, birth_date, country, entity_type)"
            " VALUES (?,?,?,?,?,?,?)",
            [
                (batch_id, p["ref_id"], p["name"], json.dumps(p.get("alt_names", []), ensure_ascii=False),
                 p.get("birth_date"), p.get("country"), p.get("entity_type", "Person"))
                for p in persons
            ],
        )
        return int(batch_id)  # type: ignore[arg-type]


def list_batches() -> list[dict[str, Any]]:
    with connect() as conn:
        return rows(conn.execute(
            """SELECT b.*, (SELECT COUNT(*) FROM persons p WHERE p.batch_id=b.id) AS person_count,
                      (SELECT MAX(id) FROM runs r WHERE r.batch_id=b.id) AS latest_run_id
               FROM batches b ORDER BY b.id DESC"""
        ).fetchall())


def get_batch(batch_id: int) -> dict[str, Any] | None:
    with connect() as conn:
        return row(conn.execute("SELECT * FROM batches WHERE id=?", (batch_id,)).fetchone())


def delete_batch(batch_id: int) -> None:
    with connect() as conn:
        conn.execute("DELETE FROM batches WHERE id=?", (batch_id,))


def get_persons(batch_id: int) -> list[dict[str, Any]]:
    with connect() as conn:
        return rows(conn.execute(
            "SELECT * FROM persons WHERE batch_id=? ORDER BY id", (batch_id,)
        ).fetchall())


# ---------- runs ----------

def create_run(batch_id: int, screener: str, datasets: list[str], total: int) -> int:
    with connect() as conn:
        cur = conn.execute(
            "INSERT INTO runs (batch_id, started_at, status, screener, datasets, total)"
            " VALUES (?,?,?,?,?,?)",
            (batch_id, now(), "running", screener, json.dumps(datasets), total),
        )
        return int(cur.lastrowid)  # type: ignore[arg-type]


def update_run(run_id: int, **fields: Any) -> None:
    if not fields:
        return
    cols = ", ".join(f"{k}=?" for k in fields)
    with connect() as conn:
        conn.execute(f"UPDATE runs SET {cols} WHERE id=?", (*fields.values(), run_id))


def get_run(run_id: int) -> dict[str, Any] | None:
    with connect() as conn:
        return row(conn.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone())


def list_runs(batch_id: int) -> list[dict[str, Any]]:
    with connect() as conn:
        return rows(conn.execute(
            "SELECT * FROM runs WHERE batch_id=? ORDER BY id DESC", (batch_id,)
        ).fetchall())


def run_stats(run_id: int) -> dict[str, int]:
    with connect() as conn:
        r = conn.execute(
            """SELECT COUNT(*) AS screened,
                SUM(status='clear') AS clear,
                SUM(status='possible') AS possible,
                SUM(status='strong') AS strong,
                SUM(status!='clear' AND review_decision IS NULL) AS pending,
                SUM(review_decision='cleared') AS cleared,
                SUM(review_decision='escalated') AS escalated
               FROM results WHERE run_id=?""",
            (run_id,),
        ).fetchone()
    return {k: int(r[k] or 0) for k in r.keys()}


# ---------- results ----------

def save_result(run_id: int, person_id: int, status: str, top_score: float,
                candidates: list[dict[str, Any]]) -> None:
    with connect() as conn:
        conn.execute(
            """INSERT INTO results (run_id, person_id, status, top_score, candidates)
               VALUES (?,?,?,?,?)
               ON CONFLICT(run_id, person_id) DO UPDATE SET
                 status=excluded.status, top_score=excluded.top_score, candidates=excluded.candidates""",
            (run_id, person_id, status, top_score, json.dumps(candidates, ensure_ascii=False)),
        )


def get_results(run_id: int, only_flagged: bool = False) -> list[dict[str, Any]]:
    sql = """SELECT r.*, p.ref_id, p.name, p.alt_names, p.birth_date, p.country, p.entity_type
             FROM results r JOIN persons p ON p.id = r.person_id WHERE r.run_id=?"""
    if only_flagged:
        sql += " AND r.status != 'clear'"
    sql += " ORDER BY CASE r.status WHEN 'strong' THEN 0 WHEN 'possible' THEN 1 ELSE 2 END, r.top_score DESC, p.id"
    with connect() as conn:
        return rows(conn.execute(sql, (run_id,)).fetchall())


def get_result(result_id: int) -> dict[str, Any] | None:
    with connect() as conn:
        return row(conn.execute(
            """SELECT r.*, p.ref_id, p.name, p.alt_names, p.birth_date, p.country, p.entity_type,
                      p.batch_id
               FROM results r JOIN persons p ON p.id = r.person_id WHERE r.id=?""",
            (result_id,),
        ).fetchone())


def review_result(result_id: int, decision: str, note: str, reviewer: str) -> None:
    if decision not in ("cleared", "escalated"):
        raise ValueError("decision must be 'cleared' or 'escalated'")
    with connect() as conn:
        conn.execute(
            "UPDATE results SET review_decision=?, review_note=?, reviewer=?, reviewed_at=? WHERE id=?",
            (decision, note, reviewer, now(), result_id),
        )


def set_ai_summary(result_id: int, text: str) -> None:
    with connect() as conn:
        conn.execute("UPDATE results SET ai_summary=? WHERE id=?", (text, result_id))
