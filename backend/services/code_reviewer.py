"""
Code review service using Claude CLI /code-review command
"""
import json
import subprocess
import asyncio
from pathlib import Path
from typing import Optional
from dataclasses import dataclass
from enum import Enum


class ReviewSeverity(str, Enum):
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


@dataclass
class ReviewIssue:
    """Represents a single code review issue"""
    severity: ReviewSeverity
    confidence: float
    message: str
    file_path: Optional[str] = None
    line_number: Optional[int] = None

    def to_dict(self):
        return {
            "severity": self.severity.value,
            "confidence": self.confidence,
            "message": self.message,
            "file_path": self.file_path,
            "line_number": self.line_number
        }


@dataclass
class CodeReviewResult:
    """Result of a code review"""
    success: bool
    issues: list[ReviewIssue]
    raw_output: str
    error_message: Optional[str] = None

    def has_critical_issues(self, confidence_threshold: float = 80.0) -> bool:
        """Check if there are high-confidence issues"""
        return any(
            issue.confidence >= confidence_threshold
            for issue in self.issues
        )

    def get_high_confidence_issues(self, threshold: float = 80.0) -> list[ReviewIssue]:
        """Get issues above confidence threshold"""
        return [
            issue for issue in self.issues
            if issue.confidence >= threshold
        ]

    def summary(self) -> str:
        """Generate a summary of the review"""
        if not self.issues:
            return "No issues found"

        errors = sum(1 for i in self.issues if i.severity == ReviewSeverity.ERROR)
        warnings = sum(1 for i in self.issues if i.severity == ReviewSeverity.WARNING)
        infos = sum(1 for i in self.issues if i.severity == ReviewSeverity.INFO)

        parts = []
        if errors:
            parts.append(f"{errors} error(s)")
        if warnings:
            parts.append(f"{warnings} warning(s)")
        if infos:
            parts.append(f"{infos} info(s)")

        return ", ".join(parts)


async def run_code_review(
    worktree_path: str,
    timeout: int = 60
) -> CodeReviewResult:
    """
    Run Claude code review on a worktree

    Args:
        worktree_path: Path to the worktree to review
        timeout: Timeout in seconds (default 60)

    Returns:
        CodeReviewResult with issues found
    """
    worktree_path_obj = Path(worktree_path)

    if not worktree_path_obj.exists():
        return CodeReviewResult(
            success=False,
            issues=[],
            raw_output="",
            error_message=f"Worktree path does not exist: {worktree_path}"
        )

    try:
        # Execute claude --print "/code-review" --output-format json
        process = await asyncio.create_subprocess_exec(
            "claude",
            "--print",
            "/code-review",
            "--output-format", "json",
            cwd=str(worktree_path_obj),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )

        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=timeout
            )
        except asyncio.TimeoutError:
            process.kill()
            await process.wait()
            return CodeReviewResult(
                success=False,
                issues=[],
                raw_output="",
                error_message=f"Code review timed out after {timeout} seconds"
            )

        raw_output = stdout.decode('utf-8') if stdout else ""
        error_output = stderr.decode('utf-8') if stderr else ""

        if process.returncode != 0:
            return CodeReviewResult(
                success=False,
                issues=[],
                raw_output=raw_output,
                error_message=f"Claude command failed: {error_output}"
            )

        # Parse the JSON output
        issues = parse_review_output(raw_output)

        return CodeReviewResult(
            success=True,
            issues=issues,
            raw_output=raw_output
        )

    except FileNotFoundError:
        return CodeReviewResult(
            success=False,
            issues=[],
            raw_output="",
            error_message="Claude CLI not found. Please ensure 'claude' command is available."
        )
    except Exception as e:
        return CodeReviewResult(
            success=False,
            issues=[],
            raw_output="",
            error_message=f"Unexpected error during code review: {str(e)}"
        )


def parse_review_output(json_output: str) -> list[ReviewIssue]:
    """
    Parse JSON output from Claude /code-review

    Args:
        json_output: JSON string from claude command

    Returns:
        List of ReviewIssue objects
    """
    if not json_output or not json_output.strip():
        return []

    try:
        data = json.loads(json_output)

        # Handle different possible JSON structures
        # Assuming format: {"issues": [...]} or direct array [...]
        if isinstance(data, dict):
            issues_data = data.get("issues", [])
        elif isinstance(data, list):
            issues_data = data
        else:
            return []

        issues = []
        for item in issues_data:
            try:
                # Map severity string to enum
                severity_str = item.get("severity", "info").lower()
                severity = ReviewSeverity(severity_str) if severity_str in ["error", "warning", "info"] else ReviewSeverity.INFO

                issue = ReviewIssue(
                    severity=severity,
                    confidence=float(item.get("confidence", 0)),
                    message=item.get("message", ""),
                    file_path=item.get("file_path"),
                    line_number=item.get("line_number")
                )
                issues.append(issue)
            except (ValueError, KeyError, TypeError) as e:
                # Skip malformed issue entries
                continue

        return issues

    except json.JSONDecodeError:
        # If JSON parsing fails, return empty list
        return []


def should_auto_fix(
    issues: list[ReviewIssue],
    confidence_threshold: float = 80.0
) -> bool:
    """
    Determine if auto-fix should be triggered

    Args:
        issues: List of review issues
        confidence_threshold: Minimum confidence to trigger auto-fix

    Returns:
        True if auto-fix should run
    """
    return any(
        issue.confidence >= confidence_threshold
        for issue in issues
    )


def filter_high_confidence_issues(
    issues: list[ReviewIssue],
    threshold: float = 80.0
) -> list[ReviewIssue]:
    """
    Filter issues by confidence threshold

    Args:
        issues: List of review issues
        threshold: Minimum confidence

    Returns:
        Filtered list of high-confidence issues
    """
    return [
        issue for issue in issues
        if issue.confidence >= threshold
    ]


def format_issues_for_context(issues: list[ReviewIssue]) -> str:
    """
    Format issues as context for coding phase

    Args:
        issues: List of review issues

    Returns:
        Formatted string for coding prompt
    """
    if not issues:
        return "No issues to fix"

    lines = ["Code review found the following issues to fix:\n"]

    for i, issue in enumerate(issues, 1):
        location = ""
        if issue.file_path:
            location = f" in {issue.file_path}"
            if issue.line_number:
                location += f":{issue.line_number}"

        lines.append(
            f"{i}. [{issue.severity.value.upper()}] "
            f"{issue.message}{location} "
            f"(confidence: {issue.confidence:.0f}%)"
        )

    return "\n".join(lines)
