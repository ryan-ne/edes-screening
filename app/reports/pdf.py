"""PDF summary report for submission to the donor."""
from __future__ import annotations

import io
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table,
                                TableStyle)

from .. import db
from ..config import settings
from . import dataset_label, final_outcome

NAVY = colors.HexColor("#1F3A5F")


def _table(data: list[list], col_widths: list[float], header: bool = True) -> Table:
    t = Table(data, colWidths=col_widths, repeatRows=1 if header else 0)
    style = [
        ("FONT", (0, 0), (-1, -1), "Helvetica", 8.5),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#C9D1DA")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F5F7FA")]),
    ]
    if header:
        style += [("BACKGROUND", (0, 0), (-1, 0), NAVY), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                  ("FONT", (0, 0), (-1, 0), "Helvetica-Bold", 8.5)]
    t.setStyle(TableStyle(style))
    return t


def build_pdf(run_id: int, include_names: bool = False) -> bytes:
    run = db.get_run(run_id)
    if not run:
        raise ValueError("Run not found")
    batch = db.get_batch(run["batch_id"]) or {}
    results = db.get_results(run_id)
    stats = db.run_stats(run_id)

    ss = getSampleStyleSheet()
    h1 = ParagraphStyle("h1", parent=ss["Title"], textColor=NAVY, fontSize=18, alignment=0)
    h2 = ParagraphStyle("h2", parent=ss["Heading2"], textColor=NAVY, spaceBefore=10)
    body = ParagraphStyle("b", parent=ss["BodyText"], fontSize=9.5, leading=13)
    small = ParagraphStyle("s", parent=body, fontSize=8, leading=10, textColor=colors.HexColor("#555555"))
    cell = ParagraphStyle("c", parent=body, fontSize=8.5, leading=10.5)
    P = lambda t, s=cell: Paragraph(escape(str(t or "")), s)  # noqa: E731

    story: list = [Paragraph("Beneficiary Screening Report", h1), Spacer(1, 4)]
    meta = [
        ["Organization", settings.org_name],
        ["Prepared for (donor)", batch.get("donor_name") or "—"],
        ["Batch", batch.get("name", "")],
        ["Screening date", run["started_at"]],
        ["List data version", run.get("data_version") or "n/a"],
    ]
    story.append(_table([[P(a), P(b)] for a, b in meta], [45 * mm, 125 * mm], header=False))

    story.append(Paragraph("Results summary", h2))
    potential = stats["possible"] + stats["strong"]
    summ = [
        ["Total individuals/entities screened", stats["screened"]],
        ["No match", stats["clear"]],
        ["Potential matches identified", potential],
        ["Cleared after review (false positives)", stats["cleared"]],
        ["Escalated (potential true matches)", stats["escalated"]],
        ["Pending review", stats["pending"]],
    ]
    story.append(_table([["Measure", "Count"]] + [[P(a), str(b)] for a, b in summ], [120 * mm, 50 * mm]))
    if stats["pending"]:
        story.append(Spacer(1, 4))
        story.append(Paragraph(f"<b>Note:</b> {stats['pending']} potential match(es) still awaiting review. "
                               "This report is a draft until all are reviewed.", body))
    if run.get("summary"):
        story.append(Spacer(1, 6))
        story.append(Paragraph(escape(run["summary"]), body))

    story.append(Paragraph("Methodology", h2))
    story.append(Paragraph(
        "Each beneficiary's name (including alternate spellings and local-script names where provided), "
        "date of birth and country were compared against the lists below using fuzzy name matching. "
        f"Candidate matches scoring at or above {settings.possible_threshold:.2f} were reviewed manually "
        "by staff, who compared identifying details (e.g. date of birth, nationality, location) and "
        "recorded a decision.", body))
    story.append(Spacer(1, 4))
    story.append(Paragraph("<b>Lists screened:</b>", body))
    for d in run["datasets"]:
        story.append(Paragraph("• " + escape(dataset_label(d)), body))

    flagged = [r for r in results if r["status"] != "clear"]
    if flagged:
        story.append(Paragraph("Potential matches and review outcomes", h2))
        data = [["Beneficiary ID"] + (["Name"] if include_names else []) +
                ["Candidate", "Score", "Outcome", "Review note"]]
        for r in flagged:
            best = r["candidates"][0] if r["candidates"] else {}
            data.append([P(r["ref_id"])] + ([P(r["name"])] if include_names else []) +
                        [P(best.get("caption")), f"{r['top_score']:.2f}", P(final_outcome(r)),
                         P(r.get("review_note"))])
        widths = [25 * mm] + ([30 * mm] if include_names else []) + [35 * mm, 14 * mm, 35 * mm]
        widths.append(170 * mm - sum(widths))
        story.append(_table(data, widths))

    story.append(PageBreak())
    story.append(Paragraph("Annex: All screened beneficiaries", h2))
    data = [["#", "Beneficiary ID"] + (["Name"] if include_names else []) + ["Outcome"]]
    for i, r in enumerate(results, 1):
        data.append([str(i), P(r["ref_id"])] + ([P(r["name"])] if include_names else []) + [P(final_outcome(r))])
    widths = [10 * mm, 40 * mm] + ([60 * mm] if include_names else []) + []
    widths.append(170 * mm - sum(widths))
    story.append(_table(data, widths))

    story.append(Spacer(1, 10))
    story.append(Paragraph(
        "Disclaimer: Screening is based on name similarity against public lists at the date shown. "
        "A potential match is not a finding that a person is listed. Results reflect list data at the "
        "time of screening; re-screening is recommended periodically.", small))

    buf = io.BytesIO()

    def _footer(canvas, doc):
        canvas.saveState()
        canvas.setFont("Helvetica", 7.5)
        canvas.setFillColor(colors.HexColor("#777777"))
        canvas.drawString(20 * mm, 10 * mm, f"{settings.org_name} — Beneficiary Screening Report — Confidential")
        canvas.drawRightString(190 * mm, 10 * mm, f"Page {doc.page}")
        canvas.restoreState()

    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=20 * mm, rightMargin=20 * mm,
                            topMargin=18 * mm, bottomMargin=18 * mm,
                            title="Beneficiary Screening Report", author=settings.org_name)
    doc.build(story, onFirstPage=_footer, onLaterPages=_footer)
    return buf.getvalue()
