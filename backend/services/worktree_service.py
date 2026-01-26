"""
Worktree management service for listing, removing, and getting stats on git worktrees.
"""
import asyncio
import subprocess
import logging
import os
import re
import shutil
from datetime import datetime, timedelta, timezone
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


async def check_worktree_health(worktree_path: str) -> dict:
    """
    Check the health and integrity of a worktree.

    Returns:
        dict with keys:
            - healthy: bool (overall health status)
            - exists: bool (directory exists)
            - git_valid: bool (valid git worktree)
            - has_uncommitted: bool (has uncommitted changes)
            - branch: str | None (current branch)
            - last_activity: str | None (ISO timestamp of last git activity)
            - issues: list[str] (list of detected issues)
    """
    result = {
        'healthy': True,
        'exists': False,
        'git_valid': False,
        'has_uncommitted': False,
        'branch': None,
        'last_activity': None,
        'issues': []
    }

    path = Path(worktree_path)

    # Check if directory exists
    if not path.exists():
        result['healthy'] = False
        result['issues'].append('Worktree directory does not exist')
        return result

    result['exists'] = True

    # Check if .git file exists (worktrees have .git file, not directory)
    git_file = path / '.git'
    if not git_file.exists():
        result['healthy'] = False
        result['issues'].append('Missing .git file - not a valid worktree')
        return result

    try:
        # Verify git worktree is valid by running git status
        status_result = await asyncio.to_thread(
            subprocess.run,
            ['git', 'status', '--porcelain'],
            cwd=worktree_path,
            capture_output=True,
            text=True
        )

        if status_result.returncode != 0:
            result['healthy'] = False
            result['issues'].append(f'Git status failed: {status_result.stderr.strip()}')
            return result

        result['git_valid'] = True

        # Check for uncommitted changes
        if status_result.stdout.strip():
            result['has_uncommitted'] = True
            result['issues'].append('Has uncommitted changes')

        # Get current branch
        branch_result = await asyncio.to_thread(
            subprocess.run,
            ['git', 'branch', '--show-current'],
            cwd=worktree_path,
            capture_output=True,
            text=True
        )

        if branch_result.returncode == 0:
            result['branch'] = branch_result.stdout.strip() or None

        # Get last activity (last commit date)
        log_result = await asyncio.to_thread(
            subprocess.run,
            ['git', 'log', '-1', '--format=%ci'],
            cwd=worktree_path,
            capture_output=True,
            text=True
        )

        if log_result.returncode == 0 and log_result.stdout.strip():
            try:
                # Parse git date format: "2024-01-15 10:30:45 +0000"
                date_str = log_result.stdout.strip()
                # Convert to ISO format
                last_commit = datetime.strptime(date_str[:19], '%Y-%m-%d %H:%M:%S')
                # Handle timezone offset
                tz_str = date_str[20:].strip()
                if tz_str:
                    hours = int(tz_str[:3])
                    minutes = int(tz_str[0] + tz_str[3:5])
                    last_commit = last_commit.replace(tzinfo=timezone(timedelta(hours=hours, minutes=minutes)))
                result['last_activity'] = last_commit.isoformat()
            except (ValueError, IndexError):
                pass

        # Check if worktree is locked
        lock_result = await asyncio.to_thread(
            subprocess.run,
            ['git', 'worktree', 'list', '--porcelain'],
            cwd=worktree_path,
            capture_output=True,
            text=True
        )

        if 'locked' in lock_result.stdout:
            result['issues'].append('Worktree is locked')

    except Exception as e:
        result['healthy'] = False
        result['issues'].append(f'Error checking worktree: {str(e)}')

    # Overall health: no critical issues
    if not result['git_valid']:
        result['healthy'] = False

    return result


