"""
Wrapper for Claude Code CLI.
Uses Pro/Max subscription, not the paid API.
Includes intelligent retry system for recoverable errors.
"""

import asyncio
import json
import re
import os
import shutil
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable, List, Optional

from backend.services.retry_manager import (
    RetryManager,
    RetryContext,
    RetryError,
    ErrorCategory,
    create_retry_manager_from_settings,
)
from backend.services.retry_metrics import (
    get_retry_metrics,
    record_retry_start,
    record_retry_attempt,
    record_retry_end,
)
from backend.models import RetryConfig, RecoverableErrorType

logger = logging.getLogger(__name__)


@dataclass
class RetryMetadata:
    """Metadata about retry attempts during CLI execution.

    This is returned alongside the result to provide visibility into
    retry behavior for logging, metrics, and user notification.
    """
    total_attempts: int = 1
    successful_attempt: int = 1
    total_retry_time: float = 0.0
    errors: list[dict] = field(default_factory=list)

    @property
    def had_retries(self) -> bool:
        """Check if any retries occurred."""
        return self.total_attempts > 1

    def to_dict(self) -> dict:
        """Convert to dictionary for serialization."""
        return {
            "total_attempts": self.total_attempts,
            "successful_attempt": self.successful_attempt,
            "total_retry_time": self.total_retry_time,
            "errors": self.errors,
            "had_retries": self.had_retries,
        }


class ErrorClassifier:
    """Classifies errors from Claude CLI process output and return codes.

    This class analyzes the output and return code from the Claude CLI
    process to determine the error type and whether it's recoverable.
    """

    # Return code patterns (Claude CLI specific)
    TIMEOUT_RETURN_CODES = {124, 137}  # timeout command, SIGKILL
    CONNECTION_ERROR_CODES = {1, 2}  # General error, often network-related

    # Output patterns for error detection
    RATE_LIMIT_PATTERNS = [
        r"rate\s*limit",
        r"too\s*many\s*requests",
        r"429",
        r"throttl",
        r"quota\s*exceeded",
        r"overloaded",
    ]

    TIMEOUT_PATTERNS = [
        r"timeout",
        r"timed?\s*out",
        r"deadline\s*exceeded",
        r"ETIMEDOUT",
        r"request\s*timeout",
    ]

    CONNECTION_PATTERNS = [
        r"connection\s*(error|refused|reset|closed)",
        r"ECONNREFUSED",
        r"ECONNRESET",
        r"network\s*(error|unreachable)",
        r"socket\s*(hang\s*up|error)",
        r"EPIPE",
        r"EOF\s*error",
        r"fetch\s*failed",
    ]

    SERVER_ERROR_PATTERNS = [
        r"502\s*(bad\s*gateway)?",
        r"503\s*(service\s*unavailable)?",
        r"504\s*(gateway\s*timeout)?",
        r"520",  # Cloudflare errors
        r"521",
        r"522",
        r"523",
        r"524",
        r"internal\s*server\s*error",
        r"server\s*error",
    ]

    AUTH_ERROR_PATTERNS = [
        r"401\s*(unauthorized)?",
        r"403\s*(forbidden)?",
        r"authentication\s*failed",
        r"invalid\s*(token|api\s*key|credentials)",
        r"not\s*authenticated",
    ]

    BAD_REQUEST_PATTERNS = [
        r"400\s*(bad\s*request)?",
        r"invalid\s*request",
        r"malformed",
        r"validation\s*error",
        r"content\s*blocked",
        r"content\s*policy",
    ]

    def __init__(self):
        """Initialize and compile regex patterns."""
        self._rate_limit_re = re.compile(
            "|".join(self.RATE_LIMIT_PATTERNS), re.IGNORECASE
        )
        self._timeout_re = re.compile(
            "|".join(self.TIMEOUT_PATTERNS), re.IGNORECASE
        )
        self._connection_re = re.compile(
            "|".join(self.CONNECTION_PATTERNS), re.IGNORECASE
        )
        self._server_error_re = re.compile(
            "|".join(self.SERVER_ERROR_PATTERNS), re.IGNORECASE
        )
        self._auth_error_re = re.compile(
            "|".join(self.AUTH_ERROR_PATTERNS), re.IGNORECASE
        )
        self._bad_request_re = re.compile(
            "|".join(self.BAD_REQUEST_PATTERNS), re.IGNORECASE
        )

    def classify(
        self,
        output: str,
        return_code: int | None = None,
        exception: Exception | None = None,
    ) -> tuple[str, ErrorCategory, int | None]:
        """Classify an error based on output, return code, and exception.

        Args:
            output: The CLI output (stdout/stderr combined)
            return_code: Process return code (if available)
            exception: Exception that occurred (if any)

        Returns:
            Tuple of (error_type, category, http_code_if_detected)
        """
        http_code = None

        # Check for asyncio.TimeoutError
        if isinstance(exception, asyncio.TimeoutError):
            return RecoverableErrorType.TIMEOUT.value, ErrorCategory.RECOVERABLE, None

        # Check return code first
        if return_code is not None:
            if return_code in self.TIMEOUT_RETURN_CODES:
                return RecoverableErrorType.TIMEOUT.value, ErrorCategory.RECOVERABLE, None

        # Analyze output text
        if output:
            # Check fatal errors first (non-recoverable)
            if self._auth_error_re.search(output):
                # Try to extract HTTP code
                if "401" in output:
                    http_code = 401
                elif "403" in output:
                    http_code = 403
                return "authentication_error", ErrorCategory.FATAL, http_code

            if self._bad_request_re.search(output):
                if "400" in output:
                    http_code = 400
                return "bad_request", ErrorCategory.FATAL, http_code

            # Check recoverable errors
            if self._rate_limit_re.search(output):
                http_code = 429 if "429" in output else None
                return RecoverableErrorType.RATE_LIMIT.value, ErrorCategory.RECOVERABLE, http_code

            if self._timeout_re.search(output):
                return RecoverableErrorType.TIMEOUT.value, ErrorCategory.RECOVERABLE, None

            if self._connection_re.search(output):
                return RecoverableErrorType.CONNECTION_ERROR.value, ErrorCategory.RECOVERABLE, None

            if self._server_error_re.search(output):
                # Extract HTTP code if present
                for code in [502, 503, 504, 520, 521, 522, 523, 524]:
                    if str(code) in output:
                        http_code = code
                        break
                return RecoverableErrorType.SERVER_ERROR.value, ErrorCategory.RECOVERABLE, http_code

        # Default: unknown error (treat as non-recoverable to be safe)
        return "unknown", ErrorCategory.UNKNOWN, None


