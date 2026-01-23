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

        # Build code review prompt - very strict JSON format
        review_prompt = """Review git diff HEAD~1 for bugs/security issues.

OUTPUT FORMAT (STRICT - no other text allowed):
{"severity":"error|warning|info","confidence":0-100,"message":"issue description","file_path":"path","line_number":N}

One JSON object per line. No markdown. No explanations. No headers.
If no issues: {"no_issues":true}

Run: git diff HEAD~1
Then output ONLY JSON lines."""

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
        print(f"[CODE_REVIEW] stdout content: {raw_output[:2000]}")
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

    # Fallback: if no JSON issues found, try parsing as markdown
    if not issues:
        print("[CODE_REVIEW] No JSON issues found, trying markdown parser...")
        issues = _extract_issues_from_text(json_output)
        if issues:
            print(f"[CODE_REVIEW] Markdown parser found {len(issues)} issues")

    return issues


def _extract_issues_from_text(text: str) -> list[ReviewIssue]:
    """Extract issues from text - supports JSON and markdown formats"""
    import re
    issues = []

    # First try: Look for JSON-like patterns
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

    # Second try: Parse markdown-style issues if no JSON found
    if not issues:
        issues.extend(_extract_issues_from_markdown(text))

    return issues


def _extract_issues_from_markdown(text: str) -> list[ReviewIssue]:
    """Extract issues from markdown-formatted code review output"""
    import re
    issues = []

    # Detect severity from section headers or emojis
    current_severity = ReviewSeverity.INFO

    # Split into lines for processing
    lines = text.split('\n')
    i = 0

    while i < len(lines):
        line = lines[i].strip()

        # Update severity based on section headers
        lower_line = line.lower()
        if 'critical' in lower_line or '🔴' in line or 'error' in lower_line:
            current_severity = ReviewSeverity.ERROR
        elif 'medium' in lower_line or '🟡' in line or 'warning' in lower_line:
            current_severity = ReviewSeverity.WARNING
        elif 'minor' in lower_line or '🟢' in line or 'info' in lower_line:
            current_severity = ReviewSeverity.INFO

        # Look for issue titles (numbered items with bold text)
        # Pattern: "#### 1. **Issue Title**" or "1. **Issue Title**"
        issue_match = re.match(r'^#{0,4}\s*\d+\.\s*\*\*(.+?)\*\*', line)
        if issue_match:
            issue_title = issue_match.group(1).strip()

            # Look for file path in following lines
            file_path = None
            line_number = None

            # Check next few lines for file reference
            for j in range(i + 1, min(i + 5, len(lines))):
                next_line = lines[j]
                # Look for patterns like (file.py:123) or `file.py:123`
                file_match = re.search(r'[`(]([^`()]+\.\w+):(\d+)[`)]', next_line)
                if file_match:
                    file_path = file_match.group(1)
                    line_number = int(file_match.group(2))
                    break
                # Also try just filename patterns
                file_match2 = re.search(r'[`(]([^`()]+\.\w+)[`)]', next_line)
                if file_match2 and not file_path:
                    file_path = file_match2.group(1)

            # Use 85% confidence for markdown - Claude explicitly identified these
            issue = ReviewIssue(
                severity=current_severity,
                confidence=85.0,
                message=issue_title,
                file_path=file_path,
                line_number=line_number
            )
            issues.append(issue)

        i += 1

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
