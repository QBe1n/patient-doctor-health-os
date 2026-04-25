# Ingest-агент для лабораторий: архитектура

**Контекст:** подагент `ingest.labs.email` из общего плана Health OS. Забирает PDF-результаты из писем Инвитро / Гемотеста / KDL / Хеликса / CMD / Citilab, парсит, маппит на LOINC, пишет в HAPI FHIR.

**Принципы:**

- Каждый этап — отдельный модуль с чистым контрактом (dataclass на вход, dataclass на выход). Можно тестировать изолированно и переставлять без переписывания соседей.
- Идемпотентность на каждом шаге: повторный прогон того же письма не создаёт дублей в FHIR.
- Fail-safe: любой этап может упасть, pipeline помечает сообщение как `needs_review` и идёт дальше. Никакого «уронили цикл — пропустили следующую лабу».
- Human-in-the-loop там, где LLM может ошибиться в цифрах (это всегда).

---

## 1. Поток данных (высокий уровень)

```
┌──────────────┐   ┌──────────────┐   ┌──────────────┐   ┌──────────────┐
│   IMAP       │──▶│  Classifier  │──▶│  Extractor   │──▶│  Parser      │
│   puller     │   │  (lab_id)    │   │  (PDF→text)  │   │  (text→obs)  │
│  every 15min │   │              │   │              │   │              │
└──────────────┘   └──────────────┘   └──────────────┘   └──────┬───────┘
       │                                                         │
       ▼                                                         ▼
┌──────────────┐                                         ┌──────────────┐
│  Raw storage │                                         │   Mapper     │
│   MinIO      │                                         │  (→ LOINC)   │
│  .eml + .pdf │                                         └──────┬───────┘
└──────────────┘                                                │
                                                                ▼
┌──────────────┐   ┌──────────────┐   ┌──────────────┐   ┌──────────────┐
│   Alerts     │◀──│   Notion     │◀──│   FHIR       │◀──│  Validator   │
│   dispatcher │   │   sync       │   │   writer     │   │  + flags     │
└──────┬───────┘   └──────────────┘   └──────────────┘   └──────────────┘
       │
       ▼
┌──────────────┐
│  Telegram /  │
│    email     │
└──────────────┘
```

Каждый блок ниже описан отдельно: что на входе, что на выходе, чем решается, как тестируется, что может сломаться.

---

## 2. Модули и контракты

### 2.1 `IMAP Puller`

**Что делает:** раз в 15 минут ходит в почтовый ящик `labs@домен` и забирает новые письма.

```python
@dataclass
class RawEmail:
    message_id: str            # IMAP Message-ID, идемпотентный ключ
    received_at: datetime
    from_addr: str
    subject: str
    body_text: str | None
    body_html: str | None
    attachments: list[Attachment]  # bytes + content_type + filename
    raw_eml_path: str          # путь в MinIO, куда положили исходник
```

