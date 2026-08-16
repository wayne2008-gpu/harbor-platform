from pathlib import Path

import pytest
from pydantic import ValidationError

from harbor_control_plane.config import load_control_plane_config


def test_load_control_plane_config_reads_cos_toml(tmp_path: Path) -> None:
    config_path = tmp_path / "control-plane.toml"
    config_path.write_text(
        """
[artifact_storage]
backend = "cos"
download_mode = "signed-url"
signed_url_ttl_sec = 300

[artifact_storage.cos]
bucket = "harbor-artifacts-1250000000"
region = "ap-guangzhou"
prefix = "dev"
secret_id = "sid"
secret_key = "skey"
""".lstrip()
    )

    config = load_control_plane_config(config_path)

    assert config.artifact_storage.backend == "cos"
    assert config.artifact_storage.signed_url_ttl_sec == 300
    assert config.artifact_storage.cos is not None
    assert config.artifact_storage.cos.secret_id == "sid"


def test_load_control_plane_config_requires_cos_section_for_cos_backend(
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "control-plane.toml"
    config_path.write_text('[artifact_storage]\nbackend = "cos"\n')

    with pytest.raises(ValidationError):
        load_control_plane_config(config_path)
