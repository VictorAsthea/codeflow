"""
Claude Usage Service

Fetches real-time usage data by executing the Claude CLI's /usage command.
This relies on the user having already authenticated via `claude login`.
"""

import asyncio
import logging
import re
import sys
import threading
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)


class ClaudeUsageService:
    """Service to fetch Claude CLI usage data."""

    def __init__(self):
        self.timeout = 20  # seconds
        self.is_windows = sys.platform == 'win32'
        self._cache = None
        self._cache_time = None
        self._cache_ttl = 60  # Cache for 60 seconds

    async def get_usage(self) -> dict:
        """
        Get usage data from Claude CLI.

        Returns dict with:
        - session_percentage: int (% used)
        - session_reset_text: str
        - weekly_percentage: int (% used)
        - weekly_reset_text: str
        - sonnet_percentage: int (% used)
        - sonnet_reset_text: str
        - last_updated: str (ISO timestamp)
        - error: str | None
        """
        # Check cache
        if self._cache and self._cache_time:
            elapsed = (datetime.now() - self._cache_time).total_seconds()
            if elapsed < self._cache_ttl:
                return self._cache

        try:
            output = await self._execute_usage_command()
            result = self._parse_usage_output(output)
            result["last_updated"] = datetime.now().isoformat()
            result["error"] = None

            # Cache result
            self._cache = result
            self._cache_time = datetime.now()

            return result
        except Exception as e:
            logger.error(f"Failed to get usage: {e}")
            return {
                "session_percentage": None,
                "session_reset_text": None,
                "weekly_percentage": None,
                "weekly_reset_text": None,
                "sonnet_percentage": None,
                "sonnet_reset_text": None,
                "last_updated": datetime.now().isoformat(),
                "error": str(e)
            }

    async def _execute_usage_command(self) -> str:
        """Execute claude CLI and get /usage output."""
        if self.is_windows:
            return await self._execute_windows()
        else:
            return await self._execute_unix()

    async def _execute_windows(self) -> str:
        """Windows implementation using pywinpty with cmd.exe wrapper."""
        try:
            import winpty
        except ImportError:
            raise ImportError("pywinpty not installed. Run: pip install pywinpty")

        import os
        loop = asyncio.get_event_loop()
        result = {"output": "", "error": None}
        cwd = os.getcwd()

        def run_pty():
            import time
            pty_process = None

            try:
                # Use cmd.exe wrapper for proper PTY handling
                cmd = f'cmd.exe /c claude --add-dir "{cwd}"'
                pty_process = winpty.PtyProcess.spawn(cmd)
                logger.info("Claude CLI spawned via cmd.exe")

                # Thread to read output
                read_buffer = []
                stop_reading = threading.Event()
                got_repl = threading.Event()

                def reader():
                    while not stop_reading.is_set():
                        try:
                            if pty_process.isalive():
                                data = pty_process.read(1024)
                                if data:
                                    read_buffer.append(data)
                                    # Check for REPL ready
                                    buf = ''.join(read_buffer)
                                    if '?' in buf and 'shortcuts' in buf:
                                        got_repl.set()
                        except EOFError:
                            break
                        except Exception:
                            break

                reader_thread = threading.Thread(target=reader, daemon=True)
                reader_thread.start()

                # Wait for REPL to be ready
                got_repl.wait(timeout=10)
                time.sleep(1)
                logger.info("REPL ready")

                # Send /usage command
                pty_process.write('/usage\r')
                time.sleep(1.5)
                # Send Enter to confirm autocomplete selection
                pty_process.write('\r')
                logger.info("Sent /usage command")

                # Wait for usage data
                start = time.time()
                while time.time() - start < 8:
                    buffer = ''.join(read_buffer)
                    if 'Current session' in buffer and '% left' in buffer:
                        logger.info("Usage data detected")
                        time.sleep(2)  # Wait for complete output
                        break
                    time.sleep(0.3)

                # Stop reader and get final buffer
                stop_reading.set()
                time.sleep(0.3)
                result["output"] = ''.join(read_buffer)
                logger.info(f"Got {len(result['output'])} chars of output")

                # Exit CLI
                try:
                    pty_process.write('\x1b')  # ESC
                    time.sleep(0.3)
                    pty_process.terminate()
                except Exception:
                    pass

            except Exception as e:
                result["error"] = str(e)
                logger.error(f"PTY error: {e}")
            finally:
                if pty_process:
                    try:
                        pty_process.terminate()
                    except Exception:
                        pass

        # Run in executor with timeout
        try:
            await asyncio.wait_for(
                loop.run_in_executor(None, run_pty),
                timeout=self.timeout
            )
        except asyncio.TimeoutError:
            raise TimeoutError("Claude CLI timed out")

        if result["error"]:
            raise Exception(result["error"])

        return result["output"]

    async def _execute_unix(self) -> str:
        """Unix implementation using pexpect."""
        try:
            import pexpect
        except ImportError:
            raise ImportError("pexpect not installed. Run: pip install pexpect")

        loop = asyncio.get_event_loop()

        def run_pexpect():
            import time
            try:
                child = pexpect.spawn('claude', timeout=self.timeout)

                # Wait for REPL prompt
                child.expect(['❯', r'\? for shortcuts'], timeout=15)

                # Send /usage command
                child.sendline('/usage')

                # Wait for usage output
                child.expect('Current session', timeout=10)
                child.expect(['% left', '% used'], timeout=5)

                # Wait for full output
                time.sleep(2)

                # Get all output
                output = child.before.decode('utf-8', errors='ignore')
                output += child.after.decode('utf-8', errors='ignore') if child.after else ''

                # Read any remaining output
                try:
                    remaining = child.read_nonblocking(4096, timeout=1)
                    output += remaining.decode('utf-8', errors='ignore')
                except Exception:
                    pass

                # Exit
                child.sendcontrol('c')
                child.close()

                return output

            except Exception as e:
                logger.error(f"pexpect error: {e}")
                raise

        return await loop.run_in_executor(None, run_pexpect)

    def _parse_usage_output(self, raw_output: str) -> dict:
        """Parse Claude CLI usage output."""

        # Strip ANSI codes
        output = self._strip_ansi(raw_output)
        lines = [l.strip() for l in output.split('\n') if l.strip()]

        result = {
            "session_percentage": None,
            "session_reset_text": None,
            "weekly_percentage": None,
            "weekly_reset_text": None,
            "sonnet_percentage": None,
            "sonnet_reset_text": None,
        }

        # Parse sections
        session = self._parse_section(lines, 'Current session')
        weekly = self._parse_section(lines, 'Current week (all models)')

        # Try different labels for Sonnet/Opus
        sonnet = self._parse_section(lines, 'Current week (Sonnet only)')
        if sonnet['percentage'] is None:
            sonnet = self._parse_section(lines, 'Current week (Sonnet)')
        if sonnet['percentage'] is None:
            sonnet = self._parse_section(lines, 'Current week (Opus)')

        result['session_percentage'] = session['percentage']
        result['session_reset_text'] = session['reset_text']
        result['weekly_percentage'] = weekly['percentage']
        result['weekly_reset_text'] = weekly['reset_text']
        result['sonnet_percentage'] = sonnet['percentage']
        result['sonnet_reset_text'] = sonnet['reset_text']

        return result

    def _parse_section(self, lines: list, section_label: str) -> dict:
        """Parse a section to extract percentage and reset text."""

        result = {'percentage': None, 'reset_text': None}

        # Find section (search from end, as terminal output may have refreshes)
        section_idx = -1
        for i in range(len(lines) - 1, -1, -1):
            if section_label.lower() in lines[i].lower():
                section_idx = i
                break

        if section_idx == -1:
            return result

        # Search next 5 lines
        search_window = lines[section_idx:section_idx + 5]

        for line in search_window:
            # Extract percentage
            if result['percentage'] is None:
                match = re.search(r'(\d{1,3})\s*%\s*(left|used|remaining)', line, re.I)
                if match:
                    value = int(match.group(1))
                    is_left = match.group(2).lower() in ['left', 'remaining']
                    # Convert to "used" percentage
                    result['percentage'] = (100 - value) if is_left else value

            # Extract reset text
            if result['reset_text'] is None and 'reset' in line.lower():
                match = re.search(r'(resets?.*)$', line, re.I)
                if match:
                    reset_text = match.group(1)
                    # Clean up
                    reset_text = re.sub(r'\d{1,3}\s*%\s*(left|used|remaining)', '', reset_text, flags=re.I)
                    reset_text = reset_text.strip()
                    # Remove timezone in parentheses
                    reset_text = re.sub(r'\s*\([A-Za-z_/]+\)\s*$', '', reset_text)
                    result['reset_text'] = reset_text.strip()

        return result

    def _strip_ansi(self, text: str) -> str:
        """Remove ANSI escape codes."""
        # CSI sequences
        text = re.sub(r'\x1B\[[0-9;?]*[A-Za-z@]', '', text)
        # OSC sequences
        text = re.sub(r'\x1B\][^\x07\x1B]*(?:\x07|\x1B\\)?', '', text)
        # Other ESC sequences
        text = re.sub(r'\x1B[A-Za-z]', '', text)
        # Carriage returns
        text = text.replace('\r\n', '\n').replace('\r', '\n')
        # Control characters
        text = re.sub(r'[\x00-\x08\x0B-\x1F\x7F]', '', text)
        return text


# Singleton
_usage_service: Optional[ClaudeUsageService] = None


def get_usage_service() -> ClaudeUsageService:
    """Get singleton usage service instance."""
    global _usage_service
    if _usage_service is None:
        _usage_service = ClaudeUsageService()
    return _usage_service
