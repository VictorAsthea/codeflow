import asyncio
import json
import os
import re
import shutil
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Callable, Any

from backend.config import settings


def find_claude_cli():
    """Find claude CLI executable"""
    claude_path = shutil.which("claude")
    if claude_path:
        return claude_path

    npm_path = os.path.join(os.environ.get("APPDATA", ""), "npm", "claude.cmd")
    if os.path.exists(npm_path):
        return npm_path

    return "claude"


def _clear_claude_cache(working_dir: str):
    """Clear Claude cache to avoid tool_use id conflicts"""
    claude_cache_dir = Path(working_dir) / ".claude"
    if claude_cache_dir.exists():
        try:
            for item in claude_cache_dir.iterdir():
                # Keep settings files only
                if item.name not in ["settings.json", "settings.local.json"]:
                    if item.is_dir():
                        shutil.rmtree(item, ignore_errors=True)
                    else:
                        item.unlink(missing_ok=True)
            print(f"[DEBUG] Cleared Claude cache in {claude_cache_dir}")
        except Exception as e:
            print(f"[DEBUG] Failed to clear Claude cache: {e}")


def _extract_session_id(output: str) -> str | None:
    """Extract session_id from Claude's JSON output"""
    for line in output.split('\n'):
        line = line.strip()
        if not line:
            continue
        try:
            data = json.loads(line)
            if isinstance(data, dict) and "session_id" in data:
                return data["session_id"]
        except json.JSONDecodeError:
            continue
    return None


def _detect_max_turns_reached(output: str) -> bool:
    """Detect if Claude hit the max turns limit"""
    patterns = [
        r"Reached max turns",
        r"Error: Reached max turns",
        r"max.?turns.*reached",
    ]
    for pattern in patterns:
        if re.search(pattern, output, re.IGNORECASE):
            return True
    return False


def _run_claude_single_sync(
    cmd: list[str],
    working_dir: str,
    prompt: str | None,
    timeout: int = 600
) -> tuple[int, str, str | None]:
    """
    Run a single Claude CLI invocation synchronously.
    This is called via asyncio.to_thread to avoid Windows asyncio subprocess issues.

    Returns:
        tuple of (exit_code, output, session_id)
    """
    try:
        # On Windows, .CMD files need to be run through cmd.exe
        if sys.platform == 'win32' and cmd[0].lower().endswith('.cmd'):
            cmd = ['cmd.exe', '/c'] + cmd

        print(f"[DEBUG] Running command: {cmd[:5]}...")

        process = subprocess.Popen(
            cmd,
            cwd=working_dir,
            stdin=subprocess.PIPE if prompt else None,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding='utf-8',
            errors='replace'
        )

        print(f"[DEBUG] Process started with PID: {process.pid}")

        try:
            stdout, _ = process.communicate(
                input=prompt,
                timeout=timeout
            )
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
            return 124, "Timeout reached", None

        output = stdout or ""
        exit_code = process.returncode

        # Extract session_id from output
        session_id = None
        for line in output.split('\n'):
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
                if isinstance(data, dict) and "session_id" in data:
                    session_id = data["session_id"]
                    print(f"[DEBUG] Captured session_id: {session_id}")
                    break
            except json.JSONDecodeError:
                continue

        print(f"[DEBUG] Process finished with exit code: {exit_code}")
        print(f"[DEBUG] Output length: {len(output)}")

        return exit_code, output, session_id

    except FileNotFoundError as e:
        print(f"[DEBUG] FileNotFoundError: {e}")
        raise RuntimeError("Claude CLI not found. Make sure 'claude' is installed and in PATH")
    except Exception as e:
        print(f"[DEBUG] Exception: {e}")
        raise RuntimeError(f"Failed to run Claude: {str(e)}")


async def _run_claude_single(
    cmd: list[str],
    working_dir: str,
    prompt: str | None,
    on_output: Callable[[str], Any] = None,
    timeout: int = 600
) -> tuple[int, str, str | None]:
    """
    Run a single Claude CLI invocation asynchronously.
    Uses asyncio.to_thread to avoid Windows asyncio subprocess issues.

    Returns:
        tuple of (exit_code, output, session_id)
    """
    # Run the synchronous function in a thread pool
    exit_code, output, session_id = await asyncio.to_thread(
        _run_claude_single_sync,
        cmd, working_dir, prompt, timeout
    )

    # Stream output after execution if callback provided
    if on_output and output:
        line_count = 0
        for line in output.split('\n'):
            if line:
                line_count += 1
                if line_count <= 3 or line_count % 10 == 0:
                    print(f"[DEBUG] Streaming line {line_count}: {line[:100]}...")
                await on_output(line)

    return exit_code, output, session_id


