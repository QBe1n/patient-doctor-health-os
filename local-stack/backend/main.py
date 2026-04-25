"""Health OS local backend — FastAPI."""
from __future__ import annotations
from datetime import date
from io import BytesIO
from typing import List, Optional
from uuid import UUID, uuid4

from fastapi import FastAPI, Depends, HTTPException, UploadFile, File as FFile, Form
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select, desc
from sqlalchemy.orm import Session

from db import engine, get_db
import models
import schemas
import storage

app = FastAPI(title="Health OS — Local API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health():
    return {"status": "ok"}


# ── Families ───────────────────────────────────────────────────
@app.get("/families", response_model=List[schemas.FamilyOut])
def list_families(db: Session = Depends(get_db)):
    return db.scalars(select(models.Family).order_by(models.Family.name)).all()


@app.post("/families", response_model=schemas.FamilyOut)
def create_family(payload: schemas.FamilyIn, db: Session = Depends(get_db)):
    f = models.Family(**payload.model_dump())
    db.add(f); db.commit(); db.refresh(f)
    return f


# ── Patients ───────────────────────────────────────────────────
@app.get("/patients", response_model=List[schemas.PatientOut])
def list_patients(family_id: Optional[UUID] = None, db: Session = Depends(get_db)):
    q = select(models.Patient).order_by(models.Patient.full_name)
    if family_id:
        q = q.where(models.Patient.family_id == family_id)
    return db.scalars(q).all()


@app.post("/patients", response_model=schemas.PatientOut)
def create_patient(payload: schemas.PatientIn, db: Session = Depends(get_db)):
    p = models.Patient(**payload.model_dump())
    db.add(p); db.commit(); db.refresh(p)
    return p


@app.get("/patients/{patient_id}", response_model=schemas.PatientOut)
def get_patient(patient_id: UUID, db: Session = Depends(get_db)):
    p = db.get(models.Patient, patient_id)
    if not p: raise HTTPException(404, "patient not found")
    return p


@app.patch("/patients/{patient_id}", response_model=schemas.PatientOut)
def update_patient(patient_id: UUID, payload: schemas.PatientIn, db: Session = Depends(get_db)):
    p = db.get(models.Patient, patient_id)
    if not p: raise HTTPException(404, "patient not found")
    for k, v in payload.model_dump(exclude_unset=True).items():
        setattr(p, k, v)
    db.commit(); db.refresh(p)
    return p


@app.get("/patients/{patient_id}/summary", response_model=schemas.PatientSummary)
def patient_summary(patient_id: UUID, db: Session = Depends(get_db)):
    p = db.get(models.Patient, patient_id)
    if not p: raise HTTPException(404, "patient not found")
    visits = db.scalars(
        select(models.Visit).where(models.Visit.patient_id == patient_id).order_by(desc(models.Visit.visit_date))
    ).all()
    problems = db.scalars(
        select(models.ActiveProblem).where(models.ActiveProblem.patient_id == patient_id).order_by(desc(models.ActiveProblem.created_at))
    ).all()
    tasks = db.scalars(
        select(models.PersonalTask).where(models.PersonalTask.patient_id == patient_id).order_by(models.PersonalTask.deadline)
    ).all()
    # последние наблюдения по коду+стороне
    obs = db.scalars(
        select(models.Observation).where(models.Observation.patient_id == patient_id).order_by(desc(models.Observation.observed_at))
    ).all()
    seen = set()
    latest = []
    for o in obs:
        key = (o.code, o.body_site)
        if key in seen: continue
        seen.add(key); latest.append(o)
    return schemas.PatientSummary(
        patient=p, family=p.family, visits=visits, problems=problems,
        tasks=tasks, latest_observations=latest,
    )


# ── Visits ─────────────────────────────────────────────────────
@app.get("/visits", response_model=List[schemas.VisitOut])
def list_visits(patient_id: Optional[UUID] = None, db: Session = Depends(get_db)):
    q = select(models.Visit).order_by(desc(models.Visit.visit_date))
    if patient_id:
        q = q.where(models.Visit.patient_id == patient_id)
    return db.scalars(q).all()


@app.post("/visits", response_model=schemas.VisitOut)
def create_visit(payload: schemas.VisitIn, db: Session = Depends(get_db)):
    v = models.Visit(**payload.model_dump())
    db.add(v); db.commit(); db.refresh(v)
    return v


# ── Observations ───────────────────────────────────────────────
@app.get("/observations", response_model=List[schemas.ObservationOut])
def list_observations(
    patient_id: Optional[UUID] = None,
    code: Optional[str] = None,
    db: Session = Depends(get_db),
):
    q = select(models.Observation).order_by(desc(models.Observation.observed_at))
    if patient_id: q = q.where(models.Observation.patient_id == patient_id)
    if code:       q = q.where(models.Observation.code == code)
    return db.scalars(q).all()


@app.post("/observations", response_model=schemas.ObservationOut)
def create_observation(payload: schemas.ObservationIn, db: Session = Depends(get_db)):
    # автофлаг по референсам
    data = payload.model_dump()
    if data.get("flag") is None and data.get("value_num") is not None:
        v = float(data["value_num"])
        lo = float(data["ref_low"]) if data.get("ref_low") is not None else None
        hi = float(data["ref_high"]) if data.get("ref_high") is not None else None
        if lo is not None and v < lo: data["flag"] = "low"
        elif hi is not None and v > hi: data["flag"] = "high"
        else:                            data["flag"] = "normal"
    o = models.Observation(**data)
    db.add(o); db.commit(); db.refresh(o)
    return o


# ── Problems ───────────────────────────────────────────────────
@app.get("/problems", response_model=List[schemas.ProblemOut])
def list_problems(patient_id: Optional[UUID] = None, db: Session = Depends(get_db)):
    q = select(models.ActiveProblem).order_by(desc(models.ActiveProblem.created_at))
    if patient_id: q = q.where(models.ActiveProblem.patient_id == patient_id)
    return db.scalars(q).all()


@app.post("/problems", response_model=schemas.ProblemOut)
def create_problem(payload: schemas.ProblemIn, db: Session = Depends(get_db)):
    p = models.ActiveProblem(**payload.model_dump())
    db.add(p); db.commit(); db.refresh(p)
    return p


@app.patch("/problems/{problem_id}", response_model=schemas.ProblemOut)
def update_problem(problem_id: UUID, payload: schemas.ProblemIn, db: Session = Depends(get_db)):
    pr = db.get(models.ActiveProblem, problem_id)
    if not pr: raise HTTPException(404, "problem not found")
    for k, v in payload.model_dump(exclude_unset=True).items():
        setattr(pr, k, v)
    db.commit(); db.refresh(pr)
    return pr


# ── Tasks ──────────────────────────────────────────────────────
@app.get("/tasks", response_model=List[schemas.TaskOut])
def list_tasks(patient_id: Optional[UUID] = None, status: Optional[str] = None, db: Session = Depends(get_db)):
    q = select(models.PersonalTask).order_by(models.PersonalTask.deadline.nullslast())
    if patient_id: q = q.where(models.PersonalTask.patient_id == patient_id)
    if status:     q = q.where(models.PersonalTask.status == status)
    return db.scalars(q).all()


@app.post("/tasks", response_model=schemas.TaskOut)
def create_task(payload: schemas.TaskIn, db: Session = Depends(get_db)):
    t = models.PersonalTask(**payload.model_dump())
    db.add(t); db.commit(); db.refresh(t)
    return t


@app.patch("/tasks/{task_id}", response_model=schemas.TaskOut)
def update_task(task_id: UUID, payload: schemas.TaskIn, db: Session = Depends(get_db)):
    t = db.get(models.PersonalTask, task_id)
    if not t: raise HTTPException(404, "task not found")
    for k, v in payload.model_dump(exclude_unset=True).items():
        setattr(t, k, v)
    db.commit(); db.refresh(t)
    return t


# ── Files (MinIO) ──────────────────────────────────────────────
@app.post("/files", response_model=schemas.FileOut)
def upload_file(
    patient_id: UUID = Form(...),
    visit_id: Optional[UUID] = Form(None),
    description: Optional[str] = Form(None),
    file: UploadFile = FFile(...),
    db: Session = Depends(get_db),
):
    if not db.get(models.Patient, patient_id):
        raise HTTPException(404, "patient not found")
    raw = file.file.read()
    key = f"{patient_id}/{uuid4()}-{file.filename}"
    storage.upload(BytesIO(raw), len(raw), key, file.content_type or "application/octet-stream")
    f = models.File(
        patient_id=patient_id, visit_id=visit_id,
        object_key=key, original_name=file.filename, mime_type=file.content_type,
        size_bytes=len(raw), file_type=(file.content_type or "").split("/")[0],
        description=description,
    )
    db.add(f); db.commit(); db.refresh(f)
    return f


@app.get("/files", response_model=List[schemas.FileOut])
def list_files(patient_id: Optional[UUID] = None, db: Session = Depends(get_db)):
    q = select(models.File).order_by(desc(models.File.uploaded_at))
    if patient_id: q = q.where(models.File.patient_id == patient_id)
    return db.scalars(q).all()


@app.get("/files/{file_id}/url")
def file_url(file_id: UUID, db: Session = Depends(get_db)):
    f = db.get(models.File, file_id)
    if not f: raise HTTPException(404, "file not found")
    return {"url": storage.presigned_get(f.object_key)}
