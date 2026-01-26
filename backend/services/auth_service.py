"""
Authentication service for managing user credentials.

Supports two methods:
- Subscription: Claude Pro/Max via CLI OAuth
- API Key: Direct Anthropic SDK usage
"""

import asyncio
import json
import logging
import os
import shutil
import stat
import time
from enum import Enum
from pathlib import Path
from typing import Optional

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


class AuthMethod(str, Enum):
    SUBSCRIPTION = "subscription"
    API_KEY = "api_key"


class AuthService:
    """
    Service for managing authentication methods.

    Supports:
    - Subscription: Uses Claude CLI OAuth tokens (managed by CLI)
    - API Key: Direct Anthropic SDK usage with stored key
    """

    CREDENTIALS_DIR = Path.home() / ".codeflow"
    CREDENTIALS_FILE = CREDENTIALS_DIR / "credentials.json"
    CLAUDE_CREDENTIALS_FILE = Path.home() / ".claude" / ".credentials.json"

    def __init__(self):
        self._ensure_credentials_dir()

    def _ensure_credentials_dir(self):
        """Ensure the credentials directory exists with proper permissions."""
        if not self.CREDENTIALS_DIR.exists():
            self.CREDENTIALS_DIR.mkdir(parents=True, exist_ok=True)
            # Set directory permissions (Unix only)
            if os.name != 'nt':
                os.chmod(self.CREDENTIALS_DIR, stat.S_IRWXU)

    async def get_auth_status(self) -> dict:
        """
        Check all authentication methods and return status.

        Returns:
            dict with keys:
            - authenticated: bool - True if any method is available
            - method: str | None - The preferred method to use
            - subscription_available: bool
            - api_key_available: bool
        """
        subscription = await self.check_subscription()
        api_key = await self.check_api_key()

        # Determine preferred method (subscription takes priority)
        method = None
        if subscription:
            method = AuthMethod.SUBSCRIPTION.value
        elif api_key:
            method = AuthMethod.API_KEY.value

        return {
            "authenticated": subscription or api_key,
            "method": method,
            "subscription_available": subscription,
            "api_key_available": api_key
        }

    async def check_subscription(self) -> bool:
        """
        Check if Claude CLI is authenticated via subscription.

        Returns:
            True if subscription is available and valid
        """
        try:
            # Check if credentials file exists
            if not self.CLAUDE_CREDENTIALS_FILE.exists():
                logger.debug("Claude CLI credentials file not found")
                return False

            # Read and validate credentials file
            with open(self.CLAUDE_CREDENTIALS_FILE, 'r', encoding='utf-8') as f:
                credentials = json.load(f)

            # Check for OAuth credentials
            oauth = credentials.get("claudeAiOauth", {})
            if not oauth:
                logger.debug("No OAuth credentials found")
                return False

            # Check if token exists and is not expired
            access_token = oauth.get("accessToken")
            expires_at = oauth.get("expiresAt", 0)

            if not access_token:
                logger.debug("No access token found")
                return False

            # Check expiration (expiresAt is in milliseconds)
            current_time_ms = int(time.time() * 1000)
            if expires_at < current_time_ms:
                logger.debug("Access token expired")
                return False

            # Valid subscription found
            subscription_type = oauth.get("subscriptionType", "unknown")
            logger.info(f"Subscription detected: {subscription_type}")
            return True

        except json.JSONDecodeError:
            logger.warning("Invalid credentials file format")
            return False
        except Exception as e:
            logger.warning(f"Subscription check failed: {e}")
            return False

    async def check_api_key(self) -> bool:
        """
        Check if a valid API key exists.

        Returns:
            True if a valid API key is stored and working
        """
        api_key = await self.get_api_key()
        if not api_key:
            return False

        # Validate the key with a minimal API call
        return await self.validate_api_key(api_key)

    async def validate_api_key(self, key: str) -> bool:
        """
        Test API key with a minimal SDK call.

        Args:
            key: The API key to validate

        Returns:
            True if the key is valid
        """
        try:
            import anthropic

            client = anthropic.Anthropic(api_key=key)

            # Make a minimal call to validate the key
            # Using count_tokens is the cheapest operation
            response = client.messages.count_tokens(
                model="claude-haiku-4-20250514",
                messages=[{"role": "user", "content": "test"}]
            )

            logger.debug(f"API key validation successful")
            return True

        except ImportError:
            logger.error("anthropic package not installed")
            return False
        except Exception as e:
            error_msg = str(e).lower()
            if "invalid" in error_msg or "unauthorized" in error_msg or "authentication" in error_msg:
                logger.warning(f"API key validation failed: invalid key")
            else:
                logger.warning(f"API key validation failed: {e}")
            return False

    async def save_api_key(self, key: str) -> dict:
        """
        Validate and save API key.

        Args:
            key: The API key to save

        Returns:
            dict with success status and optional error
        """
        # Validate the key first
        is_valid = await self.validate_api_key(key)

        if not is_valid:
            return {
                "success": False,
                "error": "Invalid API key. Please check your key and try again."
            }

        try:
            # Load existing credentials or create new
            credentials = {}
            if self.CREDENTIALS_FILE.exists():
                with open(self.CREDENTIALS_FILE, 'r', encoding='utf-8') as f:
                    credentials = json.load(f)

            # Update with new API key
            credentials["api_key"] = key

            # Save credentials
            with open(self.CREDENTIALS_FILE, 'w', encoding='utf-8') as f:
                json.dump(credentials, f, indent=2)

            # Set file permissions (Unix only)
            if os.name != 'nt':
                os.chmod(self.CREDENTIALS_FILE, stat.S_IRUSR | stat.S_IWUSR)

            logger.info("API key saved successfully")
            return {"success": True}

        except Exception as e:
            logger.error(f"Failed to save API key: {e}")
            return {
                "success": False,
                "error": f"Failed to save credentials: {str(e)}"
            }

    async def get_api_key(self) -> Optional[str]:
        """
        Get stored API key.

        Returns:
            The API key if stored, None otherwise
        """
        try:
            if not self.CREDENTIALS_FILE.exists():
                return None

            with open(self.CREDENTIALS_FILE, 'r', encoding='utf-8') as f:
                credentials = json.load(f)

            return credentials.get("api_key")

        except Exception as e:
            logger.warning(f"Failed to read API key: {e}")
            return None

    async def get_preferred_method(self) -> Optional[AuthMethod]:
        """
        Get the authentication method to use for API calls.

        Returns:
            AuthMethod if authenticated, None otherwise
        """
        status = await self.get_auth_status()

        if not status["authenticated"]:
            return None

        return AuthMethod(status["method"])

    async def clear_credentials(self) -> dict:
        """
        Clear stored API key.

        Returns:
            dict with success status
        """
        try:
            if self.CREDENTIALS_FILE.exists():
                with open(self.CREDENTIALS_FILE, 'r', encoding='utf-8') as f:
                    credentials = json.load(f)

                # Remove only the API key, keep other settings
                if "api_key" in credentials:
                    del credentials["api_key"]

                with open(self.CREDENTIALS_FILE, 'w', encoding='utf-8') as f:
                    json.dump(credentials, f, indent=2)

                logger.info("API key cleared")

            return {"success": True}

        except Exception as e:
            logger.error(f"Failed to clear credentials: {e}")
            return {
                "success": False,
                "error": f"Failed to clear credentials: {str(e)}"
            }

    async def open_claude_login_page(self) -> dict:
        """
        Open Claude.ai login page in the browser.

        Returns:
            dict with success status
        """
        import webbrowser

        try:
            webbrowser.open("https://claude.ai/login")
            logger.info("Opened Claude.ai login page")
            return {"success": True}
        except Exception as e:
            logger.error(f"Failed to open browser: {e}")
            return {
                "success": False,
                "error": f"Failed to open browser: {str(e)}"
            }


# Singleton instance
_auth_service: Optional[AuthService] = None


def get_auth_service() -> AuthService:
    """Get the singleton AuthService instance."""
    global _auth_service
    if _auth_service is None:
        _auth_service = AuthService()
    return _auth_service
