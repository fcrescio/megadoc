from dataclasses import dataclass
from pathlib import Path
from tempfile import NamedTemporaryFile

import boto3
from botocore.client import Config

from common.config import Settings, get_settings


@dataclass
class StoredObject:
    bucket: str
    key: str


class StorageBackend:
    def put_file(self, source: Path, bucket: str, key: str, content_type: str) -> StoredObject:
        raise NotImplementedError

    def put_bytes(self, content: bytes, bucket: str, key: str, content_type: str) -> StoredObject:
        with NamedTemporaryFile(delete=False) as tmp:
            path = Path(tmp.name)
            path.write_bytes(content)
        try:
            return self.put_file(path, bucket=bucket, key=key, content_type=content_type)
        finally:
            path.unlink(missing_ok=True)

    def download_to_path(self, bucket: str, key: str, destination: Path) -> Path:
        raise NotImplementedError

    def read_bytes(self, bucket: str, key: str) -> bytes:
        raise NotImplementedError

    def exists(self, bucket: str, key: str) -> bool:
        raise NotImplementedError

    def healthcheck(self) -> bool:
        raise NotImplementedError


class S3StorageBackend(StorageBackend):
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._client = boto3.client(
            "s3",
            endpoint_url=settings.s3_endpoint_url,
            aws_access_key_id=settings.s3_access_key,
            aws_secret_access_key=settings.s3_secret_key,
            region_name=settings.s3_region,
            config=Config(signature_version="s3v4"),
        )

    def put_file(self, source: Path, bucket: str, key: str, content_type: str) -> StoredObject:
        self._client.upload_file(
            str(source),
            bucket,
            key,
            ExtraArgs={"ContentType": content_type},
        )
        return StoredObject(bucket=bucket, key=key)

    def download_to_path(self, bucket: str, key: str, destination: Path) -> Path:
        destination.parent.mkdir(parents=True, exist_ok=True)
        self._client.download_file(bucket, key, str(destination))
        return destination

    def read_bytes(self, bucket: str, key: str) -> bytes:
        response = self._client.get_object(Bucket=bucket, Key=key)
        try:
            return response["Body"].read()
        finally:
            response["Body"].close()

    def exists(self, bucket: str, key: str) -> bool:
        try:
            self._client.head_object(Bucket=bucket, Key=key)
            return True
        except Exception:
            return False

    def healthcheck(self) -> bool:
        self._client.list_buckets()
        return True


class LocalFilesystemStorageBackend(StorageBackend):
    def __init__(self, settings: Settings) -> None:
        self._root = settings.local_storage_path
        self._root.mkdir(parents=True, exist_ok=True)

    def _resolve(self, bucket: str, key: str) -> Path:
        return self._root / bucket / key

    def put_file(self, source: Path, bucket: str, key: str, content_type: str) -> StoredObject:
        destination = self._resolve(bucket, key)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(source.read_bytes())
        return StoredObject(bucket=bucket, key=key)

    def download_to_path(self, bucket: str, key: str, destination: Path) -> Path:
        source = self._resolve(bucket, key)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(source.read_bytes())
        return destination

    def read_bytes(self, bucket: str, key: str) -> bytes:
        return self._resolve(bucket, key).read_bytes()

    def exists(self, bucket: str, key: str) -> bool:
        return self._resolve(bucket, key).exists()

    def healthcheck(self) -> bool:
        self._root.mkdir(parents=True, exist_ok=True)
        return True


def get_storage_backend(settings: Settings | None = None) -> StorageBackend:
    app_settings = settings or get_settings()
    if app_settings.storage_backend == "filesystem":
        return LocalFilesystemStorageBackend(app_settings)
    return S3StorageBackend(app_settings)
