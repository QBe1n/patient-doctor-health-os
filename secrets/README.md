# Секреты

Docker Compose подхватывает файлы из этой папки как Docker secrets. Каждый файл — одна строка без переноса в конце.

## Генерация при первом запуске

```bash
cd secrets
# Пользователь БД
echo -n "healthos" > pg_user
# Сильный пароль для Postgres
openssl rand -base64 32 | tr -d '\n' > pg_password
# MinIO admin
echo -n "minioadmin" > minio_user
openssl rand -base64 32 | tr -d '\n' > minio_password
chmod 600 pg_password minio_password
```

## Что НЕ делать

- Не коммить содержимое файлов в git. `.gitignore` уже закрывает всё, кроме `README.md`.
- Не использовать одинаковые пароли для pg_password и minio_password.
- Для продакшн-сетапа (второй пациент и/или врач) — переезжай на [SOPS](https://github.com/getsops/sops) + age и храни зашифрованные файлы в репозитории. Расшифровка — через систему ключей (YubiKey, age-keygen).

## Ротация

Меняешь файл → `docker compose up -d --force-recreate postgres minio` (только нужный сервис). HAPI-коннекция к Postgres подхватит новый пароль через env только после рестарта HAPI.
