-- Health OS — схема локальной БД
-- Семьи → Пациенты → Визиты → Наблюдения
--                  → Активные проблемы → Личные задачи

CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE EXTENSION IF NOT EXISTS vector;

-- Отдельная БД для HAPI FHIR (создаётся при первом старте)
SELECT 'CREATE DATABASE fhir'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'fhir')\gexec

-- ────────────────────────────────────────────────────────────────
-- Справочники
-- ────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS families (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name        TEXT NOT NULL,
    notes       TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS patients (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    family_id       UUID REFERENCES families(id) ON DELETE SET NULL,
    full_name       TEXT NOT NULL,
    birth_date      DATE,
    sex             TEXT CHECK (sex IN ('m', 'f', 'other') OR sex IS NULL),
    blood_type      TEXT,
    allergies       TEXT,
    chronic_summary TEXT,
    notes           TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_patients_family ON patients(family_id);
CREATE INDEX IF NOT EXISTS idx_patients_name   ON patients(full_name);

-- ────────────────────────────────────────────────────────────────
-- Визиты (Encounter) — хронология
-- ────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS visits (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    patient_id      UUID NOT NULL REFERENCES patients(id) ON DELETE CASCADE,
    visit_date      DATE NOT NULL,
    visit_type      TEXT,                    -- УЗИ, офтальмолог, терапевт, лаб
    specialty       TEXT,                    -- gastro, ophth, cardio, lab
    practitioner    TEXT,                    -- ФИО врача
    facility        TEXT,                    -- клиника
    reason          TEXT,
    summary         TEXT,                    -- общий вывод визита
    diagnosis_codes TEXT[],                  -- ICD-10 коды
    next_visit_date DATE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_visits_patient ON visits(patient_id, visit_date DESC);

-- ────────────────────────────────────────────────────────────────
-- Наблюдения (Observation, FHIR-style)
-- ────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS observations (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    patient_id      UUID NOT NULL REFERENCES patients(id) ON DELETE CASCADE,
    visit_id        UUID REFERENCES visits(id) ON DELETE SET NULL,
    code            TEXT NOT NULL,           -- IOP_OD, VA_OD, HBA1C, LDL, BP_SYS...
    code_system     TEXT DEFAULT 'local',    -- loinc | snomed | local
    display_name    TEXT,                    -- "ВГД OD", "HbA1c"
    value_num       NUMERIC,                 -- числовое значение
    value_text      TEXT,                    -- если результат текстовый
    unit            TEXT,                    -- mmHg, %, mmol/L
    ref_low         NUMERIC,
    ref_high        NUMERIC,
    flag            TEXT CHECK (flag IN ('low','normal','high','critical') OR flag IS NULL),
    body_site       TEXT,                    -- OD/OS/OU
    observed_at     TIMESTAMPTZ NOT NULL,
    notes           TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_obs_patient_code ON observations(patient_id, code, observed_at DESC);
CREATE INDEX IF NOT EXISTS idx_obs_visit        ON observations(visit_id);

-- ────────────────────────────────────────────────────────────────
-- Активные проблемы (Condition + CarePlan instance)
-- ────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS active_problems (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    patient_id      UUID NOT NULL REFERENCES patients(id) ON DELETE CASCADE,
    title           TEXT NOT NULL,           -- "НАЖБП", "Подозрение на глаукому OS"
    icd10           TEXT,                    -- K76.0, H40.x
    status          TEXT NOT NULL DEFAULT 'active'
                     CHECK (status IN ('active','chronic','monitoring','resolved','remission','suspect')),
    severity        TEXT,                    -- low/medium/high/critical
    onset_date      DATE,
    next_review_date DATE,
    careplan_template TEXT,                  -- ссылка на шаблон (NAFLD, ATH, HTN…)
    notes           TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_problems_patient ON active_problems(patient_id, status);

-- ────────────────────────────────────────────────────────────────
-- Личные задачи (Task)
-- ────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS personal_tasks (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    patient_id      UUID NOT NULL REFERENCES patients(id) ON DELETE CASCADE,
    problem_id      UUID REFERENCES active_problems(id) ON DELETE SET NULL,
    title           TEXT NOT NULL,
    description     TEXT,
    priority        TEXT CHECK (priority IN ('критический','высокий','средний','низкий') OR priority IS NULL),
    status          TEXT NOT NULL DEFAULT 'planned'
                     CHECK (status IN ('planned','in_progress','done','overdue','cancelled','recurring')),
    frequency       TEXT,                    -- разово, еженедельно, ежемесячно...
    deadline        DATE,
    next_run        DATE,
    cost_rub        NUMERIC,
    result          TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_tasks_patient_status ON personal_tasks(patient_id, status, deadline);

-- ────────────────────────────────────────────────────────────────
-- Файлы (PDF/фото анализов в MinIO)
-- ────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS files (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    patient_id      UUID NOT NULL REFERENCES patients(id) ON DELETE CASCADE,
    visit_id        UUID REFERENCES visits(id) ON DELETE SET NULL,
    object_key      TEXT NOT NULL,           -- путь в MinIO bucket
    original_name   TEXT,
    mime_type       TEXT,
    size_bytes      BIGINT,
    file_type       TEXT,                    -- pdf, image, scan
    description     TEXT,
    uploaded_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_files_patient ON files(patient_id, uploaded_at DESC);

-- ────────────────────────────────────────────────────────────────
-- Updated_at trigger
-- ────────────────────────────────────────────────────────────────

CREATE OR REPLACE FUNCTION touch_updated_at() RETURNS TRIGGER AS $$
BEGIN NEW.updated_at = now(); RETURN NEW; END;
$$ LANGUAGE plpgsql;

DO $$
DECLARE t TEXT;
BEGIN
  FOR t IN SELECT unnest(ARRAY['families','patients','visits','active_problems','personal_tasks']) LOOP
    EXECUTE format('DROP TRIGGER IF EXISTS trg_%s_touch ON %I; CREATE TRIGGER trg_%s_touch BEFORE UPDATE ON %I FOR EACH ROW EXECUTE FUNCTION touch_updated_at();', t, t, t, t);
  END LOOP;
END$$;

-- ────────────────────────────────────────────────────────────────
-- View: последние значения наблюдений по коду для пациента
-- ────────────────────────────────────────────────────────────────

CREATE OR REPLACE VIEW v_latest_observations AS
SELECT DISTINCT ON (patient_id, code, body_site)
    patient_id, code, display_name, body_site,
    value_num, value_text, unit, flag, observed_at
FROM observations
ORDER BY patient_id, code, body_site, observed_at DESC;
