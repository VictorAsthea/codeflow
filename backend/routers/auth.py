"""
Authentication router for managing user credentials.

Provides endpoints for:
- Checking auth status
- Setting/clearing API keys
- Verifying subscription status
"""

import logging
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from backend.services.auth_service import get_auth_service
from backend.services.claude_usage_service import get_usage_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])


class ApiKeyRequest(BaseModel):
    """Request body for setting API key."""
    key: str = Field(..., min_length=1, max_length=500)


class AuthStatusResponse(BaseModel):
    """Response for auth status endpoint."""
    authenticated: bool
    method: str | None
    subscription_available: bool
    api_key_available: bool


class ApiKeyResponse(BaseModel):
    """Response for API key operations."""
    success: bool
    error: str | None = None


class LoginCliResponse(BaseModel):
    """Response for CLI login operation."""
    success: bool
    message: str | None = None
    error: str | None = None


class RateLimitResponse(BaseModel):
    """Response for rate limit status."""
    method: str | None = None
    tier: str | None = None
    requests_limit: int | None = None
    requests_remaining: int | None = None
    requests_reset: str | None = None
    tokens_limit: int | None = None
    tokens_remaining: int | None = None
    tokens_reset: str | None = None


class UsageResponse(BaseModel):
    """Response for Claude CLI usage data."""
    session_percentage: int | None = None
    session_reset_text: str | None = None
    weekly_percentage: int | None = None
    weekly_reset_text: str | None = None
    sonnet_percentage: int | None = None
    sonnet_reset_text: str | None = None
    last_updated: str | None = None
    error: str | None = None


@router.get("/status", response_model=AuthStatusResponse)
async def get_status():
    """
    Get current authentication status.

    Returns:
        AuthStatusResponse with authentication details
    """
    try:
        service = get_auth_service()
        status = await service.get_auth_status()
        return AuthStatusResponse(**status)
    except Exception as e:
        logger.error(f"Failed to get auth status: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api-key", response_model=ApiKeyResponse)
async def set_api_key(request: ApiKeyRequest):
    """
    Validate and save API key.

    Args:
        request: ApiKeyRequest with the API key

    Returns:
        ApiKeyResponse with success status
    """
    try:
        service = get_auth_service()
        result = await service.save_api_key(request.key)

        if not result["success"]:
            raise HTTPException(status_code=400, detail=result.get("error", "Invalid API key"))

        return ApiKeyResponse(**result)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to save API key: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/api-key", response_model=ApiKeyResponse)
async def clear_api_key():
    """
    Remove stored API key.

    Returns:
        ApiKeyResponse with success status
    """
    try:
        service = get_auth_service()
        result = await service.clear_credentials()
        return ApiKeyResponse(**result)
    except Exception as e:
        logger.error(f"Failed to clear API key: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/verify-subscription", response_model=AuthStatusResponse)
async def verify_subscription():
    """
    Re-check subscription status.

    Use this after the user runs `claude login` in their terminal.

    Returns:
        AuthStatusResponse with updated authentication details
    """
    try:
        service = get_auth_service()
        status = await service.get_auth_status()
        return AuthStatusResponse(**status)
    except Exception as e:
        logger.error(f"Failed to verify subscription: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/login-cli", response_model=LoginCliResponse)
async def login_cli():
    """
    Open Claude.ai login page in browser.

    Returns:
        LoginCliResponse with success status
    """
    try:
        service = get_auth_service()
        result = await service.open_claude_login_page()

        if not result["success"]:
            raise HTTPException(status_code=400, detail=result.get("error", "Failed to open browser"))

        return LoginCliResponse(success=True, message="Browser opened")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to open login page: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/rate-limit", response_model=RateLimitResponse)
async def get_rate_limit():
    """
    Get current rate limit status.

    For subscription: reads from credentials file
    For API key: makes minimal API call to get headers

    Returns:
        RateLimitResponse with rate limit info
    """
    try:
        service = get_auth_service()
        result = await service.get_rate_limit_status()
        return RateLimitResponse(**result)
    except Exception as e:
        logger.error(f"Failed to get rate limit: {e}")
        return RateLimitResponse()


@router.get("/usage", response_model=UsageResponse)
async def get_usage():
    """
    Get real-time usage data from Claude CLI.

    Executes `claude /usage` command and parses the output.
    Returns session and weekly usage percentages with reset times.

    Returns:
        UsageResponse with usage data
    """
    try:
        service = get_usage_service()
        result = await service.get_usage()
        return UsageResponse(**result)
    except Exception as e:
        logger.error(f"Failed to get usage: {e}")
        return UsageResponse(error=str(e))
