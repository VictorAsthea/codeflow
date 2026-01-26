"""
Shared validation module for path parameter validation and input sanitization.

Provides:
1. Reusable validators using Annotated types with Pydantic Field constraints.
   These prevent malformed IDs from reaching business logic and protect against injection.

2. Input sanitization utilities for strings used in shell commands or file operations.
   IMPORTANT: These utilities are a defense-in-depth measure. The primary protection
   against command injection is using subprocess with lists (not shell=True).

Security Notes:
- All IDs are validated with strict alphanumeric patterns to prevent injection
- Path validation ensures no directory traversal attacks
- Shell command inputs should always use subprocess with list arguments
- File paths should be validated against allowed base directories
"""

from typing import Annotated, Optional
from pydantic import Field
from pathlib import Path
import re
import os

# Shared ID pattern - alphanumeric with hyphens and underscores
# This pattern is intentionally strict to prevent injection attacks
ID_PATTERN = r"^[a-zA-Z0-9-_]+$"
MAX_ID_LENGTH = 50

# Task ID - used for task/{task_id} endpoints
TaskId = Annotated[
    str,
    Field(
        min_length=1,
        max_length=MAX_ID_LENGTH,
        pattern=ID_PATTERN,
        description="Task identifier (alphanumeric, hyphens, underscores only)"
    )
]

# Feature ID - used for roadmap/features/{feature_id} endpoints
FeatureId = Annotated[
    str,
    Field(
        min_length=1,
        max_length=MAX_ID_LENGTH,
        pattern=ID_PATTERN,
        description="Feature identifier (alphanumeric, hyphens, underscores only)"
    )
]

# Session ID - used for memory/session/{session_id} endpoints
SessionId = Annotated[
    str,
    Field(
        min_length=1,
        max_length=MAX_ID_LENGTH,
        pattern=ID_PATTERN,
        description="Session identifier (alphanumeric, hyphens, underscores only)"
    )
]

# Suggestion ID - used for ideation/suggestions/{suggestion_id} endpoints
SuggestionId = Annotated[
    str,
    Field(
        min_length=1,
        max_length=MAX_ID_LENGTH,
        pattern=ID_PATTERN,
        description="Suggestion identifier (alphanumeric, hyphens, underscores only)"
    )
]

# Subtask ID - used for tasks/{task_id}/subtasks/{subtask_id} endpoints
SubtaskId = Annotated[
    str,
    Field(
        min_length=1,
        max_length=MAX_ID_LENGTH,
        pattern=ID_PATTERN,
        description="Subtask identifier (alphanumeric, hyphens, underscores only)"
    )
]

# Phase name - used for tasks/{task_id}/phases/{phase_name} endpoints
# Phase names are typically: planning, coding, validation
PhaseName = Annotated[
    str,
    Field(
        min_length=1,
        max_length=MAX_ID_LENGTH,
        pattern=ID_PATTERN,
        description="Phase name (alphanumeric, hyphens, underscores only)"
    )
]

# Branch name - used for git operations
# Branch names can include slashes (e.g., task/123-feature)
BRANCH_PATTERN = r"^[a-zA-Z0-9-_/]+$"
MAX_BRANCH_LENGTH = 100

BranchName = Annotated[
    str,
    Field(
        min_length=1,
        max_length=MAX_BRANCH_LENGTH,
        pattern=BRANCH_PATTERN,
        description="Git branch name (alphanumeric, hyphens, underscores, slashes only)"
    )
]


# =============================================================================
# INPUT SANITIZATION UTILITIES
# =============================================================================
# Defense-in-depth utilities for sanitizing user input before use in shell
# commands or file operations. These complement (not replace) proper practices:
# - Always use subprocess with list arguments (never shell=True)
# - Validate paths against allowed directories
# - Use parameterized queries for databases
# =============================================================================


class SanitizationError(ValueError):
    """Raised when input fails sanitization checks."""
    pass


def sanitize_shell_arg(value: str, max_length: int = 1000, allow_spaces: bool = True) -> str:
    """
    Sanitize a string intended for use as a shell command argument.

    Security: This is a defense-in-depth measure. Always use subprocess with
    list arguments to prevent shell injection - this function provides an
    additional layer of validation.

    Args:
        value: The string to sanitize
        max_length: Maximum allowed length (default 1000)
        allow_spaces: Whether to allow spaces in the value (default True)

    Returns:
        The sanitized string (unchanged if valid)

    Raises:
        SanitizationError: If the value contains dangerous characters or patterns
    """
    if not value:
        return value

    if len(value) > max_length:
        raise SanitizationError(f"Value exceeds maximum length of {max_length} characters")

    # Characters that could be dangerous in shell contexts
    # Even with subprocess lists, these can cause issues with certain commands
    dangerous_patterns = [
        r'\x00',           # Null byte - can truncate strings
        r'`',              # Command substitution in backticks
        r'\$\(',           # Command substitution $(...)
        r'\$\{',           # Variable expansion ${...}
        r'\|',             # Pipe
        r';',              # Command separator
        r'&&',             # Command chaining
        r'\|\|',           # Command chaining
        r'<\(',            # Process substitution
        r'\n',             # Newline - can inject commands
        r'\r',             # Carriage return
    ]

    for pattern in dangerous_patterns:
        if re.search(pattern, value):
            raise SanitizationError(f"Value contains potentially dangerous pattern")

    if not allow_spaces and ' ' in value:
        raise SanitizationError("Value contains spaces which are not allowed")

    return value


