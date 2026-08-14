from datetime import datetime, timezone

from pydantic import BaseModel, Field


class JobDispatchRouting(BaseModel):
    provider: str | None = None
    tags: list[str] = Field(default_factory=list)


class JobDispatchMessage(BaseModel):
    schema_version: int = 1
    message_id: str
    job_id: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    routing: JobDispatchRouting = Field(default_factory=JobDispatchRouting)