# Global error classifier instance
_error_classifier = ErrorClassifier()


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


async def _execute_claude_cli_once(
    cmd: list[str],
    prompt: str,
    cwd: str,
    timeout: int,
    env: dict,
    on_output: Callable[[str], None] | None = None,
) -> tuple[bool, str, int | None, Exception | None]:
    """Execute Claude CLI once (internal helper for retry logic).

    Args:
        cmd: Command and arguments to execute
        prompt: The prompt to send via stdin
        cwd: Working directory
        timeout: Timeout in seconds for each line read
        env: Environment variables
        on_output: Callback for each output line

    Returns:
        Tuple of (success, output, return_code, exception)
    """
    process = None
    exception = None

    try:
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

        while True:
            try:
                line = await asyncio.wait_for(
                    process.stdout.readline(),
                    timeout=timeout
                )
            except asyncio.TimeoutError as e:
                process.kill()
                await process.wait()
                if on_output:
                    on_output("ERROR: Execution timed out\n")
                return False, "Timeout", 124, e

            if not line:
                break

            decoded = line.decode('utf-8', errors='replace')
            output_lines.append(decoded)

            if on_output:
                on_output(decoded)

        await process.wait()

        full_output = "".join(output_lines)
        return_code = process.returncode
        success = return_code == 0

        return success, full_output, return_code, None

    except Exception as e:
        logger.error(f"Claude CLI error: {e}")
        if process:
            try:
                process.kill()
                await process.wait()
            except Exception:
                pass
        return False, str(e), None, e


