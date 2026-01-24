"""
Wrapper for Claude Code CLI.
Uses Pro/Max subscription, not the paid API.
"""

import asyncio
import json
import re
import os
import shutil
import logging
from typing import Callable

logger = logging.getLogger(__name__)


def get_claude_command() -> str:
    """
    Get the Claude CLI command path.
    Checks multiple locations for Claude CLI installation.
    """
    # Check if claude is in PATH
    claude_path = shutil.which("claude")
    if claude_path:
        return claude_path

    # Common installation locations
    possible_paths = [
        # npm global install (Windows)
        os.path.expandvars(r"%APPDATA%\npm\claude.cmd"),
        os.path.expandvars(r"%APPDATA%\npm\claude"),
        # npm global install (Unix)
        os.path.expanduser("~/.npm-global/bin/claude"),
        "/usr/local/bin/claude",
        "/usr/bin/claude",
        # pnpm
        os.path.expanduser("~/.local/share/pnpm/claude"),
    ]

    for path in possible_paths:
        if os.path.exists(path):
            logger.info(f"Found Claude CLI at: {path}")
            return path

    return "claude"  # Fallback


async def run_claude_cli(
    prompt: str,
    cwd: str,
    output_format: str = "text",
    allowed_tools: list[str] | None = None,
    max_turns: int = 50,
    timeout: int = 600,
    on_output: Callable[[str], None] | None = None
) -> tuple[bool, str]:
    """
    Execute Claude Code CLI with a prompt.

    Args:
        prompt: The prompt to send
        cwd: Working directory
        output_format: "text" or "json"
        allowed_tools: List of allowed tools (Edit, Write, Bash, Read)
        max_turns: Max turns
        timeout: Timeout in seconds
        on_output: Callback for each output line (streaming)

    Returns:
        Tuple (success: bool, output: str)
    """
    claude_cmd = get_claude_command()
    cmd = [claude_cmd, "--print", "--no-session-persistence"]

    if output_format == "json":
        cmd.extend(["--output-format", "json"])

    if allowed_tools:
        cmd.extend(["--allowedTools", ",".join(allowed_tools)])

    cmd.extend(["--max-turns", str(max_turns)])

    # Prompt will be passed via stdin (handles long prompts and special chars)
    cmd.append("-")  # Read from stdin

    logger.info(f"Running Claude CLI: {claude_cmd} (max_turns={max_turns}, timeout={timeout}s)")

    # Prepare environment with npm path (Windows)
    env = os.environ.copy()
    npm_path = os.path.expandvars(r"%APPDATA%\npm")
    if os.path.exists(npm_path):
        env["PATH"] = npm_path + os.pathsep + env.get("PATH", "")

    # Create process with stdin pipe
    process = await asyncio.create_subprocess_exec(
        *cmd,
        cwd=cwd,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        env=env
    )

    # Send prompt via stdin and close it
    process.stdin.write(prompt.encode('utf-8'))
    await process.stdin.drain()
    process.stdin.close()
    await process.stdin.wait_closed()

    output_lines = []

    try:
        while True:
            try:
                line = await asyncio.wait_for(
                    process.stdout.readline(),
                    timeout=timeout
                )
            except asyncio.TimeoutError:
                process.kill()
                if on_output:
                    on_output("ERROR: Execution timed out\n")
                return False, "Timeout"

            if not line:
                break

            decoded = line.decode('utf-8', errors='replace')
            output_lines.append(decoded)

            if on_output:
                on_output(decoded)

        await process.wait()

        full_output = "".join(output_lines)
        success = process.returncode == 0

        return success, full_output

    except Exception as e:
        logger.error(f"Claude CLI error: {e}")
        process.kill()
        return False, str(e)


def extract_json_from_output(output: str) -> dict | list | None:
    """
    Extract JSON from Claude CLI output.
    Handles cases where JSON is in markdown blocks or mixed with text.
    """
    # Try to find a JSON markdown block
    json_match = re.search(r'```(?:json)?\s*([\s\S]*?)\s*```', output)
    if json_match:
        try:
            return json.loads(json_match.group(1))
        except json.JSONDecodeError:
            pass

    # Try to find a JSON array directly
    array_match = re.search(r'\[\s*\{[\s\S]*\}\s*\]', output)
    if array_match:
        try:
            return json.loads(array_match.group(0))
        except json.JSONDecodeError:
            pass

    # Try to find a JSON object
    object_match = re.search(r'\{[\s\S]*\}', output)
    if object_match:
        try:
            return json.loads(object_match.group(0))
        except json.JSONDecodeError:
            pass

    # Last try: parse entire output
    try:
        return json.loads(output.strip())
    except json.JSONDecodeError:
        return None


async def run_claude_for_json(
    prompt: str,
    cwd: str,
    timeout: int = 300,
    on_output: Callable[[str], None] | None = None
) -> tuple[bool, dict | list | None]:
    """
    Execute Claude CLI and parse JSON response.
    Used for planning (subtask generation).

    Returns:
        Tuple (success: bool, parsed_json: dict/list or None)
    """
    # Add instruction for JSON output
    json_prompt = f"""{prompt}

IMPORTANT: Your response must be ONLY valid JSON, no other text before or after.
Do not use markdown code blocks, just raw JSON."""

    success, output = await run_claude_cli(
        prompt=json_prompt,
        cwd=cwd,
        output_format="text",  # We parse ourselves
        allowed_tools=["Read", "Glob", "Grep"],  # Read-only for planning
        max_turns=10,
        timeout=timeout,
        on_output=on_output
    )

    if not success:
        return False, None

    # Extract and parse JSON
    parsed = extract_json_from_output(output)
    return parsed is not None, parsed


async def run_claude_for_coding(
    prompt: str,
    cwd: str,
    timeout: int = 600,
    on_output: Callable[[str], None] | None = None
) -> bool:
    """
    Execute Claude CLI for coding (file creation/modification).

    Returns:
        True if success, False otherwise
    """
    success, _ = await run_claude_cli(
        prompt=prompt,
        cwd=cwd,
        allowed_tools=["Edit", "Write", "Bash", "Read", "Glob", "Grep"],
        max_turns=50,
        timeout=timeout,
        on_output=on_output
    )

    return success


async def run_claude_for_review(
    prompt: str,
    cwd: str,
    timeout: int = 300,
    on_output: Callable[[str], None] | None = None
) -> tuple[bool, str]:
    """
    Execute Claude CLI for review (read + analysis).

    Returns:
        Tuple (success: bool, review_output: str)
    """
    return await run_claude_cli(
        prompt=prompt,
        cwd=cwd,
        allowed_tools=["Read", "Bash", "Glob", "Grep"],  # Read + can run tests
        max_turns=30,
        timeout=timeout,
        on_output=on_output
    )
