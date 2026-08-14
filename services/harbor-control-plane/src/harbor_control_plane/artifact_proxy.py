from pathlib import Path

from fastapi import HTTPException
from fastapi.responses import FileResponse


def serve_runner_local_artifact(*, storage_key: str, allowed_root: Path) -> FileResponse:
    root = allowed_root.expanduser().resolve()
    path = Path(storage_key).expanduser().resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise HTTPException(status_code=403, detail="Artifact path is not allowed") from exc
    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=404, detail="Artifact file not found")
    return FileResponse(path)
