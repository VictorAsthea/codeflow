import asyncio
import subprocess
import logging
import re
from typing import Callable, Any, Optional
from datetime import datetime

from backend.services.github_service import get_comments_by_ids
from backend.services.claude_runner import run_claude_with_streaming

# Use Haiku for fast PR fixes
PR_FIX_MODEL = "claude-haiku-4-20250514"

logger = logging.getLogger(__name__)


def _build_fix_prompt(comments: list[dict]) -> str:
    """
    Build a concise prompt for Claude to fix PR review comments.
    Optimized for speed - only includes essential context.
    """
    prompt_parts = ["Fix these PR review comments. Make minimal changes.\n"]

    # Group comments by file
    comments_by_file = {}
    for comment in comments:
        path = comment.get("path", "unknown")
        if path not in comments_by_file:
            comments_by_file[path] = []
        comments_by_file[path].append(comment)

    for file_path, file_comments in comments_by_file.items():
        prompt_parts.append(f"## {file_path}")

        for comment in file_comments:
            line = comment.get("line", "?")
            body = comment.get("body", "")
            diff_hunk = comment.get("diff_hunk", "")

            # Clean body - remove markdown images
            clean_body = re.sub(r'!\[[^\]]*\]\([^)]*\)', '', body).strip()

            prompt_parts.append(f"Line {line}: {clean_body}")

            if diff_hunk:
                # Only include relevant lines from diff (last 10 lines max)
                hunk_lines = diff_hunk.strip().split('\n')[-10:]
                prompt_parts.append("```diff")
                prompt_parts.append('\n'.join(hunk_lines))
                prompt_parts.append("```")

    prompt_parts.append("\nUse Edit tool. No new files. Minimal changes only.")

    return "\n".join(prompt_parts)


async def _read_file_contents(file_paths: list[str], worktree_path: str) -> dict[str, str]:
    """Read contents of specified files."""
    contents = {}
    for path in file_paths:
        full_path = f"{worktree_path}/{path}"
        try:
            with open(full_path, 'r', encoding='utf-8') as f:
                contents[path] = f.read()
        except FileNotFoundError:
            logger.warning(f"File not found: {full_path}")
        except Exception as e:
            logger.error(f"Error reading {full_path}: {e}")
    return contents


async def _commit_and_push(worktree_path: str, message: str) -> dict:
    """Stage all changes, commit, and push."""
    try:
        # Check if there are changes to commit
        status_result = await asyncio.to_thread(
            subprocess.run,
            ["git", "status", "--porcelain"],
            cwd=worktree_path,
            capture_output=True,
            text=True,
            check=True
        )

        if not status_result.stdout.strip():
            return {"success": True, "commit_sha": None, "message": "No changes to commit"}

        # Stage all changes
        await asyncio.to_thread(
            subprocess.run,
            ["git", "add", "."],
            cwd=worktree_path,
            capture_output=True,
            text=True,
            check=True
        )

        # Commit
        await asyncio.to_thread(
            subprocess.run,
            ["git", "commit", "-m", message],
            cwd=worktree_path,
            capture_output=True,
            text=True,
            check=True
        )

        # Get commit SHA
        sha_result = await asyncio.to_thread(
            subprocess.run,
            ["git", "rev-parse", "HEAD"],
            cwd=worktree_path,
            capture_output=True,
            text=True,
            check=True
        )
        commit_sha = sha_result.stdout.strip()

        # Push
        await asyncio.to_thread(
            subprocess.run,
            ["git", "push"],
            cwd=worktree_path,
            capture_output=True,
            text=True,
            check=True
        )

        return {"success": True, "commit_sha": commit_sha}

    except subprocess.CalledProcessError as e:
        logger.error(f"Git operation failed: {e.stderr}")
        return {"success": False, "error": e.stderr.strip() if e.stderr else str(e)}


