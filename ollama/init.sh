#!/bin/sh
# Ollama init: тянет модели после того, как сервер поднялся.
# Запускается sidecar-контейнером один раз.
#
# Профили под разное железо (подставь нужный в OLLAMA_PROFILE через .env):
#   lite    — 8–12 GB RAM/VRAM  (минимальный)
#   base    — 16 GB             (дефолт, рекомендуется)
#   heavy   — 24+ GB            (комфортно всё)
#
# Список моделей можно менять — скрипт идемпотентен, при повторном запуске
# уже скачанные модели пропускаются.

set -eu

PROFILE="${OLLAMA_PROFILE:-base}"
echo "→ Профиль: $PROFILE"

case "$PROFILE" in
  lite)
    MODELS="saiga-llama3:8b-instruct-q4_K_M medgemma:4b-it-q4_K_M nomic-embed-text:latest"
    ;;
  base)
    MODELS="qwen2.5:14b-instruct-q4_K_M medgemma:4b-it-q4_K_M bge-m3:latest"
    ;;
  heavy)
    MODELS="qwen2.5:32b-instruct-q4_K_M medgemma:27b-it-q4_K_M bge-m3:latest"
    ;;
  *)
    echo "❌ Неизвестный профиль: $PROFILE"; exit 1
    ;;
esac

echo "→ Ожидание готовности Ollama…"
for i in $(seq 1 60); do
  if ollama list >/dev/null 2>&1; then
    break
  fi
  sleep 2
done

for m in $MODELS; do
  if ollama list | awk '{print $1}' | grep -q "^${m%:*}:"; then
    echo "→ Уже есть: $m — пропускаю"
    continue
  fi
  echo "→ Тяну: $m"
  ollama pull "$m" || echo "⚠  Не удалось скачать $m — продолжаю"
done

echo "✓ Ollama инициализирована. Доступные модели:"
ollama list
