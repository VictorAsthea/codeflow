from datetime import datetime
from enum import Enum
from typing import Dict, Any, List
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
    pr_url: str | None = None
    skip_ai_review: bool = False
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)


class GlobalConfig(BaseModel):
    default_model: str = "claude-sonnet-4-20250514"
    default_intensity: str = "medium"
    project_path: str
    auto_review: bool = True


class TaskCreate(BaseModel):
    title: str | None = None
    description: str
    skip_ai_review: bool = False
    agent_profile: str = "balanced"
    phase_config: Dict[str, PhaseConfigUpdate] | None = None
    require_human_review_before_coding: bool = False
    git_options: Dict[str, str] | None = None
    file_references: List[str] = Field(default_factory=list)
    screenshots: List[str] = Field(default_factory=list)


class TaskUpdate(BaseModel):
    title: str | None = None
    description: str | None = None
    status: TaskStatus | None = None
    skip_ai_review: bool | None = None


class PhaseConfigUpdate(BaseModel):
    model: str | None = None
    intensity: str | None = None
    max_turns: int | None = None
