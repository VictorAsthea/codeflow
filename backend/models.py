from datetime import datetime
from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field, field_validator, HttpUrl
import re

# Validation constants
TASK_ID_PATTERN = r"^[a-zA-Z0-9-_]+$"
TASK_ID_REGEX = re.compile(TASK_ID_PATTERN)
MAX_TITLE_LENGTH = 500
MAX_DESCRIPTION_LENGTH = 10000
MAX_ID_LENGTH = 100
MAX_PATH_LENGTH = 4096  # Standard max path length

# Feature/Roadmap validation constants
FEATURE_ID_PATTERN = r"^[a-zA-Z0-9-_]+$"
FEATURE_ID_REGEX = re.compile(FEATURE_ID_PATTERN)
MAX_FEATURE_TITLE_LENGTH = 200
MAX_FEATURE_DESCRIPTION_LENGTH = 5000
MAX_JUSTIFICATION_LENGTH = 2000
MAX_FEATURE_ID_LENGTH = 100
MAX_PROJECT_NAME_LENGTH = 200
MAX_PROJECT_DESCRIPTION_LENGTH = 5000
MAX_TARGET_AUDIENCE_LENGTH = 1000
MAX_PERSONA_LENGTH = 200
MAX_COMPETITOR_NAME_LENGTH = 200
MAX_URL_LENGTH = 2048  # Standard max URL length

# Ideation/Chat validation constants
MAX_CHAT_MESSAGE_LENGTH = 10000  # Max user message length to prevent abuse
MAX_SUGGESTION_TITLE_LENGTH = 200
MAX_SUGGESTION_DESCRIPTION_LENGTH = 5000
MAX_SUGGESTION_ID_LENGTH = 100
SUGGESTION_ID_PATTERN = r"^[a-zA-Z0-9-_]+$"
SUGGESTION_ID_REGEX = re.compile(SUGGESTION_ID_PATTERN)
MAX_CHAT_RESPONSE_LENGTH = 50000  # AI responses can be longer
MAX_CHAT_SUGGESTION_LENGTH = 500  # Individual suggestion text in chat response
PRIORITY_VALUES = {"low", "medium", "high"}  # Valid priority values

# Path security patterns
# Disallow path traversal sequences
PATH_TRAVERSAL_PATTERN = re.compile(r"(^|[\\/])\.\.($|[\\/])")
# Shell metacharacters that could enable injection
# Note: backslash (\) is allowed for Windows path separators
SHELL_METACHARACTERS = set(';&|`$(){}[]<>!\'"*?~#')
# Null bytes (path injection)
NULL_BYTE_PATTERN = re.compile(r"\x00")


def validate_path_security(path: str, field_name: str = "path") -> str:
    """
    Validate a file path for security issues.

    Checks for:
    - Path traversal attacks (../)
    - Shell metacharacters that could enable injection
    - Null bytes
    - Empty paths
    - Excessive length
    """
    if not path:
        raise ValueError(f"{field_name} cannot be empty")

    # Check length
    if len(path) > MAX_PATH_LENGTH:
        raise ValueError(f"{field_name} exceeds maximum length of {MAX_PATH_LENGTH} characters")

    # Check for null bytes
    if NULL_BYTE_PATTERN.search(path):
        raise ValueError(f"{field_name} contains invalid null bytes")

    # Check for path traversal
    if PATH_TRAVERSAL_PATTERN.search(path):
        raise ValueError(f"{field_name} contains path traversal sequences (..)")

    # Check for shell metacharacters
    # Allow common path characters: / \ . - _ and alphanumerics, spaces, colons (Windows drive)
    dangerous_chars = set(path) & SHELL_METACHARACTERS
    if dangerous_chars:
        raise ValueError(
            f"{field_name} contains potentially dangerous characters: {', '.join(sorted(dangerous_chars))}"
        )

    return path


