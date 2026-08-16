import os
from pathlib import Path

from harbor_control_plane.app import create_app
from harbor_control_plane.artifact_resolver import CosArtifactResolver
from harbor_control_plane.config import ControlPlaneConfig, load_control_plane_config
from harbor_control_plane.db import create_schema, make_engine
from harbor_control_plane.publisher import (
    InMemoryJobPublisher,
    create_rocketmq_job_publisher,
)
from harbor_control_plane.sql_repository import SqlJobRepository

DEFAULT_CONFIG_PATH = Path("/config/control-plane.toml")


def _create_configured_app():
    config = _load_config()
    database_url = os.getenv("HARBOR_CONTROL_PLANE_DATABASE_URL")
    artifact_root_value = os.getenv("HARBOR_ARTIFACT_ALLOWED_ROOT")
    artifact_root = Path(artifact_root_value) if artifact_root_value else None
    artifact_resolver = _create_artifact_resolver(config)
    publisher = _create_publisher()
    if database_url is None:
        return create_app(
            publisher=publisher,
            artifact_allowed_root=artifact_root,
            artifact_resolver=artifact_resolver,
        )

    engine = make_engine(database_url)
    create_schema(engine)
    return create_app(
        repository=SqlJobRepository(engine),
        publisher=publisher,
        artifact_allowed_root=artifact_root,
        artifact_resolver=artifact_resolver,
    )


def _load_config() -> ControlPlaneConfig:
    config_path = os.getenv("HARBOR_CONTROL_PLANE_CONFIG")
    if config_path:
        return load_control_plane_config(Path(config_path))
    if DEFAULT_CONFIG_PATH.exists():
        return load_control_plane_config(DEFAULT_CONFIG_PATH)
    return ControlPlaneConfig()


def _create_artifact_resolver(config: ControlPlaneConfig):
    if config.artifact_storage.backend == "cos":
        return CosArtifactResolver(config=config.artifact_storage)
    return None


def _create_publisher():
    namesrv_addr = os.getenv("HARBOR_ROCKETMQ_NAMESRV")
    topic = os.getenv("HARBOR_ROCKETMQ_TOPIC")
    if not namesrv_addr and not topic:
        return InMemoryJobPublisher()
    if not namesrv_addr or not topic:
        raise RuntimeError(
            "HARBOR_ROCKETMQ_NAMESRV and HARBOR_ROCKETMQ_TOPIC must be set together"
        )
    return create_rocketmq_job_publisher(
        namesrv_addr=namesrv_addr,
        topic=topic,
        producer_group=os.getenv("HARBOR_ROCKETMQ_PRODUCER_GROUP", "harbor-api"),
    )


app = _create_configured_app()
