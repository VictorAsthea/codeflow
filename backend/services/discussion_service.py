"""
Discussion service for feature/suggestion refinement.

Provides chat-based discussions to refine features and suggestions with AI assistance.
Stores conversation history per item.
"""

import json
import logging
import asyncio
from pathlib import Path
from datetime import datetime
from typing import Optional, Literal
from pydantic import BaseModel

from backend.services.roadmap_ai import call_claude
from backend.services.project_context import get_project_context
from backend.config import settings

logger = logging.getLogger(__name__)


class DiscussionMessage(BaseModel):
    """A single message in a discussion."""
    role: Literal["user", "assistant"]
    content: str
    timestamp: datetime = None

    def __init__(self, **data):
        if data.get('timestamp') is None:
            data['timestamp'] = datetime.now()
        super().__init__(**data)


class Discussion(BaseModel):
    """A discussion thread for a feature or suggestion."""
    item_id: str
    item_type: Literal["feature", "suggestion"]
    item_title: str
    messages: list[DiscussionMessage] = []
    created_at: datetime = None
    updated_at: datetime = None

    def __init__(self, **data):
        now = datetime.now()
        if data.get('created_at') is None:
            data['created_at'] = now
        if data.get('updated_at') is None:
            data['updated_at'] = now
        super().__init__(**data)


class DiscussionStorage:
    """Storage for discussions in .codeflow/discussions/"""

    def __init__(self, project_path: Optional[str] = None):
        self.project_path = Path(project_path or settings.project_path)
        self.discussions_dir = self.project_path / ".codeflow" / "discussions"

    def _ensure_dir(self):
        """Ensure discussions directory exists."""
        self.discussions_dir.mkdir(parents=True, exist_ok=True)

    def _get_file_path(self, item_id: str) -> Path:
        """Get file path for a discussion."""
        return self.discussions_dir / f"{item_id}.json"

    def get_discussion(self, item_id: str) -> Optional[Discussion]:
        """Load a discussion by item ID."""
        file_path = self._get_file_path(item_id)
        if not file_path.exists():
            return None

        try:
            data = json.loads(file_path.read_text(encoding="utf-8"))
            # Parse timestamps
            if data.get('created_at'):
                data['created_at'] = datetime.fromisoformat(data['created_at'])
            if data.get('updated_at'):
                data['updated_at'] = datetime.fromisoformat(data['updated_at'])
            for msg in data.get('messages', []):
                if msg.get('timestamp'):
                    msg['timestamp'] = datetime.fromisoformat(msg['timestamp'])
            return Discussion(**data)
        except Exception as e:
            logger.error(f"Failed to load discussion {item_id}: {e}")
            return None

    def save_discussion(self, discussion: Discussion):
        """Save a discussion."""
        self._ensure_dir()
        file_path = self._get_file_path(discussion.item_id)
        discussion.updated_at = datetime.now()

        data = discussion.model_dump(mode="json")
        file_path.write_text(
            json.dumps(data, indent=2, default=str, ensure_ascii=False),
            encoding="utf-8"
        )

    def delete_discussion(self, item_id: str) -> bool:
        """Delete a discussion."""
        file_path = self._get_file_path(item_id)
        if file_path.exists():
            file_path.unlink()
            return True
        return False

    def list_discussions(self) -> list[dict]:
        """List all discussions with basic info."""
        self._ensure_dir()
        discussions = []

        for file_path in self.discussions_dir.glob("*.json"):
            try:
                data = json.loads(file_path.read_text(encoding="utf-8"))
                discussions.append({
                    "item_id": data.get("item_id"),
                    "item_type": data.get("item_type"),
                    "item_title": data.get("item_title"),
                    "message_count": len(data.get("messages", [])),
                    "updated_at": data.get("updated_at")
                })
            except Exception:
                pass

        return sorted(discussions, key=lambda x: x.get("updated_at", ""), reverse=True)


