"""App settings, read from environment / .env file."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


def _list(value: str | None, default: list[str]) -> list[str]:
    if not value:
        return default
    return [v.strip() for v in value.split(",") if v.strip()]


# Default list set: the sanctions/debarment lists most donors require for
# beneficiary/partner vetting. Dataset names are OpenSanctions dataset IDs.
DEFAULT_DATASETS = [
    "us_ofac_sdn",          # US OFAC Specially Designated Nationals
    "us_ofac_cons",         # US OFAC Consolidated (non-SDN)
    "un_sc_sanctions",      # UN Security Council Consolidated List
    "eu_fsf",               # EU Financial Sanctions Files
    "gb_fcdo_sanctions",    # UK FCDO sanctions list
    "worldbank_debarred",   # World Bank debarred firms & individuals
    "us_sam_exclusions",    # US SAM.gov exclusions
]


@dataclass
class Settings:
    org_name: str = os.getenv("ORG_NAME", "Our Organization")
    db_path: Path = Path(os.getenv("DB_PATH", str(BASE_DIR / "data" / "screening.db")))
    screener: str = os.getenv("SCREENER", "auto")  # auto | opensanctions | mock
    opensanctions_api_key: str = os.getenv("OPENSANCTIONS_API_KEY", "")
    opensanctions_url: str = os.getenv("OPENSANCTIONS_URL", "https://api.opensanctions.org")
    datasets: list[str] = field(
        default_factory=lambda: _list(os.getenv("SCREENING_DATASETS"), DEFAULT_DATASETS)
    )
    anthropic_api_key: str = os.getenv("ANTHROPIC_API_KEY", "")
    claude_model: str = os.getenv("CLAUDE_MODEL", "claude-sonnet-5-5")
    # Score thresholds (0-1) for match classification
    possible_threshold: float = float(os.getenv("POSSIBLE_THRESHOLD", "0.5"))
    strong_threshold: float = float(os.getenv("STRONG_THRESHOLD", "0.8"))
    batch_size: int = int(os.getenv("BATCH_SIZE", "25"))

    @property
    def screener_name(self) -> str:
        if self.screener == "auto":
            return "opensanctions" if self.opensanctions_api_key else "mock"
        return self.screener

    @property
    def claude_enabled(self) -> bool:
        return bool(self.anthropic_api_key)


settings = Settings()
