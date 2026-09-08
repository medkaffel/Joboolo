"""PREP-01 — hermetic contract tests for S3-compatible object storage."""

import importlib
import sys
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

_REQUIRED = {
    "S3_ENDPOINT_URL": "https://account.example.invalid",
    "S3_ACCESS_KEY_ID": "test-access-key",
    "S3_SECRET_ACCESS_KEY": "test-secret-key",
    "S3_BUCKET_NAME": "joboolo-preprod-private",
    "S3_REGION": "auto",
}


class _Body:
    def __init__(self, data: bytes):
        self._data = data
        self.closed = False

    def read(self):
        return self._data

    def close(self):
        self.closed = True


class _FakeS3:
    def __init__(self):
        self.put_calls = []
        self.get_calls = []
        self.get_response = {
            "Body": _Body(b"stored-content"),
            "ContentType": "application/pdf",
        }

    def put_object(self, **kwargs):
        self.put_calls.append(kwargs)
        return {"ETag": "test"}

    def get_object(self, **kwargs):
        self.get_calls.append(kwargs)
        return self.get_response


@pytest.fixture
def storage_module(monkeypatch):
    for name in _REQUIRED:
        monkeypatch.delenv(name, raising=False)

    sys.modules.pop("storage", None)
    storage = importlib.import_module("storage")
    storage._s3_client = None
    storage._bucket_name = None
    return storage


def _configure(monkeypatch):
    for name, value in _REQUIRED.items():
        monkeypatch.setenv(name, value)


def test_init_storage_requires_configuration_without_exposing_secret(storage_module, monkeypatch):
    monkeypatch.setenv("S3_SECRET_ACCESS_KEY", "do-not-leak-this-secret")

    with pytest.raises(RuntimeError) as exc:
        storage_module.init_storage()

    message = str(exc.value)
    assert "S3_ENDPOINT_URL" in message
    assert "do-not-leak-this-secret" not in message


def test_init_storage_builds_and_caches_s3_client(storage_module, monkeypatch):
    _configure(monkeypatch)
    fake = _FakeS3()
    calls = []

    def fake_client(service_name, **kwargs):
        calls.append((service_name, kwargs))
        return fake

    monkeypatch.setattr(storage_module.boto3, "client", fake_client)

    first = storage_module.init_storage()
    second = storage_module.init_storage()

    assert first is fake
    assert second is fake
    assert calls == [
        (
            "s3",
            {
                "endpoint_url": "https://account.example.invalid",
                "aws_access_key_id": "test-access-key",
                "aws_secret_access_key": "test-secret-key",
                "region_name": "auto",
            },
        )
    ]
    assert storage_module._bucket_name == "joboolo-preprod-private"


def test_put_object_preserves_path_body_content_type_and_size(storage_module, monkeypatch):
    _configure(monkeypatch)
    fake = _FakeS3()
    monkeypatch.setattr(storage_module.boto3, "client", lambda *args, **kwargs: fake)

    path = "joboolo/candidates/user-1/cv/document.pdf"
    data = b"%PDF-test"
    result = storage_module.put_object(path, data, "application/pdf")

    assert result == {"path": path, "size": len(data)}
    assert fake.put_calls == [
        {
            "Bucket": "joboolo-preprod-private",
            "Key": path,
            "Body": data,
            "ContentType": "application/pdf",
        }
    ]


def test_get_object_returns_bytes_content_type_and_closes_body(storage_module, monkeypatch):
    _configure(monkeypatch)
    fake = _FakeS3()
    body = fake.get_response["Body"]
    monkeypatch.setattr(storage_module.boto3, "client", lambda *args, **kwargs: fake)

    content, content_type = storage_module.get_object("joboolo/uploads/user-1/cv.pdf")

    assert content == b"stored-content"
    assert content_type == "application/pdf"
    assert body.closed is True
    assert fake.get_calls == [
        {
            "Bucket": "joboolo-preprod-private",
            "Key": "joboolo/uploads/user-1/cv.pdf",
        }
    ]


def test_get_object_content_type_falls_back_to_octet_stream(storage_module, monkeypatch):
    _configure(monkeypatch)
    fake = _FakeS3()
    fake.get_response = {"Body": _Body(b"raw")}
    monkeypatch.setattr(storage_module.boto3, "client", lambda *args, **kwargs: fake)

    content, content_type = storage_module.get_object("joboolo/uploads/user-1/raw.bin")

    assert content == b"raw"
    assert content_type == "application/octet-stream"
