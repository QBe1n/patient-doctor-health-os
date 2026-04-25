# Health OS — локальный self-hosted стек

Полностью локальная медкарта семьи на твоей машине. Ничего не уходит в облако.

```
Семьи ──< Пациенты ──< Визиты ──< Наблюдения (FHIR-style)
            │
            ├──< Активные проблемы ──> CarePlan-шаблон
            │           │
            │           └──< Личные задачи
            │
            └──< Файлы (PDF/фото в MinIO)
```

## Что внутри

| Сервис | Порт | Назначение |
|---|---|---|
| **Web UI** | `localhost:3000` | основной интерфейс — добавление визитов, наблюдений, задач, файлов |
| **Backend API** | `localhost:8000` | FastAPI + автодокументация на `/docs` |
| **PostgreSQL 16 + pgvector** | `localhost:5432` | основная БД (named volume `health_os_pgdata`) |
| **MinIO** | `localhost:9000` (S3) / `:9001` (UI) | хранилище PDF/фото (named volume `health_os_miniodata`) |
| **HAPI FHIR R4** | `localhost:8080` | FHIR-эндпоинт для совместимости с медсистемами |
| **Ollama** *(опционально)* | `localhost:11434` | локальные LLM для ингеста PDF |

## Требования

- **Docker Desktop** или Docker Engine + Compose plugin
- ~2 GB свободной RAM, ~4 GB диска (без Ollama)
- macOS / Linux / Windows (WSL2)

## Запуск за 3 минуты

```bash
git clone https://github.com/QBe1n/patient-doctor-health-os
cd patient-doctor-health-os/local-stack
make up
```

Жди ~30 секунд (первый раз — пара минут на сборку backend/web и pull образов).

Открой **http://localhost:3000** — пустая медкарта готова.

### Загрузить пример (Кубальская И.В.)

```bash
make seed-kub
```

Создаст семью Кубальских, пациента, 3 визита (УЗИ ОБП + 2 офтальмолога), наблюдения (ВГД, VA), 5 активных проблем и 9 личных задач.

## Базовый рабочий цикл

> "Включил → запустил → проверил → обновил → внёс информацию → выключил → включил снова → всё на месте."

```bash
make up        # утром: запустил
# работаешь в http://localhost:3000:
#  - добавляешь визит "терапевт 25.04.2026"
#  - вносишь HbA1c, ЛПНП, АД
#  - загружаешь PDF результата
#  - закрываешь задачу "✓ done"
make down      # вечером: выключил, ноутбук в сон/выкл

# через неделю:
make up        # снова. БД, файлы, состояние задач — всё там же.
```

**Где лежат данные физически:**
```
docker volume ls | grep health_os
# health_os_pgdata     ← Postgres
# health_os_miniodata  ← все PDF/фото
# health_os_ollamadata ← модели LLM (только если включал ai-профиль)
```

`docker compose down` **не трогает** volumes. Только `make nuke` или `docker compose down -v` их удаляет.

## Команды

| Команда | Что делает |
|---|---|
| `make up` | поднять весь стек |
| `make down` | остановить (данные сохраняются) |
| `make restart` | перезапуск |
| `make logs` | хвост логов всех сервисов |
| `make status` | какие контейнеры живы |
| `make build` | пересобрать backend/web после правок кода |
| `make seed-kub` | засеять данные Кубальской И.В. (идемпотентно) |
| `make backup` | дамп БД + tar MinIO в `./backups/` |
| `make restore F=backups/db-XXXX.sql` | восстановить БД из дампа |
| `make ai-up` | поднять Ollama (профиль `ai`) |
| `make shell-pg` | psql внутри Postgres |
| `make shell-be` | bash в backend-контейнере |
| `make nuke` | ⚠️ удалить ВСЕ данные (с 5-сек паузой) |

## Бэкап на внешний диск

```bash
make backup
# создаст: backups/db-20260425-120000.sql + backups/minio-20260425-120000.tar.gz

# скопируй на внешний диск
cp backups/db-*.sql /Volumes/Backup/health-os/
cp backups/minio-*.tar.gz /Volumes/Backup/health-os/
```

Восстановление:
```bash
make up
make restore F=backups/db-20260425-120000.sql
# для MinIO:
docker run --rm -v health_os_miniodata:/data -v $(pwd)/backups:/in alpine \
  sh -c "rm -rf /data/* && tar xzf /in/minio-20260425-120000.tar.gz -C /data"
```

## Доступ к сервисам

- **Web UI:** http://localhost:3000
- **API + Swagger:** http://localhost:8000/docs
- **MinIO Console** (логин/пароль из `.env`): http://localhost:9001
- **HAPI FHIR:** http://localhost:8080

## Ручной ввод одной командой (curl)

```bash
# создать пациента
curl -X POST http://localhost:8000/patients \
  -H 'Content-Type: application/json' \
  -d '{"full_name":"Иванов И.И.","birth_date":"1980-03-15","sex":"m"}'

# добавить наблюдение
curl -X POST http://localhost:8000/observations \
  -H 'Content-Type: application/json' \
  -d '{"patient_id":"...","code":"HBA1C","value_num":5.4,"unit":"%","ref_low":4.0,"ref_high":5.7,"observed_at":"2026-04-25T10:00:00+03:00"}'

# загрузить PDF
curl -X POST http://localhost:8000/files \
  -F patient_id=... -F file=@analyses.pdf -F description="Биохимия 25.04"
```

## Безопасность

Стек слушает `localhost`. Доступ только с твоей машины. Если хочешь открыть на телефон/жену в одной Wi-Fi сети — пробрось порты в роутере или используй [Tailscale](https://tailscale.com).

**Перед открытием наружу** — поменяй `MINIO_ROOT_PASSWORD` и `POSTGRES_PASSWORD` в `.env`.

## Дисклеймер

Это **не заменяет врача**. Это инструмент личной хронологии и чеклист для контроля. Все клинические решения принимает только лечащий врач.
