"""Screener interface.

A screener takes a chunk of persons and returns, per person id, a list of
candidate matches in a normalized shape:

    {
      "entity_id": str, "caption": str, "score": float (0-1),
      "datasets": [str], "topics": [str], "birth_dates": [str],
      "countries": [str], "aliases": [str], "url": str | None,
    }
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class Screener(ABC):
    name: str = "base"

    @abstractmethod
    def screen(self, persons: list[dict[str, Any]], datasets: list[str]) -> dict[int, list[dict[str, Any]]]:
        """Return {person_id: [candidate, ...]}."""

    def data_version(self) -> str | None:
        """Version / date of the list data used, for the audit trail."""
        return None
