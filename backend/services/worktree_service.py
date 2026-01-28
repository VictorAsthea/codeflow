"""
Worktree management service for listing, removing, and getting stats on git worktrees.
"""
import asyncio
import subprocess
import logging
import re
import shutil
import fnmatch
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


async def list_worktrees(project_path: str) -> list[dict]:
    """
    List all git worktrees with their stats.

    Returns:
        list of dicts with keys:
            - path: str (worktree path)
            - branch: str (branch name)
            - task_id: str | None (extracted from branch name if task/XXX format)
            - head: str (commit SHA)
            - is_main: bool (is this the main worktree)
            - files_changed: int
            - commits_ahead: int
            - lines_added: int
            - lines_removed: int
            - base_branch: str (develop or main)
    """
    try:
        result = await asyncio.to_thread(
            subprocess.run,
            ["git", "worktree", "list", "--porcelain"],
            cwd=project_path,
            capture_output=True,
            text=True,
            check=True
        )

        worktrees = []
        current_worktree = {}

        for line in result.stdout.strip().split('\n'):
            if not line:
                if current_worktree:
                    worktrees.append(current_worktree)
                    current_worktree = {}
                continue

            if line.startswith('worktree '):
                current_worktree['path'] = line[9:]
            elif line.startswith('HEAD '):
                current_worktree['head'] = line[5:]
            elif line.startswith('branch '):
                # refs/heads/branch-name -> branch-name
                branch_ref = line[7:]
                current_worktree['branch'] = branch_ref.replace('refs/heads/', '')
            elif line == 'bare':
                current_worktree['is_bare'] = True
            elif line == 'detached':
                current_worktree['is_detached'] = True

        # Don't forget the last one
        if current_worktree:
            worktrees.append(current_worktree)

        # Enrich with stats
        enriched = []
        for wt in worktrees:
            path = wt.get('path', '')
            branch = wt.get('branch', '')

            # Skip bare repos
            if wt.get('is_bare'):
                continue

            # Determine if main worktree
            is_main = path == project_path or branch in ['main', 'develop', 'master']

            # Extract task ID from branch name (task/XXX-name format)
            task_id = None
            if branch.startswith('task/'):
                match = re.match(r'task/(\d{3}-[a-z0-9-]+)', branch)
                if match:
                    task_id = match.group(1)

            # Get stats for non-main worktrees
            stats = {'files_changed': 0, 'commits_ahead': 0, 'lines_added': 0, 'lines_removed': 0}
            base_branch = 'develop'

            if not is_main and Path(path).exists():
                stats = await get_worktree_stats(path, base_branch)

            enriched.append({
                'path': path,
                'branch': branch,
                'task_id': task_id,
                'head': wt.get('head', ''),
                'is_main': is_main,
                'is_detached': wt.get('is_detached', False),
                'base_branch': base_branch,
                **stats
            })

        return enriched

    except subprocess.CalledProcessError as e:
        logger.error(f"Failed to list worktrees: {e.stderr}")
        return []
    except Exception as e:
        logger.error(f"Error listing worktrees: {e}")
        return []