async def cleanup_stale_worktrees(project_path: str, max_age_hours: int = 72) -> dict:
    """
    Remove abandoned worktrees that haven't been active for a specified time.

    Args:
        project_path: Path to the main git repository
        max_age_hours: Maximum hours of inactivity before considering a worktree stale

    Returns:
        dict with keys:
            - cleaned: int (number of worktrees removed)
            - skipped: int (number of worktrees skipped)
            - errors: list[str] (errors encountered)
            - details: list[dict] (details of each worktree processed)
    """
    result = {
        'cleaned': 0,
        'skipped': 0,
        'errors': [],
        'details': []
    }

    try:
        worktrees = await list_worktrees(project_path)
        cutoff_time = datetime.now(timezone.utc) - timedelta(hours=max_age_hours)

        for wt in worktrees:
            path = wt.get('path', '')
            detail = {'path': path, 'action': 'skipped', 'reason': ''}

            # Skip main worktree
            if wt.get('is_main'):
                detail['reason'] = 'Main worktree'
                result['skipped'] += 1
                result['details'].append(detail)
                continue

            # Check health
            health = await check_worktree_health(path)

            # Skip if worktree doesn't exist (already gone)
            if not health['exists']:
                detail['reason'] = 'Does not exist'
                result['skipped'] += 1
                result['details'].append(detail)
                continue

            # Skip if has uncommitted changes
            if health['has_uncommitted']:
                detail['reason'] = 'Has uncommitted changes'
                result['skipped'] += 1
                result['details'].append(detail)
                continue

            # Check last activity
            is_stale = False
            if health['last_activity']:
                try:
                    last_activity = datetime.fromisoformat(health['last_activity'])
                    if last_activity < cutoff_time:
                        is_stale = True
                except (ValueError, TypeError):
                    # If we can't parse the date, check file modification time
                    pass

            # Fallback: check directory modification time
            if not is_stale and health['last_activity'] is None:
                try:
                    path_obj = Path(path)
                    mtime = datetime.fromtimestamp(path_obj.stat().st_mtime, tz=timezone.utc)
                    if mtime < cutoff_time:
                        is_stale = True
                except (OSError, ValueError):
                    pass

            if not is_stale:
                detail['reason'] = 'Recent activity'
                result['skipped'] += 1
                result['details'].append(detail)
                continue

            # Remove the stale worktree
            remove_result = await remove_worktree(project_path, path)

            if remove_result['success']:
                detail['action'] = 'cleaned'
                detail['reason'] = f'Inactive for more than {max_age_hours} hours'
                result['cleaned'] += 1
            else:
                detail['action'] = 'error'
                detail['reason'] = remove_result.get('error', 'Unknown error')
                result['errors'].append(f"Failed to remove {path}: {detail['reason']}")

            result['details'].append(detail)

    except Exception as e:
        logger.error(f"Error during worktree cleanup: {e}")
        result['errors'].append(str(e))

    return result


async def get_worktree_disk_usage(project_path: str) -> dict:
    """
    Calculate total disk usage for all worktrees.

    Returns:
        dict with keys:
            - total_bytes: int (total disk usage in bytes)
            - total_formatted: str (human-readable total)
            - worktrees: list[dict] (per-worktree usage)
                - path: str
                - bytes: int
                - formatted: str
    """
    result = {
        'total_bytes': 0,
        'total_formatted': '0 B',
        'worktrees': []
    }

    def format_bytes(size: int) -> str:
        """Format bytes to human-readable string."""
        for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
            if abs(size) < 1024.0:
                return f"{size:.1f} {unit}"
            size /= 1024.0
        return f"{size:.1f} PB"

    def get_dir_size(path: str) -> int:
        """Calculate directory size in bytes."""
        total = 0
        try:
            for dirpath, dirnames, filenames in os.walk(path):
                # Skip .git internals for main repo (they're shared)
                if '.git' in dirpath.split(os.sep):
                    continue
                for filename in filenames:
                    filepath = os.path.join(dirpath, filename)
                    try:
                        total += os.path.getsize(filepath)
                    except (OSError, FileNotFoundError):
                        pass
        except (OSError, PermissionError):
            pass
        return total

    try:
        worktrees = await list_worktrees(project_path)

        for wt in worktrees:
            path = wt.get('path', '')

            # Skip main worktree (don't count main repo size)
            if wt.get('is_main'):
                continue

            if not Path(path).exists():
                continue

            # Calculate size in thread to avoid blocking
            size = await asyncio.to_thread(get_dir_size, path)

            result['worktrees'].append({
                'path': path,
                'branch': wt.get('branch', ''),
                'task_id': wt.get('task_id'),
                'bytes': size,
                'formatted': format_bytes(size)
            })

            result['total_bytes'] += size

        result['total_formatted'] = format_bytes(result['total_bytes'])

    except Exception as e:
        logger.error(f"Error calculating disk usage: {e}")

    return result
