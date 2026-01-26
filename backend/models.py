from datetime import datetime
from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field


class TaskStatus(str, Enum):
    BACKLOG = "backlog"
    QUEUED = "queued"
    IN_PROGRESS = "in_progress"
    AI_REVIEW = "ai_review"
    HUMAN_REVIEW = "human_review"
    DONE = "done"


class PhaseStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    IN_PROGRESS = "in_progress"  # Alias for running
    DONE = "done"
    COMPLETED = "completed"  # Alias for done
    FAILED = "failed"


class SubtaskStatus(str, Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"


class Subtask(BaseModel):
    id: str  # "subtask-1", "subtask-2", etc.
    title: str
    description: str | None = None
    status: SubtaskStatus = SubtaskStatus.PENDING
    order: int  # For sorting
    dependencies: list[str] = Field(default_factory=list)  # IDs of dependent subtasks
    started_at: datetime | None = None
    completed_at: datetime | None = None
    error: str | None = None  # If failed


class AgentProfile(str, Enum):
    QUICK = "quick"
    BALANCED = "balanced"
    THOROUGH = "thorough"


class PhaseConfig(BaseModel):
    model: str = "claude-sonnet-4-20250514"
    intensity: str = "medium"
    max_turns: int = 10


class PhaseMetrics(BaseModel):
    current_turn: int = 0
    estimated_turns: int = 0
    elapsed_time: float = 0.0
    estimated_remaining: float | None = None
    progress_percentage: int = 0
    last_log_preview: str = ""


class Phase(BaseModel):
    name: str
    status: PhaseStatus = PhaseStatus.PENDING
    config: PhaseConfig
    logs: list[str] = Field(default_factory=list)
    metrics: PhaseMetrics = Field(default_factory=PhaseMetrics)
    started_at: datetime | None = None
    completed_at: datetime | None = None


class GitOptions(BaseModel):
    branch_name: str | None = None
    target_branch: str = "develop"


class FileReference(BaseModel):
    path: str
    line_start: int | None = None
    line_end: int | None = None


class Task(BaseModel):
    id: str
    title: str
    description: str
    status: TaskStatus = TaskStatus.BACKLOG
    phases: dict[str, Phase]
    worktree_path: str | None = None
    branch_name: str | None = None
    pr_url: str | None = None
    pr_number: int | None = None
    pr_merged: bool = False
    pr_merged_at: datetime | None = None
    skip_ai_review: bool = False
    agent_profile: AgentProfile = AgentProfile.BALANCED
    require_human_review_before_coding: bool = False
    file_references: list[FileReference] = Field(default_factory=list)
    screenshots: list[str] = Field(default_factory=list)
    review_issues: list[dict] | None = None
    review_cycles: int = 0
    review_status: str | None = None
    review_output: str | None = None
    archived: bool = False
    archived_at: datetime | None = None
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)
    # v0.4 - Subtask workflow
    subtasks: list[Subtask] = Field(default_factory=list)
    current_phase: str | None = None  # "planning", "coding", "validation"
    current_subtask_id: str | None = None


class GlobalConfig(BaseModel):
    # General settings
    project_path: str
    target_branch: str = "main"

    # Legacy settings (keep for compatibility)
    default_model: str = "claude-sonnet-4-20250514"
    default_intensity: str = "medium"
    auto_review: bool = True

    # Agents configuration
    max_parallel_tasks: int = Field(default=3, ge=1, le=10)

    # Model configuration per phase
    planning_model: str = "claude-sonnet-4-20250514"
    coding_model: str = "claude-sonnet-4-20250514"
    validation_model: str = "claude-haiku-4-20250514"

    # Git settings
    auto_create_pr: bool = True
    pr_template: Optional[str] = None

    # Notification settings
    enable_sounds: bool = True
    enable_desktop_notifications: bool = False


