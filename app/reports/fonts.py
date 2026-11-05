"""Pick a Unicode TTF font for PDFs when available (Latin-extended, Cyrillic,
Greek), else fall back to built-in Helvetica (Latin-1 only)."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

CANDIDATES = [
    # Debian/Ubuntu (Docker image installs fonts-dejavu-core)
    ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
    # Windows
    ("C:/Windows/Fonts/arial.ttf", "C:/Windows/Fonts/arialbd.ttf"),
    # macOS
    ("/System/Library/Fonts/Supplemental/Arial.ttf", "/System/Library/Fonts/Supplemental/Arial Bold.ttf"),
]


@lru_cache(maxsize=1)
def fonts() -> tuple[str, str]:
    """Return (regular, bold) font names registered with reportlab."""
    for regular, bold in CANDIDATES:
        if Path(regular).exists() and Path(bold).exists():
            try:
                pdfmetrics.registerFont(TTFont("UniSans", regular))
                pdfmetrics.registerFont(TTFont("UniSans-Bold", bold))
                return "UniSans", "UniSans-Bold"
            except Exception:  # noqa: BLE001 — broken font file, try next
                continue
    return "Helvetica", "Helvetica-Bold"
