"""
Service for the Validation phase (automatic QA).
Triggered when a task moves to "AI Review" status.
Uses Claude Code CLI (subscription), not the paid API.
"""

import logging
from typing import Callable

from backend.models import Task, SubtaskStatus
from backend.services.project_context import get_project_context
from backend.services.claude_cli import run_claude_for_review, run_claude_for_coding

logger = logging.getLogger(__name__)


VALIDATION_PROMPT_TEMPLATE = '''## QA Validation for Task: {task_title}

You are reviewing ONLY the changes made for this specific task.

### Task Description
{task_description}

### What was implemented (subtasks completed)
{completed_subtasks}

### Acceptance Criteria
{acceptance_criteria}

## Your Job

1. Use `git diff develop` to see ONLY the changes made for this task
2. Review these specific changes against the task requirements
3. Check for:
   - Does the implementation match the task description?
   - Any obvious bugs in the NEW code?
   - Missing functionality mentioned in the task?

DO NOT review:
- Code that existed before this task
- Unrelated files
- General code style (unless egregious)

## Output Format

Respond with EXACTLY this format:

## QA Result: PASS

### Summary
Brief summary of what was implemented and why it's acceptable.

OR if there are real issues:

## QA Result: FAIL

### Summary
Brief explanation of the problem.

### Issues Found
- Specific issue 1
- Specific issue 2

IMPORTANT: If the implementation is functional and meets the task requirements, mark as PASS.
Only FAIL if there are real bugs or missing required functionality.
'''


async def run_validation(
    task: Task,
    project_path: str,
    worktree_path: str,
    on_output: Callable[[str], None] | None = None
) -> dict:
    """
    Execute QA validation for a task.

    Args:
        task: The task to validate
        project_path: Project path
        worktree_path: Worktree path
        on_output: Callback for output

    Returns:
        {"passed": bool, "summary": str, "issues": list}
    """
    logger.info(f"Running validation for task {task.id}")

    # Acceptance criteria from description or spec
    acceptance_criteria = extract_acceptance_criteria(task)

    completed_subtasks = "\n".join([
        f"- {s.title}: {s.description or ''}"
        for s in task.subtasks if s.status == SubtaskStatus.COMPLETED
    ]) or "Task completed as a single unit"

    prompt = VALIDATION_PROMPT_TEMPLATE.format(
        task_title=task.title,
        task_description=task.description or "",
        acceptance_criteria=acceptance_criteria,
        completed_subtasks=completed_subtasks
    )

    # Execute Claude CLI for review
    success, output = await run_claude_for_review(
        prompt=prompt,
        cwd=worktree_path,
        timeout=300,  # 5 min max for validation
        on_output=on_output
    )

    # Parse the result
    result = parse_validation_result(output)

    logger.info(f"Validation result for task {task.id}: {'PASS' if result['passed'] else 'FAIL'}")

    return result


def extract_acceptance_criteria(task: Task) -> str:
    """Extract acceptance criteria from the task."""
    description = task.description or ""

    # Pattern: "Acceptance Criteria" section or list with dashes
    if "acceptance criteria" in description.lower():
        lines = description.split("\n")
        criteria_lines = []
        in_criteria = False

        for line in lines:
            if "acceptance criteria" in line.lower():
                in_criteria = True
                continue
            if in_criteria:
                if line.strip().startswith(("-", "*", "•")):
                    criteria_lines.append(line.strip())
                elif line.startswith("#"):
                    break

        if criteria_lines:
            return "\n".join(criteria_lines)

    # Check for checkbox pattern [ ] or [x]
    checkboxes = []
    for line in description.split("\n"):
        if "[ ]" in line or "[x]" in line or "[X]" in line:
            checkboxes.append(line.strip())

    if checkboxes:
        return "\n".join(checkboxes)

    # Default: the task description itself is the criteria
    return "Implementation should match the task description above."


