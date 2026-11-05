"""EU restrictive measures (sanctions) screening report.

Structure:
  1. Screening details (organisation, donor, contract ref, list + version)
  2. Results summary + conclusion
  3. Method
  4. Declaration with signature block
  Annex 1. All screened participants and results
  Annex 2. Match evidence: side-by-side comparison for each potential match
"""
from __future__ import annotations

import io
from typing import Any
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (CondPageBreak, KeepTogether, PageBreak, Paragraph,
                                SimpleDocTemplate, Spacer, Table, TableStyle)

from .. import db
from ..config import settings
from . import dataset_label, final_outcome
from .fonts import fonts

EU_BLUE = colors.HexColor("#003399")
GRID = colors.HexColor("#C9D1DA")
ZEBRA = colors.HexColor("#F4F6FA")
RED = colors.HexColor("#B42318")
GREEN = colors.HexColor("#1B7F3B")
AMBER = colors.HexColor("#9A6700")

LEVEL_TEXT = {"strong": "Strong match", "possible": "Possible match", "clear": "No match"}
CHECK_TEXT = {"match": "Same", "differs": "Different", "unknown": "Not comparable"}


def _styles():
    reg, bold = fonts()
    ss = getSampleStyleSheet()
    base = ParagraphStyle("base", parent=ss["BodyText"], fontName=reg, fontSize=9.5, leading=13)
    return {
        "reg": reg, "bold": bold,
        "title": ParagraphStyle("t", parent=base, fontName=bold, fontSize=17, leading=21, textColor=EU_BLUE),
        "subtitle": ParagraphStyle("st", parent=base, fontSize=10.5, textColor=colors.HexColor("#444444")),
        "h2": ParagraphStyle("h2", parent=base, fontName=bold, fontSize=12.5, leading=16, textColor=EU_BLUE,
                             spaceBefore=12, spaceAfter=5),
        "h3": ParagraphStyle("h3", parent=base, fontName=bold, fontSize=10.5, leading=14, spaceBefore=8, spaceAfter=3),
        "body": base,
        "cell": ParagraphStyle("c", parent=base, fontSize=8.5, leading=10.5),
        "cellb": ParagraphStyle("cb", parent=base, fontName=bold, fontSize=8.5, leading=10.5),
        "small": ParagraphStyle("s", parent=base, fontSize=7.8, leading=10, textColor=colors.HexColor("#555555")),
        "banner": ParagraphStyle("b", parent=base, fontName=bold, fontSize=10, leading=13, textColor=colors.white),
    }


def _printable(name: str) -> str:
    """PDF fonts cover Latin/Greek/Cyrillic only; other scripts (e.g. Myanmar) render as boxes."""
    ok = all(ord(ch) < 0x0250 or 0x0370 <= ord(ch) < 0x0530 or 0x1E00 <= ord(ch) < 0x2070 for ch in name)
    return name if ok else "[local-script name on file]"


def _p(text: Any, style) -> Paragraph:
    return Paragraph(escape(str(text if text not in (None, "") else "—")), style)


def _table(data, widths, st, header=True, extra=None) -> Table:
    t = Table(data, colWidths=widths, repeatRows=1 if header else 0)
    style = [
        ("FONT", (0, 0), (-1, -1), st["reg"], 8.5),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("GRID", (0, 0), (-1, -1), 0.4, GRID),
        ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]
    if header:
        style += [("BACKGROUND", (0, 0), (-1, 0), EU_BLUE), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                  ("FONT", (0, 0), (-1, 0), st["bold"], 8.5),
                  ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, ZEBRA])]
    else:
        style += [("BACKGROUND", (0, 0), (0, -1), ZEBRA)]
    t.setStyle(TableStyle(style + (extra or [])))
    return t


def _banner(text: str, color, st) -> Table:
    t = Table([[Paragraph(escape(text), st["banner"])]], colWidths=[170 * mm])
    t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), color),
                           ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                           ("LEFTPADDING", (0, 0), (-1, -1), 8)]))
    return t


def _screen_date(run: dict) -> str:
    return (run.get("finished_at") or run["started_at"])[:10]


