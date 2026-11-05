"""Excel report: Summary sheet + Results sheet (+ Matches detail)."""
from __future__ import annotations

import io

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from .. import db
from ..config import settings
from . import dataset_label, final_outcome

HEADER_FILL = PatternFill("solid", fgColor="1F3A5F")
HEADER_FONT = Font(bold=True, color="FFFFFF")
OUTCOME_FILL = {
    "No match": "E8F5E9",
    "Cleared after review (false positive)": "E3F2FD",
    "Pending review": "FFF8E1",
    "Escalated - potential true match": "FFEBEE",
}


def _header(ws, cols: list[str]) -> None:
    ws.append(cols)
    for c in ws[1]:
        c.fill, c.font = HEADER_FILL, HEADER_FONT
        c.alignment = Alignment(vertical="center", wrap_text=True)
    ws.freeze_panes = "A2"


def _autosize(ws, max_width: int = 60) -> None:
    for col in ws.columns:
        width = max((len(str(c.value or "")) for c in col), default=8)
        ws.column_dimensions[get_column_letter(col[0].column)].width = min(max_width, max(10, width + 2))


def build_excel(run_id: int, include_names: bool = True) -> bytes:
    run = db.get_run(run_id)
    if not run:
        raise ValueError("Run not found")
    batch = db.get_batch(run["batch_id"]) or {}
    results = db.get_results(run_id)
    stats = db.run_stats(run_id)

    wb = Workbook()
    ws = wb.active
    ws.title = "Summary"
    rows = [
        ("Beneficiary Screening Report", ""),
        ("Organization", settings.org_name),
        ("Prepared for (donor)", batch.get("donor_name") or ""),
        ("Batch", batch.get("name", "")),
        ("Screening date", run["started_at"]),
        ("Screening source", run["screener"]),
        ("List data version", run.get("data_version") or "n/a"),
        ("Lists screened", "; ".join(dataset_label(d) for d in run["datasets"])),
        ("", ""),
        ("Total screened", stats["screened"]),
        ("No match", stats["clear"]),
        ("Potential matches found", stats["possible"] + stats["strong"]),
        ("  - cleared after review (false positive)", stats["cleared"]),
        ("  - escalated (potential true match)", stats["escalated"]),
        ("  - pending review", stats["pending"]),
    ]
    for r in rows:
        ws.append(r)
    ws["A1"].font = Font(bold=True, size=14)
    if run.get("summary"):
        ws.append(("", ""))
        ws.append(("Summary", run["summary"]))
    ws.append(("", ""))
    ws.append(("Note", "Potential matches are name-based and require human review. "
                       "A potential match is not a determination that a person is listed."))
    ws.column_dimensions["A"].width = 42
    ws.column_dimensions["B"].width = 90
    for r in ws.iter_rows(min_row=2):
        r[1].alignment = Alignment(wrap_text=True, vertical="top")

    ws2 = wb.create_sheet("Results")
    cols = ["Beneficiary ID"] + (["Name", "Other names", "Date of birth", "Country"] if include_names else []) + [
        "Type", "Outcome", "Match level", "Top score", "Best candidate", "Candidate lists",
        "Reviewer", "Reviewed at", "Review note"]
    _header(ws2, cols)
    for r in results:
        best = r["candidates"][0] if r["candidates"] else {}
        outcome = final_outcome(r)
        line = [r["ref_id"]]
        if include_names:
            line += [r["name"], "; ".join(r["alt_names"]), r["birth_date"] or "", r["country"] or ""]
        line += [r["entity_type"], outcome, r["status"].title(), round(r["top_score"], 3),
                 best.get("caption", ""), "; ".join(best.get("datasets", [])),
                 r.get("reviewer") or "", r.get("reviewed_at") or "", r.get("review_note") or ""]
        ws2.append(line)
        fill = PatternFill("solid", fgColor=OUTCOME_FILL.get(outcome, "FFFFFF"))
        ws2.cell(row=ws2.max_row, column=cols.index("Outcome") + 1).fill = fill
    ws2.auto_filter.ref = ws2.dimensions
    _autosize(ws2)

    flagged = [r for r in results if r["status"] != "clear"]
    if flagged:
        ws3 = wb.create_sheet("Match details")
        _header(ws3, ["Beneficiary ID", "Candidate", "Adjusted score", "Raw score", "Lists",
                      "Topics", "Candidate DOB", "Candidate countries", "Notes", "Link", "AI summary"])
        for r in flagged:
            for c in r["candidates"]:
                ws3.append([r["ref_id"], c.get("caption"), c.get("adjusted_score"), c.get("score"),
                            "; ".join(c.get("datasets", [])), "; ".join(c.get("topics", [])),
                            "; ".join(c.get("birth_dates", [])), "; ".join(c.get("countries", [])),
                            "; ".join(c.get("notes", [])), c.get("url") or "", r.get("ai_summary") or ""])
        _autosize(ws3)

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
