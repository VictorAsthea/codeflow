import asyncio
import subprocess
import json
import logging
import re
from typing import Optional
from datetime import datetime

logger = logging.getLogger(__name__)

# Known bot authors for code review tools
BOT_AUTHORS = [
    "coderabbitai[bot]",
    "gemini-code-review[bot]",
    "github-actions[bot]",
    "dependabot[bot]",
    "copilot[bot]"
]


async def get_repo_info(project_path: str) -> dict:
    """
    Get repository owner and name from git remote.

    Returns:
        dict with keys: owner, repo
    """
    try:
        result = await asyncio.to_thread(
            subprocess.run,
            ["git", "remote", "get-url", "origin"],
            cwd=project_path,
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='replace',
            check=True
        )

        remote_url = result.stdout.strip()

        # Parse GitHub URL (supports both HTTPS and SSH)
        # HTTPS: https://github.com/owner/repo.git
        # SSH: git@github.com:owner/repo.git
        patterns = [
            r'github\.com[:/]([^/]+)/([^/]+?)(?:\.git)?$',
        ]

        for pattern in patterns:
            match = re.search(pattern, remote_url)
            if match:
                return {
                    "owner": match.group(1),
                    "repo": match.group(2)
                }

        logger.error(f"Could not parse GitHub remote URL: {remote_url}")
        return {"owner": None, "repo": None}

    except Exception as e:
        logger.error(f"Error getting repo info: {e}")
        return {"owner": None, "repo": None}


async def get_pr_details(pr_number: int, project_path: str) -> dict:
    """
    Get PR details using gh CLI.

    Returns:
        dict with keys: state, mergeable, title, url, headRefName, baseRefName
    """
    try:
        result = await asyncio.to_thread(
            subprocess.run,
            [
                "gh", "pr", "view", str(pr_number),
                "--json", "state,mergeable,title,url,headRefName,baseRefName,number"
            ],
            cwd=project_path,
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='replace',
            check=True
        )

        return json.loads(result.stdout)

    except subprocess.CalledProcessError as e:
        logger.error(f"Failed to get PR details: {e.stderr}")
        return {"error": e.stderr.strip() if e.stderr else str(e)}
    except FileNotFoundError:
        logger.error("GitHub CLI (gh) is not installed")
        return {"error": "GitHub CLI (gh) is not installed"}
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse PR details: {e}")
        return {"error": str(e)}


async def get_pr_review_comments(
    pr_number: int,
    project_path: str,
    author_filter: Optional[list[str]] = None
) -> list[dict]:
    """
    Get PR review comments using GitHub API via gh CLI.

    Args:
        pr_number: PR number
        project_path: Path to git repo
        author_filter: Optional list of authors to filter by (e.g., BOT_AUTHORS)

    Returns:
        list of dicts with keys:
            - id: int
            - author: str
            - body: str
            - path: str (file path)
            - line: int (line number, if available)
            - diff_hunk: str (surrounding diff context)
            - created_at: str
            - url: str (link to comment)
    """
    repo_info = await get_repo_info(project_path)
    if not repo_info.get("owner") or not repo_info.get("repo"):
        logger.error("Could not determine repo owner/name")
        return []

    owner = repo_info["owner"]
    repo = repo_info["repo"]

    try:
        # Get review comments (comments on specific lines of code)
        result = await asyncio.to_thread(
            subprocess.run,
            [
                "gh", "api",
                f"repos/{owner}/{repo}/pulls/{pr_number}/comments",
                "--paginate"
            ],
            cwd=project_path,
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='replace',
            check=True
        )

        raw_comments = json.loads(result.stdout) if result.stdout else []

        comments = []
        for comment in raw_comments:
            author = comment.get("user", {}).get("login", "unknown")

            # Apply author filter if specified
            if author_filter and author not in author_filter:
                continue

            comments.append({
                "id": comment.get("id"),
                "author": author,
                "body": comment.get("body", ""),
                "path": comment.get("path", ""),
                "line": comment.get("line") or comment.get("original_line"),
                "diff_hunk": comment.get("diff_hunk", ""),
                "created_at": comment.get("created_at", ""),
                "url": comment.get("html_url", ""),
                "commit_id": comment.get("commit_id", ""),
                "in_reply_to_id": comment.get("in_reply_to_id")
            })

        return comments

    except subprocess.CalledProcessError as e:
        logger.error(f"Failed to get PR comments: {e.stderr}")
        return []
    except FileNotFoundError:
        logger.error("GitHub CLI (gh) is not installed")
        return []
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse PR comments: {e}")
        return []


