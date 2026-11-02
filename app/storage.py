"""Ciphertext-only storage adapters: local filesystem for development, S3 for cloud."""
from pathlib import Path
import re
import time
import boto3
from botocore.exceptions import ClientError
from botocore.config import Config
from .config import settings

_client = None
_KEY_RE = re.compile(r"^[0-9a-f-]{36}/[0-9]{8}\.bin$")

def _check_key(key: str) -> None:
    if not _KEY_RE.fullmatch(key):
        raise ValueError("Invalid generated storage key")

def init_storage():
    global _client
    if settings.storage_backend == "local":
        Path(settings.storage_root).mkdir(parents=True, exist_ok=True)
        return
    if settings.storage_backend != "s3":
        raise RuntimeError("STORAGE_BACKEND must be 'local' or 's3'")
    kwargs = {"endpoint_url": settings.s3_endpoint_url or None, "region_name": settings.s3_region}
    if settings.s3_access_key or settings.s3_secret_key:
        if not settings.s3_access_key or not settings.s3_secret_key:
            raise RuntimeError("Both S3_ACCESS_KEY and S3_SECRET_KEY must be set together")
        kwargs.update(aws_access_key_id=settings.s3_access_key, aws_secret_access_key=settings.s3_secret_key)
    elif settings.s3_endpoint_url:
        raise RuntimeError("Explicit S3 credentials are required for a custom S3 endpoint")
    # On AWS, boto3 uses the workload's short-lived IAM task-role credentials.
    # Railway Buckets require virtual-hosted-style URLs; this also works with AWS S3.
    _client = boto3.client("s3", config=Config(s3={"addressing_style": "virtual"}), **kwargs)
    last_error = None
    for attempt in range(30):
        try:
            _client.head_bucket(Bucket=settings.s3_bucket)
            return
        except ClientError as exc:
            code = str(exc.response.get("Error", {}).get("Code", ""))
            if code in {"404", "NoSuchBucket", "NotFound"}:
                if settings.s3_endpoint_url:
                    _client.create_bucket(Bucket=settings.s3_bucket)
                    return
                raise RuntimeError("The configured private S3 bucket does not exist") from exc
            last_error = exc
        except Exception as exc:
            last_error = exc
        time.sleep(min(2, 0.25 + attempt * 0.1))
    raise RuntimeError("Object storage is unavailable after startup retries") from last_error

def put_object(key: str, data: bytes):
    _check_key(key)
    if settings.storage_backend == "s3":
        _client.put_object(Bucket=settings.s3_bucket, Key=key, Body=data)
    else:
        path = Path(settings.storage_root) / key
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "xb") as f: f.write(data)

def get_object(key: str) -> bytes:
    _check_key(key)
    if settings.storage_backend == "s3":
        return _client.get_object(Bucket=settings.s3_bucket, Key=key)["Body"].read()
    return (Path(settings.storage_root) / key).read_bytes()

def delete_object(key: str):
    _check_key(key)
    if settings.storage_backend == "s3":
        _client.delete_object(Bucket=settings.s3_bucket, Key=key)
    else:
        (Path(settings.storage_root) / key).unlink(missing_ok=True)