async def get_worktree_stats(worktree_path: str, base_branch: str = "develop") -> dict:
    """
    Get statistics for a worktree compared to base branch.

    Returns:
        dict with keys: files_changed, commits_ahead, lines_added, lines_removed
    """
    stats = {
        'files_changed': 0,
        'commits_ahead': 0,
        'lines_added': 0,
        'lines_removed': 0
    }

    try:
        # Fetch to make sure we have latest
        await asyncio.to_thread(
            subprocess.run,
            ["git", "fetch", "origin", base_branch],
            cwd=worktree_path,
            capture_output=True,
            text=True
        )

        # Count commits ahead
        commits_result = await asyncio.to_thread(
            subprocess.run,
            ["git", "rev-list", "--count", f"origin/{base_branch}..HEAD"],
            cwd=worktree_path,
            capture_output=True,
            text=True
        )
        if commits_result.returncode == 0:
            stats['commits_ahead'] = int(commits_result.stdout.strip() or 0)

        # Get diff stats
        diff_result = await asyncio.to_thread(
            subprocess.run,
            ["git", "diff", "--stat", f"origin/{base_branch}...HEAD"],
            cwd=worktree_path,
            capture_output=True,
            text=True
        )

        if diff_result.returncode == 0 and diff_result.stdout:
            lines = diff_result.stdout.strip().split('\n')
            if lines:
                # Last line is summary: "X files changed, Y insertions(+), Z deletions(-)"
                summary = lines[-1]

                files_match = re.search(r'(\d+) files? changed', summary)
                if files_match:
                    stats['files_changed'] = int(files_match.group(1))

                insertions_match = re.search(r'(\d+) insertions?\(\+\)', summary)
                if insertions_match:
                    stats['lines_added'] = int(insertions_match.group(1))

                deletions_match = re.search(r'(\d+) deletions?\(-\)', summary)
                if deletions_match:
                    stats['lines_removed'] = int(deletions_match.group(1))

    except Exception as e:
        logger.error(f"Error getting worktree stats: {e}")

    return stats


async def remove_worktree(project_path: str, worktree_path: str) -> dict:
    """
    Remove a worktree and optionally its branch.

    Returns:
        dict with keys: success, error (if failed)
    """
    try:
        # Remove the worktree
        result = await asyncio.to_thread(
            subprocess.run,
            ["git", "worktree", "remove", "--force", worktree_path],
            cwd=project_path,
            capture_output=True,
            text=True
        )

        if result.returncode != 0:
            return {
                'success': False,
                'error': result.stderr.strip() or 'Failed to remove worktree'
            }

        # Prune any stale worktree entries
        await asyncio.to_thread(
            subprocess.run,
            ["git", "worktree", "prune"],
            cwd=project_path,
            capture_output=True
        )

        return {'success': True}

    except Exception as e:
        logger.error(f"Error removing worktree: {e}")
        return {'success': False, 'error': str(e)}


async def merge_worktree(project_path: str, worktree_path: str, target_branch: str = "develop") -> dict:
    """
    Merge the worktree's branch into target branch.

    This performs:
    1. Fetch latest target branch
    2. Checkout target branch in main repo
    3. Merge the worktree's branch
    4. Push to origin

    Returns:
        dict with keys: success, message, error (if failed)
    """
    try:
        # Get the branch name of the worktree
        branch_result = await asyncio.to_thread(
            subprocess.run,
            ["git", "branch", "--show-current"],
            cwd=worktree_path,
            capture_output=True,
            text=True,
            check=True
        )
        source_branch = branch_result.stdout.strip()

        if not source_branch:
            return {'success': False, 'error': 'Could not determine worktree branch'}

        # Fetch latest
        await asyncio.to_thread(
            subprocess.run,
            ["git", "fetch", "origin"],
            cwd=project_path,
            capture_output=True,
            text=True
        )

        # Checkout target branch
        checkout_result = await asyncio.to_thread(
            subprocess.run,
            ["git", "checkout", target_branch],
            cwd=project_path,
            capture_output=True,
            text=True
        )

        if checkout_result.returncode != 0:
            return {
                'success': False,
                'error': f'Failed to checkout {target_branch}: {checkout_result.stderr}'
            }

        # Pull latest target
        await asyncio.to_thread(
            subprocess.run,
            ["git", "pull", "origin", target_branch],
            cwd=project_path,
            capture_output=True,
            text=True
        )

        # Merge source branch
        merge_result = await asyncio.to_thread(
            subprocess.run,
            ["git", "merge", source_branch, "--no-edit"],
            cwd=project_path,
            capture_output=True,
            text=True
        )

        if merge_result.returncode != 0:
            # Abort the merge if it failed
            await asyncio.to_thread(
                subprocess.run,
                ["git", "merge", "--abort"],
                cwd=project_path,
                capture_output=True
            )
            return {
                'success': False,
                'error': f'Merge conflict: {merge_result.stderr or merge_result.stdout}'
            }

        # Push to origin
        push_result = await asyncio.to_thread(
            subprocess.run,
            ["git", "push", "origin", target_branch],
            cwd=project_path,
            capture_output=True,
            text=True
        )

        if push_result.returncode != 0:
            return {
                'success': False,
                'error': f'Failed to push: {push_result.stderr}'
            }

        return {
            'success': True,
            'message': f'Successfully merged {source_branch} into {target_branch}'
        }

    except Exception as e:
        logger.error(f"Error merging worktree: {e}")
        return {'success': False, 'error': str(e)}


