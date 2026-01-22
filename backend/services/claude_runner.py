import asyncio
import json
import os
import shutil
from typing import Callable, Any


def find_claude_cli():
    """Find claude CLI executable"""
    claude_path = shutil.which("claude")
    if claude_path:
        return claude_path

    npm_path = os.path.join(os.environ.get("APPDATA", ""), "npm", "claude.cmd")
    if os.path.exists(npm_path):
        return npm_path

    return "claude"


async def run_claude(
    prompt: str,
    working_dir: str,
    model: str = "claude-sonnet-4-20250514",
    allowed_tools: list[str] = None,
    max_turns: int = 10,
    on_output: Callable[[str], Any] = None
) -> dict:
    """
    Run Claude Code CLI and stream output

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
        "--model", model,
        "--max-turns", str(max_turns),
        "--permission-mode", "bypassPermissions"
    ]

    if allowed_tools:
        for tool in allowed_tools:
            cmd.extend(["--allowedTools", tool])

    print(f"[DEBUG] ========== CLAUDE COMMAND ==========")
    print(f"[DEBUG] Command as list (each element is a separate arg):")
    for i, arg in enumerate(cmd):
        print(f"[DEBUG]   [{i}] {arg}")
    print(f"[DEBUG] Prompt will be sent via STDIN: {prompt[:100]}...")
    print(f"[DEBUG] Working directory: {working_dir}")
    print(f"[DEBUG] Allowed tools: {allowed_tools}")
    print(f"[DEBUG] ======================================")

    try:
        process = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=working_dir,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )

        # Send prompt via stdin
        process.stdin.write(prompt.encode('utf-8'))
        await process.stdin.drain()
        process.stdin.close()

        print(f"[DEBUG] Process started with PID: {process.pid}")

        output_lines = []
        line_count = 0

        async def read_stream(stream, callback, stream_name):
            nonlocal line_count
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
                if callback:
                    await callback(line_str.rstrip())

        await asyncio.gather(
            read_stream(process.stdout, on_output, "STDOUT"),
            read_stream(process.stderr, on_output, "STDERR")
        )

        await process.wait()

        print(f"[DEBUG] Process finished with exit code: {process.returncode}")
        print(f"[DEBUG] Total lines captured: {line_count}")

        return {
            "exit_code": process.returncode,
            "output": "".join(output_lines)
        }

    except FileNotFoundError as e:
        print(f"[DEBUG] FileNotFoundError: {e}")
        raise RuntimeError("Claude CLI not found. Make sure 'claude' is installed and in PATH")
    except Exception as e:
        print(f"[DEBUG] Exception: {e}")
        raise RuntimeError(f"Failed to run Claude: {str(e)}")


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
