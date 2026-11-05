"""Optional Claude summaries. Only runs when ANTHROPIC_API_KEY is set.

Data minimization: only flagged persons are sent, and only the fields
needed to judge the match (name, birth year, country, candidate evidence).
Beneficiary IDs, phone numbers etc. are never sent.
"""
from __future__ import annotations

import json
from typing import Any

from . import db
from .config import settings

SYSTEM = (
    "You assist a non-profit compliance officer reviewing sanctions-screening hits "
    "for program beneficiaries. Be factual and brief. Never state that a person IS "
    "the listed individual; describe how strong the evidence is and what a reviewer "
    "should verify (e.g. date of birth, ID document, location). Plain English."
)


def _client():
    import anthropic
    return anthropic.Anthropic(api_key=settings.anthropic_api_key)


def _text(resp: Any) -> str:
    return "".join(b.text for b in resp.content if getattr(b, "type", "") == "text").strip()


def summarize_result(result: dict[str, Any], client: Any = None) -> str:
    client = client or _client()
    evidence = {
        "screened_person": {
            "name": result["name"], "other_names": result.get("alt_names", []),
            "birth_year": (result.get("birth_date") or "")[:4] or None,
            "country": result.get("country"),
        },
        "candidates": [
            {k: c.get(k) for k in ("caption", "adjusted_score", "datasets", "topics",
                                   "birth_dates", "countries", "notes", "positions")}
            for c in result.get("candidates", [])
        ],
    }
    resp = client.messages.create(
        model=settings.claude_model, max_tokens=300, system=SYSTEM,
        messages=[{"role": "user", "content":
                   "In 2-3 sentences, assess this potential match and say what to verify:\n"
                   + json.dumps(evidence, ensure_ascii=False)}],
    )
    return _text(resp)


def summarize_run(run_id: int) -> None:
    client = _client()
    flagged = db.get_results(run_id, only_flagged=True)
    for r in flagged:
        db.set_ai_summary(r["id"], summarize_result(r, client))
    stats = db.run_stats(run_id)
    run = db.get_run(run_id)
    resp = client.messages.create(
        model=settings.claude_model, max_tokens=400, system=SYSTEM,
        messages=[{"role": "user", "content":
                   "Write a short executive summary paragraph (no names) for a donor report "
                   "on this beneficiary screening run. Mention that potential matches require "
                   "manual review before any conclusion.\n"
                   + json.dumps({"stats": stats, "lists": run["datasets"] if run else []})}],
    )
    db.update_run(run_id, summary=_text(resp))
