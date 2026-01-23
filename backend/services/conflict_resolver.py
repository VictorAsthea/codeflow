import asyncio
import logging
from typing import Callable, Any, Optional

from backend.services.git_service import (
    start_merge_with_develop,
    parse_conflict_regions,
    complete_merge,
    push_with_lease,
    abort_merge
)
from backend.services.claude_runner import run_claude_with_streaming

logger = logging.getLogger(__name__)


def _build_conflict_resolution_prompt(
    conflicting_files: list[str],
    file_conflicts: dict[str, list[dict]]
) -> str:
    """
    Build a prompt for Claude to resolve merge conflicts.

    Args:
        conflicting_files: List of file paths with conflicts
        file_conflicts: Dict mapping file paths to their conflict regions

    Returns:
        Formatted prompt string
    """
    prompt_parts = [
        "You are resolving merge conflicts between the current branch and develop.",
        "The conflicts have already been created by git merge. Your job is to resolve them.",
        "",
        "## Conflicting Files:",
        ""
    ]

    for file_path in conflicting_files:
        regions = file_conflicts.get(file_path, [])
        prompt_parts.append(f"### {file_path}")
        prompt_parts.append(f"Number of conflict regions: {len(regions)}")
        prompt_parts.append("")

        for i, region in enumerate(regions, 1):
            prompt_parts.append(f"**Conflict {i} (lines {region['start_line']}-{region['end_line']}):**")
            prompt_parts.append("")
            prompt_parts.append("Current branch (ours):")
            prompt_parts.append("```")
            prompt_parts.append(region['ours'])
            prompt_parts.append("```")
            prompt_parts.append("")
            prompt_parts.append("Develop branch (theirs):")
            prompt_parts.append("```")
            prompt_parts.append(region['theirs'])
            prompt_parts.append("```")
            prompt_parts.append("")

    prompt_parts.extend([
        "## Instructions:",
        "1. Read each file with conflicts using the Read tool",
        "2. For each conflict region (marked with <<<<<<<, =======, >>>>>>>):",
        "   - Understand what both versions are trying to do",
        "   - Choose the best resolution that preserves functionality from both branches",
        "   - If both changes are needed, merge them intelligently",
        "   - If the changes conflict, prefer the current branch changes but incorporate develop's intent",
        "3. Use the Edit tool to resolve each conflict",
        "4. Remove ALL conflict markers (<<<<<<<, =======, >>>>>>>)",
        "5. Ensure the resulting code is syntactically correct and functional",
        "",
        "IMPORTANT: Do NOT leave any conflict markers in the files.",
        "",
        "Resolve all conflicts in the files listed above."
    ])

    return "\n".join(prompt_parts)