def _evidence_block(i: int, r: dict, st, screened: list[str]) -> list:
    """Side-by-side comparison for one flagged participant."""
    c = r["candidates"][0] if r["candidates"] else {}
    listed_on = [d for d in c.get("datasets", []) if d in screened] or c.get("datasets", [])
    other = "; ".join(dict.fromkeys(_printable(n) for n in r.get("alt_names") or [])) or None
    aliases = list(dict.fromkeys(_printable(a) for a in (c.get("aliases") or []) if a != c.get("caption")))[:6]
    rows = [
        [_p("Field", st["cellb"]), _p("Participant", st["cellb"]), _p("EU list entry", st["cellb"]),
         _p("Check", st["cellb"])],
        [_p("Name", st["cellb"]), _p(r["name"], st["cell"]), _p(c.get("caption"), st["cell"]),
         _p("Exact match" if c.get("match_type") == "exact" else "Similar, not identical", st["cell"])],
        [_p("Other names", st["cellb"]), _p(other, st["cell"]), _p("; ".join(aliases) or None, st["cell"]), _p("", st["cell"])],
        [_p("Date of birth", st["cellb"]), _p(r.get("birth_date"), st["cell"]),
         _p(", ".join(c.get("birth_dates") or []) or None, st["cell"]),
         _p(CHECK_TEXT.get(c.get("dob_check", "unknown")), st["cell"])],
        [_p("Country", st["cellb"]), _p(r.get("country"), st["cell"]),
         _p(", ".join(c.get("countries") or []).upper() or None, st["cell"]),
         _p(CHECK_TEXT.get(c.get("country_check", "unknown")), st["cell"])],
        [_p("Listing", st["cellb"]), _p("", st["cell"]),
         _p("; ".join([*(dataset_label(d) for d in listed_on), *(c.get("programs") or [])]), st["cell"]),
         _p("", st["cell"])],
        [_p("Reference", st["cellb"]), _p(r["ref_id"], st["cell"]), _p(c.get("url") or c.get("entity_id"), st["cell"]),
         _p("", st["cell"])],
    ]
    decision = {"cleared": "CLEARED — not the same person (false positive)",
                "escalated": "ESCALATED — potential true match"}.get(r.get("review_decision") or "", "PENDING REVIEW")
    color = {"cleared": GREEN, "escalated": RED}.get(r.get("review_decision") or "", AMBER)
    outcome = [
        [_p("Assessment", st["cellb"]), _p(LEVEL_TEXT.get(r["status"]), st["cell"])],
        [_p("Decision", st["cellb"]), Paragraph(f'<font color="{color.hexval()}"><b>{escape(decision)}</b></font>', st["cell"])],
        [_p("Reason", st["cellb"]), _p(r.get("review_note"), st["cell"])],
        [_p("Reviewed by", st["cellb"]),
         _p(f"{r.get('reviewer') or '—'}  ·  {r.get('reviewed_at') or '—'}", st["cell"])],
    ]
    return [KeepTogether([
        Paragraph(f"A2.{i}  {escape(r['ref_id'])} — {escape(r['name'])}", st["h3"]),
        _table(rows, [28 * mm, 52 * mm, 60 * mm, 30 * mm], st),
        Spacer(1, 3),
        _table(outcome, [28 * mm, 142 * mm], st, header=False),
        Spacer(1, 6),
    ])]