def sanitize_filename(filename: str, max_length: int = 255) -> str:
    """
    Sanitize a filename to prevent directory traversal and invalid characters.

    Security: Prevents:
    - Directory traversal attacks (../, absolute paths)
    - Null byte injection
    - Invalid filesystem characters

    Args:
        filename: The filename to sanitize
        max_length: Maximum allowed length (default 255, typical filesystem limit)

    Returns:
        The sanitized filename (unchanged if valid)

    Raises:
        SanitizationError: If the filename is unsafe
    """
    if not filename:
        raise SanitizationError("Filename cannot be empty")

    if len(filename) > max_length:
        raise SanitizationError(f"Filename exceeds maximum length of {max_length} characters")

    # Check for null bytes
    if '\x00' in filename:
        raise SanitizationError("Filename contains null bytes")

    # Check for directory traversal
    if '..' in filename:
        raise SanitizationError("Filename contains directory traversal sequence")

    # Check for absolute paths or path separators
    if '/' in filename or '\\' in filename:
        raise SanitizationError("Filename contains path separators")

    # Check for invalid characters on Windows/Unix
    invalid_chars = '<>:"|?*'
    for char in invalid_chars:
        if char in filename:
            raise SanitizationError(f"Filename contains invalid character: {char}")

    # Prevent hidden files unless explicitly intended
    # (caller can strip the dot if they want to allow hidden files)

    return filename


def validate_path_within_directory(path: str, base_directory: str) -> Path:
    """
    Validate that a path is within an allowed base directory.

    Security: Prevents directory traversal attacks by ensuring the resolved
    path is within the allowed base directory. Uses os.path.realpath to
    resolve symlinks and normalize the path.

    Args:
        path: The path to validate (can be relative to base_directory)
        base_directory: The allowed base directory

    Returns:
        The resolved Path object if valid

    Raises:
        SanitizationError: If the path escapes the base directory
    """
    if not path:
        raise SanitizationError("Path cannot be empty")

    if not base_directory:
        raise SanitizationError("Base directory cannot be empty")

    # Resolve both paths to absolute, normalized forms
    base_resolved = os.path.realpath(base_directory)
    full_path = os.path.join(base_resolved, path)
    path_resolved = os.path.realpath(full_path)

    # Ensure the resolved path starts with the base directory
    # Using commonpath prevents false positives from partial matches
    try:
        common = os.path.commonpath([base_resolved, path_resolved])
        if common != base_resolved:
            raise SanitizationError("Path escapes the allowed directory")
    except ValueError:
        # Paths are on different drives (Windows) or have no common path
        raise SanitizationError("Path escapes the allowed directory")

    return Path(path_resolved)


def sanitize_git_ref(ref: str, max_length: int = 200) -> str:
    """
    Sanitize a git reference (branch name, tag, commit hash).

    Security: Git refs are used in subprocess calls, so they must be validated
    to prevent injection attacks.

    Args:
        ref: The git reference to sanitize
        max_length: Maximum allowed length (default 200)

    Returns:
        The sanitized reference (unchanged if valid)

    Raises:
        SanitizationError: If the reference contains invalid characters
    """
    if not ref:
        raise SanitizationError("Git reference cannot be empty")

    if len(ref) > max_length:
        raise SanitizationError(f"Git reference exceeds maximum length of {max_length} characters")

    # Git refs can contain alphanumerics, hyphens, underscores, slashes, and dots
    # But not consecutive dots, leading/trailing dots, or special sequences
    if not re.match(r'^[a-zA-Z0-9][a-zA-Z0-9._/-]*$', ref):
        raise SanitizationError("Git reference contains invalid characters")

    # Check for dangerous patterns
    if '..' in ref:  # Could be directory traversal or git range
        raise SanitizationError("Git reference contains '..' sequence")

    if ref.startswith('-'):  # Could be interpreted as a flag
        raise SanitizationError("Git reference cannot start with '-'")

    if ref.endswith('.lock'):  # Git internal file
        raise SanitizationError("Git reference cannot end with '.lock'")

    return ref


def sanitize_commit_message(message: str, max_length: int = 5000) -> str:
    """
    Sanitize a git commit message.

    Security: Commit messages are passed to git commands and displayed in logs.
    This ensures they don't contain control characters or excessively long content.

    Args:
        message: The commit message to sanitize
        max_length: Maximum allowed length (default 5000)

    Returns:
        The sanitized message (unchanged if valid)

    Raises:
        SanitizationError: If the message is invalid
    """
    if not message:
        raise SanitizationError("Commit message cannot be empty")

    if len(message) > max_length:
        raise SanitizationError(f"Commit message exceeds maximum length of {max_length} characters")

    # Check for null bytes (can cause truncation)
    if '\x00' in message:
        raise SanitizationError("Commit message contains null bytes")

    return message