async def fix_pr_comments(
    task_id: str,
    comment_ids: list[int],
    pr_number: int,
    worktree_path: str,
    project_path: str,
    log_callback: Optional[Callable[[str], Any]] = None
) -> dict:
    """
    Fix PR review comments using Claude.

    Args:
        task_id: Task ID for tracking
        comment_ids: List of comment IDs to fix
        pr_number: PR number
        worktree_path: Path to the worktree
        project_path: Path to the main project (for gh CLI)
        log_callback: Optional callback for streaming logs

    Returns:
        dict with keys:
            - success: bool
            - fixed_count: int
            - commit_sha: str (if changes were made)
            - error: str (if failed)
    """
    async def log(message: str):
        if log_callback:
            await log_callback(message)
        logger.info(message)

    await log(f"[PR-FIXER] Starting to fix {len(comment_ids)} comments...")

    try:
        # Fetch the comments
        await log("[PR-FIXER] Fetching comment details...")
        comments = await get_comments_by_ids(comment_ids, pr_number, project_path)

        if not comments:
            await log("[PR-FIXER] No comments found with the provided IDs")
            return {"success": False, "fixed_count": 0, "error": "No comments found"}

        await log(f"[PR-FIXER] Fixing {len(comments)} comments...")

        # Build concise prompt (no file reading needed - Claude will read if needed)
        prompt = _build_fix_prompt(comments)

        # Run Claude with Haiku for speed (max 10 turns)
        result = await run_claude_with_streaming(
            prompt=prompt,
            working_dir=worktree_path,
            model=PR_FIX_MODEL,
            allowed_tools=["Read", "Edit", "Glob"],
            max_turns=10,
            log_callback=log_callback
        )

        if result.get("exit_code", 1) != 0:
            await log(f"[PR-FIXER] Claude exited with code {result.get('exit_code')}")
            # Continue anyway, Claude might have made partial fixes

        # Commit and push the changes
        await log("[PR-FIXER] Committing and pushing changes...")
        commit_result = await _commit_and_push(
            worktree_path,
            f"fix: address {len(comments)} PR review comment(s)"
        )

        if commit_result.get("success"):
            if commit_result.get("commit_sha"):
                await log(f"[PR-FIXER] Successfully pushed commit: {commit_result['commit_sha'][:8]}")
                return {
                    "success": True,
                    "fixed_count": len(comments),
                    "commit_sha": commit_result["commit_sha"]
                }
            else:
                await log("[PR-FIXER] No changes were made by Claude")
                return {
                    "success": True,
                    "fixed_count": 0,
                    "message": "No changes needed"
                }
        else:
            await log(f"[PR-FIXER] Failed to commit/push: {commit_result.get('error')}")
            return {
                "success": False,
                "fixed_count": 0,
                "error": commit_result.get("error", "Failed to commit changes")
            }

    except Exception as e:
        error_msg = f"Error fixing PR comments: {e}"
        await log(f"[PR-FIXER] {error_msg}")
        logger.exception(error_msg)
        return {"success": False, "fixed_count": 0, "error": str(e)}


async def fix_all_bot_comments(
    task_id: str,
    pr_number: int,
    worktree_path: str,
    project_path: str,
    log_callback: Optional[Callable[[str], Any]] = None
) -> dict:
    """
    Fix all comments from bot reviewers (CodeRabbit, Gemini, etc.).

    This is a convenience function that fetches all bot comments and fixes them.
    """
    from backend.services.github_service import get_all_pr_reviews, BOT_AUTHORS

    async def log(message: str):
        if log_callback:
            await log_callback(message)
        logger.info(message)

    await log("[PR-FIXER] Fetching all bot comments...")

    reviews = await get_all_pr_reviews(pr_number, project_path, include_bots_only=True)
    bot_comments = reviews.get("bot_comments", [])

    if not bot_comments:
        await log("[PR-FIXER] No bot comments found to fix")
        return {"success": True, "fixed_count": 0, "message": "No bot comments found"}

    comment_ids = [c.get("id") for c in bot_comments if c.get("id")]
    await log(f"[PR-FIXER] Found {len(comment_ids)} bot comments to fix")

    return await fix_pr_comments(
        task_id, comment_ids, pr_number, worktree_path, project_path, log_callback
    )
