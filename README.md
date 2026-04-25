# Patient & Doctor Health OS

Локальный self-hosted фундамент для personal Health OS под РФ-рынок: HAPI FHIR R5, Postgres с pgvector, MinIO и Ollama. Всё локально, всё open-source, всё на loopback — наружу ничего не торчит.

Это база под ingest-агента лабораторных анализов (Инвитро/Гемотест/KDL/...) и последующие агенты подготовки визита, алертов, постобработки.

> ⚠️ **Дисклеймер.** Проект не является медицинским изделием и не заменяет врача. Используется как личный инструмент агрегации данных и подготовки к визитам. Все клинические решения — только профильный специалист.

## Документация

- [docs/health-os-plan-rf.md](docs/health-os-plan-rf.md) — основной план под РФ-рынок (ЕМИАС, 152-ФЗ, локальные лабы).
- [docs/ingest-agent-architecture.md](docs/ingest-agent-architecture.md) — архитектура ingest-агента (9 модулей, парсинг PDF, маппинг LOINC, запись в HAPI FHIR).
- [docs/health-os-plan.md](docs/health-os-plan.md) — исходная (UAE) версия плана.

---

## Что внутри

| Сервис | Порт (127.0.0.1) | Назначение |
|---|---|---|
| HAPI FHIR | 8080 | Медицинское ядро: Patient, Observation, DiagnosticReport, ... |
| Postgres 16 + pgvector | 5432 | Бэкенд HAPI + БД `ingest` с таблицами состояния и LOINC-словарём |
| MinIO | 9000 (API), 9001 (UI) | Object storage: сырые .eml, PDF-вложения, будущие DICOM |
| Ollama | 11434 | Локальный LLM-рантайм (Qwen 2.5 / MedGemma / BGE-M3) |

## Требования

- Docker 24+ и Docker Compose v2 (`docker compose`, без дефиса).
- Минимум **16 ГБ RAM** и **40 ГБ свободного диска** на первый запуск (модели Ollama ≈ 15 ГБ).
- Профиль `lite` в `.env` — если меньше памяти.
- Linux/macOS. На Windows — через WSL2.
- На Mac с Apple Silicon: Docker CPU ок, но Ollama быстрее работает нативно (бинарь + `OLLAMA_HOST=0.0.0.0:11434`). См. раздел «Mac/GPU» ниже.

## Быстрый старт

```bash
cd health-os
cp .env.example .env          # и при желании меняем OLLAMA_PROFILE
make up                       # создаст секреты и поднимет стек
make wait                     # ждём пока всё стартует (первый раз 15–30 мин — тянутся модели)
make smoke                    # пишет тестового Patient и читает обратно
```

**Что произойдёт на `make up`:**

1. Создадутся файлы в `./secrets/` со случайными паролями.
2. Docker поднимет Postgres, применит SQL из `postgres/init/` — создаст БД `hapi` и `ingest`, включит pgvector/pgcrypto, зальёт 30 LOINC-синонимов на русском и 3 критических порога.
3. HAPI FHIR стартует, мигрирует схему в `hapi`, поднимает REST на `:8080/fhir`.
4. MinIO стартует, sidecar `minio-init` создаст бакеты: `raw-emails`, `raw-attachments`, `documents`, `pipeline`, `imaging`.
5. Ollama стартует, sidecar `ollama-init` скачает модели по выбранному профилю.

## Проверка вручную

```bash
# HAPI — capability statement
curl -s http://localhost:8080/fhir/metadata | jq '.software'

# Postgres — pgvector и словарь
docker compose exec postgres psql -U healthos -d ingest -c \
  "select extname from pg_extension; select count(*) from loinc_ru_synonyms;"

# MinIO — список бакетов (через консоль)
open http://localhost:9001
# Логин и пароль — из secrets/minio_user и secrets/minio_password

# Ollama — какие модели подтянулись
curl -s http://localhost:11434/api/tags | jq '.models[].name'

# Пробный запрос к LLM
curl -s http://localhost:11434/api/generate -d '{
  "model": "qwen2.5:14b-instruct-q4_K_M",
  "prompt": "Ответь по-русски: что измеряет HbA1c?",
  "stream": false
}' | jq -r '.response'
```

## Структура проекта

```
health-os/
├── docker-compose.yml              главный compose
├── Makefile                        команды для работы со стеком
├── .env.example                    дефолты (версии образов, профиль моделей)
├── .gitignore
├── hapi/
│   └── application.yaml            конфиг HAPI (R5, PG, CORS, валидация)
├── postgres/
│   └── init/
│       └── 00-extensions-and-dbs.sql   создание БД hapi/ingest, расширения, seed
├── minio/
│   └── init.sh                     создание бакетов и политик
├── ollama/
│   └── init.sh                     pull моделей по профилю
└── secrets/
    └── README.md                   как генерировать/ротировать пароли
```