def validate_path_security_optional(path: str | None, field_name: str = "path") -> str | None:
    """Validate a file path if provided, allowing None values."""
    if path is None:
        return None
    return validate_path_security(path, field_name)


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
    id: str = Field(
        ...,
        min_length=1,
        max_length=MAX_ID_LENGTH,
        pattern=TASK_ID_PATTERN,
        description="Subtask identifier (e.g., 'subtask-1', 'subtask-2')"
    )
    title: str = Field(
        ...,
        min_length=1,
        max_length=MAX_TITLE_LENGTH,
        description="Subtask title"
    )
    description: str | None = Field(
        default=None,
        max_length=MAX_DESCRIPTION_LENGTH,
        description="Subtask description"
    )
    status: SubtaskStatus = SubtaskStatus.PENDING
    order: int = Field(..., ge=0, description="Order for sorting")
    dependencies: list[str] = Field(default_factory=list)  # IDs of dependent subtasks
    started_at: datetime | None = None
    completed_at: datetime | None = None
    error: str | None = Field(
        default=None,
        max_length=MAX_DESCRIPTION_LENGTH,
        description="Error message if failed"
    )

    @field_validator("title")
    @classmethod
    def validate_title(cls, v: str) -> str:
        """Strip whitespace and ensure title is not empty."""
        v = v.strip()
        if not v:
            raise ValueError("Title cannot be empty or whitespace-only")
        return v

    @field_validator("description")
    @classmethod
    def validate_description(cls, v: str | None) -> str | None:
        """Strip whitespace from description if provided."""
        if v is not None:
            v = v.strip()
            if not v:
                return None  # Treat empty string as None
        return v


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
    path: str = Field(
        ...,
        min_length=1,
        max_length=MAX_PATH_LENGTH,
        description="File path (relative to project root)"
    )
    line_start: int | None = Field(default=None, ge=1, description="Starting line number")
    line_end: int | None = Field(default=None, ge=1, description="Ending line number")

    @field_validator("path")
    @classmethod
    def validate_path(cls, v: str) -> str:
        """Validate file path for security issues."""
        v = v.strip()
        return validate_path_security(v, "path")

    @field_validator("line_end")
    @classmethod
    def validate_line_end(cls, v: int | None, info) -> int | None:
        """Ensure line_end is >= line_start if both are provided."""
        if v is not None and info.data.get("line_start") is not None:
            if v < info.data["line_start"]:
                raise ValueError("line_end must be >= line_start")
        return v


class Task(BaseModel):
    id: str = Field(
        ...,
        min_length=1,
        max_length=MAX_ID_LENGTH,
        pattern=TASK_ID_PATTERN,
        description="Unique task identifier (alphanumeric, hyphens, underscores only)"
    )
    title: str = Field(
        ...,
        min_length=1,
        max_length=MAX_TITLE_LENGTH,
        description="Task title"
    )
    description: str = Field(
        ...,
        min_length=1,
        max_length=MAX_DESCRIPTION_LENGTH,
        description="Task description"
    )
    status: TaskStatus = TaskStatus.BACKLOG
    phases: dict[str, Phase]
    worktree_path: str | None = Field(
        default=None,
        max_length=MAX_PATH_LENGTH,
        description="Path to the git worktree for this task"
    )
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

    @field_validator("title", "description")
    @classmethod
    def strip_and_validate_not_empty(cls, v: str) -> str:
        """Strip whitespace and ensure the value is not empty or whitespace-only."""
        if v is not None:
            v = v.strip()
            if not v:
                raise ValueError("Value cannot be empty or whitespace-only")
        return v

    @field_validator("worktree_path")
    @classmethod
    def validate_worktree_path(cls, v: str | None) -> str | None:
        """Validate worktree path for security issues."""
        return validate_path_security_optional(v, "worktree_path")


class GlobalConfig(BaseModel):
    # General settings
    project_path: str = Field(
        ...,
        min_length=1,
        max_length=MAX_PATH_LENGTH,
        description="Absolute path to the project directory"
    )
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

    @field_validator("project_path")
    @classmethod
    def validate_project_path(cls, v: str) -> str:
        """Validate project path for security issues."""
        return validate_path_security(v, "project_path")


