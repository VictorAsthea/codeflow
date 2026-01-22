from datetime import datetime
from enum import Enum
from pydantic import BaseModel, Field


class TaskStatus(str, Enum):
    BACKLOG = "backlog"
    IN_PROGRESS = "in_progress"
    AI_REVIEW = "ai_review"
    HUMAN_REVIEW = "human_review"
    DONE = "done"


class PhaseStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"


class PhaseConfig(BaseModel):
    model: str = "claude-sonnet-4-20250514"
    intensity: str = "medium"
    max_turns: int = 10


class Phase(BaseModel):
    name: str
    status: PhaseStatus = PhaseStatus.PENDING
    config: PhaseConfig
    logs: list[str] = Field(default_factory=list)
    started_at: datetime | None = None
    completed_at: datetime | None = None


class Task(BaseModel):
    id: str
    title: str
    description: str
    status: TaskStatus = TaskStatus.BACKLOG
    phases: dict[str, Phase]
    worktree_path: str | None = None
    branch_name: str | None = None
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)


class GlobalConfig(BaseModel):
    default_model: str = "claude-sonnet-4-20250514"
    default_intensity: str = "medium"
    project_path: str
    auto_review: bool = True


class TaskCreate(BaseModel):
    title: str
    description: str


class TaskUpdate(BaseModel):
    title: str | None = None
    description: str | None = None
    status: TaskStatus | None = None


class PhaseConfigUpdate(BaseModel):
    model: str | None = None
    intensity: str | None = None
    max_turns: int | None = None
