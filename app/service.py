"""Run a screening over a batch: chunk persons, call screener, score, store."""
from __future__ import annotations

import logging
from typing import Any

from . import db, scoring
from .config import settings
from .screening import get_screener

log = logging.getLogger(__name__)


def start_run(batch_id: int, screener_name: str | None = None,
              datasets: list[str] | None = None) -> int:
    persons = db.get_persons(batch_id)
    batch = db.get_batch(batch_id) or {}
    screener_name = screener_name or settings.screener_name
    datasets = datasets or settings.datasets_for(batch.get("profile"))
    return db.create_run(batch_id, screener_name, datasets, len(persons))


def execute_run(run_id: int) -> None:
    """Blocking. Call from a background task/thread."""
    run = db.get_run(run_id)
    if not run:
        return
    try:
        screener = get_screener(run["screener"])
        db.update_run(run_id, data_version=screener.data_version())
        persons = db.get_persons(run["batch_id"])
        size = max(1, settings.batch_size)
        processed = 0
        for i in range(0, len(persons), size):
            chunk = persons[i:i + size]
            found = screener.screen(chunk, run["datasets"])
            for p in chunk:
                status, top, kept = scoring.evaluate(p, found.get(p["id"], []))
                db.save_result(run_id, p["id"], status, top, kept)
            processed += len(chunk)
            db.update_run(run_id, processed=processed)
        if settings.claude_enabled:
            try:
                from . import summarize
                summarize.summarize_run(run_id)
            except Exception as e:  # noqa: BLE001 — summaries are optional
                log.warning("Claude summary failed: %s", e)
        db.update_run(run_id, status="done", finished_at=db.now())
    except Exception as e:  # noqa: BLE001
        log.exception("Run %s failed", run_id)
        db.update_run(run_id, status="failed", error=str(e), finished_at=db.now())


def screen_one(person: dict[str, Any], screener_name: str | None = None,
               datasets: list[str] | None = None) -> dict[str, Any]:
    """Ad-hoc single-person screen (not stored)."""
    screener = get_screener(screener_name)
    p = {"id": 0, "alt_names": [], "entity_type": "Person", **person}
    found = screener.screen([p], datasets or settings.datasets_for(None))
    status, top, kept = scoring.evaluate(p, found.get(0, []))
    return {"status": status, "top_score": top, "candidates": kept,
            "screener": screener.name, "data_version": screener.data_version()}