def build_eu_pdf(run_id: int) -> bytes:
    run = db.get_run(run_id)
    if not run:
        raise ValueError("Run not found")
    batch = db.get_batch(run["batch_id"]) or {}
    results = db.get_results(run_id)
    stats = db.run_stats(run_id)
    st = _styles()
    date = _screen_date(run)
    lists = "; ".join(dataset_label(d) for d in run["datasets"])
    is_draft = stats["pending"] > 0 or run["status"] != "done"
    is_demo = run["screener"] == "mock"

    story: list = [
        Paragraph("Sanctions Screening Report", st["title"]),
        Paragraph("EU restrictive measures — screening of programme participants", st["subtitle"]),
        Spacer(1, 8),
    ]
    if is_demo:
        story += [_banner("DEMO DATA — fictional test watchlist, not real EU list. Do not submit.", RED, st), Spacer(1, 6)]
    if is_draft:
        story += [_banner(f"DRAFT — {stats['pending']} potential match(es) awaiting review. "
                          "Complete all reviews before signing and submitting.", AMBER, st), Spacer(1, 6)]

    # 1. Details
    story.append(Paragraph("1. Screening details", st["h2"]))
    details = [
        ("Organisation", settings.org_name),
        ("Donor", batch.get("donor_name")),
        ("Contract / grant reference", batch.get("contract_ref")),
        ("Participant list", f"{batch.get('name', '')} ({batch.get('source_file') or '—'})"),
        ("Number of participants screened", stats["screened"]),
        ("Date of screening", date),
        ("Sanctions list(s)", lists),
        ("List data version", run.get("data_version")),
        ("Screening source", "OpenSanctions (consolidated copy of official list data)"
         if run["screener"] == "opensanctions" else run["screener"]),
    ]
    story.append(_table([[_p(a, st["cellb"]), _p(b, st["cell"])] for a, b in details],
                        [60 * mm, 110 * mm], st, header=False))

    # 2. Summary
    story.append(Paragraph("2. Results", st["h2"]))
    summary = [
        [_p("Result", st["cellb"]), _p("Count", st["cellb"])],
        [_p("No match", st["cell"]), str(stats["clear"])],
        [_p("Potential match — cleared after review (not the same person)", st["cell"]), str(stats["cleared"])],
        [_p("Potential match — escalated (possible true match)", st["cell"]), str(stats["escalated"])],
        [_p("Potential match — pending review", st["cell"]), str(stats["pending"])],
        [_p("Total screened", st["cellb"]), str(stats["screened"])],
    ]
    story.append(_table(summary, [140 * mm, 30 * mm], st,
                        extra=[("FONT", (0, -1), (-1, -1), st["bold"], 8.5), ("ALIGN", (1, 0), (1, -1), "RIGHT")]))
    story.append(Spacer(1, 6))
    if is_draft:
        conclusion = "Screening is not complete: potential matches remain to be reviewed (see Annex 2)."
    elif stats["escalated"]:
        conclusion = (f"{stats['escalated']} participant(s) could not be excluded as possible matches with persons "
                      "or entities subject to EU restrictive measures and have been escalated (see Annex 2). "
                      "All other participants were found not to match any listed person or entity.")
    else:
        conclusion = ("None of the screened participants was identified as a person or entity subject to EU "
                      "restrictive measures. All potential name matches were reviewed and cleared (see Annex 2).")
    story.append(Paragraph(f"<b>Conclusion:</b> {escape(conclusion)}", st["body"]))

    # 3. Method
    story.append(Paragraph("3. Method", st["h2"]))
    for line in [
        "Each participant's full name as shown on their identity document, any other names, date of birth "
        "and country were compared with every name and alias of the persons and entities on the list(s) above.",
        "Exact name match (same name words in any order, ignoring capitalisation, accents and titles such as "
        "U / Daw / Mr) is classed as a <b>Strong match</b>. If the dates of birth clearly differ it is classed as "
        "a <b>Possible match</b>.",
        f"Similar but not identical names are classed as a <b>Possible match</b> when the similarity score is "
        f"{settings.possible_threshold:.2f} or higher. Lower-scoring similarities are not reported.",
        "Every Strong and Possible match was reviewed by staff, who compared identifying details and recorded a "
        "decision and reason (Annex 2).",
    ]:
        story.append(Paragraph("• " + line, st["body"]))

    # 4. Declaration
    story.append(CondPageBreak(75 * mm))
    story.append(Paragraph("4. Declaration", st["h2"]))
    story.append(Paragraph(
        f"I, the undersigned, on behalf of <b>{escape(settings.org_name)}</b>, declare that all "
        f"<b>{stats['screened']}</b> participants listed in Annex 1 were screened on <b>{date}</b> against the "
        f"{escape(lists)}, and that the results and review decisions reported in this document are complete "
        "and accurate to the best of my knowledge. To the best of my knowledge, no funds or economic resources "
        "have been or will be made available, directly or indirectly, to any person or entity subject to EU "
        "restrictive measures under this programme.", st["body"]))
    story.append(Spacer(1, 10))
    sig = [[_p(lbl, st["cellb"]), ""] for lbl in ("Name", "Position", "Signature", "Date", "Place")]
    sig_t = Table(sig, colWidths=[30 * mm, 90 * mm], rowHeights=[9 * mm] * 5)
    sig_t.setStyle(TableStyle([("LINEBELOW", (1, 0), (1, -1), 0.6, colors.black),
                               ("VALIGN", (0, 0), (-1, -1), "BOTTOM")]))
    stamp = Table([[_p("Organisation stamp", st["small"])]], colWidths=[45 * mm], rowHeights=[45 * mm])
    stamp.setStyle(TableStyle([("BOX", (0, 0), (-1, -1), 0.6, GRID), ("VALIGN", (0, 0), (-1, -1), "TOP")]))
    story.append(Table([[sig_t, stamp]], colWidths=[125 * mm, 45 * mm],
                       style=TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP")])))

    # Annex 1
    story.append(PageBreak())
    story.append(Paragraph("Annex 1 — Screened participants", st["h2"]))
    data = [[_p(h, st["cellb"]) for h in ("#", "ID", "Full name", "Date of birth", "Country", "Screened", "Result")]]
    order = sorted(results, key=lambda r: r["person_id"])
    for i, r in enumerate(order, 1):
        data.append([str(i), _p(r["ref_id"], st["cell"]), _p(r["name"], st["cell"]), _p(r.get("birth_date"), st["cell"]),
                     _p(r.get("country"), st["cell"]), _p(date, st["cell"]), _p(final_outcome(r), st["cell"])])
    story.append(_table(data, [9 * mm, 20 * mm, 43 * mm, 22 * mm, 19 * mm, 22 * mm, 35 * mm], st))

    # Annex 2
    flagged = [r for r in results if r["status"] != "clear"]
    story.append(PageBreak())
    story.append(Paragraph("Annex 2 — Potential matches: evidence and review", st["h2"]))
    if not flagged:
        story.append(Paragraph("No potential matches were found. No review was required.", st["body"]))
    else:
        story.append(Paragraph(
            "For each potential match, the participant's details are compared with the closest entry on the "
            "sanctions list, followed by the reviewer's decision.", st["body"]))
        story.append(Spacer(1, 4))
        for i, r in enumerate(flagged, 1):
            story += _evidence_block(i, r, st, run["datasets"])

    story.append(Spacer(1, 8))
    story.append(Paragraph(
        "Note: name screening identifies potential matches only. A potential match is not a finding that a person "
        "is subject to restrictive measures. Results reflect list data at the version and date stated; EU lists "
        "change frequently and re-screening before each payment or distribution cycle is recommended.", st["small"]))

    buf = io.BytesIO()
    title = f"EU sanctions screening report — {batch.get('name', '')}"

    def _decorate(canvas, doc):
        canvas.saveState()
        canvas.setFont(st["reg"], 7.5)
        canvas.setFillColor(colors.HexColor("#777777"))
        canvas.drawString(20 * mm, 10 * mm, f"{settings.org_name} — EU sanctions screening report — "
                                            f"{batch.get('contract_ref') or batch.get('name', '')} — Confidential")
        canvas.drawRightString(190 * mm, 10 * mm, f"Page {doc.page}")
        if is_draft or is_demo:
            canvas.setFont(st["bold"], 70)
            canvas.setFillColor(colors.Color(0.85, 0.2, 0.2, alpha=0.08))
            canvas.translate(105 * mm, 150 * mm)
            canvas.rotate(45)
            canvas.drawCentredString(0, 0, "DEMO" if is_demo else "DRAFT")
        canvas.restoreState()

    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=20 * mm, rightMargin=20 * mm,
                            topMargin=18 * mm, bottomMargin=18 * mm, title=title, author=settings.org_name)
    doc.build(story, onFirstPage=_decorate, onLaterPages=_decorate)
    return buf.getvalue()
