"""FastAPI app: browser UI + REST API (/api, docs at /docs)."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field

from . import auth, db, service
from .config import settings
from .importer import import_file
from .reports import dataset_label, final_outcome
from .reports.excel import build_excel
from .reports.pdf import build_pdf

logging.basicConfig(level=logging.INFO)
MAX_UPLOAD = 10 * 1024 * 1024  # 10 MB


@asynccontextmanager
async def lifespan(_: FastAPI):
    db.init_db()
    yield


app = FastAPI(title="Beneficiary Screening", version="1.0", lifespan=lifespan,
              description="Screen program beneficiaries against sanctions/debarment lists "
                          "and produce donor compliance reports.")
app.add_middleware(auth.AuthMiddleware)
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
templates.env.globals.update(settings=settings, dataset_label=dataset_label, final_outcome=final_outcome)


def _require(obj: Any, what: str) -> Any:
    if not obj:
        raise HTTPException(404, f"{what} not found")
    return obj


async def _read_upload(file: UploadFile) -> bytes:
    content = await file.read()
    if len(content) > MAX_UPLOAD:
        raise HTTPException(413, "File too large (max 10 MB).")
    return content


def _create_and_run(bg: BackgroundTasks, name: str, donor: str | None, filename: str,
                    content: bytes) -> tuple[int, int, Any]:
    try:
        imp = import_file(filename, content)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    if not imp.persons:
        raise HTTPException(400, "No valid rows found in file.")
    batch_id = db.create_batch(name or filename, donor, filename, imp.persons)
    run_id = service.start_run(batch_id)
    bg.add_task(service.execute_run, run_id)
    return batch_id, run_id, imp


# =========================== Login ===========================

@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    if not settings.auth_enabled:
        return RedirectResponse("/", status_code=303)
    return templates.TemplateResponse(request, "login.html", {"error": None})


@app.post("/login", response_class=HTMLResponse)
def login_submit(request: Request, password: str = Form(...)):
    if not settings.auth_enabled:
        return RedirectResponse("/", status_code=303)
    ip = auth.client_ip(request)
    if auth.locked_out(ip):
        return templates.TemplateResponse(
            request, "login.html", {"error": "Too many failed attempts. Try again in 15 minutes."},
            status_code=429)
    if not auth.check_password(password):
        auth.record_fail(ip)
        return templates.TemplateResponse(request, "login.html", {"error": "Wrong password."},
                                          status_code=401)
    auth.clear_fails(ip)
    resp = RedirectResponse("/", status_code=303)
    resp.set_cookie(auth.COOKIE, auth.make_token(), max_age=auth.SESSION_TTL, httponly=True,
                    secure=settings.cookie_secure, samesite="lax")
    return resp


@app.post("/logout")
def logout():
    resp = RedirectResponse("/login" if settings.auth_enabled else "/", status_code=303)
    resp.delete_cookie(auth.COOKIE)
    return resp


# =========================== UI ===========================

@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    batches = db.list_batches()
    for b in batches:
        b["run"] = db.get_run(b["latest_run_id"]) if b["latest_run_id"] else None
        b["stats"] = db.run_stats(b["latest_run_id"]) if b["latest_run_id"] else None
    return templates.TemplateResponse(request, "home.html", {"batches": batches})


@app.post("/upload")
async def ui_upload(bg: BackgroundTasks, file: UploadFile = File(...),
                    name: str = Form(""), donor_name: str = Form("")):
    content = await _read_upload(file)
    _, run_id, imp = _create_and_run(bg, name, donor_name or None, file.filename or "upload", content)
    return RedirectResponse(f"/runs/{run_id}?imported={len(imp.persons)}&skipped={len(imp.warnings)}",
                            status_code=303)


@app.get("/runs/{run_id}", response_class=HTMLResponse)
def ui_run(request: Request, run_id: int, show: str = "flagged"):
    run = _require(db.get_run(run_id), "Run")
    batch = db.get_batch(run["batch_id"])
    results = db.get_results(run_id, only_flagged=(show == "flagged"))
    return templates.TemplateResponse(request, "run.html", {
        "run": run, "batch": batch, "results": results, "stats": db.run_stats(run_id),
        "runs": db.list_runs(run["batch_id"]), "show": show,
        "imported": request.query_params.get("imported"),
        "skipped": request.query_params.get("skipped"),
    })


@app.get("/results/{result_id}", response_class=HTMLResponse)
def ui_result(request: Request, result_id: int):
    r = _require(db.get_result(result_id), "Result")
    flagged = db.get_results(r["run_id"], only_flagged=True)
    ids = [x["id"] for x in flagged]
    pending = [x["id"] for x in flagged if not x["review_decision"] and x["id"] != result_id]
    idx = ids.index(result_id) if result_id in ids else -1
    return templates.TemplateResponse(request, "result.html", {
        "r": r, "next_pending": pending[0] if pending else None,
        "prev_id": ids[idx - 1] if idx > 0 else None,
        "next_id": ids[idx + 1] if 0 <= idx < len(ids) - 1 else None,
        "reviewer": request.cookies.get("reviewer", ""),
    })


@app.post("/results/{result_id}/review")
def ui_review(result_id: int, decision: str = Form(...), note: str = Form(""),
              reviewer: str = Form(...), go: str = Form("next")):
    r = _require(db.get_result(result_id), "Result")
    if decision == "cleared" and not note.strip():
        note = "Not the same person: identifying details do not match."
    db.review_result(result_id, decision, note.strip(), reviewer.strip())
    flagged = db.get_results(r["run_id"], only_flagged=True)
    pending = [x["id"] for x in flagged if not x["review_decision"]]
    url = f"/results/{pending[0]}" if (go == "next" and pending) else f"/runs/{r['run_id']}"
    resp = RedirectResponse(url, status_code=303)
    resp.set_cookie("reviewer", reviewer.strip(), max_age=60 * 60 * 24 * 365, samesite="strict")
    return resp


@app.post("/batches/{batch_id}/rescreen")
def ui_rescreen(bg: BackgroundTasks, batch_id: int):
    _require(db.get_batch(batch_id), "Batch")
    run_id = service.start_run(batch_id)
    bg.add_task(service.execute_run, run_id)
    return RedirectResponse(f"/runs/{run_id}", status_code=303)


@app.post("/batches/{batch_id}/delete")
def ui_delete(batch_id: int):
    db.delete_batch(batch_id)
    return RedirectResponse("/", status_code=303)


@app.get("/runs/{run_id}/report.xlsx")
def report_xlsx(run_id: int, names: bool = True):
    _require(db.get_run(run_id), "Run")
    return Response(build_excel(run_id, include_names=names),
                    media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f'attachment; filename="screening_run{run_id}.xlsx"'})


@app.get("/runs/{run_id}/report.pdf")
def report_pdf(run_id: int, names: bool = False):
    _require(db.get_run(run_id), "Run")
    return Response(build_pdf(run_id, include_names=names), media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="screening_run{run_id}.pdf"'})


# =========================== REST API ===========================

class PersonIn(BaseModel):
    name: str = Field(..., min_length=1)
    alt_names: list[str] = []
    birth_date: str | None = None
    country: str | None = None
    entity_type: str = "Person"


class ReviewIn(BaseModel):
    decision: str = Field(..., pattern="^(cleared|escalated)$")
    note: str = ""
    reviewer: str = Field(..., min_length=1)


@app.get("/api/health")
def api_health():
    return {"ok": True, "screener": settings.screener_name, "datasets": settings.datasets,
            "claude_enabled": settings.claude_enabled}


@app.get("/api/batches")
def api_batches():
    return db.list_batches()


@app.post("/api/batches", status_code=201)
async def api_create_batch(bg: BackgroundTasks, file: UploadFile = File(...),
                           name: str = Form(""), donor_name: str = Form("")):
    content = await _read_upload(file)
    batch_id, run_id, imp = _create_and_run(bg, name, donor_name or None, file.filename or "upload", content)
    return {"batch_id": batch_id, "run_id": run_id, "imported": len(imp.persons),
            "duplicates": imp.duplicates, "warnings": imp.warnings, "column_mapping": imp.mapping}


@app.get("/api/batches/{batch_id}")
def api_batch(batch_id: int):
    b = _require(db.get_batch(batch_id), "Batch")
    return {**b, "runs": [{**r, "stats": db.run_stats(r["id"])} for r in db.list_runs(batch_id)]}


@app.post("/api/batches/{batch_id}/rescreen", status_code=201)
def api_rescreen(bg: BackgroundTasks, batch_id: int):
    _require(db.get_batch(batch_id), "Batch")
    run_id = service.start_run(batch_id)
    bg.add_task(service.execute_run, run_id)
    return {"run_id": run_id}


@app.delete("/api/batches/{batch_id}", status_code=204)
def api_delete_batch(batch_id: int):
    _require(db.get_batch(batch_id), "Batch")
    db.delete_batch(batch_id)


@app.get("/api/runs/{run_id}")
def api_run(run_id: int):
    run = _require(db.get_run(run_id), "Run")
    return {**run, "stats": db.run_stats(run_id)}


@app.get("/api/runs/{run_id}/results")
def api_results(run_id: int, flagged_only: bool = False):
    _require(db.get_run(run_id), "Run")
    return [{**r, "outcome": final_outcome(r)} for r in db.get_results(run_id, only_flagged=flagged_only)]


@app.post("/api/results/{result_id}/review")
def api_review(result_id: int, body: ReviewIn):
    _require(db.get_result(result_id), "Result")
    db.review_result(result_id, body.decision, body.note, body.reviewer)
    return db.get_result(result_id)


@app.post("/api/screen")
def api_screen(person: PersonIn):
    """Screen one person ad hoc (result not stored)."""
    return service.screen_one(person.model_dump())