async def chat_discussion(
    item_id: str,
    item_type: Literal["feature", "suggestion"],
    item_title: str,
    item_description: str,
    message: str,
    project_path: Optional[str] = None
) -> tuple[str, Optional[str]]:
    """
    Send a message in a discussion and get AI response.

    Args:
        item_id: Feature or suggestion ID
        item_type: "feature" or "suggestion"
        item_title: Title of the item
        item_description: Current description
        message: User message
        project_path: Project path for context

    Returns:
        Tuple of (AI response, suggested description update or None)
    """
    storage = DiscussionStorage(project_path)

    # Load or create discussion
    discussion = storage.get_discussion(item_id)
    if not discussion:
        discussion = Discussion(
            item_id=item_id,
            item_type=item_type,
            item_title=item_title
        )

    # Add user message
    discussion.messages.append(DiscussionMessage(role="user", content=message))

    # Build conversation history for context
    history = "\n".join([
        f"{'User' if m.role == 'user' else 'Assistant'}: {m.content}"
        for m in discussion.messages[-10:]  # Last 10 messages
    ])

    # Get project context
    project_context = ""
    project_name = "Projet"
    project_description = ""
    if project_path:
        try:
            ctx = get_project_context(project_path)
            project_context = ctx.get_context_for_prompt()
            project_name = Path(project_path).name

            # Try to read project description from codeflow config
            config_path = Path(project_path) / ".codeflow" / "config.json"
            if config_path.exists():
                config = json.loads(config_path.read_text(encoding='utf-8'))
                project_description = config.get("project_description", "")
                if config.get("project_name"):
                    project_name = config["project_name"]

            # Fallback to README if no description in config
            if not project_description:
                readme_path = Path(project_path) / "README.md"
                if readme_path.exists():
                    readme_content = readme_path.read_text(encoding='utf-8')[:1000]
                    lines = [l for l in readme_content.split('\n') if l.strip() and not l.startswith('#') and not l.startswith('`')]
                    if lines:
                        project_description = lines[0][:200]
        except Exception:
            pass

    logger.info(f"Discussion context: project={project_name}, feature='{item_title}', feature_desc='{item_description[:80] if item_description else 'none'}'")

    system_prompt = f"""CONTEXTE:
- Projet: {project_name}
- {project_description if project_description else ""}
- Feature à raffiner: "{item_title}"
- Description actuelle de la feature: "{item_description}"

TU DOIS raffiner la FEATURE ci-dessus (pas le projet entier).

RÈGLES:
1. Réponds en 2-3 phrases, pose des questions pour clarifier
2. Ne propose JAMAIS d'implémenter du code

SI LE MESSAGE CONTIENT "FINALISER":
Résume ce qui a été discuté et termine OBLIGATOIREMENT par:

[DESCRIPTION_UPDATE]
<description enrichie de la feature basée sur la discussion, 5-8 lignes>
[/DESCRIPTION_UPDATE]"""

    prompt = f"""=== CONTEXTE ===
Projet: {project_name} - {project_description if project_description else ''}
Feature: "{item_title}"
Description actuelle: "{item_description}"

=== DISCUSSION ===
{history}

=== INSTRUCTION ===
Réponds en contexte de cette feature. Si le message contient "FINALISER", génère la description enrichie avec [DESCRIPTION_UPDATE]...[/DESCRIPTION_UPDATE]."""

    logger.info(f"Calling Claude for discussion with model=sonnet, prompt length={len(prompt)}")
    # Run in thread to avoid blocking async event loop
    success, output, stderr = await asyncio.to_thread(
        call_claude,
        prompt,
        180,  # timeout increased for sonnet
        False,  # json_output
        system_prompt,
        "sonnet"  # model - sonnet follows instructions better than haiku
    )
    logger.info(f"Claude response: success={success}, output_len={len(output) if output else 0}, stderr={stderr[:200] if stderr else 'none'}")

    response = ""
    description_update = None

    if success and output:
        response = output

        # Check for description update
        if "[DESCRIPTION_UPDATE]" in response and "[/DESCRIPTION_UPDATE]" in response:
            start = response.index("[DESCRIPTION_UPDATE]") + len("[DESCRIPTION_UPDATE]")
            end = response.index("[/DESCRIPTION_UPDATE]")
            description_update = response[start:end].strip()
            # Remove the update block from visible response
            response = response[:response.index("[DESCRIPTION_UPDATE]")].strip()

        # Add assistant message
        discussion.messages.append(DiscussionMessage(role="assistant", content=response))
        storage.save_discussion(discussion)
    else:
        logger.warning(f"Discussion chat failed: {stderr}")
        if "Timeout" in stderr:
            response = "La réponse a pris trop de temps. Réessayez avec un message plus court."
        else:
            response = f"Erreur: {stderr[:100] if stderr else 'Échec de la requête'}"

    return response, description_update


def get_discussion_storage(project_path: Optional[str] = None) -> DiscussionStorage:
    """Get storage instance for a project."""
    return DiscussionStorage(project_path or settings.project_path)