async def run_claude(
    prompt: str,
    working_dir: str,
    model: str = "claude-sonnet-4-20250514",
    allowed_tools: list[str] = None,
    max_turns: int = 10,
    on_output: Callable[[str], Any] = None,
    timeout: int = 600
) -> dict:
    """
    Run Claude Code CLI and stream output with auto-resume support.

    Args:
        prompt: The prompt to send to Claude
        working_dir: Working directory for Claude
        model: Claude model to use
        allowed_tools: List of allowed tools (e.g., ["Edit", "Bash"])
        max_turns: Maximum number of turns
        on_output: Optional callback for streaming output
        timeout: Timeout in seconds (default 600)

    Returns:
        dict with exit_code and output
    """
    # Clear Claude cache to avoid tool_use id conflicts
    _clear_claude_cache(working_dir)

    claude_cmd = find_claude_cli()
    print(f"[DEBUG] Claude CLI path: {claude_cmd}")

    # Generate unique session ID to ensure fresh conversation
    session_uuid = str(uuid.uuid4())

    cmd = [
        claude_cmd,
        "--print",
        "--no-session-persistence",
        "--session-id", session_uuid,
        "--model", model,
        "--max-turns", str(max_turns),
        "--dangerously-skip-permissions"
    ]

    if allowed_tools:
        cmd.extend(["--allowedTools", ",".join(allowed_tools)])

    # Add "-" to read prompt from stdin (handles long prompts and special chars)
    cmd.append("-")

    print(f"[DEBUG] ========== CLAUDE COMMAND ==========")
    print(f"[DEBUG] Command as list (each element is a separate arg):")
    for i, arg in enumerate(cmd):
        print(f"[DEBUG]   [{i}] {arg}")
    print(f"[DEBUG] Prompt will be sent via STDIN: {prompt[:100]}...")
    print(f"[DEBUG] Working directory: {working_dir}")
    print(f"[DEBUG] Allowed tools: {allowed_tools}")
    print(f"[DEBUG] ======================================")

    # Initial run
    exit_code, output, session_id = await _run_claude_single(
        cmd, working_dir, prompt, on_output, timeout
    )

    all_output = output
    resume_count = 0
    max_retries = settings.auto_resume_max_retries
    delay_seconds = settings.auto_resume_delay_seconds

    # Auto-resume loop
    while (
        settings.auto_resume_enabled
        and _detect_max_turns_reached(output)
        and session_id
        and resume_count < max_retries
    ):
        resume_count += 1
        print(f"[AUTO-RESUME] {resume_count}/{max_retries} - continuing session {session_id}")

        if on_output:
            await on_output(f"[AUTO-RESUME] {resume_count}/{max_retries} - continuing session {session_id}")

        await asyncio.sleep(delay_seconds)

        resume_cmd = [
            claude_cmd,
            "--resume", session_id,
            "--print",
            "--dangerously-skip-permissions",
            "continue exactement où tu en étais"
        ]

        print(f"[DEBUG] ========== RESUME COMMAND ==========")
        for i, arg in enumerate(resume_cmd):
            print(f"[DEBUG]   [{i}] {arg}")
        print(f"[DEBUG] ======================================")

        exit_code, output, new_session_id = await _run_claude_single(
            resume_cmd, working_dir, None, on_output, timeout
        )

        all_output += output

        # Update session_id if a new one was returned
        if new_session_id:
            session_id = new_session_id

    if resume_count >= max_retries and _detect_max_turns_reached(output):
        print(f"[AUTO-RESUME] Max retries ({max_retries}) reached, returning error")
        if on_output:
            await on_output(f"[AUTO-RESUME] Max retries ({max_retries}) reached")

    return {
        "exit_code": exit_code,
        "output": all_output,
        "session_id": session_id,
        "resume_count": resume_count
    }


async def run_claude_with_streaming(
    prompt: str,
    working_dir: str,
    model: str = "claude-sonnet-4-20250514",
    allowed_tools: list[str] = None,
    max_turns: int = 10,
    log_callback: Callable[[str], Any] = None
) -> dict:
    """
    Run Claude with real-time log streaming

    This is a convenience wrapper around run_claude that handles
    log formatting and streaming
    """
    print(f"[DEBUG] run_claude_with_streaming called with callback: {log_callback is not None}")

    callback_count = 0

    async def output_handler(line: str):
        nonlocal callback_count
        callback_count += 1
        if callback_count <= 3 or callback_count % 10 == 0:
            print(f"[DEBUG] output_handler called (count: {callback_count}): {line[:50]}...")
        if log_callback:
            await log_callback(line.rstrip())

    result = await run_claude(
        prompt=prompt,
        working_dir=working_dir,
        model=model,
        allowed_tools=allowed_tools,
        max_turns=max_turns,
        on_output=output_handler
    )

    print(f"[DEBUG] run_claude_with_streaming finished, callback called {callback_count} times")
    return result