class TaskCreate(BaseModel):
    title: str | None = Field(
        default=None,
        max_length=MAX_TITLE_LENGTH,
        description="Task title (optional, auto-generated if not provided)"
    )
    description: str = Field(
        ...,
        min_length=1,
        max_length=MAX_DESCRIPTION_LENGTH,
        description="Task description"
    )
    agent_profile: AgentProfile = AgentProfile.BALANCED
    planning_config: PhaseConfig | None = None
    coding_config: PhaseConfig | None = None
    validation_config: PhaseConfig | None = None
    require_human_review_before_coding: bool = False
    skip_ai_review: bool = False
    git_options: GitOptions | None = None
    file_references: list[FileReference] = Field(default_factory=list)
    screenshots: list[str] = Field(default_factory=list)

    @field_validator("title")
    @classmethod
    def validate_title(cls, v: str | None) -> str | None:
        """Strip whitespace and validate title if provided."""
        if v is not None:
            v = v.strip()
            if not v:
                return None  # Treat empty string as None (will be auto-generated)
        return v

    @field_validator("description")
    @classmethod
    def validate_description(cls, v: str) -> str:
        """Strip whitespace and ensure description is not empty."""
        v = v.strip()
        if not v:
            raise ValueError("Description cannot be empty or whitespace-only")
        return v


class TaskUpdate(BaseModel):
    title: str | None = Field(
        default=None,
        min_length=1,
        max_length=MAX_TITLE_LENGTH,
        description="Task title"
    )
    description: str | None = Field(
        default=None,
        min_length=1,
        max_length=MAX_DESCRIPTION_LENGTH,
        description="Task description"
    )
    status: TaskStatus | None = None
    skip_ai_review: bool | None = None

    @field_validator("title", "description")
    @classmethod
    def strip_and_validate(cls, v: str | None) -> str | None:
        """Strip whitespace and ensure value is not empty if provided."""
        if v is not None:
            v = v.strip()
            if not v:
                raise ValueError("Value cannot be empty or whitespace-only")
        return v


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
    id: str = Field(
        ...,
        min_length=1,
        max_length=MAX_FEATURE_ID_LENGTH,
        pattern=FEATURE_ID_PATTERN,
        description="Feature identifier (alphanumeric, hyphens, underscores only)"
    )
    title: str = Field(
        ...,
        min_length=1,
        max_length=MAX_FEATURE_TITLE_LENGTH,
        description="Feature title"
    )
    description: str = Field(
        ...,
        min_length=1,
        max_length=MAX_FEATURE_DESCRIPTION_LENGTH,
        description="Feature description"
    )
    justification: str | None = Field(
        default=None,
        max_length=MAX_JUSTIFICATION_LENGTH,
        description="Justification for the feature"
    )
    phase: RoadmapPhase
    priority: Priority
    complexity: Complexity
    impact: Impact
    status: FeatureStatus = FeatureStatus.UNDER_REVIEW
    task_id: str | None = Field(
        default=None,
        max_length=MAX_ID_LENGTH,
        pattern=TASK_ID_PATTERN,
        description="Associated task ID (if converted to task)"
    )
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)

    @field_validator("title", "description")
    @classmethod
    def strip_and_validate_not_empty(cls, v: str) -> str:
        """Strip whitespace and ensure the value is not empty or whitespace-only."""
        v = v.strip()
        if not v:
            raise ValueError("Value cannot be empty or whitespace-only")
        return v

    @field_validator("justification")
    @classmethod
    def validate_justification(cls, v: str | None) -> str | None:
        """Strip whitespace from justification if provided."""
        if v is not None:
            v = v.strip()
            if not v:
                return None  # Treat empty string as None
        return v


class ProjectAnalysis(BaseModel):
    date: datetime
    stack: list[str] = Field(default_factory=list)
    structure_summary: str = ""
    files_count: int = 0


