"""Offline mock screener for demos and tests. NOT real screening data.

Matches against a small fictional watchlist using fuzzy string similarity.
"""
from __future__ import annotations

from difflib import SequenceMatcher
from typing import Any

from ..importer import match_key
from .base import Screener

# Fictional entries only.
FAKE_WATCHLIST: list[dict[str, Any]] = [
    {"entity_id": "mock-001", "caption": "Viktor Demo Sanctionov", "datasets": ["us_ofac_sdn", "eu_fsf", "eu_edes"],
     "topics": ["sanction"], "birth_dates": ["1965-04-12"], "countries": ["xx"], "aliases": []},
    {"entity_id": "mock-002", "caption": "Aung Test Example", "datasets": ["un_sc_sanctions", "eu_fsf", "eu_edes"],
     "topics": ["sanction"], "birth_dates": ["1978"], "countries": ["mm"],
     "aliases": ["Aung T. Example", "Ko Aung Example"]},
    {"entity_id": "mock-003", "caption": "Maria Fictional Debarred", "datasets": ["worldbank_debarred", "eu_fsf", "eu_edes"],
     "topics": ["sanction"], "birth_dates": [], "countries": ["zz"], "aliases": []},
    {"entity_id": "mock-004", "caption": "Sample Front Company Ltd", "datasets": ["eu_fsf", "eu_edes"],
     "topics": ["sanction"], "birth_dates": [], "countries": ["xx"], "aliases": []},
]


def _sim(a: str, b: str) -> float:
    a_tokens, b_tokens = sorted(match_key(t) for t in a.split()), sorted(match_key(t) for t in b.split())
    return SequenceMatcher(None, " ".join(a_tokens), " ".join(b_tokens)).ratio()


class MockScreener(Screener):
    name = "mock"

    def screen(self, persons: list[dict[str, Any]], datasets: list[str]) -> dict[int, list[dict[str, Any]]]:
        out: dict[int, list[dict[str, Any]]] = {}
        for p in persons:
            names = [p["name"], *p.get("alt_names", [])]
            cands = []
            for w in FAKE_WATCHLIST:
                if datasets and not set(w["datasets"]) & set(datasets):
                    continue
                score = max(_sim(n, wn) for n in names for wn in [w["caption"], *w["aliases"]])
                if score >= 0.4:
                    cands.append({**w, "score": round(score, 3), "positions": [],
                                  "schema": "Person", "url": None})
            out[int(p["id"])] = sorted(cands, key=lambda c: c["score"], reverse=True)
        return out

    def data_version(self) -> str | None:
        return "mock-demo-data (not real lists)"
