"""S3-compatible object storage facade for Joboolo.

PREP-01 keeps the historical public contract used by routes/files.py while
removing the Emergent object-storage dependency. Cloudflare R2 is S3-compatible,
so the same implementation can also target another S3-compatible provider.
"""

import os

import boto3

APP_NAME = "joboolo"

_s3_client = None
_bucket_name = None


def _required_env(name: str) -> str:
    """Return a required storage setting without ever exposing its value."""
    value = os.environ.get(name)
    if value is None or not value.strip():
        raise RuntimeError(f"{name} manquante pour le stockage objet")
    return value.strip()


def init_storage():
    """Initialize and cache the S3-compatible client.

    Client construction is intentionally side-effect free: connectivity is
    proven by the first object operation, while startup still validates that
    every required storage variable is present.
    """
    global _s3_client, _bucket_name

    if _s3_client is not None:
        return _s3_client

    endpoint_url = _required_env("S3_ENDPOINT_URL").rstrip("/")
    access_key_id = _required_env("S3_ACCESS_KEY_ID")
    secret_access_key = _required_env("S3_SECRET_ACCESS_KEY")
    bucket_name = _required_env("S3_BUCKET_NAME")
    region = (os.environ.get("S3_REGION") or "auto").strip() or "auto"

    _s3_client = boto3.client(
        "s3",
        endpoint_url=endpoint_url,
        aws_access_key_id=access_key_id,
        aws_secret_access_key=secret_access_key,
        region_name=region,
    )
    _bucket_name = bucket_name
    return _s3_client


def put_object(path: str, data: bytes, content_type: str) -> dict:
    """Store bytes at the exact historical storage path."""
    client = init_storage()
    client.put_object(
        Bucket=_bucket_name,
        Key=path,
        Body=data,
        ContentType=content_type,
    )
    return {"path": path, "size": len(data)}


def get_object(path: str):
    """Return stored bytes and their content type."""
    client = init_storage()
    response = client.get_object(Bucket=_bucket_name, Key=path)
    body = response["Body"]
    try:
        content = body.read()
    finally:
        close = getattr(body, "close", None)
        if close:
            close()
    return content, response.get("ContentType") or "application/octet-stream"