class Competitor(BaseModel):
    name: str = Field(
        ...,
        min_length=1,
        max_length=MAX_COMPETITOR_NAME_LENGTH,
        description="Competitor name"
    )
    url: str | None = Field(
        default=None,
        max_length=MAX_URL_LENGTH,
        description="Competitor URL"
    )
    features: list[str] = Field(default_factory=list)

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        """Strip whitespace and ensure name is not empty."""
        v = v.strip()
        if not v:
            raise ValueError("Name cannot be empty or whitespace-only")
        return v

    @field_validator("url")
    @classmethod
    def validate_url(cls, v: str | None) -> str | None:
        """Validate URL format if provided."""
        if v is not None:
            v = v.strip()
            if not v:
                return None  # Treat empty string as None
            # Basic URL validation - must start with http:// or https://
            if not v.startswith(("http://", "https://")):
                raise ValueError("URL must start with http:// or https://")
        return v


class CompetitorAnalysis(BaseModel):
    date: datetime
    competitors: list[Competitor] = Field(default_factory=list)


class Roadmap(BaseModel):
    project_name: str = Field(
        default="",
        max_length=MAX_PROJECT_NAME_LENGTH,
        description="Project name"
    )
    project_description: str = Field(
        default="",
        max_length=MAX_PROJECT_DESCRIPTION_LENGTH,
        description="Project description"
    )
    target_audience: str = Field(
        default="",
        max_length=MAX_TARGET_AUDIENCE_LENGTH,
        description="Target audience description"
    )
    personas: list[str] = Field(default_factory=list)
    features: list[Feature] = Field(default_factory=list)
    analysis: ProjectAnalysis | None = None
    competitor_analysis: CompetitorAnalysis | None = None

    @field_validator("project_name", "project_description", "target_audience")
    @classmethod
    def strip_whitespace(cls, v: str) -> str:
        """Strip whitespace from string fields."""
        return v.strip() if v else v

    @field_validator("personas")
    @classmethod
    def validate_personas(cls, v: list[str]) -> list[str]:
        """Validate and strip personas."""
        validated = []
        for persona in v:
            if isinstance(persona, str):
                persona = persona.strip()
                if persona:
                    if len(persona) > MAX_PERSONA_LENGTH:
                        raise ValueError(f"Persona exceeds maximum length of {MAX_PERSONA_LENGTH} characters")
                    validated.append(persona)
        return validated


class FeatureCreate(BaseModel):
    title: str = Field(
        ...,
        min_length=1,
        max_length=MAX_FEATURE_TITLE_LENGTH,
        description="Feature title"
    )
    description: str = Field(
        ...,
        min_length=1,
        max_length=MAX_FEATURE_DESCRIPTION_LENGTH,
        description="Feature description"
    )
    justification: str | None = Field(
        default=None,
        max_length=MAX_JUSTIFICATION_LENGTH,
        description="Justification for the feature"
    )
    phase: RoadmapPhase = RoadmapPhase.CORE
    priority: Priority = Priority.SHOULD_HAVE
    complexity: Complexity = Complexity.MEDIUM
    impact: Impact = Impact.MEDIUM

    @field_validator("title", "description")
    @classmethod
    def strip_and_validate_not_empty(cls, v: str) -> str:
        """Strip whitespace and ensure the value is not empty or whitespace-only."""
        v = v.strip()
        if not v:
            raise ValueError("Value cannot be empty or whitespace-only")
        return v

    @field_validator("justification")
    @classmethod
    def validate_justification(cls, v: str | None) -> str | None:
        """Strip whitespace from justification if provided."""
        if v is not None:
            v = v.strip()
            if not v:
                return None  # Treat empty string as None
        return v