async def get_worktree_by_task_id(project_path: str, task_id: str) -> Optional[dict]:
    """Find a worktree by its task ID."""
    worktrees = await list_worktrees(project_path)
    for wt in worktrees:
        if wt.get('task_id') == task_id:
            return wt
    return None


def _matches_pattern(file_path: Path, pattern: str, base_path: Path) -> bool:
    """
    Check if a file path matches a glob pattern.

    Handles both simple patterns (*.py) and path patterns (tests/**).
    """
    relative_path = file_path.relative_to(base_path)
    relative_str = str(relative_path).replace("\\", "/")

    # Handle directory patterns (ending with /)
    if pattern.endswith("/"):
        dir_pattern = pattern.rstrip("/")
        # Check if the file is inside a directory matching the pattern
        parts = relative_str.split("/")
        for i, part in enumerate(parts):
            if fnmatch.fnmatch(part, dir_pattern):
                return True
        return False

    # Handle path patterns with **
    if "**" in pattern:
        # Convert ** glob to regex-like matching
        pattern_parts = pattern.replace("\\", "/").split("/")
        path_parts = relative_str.split("/")
        return _match_glob_pattern(path_parts, pattern_parts)

    # Handle path patterns with /
    if "/" in pattern:
        return fnmatch.fnmatch(relative_str, pattern)

    # Simple filename pattern - match against the filename only
    return fnmatch.fnmatch(file_path.name, pattern)


def _match_glob_pattern(path_parts: list[str], pattern_parts: list[str]) -> bool:
    """
    Match path parts against pattern parts, supporting ** wildcards.
    """
    if not pattern_parts:
        return not path_parts

    if not path_parts:
        # Only match if remaining pattern is all **
        return all(p == "**" for p in pattern_parts)

    pattern = pattern_parts[0]

    if pattern == "**":
        # ** can match zero or more directories
        if len(pattern_parts) == 1:
            return True
        # Try matching ** against 0, 1, 2, ... path components
        for i in range(len(path_parts) + 1):
            if _match_glob_pattern(path_parts[i:], pattern_parts[1:]):
                return True
        return False

    if fnmatch.fnmatch(path_parts[0], pattern):
        return _match_glob_pattern(path_parts[1:], pattern_parts[1:])

    return False