async def resolve_conflicts(
    task_id: str,
    worktree_path: str,
    log_callback: Optional[Callable[[str], Any]] = None
) -> dict:
    """
    Resolve merge conflicts with develop branch using Claude.

    This function:
    1. Fetches origin/develop and attempts to merge
    2. If there are conflicts, uses Claude to resolve them
    3. Commits the merge and pushes

    Args:
        task_id: Task ID for tracking
        worktree_path: Path to the worktree
        log_callback: Optional callback for streaming logs

    Returns:
        dict with keys:
            - success: bool
            - resolved_files: list[str]
            - conflict_count: int
            - commit_sha: str (if successful)
            - error: str (if failed)
    """
    async def log(message: str):
        if log_callback:
            await log_callback(message)
        logger.info(message)

    await log("[CONFLICT-RESOLVER] Starting conflict resolution with develop...")

    try:
        # Step 1: Start the merge with develop
        await log("[CONFLICT-RESOLVER] Fetching and merging origin/develop...")
        merge_result = await start_merge_with_develop(worktree_path)

        if not merge_result.get("success"):
            await log(f"[CONFLICT-RESOLVER] Failed to start merge: {merge_result.get('error')}")
            return {
                "success": False,
                "resolved_files": [],
                "conflict_count": 0,
                "error": merge_result.get("error", "Failed to start merge")
            }

        if not merge_result.get("has_conflicts"):
            # No conflicts, just complete the merge
            await log("[CONFLICT-RESOLVER] No conflicts found, completing merge...")
            commit_result = await complete_merge(worktree_path, "chore: merge develop (no conflicts)")

            if commit_result.get("success"):
                push_result = await push_with_lease(worktree_path)
                if push_result.get("success"):
                    await log(f"[CONFLICT-RESOLVER] Merge completed: {commit_result['commit_sha'][:8]}")
                    return {
                        "success": True,
                        "resolved_files": [],
                        "conflict_count": 0,
                        "commit_sha": commit_result["commit_sha"]
                    }
                else:
                    await log(f"[CONFLICT-RESOLVER] Push failed: {push_result.get('error')}")
                    return {
                        "success": False,
                        "resolved_files": [],
                        "conflict_count": 0,
                        "error": push_result.get("error", "Push failed")
                    }

            return commit_result

        # Step 2: Parse conflicts for each file
        conflicting_files = merge_result.get("conflicting_files", [])
        await log(f"[CONFLICT-RESOLVER] Found conflicts in {len(conflicting_files)} files:")
        for f in conflicting_files:
            await log(f"  - {f}")

        file_conflicts = {}
        total_conflict_count = 0

        for file_path in conflicting_files:
            regions = await parse_conflict_regions(file_path, worktree_path)
            file_conflicts[file_path] = regions
            total_conflict_count += len(regions)
            await log(f"[CONFLICT-RESOLVER] {file_path}: {len(regions)} conflict region(s)")

        # Step 3: Build prompt and run Claude
        await log(f"[CONFLICT-RESOLVER] Total conflicts: {total_conflict_count}")
        await log("[CONFLICT-RESOLVER] Running Claude to resolve conflicts...")

        prompt = _build_conflict_resolution_prompt(conflicting_files, file_conflicts)

        result = await run_claude_with_streaming(
            prompt=prompt,
            working_dir=worktree_path,
            allowed_tools=["Read", "Edit", "Write", "Glob", "Grep"],
            max_turns=30,  # More turns for complex conflicts
            log_callback=log_callback
        )

        if result.get("exit_code", 1) != 0:
            await log(f"[CONFLICT-RESOLVER] Claude exited with code {result.get('exit_code')}")
            # Continue anyway, Claude might have resolved some conflicts

        # Step 4: Verify conflicts are resolved (no conflict markers remain)
        unresolved = []
        for file_path in conflicting_files:
            regions = await parse_conflict_regions(file_path, worktree_path)
            if regions:
                unresolved.append(file_path)

        if unresolved:
            await log(f"[CONFLICT-RESOLVER] WARNING: Unresolved conflicts remain in: {', '.join(unresolved)}")
            # Abort the merge since we couldn't fully resolve
            await abort_merge(worktree_path)
            return {
                "success": False,
                "resolved_files": [f for f in conflicting_files if f not in unresolved],
                "conflict_count": total_conflict_count,
                "error": f"Conflicts remain in: {', '.join(unresolved)}"
            }

        # Step 5: Complete the merge
        await log("[CONFLICT-RESOLVER] All conflicts resolved, committing merge...")
        commit_result = await complete_merge(
            worktree_path,
            f"fix: merge develop and resolve {total_conflict_count} conflict(s)"
        )

        if not commit_result.get("success"):
            await log(f"[CONFLICT-RESOLVER] Failed to commit: {commit_result.get('error')}")
            await abort_merge(worktree_path)
            return {
                "success": False,
                "resolved_files": conflicting_files,
                "conflict_count": total_conflict_count,
                "error": commit_result.get("error", "Failed to commit merge")
            }

        # Step 6: Push
        await log("[CONFLICT-RESOLVER] Pushing changes...")
        push_result = await push_with_lease(worktree_path)

        if not push_result.get("success"):
            await log(f"[CONFLICT-RESOLVER] Push failed: {push_result.get('error')}")
            return {
                "success": False,
                "resolved_files": conflicting_files,
                "conflict_count": total_conflict_count,
                "commit_sha": commit_result.get("commit_sha"),
                "error": push_result.get("error", "Push failed")
            }

        await log(f"[CONFLICT-RESOLVER] Successfully resolved and pushed: {commit_result['commit_sha'][:8]}")
        return {
            "success": True,
            "resolved_files": conflicting_files,
            "conflict_count": total_conflict_count,
            "commit_sha": commit_result["commit_sha"]
        }

    except Exception as e:
        error_msg = f"Error resolving conflicts: {e}"
        await log(f"[CONFLICT-RESOLVER] {error_msg}")
        logger.exception(error_msg)

        # Try to abort the merge
        try:
            await abort_merge(worktree_path)
        except:
            pass

        return {
            "success": False,
            "resolved_files": [],
            "conflict_count": 0,
            "error": str(e)
        }


async def check_and_warn_conflicts(worktree_path: str) -> dict:
    """
    Check for conflicts without merging. Use this before creating a PR
    to warn the user about potential conflicts.

    Returns:
        dict with keys:
            - has_conflicts: bool
            - conflicting_files: list[str]
            - behind_commits: int
    """
    from backend.services.git_service import check_conflicts_with_develop

    return await check_conflicts_with_develop(worktree_path)
