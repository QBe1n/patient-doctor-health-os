"""SQLAlchemy ORM models — зеркало init.sql."""
from datetime import datetime, date
from uuid import uuid4
from sqlalchemy import (
    Column, String, Text, Date, DateTime, Numeric, BigInteger,
    ForeignKey, ARRAY, func
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from db import Base


def _id():
    return Column(UUID(as_uuid=True), primary_key=True, default=uuid4)


class Family(Base):
    __tablename__ = "families"
    id = _id()
    name = Column(Text, nullable=False)
    notes = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now())
    patients = relationship("Patient", back_populates="family")


class Patient(Base):
    __tablename__ = "patients"
    id = _id()
    family_id = Column(UUID(as_uuid=True), ForeignKey("families.id"))
    full_name = Column(Text, nullable=False)
    birth_date = Column(Date)
    sex = Column(Text)
    blood_type = Column(Text)
    allergies = Column(Text)
    chronic_summary = Column(Text)
    notes = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now())
    family = relationship("Family", back_populates="patients")
    visits = relationship("Visit", back_populates="patient", cascade="all, delete")
    observations = relationship("Observation", back_populates="patient", cascade="all, delete")
    problems = relationship("ActiveProblem", back_populates="patient", cascade="all, delete")
    tasks = relationship("PersonalTask", back_populates="patient", cascade="all, delete")
    files = relationship("File", back_populates="patient", cascade="all, delete")


class Visit(Base):
    __tablename__ = "visits"
    id = _id()
    patient_id = Column(UUID(as_uuid=True), ForeignKey("patients.id", ondelete="CASCADE"), nullable=False)
    visit_date = Column(Date, nullable=False)
    visit_type = Column(Text)
    specialty = Column(Text)
    practitioner = Column(Text)
    facility = Column(Text)
    reason = Column(Text)
    summary = Column(Text)
    diagnosis_codes = Column(ARRAY(Text))
    next_visit_date = Column(Date)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now())
    patient = relationship("Patient", back_populates="visits")
    observations = relationship("Observation", back_populates="visit")


class Observation(Base):
    __tablename__ = "observations"
    id = _id()
    patient_id = Column(UUID(as_uuid=True), ForeignKey("patients.id", ondelete="CASCADE"), nullable=False)
    visit_id = Column(UUID(as_uuid=True), ForeignKey("visits.id"))
    code = Column(Text, nullable=False)
    code_system = Column(Text, default="local")
    display_name = Column(Text)
    value_num = Column(Numeric)
    value_text = Column(Text)
    unit = Column(Text)
    ref_low = Column(Numeric)
    ref_high = Column(Numeric)
    flag = Column(Text)
    body_site = Column(Text)
    observed_at = Column(DateTime(timezone=True), nullable=False)
    notes = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    patient = relationship("Patient", back_populates="observations")
    visit = relationship("Visit", back_populates="observations")


class ActiveProblem(Base):
    __tablename__ = "active_problems"
    id = _id()
    patient_id = Column(UUID(as_uuid=True), ForeignKey("patients.id", ondelete="CASCADE"), nullable=False)
    title = Column(Text, nullable=False)
    icd10 = Column(Text)
    status = Column(Text, default="active", nullable=False)
    severity = Column(Text)
    onset_date = Column(Date)
    next_review_date = Column(Date)
    careplan_template = Column(Text)
    notes = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now())
    patient = relationship("Patient", back_populates="problems")
    tasks = relationship("PersonalTask", back_populates="problem")


class PersonalTask(Base):
    __tablename__ = "personal_tasks"
    id = _id()
    patient_id = Column(UUID(as_uuid=True), ForeignKey("patients.id", ondelete="CASCADE"), nullable=False)
    problem_id = Column(UUID(as_uuid=True), ForeignKey("active_problems.id"))
    title = Column(Text, nullable=False)
    description = Column(Text)
    priority = Column(Text)
    status = Column(Text, default="planned", nullable=False)
    frequency = Column(Text)
    deadline = Column(Date)
    next_run = Column(Date)
    cost_rub = Column(Numeric)
    result = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now())
    patient = relationship("Patient", back_populates="tasks")
    problem = relationship("ActiveProblem", back_populates="tasks")


class File(Base):
    __tablename__ = "files"
    id = _id()
    patient_id = Column(UUID(as_uuid=True), ForeignKey("patients.id", ondelete="CASCADE"), nullable=False)
    visit_id = Column(UUID(as_uuid=True), ForeignKey("visits.id"))
    object_key = Column(Text, nullable=False)
    original_name = Column(Text)
    mime_type = Column(Text)
    size_bytes = Column(BigInteger)
    file_type = Column(Text)
    description = Column(Text)
    uploaded_at = Column(DateTime(timezone=True), server_default=func.now())
    patient = relationship("Patient", back_populates="files")
