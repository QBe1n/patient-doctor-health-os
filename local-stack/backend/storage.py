"""MinIO client wrapper."""
import os
from minio import Minio

_client = None


def client() -> Minio:
    global _client
    if _client is None:
        _client = Minio(
            os.environ["MINIO_ENDPOINT"],
            access_key=os.environ["MINIO_ACCESS_KEY"],
            secret_key=os.environ["MINIO_SECRET_KEY"],
            secure=os.environ.get("MINIO_SECURE", "false").lower() == "true",
        )
    return _client


def bucket() -> str:
    return os.environ.get("MINIO_BUCKET", "health-files")


def ensure_bucket() -> None:
    c = client()
    if not c.bucket_exists(bucket()):
        c.make_bucket(bucket())


def upload(stream, length: int, key: str, content_type: str) -> None:
    ensure_bucket()
    client().put_object(bucket(), key, stream, length=length, content_type=content_type)


def presigned_get(key: str, expires_seconds: int = 3600) -> str:
    from datetime import timedelta
    return client().presigned_get_object(bucket(), key, expires=timedelta(seconds=expires_seconds))
