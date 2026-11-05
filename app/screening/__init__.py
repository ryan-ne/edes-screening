from ..config import settings
from .base import Screener


def get_screener(name: str | None = None) -> Screener:
    name = name or settings.screener_name
    if name == "opensanctions":
        from .opensanctions import OpenSanctionsScreener
        return OpenSanctionsScreener()
    if name == "mock":
        from .mock import MockScreener
        return MockScreener()
    raise ValueError(f"Unknown screener: {name}")
