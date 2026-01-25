from fastapi import APIRouter, Request, HTTPException, Header
import hashlib
import hmac
import logging
from typing import Optional

router = APIRouter()
logger = logging.getLogger(__name__)


async def verify_github_signature(payload_body: bytes, signature_header: Optional[str], secret: str) -> bool:
    """Verify GitHub webhook signature"""
    if not signature_header:
        return False

    try:
        hash_algorithm, github_signature = signature_header.split('=')
    except ValueError:
        return False

    if hash_algorithm != 'sha256':
        return False

    mac = hmac.new(secret.encode(), msg=payload_body, digestmod=hashlib.sha256)
    return hmac.compare_digest(mac.hexdigest(), github_signature)


@router.post("/webhooks/github")
async def github_webhook(
    request: Request,
    x_github_event: Optional[str] = Header(None),
    x_hub_signature_256: Optional[str] = Header(None)
):
    """Handle GitHub webhook events for PR status changes"""
    from backend.config import settings

    body = await request.body()
    payload = await request.json()

    webhook_secret = getattr(settings, 'github_webhook_secret', None)
    if webhook_secret:
        if not verify_github_signature(body, x_hub_signature_256, webhook_secret):
            raise HTTPException(status_code=401, detail="Invalid signature")

    if x_github_event == "pull_request":
        action = payload.get("action")
        pr_data = payload.get("pull_request", {})
        pr_number = pr_data.get("number")
        pr_state = pr_data.get("state")
        merged = pr_data.get("merged", False)
        merged_at = pr_data.get("merged_at")

        logger.info(f"GitHub webhook: PR #{pr_number} action={action} state={pr_state} merged={merged}")

        if action == "closed" and merged:
            from backend.main import pr_monitor_instance
            if pr_monitor_instance:
                await pr_monitor_instance.check_pr_status_by_webhook(pr_number, merged, merged_at)

            # Auto-sync: Pull latest develop after PR merge
            from backend.services import git_service
            from backend.websocket_manager import kanban_manager

            logger.info(f"PR #{pr_number} merged, auto-syncing develop branch...")

            # Broadcast syncing started
            await kanban_manager.broadcast("git:syncing", {
                "message": f"PR #{pr_number} merged, syncing develop..."
            })

            sync_result = await git_service.pull_develop(settings.project_path)

            if sync_result["success"]:
                await kanban_manager.broadcast("git:synced", {
                    "message": sync_result["message"],
                    "commits_pulled": sync_result["commits_pulled"],
                    "triggered_by": f"PR #{pr_number} merge"
                })
                logger.info(f"Auto-sync after PR #{pr_number} merge: {sync_result['message']}")
            else:
                await kanban_manager.broadcast("git:sync_error", {
                    "message": sync_result.get("error", "Auto-sync failed"),
                    "triggered_by": f"PR #{pr_number} merge"
                })
                logger.error(f"Auto-sync failed after PR #{pr_number} merge: {sync_result.get('error')}")

        return {"status": "received", "event": "pull_request", "action": action, "pr": pr_number}

    return {"status": "received", "event": x_github_event}