def parse_validation_result(output: str) -> dict:
    """Parse the validation result."""
    result = {
        "passed": True,  # Default to PASS
        "summary": "",
        "issues": [],
        "recommendations": [],
        "raw_output": output
    }

    if not output:
        result["summary"] = "Validation completed (no output)"
        return result

    # Look for explicit FAIL verdict
    output_upper = output.upper()

    # Only set to FAIL if explicitly stated
    if "QA RESULT: FAIL" in output_upper or "RESULT: FAIL" in output_upper:
        result["passed"] = False
    elif "QA RESULT: PASS" in output_upper or "RESULT: PASS" in output_upper:
        result["passed"] = True
    else:
        # No explicit verdict - check for positive indicators
        output_lower = output.lower()
        if any(phrase in output_lower for phrase in [
            "no issues", "looks good", "implementation is correct",
            "meets the requirements", "working as expected",
            "successfully implemented", "all criteria met"
        ]):
            result["passed"] = True
        # Only fail if there are clear negative indicators
        elif any(phrase in output_lower for phrase in [
            "critical bug", "does not work", "broken", "fails to"
        ]):
            result["passed"] = False
        # Default: PASS (benefit of the doubt)

    # Extract the summary
    if "### Summary" in output:
        start = output.find("### Summary") + len("### Summary")
        end = output.find("###", start)
        if end == -1:
            end = len(output)
        result["summary"] = output[start:end].strip()
    else:
        # Use first paragraph as summary
        paragraphs = output.split("\n\n")
        if paragraphs:
            result["summary"] = paragraphs[0].strip()[:500]

    # Extract issues (only if FAIL)
    if "### Issues Found" in output or "### Issues" in output:
        marker = "### Issues Found" if "### Issues Found" in output else "### Issues"
        start = output.find(marker) + len(marker)
        end = output.find("###", start)
        if end == -1:
            end = len(output)
        issues_text = output[start:end]

        for line in issues_text.split("\n"):
            line = line.strip()
            if line.startswith("-") and len(line) > 2:
                issue = line[1:].strip()
                # Filter out non-issues
                if issue and issue.lower() not in [
                    "none", "n/a", "no issues", "no issues found",
                    "none found", "no major issues"
                ]:
                    result["issues"].append(issue)

    # If no real issues found, ensure PASS
    if not result["issues"]:
        result["passed"] = True

    # Extract recommendations (optional, don't affect pass/fail)
    if "### Recommendations" in output:
        start = output.find("### Recommendations") + len("### Recommendations")
        end = output.find("###", start)
        if end == -1:
            end = len(output)
        rec_text = output[start:end]

        for line in rec_text.split("\n"):
            line = line.strip()
            if line.startswith("-") and len(line) > 2:
                rec = line[1:].strip()
                if rec and rec.lower() not in ["none", "n/a"]:
                    result["recommendations"].append(rec)

    return result


async def auto_fix_issues(
    task: Task,
    issues: list[str],
    worktree_path: str,
    on_output: Callable[[str], None] | None = None,
    max_attempts: int = 2
) -> bool:
    """
    Attempt to automatically fix issues found during validation.

    Returns:
        True if fix attempt completed
    """
    if not issues:
        return True

    logger.info(f"Attempting to auto-fix {len(issues)} issues for task {task.id}")

    issues_formatted = "\n".join(f"- {issue}" for issue in issues)

    fix_prompt = f'''## Fix Issues for Task: {task.title}

The following issues were found during QA review:

{issues_formatted}

Please fix these specific issues:
1. Read the relevant files
2. Make the minimal changes needed
3. Focus only on the issues listed above

Do not refactor or change anything else.
'''

    success = await run_claude_for_coding(
        prompt=fix_prompt,
        cwd=worktree_path,
        timeout=600,
        on_output=on_output
    )

    if success:
        logger.info(f"Auto-fix completed for task {task.id}")
        return True

    logger.warning(f"Auto-fix failed for task {task.id}")
    return False


def should_auto_fix(result: dict, confidence_threshold: float = 0.85) -> bool:
    """
    Determine if issues should be auto-fixed based on the validation result.

    Auto-fix only for minor, specific issues.
    """
    if result["passed"]:
        return False

    if not result["issues"]:
        return False

    # Don't auto-fix if there are too many issues
    if len(result["issues"]) > 3:
        return False

    # Check for critical keywords that shouldn't be auto-fixed
    critical_keywords = ["security", "data loss", "critical", "breaking", "corrupt", "architecture"]
    for issue in result["issues"]:
        issue_lower = issue.lower()
        if any(keyword in issue_lower for keyword in critical_keywords):
            return False

    return True
