import asyncio
import subprocess
import logging
import re
from typing import Optional

logger = logging.getLogger(__name__)


async def check_conflicts_with_develop(worktree_path: str) -> dict:
    """
    Check if current branch has conflicts with develop branch.

    Returns:
        dict with keys:
            - has_conflicts: bool
            - conflicting_files: list[str]
            - behind_commits: int (how many commits behind develop)
    """
    try:
        # Fetch latest from origin
        await asyncio.to_thread(
            subprocess.run,
            ["git", "fetch", "origin", "develop"],
            cwd=worktree_path,
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='replace',
            check=True
        )

        # Get merge base
        merge_base_result = await asyncio.to_thread(
            subprocess.run,
            ["git", "merge-base", "HEAD", "origin/develop"],
            cwd=worktree_path,
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='replace'
        )

        if merge_base_result.returncode != 0:
            logger.warning(f"Could not find merge base: {merge_base_result.stderr}")
            return {"has_conflicts": False, "conflicting_files": [], "behind_commits": 0}

        merge_base = merge_base_result.stdout.strip()

        # Count commits behind develop
        behind_result = await asyncio.to_thread(
            subprocess.run,
            ["git", "rev-list", "--count", f"HEAD..origin/develop"],
            cwd=worktree_path,
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='replace'
        )

        behind_commits = 0
        if behind_result.returncode == 0:
            behind_commits = int(behind_result.stdout.strip())

        # Use merge-tree to check for conflicts without actually merging
        # This requires git 2.38+ for --write-tree option
        # Fallback to merge --no-commit for older git versions
        merge_tree_result = await asyncio.to_thread(
            subprocess.run,
            ["git", "merge-tree", merge_base, "HEAD", "origin/develop"],
            cwd=worktree_path,
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='replace'
        )

        output = merge_tree_result.stdout

        # Parse merge-tree output for conflicts
        conflicting_files = []
        has_conflicts = False

        # Look for conflict markers in merge-tree output
        # Format: "<<<<<<<<" or conflict sections
        if "<<<<<<" in output or merge_tree_result.returncode != 0:
            has_conflicts = True

            # Extract file paths from conflict markers
            # The merge-tree output format varies, so we parse carefully
            lines = output.split('\n')
            current_file = None

            for line in lines:
                # Look for file headers in diff-like output
                if line.startswith('+++ ') or line.startswith('--- '):
                    file_match = re.match(r'^[+-]{3} [ab]/(.+)$', line)
                    if file_match:
                        current_file = file_match.group(1)
                        if current_file and current_file not in conflicting_files:
                            conflicting_files.append(current_file)

        # If merge-tree didn't give us file names, try a dry-run merge
        if has_conflicts and not conflicting_files:
            conflicting_files = await _get_conflict_files_from_dry_merge(worktree_path)

        return {
            "has_conflicts": has_conflicts,
            "conflicting_files": conflicting_files,
            "behind_commits": behind_commits
        }

    except subprocess.CalledProcessError as e:
        logger.error(f"Git command failed: {e.stderr}")
        return {"has_conflicts": False, "conflicting_files": [], "behind_commits": 0, "error": str(e)}
    except Exception as e:
        logger.error(f"Error checking conflicts: {e}")
        return {"has_conflicts": False, "conflicting_files": [], "behind_commits": 0, "error": str(e)}


async def _get_conflict_files_from_dry_merge(worktree_path: str) -> list[str]:
    """
    Attempt a merge to get conflict file list, then abort.
    This is a fallback if merge-tree doesn't provide file names.
    """
    conflicting_files = []

    try:
        # Try to merge (this will fail if there are conflicts)
        merge_result = await asyncio.to_thread(
            subprocess.run,
            ["git", "merge", "origin/develop", "--no-commit", "--no-ff"],
            cwd=worktree_path,
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='replace'
        )

        if merge_result.returncode != 0:
            # Parse stderr for conflict file names
            output = merge_result.stdout + merge_result.stderr

            # Look for "CONFLICT (content): Merge conflict in <file>"
            conflict_pattern = re.compile(r'CONFLICT.*?: (?:Merge conflict in|.* -> )(.+)')
            for line in output.split('\n'):
                match = conflict_pattern.search(line)
                if match:
                    file_path = match.group(1).strip()
                    if file_path and file_path not in conflicting_files:
                        conflicting_files.append(file_path)

        # Always abort the merge attempt
        await asyncio.to_thread(
            subprocess.run,
            ["git", "merge", "--abort"],
            cwd=worktree_path,
            capture_output=True
        )

    except Exception as e:
        logger.error(f"Error in dry merge: {e}")
        # Try to abort anyway
        try:
            await asyncio.to_thread(
                subprocess.run,
                ["git", "merge", "--abort"],
                cwd=worktree_path,
                capture_output=True
            )
        except:
            pass

    return conflicting_files


