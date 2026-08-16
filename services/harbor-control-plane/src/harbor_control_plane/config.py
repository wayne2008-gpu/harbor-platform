import json
import tomllib
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field

from harbor_control_plane.artifact_resolver import ControlPlaneArtifactStorageConfig


class ControlPlaneConfig(BaseModel):
    artifact_storage: ControlPlaneArtifactStorageConfig = Field(
        default_factory=ControlPlaneArtifactStorageConfig
    )


def load_control_plane_config(path: Path) -> ControlPlaneConfig:
    try:
        text = path.read_text()
    except OSError as exc:
        raise ValueError(f"Failed to read control-plane config {path}: {exc}") from exc
    try:
        data = _parse_config_text(text, path.suffix.lower())
    except (json.JSONDecodeError, tomllib.TOMLDecodeError, yaml.YAMLError) as exc:
        raise ValueError(f"Failed to parse control-plane config {path}: {exc}") from exc
    return ControlPlaneConfig.model_validate(data or {})


def _parse_config_text(text: str, suffix: str) -> Any:
    if suffix == ".json":
        return json.loads(text)
    if suffix in {".yaml", ".yml"}:
        return yaml.safe_load(text)
    if suffix == ".toml":
        return tomllib.loads(text)
    raise ValueError(
        f"Unsupported control-plane config format {suffix!r}. "
        "Use .json, .yaml, .yml, or .toml."
    )
