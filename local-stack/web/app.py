"""Health OS Web UI — простой server-rendered интерфейс на HTMX."""
import os
from datetime import date, datetime
from typing import Optional
from uuid import UUID

import httpx
from fastapi import FastAPI, Request, Form, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

BACKEND = os.environ.get("BACKEND_URL", "http://backend:8000")

app = FastAPI(title="Health OS — Web")
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")


def api():
    return httpx.Client(base_url=BACKEND, timeout=30)


@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    with api() as c:
        families = c.get("/families").json()
        patients = c.get("/patients").json()
    return templates.TemplateResponse("home.html", {
        "request": request, "families": families, "patients": patients,
    })


# ── Семьи ──────────────────────────────────────────────────────
@app.post("/families/create")
def create_family(name: str = Form(...), notes: str = Form("")):
    with api() as c:
        c.post("/families", json={"name": name, "notes": notes or None})
    return RedirectResponse("/", status_code=303)


# ── Пациенты ───────────────────────────────────────────────────
@app.post("/patients/create")
def create_patient(
    full_name: str = Form(...),
    family_id: Optional[str] = Form(None),
    birth_date: Optional[str] = Form(None),
    sex: Optional[str] = Form(None),
):
    with api() as c:
        c.post("/patients", json={
            "full_name": full_name,
            "family_id": family_id or None,
            "birth_date": birth_date or None,
            "sex": sex or None,
        })
    return RedirectResponse("/", status_code=303)


@app.get("/patients/{pid}", response_class=HTMLResponse)
def patient_view(request: Request, pid: UUID):
    with api() as c:
        s = c.get(f"/patients/{pid}/summary").json()
        files = c.get("/files", params={"patient_id": str(pid)}).json()
    return templates.TemplateResponse("patient.html", {"request": request, "s": s, "files": files})


# ── Визит ──────────────────────────────────────────────────────
@app.post("/patients/{pid}/visits/create")
def create_visit(
    pid: UUID,
    visit_date: str = Form(...),
    visit_type: str = Form(""),
    specialty: str = Form(""),
    practitioner: str = Form(""),
    facility: str = Form(""),
    summary: str = Form(""),
    next_visit_date: str = Form(""),
):
    with api() as c:
        c.post("/visits", json={
            "patient_id": str(pid),
            "visit_date": visit_date,
            "visit_type": visit_type or None,
            "specialty": specialty or None,
            "practitioner": practitioner or None,
            "facility": facility or None,
            "summary": summary or None,
            "next_visit_date": next_visit_date or None,
        })
    return RedirectResponse(f"/patients/{pid}", status_code=303)


# ── Наблюдение ─────────────────────────────────────────────────
@app.post("/patients/{pid}/observations/create")
def create_observation(
    pid: UUID,
    code: str = Form(...),
    display_name: str = Form(""),
    value_num: Optional[str] = Form(None),
    value_text: str = Form(""),
    unit: str = Form(""),
    body_site: str = Form(""),
    observed_at: str = Form(...),
    ref_low: Optional[str] = Form(None),
    ref_high: Optional[str] = Form(None),
    visit_id: Optional[str] = Form(None),
):
    payload = {
        "patient_id": str(pid),
        "code": code,
        "display_name": display_name or None,
        "value_num": float(value_num) if value_num else None,
        "value_text": value_text or None,
        "unit": unit or None,
        "body_site": body_site or None,
        "observed_at": observed_at,
        "ref_low": float(ref_low) if ref_low else None,
        "ref_high": float(ref_high) if ref_high else None,
        "visit_id": visit_id or None,
    }
    with api() as c:
        c.post("/observations", json=payload)
    return RedirectResponse(f"/patients/{pid}", status_code=303)


# ── Активная проблема ─────────────────────────────────────────
@app.post("/patients/{pid}/problems/create")
def create_problem(
    pid: UUID,
    title: str = Form(...),
    icd10: str = Form(""),
    status: str = Form("active"),
    severity: str = Form(""),
    next_review_date: str = Form(""),
    careplan_template: str = Form(""),
):
    with api() as c:
        c.post("/problems", json={
            "patient_id": str(pid),
            "title": title,
            "icd10": icd10 or None,
            "status": status,
            "severity": severity or None,
            "next_review_date": next_review_date or None,
            "careplan_template": careplan_template or None,
        })
    return RedirectResponse(f"/patients/{pid}", status_code=303)


# ── Задача ─────────────────────────────────────────────────────
@app.post("/patients/{pid}/tasks/create")
def create_task(
    pid: UUID,
    title: str = Form(...),
    priority: str = Form(""),
    deadline: str = Form(""),
    frequency: str = Form(""),
    cost_rub: Optional[str] = Form(None),
    problem_id: Optional[str] = Form(None),
):
    with api() as c:
        c.post("/tasks", json={
            "patient_id": str(pid),
            "title": title,
            "priority": priority or None,
            "deadline": deadline or None,
            "frequency": frequency or None,
            "cost_rub": float(cost_rub) if cost_rub else None,
            "problem_id": problem_id or None,
        })
    return RedirectResponse(f"/patients/{pid}", status_code=303)


@app.post("/tasks/{tid}/done")
def mark_done(tid: UUID, request: Request):
    with api() as c:
        # получим текущую запись чтобы PATCH работал
        all_tasks = c.get("/tasks").json()
        cur = next((t for t in all_tasks if t["id"] == str(tid)), None)
        if cur:
            cur["status"] = "done"
            c.patch(f"/tasks/{tid}", json=cur)
    return RedirectResponse(request.headers.get("referer", "/"), status_code=303)


# ── Файл ───────────────────────────────────────────────────────
@app.post("/patients/{pid}/files/upload")
async def upload_file(
    pid: UUID,
    file: UploadFile = File(...),
    description: str = Form(""),
):
    raw = await file.read()
    files = {"file": (file.filename, raw, file.content_type or "application/octet-stream")}
    data = {"patient_id": str(pid), "description": description}
    with api() as c:
        c.post("/files", data=data, files=files)
    return RedirectResponse(f"/patients/{pid}", status_code=303)


@app.get("/files/{fid}/open")
def open_file(fid: UUID):
    with api() as c:
        url = c.get(f"/files/{fid}/url").json()["url"]
    # MinIO presigned URL ссылается на minio:9000 (внутренний DNS) — заменим на localhost
    url = url.replace("http://minio:9000", "http://localhost:9000")
    return RedirectResponse(url)
