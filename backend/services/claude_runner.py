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

    cmd = [
        claude_cmd,
        "-p", prompt,
        "--model", model,
        "--maxTurns", str(max_turns)
    ]

    if allowed_tools:
        for tool in allowed_tools:
            cmd.extend(["--allowedTools", tool])

    try:
        process = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=working_dir,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )

        output_lines = []

        async def read_stream(stream, callback):
            while True:
                line = await stream.readline()
                if not line:
                    break
                line_str = line.decode('utf-8', errors='ignore')
                output_lines.append(line_str)
                if callback:
                    await callback(line_str)

        await asyncio.gather(
            read_stream(process.stdout, on_output),
            read_stream(process.stderr, on_output)
        )

        await process.wait()

        return {
            "exit_code": process.returncode,
            "output": "".join(output_lines)
        }

    except FileNotFoundError:
        raise RuntimeError("Claude CLI not found. Make sure 'claude' is installed and in PATH")
    except Exception as e:
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
    async def output_handler(line: str):
        if log_callback:
            await log_callback(line.rstrip())

    return await run_claude(
        prompt=prompt,
        working_dir=working_dir,
        model=model,
        allowed_tools=allowed_tools,
        max_turns=max_turns,
        on_output=output_handler
    )
