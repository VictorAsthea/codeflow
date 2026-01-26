"""
Resource conflict detection for parallel task execution.
Predicts file modifications and detects conflicts between tasks running in parallel.
"""

import re
import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from backend.models import Task

logger = logging.getLogger(__name__)


class ConflictSeverity(str, Enum):
    """Severity level of a detected conflict."""
    HIGH = "high"      # Same file modified by both tasks
    MEDIUM = "medium"  # Related files/directories
    LOW = "low"        # Potential indirect conflict


@dataclass
class FilePattern:
    """A pattern representing files that may be modified."""
    pattern: str
    confidence: float  # 0.0 to 1.0
    source: str  # Where this prediction came from


@dataclass
class PredictedFiles:
    """Predicted files that a task will modify."""
    task_id: str
    files: list[FilePattern] = field(default_factory=list)
    directories: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "task_id": self.task_id,
            "files": [{"pattern": f.pattern, "confidence": f.confidence, "source": f.source} for f in self.files],
            "directories": self.directories
        }


@dataclass
class Conflict:
    """A detected conflict between two tasks."""
    task_a_id: str
    task_b_id: str
    conflicting_patterns: list[str]
    severity: ConflictSeverity
    description: str

    def to_dict(self) -> dict:
        return {
            "task_a_id": self.task_a_id,
            "task_b_id": self.task_b_id,
            "conflicting_patterns": self.conflicting_patterns,
            "severity": self.severity.value,
            "description": self.description
        }


