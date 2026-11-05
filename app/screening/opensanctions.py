"""OpenSanctions /match API screener.

Docs: https://api.opensanctions.org/  (free API keys for non-profit /
non-commercial use: https://www.opensanctions.org/api/)
"""
from __future__ import annotations

import time
from typing import Any

import httpx

from ..config import settings
from .base import Screener


class OpenSanctionsError(RuntimeError):
    pass


class OpenSanctionsScreener(Screener):
    name = "opensanctions"

    def __init__(self, api_key: str | None = None, base_url: str | None = None,
                 client: httpx.Client | None = None) -> None:
        self.api_key = api_key or settings.opensanctions_api_key
        if not self.api_key:
            raise OpenSanctionsError("OPENSANCTIONS_API_KEY is not set.")
        self.base_url = (base_url or settings.opensanctions_url).rstrip("/")
        self.client = client or httpx.Client(
            timeout=60,
            headers={"Authorization": f"ApiKey {self.api_key}",
                     "User-Agent": "edes-screening/1.0"},
        )
        self._version: str | None = None

    @staticmethod
    def build_query(p: dict[str, Any]) -> dict[str, Any]:
        props: dict[str, list[str]] = {"name": [p["name"], *p.get("alt_names", [])]}
        if p.get("birth_date") and p.get("entity_type", "Person") == "Person":
            props["birthDate"] = [p["birth_date"]]
        if p.get("country"):
            key = "nationality" if p.get("entity_type", "Person") == "Person" else "country"
            props[key] = [p["country"]]
        schema = "Person" if p.get("entity_type", "Person") == "Person" else "Organization"
        return {"schema": schema, "properties": props}

    @staticmethod
    def normalize(result: dict[str, Any]) -> dict[str, Any]:
        props = result.get("properties", {}) or {}
        eid = result.get("id", "")
        return {
            "entity_id": eid,
            "caption": result.get("caption") or (props.get("name") or ["?"])[0],
            "schema": result.get("schema"),
            "score": float(result.get("score", 0)),
            "datasets": result.get("datasets", []),
            "topics": props.get("topics", []),
            "birth_dates": props.get("birthDate", []),
            "countries": sorted(set(props.get("nationality", []) + props.get("country", []))),
            # all known names: used for exact-name matching, UI shows the first few
            "aliases": list(dict.fromkeys(props.get("name", []) + props.get("alias", [])
                                          + props.get("previousName", []) + props.get("weakAlias", [])))[:40],
            "addresses": props.get("address", [])[:3],
            "programs": props.get("program", [])[:3],
            "listing_date": (props.get("createdAt") or [None])[0],
            "positions": props.get("position", [])[:3],
            "url": f"https://www.opensanctions.org/entities/{eid}/" if eid else None,
        }

    def _post(self, body: dict[str, Any], datasets: list[str]) -> dict[str, Any]:
        params: list[tuple[str, str]] = [("algorithm", "best"), ("limit", "5"),
                                         ("threshold", str(settings.possible_threshold)),
                                         ("cutoff", "0.4")]
        params += [("include_dataset", d) for d in datasets]
        url = f"{self.base_url}/match/default"
        last_err: Exception | None = None
        for attempt in range(4):
            try:
                resp = self.client.post(url, params=params, json=body)
                if resp.status_code == 429 or resp.status_code >= 500:
                    raise OpenSanctionsError(f"HTTP {resp.status_code}")
                if resp.status_code in (401, 403):
                    raise OpenSanctionsError("API key rejected by OpenSanctions (HTTP %d)." % resp.status_code)
                resp.raise_for_status()
                return resp.json()
            except OpenSanctionsError as e:
                if "rejected" in str(e):
                    raise
                last_err = e
            except httpx.HTTPError as e:
                last_err = e
            time.sleep(2 ** attempt)
        raise OpenSanctionsError(f"OpenSanctions request failed after retries: {last_err}")

    def screen(self, persons: list[dict[str, Any]], datasets: list[str]) -> dict[int, list[dict[str, Any]]]:
        body = {"queries": {str(p["id"]): self.build_query(p) for p in persons}}
        data = self._post(body, datasets)
        out: dict[int, list[dict[str, Any]]] = {}
        for key, resp in (data.get("responses") or {}).items():
            out[int(key)] = [self.normalize(r) for r in resp.get("results", [])]
        for p in persons:
            out.setdefault(int(p["id"]), [])
        return out

    def data_version(self) -> str | None:
        if self._version is None:
            try:
                r = self.client.get(f"{self.base_url}/catalog")
                for ds in r.json().get("datasets", []):
                    if ds.get("name") == "default":
                        self._version = ds.get("version") or ds.get("last_export") or ds.get("updated_at")
                        break
            except Exception:  # noqa: BLE001 — best effort, audit info only
                self._version = None
        return self._version