async def get_pr_issue_comments(pr_number: int, project_path: str) -> list[dict]:
    """
    Get issue-style comments on a PR (not on specific code lines).

    These are general comments on the PR, not associated with specific files.
    """
    repo_info = await get_repo_info(project_path)
    if not repo_info.get("owner") or not repo_info.get("repo"):
        return []

    owner = repo_info["owner"]
    repo = repo_info["repo"]

    try:
        result = await asyncio.to_thread(
            subprocess.run,
            [
                "gh", "api",
                f"repos/{owner}/{repo}/issues/{pr_number}/comments",
                "--paginate"
            ],
            cwd=project_path,
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='replace',
            check=True
        )

        raw_comments = json.loads(result.stdout) if result.stdout else []

        return [
            {
                "id": comment.get("id"),
                "author": comment.get("user", {}).get("login", "unknown"),
                "body": comment.get("body", ""),
                "created_at": comment.get("created_at", ""),
                "url": comment.get("html_url", ""),
                "is_bot": comment.get("user", {}).get("login", "") in BOT_AUTHORS
            }
            for comment in raw_comments
        ]

    except Exception as e:
        logger.error(f"Failed to get issue comments: {e}")
        return []


async def get_all_pr_reviews(
    pr_number: int,
    project_path: str,
    include_bots_only: bool = False
) -> dict:
    """
    Get all review comments grouped by file with PR status.

    Args:
        pr_number: PR number
        project_path: Path to git repo
        include_bots_only: If True, only include comments from BOT_AUTHORS

    Returns:
        dict with keys:
            - pr_status: dict with PR details
            - comments: list of all comments
            - grouped_by_file: dict mapping file paths to their comments
            - bot_comments: list of comments from bots only
    """
    # Get PR details
    pr_details = await get_pr_details(pr_number, project_path)

    # Get review comments
    author_filter = BOT_AUTHORS if include_bots_only else None
    review_comments = await get_pr_review_comments(
        pr_number, project_path, author_filter
    )

    # Group by file
    grouped_by_file = {}
    for comment in review_comments:
        path = comment.get("path", "general")
        if path not in grouped_by_file:
            grouped_by_file[path] = []
        grouped_by_file[path].append(comment)

    # Sort comments within each file by line number
    for path in grouped_by_file:
        grouped_by_file[path].sort(key=lambda c: c.get("line") or 0)

    # Filter bot comments
    bot_comments = [c for c in review_comments if c.get("author") in BOT_AUTHORS]

    return {
        "pr_status": pr_details,
        "comments": review_comments,
        "grouped_by_file": grouped_by_file,
        "bot_comments": bot_comments,
        "total_comments": len(review_comments),
        "bot_comment_count": len(bot_comments)
    }


async def get_comment_by_id(
    comment_id: int,
    pr_number: int,
    project_path: str
) -> Optional[dict]:
    """
    Get a specific comment by its ID.
    """
    comments = await get_pr_review_comments(pr_number, project_path)
    for comment in comments:
        if comment.get("id") == comment_id:
            return comment
    return None


async def get_comments_by_ids(
    comment_ids: list[int],
    pr_number: int,
    project_path: str
) -> list[dict]:
    """
    Get multiple comments by their IDs.
    """
    comments = await get_pr_review_comments(pr_number, project_path)
    id_set = set(comment_ids)
    return [c for c in comments if c.get("id") in id_set]


async def reply_to_comment(
    comment_id: int,
    body: str,
    pr_number: int,
    project_path: str
) -> dict:
    """
    Reply to a review comment.
    """
    repo_info = await get_repo_info(project_path)
    if not repo_info.get("owner") or not repo_info.get("repo"):
        return {"success": False, "error": "Could not determine repo"}

    owner = repo_info["owner"]
    repo = repo_info["repo"]

    try:
        result = await asyncio.to_thread(
            subprocess.run,
            [
                "gh", "api",
                f"repos/{owner}/{repo}/pulls/{pr_number}/comments/{comment_id}/replies",
                "-X", "POST",
                "-f", f"body={body}"
            ],
            cwd=project_path,
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='replace',
            check=True
        )

        return {"success": True, "response": json.loads(result.stdout)}

    except subprocess.CalledProcessError as e:
        logger.error(f"Failed to reply to comment: {e.stderr}")
        return {"success": False, "error": e.stderr.strip() if e.stderr else str(e)}