class FeatureUpdate(BaseModel):
    title: str | None = Field(
        default=None,
        min_length=1,
        max_length=MAX_FEATURE_TITLE_LENGTH,
        description="Feature title"
    )
    description: str | None = Field(
        default=None,
        min_length=1,
        max_length=MAX_FEATURE_DESCRIPTION_LENGTH,
        description="Feature description"
    )
    justification: str | None = Field(
        default=None,
        max_length=MAX_JUSTIFICATION_LENGTH,
        description="Justification for the feature"
    )
    phase: RoadmapPhase | None = None
    priority: Priority | None = None
    complexity: Complexity | None = None
    impact: Impact | None = None
    status: FeatureStatus | None = None

    @field_validator("title", "description")
    @classmethod
    def strip_and_validate(cls, v: str | None) -> str | None:
        """Strip whitespace and ensure value is not empty if provided."""
        if v is not None:
            v = v.strip()
            if not v:
                raise ValueError("Value cannot be empty or whitespace-only")
        return v

    @field_validator("justification")
    @classmethod
    def validate_justification(cls, v: str | None) -> str | None:
        """Strip whitespace from justification if provided."""
        if v is not None:
            v = v.strip()
            if not v:
                return None  # Treat empty string as None
        return v


class RoadmapUpdate(BaseModel):
    project_name: str | None = Field(
        default=None,
        max_length=MAX_PROJECT_NAME_LENGTH,
        description="Project name"
    )
    project_description: str | None = Field(
        default=None,
        max_length=MAX_PROJECT_DESCRIPTION_LENGTH,
        description="Project description"
    )
    target_audience: str | None = Field(
        default=None,
        max_length=MAX_TARGET_AUDIENCE_LENGTH,
        description="Target audience description"
    )
    personas: list[str] | None = None

    @field_validator("project_name", "project_description", "target_audience")
    @classmethod
    def strip_whitespace(cls, v: str | None) -> str | None:
        """Strip whitespace from string fields if provided."""
        return v.strip() if v else v

    @field_validator("personas")
    @classmethod
    def validate_personas(cls, v: list[str] | None) -> list[str] | None:
        """Validate and strip personas if provided."""
        if v is None:
            return v
        validated = []
        for persona in v:
            if isinstance(persona, str):
                persona = persona.strip()
                if persona:
                    if len(persona) > MAX_PERSONA_LENGTH:
                        raise ValueError(f"Persona exceeds maximum length of {MAX_PERSONA_LENGTH} characters")
                    validated.append(persona)
        return validated


# ============== Ideation Models ==============

class SuggestionCategory(str, Enum):
    SECURITY = "security"
    PERFORMANCE = "performance"
    QUALITY = "quality"
    FEATURE = "feature"


