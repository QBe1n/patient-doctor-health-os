"""Pydantic schemas for API."""
from __future__ import annotations
from datetime import date, datetime
from decimal import Decimal
from typing import Optional, List
from uuid import UUID
from pydantic import BaseModel, Field, ConfigDict


class _ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ── Family ─────────────────────────────────────────────────────
class FamilyIn(BaseModel):
    name: str
    notes: Optional[str] = None


class FamilyOut(_ORM, FamilyIn):
    id: UUID
    created_at: datetime


# ── Patient ────────────────────────────────────────────────────
class PatientIn(BaseModel):
    family_id: Optional[UUID] = None
    full_name: str
    birth_date: Optional[date] = None
    sex: Optional[str] = None
    blood_type: Optional[str] = None
    allergies: Optional[str] = None
    chronic_summary: Optional[str] = None
    notes: Optional[str] = None


class PatientOut(_ORM, PatientIn):
    id: UUID
    created_at: datetime


# ── Visit ──────────────────────────────────────────────────────
class VisitIn(BaseModel):
    patient_id: UUID
    visit_date: date
    visit_type: Optional[str] = None
    specialty: Optional[str] = None
    practitioner: Optional[str] = None
    facility: Optional[str] = None
    reason: Optional[str] = None
    summary: Optional[str] = None
    diagnosis_codes: Optional[List[str]] = None
    next_visit_date: Optional[date] = None


class VisitOut(_ORM, VisitIn):
    id: UUID
    created_at: datetime


# ── Observation ────────────────────────────────────────────────
class ObservationIn(BaseModel):
    patient_id: UUID
    visit_id: Optional[UUID] = None
    code: str
    code_system: str = "local"
    display_name: Optional[str] = None
    value_num: Optional[Decimal] = None
    value_text: Optional[str] = None
    unit: Optional[str] = None
    ref_low: Optional[Decimal] = None
    ref_high: Optional[Decimal] = None
    flag: Optional[str] = None
    body_site: Optional[str] = None
    observed_at: datetime
    notes: Optional[str] = None


class ObservationOut(_ORM, ObservationIn):
    id: UUID


# ── ActiveProblem ──────────────────────────────────────────────
class ProblemIn(BaseModel):
    patient_id: UUID
    title: str
    icd10: Optional[str] = None
    status: str = "active"
    severity: Optional[str] = None
    onset_date: Optional[date] = None
    next_review_date: Optional[date] = None
    careplan_template: Optional[str] = None
    notes: Optional[str] = None


class ProblemOut(_ORM, ProblemIn):
    id: UUID


# ── Task ──────────────────────────────────────────────────────
class TaskIn(BaseModel):
    patient_id: UUID
    problem_id: Optional[UUID] = None
    title: str
    description: Optional[str] = None
    priority: Optional[str] = None
    status: str = "planned"
    frequency: Optional[str] = None
    deadline: Optional[date] = None
    next_run: Optional[date] = None
    cost_rub: Optional[Decimal] = None
    result: Optional[str] = None


class TaskOut(_ORM, TaskIn):
    id: UUID


# ── File ──────────────────────────────────────────────────────
class FileOut(_ORM):
    id: UUID
    patient_id: UUID
    visit_id: Optional[UUID] = None
    object_key: str
    original_name: Optional[str]
    mime_type: Optional[str]
    size_bytes: Optional[int]
    file_type: Optional[str]
    description: Optional[str]
    uploaded_at: datetime


# ── Patient summary ──────────────────────────────────────────
class PatientSummary(BaseModel):
    patient: PatientOut
    family: Optional[FamilyOut] = None
    visits: List[VisitOut] = Field(default_factory=list)
    problems: List[ProblemOut] = Field(default_factory=list)
    tasks: List[TaskOut] = Field(default_factory=list)
    latest_observations: List[ObservationOut] = Field(default_factory=list)
