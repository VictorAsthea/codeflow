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
from typing import Callable, List, Optional

logger = logging.getLogger(__name__)


def get_project_allowed_tools(project_path: str, base_tools: List[str]) -> List[str]:
    """
    Construit la liste des outils autorisés en combinant les outils de base
    avec les commandes Bash autorisées depuis security.json.

    Args:
        project_path: Chemin du projet
        base_tools: Outils de base (Edit, Write, Read, etc.)

    Returns:
        Liste complète des outils autorisés
    """
    from backend.services.project_config_service import get_project_config

    try:
        config = get_project_config(project_path)
        allowed_commands = config.get_allowed_commands()

        if not allowed_commands:
            return base_tools

        # Format: Bash(cmd1:*), Bash(cmd2:*), etc.
        bash_tools = [f"Bash({cmd}:*)" for cmd in allowed_commands]

        # Combiner les outils de base + commandes bash autorisées
        return base_tools + bash_tools

    except Exception as e:
        logger.warning(f"Failed to load security config: {e}")
        return base_tools


def get_mcp_args(project_path: str) -> List[str]:
    """
    Construit les arguments MCP depuis mcp.json.

    Converts Codeflow mcp.json format to Claude CLI format and passes as JSON string.

    Returns:
        Liste d'arguments pour --mcp-config
    """
    try:
        # Load Codeflow mcp.json
        mcp_config_path = os.path.join(project_path, ".codeflow", "mcp.json")
        if not os.path.exists(mcp_config_path):
            return []

        with open(mcp_config_path, 'r', encoding='utf-8') as f:
            codeflow_config = json.load(f)

        servers = codeflow_config.get("servers", {})
        if not servers:
            return []

        # Convert to Claude CLI format (only enabled servers)
        claude_mcp_servers = {}
        for name, server in servers.items():
            if server.get("enabled", False):
                claude_mcp_servers[name] = {
                    "command": server.get("command", ""),
                    "args": server.get("args", [])
                }

        if not claude_mcp_servers:
            return []

        # Build the JSON config string for --mcp-config
        claude_config = {"mcpServers": claude_mcp_servers}
        config_json = json.dumps(claude_config)

        logger.info(f"MCP config: {len(claude_mcp_servers)} servers enabled")
        return ["--mcp-config", config_json]

    except Exception as e:
        logger.warning(f"Failed to load MCP config: {e}")
        return []


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
    on_output: Callable[[str], None] | None = None,
    use_project_config: bool = True
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
        use_project_config: If True, load tools from security.json and MCPs from mcp.json

    Returns:
        Tuple (success: bool, output: str)
    """
    claude_cmd = get_claude_command()
    cmd = [claude_cmd, "--print", "--no-session-persistence"]

    if output_format == "json":
        cmd.extend(["--output-format", "json"])

    # Build allowed tools list
    if allowed_tools:
        if use_project_config:
            # Enhance with project-specific bash commands
            allowed_tools = get_project_allowed_tools(cwd, allowed_tools)
        cmd.extend(["--allowedTools", ",".join(allowed_tools)])

    # Add MCP servers from project config
    mcp_count = 0
    if use_project_config:
        mcp_args = get_mcp_args(cwd)
        cmd.extend(mcp_args)
        mcp_count = len(mcp_args) // 2

    cmd.extend(["--max-turns", str(max_turns)])

    # Prompt will be passed via stdin (handles long prompts and special chars)
    cmd.append("-")  # Read from stdin

    # Log configuration
    logger.info(f"Running Claude CLI: {claude_cmd} (max_turns={max_turns}, timeout={timeout}s, mcps={mcp_count})")
    if allowed_tools:
        bash_count = sum(1 for t in allowed_tools if t.startswith("Bash("))
        logger.debug(f"Allowed tools: {len(allowed_tools)} total, {bash_count} bash commands")

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
    if not output or not output.strip():
        logger.warning("extract_json_from_output: Empty output")
        return None

    # Try to find a JSON markdown block
    json_match = re.search(r'```(?:json)?\s*([\s\S]*?)\s*```', output)
    if json_match:
        try:
            result = json.loads(json_match.group(1))
            logger.debug("JSON extracted from markdown block")
            return result
        except json.JSONDecodeError as e:
            logger.debug(f"Failed to parse markdown JSON: {e}")

    # Try to find a JSON array directly (more specific pattern)
    array_match = re.search(r'\[\s*\{[\s\S]*?\}\s*(?:,\s*\{[\s\S]*?\}\s*)*\]', output)
    if array_match:
        try:
            result = json.loads(array_match.group(0))
            logger.debug("JSON extracted as array")
            return result
        except json.JSONDecodeError as e:
            logger.debug(f"Failed to parse array JSON: {e}")

    # Try to find any JSON array
    array_match2 = re.search(r'\[[\s\S]*\]', output)
    if array_match2:
        try:
            result = json.loads(array_match2.group(0))
            logger.debug("JSON extracted as simple array")
            return result
        except json.JSONDecodeError as e:
            logger.debug(f"Failed to parse simple array JSON: {e}")

    # Try to find a JSON object
    object_match = re.search(r'\{[\s\S]*\}', output)
    if object_match:
        try:
            result = json.loads(object_match.group(0))
            logger.debug("JSON extracted as object")
            return result
        except json.JSONDecodeError as e:
            logger.debug(f"Failed to parse object JSON: {e}")

    # Last try: parse entire output
    try:
        result = json.loads(output.strip())
        logger.debug("JSON parsed from entire output")
        return result
    except json.JSONDecodeError as e:
        logger.warning(f"extract_json_from_output: All parsing methods failed. Output preview: {output[:500]}...")
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

    logger.info("run_claude_for_json: Starting Claude CLI call for JSON response")

    success, output = await run_claude_cli(
        prompt=json_prompt,
        cwd=cwd,
        output_format="text",  # Keep text to allow tool use during exploration
        allowed_tools=["Read", "Glob", "Grep"],  # Read-only for planning
        max_turns=15,  # More turns to allow exploration + JSON generation
        timeout=timeout,
        on_output=on_output,
        use_project_config=False  # Disable MCPs for planning (faster, no timeout)
    )

    if not success:
        logger.error(f"run_claude_for_json: Claude CLI failed. Output: {output[:500] if output else 'None'}...")
        return False, None

    logger.info(f"run_claude_for_json: Claude CLI succeeded, output length: {len(output) if output else 0}")

    # Extract and parse JSON
    parsed = extract_json_from_output(output)

    if parsed is None:
        logger.error("run_claude_for_json: Failed to extract JSON from output")
    else:
        logger.info(f"run_claude_for_json: Successfully parsed JSON, type: {type(parsed).__name__}")

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