class SuggestionStatus(str, Enum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    DISMISSED = "dismissed"


class Suggestion(BaseModel):
    id: str = Field(
        ...,
        min_length=1,
        max_length=MAX_SUGGESTION_ID_LENGTH,
        pattern=SUGGESTION_ID_PATTERN,
        description="Suggestion identifier (alphanumeric, hyphens, underscores only)"
    )
    title: str = Field(
        ...,
        min_length=1,
        max_length=MAX_SUGGESTION_TITLE_LENGTH,
        description="Suggestion title"
    )
    description: str = Field(
        ...,
        min_length=1,
        max_length=MAX_SUGGESTION_DESCRIPTION_LENGTH,
        description="Suggestion description"
    )
    category: SuggestionCategory
    priority: str = Field(
        default="medium",
        description="Priority level: low, medium, or high"
    )
    status: SuggestionStatus = SuggestionStatus.PENDING
    task_id: str | None = Field(
        default=None,
        max_length=MAX_ID_LENGTH,
        pattern=TASK_ID_PATTERN,
        description="Associated task ID (if converted to task)"
    )
    created_at: datetime = Field(default_factory=datetime.now)

    @field_validator("title", "description")
    @classmethod
    def strip_and_validate_not_empty(cls, v: str) -> str:
        """Strip whitespace and ensure the value is not empty or whitespace-only."""
        v = v.strip()
        if not v:
            raise ValueError("Value cannot be empty or whitespace-only")
        return v

    @field_validator("priority")
    @classmethod
    def validate_priority(cls, v: str) -> str:
        """Validate priority is one of the allowed values."""
        v = v.strip().lower()
        if v not in PRIORITY_VALUES:
            raise ValueError(f"Priority must be one of: {', '.join(sorted(PRIORITY_VALUES))}")
        return v


class IdeationAnalysis(BaseModel):
    project_path: str = Field(
        ...,
        min_length=1,
        max_length=MAX_PATH_LENGTH,
        description="Absolute path to the analyzed project"
    )
    project_name: str = Field(
        ...,
        min_length=1,
        max_length=MAX_PROJECT_NAME_LENGTH,
        description="Name of the analyzed project"
    )
    stack: list[str] = Field(
        default_factory=list,
        max_length=50,  # Reasonable limit for tech stack items
        description="Technology stack detected"
    )
    frameworks: list[str] = Field(
        default_factory=list,
        max_length=50,  # Reasonable limit for frameworks
        description="Frameworks detected"
    )
    files_count: int = Field(default=0, ge=0)
    lines_count: int = Field(default=0, ge=0)
    key_directories: list[str] = Field(
        default_factory=list,
        max_length=100,  # Reasonable limit for directories
        description="Key directories in the project"
    )
    patterns_detected: list[str] = Field(
        default_factory=list,
        max_length=100,  # Reasonable limit for patterns
        description="Code patterns detected"
    )
    analyzed_at: datetime = Field(default_factory=datetime.now)

    @field_validator("project_path")
    @classmethod
    def validate_project_path(cls, v: str) -> str:
        """Validate project path for security issues."""
        return validate_path_security(v, "project_path")

    @field_validator("project_name")
    @classmethod
    def validate_project_name(cls, v: str) -> str:
        """Strip whitespace and ensure project name is not empty."""
        v = v.strip()
        if not v:
            raise ValueError("Project name cannot be empty or whitespace-only")
        return v

    @field_validator("stack", "frameworks", "patterns_detected")
    @classmethod
    def validate_string_lists(cls, v: list[str]) -> list[str]:
        """Validate and clean string list items."""
        validated = []
        for item in v:
            if isinstance(item, str):
                item = item.strip()
                if item:
                    if len(item) > MAX_FEATURE_TITLE_LENGTH:  # Reuse 200 char limit
                        raise ValueError(f"Item exceeds maximum length of {MAX_FEATURE_TITLE_LENGTH} characters")
                    validated.append(item)
        return validated

    @field_validator("key_directories")
    @classmethod
    def validate_key_directories(cls, v: list[str]) -> list[str]:
        """Validate directory paths for security issues."""
        validated = []
        for path in v:
            if isinstance(path, str):
                path = path.strip()
                if path:
                    # Validate each path for security
                    validate_path_security(path, "key_directories item")
                    validated.append(path)
        return validated


class IdeationData(BaseModel):
    analysis: IdeationAnalysis | None = None
    suggestions: list[Suggestion] = Field(
        default_factory=list,
        max_length=500,  # Reasonable limit for suggestions
        description="AI-generated improvement suggestions"
    )


class ChatRole(str, Enum):
    """Valid roles for chat messages."""
    USER = "user"
    ASSISTANT = "assistant"


class ChatMessage(BaseModel):
    role: str = Field(
        ...,
        description="Message role: 'user' or 'assistant'"
    )
    content: str = Field(
        ...,
        min_length=1,
        max_length=MAX_CHAT_MESSAGE_LENGTH,
        description="Message content"
    )
    timestamp: datetime = Field(default_factory=datetime.now)

    @field_validator("role")
    @classmethod
    def validate_role(cls, v: str) -> str:
        """Validate role is one of the allowed values."""
        v = v.strip().lower()
        valid_roles = {role.value for role in ChatRole}
        if v not in valid_roles:
            raise ValueError(f"Role must be one of: {', '.join(sorted(valid_roles))}")
        return v

    @field_validator("content")
    @classmethod
    def validate_content(cls, v: str) -> str:
        """Strip whitespace and ensure content is not empty."""
        v = v.strip()
        if not v:
            raise ValueError("Content cannot be empty or whitespace-only")
        return v


class ChatRequest(BaseModel):
    message: str = Field(
        ...,
        min_length=1,
        max_length=MAX_CHAT_MESSAGE_LENGTH,
        description="User message (max 10000 characters)"
    )
    context: list[ChatMessage] = Field(
        default_factory=list,
        max_length=100,  # Limit conversation history size
        description="Previous conversation messages for context"
    )

    @field_validator("message")
    @classmethod
    def validate_message(cls, v: str) -> str:
        """Strip whitespace and ensure message is not empty."""
        v = v.strip()
        if not v:
            raise ValueError("Message cannot be empty or whitespace-only")
        return v


class ChatResponse(BaseModel):
    response: str = Field(
        ...,
        min_length=1,
        max_length=MAX_CHAT_RESPONSE_LENGTH,
        description="AI response content"
    )
    suggestions: list[str] = Field(
        default_factory=list,
        max_length=20,  # Limit number of suggestions
        description="Suggested follow-up prompts or actions"
    )

    @field_validator("suggestions")
    @classmethod
    def validate_suggestions(cls, v: list[str]) -> list[str]:
        """Validate and clean suggestion strings."""
        validated = []
        for suggestion in v:
            if isinstance(suggestion, str):
                suggestion = suggestion.strip()
                if suggestion:
                    if len(suggestion) > MAX_CHAT_SUGGESTION_LENGTH:
                        raise ValueError(
                            f"Suggestion exceeds maximum length of {MAX_CHAT_SUGGESTION_LENGTH} characters"
                        )
                    validated.append(suggestion)
        return validated


# ============== Memory/Session Models ==============

class SessionStatus(str, Enum):
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class Session(BaseModel):
    """Session metadata for list views."""
    session_id: str
    task_id: str | None = None
    task_title: str | None = None
    worktree: str | None = Field(
        default=None,
        max_length=MAX_PATH_LENGTH,
        description="Path to the worktree for this session"
    )
    started_at: datetime | None = None
    ended_at: datetime | None = None
    status: SessionStatus = SessionStatus.COMPLETED
    messages_count: int = Field(default=0, ge=0)
    tokens_used: int = Field(default=0, ge=0)
    claude_session_id: str | None = None

    @field_validator("worktree")
    @classmethod
    def validate_worktree(cls, v: str | None) -> str | None:
        """Validate worktree path for security issues."""
        return validate_path_security_optional(v, "worktree")


class SessionMessage(BaseModel):
    """A single message in a session conversation."""
    role: str  # "user", "assistant", "system"
    content: str
    timestamp: datetime | None = None


class SessionDetail(Session):
    """Full session details including conversation."""
    messages: list[SessionMessage] = Field(default_factory=list)
    raw_output: str | None = None
    error: str | None = None


class SessionCreate(BaseModel):
    """Data for creating a new session."""
    task_title: str | None = None
    worktree: str | None = Field(
        default=None,
        max_length=MAX_PATH_LENGTH,
        description="Path to the worktree for this session"
    )
    started_at: datetime | None = None
    ended_at: datetime | None = None
    status: SessionStatus = SessionStatus.COMPLETED
    messages_count: int = Field(default=0, ge=0)
    tokens_used: int = Field(default=0, ge=0)
    claude_session_id: str | None = None
    messages: list[dict] = Field(default_factory=list)
    raw_output: str | None = None
    error: str | None = None

    @field_validator("worktree")
    @classmethod
    def validate_worktree(cls, v: str | None) -> str | None:
        """Validate worktree path for security issues."""
        return validate_path_security_optional(v, "worktree")


class ResumeInfo(BaseModel):
    """Information needed to resume a session."""
    claude_session_id: str
    project_path: str | None = Field(
        default=None,
        max_length=MAX_PATH_LENGTH,
        description="Absolute path to the project directory"
    )
    worktree_path: str | None = Field(
        default=None,
        max_length=MAX_PATH_LENGTH,
        description="Path to the worktree directory"
    )
    last_message: str | None = None

    @field_validator("project_path", "worktree_path")
    @classmethod
    def validate_paths(cls, v: str | None, info) -> str | None:
        """Validate path fields for security issues."""
        return validate_path_security_optional(v, info.field_name)
