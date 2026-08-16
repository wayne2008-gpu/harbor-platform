from pathlib import Path

from fastapi.responses import FileResponse

from harbor_control_plane.artifact_resolver import _serve_runner_local_artifact


def serve_runner_local_artifact(
    *,
    storage_key: str,
    allowed_root: Path,
) -> FileResponse:
    return _serve_runner_local_artifact(
        storage_key=storage_key,
        allowed_root=allowed_root,
    )