async def run_claude_cli(
    prompt: str,
    cwd: str,
    output_format: str = "text",
    allowed_tools: list[str] | None = None,
    max_turns: int = 50,
    timeout: int = 600,
    on_output: Callable[[str], None] | None = None,
    use_project_config: bool = True,
    retry_config: RetryConfig | None = None,
    enable_retry: bool = True,
    task_id: str | None = None,
) -> tuple[bool, str, RetryMetadata | None]:
    """
    Execute Claude Code CLI with a prompt and intelligent retry.

    Args:
        prompt: The prompt to send
        cwd: Working directory
        output_format: "text" or "json"
        allowed_tools: List of allowed tools (Edit, Write, Bash, Read)
        max_turns: Max turns
        timeout: Timeout in seconds
        on_output: Callback for each output line (streaming)
        use_project_config: If True, load tools from security.json and MCPs from mcp.json
        retry_config: Optional retry configuration (uses settings if None)
        enable_retry: Whether to enable retry logic (default True)

    Returns:
        Tuple (success: bool, output: str, retry_metadata: RetryMetadata | None)
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

    # Check if retry is enabled
    from backend.config import settings
    if not enable_retry or not settings.retry_enabled:
        # Execute without retry
        success, output, return_code, exception = await _execute_claude_cli_once(
            cmd, prompt, cwd, timeout, env, on_output
        )
        return success, output, None

    # Initialize retry manager
    if retry_config is None:
        retry_manager = create_retry_manager_from_settings()
    else:
        retry_manager = RetryManager(retry_config)

    # Track retry metadata
    retry_metadata = RetryMetadata()
    attempt = 0
    metrics_task_id = task_id or f"claude-cli-{id(prompt)}"
    retry_metrics_started = False

    while True:
        attempt += 1
        retry_metadata.total_attempts = attempt

        # Notify user of retry status (if not first attempt)
        if attempt > 1 and on_output:
            remaining = retry_manager.config.max_retries - attempt + 2
            on_output(f"\n[RETRY] Attempt {attempt}/{retry_manager.config.max_retries + 1} - {remaining} retries remaining\n")

        # Execute Claude CLI
        success, output, return_code, exception = await _execute_claude_cli_once(
            cmd, prompt, cwd, timeout, env, on_output
        )

        if success:
            retry_metadata.successful_attempt = attempt
            if attempt > 1:
                logger.info(f"Claude CLI succeeded on attempt {attempt}")
                if on_output:
                    on_output(f"\n[RETRY] Succeeded on attempt {attempt}\n")
                # Record successful retry in metrics
                if retry_metrics_started:
                    record_retry_end(
                        metrics_task_id,
                        successful=True,
                        total_attempts=attempt,
                        recovery_time=retry_metadata.total_retry_time,
                        final_error_type=None
                    )
            return True, output, retry_metadata

        # Classify the error
        error_type, category, http_code = _error_classifier.classify(
            output, return_code, exception
        )

        # Record error in metadata
        error_info = {
            "attempt": attempt,
            "error_type": error_type,
            "category": category.value,
            "http_code": http_code,
            "message": output[:500] if output else str(exception)[:500],
            "timestamp": datetime.now().isoformat(),
        }
        retry_metadata.errors.append(error_info)

        logger.warning(
            f"Claude CLI failed (attempt {attempt}): {error_type} "
            f"(category={category.value}, http_code={http_code})"
        )

        # Check if we should retry
        if category == ErrorCategory.FATAL:
            logger.error(f"Fatal error, not retrying: {error_type}")
            if on_output:
                on_output(f"\n[ERROR] Fatal error ({error_type}), not retrying\n")
            # Record failed retry in metrics if we had started retrying
            if retry_metrics_started:
                record_retry_end(
                    metrics_task_id,
                    successful=False,
                    total_attempts=attempt,
                    recovery_time=retry_metadata.total_retry_time,
                    final_error_type=error_type
                )
            else:
                # Record the error even if no retry occurred
                get_retry_metrics().record_error(error_type)
            return False, output, retry_metadata

        if category == ErrorCategory.UNKNOWN:
            logger.warning(f"Unknown error type, not retrying to be safe: {error_type}")
            if on_output:
                on_output(f"\n[ERROR] Unknown error, not retrying to be safe\n")
            # Record failed retry in metrics if we had started retrying
            if retry_metrics_started:
                record_retry_end(
                    metrics_task_id,
                    successful=False,
                    total_attempts=attempt,
                    recovery_time=retry_metadata.total_retry_time,
                    final_error_type=error_type
                )
            else:
                # Record the error even if no retry occurred
                get_retry_metrics().record_error(error_type)
            return False, output, retry_metadata

        # Check if retries exhausted
        if attempt > retry_manager.config.max_retries:
            logger.error(f"Max retries ({retry_manager.config.max_retries}) exhausted")
            if on_output:
                on_output(f"\n[ERROR] Max retries exhausted after {attempt} attempts\n")
            # Record failed retry in metrics
            if retry_metrics_started:
                record_retry_end(
                    metrics_task_id,
                    successful=False,
                    total_attempts=attempt,
                    recovery_time=retry_metadata.total_retry_time,
                    final_error_type=error_type
                )
            return False, output, retry_metadata

        # Start tracking retry metrics on first retry
        if not retry_metrics_started:
            retry_metrics_started = True
            record_retry_start(metrics_task_id, error_type)

        # Record retry attempt in metrics
        record_retry_attempt(metrics_task_id, error_type)

        # Calculate delay for next retry
        delay = retry_manager.calculate_delay(attempt - 1)
        retry_metadata.total_retry_time += delay

        if on_output:
            on_output(f"\n[RETRY] {error_type} error detected, retrying in {delay:.1f}s...\n")

        logger.info(f"Retrying in {delay:.2f}s (attempt {attempt + 1}/{retry_manager.config.max_retries + 1})")

        # Wait before retry (non-blocking)
        await asyncio.sleep(delay)


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
    on_output: Callable[[str], None] | None = None,
    enable_retry: bool = True,
    task_id: str | None = None,
) -> tuple[bool, dict | list | None, RetryMetadata | None]:
    """
    Execute Claude CLI and parse JSON response.
    Used for planning (subtask generation).

    Returns:
        Tuple (success: bool, parsed_json: dict/list or None, retry_metadata: RetryMetadata or None)
    """
    # Add instruction for JSON output
    json_prompt = f"""{prompt}

