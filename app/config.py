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

# Screening profiles chosen per batch.
#   eu    -> EU restrictive measures only, EU compliance report
#   multi -> the configurable multi-list set above, general report
EU_DATASETS = ["eu_fsf"]  # EU Consolidated Financial Sanctions List
PROFILES = {
    "eu": "EU restrictive measures (EU Consolidated List)",
    "multi": "Multi-list (OFAC, UN, EU, UK, World Bank, SAM)",
}


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
    possible_threshold: float = float(os.getenv("POSSIBLE_THRESHOLD", "0.7"))
    strong_threshold: float = float(os.getenv("STRONG_THRESHOLD", "0.9"))
    batch_size: int = int(os.getenv("BATCH_SIZE", "25"))
    default_profile: str = os.getenv("DEFAULT_PROFILE", "eu")
    # Login. Empty APP_PASSWORD = no login (local use only).
    app_password: str = os.getenv("APP_PASSWORD", "")
    secret_key: str = os.getenv("SECRET_KEY", "")
    api_token: str = os.getenv("API_TOKEN", "")
    cookie_secure: bool = os.getenv("COOKIE_SECURE", "false").lower() in ("1", "true", "yes")

    def __post_init__(self) -> None:
        # Server deployments set REQUIRE_AUTH=true so the app can never start unprotected.
        if os.getenv("REQUIRE_AUTH", "false").lower() in ("1", "true", "yes") and len(self.app_password) < 12:
            raise RuntimeError("REQUIRE_AUTH is on: set APP_PASSWORD (12+ characters).")
        if self.app_password and len(self.secret_key) < 32:
            raise RuntimeError("SECRET_KEY must be set (32+ chars) when APP_PASSWORD is set.")

    @property
    def auth_enabled(self) -> bool:
        return bool(self.app_password)

    def datasets_for(self, profile: str | None) -> list[str]:
        return list(EU_DATASETS) if (profile or self.default_profile) == "eu" else list(self.datasets)

    @property
    def screener_name(self) -> str:
        if self.screener == "auto":
            return "opensanctions" if self.opensanctions_api_key else "mock"
        return self.screener

    @property
    def claude_enabled(self) -> bool:
        return bool(self.anthropic_api_key)


settings = Settings()
