"""Turn raw screening candidates into a status: clear / possible / strong.

Rules (names come from ID documents, so exact matches matter most):

* EXACT name match (same words, any order, ignoring case/accents/punctuation
  and a leading title like U / Daw / Mr) against the list entry's name or
  any alias:
    - DOB agrees or unknown  -> STRONG
    - DOB clearly differs     -> POSSIBLE ("exact name, different DOB")
* FUZZY (similar but not identical) name:
    - score >= strong threshold AND DOB agrees -> STRONG
    - score >= possible threshold              -> POSSIBLE
    - otherwise                                 -> ignored (not shown)
"""
from __future__ import annotations

import re
import unicodedata
from typing import Any

from .config import settings

# Leading titles/honorifics ignored for exact matching (Myanmar + English).
TITLES = {"u", "daw", "ko", "ma", "maung", "mg", "saw", "naw", "mr", "mrs", "ms", "miss", "dr"}


def name_tokens(name: str) -> tuple[str, ...]:
    s = unicodedata.normalize("NFKD", name.lower())
    s = "".join(c for c in s if not unicodedata.combining(c))
    toks = [t for t in re.split(r"[^\w]+", s) if t]
    if len(toks) >= 3 and toks[0] in TITLES:
        toks = toks[1:]
    return tuple(sorted(toks))


def exact_name_match(person: dict[str, Any], cand: dict[str, Any]) -> str | None:
    """Return the list name that matched exactly, or None."""
    mine = {name_tokens(n) for n in [person.get("name", ""), *person.get("alt_names", [])] if n}
    mine.discard(())
    for n in [cand.get("caption", ""), *(cand.get("aliases") or [])]:
        if n and name_tokens(n) in mine:
            return n
    return None


def dob_check(person: dict[str, Any], cand: dict[str, Any]) -> str:
    """'match' | 'differs' | 'unknown' (compares birth year)."""
    dob = (person.get("birth_date") or "")[:4]
    cand_years = {str(d)[:4] for d in (cand.get("birth_dates") or []) if d}
    if not dob or not cand_years:
        return "unknown"
    return "match" if dob in cand_years else "differs"


def country_check(person: dict[str, Any], cand: dict[str, Any]) -> str:
    # Only compare ISO-2 codes locally; the provider already weighs country names.
    country = (person.get("country") or "").strip().lower()
    cands = [c.lower() for c in (cand.get("countries") or [])]
    if len(country) != 2 or not cands:
        return "unknown"
    return "match" if country in cands else "differs"


def assess(person: dict[str, Any], cand: dict[str, Any]) -> dict[str, Any]:
    exact = exact_name_match(person, cand)
    dob = dob_check(person, cand)
    country = country_check(person, cand)
    score = float(cand.get("score", 0))
    notes: list[str] = []

    if exact:
        match_type = "exact"
        notes.append(f"exact name match ({exact})")
        level = "possible" if dob == "differs" else "strong"
        score = max(score, 0.95 if level == "strong" else 0.7)
    else:
        match_type = "fuzzy"
        notes.append("similar name (not identical)")
        if dob == "differs":
            score = max(0.0, score - 0.25)
        if score >= settings.strong_threshold and dob == "match":
            level = "strong"
        elif score >= settings.possible_threshold:
            level = "possible"
        else:
            level = "clear"
    if dob == "match":
        notes.append("birth year matches")
    elif dob == "differs":
        notes.append("birth year differs")
    if country == "match":
        notes.append("country matches")
    elif country == "differs":
        notes.append("country differs")
    return {**cand, "match_type": match_type, "level": level, "adjusted_score": round(score, 3),
            "dob_check": dob, "country_check": country, "notes": notes}


LEVEL_RANK = {"strong": 2, "possible": 1, "clear": 0}


def classify(score: float) -> str:
    """Score-only classification (kept for API compatibility)."""
    if score >= settings.strong_threshold:
        return "strong"
    if score >= settings.possible_threshold:
        return "possible"
    return "clear"


def evaluate(person: dict[str, Any], candidates: list[dict[str, Any]]) -> tuple[str, float, list[dict[str, Any]]]:
    assessed = [assess(person, c) for c in candidates]
    kept = [c for c in assessed if c["level"] != "clear"]
    kept.sort(key=lambda c: (LEVEL_RANK[c["level"]], c["match_type"] == "exact", c["adjusted_score"]),
              reverse=True)
    kept = kept[:5]
    if not kept:
        return "clear", 0.0, []
    return kept[0]["level"], kept[0]["adjusted_score"], kept