class ConflictDetector:
    """
    Detects potential resource conflicts between parallel tasks.

    Uses heuristics to predict which files a task will modify based on:
    - Task description keywords
    - File references
    - Subtask descriptions (if planning is done)
    """

    # Keywords that suggest specific file types/directories
    KEYWORD_FILE_PATTERNS = {
        # Backend patterns
        "api": ["backend/routers/*.py", "backend/main.py"],
        "endpoint": ["backend/routers/*.py"],
        "router": ["backend/routers/*.py"],
        "model": ["backend/models.py", "backend/models/*.py"],
        "service": ["backend/services/*.py"],
        "database": ["backend/models.py", "backend/services/storage*.py", "backend/services/*storage*.py"],
        "storage": ["backend/services/storage*.py", "backend/services/*storage*.py"],
        "config": ["backend/config.py", "config.py", "*.config.*"],
        "settings": ["backend/config.py", "backend/services/settings*.py"],
        "auth": ["backend/services/auth*.py", "backend/routers/auth*.py"],
        "websocket": ["backend/websocket*.py"],

        # Frontend patterns
        "frontend": ["frontend/**/*"],
        "ui": ["frontend/**/*"],
        "component": ["frontend/js/*.js", "frontend/components/*.js"],
        "style": ["frontend/css/*.css", "frontend/styles/*.css"],
        "css": ["frontend/css/*.css"],
        "template": ["frontend/*.html", "frontend/templates/*.html"],
        "html": ["frontend/*.html"],

        # Testing patterns
        "test": ["tests/**/*", "*_test.py", "test_*.py"],
        "tests": ["tests/**/*"],

        # Documentation
        "doc": ["docs/**/*", "*.md", "README*"],
        "readme": ["README*"],

        # Git/CI
        "ci": [".github/**/*", ".gitlab-ci.yml"],
        "github": [".github/**/*"],
        "workflow": [".github/workflows/*.yml"],

        # Task-specific patterns
        "queue": ["backend/services/task_queue.py", "backend/services/*queue*.py"],
        "orchestrator": ["backend/services/task_orchestrator.py"],
        "worktree": ["backend/services/worktree*.py"],
        "planning": ["backend/services/planning*.py"],
        "validation": ["backend/services/validation*.py"],
        "roadmap": ["backend/services/roadmap*.py", "backend/routers/roadmap*.py"],
    }

    # Common file extensions and their directories
    EXTENSION_PATTERNS = {
        ".py": ["backend/**/*.py", "tests/**/*.py"],
        ".js": ["frontend/**/*.js"],
        ".css": ["frontend/**/*.css"],
        ".html": ["frontend/**/*.html"],
        ".yml": [".github/**/*.yml", "*.yml"],
        ".yaml": [".github/**/*.yaml", "*.yaml"],
        ".json": ["*.json", "package.json"],
        ".md": ["docs/**/*.md", "*.md"],
    }

    def __init__(self):
        self._task_file_cache: dict[str, PredictedFiles] = {}

    def analyze_task_files(self, task: Task) -> PredictedFiles:
        """
        Predict files that a task will modify based on its description.

        Args:
            task: The task to analyze

        Returns:
            PredictedFiles with predicted file patterns and directories
        """
        # Check cache first
        if task.id in self._task_file_cache:
            return self._task_file_cache[task.id]

        predicted = PredictedFiles(task_id=task.id)
        text_to_analyze = self._get_analyzable_text(task)

        # 1. Extract explicit file references
        predicted.files.extend(self._extract_file_references(task))

        # 2. Extract files from subtasks if available
        predicted.files.extend(self._extract_from_subtasks(task))

        # 3. Analyze keywords in description
        predicted.files.extend(self._analyze_keywords(text_to_analyze))

        # 4. Extract explicit file paths mentioned in text
        predicted.files.extend(self._extract_file_paths(text_to_analyze))

        # 5. Deduce directories from all predicted files
        predicted.directories = self._extract_directories(predicted.files)

        # Cache the result
        self._task_file_cache[task.id] = predicted

        logger.info(
            f"Analyzed task {task.id}: {len(predicted.files)} file patterns, "
            f"{len(predicted.directories)} directories"
        )

        return predicted

    def check_conflicts(self, task_a: Task, task_b: Task) -> Optional[Conflict]:
        """
        Check if two tasks have potential file conflicts.

        Args:
            task_a: First task
            task_b: Second task

        Returns:
            Conflict if found, None otherwise
        """
        if task_a.id == task_b.id:
            return None

        files_a = self.analyze_task_files(task_a)
        files_b = self.analyze_task_files(task_b)

        # Find overlapping patterns
        conflicting = []
        severity = ConflictSeverity.LOW

        # Check direct file pattern matches
        patterns_a = {f.pattern for f in files_a.files}
        patterns_b = {f.pattern for f in files_b.files}

        # Exact matches (HIGH severity)
        exact_matches = patterns_a & patterns_b
        if exact_matches:
            conflicting.extend(exact_matches)
            severity = ConflictSeverity.HIGH

        # Check for wildcard pattern overlaps
        for pattern_a in patterns_a - exact_matches:
            for pattern_b in patterns_b - exact_matches:
                if self._patterns_overlap(pattern_a, pattern_b):
                    conflicting.append(f"{pattern_a} <-> {pattern_b}")
                    if severity == ConflictSeverity.LOW:
                        severity = ConflictSeverity.MEDIUM

        # Check directory overlaps (MEDIUM severity if no higher conflicts)
        dir_overlap = set(files_a.directories) & set(files_b.directories)
        if dir_overlap and not conflicting:
            conflicting.extend([f"dir:{d}" for d in dir_overlap])
            severity = ConflictSeverity.MEDIUM

        if not conflicting:
            return None

        description = self._generate_conflict_description(
            task_a, task_b, conflicting, severity
        )

        return Conflict(
            task_a_id=task_a.id,
            task_b_id=task_b.id,
            conflicting_patterns=conflicting,
            severity=severity,
            description=description
        )

    def get_safe_parallel_tasks(self, tasks: list[Task]) -> list[list[Task]]:
        """
        Group tasks into sets that can safely run in parallel.

        Args:
            tasks: List of tasks to analyze

        Returns:
            List of task groups, where tasks within each group are safe to run together
        """
        if not tasks:
            return []

        if len(tasks) == 1:
            return [tasks]

        # Build a conflict graph
        conflicts: dict[str, set[str]] = {t.id: set() for t in tasks}

        for i, task_a in enumerate(tasks):
            for task_b in tasks[i + 1:]:
                conflict = self.check_conflicts(task_a, task_b)
                if conflict and conflict.severity in (ConflictSeverity.HIGH, ConflictSeverity.MEDIUM):
                    conflicts[task_a.id].add(task_b.id)
                    conflicts[task_b.id].add(task_a.id)

        # Greedy coloring algorithm to group non-conflicting tasks
        task_by_id = {t.id: t for t in tasks}
        groups: list[list[Task]] = []
        assigned = set()

        # Sort tasks by number of conflicts (most conflicts first for better grouping)
        sorted_task_ids = sorted(
            [t.id for t in tasks],
            key=lambda tid: len(conflicts[tid]),
            reverse=True
        )

        for task_id in sorted_task_ids:
            if task_id in assigned:
                continue

            # Find a group where this task doesn't conflict with any member
            placed = False
            for group in groups:
                can_place = all(
                    other.id not in conflicts[task_id]
                    for other in group
                )
                if can_place:
                    group.append(task_by_id[task_id])
                    assigned.add(task_id)
                    placed = True
                    break

            if not placed:
                # Create a new group
                groups.append([task_by_id[task_id]])
                assigned.add(task_id)

        return groups

    def get_all_conflicts(self, tasks: list[Task]) -> list[Conflict]:
        """
        Get all conflicts between a list of tasks.

        Args:
            tasks: List of tasks to check

        Returns:
            List of all detected conflicts
        """
        conflicts = []
        for i, task_a in enumerate(tasks):
            for task_b in tasks[i + 1:]:
                conflict = self.check_conflicts(task_a, task_b)
                if conflict:
                    conflicts.append(conflict)
        return conflicts

    def get_task_conflicts(self, task: Task, other_tasks: list[Task]) -> list[Conflict]:
        """
        Get all conflicts for a specific task against other tasks.

        Args:
            task: The task to check
            other_tasks: List of other tasks to check against

        Returns:
            List of conflicts involving this task
        """
        conflicts = []
        for other in other_tasks:
            if other.id == task.id:
                continue
            conflict = self.check_conflicts(task, other)
            if conflict:
                conflicts.append(conflict)
        return conflicts

    def clear_cache(self, task_id: Optional[str] = None):
        """Clear the prediction cache."""
        if task_id:
            self._task_file_cache.pop(task_id, None)
        else:
            self._task_file_cache.clear()

    def _get_analyzable_text(self, task: Task) -> str:
        """Combine all task text for analysis."""
        parts = [task.title, task.description or ""]

        # Include subtask info if available
        for subtask in task.subtasks:
            parts.append(subtask.title)
            if subtask.description:
                parts.append(subtask.description)

        return " ".join(parts).lower()

    def _extract_file_references(self, task: Task) -> list[FilePattern]:
        """Extract files from explicit file references."""
        patterns = []
        for ref in task.file_references:
            patterns.append(FilePattern(
                pattern=ref.path,
                confidence=1.0,
                source="file_reference"
            ))
        return patterns

    def _extract_from_subtasks(self, task: Task) -> list[FilePattern]:
        """Extract file patterns from subtask descriptions."""
        patterns = []

        for subtask in task.subtasks:
            text = f"{subtask.title} {subtask.description or ''}"

            # Look for explicit file paths in subtask descriptions
            file_matches = re.findall(
                r'(?:in |at |file |create |modify |update |edit )?'
                r'([a-zA-Z0-9_\-./]+\.[a-z]{2,4})',
                text,
                re.IGNORECASE
            )

            for match in file_matches:
                if self._is_valid_file_path(match):
                    patterns.append(FilePattern(
                        pattern=match,
                        confidence=0.9,
                        source=f"subtask:{subtask.id}"
                    ))

        return patterns

    def _analyze_keywords(self, text: str) -> list[FilePattern]:
        """Analyze text for keywords that suggest file modifications."""
        patterns = []

        for keyword, file_patterns in self.KEYWORD_FILE_PATTERNS.items():
            if keyword in text:
                for pattern in file_patterns:
                    patterns.append(FilePattern(
                        pattern=pattern,
                        confidence=0.6,
                        source=f"keyword:{keyword}"
                    ))

        return patterns

    def _extract_file_paths(self, text: str) -> list[FilePattern]:
        """Extract explicit file paths from text."""
        patterns = []

        # Match common file path patterns
        path_regex = re.compile(
            r'(?:^|[\s`"\'])([a-zA-Z0-9_\-./]+/[a-zA-Z0-9_\-./]+\.[a-z]{2,4})(?:[\s`"\']|$)'
        )

        for match in path_regex.findall(text):
            if self._is_valid_file_path(match):
                patterns.append(FilePattern(
                    pattern=match,
                    confidence=0.8,
                    source="text_path"
                ))

        return patterns

    def _extract_directories(self, file_patterns: list[FilePattern]) -> list[str]:
        """Extract unique directories from file patterns."""
        directories = set()

        for fp in file_patterns:
            pattern = fp.pattern

            # Remove wildcards for directory extraction
            clean = pattern.replace("**", "").replace("*", "")

            # Get directory part
            if "/" in clean:
                dir_part = "/".join(clean.split("/")[:-1])
                if dir_part:
                    directories.add(dir_part.strip("/"))

        return list(directories)

    def _is_valid_file_path(self, path: str) -> bool:
        """Check if a string looks like a valid file path."""
        if not path or len(path) < 3:
            return False

        # Must have an extension
        if "." not in path.split("/")[-1]:
            return False

        # Filter out URLs and other non-paths
        if path.startswith(("http://", "https://", "ftp://", "file://")):
            return False

        # Filter out version numbers
        if re.match(r'^\d+\.\d+\.\d+', path):
            return False

        return True

    def _patterns_overlap(self, pattern_a: str, pattern_b: str) -> bool:
        """Check if two file patterns might match the same files."""
        # Normalize patterns
        a = pattern_a.replace("**", "*").rstrip("/")
        b = pattern_b.replace("**", "*").rstrip("/")

        # Check if one contains the other (for directory patterns)
        if a.startswith(b.replace("*", "")) or b.startswith(a.replace("*", "")):
            return True

        # Check if base directories match
        dir_a = "/".join(a.split("/")[:-1]).replace("*", "")
        dir_b = "/".join(b.split("/")[:-1]).replace("*", "")

        if dir_a and dir_b:
            if dir_a.startswith(dir_b) or dir_b.startswith(dir_a):
                # Check if extensions match
                ext_a = a.split(".")[-1].replace("*", "")
                ext_b = b.split(".")[-1].replace("*", "")
                if not ext_a or not ext_b or ext_a == ext_b:
                    return True

        return False

    def _generate_conflict_description(
        self,
        task_a: Task,
        task_b: Task,
        conflicting: list[str],
        severity: ConflictSeverity
    ) -> str:
        """Generate a human-readable conflict description."""
        if severity == ConflictSeverity.HIGH:
            return (
                f"Tasks '{task_a.title}' and '{task_b.title}' may both modify the same files: "
                f"{', '.join(conflicting[:3])}{'...' if len(conflicting) > 3 else ''}"
            )
        elif severity == ConflictSeverity.MEDIUM:
            return (
                f"Tasks '{task_a.title}' and '{task_b.title}' may modify related files/directories: "
                f"{', '.join(conflicting[:3])}{'...' if len(conflicting) > 3 else ''}"
            )
        else:
            return (
                f"Tasks '{task_a.title}' and '{task_b.title}' have potential indirect conflicts"
            )


# Global instance
conflict_detector = ConflictDetector()