async def cleanup_worktree_files(
    worktree_path: str,
    patterns: list[str],
    keep_patterns: list[str]
) -> dict:
    """
    Clean up test/debug files from a worktree directory.

    This function scans the worktree, matches files against cleanup patterns,
    excludes files matching keep_patterns, and removes matched files/directories.

    Args:
        worktree_path: Path to the worktree directory
        patterns: List of glob patterns for files to remove (e.g., "test_*.py", ".pytest_cache/")
        keep_patterns: List of glob patterns for files to keep (e.g., "tests/**")

    Returns:
        dict with keys:
            - success: bool
            - cleaned_files: list of removed file paths (relative to worktree)
            - cleaned_dirs: list of removed directory paths (relative to worktree)
            - skipped: list of files that matched cleanup but were kept
            - errors: list of error messages
    """
    result = {
        "success": True,
        "cleaned_files": [],
        "cleaned_dirs": [],
        "skipped": [],
        "errors": []
    }

    base_path = Path(worktree_path)

    if not base_path.exists():
        result["success"] = False
        result["errors"].append(f"Worktree path does not exist: {worktree_path}")
        return result

    if not base_path.is_dir():
        result["success"] = False
        result["errors"].append(f"Worktree path is not a directory: {worktree_path}")
        return result

    # Separate directory patterns from file patterns
    dir_patterns = [p.rstrip("/") for p in patterns if p.endswith("/")]
    file_patterns = [p for p in patterns if not p.endswith("/")]

    # First pass: find and remove matching directories
    dirs_to_remove = set()

    def scan_for_directories(current_path: Path):
        """Recursively scan for directories matching cleanup patterns."""
        try:
            for item in current_path.iterdir():
                if item.is_dir():
                    # Check if directory name matches any dir pattern
                    for pattern in dir_patterns:
                        if fnmatch.fnmatch(item.name, pattern):
                            relative = str(item.relative_to(base_path)).replace("\\", "/")
                            # Check if it's protected by keep patterns
                            should_keep = False
                            for keep in keep_patterns:
                                if _matches_pattern(item, keep, base_path):
                                    should_keep = True
                                    break
                            if should_keep:
                                result["skipped"].append(relative)
                            else:
                                dirs_to_remove.add(item)
                            break
                    else:
                        # Recurse into non-matching directories
                        scan_for_directories(item)
        except PermissionError as e:
            result["errors"].append(f"Permission denied: {e}")
        except Exception as e:
            result["errors"].append(f"Error scanning {current_path}: {e}")

    # Run directory scan in thread to avoid blocking
    await asyncio.to_thread(scan_for_directories, base_path)

    # Remove matched directories
    for dir_path in dirs_to_remove:
        try:
            relative = str(dir_path.relative_to(base_path)).replace("\\", "/")
            await asyncio.to_thread(shutil.rmtree, dir_path)
            result["cleaned_dirs"].append(relative)
            logger.debug(f"Removed directory: {relative}")
        except Exception as e:
            result["errors"].append(f"Failed to remove directory {dir_path}: {e}")

    # Second pass: find and remove matching files
    files_to_remove = []

    def scan_for_files(current_path: Path):
        """Recursively scan for files matching cleanup patterns."""
        try:
            for item in current_path.iterdir():
                if item.is_file():
                    # Check if file matches any cleanup pattern
                    for pattern in file_patterns:
                        if _matches_pattern(item, pattern, base_path):
                            relative = str(item.relative_to(base_path)).replace("\\", "/")
                            # Check if it's protected by keep patterns
                            should_keep = False
                            for keep in keep_patterns:
                                if _matches_pattern(item, keep, base_path):
                                    should_keep = True
                                    break
                            if should_keep:
                                result["skipped"].append(relative)
                            else:
                                files_to_remove.append(item)
                            break
                elif item.is_dir():
                    # Recurse into directories (skip removed dirs)
                    if item not in dirs_to_remove:
                        scan_for_files(item)
        except PermissionError as e:
            result["errors"].append(f"Permission denied: {e}")
        except Exception as e:
            result["errors"].append(f"Error scanning {current_path}: {e}")

    # Run file scan in thread
    await asyncio.to_thread(scan_for_files, base_path)

    # Remove matched files
    for file_path in files_to_remove:
        try:
            relative = str(file_path.relative_to(base_path)).replace("\\", "/")
            await asyncio.to_thread(file_path.unlink)
            result["cleaned_files"].append(relative)
            logger.debug(f"Removed file: {relative}")
        except Exception as e:
            result["errors"].append(f"Failed to remove file {file_path}: {e}")

    # Log summary
    total_cleaned = len(result["cleaned_files"]) + len(result["cleaned_dirs"])
    if total_cleaned > 0:
        logger.info(
            f"Cleanup completed: removed {len(result['cleaned_files'])} files "
            f"and {len(result['cleaned_dirs'])} directories from {worktree_path}"
        )
    else:
        logger.debug(f"Cleanup completed: no files to remove from {worktree_path}")

    if result["errors"]:
        result["success"] = False
        logger.warning(f"Cleanup had {len(result['errors'])} errors")

    return result
