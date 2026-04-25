-- Health OS — init Postgres
-- Этот файл исполняется один раз при первой инициализации контейнера.
-- Создаёт: БД hapi (для HAPI FHIR), БД ingest (для операционной схемы ingest-агента),
-- включает pgvector и pgcrypto.

-- Подключаемся к основной БД, которую создал POSTGRES_DB=healthos
\connect healthos

CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- ─────────────────────────────────────────────
-- База для HAPI FHIR
-- ─────────────────────────────────────────────
CREATE DATABASE hapi
    WITH ENCODING 'UTF8'
         LC_COLLATE 'C.UTF-8'
         LC_CTYPE 'C.UTF-8'
         TEMPLATE template0;

\connect hapi
CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- ─────────────────────────────────────────────
-- База для ingest-агента (operational state + словари)
-- ─────────────────────────────────────────────
\connect healthos
CREATE DATABASE ingest
    WITH ENCODING 'UTF8'
         LC_COLLATE 'C.UTF-8'
         LC_CTYPE 'C.UTF-8'
         TEMPLATE template0;

\connect ingest
CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE EXTENSION IF NOT EXISTS vector;     -- pgvector для embedding-поиска LOINC
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- Таблица задач ingest-пайплайна
CREATE TABLE IF NOT EXISTS ingest_jobs (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    message_id      TEXT UNIQUE NOT NULL,
    lab_id          TEXT,
    status          TEXT NOT NULL CHECK (status IN (
                        'fetched','classified','extracted','parsed',
                        'mapped','validated','written','synced',
                        'needs_review','failed')),
    error           JSONB,
    attempts        INT NOT NULL DEFAULT 0,
    raw_eml_path    TEXT,
    artifacts       JSONB NOT NULL DEFAULT '{}'::jsonb,
    fhir_resources  JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ingest_jobs_status_idx ON ingest_jobs(status);
CREATE INDEX IF NOT EXISTS ingest_jobs_created_idx ON ingest_jobs(created_at DESC);

-- Идемпотентность FHIR: (lab_id, order_id | sha256) -> FHIR resource IDs
CREATE TABLE IF NOT EXISTS fhir_idempotency (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    lab_id          TEXT NOT NULL,
    idem_key        TEXT NOT NULL,           -- order_id или sha256(pdf)
    report_id       TEXT NOT NULL,           -- DiagnosticReport/<id>
    observation_ids TEXT[] NOT NULL DEFAULT '{}',
    document_ref_id TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(lab_id, idem_key)
);

-- Словарь синонимов русский → LOINC (ручной + самообучение)
CREATE TABLE IF NOT EXISTS loinc_ru_synonyms (
    id              BIGSERIAL PRIMARY KEY,
    synonym         TEXT NOT NULL,
    loinc_code      TEXT NOT NULL,
    loinc_display   TEXT NOT NULL,
    display_ru      TEXT NOT NULL,
    default_unit    TEXT,                    -- UCUM, напр. 'mmol/L'
    source          TEXT NOT NULL CHECK (source IN ('manual','dict_import','llm_confirmed')),
    confidence      REAL NOT NULL DEFAULT 1.0,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS loinc_syn_lower_idx
    ON loinc_ru_synonyms (lower(synonym));
CREATE INDEX IF NOT EXISTS loinc_syn_trgm_idx
    ON loinc_ru_synonyms USING gin (synonym gin_trgm_ops);

-- Векторный индекс LOINC для embedding-поиска
-- Размерность 1024 соответствует intfloat/multilingual-e5-large.
CREATE TABLE IF NOT EXISTS loinc_embeddings (
    loinc_code      TEXT PRIMARY KEY,
    display_en      TEXT NOT NULL,
    display_ru      TEXT,
    embedding       vector(1024)
);
CREATE INDEX IF NOT EXISTS loinc_emb_hnsw_idx
    ON loinc_embeddings USING hnsw (embedding vector_cosine_ops);

-- Критические пороги (редактируется вместе с врачом)
CREATE TABLE IF NOT EXISTS critical_thresholds (
    id              BIGSERIAL PRIMARY KEY,
    loinc_code      TEXT NOT NULL,
    label           TEXT NOT NULL,
    unit_ucum       TEXT NOT NULL,
    critical_low    REAL,
    critical_high   REAL,
    severity        TEXT NOT NULL CHECK (severity IN ('medium','high','critical')),
    note            TEXT,
    UNIQUE(loinc_code, unit_ucum)
);

-- Минимальный seed: 30 популярных показателей с LOINC.
-- Расширяется по мере накопления в word-profiles и через llm_confirmed.
INSERT INTO loinc_ru_synonyms (synonym, loinc_code, loinc_display, display_ru, default_unit, source) VALUES
  ('Глюкоза',                    '2345-7', 'Glucose [Mass/volume] in Serum or Plasma',       'Глюкоза в сыворотке',          'mmol/L', 'manual'),
  ('Glucose',                    '2345-7', 'Glucose [Mass/volume] in Serum or Plasma',       'Глюкоза в сыворотке',          'mmol/L', 'manual'),
  ('HbA1c',                      '4548-4', 'Hemoglobin A1c/Hemoglobin.total in Blood',       'Гликированный гемоглобин',     '%',      'manual'),
  ('Гликированный гемоглобин',   '4548-4', 'Hemoglobin A1c/Hemoglobin.total in Blood',       'Гликированный гемоглобин',     '%',      'manual'),
  ('АЛТ',                        '1742-6', 'Alanine aminotransferase [Enzymatic activity/volume] in Serum or Plasma', 'АЛТ',                          'U/L',    'manual'),
  ('Аланинаминотрансфераза',     '1742-6', 'Alanine aminotransferase',                       'АЛТ',                          'U/L',    'manual'),
  ('АСТ',                        '1920-8', 'Aspartate aminotransferase',                     'АСТ',                          'U/L',    'manual'),
  ('Аспартатаминотрансфераза',   '1920-8', 'Aspartate aminotransferase',                     'АСТ',                          'U/L',    'manual'),
  ('Билирубин общий',            '1975-2', 'Bilirubin.total [Mass/volume] in Serum or Plasma','Билирубин общий',              'umol/L', 'manual'),
  ('Билирубин прямой',           '1968-7', 'Bilirubin.direct',                               'Билирубин прямой',             'umol/L', 'manual'),
  ('Креатинин',                  '2160-0', 'Creatinine [Mass/volume] in Serum or Plasma',    'Креатинин в сыворотке',        'umol/L', 'manual'),
  ('Мочевина',                   '3094-0', 'Urea nitrogen [Mass/volume] in Serum or Plasma', 'Мочевина',                     'mmol/L', 'manual'),
  ('Холестерин общий',           '2093-3', 'Cholesterol [Mass/volume] in Serum or Plasma',   'Холестерин общий',             'mmol/L', 'manual'),
  ('Холестерин ЛПНП',            '13457-7','Cholesterol in LDL [Mass/volume] by calculation','Холестерин ЛПНП',              'mmol/L', 'manual'),
  ('Холестерин ЛПВП',            '2085-9', 'Cholesterol in HDL [Mass/volume] in Serum or Plasma','Холестерин ЛПВП',          'mmol/L', 'manual'),
  ('Триглицериды',               '2571-8', 'Triglyceride [Mass/volume] in Serum or Plasma',  'Триглицериды',                 'mmol/L', 'manual'),
  ('ТТГ',                        '3016-3', 'Thyrotropin [Units/volume] in Serum or Plasma',  'ТТГ',                          'mIU/L',  'manual'),
  ('Т4 свободный',               '3024-7', 'Thyroxine (T4) free [Mass/volume] in Serum or Plasma','Т4 свободный',            'pmol/L', 'manual'),
  ('Т3 свободный',               '3051-0', 'Triiodothyronine (T3) free',                     'Т3 свободный',                 'pmol/L', 'manual'),
  ('Ферритин',                   '2276-4', 'Ferritin [Mass/volume] in Serum or Plasma',      'Ферритин',                     'ug/L',   'manual'),
  ('Железо',                     '2498-4', 'Iron [Mass/volume] in Serum or Plasma',          'Железо сывороточное',          'umol/L', 'manual'),
  ('Витамин D',                  '62292-8','25-hydroxyvitamin D3+D2 [Mass/volume] in Serum or Plasma','25-OH витамин D',     'ng/mL',  'manual'),
  ('Витамин B12',                '2132-9', 'Cobalamins [Mass/volume] in Serum or Plasma',    'Витамин B12',                  'pmol/L', 'manual'),
  ('Гемоглобин',                 '718-7',  'Hemoglobin [Mass/volume] in Blood',              'Гемоглобин',                   'g/L',    'manual'),
  ('Эритроциты',                 '789-8',  'Erythrocytes [#/volume] in Blood by Automated count','Эритроциты',               '10*12/L','manual'),
  ('Лейкоциты',                  '6690-2', 'Leukocytes [#/volume] in Blood by Automated count','Лейкоциты',                  '10*9/L', 'manual'),
  ('Тромбоциты',                 '777-3',  'Platelets [#/volume] in Blood by Automated count','Тромбоциты',                  '10*9/L', 'manual'),
  ('СОЭ',                        '4537-7', 'Erythrocyte sedimentation rate',                 'СОЭ',                          'mm/h',   'manual'),
  ('СРБ',                        '1988-5', 'C reactive protein [Mass/volume] in Serum or Plasma','С-реактивный белок',       'mg/L',   'manual'),
  ('C-реактивный белок',         '1988-5', 'C reactive protein',                             'С-реактивный белок',           'mg/L',   'manual'),
  ('Калий',                      '2823-3', 'Potassium [Moles/volume] in Serum or Plasma',    'Калий',                        'mmol/L', 'manual'),
  ('Натрий',                     '2951-2', 'Sodium [Moles/volume] in Serum or Plasma',       'Натрий',                       'mmol/L', 'manual'),
  ('Кальций',                    '17861-6','Calcium [Mass/volume] in Serum or Plasma',       'Кальций общий',                'mmol/L', 'manual'),
  ('Магний',                     '19123-9','Magnesium [Moles/volume] in Serum or Plasma',    'Магний',                       'mmol/L', 'manual'),
  ('Гомоцистеин',                '13965-9','Homocysteine [Moles/volume] in Serum or Plasma', 'Гомоцистеин',                  'umol/L', 'manual')
ON CONFLICT DO NOTHING;

-- Стартовые критические пороги (3 самых важных).
INSERT INTO critical_thresholds (loinc_code, label, unit_ucum, critical_low, critical_high, severity, note) VALUES
  ('2345-7', 'Глюкоза',  'mmol/L', 2.8, 11.0, 'critical', 'Гипо-/гипергликемия — срочно'),
  ('2823-3', 'Калий',    'mmol/L', 3.0, 6.0,  'critical', 'Нарушения ритма при выходе'),
  ('718-7',  'Гемоглобин','g/L',   70,  200,  'high',     'Тяжёлая анемия / полицитемия')
ON CONFLICT DO NOTHING;