class TaskCreate(BaseModel):
    title: str | None = None
    description: str
    agent_profile: AgentProfile = AgentProfile.BALANCED
    planning_config: PhaseConfig | None = None
    coding_config: PhaseConfig | None = None
    validation_config: PhaseConfig | None = None
    require_human_review_before_coding: bool = False
    skip_ai_review: bool = False
    git_options: GitOptions | None = None
    file_references: list[FileReference] = Field(default_factory=list)
    screenshots: list[str] = Field(default_factory=list)


class TaskUpdate(BaseModel):
    title: str | None = None
    description: str | None = None
    status: TaskStatus | None = None
    skip_ai_review: bool | None = None


class PhaseConfigUpdate(BaseModel):
    model: str | None = None
    intensity: str | None = None
    max_turns: int | None = None


class FixCommentsRequest(BaseModel):
    comment_ids: list[int]


# ============== Roadmap Models ==============

class Priority(str, Enum):
    MUST_HAVE = "must"
    SHOULD_HAVE = "should"
    COULD_HAVE = "could"
    WONT_HAVE = "wont"


class RoadmapPhase(str, Enum):
    FOUNDATION = "foundation"
    CORE = "core"
    ENHANCEMENT = "enhancement"
    POLISH = "polish"


class Complexity(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class Impact(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class FeatureStatus(str, Enum):
    UNDER_REVIEW = "under_review"
    PLANNED = "planned"
    IN_PROGRESS = "in_progress"
    DONE = "done"


class Feature(BaseModel):
    id: str
    title: str
    description: str
    justification: str | None = None
    phase: RoadmapPhase
    priority: Priority
    complexity: Complexity
    impact: Impact
    status: FeatureStatus = FeatureStatus.UNDER_REVIEW
    task_id: str | None = None
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)


class ProjectAnalysis(BaseModel):
    date: datetime
    stack: list[str] = Field(default_factory=list)
    structure_summary: str = ""
    files_count: int = 0


class Competitor(BaseModel):
    name: str
    url: str | None = None
    features: list[str] = Field(default_factory=list)


class CompetitorAnalysis(BaseModel):
    date: datetime
    competitors: list[Competitor] = Field(default_factory=list)


class Roadmap(BaseModel):
    project_name: str = ""
    project_description: str = ""
    target_audience: str = ""
    personas: list[str] = Field(default_factory=list)
    features: list[Feature] = Field(default_factory=list)
    analysis: ProjectAnalysis | None = None
    competitor_analysis: CompetitorAnalysis | None = None


class FeatureCreate(BaseModel):
    title: str
    description: str
    justification: str | None = None
    phase: RoadmapPhase = RoadmapPhase.CORE
    priority: Priority = Priority.SHOULD_HAVE
    complexity: Complexity = Complexity.MEDIUM
    impact: Impact = Impact.MEDIUM


class FeatureUpdate(BaseModel):
    title: str | None = None
    description: str | None = None
    justification: str | None = None
    phase: RoadmapPhase | None = None
    priority: Priority | None = None
    complexity: Complexity | None = None
    impact: Impact | None = None
    status: FeatureStatus | None = None


class RoadmapUpdate(BaseModel):
    project_name: str | None = None
    project_description: str | None = None
    target_audience: str | None = None
    personas: list[str] | None = None


# ============== Memory Models ==============

class SessionMessage(BaseModel):
    """A single message in a Claude Code session."""
    role: str  # "user" or "assistant"
    content: str
    timestamp: datetime
    token_count: int = 0


class ClaudeSession(BaseModel):
    """A Claude Code session with conversation history."""
    session_id: str
    project_path: str
    first_prompt: str
    summary: str | None = None
    message_count: int = 0
    token_count: int = 0
    git_branch: str | None = None
    worktree_path: str | None = None
    task_id: str | None = None  # Linked Codeflow task ID if any
    created_at: datetime
    modified_at: datetime
    is_resumable: bool = True  # Can be resumed with --resume


class SessionDetail(ClaudeSession):
    """Extended session info with full conversation."""
    messages: list[SessionMessage] = Field(default_factory=list)
