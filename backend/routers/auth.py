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