IMPORTANT: Your response must be ONLY valid JSON, no other text before or after.
Do not use markdown code blocks, just raw JSON."""

    logger.info("run_claude_for_json: Starting Claude CLI call for JSON response")

    success, output, retry_metadata = await run_claude_cli(
        prompt=json_prompt,
        cwd=cwd,
        output_format="text",  # Keep text to allow tool use during exploration
        allowed_tools=["Read", "Glob", "Grep"],  # Read-only for planning
        max_turns=15,  # More turns to allow exploration + JSON generation
        timeout=timeout,
        on_output=on_output,
        use_project_config=False,  # Disable MCPs for planning (faster, no timeout)
        enable_retry=enable_retry,
        task_id=task_id,
    )

    if not success:
        logger.error(f"run_claude_for_json: Claude CLI failed. Output: {output[:500] if output else 'None'}...")
        return False, None, retry_metadata

    logger.info(f"run_claude_for_json: Claude CLI succeeded, output length: {len(output) if output else 0}")

    # Extract and parse JSON
    parsed = extract_json_from_output(output)

    if parsed is None:
        logger.error("run_claude_for_json: Failed to extract JSON from output")
    else:
        logger.info(f"run_claude_for_json: Successfully parsed JSON, type: {type(parsed).__name__}")

    return parsed is not None, parsed, retry_metadata


async def run_claude_for_coding(
    prompt: str,
    cwd: str,
    timeout: int = 600,
    on_output: Callable[[str], None] | None = None,
    enable_retry: bool = True,
    task_id: str | None = None,
) -> tuple[bool, RetryMetadata | None]:
    """
    Execute Claude CLI for coding (file creation/modification).

    Returns:
        Tuple (success: bool, retry_metadata: RetryMetadata or None)
    """
    success, _, retry_metadata = await run_claude_cli(
        prompt=prompt,
        cwd=cwd,
        allowed_tools=["Edit", "Write", "Bash", "Read", "Glob", "Grep"],
        max_turns=50,
        timeout=timeout,
        on_output=on_output,
        enable_retry=enable_retry,
        task_id=task_id,
    )

    return success, retry_metadata


async def run_claude_for_review(
    prompt: str,
    cwd: str,
    timeout: int = 300,
    on_output: Callable[[str], None] | None = None,
    enable_retry: bool = True,
    task_id: str | None = None,
) -> tuple[bool, str, RetryMetadata | None]:
    """
    Execute Claude CLI for review (read + analysis).

    Returns:
        Tuple (success: bool, review_output: str, retry_metadata: RetryMetadata or None)
    """
    return await run_claude_cli(
        prompt=prompt,
        cwd=cwd,
        allowed_tools=["Read", "Bash", "Glob", "Grep"],  # Read + can run tests
        max_turns=30,
        timeout=timeout,
        on_output=on_output,
        enable_retry=enable_retry,
        task_id=task_id,
    )
