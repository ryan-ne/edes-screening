"""Turn raw screening candidates into a status: clear / possible / strong."""
from __future__ import annotations

from typing import Any

from .config import settings


def _years(values: list[str]) -> set[str]:
    return {str(v)[:4] for v in values if v}


def adjust_score(person: dict[str, Any], cand: dict[str, Any]) -> tuple[float, list[str]]:
    """Apply simple DOB / country corroboration to the provider score.

    Provider (OpenSanctions) score already weighs names; we add a small
    bump when DOB year agrees and a penalty when it clearly conflicts.
    """
    score = float(cand.get("score", 0))
    notes: list[str] = []
    dob = person.get("birth_date")
    cand_dobs = cand.get("birth_dates") or []
    if dob and cand_dobs:
        if str(dob)[:4] in _years(cand_dobs):
            score = min(1.0, score + 0.05)
            notes.append("birth year matches")
        else:
            score = max(0.0, score - 0.25)
            notes.append("birth year differs")
    # Country: provider already weighs country names in its score. Only
    # compare locally when the input is an ISO-2 code (avoids "Myanmar" vs "mm").
    country = (person.get("country") or "").strip().lower()
    cand_countries = [c.lower() for c in (cand.get("countries") or [])]
    if len(country) == 2 and cand_countries:
        if country in cand_countries:
            notes.append("country matches")
        else:
            score = max(0.0, score - 0.1)
            notes.append("country differs")
    return round(score, 3), notes


def classify(score: float) -> str:
    if score >= settings.strong_threshold:
        return "strong"
    if score >= settings.possible_threshold:
        return "possible"
    return "clear"


def evaluate(person: dict[str, Any], candidates: list[dict[str, Any]]) -> tuple[str, float, list[dict[str, Any]]]:
    scored = []
    for c in candidates:
        adj, notes = adjust_score(person, c)
        scored.append({**c, "adjusted_score": adj, "notes": notes})
    scored.sort(key=lambda c: c["adjusted_score"], reverse=True)
    # keep only candidates worth a human look, max 5
    kept = [c for c in scored if c["adjusted_score"] >= settings.possible_threshold * 0.8][:5]
    top = scored[0]["adjusted_score"] if scored else 0.0
    return classify(top), top, kept
