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

from backend.services.claude_runner import find_claude_cli


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
        # Find Claude CLI executable
        claude_cli = find_claude_cli()
        print(f"[CODE_REVIEW] Using Claude CLI: {claude_cli}")

        # Build code review prompt
        review_prompt = """Review the recent code changes in this git worktree. Focus on:
1. Bugs and logical errors
2. Security vulnerabilities
3. Performance issues
4. Code quality problems

For each issue found, output a JSON object with this format:
{"severity": "error|warning|info", "confidence": 0-100, "message": "description", "file_path": "path/to/file", "line_number": 123}

Output ONLY valid JSON objects, one per line. If no issues are found, output: {"no_issues": true}

Start by running: git diff HEAD~1 --name-only
Then review each changed file."""

        # Execute claude with review prompt
        process = await asyncio.create_subprocess_exec(
            claude_cli,
            "--print",
            review_prompt,
            "--output-format", "json",
            "--max-turns", "5",
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

        print(f"[CODE_REVIEW] returncode: {process.returncode}")
        print(f"[CODE_REVIEW] stdout length: {len(raw_output)}")
        print(f"[CODE_REVIEW] stderr: {error_output[:200] if error_output else '(empty)'}")

        if process.returncode != 0:
            return CodeReviewResult(
                success=False,
                issues=[],
                raw_output=raw_output,
                error_message=f"Claude command failed (code {process.returncode}): {error_output}"
            )

        # Parse the JSON output - look for issue objects in the result
        issues = parse_review_output(raw_output)
        print(f"[CODE_REVIEW] parsed {len(issues)} issues")

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
    Parse JSON output from Claude code review

    Args:
        json_output: JSON string stream from claude command

    Returns:
        List of ReviewIssue objects
    """
    if not json_output or not json_output.strip():
        return []

    issues = []

    # Parse each line as potential JSON
    for line in json_output.split('\n'):
        line = line.strip()
        if not line:
            continue

        try:
            data = json.loads(line)

            # Skip non-dict entries
            if not isinstance(data, dict):
                continue

            # Skip Claude system messages (type: result, assistant, etc.)
            if data.get("type") in ["result", "assistant", "user", "system"]:
                # But check if result contains issues in the text
                if data.get("type") == "result" and "result" in data:
                    result_text = data.get("result", "")
                    if isinstance(result_text, str):
                        # Try to extract JSON from result text
                        issues.extend(_extract_issues_from_text(result_text))
                continue

            # Skip "no_issues" marker
            if data.get("no_issues"):
                continue

            # Check if this looks like an issue object
            if "severity" in data and "message" in data:
                try:
                    severity_str = data.get("severity", "info").lower()
                    if severity_str not in ["error", "warning", "info"]:
                        severity_str = "info"

                    issue = ReviewIssue(
                        severity=ReviewSeverity(severity_str),
                        confidence=float(data.get("confidence", 50)),
                        message=data.get("message", ""),
                        file_path=data.get("file_path"),
                        line_number=data.get("line_number")
                    )
                    issues.append(issue)
                except (ValueError, KeyError, TypeError):
                    continue

        except json.JSONDecodeError:
            continue

    return issues


def _extract_issues_from_text(text: str) -> list[ReviewIssue]:
    """Extract issue JSON objects embedded in text"""
    issues = []

    # Look for JSON-like patterns in the text
    import re
    json_pattern = r'\{[^{}]*"severity"[^{}]*"message"[^{}]*\}'
    matches = re.findall(json_pattern, text)

    for match in matches:
        try:
            data = json.loads(match)
            severity_str = data.get("severity", "info").lower()
            if severity_str not in ["error", "warning", "info"]:
                severity_str = "info"

            issue = ReviewIssue(
                severity=ReviewSeverity(severity_str),
                confidence=float(data.get("confidence", 50)),
                message=data.get("message", ""),
                file_path=data.get("file_path"),
                line_number=data.get("line_number")
            )
            issues.append(issue)
        except (json.JSONDecodeError, ValueError, KeyError, TypeError):
            continue

    return issues


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