**Реализация:** [`imap_tools`](https://github.com/ikvk/imap_tools), пулим через IMAP IDLE или просто по cron. Для каждого нового письма:
1. Сохраняем сырой `.eml` в MinIO (`/raw-emails/YYYY/MM/<message_id>.eml`) — это audit trail и возможность переразобрать, если парсер улучшим.
2. Сохраняем вложения отдельно (`/raw-attachments/<message_id>/<filename>`).
3. Помечаем письмо прочитанным только **после** успешного коммита в БД состояний (таблица `ingest_jobs`), чтобы при падении не потерять.

**Идемпотентность:** перед обработкой смотрим `ingest_jobs` по `message_id` — если уже есть, пропускаем.

**Что ломается:**
- IMAP-сессия обрывается → ловим, переподключаемся, ретраим.
- Сеть умерла → job остаётся в состоянии `fetched`, следующий прогон доберёт.
- Письмо > 25 МБ → обычно это снимки, не лабы; логируем и шлём себе в TG «посмотри вручную».

**Отдельный почтовый ящик обязателен.** Никогда не ходить в основной. На старте — алиас/отдельный GSuite/Yandex 360 ящик, бэкап в локальный IMAP через [dovecot](https://www.dovecot.org) если параноишь.

### 2.2 `Classifier`

**Что делает:** определяет, от какой лаборатории пришло письмо. От этого выбирается extractor-профиль.

```python
@dataclass
class ClassifiedEmail:
    raw: RawEmail
    lab_id: Literal["invitro", "gemotest", "kdl", "helix", "cmd", "citilab", "unknown"]
    confidence: float
    reason: str                # "from=results@invitro.ru" / "pdf header" / ...
```

**Реализация — приоритет от дешёвого к дорогому:**

1. **По From/Return-Path.** 95% случаев решается здесь. Справочник:
   - Инвитро: `noreply@invitro.ru`, `results@invitro.ru`
   - Гемотест: `noreply@gemotest.ru`, `info@gemotest.ru`
   - KDL: `info@kdl.ru`
   - Хеликс: `no-reply@helix.ru`
   - CMD: `noreply@cmd-online.ru`
   - Citilab: `noreply@citilab.ru`
2. **По DKIM-подписи** (тот же домен — подтверждение подлинности, защита от фишинга).
3. **По содержанию subject + первой странице PDF** (fallback для ребрендингов). Используется [`pypdf`](https://pypi.org/project/pypdf/) чтобы быстро достать первую страницу и искать по шаблонам.
4. **Если не определили — `lab_id=unknown`**, письмо отправляется в очередь `needs_review` с уведомлением в TG.

**Тест:** фикстуры с 5–10 реальными письмами от каждой лабы → classifier должен давать правильный `lab_id` с confidence ≥ 0.9.

### 2.3 `Extractor` (PDF → структурированный текст)

**Что делает:** из бинарного PDF достаёт текст с сохранённой структурой таблиц.

```python
@dataclass
class ExtractedDocument:
    source_path: str           # MinIO
    lab_id: str
    pages: list[Page]
    tables: list[Table]        # с ячейками и bbox
    metadata: dict             # дата, № заказа, пациент — если удалось достать
    extraction_method: str     # "docling_native" / "docling_ocr" / "paddle_fallback"
    quality_score: float       # 0–1, по числу распознанных таблиц/текста
```

**Три режима в порядке попыток:**

1. **Docling native** ([docling-project/docling](https://github.com/docling-project/docling)) — для программно сгенерированных PDF. Сохраняет структуру таблиц, работает с русским. 80%+ писем лабораторий сюда попадает.
2. **Docling с OCR** — для сканов и «PDF-с-картинкой-внутри». Внутри Docling вызывает [EasyOCR](https://github.com/JaidedAI/EasyOCR) или Tesseract с русским языком.
3. **PaddleOCR fallback** ([PaddleOCR](https://github.com/PaddlePaddle/PaddleOCR)) — когда Docling совсем плохо справился (сильно искажённые сканы, фото с телефона).

**Сигнал «плохо справился»:** `quality_score < 0.5` (например, Docling не нашёл таблиц на странице, где глазами видно таблицу).

**Всё прогоняется локально**, облачные OCR-сервисы не используем — это PHI.

**Что ломается:**
- Защищённый паролем PDF → лабы иногда шлют с паролем `первые 4 цифры даты рождения` или `номер заказа`. Держим в `ingest_jobs` поле `pdf_password` (если пользователь указал), иначе — в `needs_review`.
- PDF с encoding-лапшой (редко, но бывает у старых МИС) → уходит на Paddle.
- Многостраничные PDF с несколькими отчётами в одном файле → Extractor режет по маркерам «Заказ №» / «Исследование» (это уже логика Parser'а, Extractor просто отдаёт всё как есть).

### 2.4 `Parser` (lab-specific)

**Что делает:** превращает извлечённый документ в список «сырых измерений». Это **самый хрупкий** модуль и поэтому **отдельная реализация для каждой лабы** + универсальный LLM-fallback.

```python
@dataclass
class RawMeasurement:
    raw_name: str              # как в PDF: "Глюкоза", "АЛТ", "Холестерин ЛПНП"
    value_raw: str             # "5.8", "положительный", "< 0.1"
    unit_raw: str              # "ммоль/л", "Ед/л", ""
    reference_raw: str         # "3.9 – 5.5", "< 5.0", "отрицательный"
    taken_at: datetime | None  # когда взят биоматериал
    lab_section: str           # "Биохимия крови" / "Общий анализ крови"
    raw_text_block: str        # исходный кусок, откуда извлекли — для отладки

@dataclass
class ParsedReport:
    lab_id: str
    order_id: str | None       # № заказа лаборатории (для идемпотентности)
    collected_at: datetime
    issued_at: datetime
    patient_hint: dict         # {first_name, birth_year} — НЕ кладём в FHIR вслепую, используем только для сопоставления
    measurements: list[RawMeasurement]
    raw_document_ref: str      # ссылка на MinIO
```

**Два уровня парсинга:**

**Уровень 1: Lab profile (детерминистичный, быстрый, надёжный).**
Для каждой лабы — модуль `parsers/invitro.py`, `parsers/gemotest.py` и т.д. Внутри — regex/pandas-подход:
- Знаем, что у Инвитро таблица с колонками `Исследование | Результат | Референсные значения | Ед. изм.`
- Знаем якорные фразы: `Номер заказа: ...`, `Дата взятия: ...`.
- Парсим это детерминистично. Скорость ~100 мс, нет галлюцинаций.

**Уровень 2: LLM fallback.**
Если lab profile упал или confidence низкий — отправляем в локальный Qwen 2.5 14B / MedGemma со структурированным промптом и JSON-schema ([Ollama structured outputs](https://ollama.com/blog/structured-outputs) или [llama.cpp grammar](https://github.com/ggerganov/llama.cpp/tree/master/grammars)):

```
Извлеки из текста лабораторного отчёта список измерений.
Верни JSON по схеме: [{raw_name, value_raw, unit_raw, reference_raw}].
Не добавляй показатели, которых нет в тексте. Не интерпретируй.
Если не уверен в значении — укажи null.
```

**Две контрольные проверки после LLM:**

1. **Цифры не галлюцинированы.** Для каждого `value_raw` проверяем: эта строка встречается в исходном тексте? Если нет — помечаем `confidence=low`, отправляем в `needs_review`.
2. **Полнота.** Считаем строки, похожие на таблицу в исходнике vs выданных LLM измерений. Расхождение > 20% → `needs_review`.

**Это неприятное, но критичное правило: LLM не пишет цифры в FHIR без grounding-проверки.**

### 2.5 `Mapper` (raw → LOINC + нормализация)

**Что делает:** превращает `RawMeasurement` в `NormalizedMeasurement` с LOINC-кодом, численным значением, единицей измерения в стандартной шкале.

```python
@dataclass
class NormalizedMeasurement:
    loinc_code: str            # "2345-7"
    loinc_display: str         # "Glucose [Mass/volume] in Serum or Plasma"
    display_ru: str            # "Глюкоза в сыворотке"
    value_quantity: float | None
    value_string: str | None   # для качественных (положительный/отрицательный)
    unit_ucum: str             # "mmol/L", "U/L" — UCUM
    reference_low: float | None
    reference_high: float | None
    interpretation: Literal["normal", "low", "high", "critical_low", "critical_high", "abnormal", "unknown"]
    mapping_confidence: float
    mapping_source: Literal["dict_exact", "dict_synonym", "llm", "manual"]
```

**Трёхуровневый маппинг:**

1. **Словарь синонимов (локальный).** Таблица `loinc_ru_synonyms` в Postgres:
   ```
   "Глюкоза"               → 2345-7
   "Глюкоза в сыворотке"   → 2345-7
   "Glucose"               → 2345-7
   "ALT"                   → 1742-6
   "АЛТ"                   → 1742-6
   "Аланинаминотрансфераза"→ 1742-6
   ...
   ```
   На старте — 50 самых частых показателей (покрывают 80% реальных писем). Наполняется по мере накопления.

2. **Embedding-поиск** ([`pgvector`](https://github.com/pgvector/pgvector) или [Qdrant](https://qdrant.tech) локально). Если точного совпадения нет — считаем эмбеддинг русского названия (через локальную модель [`intfloat/multilingual-e5-large`](https://huggingface.co/intfloat/multilingual-e5-large)), ищем топ-3 кандидата в справочнике LOINC (заранее проиндексированном: `display_ru`, `display_en`, синонимы).

3. **LLM-подтверждение.** Топ-3 кандидата → в промпт к Qwen/MedGemma вместе с единицей измерения и референсом: «Какой LOINC соответствует показателю `X = Y ед` с референсом `[A–B]`?». LLM выбирает один или говорит «не уверен» → `needs_review`.

**Нормализация единиц в UCUM.** `ммоль/л → mmol/L`, `мкмоль/л → umol/L`, `Ед/л → U/L`. Маленькая таблица конверсий (20 строк) + конвертеры для частых `mg/dL → mmol/L` (глюкоза, холестерин). Если единица неизвестная — сохраняем как есть и помечаем `needs_review`.

**Interpretation** считает Validator (следующий модуль), не Mapper.

**Новые синонимы самообучаются.** Если маппинг прошёл через LLM и пользователь подтвердил — добавляем в `loinc_ru_synonyms` как `mapping_source=llm_confirmed`. За 2–3 месяца словарь покроет твой реальный репертуар анализов.

### 2.6 `Validator + Flag generator`

**Что делает:** сравнивает нормализованные значения с референсами, помечает отклонения, поднимает флаги.

```python
@dataclass
class ValidatedObservation:
    normalized: NormalizedMeasurement
    interpretation: str        # HL7 коды: N/L/H/LL/HH/A
    flags: list[Flag]          # возможно пусто
    delta_from_norm: float | None  # насколько вне нормы (в сигмах или %)

@dataclass
class Flag:
    severity: Literal["low", "medium", "high", "critical"]
    type: Literal["out_of_range", "critical_threshold", "trend", "missing_followup"]
    reason: str                # "Glucose = 11.2 mmol/L, норма 3.9–5.5"
    action_hint: str           # "Обсудите с терапевтом/эндокринологом"
```

**Правила:**

- Любое значение вне `[reference_low, reference_high]` → `interpretation = H` или `L`.
- **Критические пороги** (hard-coded, не зависят от референса лабы):
  - Glucose > 11 mmol/L → `critical_high`, немедленный TG-пуш.
  - Potassium < 3.0 или > 6.0 → `critical`.
  - Hemoglobin < 70 g/L → `critical_low`.
  - SpO2 < 92% (из wearable ingest) → `critical`.
  - Список ведётся в `critical_thresholds.yaml`, редактируется вместе с врачом.
- **Тренды** (требуют истории, ≥3 предыдущих значений того же показателя): рост > 20% за 30 дней у ключевых маркёров → `medium`.

**Формулировка алерта всегда:** «Показатель = значение, вне нормы [X–Y]. Обсудите с врачом.» Никаких «у вас диабет».

### 2.7 `FHIR Writer` (идемпотентный)

**Что делает:** пишет в HAPI FHIR `DiagnosticReport` + вложенные `Observation` + прикрепляет исходный PDF как `DocumentReference`.

**Идемпотентный ключ:** `(lab_id, order_id)` если есть `order_id`, иначе `(lab_id, collected_at, patient_id, sha256(raw_pdf))`. Храним в собственной таблице `fhir_idempotency` с маппингом на FHIR resource IDs.

**Порядок записи (важен для транзакционности):**

1. Если `DiagnosticReport` с этим ключом уже есть — **апдейт** (редкий случай: лаба прислала исправленные значения). Сохраняем старую версию через FHIR history.
2. Создаём `DocumentReference` со ссылкой на MinIO → PDF + `content.attachment.url = "minio://..."`.
3. Создаём `DiagnosticReport` с метаданными.
4. Для каждой `ValidatedObservation` создаём `Observation`, ссылающийся на `DiagnosticReport` через `Observation.basedOn`.
5. Для каждого `Flag` с `severity >= medium` создаём ресурс `Flag` с `Flag.subject = Patient/<id>`.

**Транзакция:** используем FHIR `Bundle` с `type=transaction` — HAPI гарантирует atomicity. Если любой ресурс не прошёл валидацию (например, неизвестный LOINC) — откатывается весь bundle, job уходит в `needs_review`.

**Профиль Observation заполняем минимально-честно:**

```json
{
  "resourceType": "Observation",
  "status": "final",
  "category": [{"coding": [{"system": "http://terminology.hl7.org/CodeSystem/observation-category", "code": "laboratory"}]}],
  "code": {"coding": [
    {"system": "http://loinc.org", "code": "2345-7", "display": "Glucose [Mass/volume] in Serum or Plasma"}
  ], "text": "Глюкоза"},
  "subject": {"reference": "Patient/001"},
  "effectiveDateTime": "2026-04-24T08:30:00+03:00",
  "issued": "2026-04-24T15:00:00+03:00",
  "performer": [{"reference": "Organization/invitro"}],
  "valueQuantity": {"value": 6.2, "unit": "mmol/L", "system": "http://unitsofmeasure.org", "code": "mmol/L"},
  "referenceRange": [{"low": {"value": 3.9}, "high": {"value": 5.5}}],
  "interpretation": [{"coding": [{"system": "http://terminology.hl7.org/CodeSystem/v3-ObservationInterpretation", "code": "H"}]}],
  "basedOn": [{"reference": "DiagnosticReport/<id>"}]
}
```

### 2.8 `Notion Sync`

**Что делает:** обновляет проекции в Notion после успешной записи в FHIR.

**Идемпотентность:** в property `FHIR ID` каждой строки Notion хранится ID ресурса. Upsert по этому полю.

**Что синкается:**
- В БД «Анализы» — 1 строка на `DiagnosticReport`, с агрегированным флагом (`✓` / `⚠` / `🔴`) и ссылкой на локальный PDF (URL в LAN через Tailscale).
- В БД «Метрики» — по одной строке на `Observation`.
- В БД «Алерты» — по одной строке на `Flag`.

**Что НЕ синкается в Notion:**
- `DocumentReference` с сырым PDF — только ссылка.
- Любое поле с расшифровкой диагноза по спецкатегориям (психиатрия/ВИЧ/наркология) — они живут только в FHIR локально.

### 2.9 `Alerts Dispatcher`

**Что делает:** отправляет уведомления по критичным флагам.

- `severity=critical` → немедленный TG-пуш: «🔴 Glucose = 11.2 ммоль/л (норма 3.9–5.5). Это критическое значение. Свяжитесь с врачом.»
- `severity=high` → TG-пуш в течение часа.
- `severity=medium` → попадает в ежедневный digest в 9:00.
- `severity=low` → только в Notion, без пуша.

**Rate-limit:** не больше 5 пушей в час — остальное сливается в digest. Защита от «упали все метрики сразу» → спам.

---

## 3. Управление состоянием: таблица `ingest_jobs`

Вся pipeline — конечный автомат. Одна таблица в Postgres (не в HAPI — это не медицинские данные, а operational state):

```sql
CREATE TABLE ingest_jobs (
  id              UUID PRIMARY KEY,
  message_id      TEXT UNIQUE NOT NULL,
  lab_id          TEXT,
  status          TEXT NOT NULL,  -- fetched | classified | extracted | parsed | mapped | validated | written | synced | needs_review | failed
  error           JSONB,
  attempts        INT DEFAULT 0,
  raw_eml_path    TEXT,
  artifacts       JSONB,           -- ссылки на MinIO на каждом этапе
  fhir_resources  JSONB,           -- {report_id, observation_ids, ...} после записи
  created_at      TIMESTAMPTZ,
  updated_at      TIMESTAMPTZ
);
```

**Переходы:**

```
fetched → classified → extracted → parsed → mapped → validated → written → synced  ✓
   │          │            │         │         │         │           │
   └──────────┴────────────┴─────────┴─────────┴─────────┴───────────┴─→ needs_review
                                                                          (ручная проверка в Notion)
```

Ручная проверка: отдельная БД в Notion «Ingest очередь» с фильтром `status=needs_review`. Пациент видит письмо, краткую причину, может подтвердить/поправить в inline-форме → job возвращается в pipeline с `manual_override=true`.

---

## 4. Тестирование

**Уровни:**

1. **Unit-тесты на parser для каждой лабы** — фикстуры из 5–10 реальных PDF, ожидаемый JSON на выходе. Запускаются на каждый коммит.
2. **Integration-тест pipeline** — mock IMAP, реальный HAPI в Docker, fixture PDF → проверяем что в FHIR всё записалось идемпотентно (дважды прогоняем — дубли не появляются).
3. **Shadow mode для LLM-компонентов.** Когда добавляем LLM-fallback — неделю гоняем его параллельно с lab-profile парсером, сравниваем результаты, смотрим расхождения перед тем, как доверять.

**Тестовый pii-free корпус:** берём реальные PDF, заменяем ФИО/даты/номера на синтетические (через [presidio](https://github.com/microsoft/presidio) или регулярками), коммитим в приватный репо.

---

## 5. Развёртывание: docker-compose кусок

```yaml
services:
  ingest-worker:
    build: ./ingest
    environment:
      IMAP_HOST: imap.yandex.ru
      IMAP_USER_FILE: /run/secrets/imap_user
      IMAP_PASS_FILE: /run/secrets/imap_pass
      HAPI_BASE_URL: http://hapi:8080/fhir
      MINIO_ENDPOINT: minio:9000
      OLLAMA_HOST: http://ollama:11434
      POSTGRES_DSN_FILE: /run/secrets/pg_dsn
    secrets: [imap_user, imap_pass, pg_dsn]
    depends_on: [hapi, minio, ollama, postgres]
    restart: unless-stopped
    # Запускается как long-running с internal cron (APScheduler)
```

**Ресурсы:**
- Один процесс worker хватает (~50 писем/день).
- Пики CPU — в Docling/LLM. Если Ollama на том же хосте — даём ingest-worker 2 CPU, памяти 2 ГБ.

---

## 6. Что делаем на Дне 4–5 MVP (конкретный срез)

На 4–5 день недели 1 реализуем:

1. IMAP Puller → классификатор по From → MinIO-хранение.
2. Extractor через Docling (без OCR-фоллбека пока).
3. Parser только для Инвитро (один lab profile, детерминистичный).
4. Mapper со словарём на 30 самых частых показателей (глюкоза, холестерин, триглицериды, ЛПВП, ЛПНП, креатинин, мочевина, АЛТ, АСТ, билирубин прямой/общий, ТТГ, Т4, Т3, ферритин, железо, витамин D, B12, гемоглобин, эритроциты, лейкоциты, тромбоциты, СОЭ, СРБ, HbA1c, калий, натрий, кальций, магний, гомоцистеин).
5. Validator с референсами + первые 3 критических порога (глюкоза, калий, гемоглобин).
6. FHIR Writer через Bundle transaction.
7. Notion sync — только «Анализы» и «Метрики».
8. Alerts Dispatcher — только Telegram, только `critical`.

Всё остальное (Гемотест/KDL/Хеликс parsers, LLM-fallback, embedding-поиск, тренды, digest, OCR-режим) — в следующие итерации.

**Exit criteria Дня 5:** присылаешь реальное письмо от Инвитро на тестовый ящик → через 3 минуты в Notion строка в «Анализах» и 10–20 строк в «Метриках», флаги корректные. Повторный прогон того же письма — ноль новых записей.

---

## 7. Что НЕ делаем на этом агенте (вынесено в другие)

- **DICOM и снимки** — это `ingest.imaging`, другой pipeline.
- **Протоколы осмотров врачей из ЕМИАС** — это `ingest.emias`.
- **Носимые устройства** — это `ingest.wearables` с webhook-ом, не через почту.
- **Расшифровка фото рецептов** — это `ingest.prescriptions` с отдельным OCR-пайплайном для написанного от руки.

Всё это висит на том же HAPI FHIR, но свои extractor/parser/mapper — переиспользовать Dcling→LLM→LOINC-поток здесь нельзя, другая природа данных.
