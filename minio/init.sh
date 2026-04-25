#!/bin/sh
# MinIO init: создаёт бакеты, включает версионирование,
# применяет lifecycle-политики. Запускается один раз sidecar-контейнером.
set -eu

MINIO_USER=$(cat /run/secrets/minio_user)
MINIO_PASSWORD=$(cat /run/secrets/minio_password)

echo "→ Ожидание готовности MinIO…"
for i in $(seq 1 30); do
  if mc alias set local http://minio:9000 "$MINIO_USER" "$MINIO_PASSWORD" >/dev/null 2>&1; then
    echo "→ MinIO готов."
    break
  fi
  sleep 2
done

create_bucket() {
  local name="$1"
  local versioning="${2:-off}"
  if ! mc ls local/"$name" >/dev/null 2>&1; then
    echo "→ Создаю бакет: $name"
    mc mb local/"$name"
  else
    echo "→ Бакет уже существует: $name"
  fi
  if [ "$versioning" = "on" ]; then
    mc version enable local/"$name" >/dev/null
    echo "  ✓ versioning=on"
  fi
  # Закрываем анонимный доступ наглухо.
  mc anonymous set none local/"$name" >/dev/null
}

# Сырые письма от лабораторий (целиком .eml) — для аудит-трейла
create_bucket raw-emails       on
# Вложения писем (PDF/XML) — с версионированием: исправленные отчёты
create_bucket raw-attachments  on
# Прочие PHI-документы (СЭМД, экспорты ЕМИАС)
create_bucket documents        on
# Артефакты пайплайна (нормализованные JSON, промпты и ответы LLM)
create_bucket pipeline         off
# Будущее: DICOM-снимки
create_bucket imaging          on

# Lifecycle: письма старше 3 лет переводим в cold (tier) — на будущее, когда добавим NAS.
# Сейчас просто включаем ILM с тэгом и оставляем локально.
cat > /tmp/ilm-retention.json <<'EOF'
{
  "Rules": [
    {
      "ID": "retain-raw-3-years",
      "Status": "Enabled",
      "Expiration": { "Days": 1095 },
      "Filter": { "Prefix": "" }
    }
  ]
}
EOF
# Не применяем автоматически — это нужно явно включать когда подтвердишь политику.
# mc ilm import local/raw-emails < /tmp/ilm-retention.json

echo "✓ MinIO инициализирован."