async def parse_conflict_regions(file_path: str, worktree_path: str) -> list[dict]:
    """
    Parse conflict markers in a file and return conflict regions.

    Returns:
        list of dicts with keys:
            - start_line: int
            - end_line: int
            - ours: str (content from current branch)
            - theirs: str (content from develop)
            - original: str (full conflict block)
    """
    full_path = f"{worktree_path}/{file_path}"

    try:
        with open(full_path, 'r', encoding='utf-8') as f:
            content = f.read()
    except FileNotFoundError:
        logger.error(f"File not found: {full_path}")
        return []
    except Exception as e:
        logger.error(f"Error reading file {full_path}: {e}")
        return []

    lines = content.split('\n')
    regions = []

    i = 0
    while i < len(lines):
        if lines[i].startswith('<<<<<<<'):
            region = {
                'start_line': i + 1,  # 1-indexed
                'ours': [],
                'theirs': [],
                'original': [lines[i]]
            }

            i += 1
            in_ours = True

            while i < len(lines):
                region['original'].append(lines[i])

                if lines[i].startswith('======='):
                    in_ours = False
                elif lines[i].startswith('>>>>>>>'):
                    region['end_line'] = i + 1  # 1-indexed
                    break
                elif in_ours:
                    region['ours'].append(lines[i])
                else:
                    region['theirs'].append(lines[i])

                i += 1

            region['ours'] = '\n'.join(region['ours'])
            region['theirs'] = '\n'.join(region['theirs'])
            region['original'] = '\n'.join(region['original'])
            regions.append(region)

        i += 1

    return regions


async def get_current_branch(worktree_path: str) -> Optional[str]:
    """Get the current branch name in the worktree."""
    try:
        result = await asyncio.to_thread(
            subprocess.run,
            ["git", "branch", "--show-current"],
            cwd=worktree_path,
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='replace',
            check=True
        )
        return result.stdout.strip()
    except Exception as e:
        logger.error(f"Error getting current branch: {e}")
        return None


async def start_merge_with_develop(worktree_path: str) -> dict:
    """
    Start a merge with origin/develop. This will create conflict markers
    in files if there are conflicts.

    Returns:
        dict with keys:
            - success: bool
            - has_conflicts: bool
            - conflicting_files: list[str]
    """
    try:
        # Fetch latest
        await asyncio.to_thread(
            subprocess.run,
            ["git", "fetch", "origin", "develop"],
            cwd=worktree_path,
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='replace',
            check=True
        )

        # Attempt merge
        merge_result = await asyncio.to_thread(
            subprocess.run,
            ["git", "merge", "origin/develop", "--no-commit"],
            cwd=worktree_path,
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='replace'
        )

        if merge_result.returncode == 0:
            return {
                "success": True,
                "has_conflicts": False,
                "conflicting_files": []
            }

        # Parse conflicts
        conflicting_files = []
        output = merge_result.stdout + merge_result.stderr

        conflict_pattern = re.compile(r'CONFLICT.*?: (?:Merge conflict in|.* -> )(.+)')
        for line in output.split('\n'):
            match = conflict_pattern.search(line)
            if match:
                file_path = match.group(1).strip()
                if file_path and file_path not in conflicting_files:
                    conflicting_files.append(file_path)

        return {
            "success": True,
            "has_conflicts": True,
            "conflicting_files": conflicting_files
        }

    except subprocess.CalledProcessError as e:
        logger.error(f"Merge failed: {e.stderr}")
        return {
            "success": False,
            "has_conflicts": False,
            "conflicting_files": [],
            "error": str(e)
        }


async def complete_merge(worktree_path: str, commit_message: str = "fix: merge develop and resolve conflicts") -> dict:
    """
    Complete a merge by staging all changes and committing.

    Returns:
        dict with keys:
            - success: bool
            - commit_sha: str (if successful)
    """
    try:
        # Stage all changes
        await asyncio.to_thread(
            subprocess.run,
            ["git", "add", "."],
            cwd=worktree_path,
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='replace',
            check=True
        )

        # Commit the merge
        commit_result = await asyncio.to_thread(
            subprocess.run,
            ["git", "commit", "-m", commit_message],
            cwd=worktree_path,
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='replace',
            check=True
        )

        # Get the commit SHA
        sha_result = await asyncio.to_thread(
            subprocess.run,
            ["git", "rev-parse", "HEAD"],
            cwd=worktree_path,
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='replace',
            check=True
        )

        return {
            "success": True,
            "commit_sha": sha_result.stdout.strip()
        }

    except subprocess.CalledProcessError as e:
        logger.error(f"Failed to complete merge: {e.stderr}")
        return {
            "success": False,
            "error": str(e)
        }


async def push_with_lease(worktree_path: str) -> dict:
    """
    Push changes using --force-with-lease for safety.

    Returns:
        dict with keys:
            - success: bool
            - error: str (if failed)
    """
    try:
        await asyncio.to_thread(
            subprocess.run,
            ["git", "push", "--force-with-lease"],
            cwd=worktree_path,
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='replace',
            check=True
        )

        return {"success": True}

    except subprocess.CalledProcessError as e:
        logger.error(f"Push failed: {e.stderr}")
        return {
            "success": False,
            "error": e.stderr.strip() if e.stderr else str(e)
        }


async def abort_merge(worktree_path: str) -> dict:
    """Abort an in-progress merge."""
    try:
        await asyncio.to_thread(
            subprocess.run,
            ["git", "merge", "--abort"],
            cwd=worktree_path,
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='replace',
            check=True
        )
        return {"success": True}
    except subprocess.CalledProcessError as e:
        logger.error(f"Failed to abort merge: {e.stderr}")
        return {"success": False, "error": str(e)}
