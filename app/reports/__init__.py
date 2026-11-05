from __future__ import annotations

from typing import Any

DATASET_LABELS = {
    "us_ofac_sdn": "US OFAC Specially Designated Nationals (SDN)",
    "us_ofac_cons": "US OFAC Consolidated Sanctions (non-SDN)",
    "un_sc_sanctions": "UN Security Council Consolidated List",
    "eu_fsf": "EU Consolidated Financial Sanctions",
    "gb_fcdo_sanctions": "UK FCDO Sanctions List",
    "worldbank_debarred": "World Bank Debarred Firms & Individuals",
    "us_sam_exclusions": "US SAM.gov Exclusions",
}


def dataset_label(d: str) -> str:
    return DATASET_LABELS.get(d, d)


def final_outcome(r: dict[str, Any]) -> str:
    if r["status"] == "clear":
        return "No match"
    if r.get("review_decision") == "cleared":
        return "Cleared after review (false positive)"
    if r.get("review_decision") == "escalated":
        return "Escalated - potential true match"
    return "Pending review"
