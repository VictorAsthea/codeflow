"""
Worktree management service for listing, removing, and getting stats on git worktrees.
"""
import asyncio
import subprocess
import logging
import re
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