## Профили Ollama

Выбираются через `OLLAMA_PROFILE` в `.env`. Скрипт идемпотентен — можно переключать на ходу и делать `make ollama-pull`.

| Профиль | RAM/VRAM | Модели |
|---|---|---|
| `lite` | 8–12 ГБ | Saiga-Llama3 8B + MedGemma 4B + nomic-embed-text |
| `base` | 16 ГБ | Qwen 2.5 14B + MedGemma 4B + BGE-M3 (рекомендуется) |
| `heavy` | 24+ ГБ | Qwen 2.5 32B + MedGemma 27B + BGE-M3 |

Эмбеддинг-модель (BGE-M3 или nomic) используется ingest-агентом для семантического поиска LOINC по русским названиям показателей. Размерность колонки `loinc_embeddings.embedding` в БД — **1024** (подходит для BGE-M3 и multilingual-e5-large). Для nomic (768) колонку нужно пересоздать на `vector(768)`.

## Mac с Apple Silicon и GPU

Docker Desktop на Mac запускает контейнеры под Linux/VM — Ollama там не видит Metal и работает на CPU (медленно). Два варианта:

**Вариант A (рекомендуется на Mac).** Ollama ставится нативно, остальное — в Docker. В `docker-compose.yml` закомментировать сервисы `ollama` и `ollama-init`, и на хосте сделать:

```bash
brew install ollama
brew services start ollama
OLLAMA_HOST=http://host.docker.internal:11434   # для ingest-агента в контейнере
```

**Вариант B (Linux с NVIDIA GPU).** В `docker-compose.yml` раскомментировать блок `deploy.resources.reservations.devices` в сервисе `ollama`. Установить [nvidia-container-toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/). После этого `docker compose up -d ollama` подхватит CUDA.

## Безопасность: что здесь уже сделано

- Все порты на `127.0.0.1` — снаружи машины ничего не видно.
- Postgres и MinIO — через Docker secrets (файлы в `./secrets/`), не через env в open text.
- HAPI CORS — только loopback и приватные подсети (10.x, Tailscale 100.x).
- HAPI anonymous access: разрешён локально. Для продакшна (второй пациент) нужно включить auth — см. раздел «Что НЕ сделано».
- MinIO anonymous access — закрыт (`mc anonymous set none`).

## Что НЕ сделано (сознательно, для MVP)

1. **Аутентификация HAPI.** Сейчас кто угодно в LAN может писать в FHIR. Ок для single-user на домашней машине. Для второго пациента/врача — добавляем Keycloak/Authentik сбоку и интерсептор SMART-on-FHIR.
2. **TLS.** Внутри compose — plain HTTP. Для доступа с телефона — ставим поверх Tailscale (он сам шифрует) или [Caddy](https://caddyserver.com) с self-signed cert.
3. **Бэкапы.** Компоуз только поднимает сервисы. Бэкапы volumes (`postgres_data`, `minio_data`) — отдельной ролью через [restic](https://restic.net) или снапшоты ZFS/Btrfs. Пример скрипта добавим на следующем этапе.
4. **Внешний доступ.** Ничего наружу. Когда нужно пуш-уведомления в Telegram — поднимаем Cloudflared tunnel только для ingress webhook'а, не для самого HAPI.
5. **LOINC-полный справочник.** В `loinc_ru_synonyms` — только 30 популярных показателей. Полный LOINC (100k+ записей) и индекс эмбеддингов для `loinc_embeddings` грузится отдельным скриптом из ingest-агента на Дне 3 MVP.
6. **Русский ValueSet для валидации.** HAPI валидирует на встроенных. Свой ValueSet с `concept.designation[ru]` — на v2.
7. **Ingest-worker.** Это следующий слой — отдельный Python-сервис, описан в `ingest_agent_architecture.md`. Его docker-compose кусок добавим, когда напишем код.

## Полезные команды

```bash
make ps            # статус всех сервисов
make logs          # логи всех сервисов
make psql-ingest   # psql shell в ingest БД
make psql-hapi     # psql shell в hapi БД (бэкенд HAPI)
make smoke         # проверка работоспособности
make down          # остановить без удаления данных
make nuke          # ВНИМАНИЕ: удалить всё включая volumes
```

## Дальше

- [ ] Написать ingest-worker (Python) по спецификации в `ingest_agent_architecture.md`.
- [ ] Загрузить полный LOINC и построить эмбеддинг-индекс (отдельный скрипт `scripts/load_loinc.py`).
- [ ] Реализовать первый lab profile (Инвитро) на реальных PDF.
- [ ] Прикрутить бэкапы (restic в Selectel/Timeweb S3 или локальный NAS).
- [ ] Вторая машина (Tailscale) → доступ к Notion/Telegram-боту из офиса.
