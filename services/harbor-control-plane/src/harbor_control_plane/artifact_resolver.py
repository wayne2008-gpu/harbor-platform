import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Protocol

from fastapi import HTTPException
from fastapi.responses import (
    FileResponse,
    RedirectResponse,
    Response,
    StreamingResponse,
)
from harbor_service_contracts import ArtifactDownloadUrlResponse, ArtifactResponse
from pydantic import BaseModel, Field, model_validator


class ArtifactResolver(Protocol):
    def content_response(self, artifact: ArtifactResponse) -> Response: ...

    def download_url(
        self, artifact: ArtifactResponse
    ) -> ArtifactDownloadUrlResponse: ...

    def read_bytes(self, artifact: ArtifactResponse) -> bytes: ...


class CosClient(Protocol):
    def get_presigned_download_url(
        self, *, bucket: str, key: str, expires: int
    ) -> str: ...

    def get_object_bytes(self, *, bucket: str, key: str) -> bytes: ...


class CosArtifactStorageConfig(BaseModel):
    bucket: str
    region: str
    prefix: str = ""
    secret_id: str
    secret_key: str
    session_token: str | None = None
    endpoint: str | None = None


class ControlPlaneArtifactStorageConfig(BaseModel):
    backend: Literal["runner-local", "cos"] = "runner-local"
    download_mode: Literal["signed-url", "proxy"] = "signed-url"
    signed_url_ttl_sec: int = Field(default=600, ge=1)
    cos: CosArtifactStorageConfig | None = None

    @model_validator(mode="after")
    def validate_backend_config(self):
        if self.backend == "cos" and self.cos is None:
            raise ValueError("artifact_storage.cos is required when backend = 'cos'")
        return self


class RunnerLocalArtifactResolver:
    def __init__(self, *, allowed_root: Path) -> None:
        self.allowed_root = allowed_root

    def content_response(self, artifact: ArtifactResponse) -> FileResponse:
        if artifact.storage_type != "runner-local":
            raise HTTPException(status_code=400, detail="Artifact is not runner-local")
        return _serve_runner_local_artifact(
            storage_key=artifact.storage_key,
            allowed_root=self.allowed_root,
        )

    def download_url(self, artifact: ArtifactResponse) -> ArtifactDownloadUrlResponse:
        if artifact.storage_type != "runner-local":
            raise HTTPException(status_code=400, detail="Artifact is not runner-local")
        raise HTTPException(
            status_code=400,
            detail="runner-local artifacts do not support signed download URLs",
        )

    def read_bytes(self, artifact: ArtifactResponse) -> bytes:
        if artifact.storage_type != "runner-local":
            raise HTTPException(status_code=400, detail="Artifact is not runner-local")
        path = _resolve_runner_local_path(
            storage_key=artifact.storage_key,
            allowed_root=self.allowed_root,
        )
        try:
            return path.read_bytes()
        except OSError as exc:
            raise HTTPException(
                status_code=404, detail="Artifact file not found"
            ) from exc


@dataclass(frozen=True)
class CosObjectRef:
    bucket: str
    key: str


class CosArtifactResolver:
    def __init__(
        self,
        *,
        config: ControlPlaneArtifactStorageConfig,
        client: CosClient | None = None,
    ) -> None:
        if config.backend != "cos" or config.cos is None:
            raise ValueError("COS artifact resolver requires COS config")
        self.config = config
        self.cos = config.cos
        self.client = client or QcloudCosClient(self.cos)

    def content_response(self, artifact: ArtifactResponse) -> Response:
        if self.config.download_mode == "signed-url":
            url = self.download_url(artifact).url
            return RedirectResponse(url)
        content = self.read_bytes(artifact)
        media_type = artifact.content_type or "application/octet-stream"
        return StreamingResponse(iter([content]), media_type=media_type)

    def download_url(self, artifact: ArtifactResponse) -> ArtifactDownloadUrlResponse:
        ref = self._object_ref(artifact)
        url = self.client.get_presigned_download_url(
            bucket=ref.bucket,
            key=ref.key,
            expires=self.config.signed_url_ttl_sec,
        )
        return ArtifactDownloadUrlResponse(
            url=url,
            expires_in=self.config.signed_url_ttl_sec,
        )

    def read_bytes(self, artifact: ArtifactResponse) -> bytes:
        ref = self._object_ref(artifact)
        return self.client.get_object_bytes(bucket=ref.bucket, key=ref.key)

    def _object_ref(self, artifact: ArtifactResponse) -> CosObjectRef:
        if artifact.storage_type != "cos":
            raise HTTPException(status_code=400, detail="Artifact is not stored in COS")
        ref = parse_cos_uri(artifact.storage_key)
        if ref.bucket != self.cos.bucket:
            raise HTTPException(status_code=403, detail="COS bucket is not allowed")
        prefix = self.cos.prefix.strip("/")
        if prefix and not ref.key.startswith(prefix + "/"):
            raise HTTPException(status_code=403, detail="COS key is not allowed")
        return ref


class QcloudCosClient:
    def __init__(self, config: CosArtifactStorageConfig) -> None:
        try:
            from qcloud_cos import CosConfig, CosS3Client
        except ImportError as exc:
            raise RuntimeError(
                "cos-python-sdk-v5 is required for COS artifacts"
            ) from exc

        kwargs = {
            "Region": config.region,
            "SecretId": config.secret_id,
            "SecretKey": config.secret_key,
            "Scheme": "https",
        }
        if config.session_token:
            kwargs["Token"] = config.session_token
        if config.endpoint:
            kwargs["Endpoint"] = config.endpoint
        cos_config = CosConfig(**kwargs)
        self._client = CosS3Client(cos_config)

    def get_presigned_download_url(self, *, bucket: str, key: str, expires: int) -> str:
        return str(
            self._client.get_presigned_url(
                Method="GET",
                Bucket=bucket,
                Key=key,
                Expired=expires,
            )
        )

    def get_object_bytes(self, *, bucket: str, key: str) -> bytes:
        response = self._client.get_object(Bucket=bucket, Key=key)
        body = response["Body"]
        raw_stream = getattr(body, "get_raw_stream", None)
        if raw_stream is not None:
            return raw_stream().read()
        return body.read()


def parse_cos_uri(uri: str) -> CosObjectRef:
    prefix = "cos://"
    if not uri.startswith(prefix):
        raise HTTPException(status_code=400, detail="Invalid COS artifact URI")
    bucket, separator, key = uri[len(prefix) :].partition("/")
    if not bucket or not separator or not key:
        raise HTTPException(status_code=400, detail="Invalid COS artifact URI")
    return CosObjectRef(bucket=bucket, key=key)


def read_artifact_json(
    *,
    resolver: ArtifactResolver,
    artifact: ArtifactResponse,
) -> Any:
    try:
        return json.loads(resolver.read_bytes(artifact).decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=500, detail="Artifact is not valid JSON"
        ) from exc


def _serve_runner_local_artifact(
    *,
    storage_key: str,
    allowed_root: Path,
) -> FileResponse:
    path = _resolve_runner_local_path(
        storage_key=storage_key,
        allowed_root=allowed_root,
    )
    return FileResponse(path)


def _resolve_runner_local_path(*, storage_key: str, allowed_root: Path) -> Path:
    root = allowed_root.expanduser().resolve()
    path = Path(storage_key).expanduser().resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise HTTPException(
            status_code=403, detail="Artifact path is not allowed"
        ) from exc
    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=404, detail="Artifact file not found")
    return path
