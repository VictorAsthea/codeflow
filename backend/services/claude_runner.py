import asyncio
import json
import os
import re
import shutil
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


async def _run_claude_single(
    cmd: list[str],
    working_dir: str,
    prompt: str | None,
    on_output: Callable[[str], Any] = None
) -> tuple[int, str, str | None]:
    """
    Run a single Claude CLI invocation.

    Returns:
        tuple of (exit_code, output, session_id)
    """
    try:
        process = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=working_dir,
            stdin=asyncio.subprocess.PIPE if prompt else None,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )

        if prompt:
            process.stdin.write(prompt.encode('utf-8'))
            await process.stdin.drain()
            process.stdin.close()

        print(f"[DEBUG] Process started with PID: {process.pid}")

        output_lines = []
        line_count = 0
        session_id = None

        async def read_stream(stream, callback, stream_name):
            nonlocal line_count, session_id
            while True:
                line = await stream.readline()
                if not line:
                    print(f"[DEBUG] {stream_name} stream ended")
                    break
                line_str = line.decode('utf-8', errors='ignore')
                if not line_str:
                    continue

                line_count += 1
                if line_count <= 3 or line_count % 10 == 0:
                    print(f"[DEBUG] {stream_name} line {line_count}: {line_str[:100]}...")

                output_lines.append(line_str)

                # Try to extract session_id from JSON lines
                if session_id is None:
                    try:
                        data = json.loads(line_str.strip())
                        if isinstance(data, dict) and "session_id" in data:
                            session_id = data["session_id"]
                            print(f"[DEBUG] Captured session_id: {session_id}")
                    except json.JSONDecodeError:
                        pass

                if callback:
                    await callback(line_str.rstrip())

        await asyncio.gather(
            read_stream(process.stdout, on_output, "STDOUT"),
            read_stream(process.stderr, on_output, "STDERR")
        )

        await process.wait()

        print(f"[DEBUG] Process finished with exit code: {process.returncode}")
        print(f"[DEBUG] Total lines captured: {line_count}")

        return process.returncode, "".join(output_lines), session_id

    except FileNotFoundError as e:
        print(f"[DEBUG] FileNotFoundError: {e}")
        raise RuntimeError("Claude CLI not found. Make sure 'claude' is installed and in PATH")
    except Exception as e:
        print(f"[DEBUG] Exception: {e}")
        raise RuntimeError(f"Failed to run Claude: {str(e)}")


async def run_claude(
    prompt: str,
    working_dir: str,
    model: str = "claude-sonnet-4-20250514",
    allowed_tools: list[str] = None,
    max_turns: int = 10,
    on_output: Callable[[str], Any] = None
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

    Returns:
        dict with exit_code and output
    """
    claude_cmd = find_claude_cli()
    print(f"[DEBUG] Claude CLI path: {claude_cmd}")

    cmd = [
        claude_cmd,
        "--print",
        "--no-session-persistence",
        "--model", model,
        "--max-turns", str(max_turns),
        "--dangerously-skip-permissions"
    ]

    if allowed_tools:
        cmd.extend(["--allowedTools", ",".join(allowed_tools)])

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
        cmd, working_dir, prompt, on_output
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
            resume_cmd, working_dir, None, on_output
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
