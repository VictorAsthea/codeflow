"""
Service for Ideation feature - AI-powered project analysis and suggestions.
Uses Claude CLI to analyze the project and generate improvement suggestions.
"""

import json
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from backend.models import (
    Suggestion, SuggestionCategory, SuggestionPriority, SuggestionStatus,
    IdeationState, IdeationChatMessage
)
from backend.services.claude_cli import run_claude_cli, extract_json_from_output
from backend.services.project_context import get_project_context

logger = logging.getLogger(__name__)

# Prompts for ideation
ANALYZE_PROJECT_PROMPT = """Analyze this project and identify areas for improvement.

Focus on:
1. Security issues (input validation, authentication, XSS, SQL injection, etc.)
2. Performance bottlenecks
3. Code quality issues (duplicate code, complexity, missing error handling)
4. Missing features that would improve the project
5. Bugs or potential bugs
6. Refactoring opportunities
7. Missing documentation
8. Testing gaps
9. Accessibility issues

For each issue found, provide:
- A clear title
- A detailed description explaining the issue and why it matters
- The category (security, performance, code_quality, feature, bug, refactoring, documentation, testing, accessibility, other)
- The priority (low, medium, high, critical)
- The file path where the issue is located (if applicable)
- The line number (if applicable)

Return your findings as a JSON array with this structure:
[
  {
    "title": "Issue title",
    "description": "Detailed description",
    "category": "security",
    "priority": "high",
    "file_path": "path/to/file.py",
    "line_number": 42
  }
]

Be thorough but focus on actionable suggestions. Limit to 10 most important issues.
Return ONLY valid JSON, no other text."""

GENERATE_SUGGESTIONS_PROMPT = """Based on the project context, generate creative suggestions for improvements and new features.

Think about:
1. Features that would enhance user experience
2. Technical improvements that would make the codebase better
3. Security enhancements
4. Performance optimizations
5. Developer experience improvements
6. Integration possibilities
7. Automation opportunities

For each suggestion:
- A clear, compelling title
- A detailed description of what could be done and why
- The category (feature, performance, security, code_quality, etc.)
- The priority (how important is this improvement)

Return suggestions as a JSON array:
[
  {
    "title": "Suggestion title",
    "description": "What to do and why",
    "category": "feature",
    "priority": "medium"
  }
]

Be creative but practical. Focus on suggestions that add real value.
Return ONLY valid JSON, no other text."""


class IdeationService:
    """Service for handling ideation/brainstorming features."""

    def __init__(self, project_path: str):
        self.project_path = Path(project_path)
        self.codeflow_dir = self.project_path / ".codeflow"
        self.state_file = self.codeflow_dir / "ideation_state.json"
        self._state: IdeationState | None = None

    def _load_state(self) -> IdeationState:
        """Load ideation state from file."""
        if self._state is not None:
            return self._state

        if self.state_file.exists():
            try:
                data = json.loads(self.state_file.read_text(encoding='utf-8'))
                self._state = IdeationState(**data)
            except Exception as e:
                logger.warning(f"Failed to load ideation state: {e}")
                self._state = IdeationState()
        else:
            self._state = IdeationState()

        return self._state

    def _save_state(self):
        """Save ideation state to file."""
        if self._state is None:
            return

        self.codeflow_dir.mkdir(exist_ok=True)
        self.state_file.write_text(
            self._state.model_dump_json(indent=2),
            encoding='utf-8'
        )

    def get_state(self) -> IdeationState:
        """Get current ideation state."""
        return self._load_state()

    def get_suggestions(self, include_dismissed: bool = False) -> list[Suggestion]:
        """Get all suggestions."""
        state = self._load_state()
        if include_dismissed:
            return state.suggestions
        return [s for s in state.suggestions if not s.dismissed]

    def dismiss_suggestion(self, suggestion_id: str) -> bool:
        """Dismiss a suggestion."""
        state = self._load_state()
        for suggestion in state.suggestions:
            if suggestion.id == suggestion_id:
                suggestion.dismissed = True
                suggestion.status = SuggestionStatus.DISMISSED
                self._save_state()
                return True
        return False

    def clear_suggestions(self) -> int:
        """Clear all suggestions. Returns count of cleared suggestions."""
        state = self._load_state()
        count = len(state.suggestions)
        state.suggestions = []
        self._save_state()
        return count

    def mark_suggestion_as_task(self, suggestion_id: str, task_id: str) -> bool:
        """Mark a suggestion as converted to a task."""
        state = self._load_state()
        for suggestion in state.suggestions:
            if suggestion.id == suggestion_id:
                suggestion.task_id = task_id
                suggestion.status = SuggestionStatus.ACCEPTED
                self._save_state()
                return True
        return False

    def accept_suggestion(self, suggestion_id: str) -> bool:
        """Accept a suggestion (mark as accepted)."""
        state = self._load_state()
        for suggestion in state.suggestions:
            if suggestion.id == suggestion_id:
                suggestion.status = SuggestionStatus.ACCEPTED
                self._save_state()
                return True
        return False

    def get_suggestion_by_id(self, suggestion_id: str) -> Suggestion | None:
        """Get a suggestion by ID."""
        state = self._load_state()
        for suggestion in state.suggestions:
            if suggestion.id == suggestion_id:
                return suggestion
        return None

    async def analyze_project(
        self,
        on_output: Callable[[str], None] | None = None
    ) -> list[Suggestion]:
        """
        Analyze the project and generate suggestions using Claude.

        Args:
            on_output: Callback for streaming output

        Returns:
            List of generated suggestions
        """
        # Get project context for the prompt
        ctx = get_project_context(str(self.project_path))
        context_str = ctx.get_context_for_prompt()

        full_prompt = f"""Project Context:
{context_str}

{ANALYZE_PROJECT_PROMPT}"""

        logger.info(f"Starting project analysis for: {self.project_path}")

        success, output = await run_claude_cli(
            prompt=full_prompt,
            cwd=str(self.project_path),
            allowed_tools=["Read", "Glob", "Grep"],  # Read-only for analysis
            max_turns=15,
            timeout=300,
            on_output=on_output
        )

        if not success:
            logger.error(f"Project analysis failed: {output}")
            return []

        # Parse JSON response
        parsed = extract_json_from_output(output)
        if not parsed or not isinstance(parsed, list):
            logger.error("Failed to parse analysis response as JSON array")
            return []

        # Convert to Suggestion objects
        suggestions = []
        for item in parsed:
            try:
                suggestion = Suggestion(
                    id=f"sug-{uuid.uuid4().hex[:8]}",
                    title=item.get("title", "Unknown"),
                    description=item.get("description", ""),
                    category=SuggestionCategory(item.get("category", "other")),
                    priority=SuggestionPriority(item.get("priority", "medium")),
                    status=SuggestionStatus.PENDING,
                    file_path=item.get("file_path"),
                    line_number=item.get("line_number"),
                    created_at=datetime.now(timezone.utc)
                )
                suggestions.append(suggestion)
            except Exception as e:
                logger.warning(f"Failed to parse suggestion: {e}")
                continue

        # Update state
        state = self._load_state()
        state.suggestions.extend(suggestions)
        state.last_analysis_at = datetime.now(timezone.utc)
        self._save_state()

        logger.info(f"Analysis complete: {len(suggestions)} suggestions generated")
        return suggestions

    async def generate_suggestions(
        self,
        on_output: Callable[[str], None] | None = None
    ) -> list[Suggestion]:
        """
        Generate creative suggestions for the project using Claude.

        Args:
            on_output: Callback for streaming output

        Returns:
            List of generated suggestions
        """
        ctx = get_project_context(str(self.project_path))
        context_str = ctx.get_context_for_prompt()

        full_prompt = f"""Project Context:
{context_str}

{GENERATE_SUGGESTIONS_PROMPT}"""

        logger.info(f"Generating suggestions for: {self.project_path}")

        success, output = await run_claude_cli(
            prompt=full_prompt,
            cwd=str(self.project_path),
            allowed_tools=["Read", "Glob", "Grep"],
            max_turns=10,
            timeout=300,
            on_output=on_output
        )

        if not success:
            logger.error(f"Suggestion generation failed: {output}")
            return []

        parsed = extract_json_from_output(output)
        if not parsed or not isinstance(parsed, list):
            logger.error("Failed to parse suggestions as JSON array")
            return []

        suggestions = []
        for item in parsed:
            try:
                suggestion = Suggestion(
                    id=f"sug-{uuid.uuid4().hex[:8]}",
                    title=item.get("title", "Unknown"),
                    description=item.get("description", ""),
                    category=SuggestionCategory(item.get("category", "feature")),
                    priority=SuggestionPriority(item.get("priority", "medium")),
                    status=SuggestionStatus.PENDING,
                    file_path=item.get("file_path"),
                    line_number=item.get("line_number"),
                    created_at=datetime.now(timezone.utc)
                )
                suggestions.append(suggestion)
            except Exception as e:
                logger.warning(f"Failed to parse suggestion: {e}")
                continue

        state = self._load_state()
        state.suggestions.extend(suggestions)
        self._save_state()

        logger.info(f"Generated {len(suggestions)} suggestions")
        return suggestions

    async def chat(
        self,
        message: str,
        on_output: Callable[[str], None] | None = None
    ) -> str:
        """
        Chat with the AI about the project (brainstorming).

        Args:
            message: User's message
            on_output: Callback for streaming output

        Returns:
            AI's response
        """
        state = self._load_state()

        # Add user message to history
        user_msg = IdeationChatMessage(
            role="user",
            content=message,
            timestamp=datetime.now(timezone.utc)
        )
        state.chat_history.append(user_msg)

        # Build conversation context
        ctx = get_project_context(str(self.project_path))
        context_str = ctx.get_context_for_prompt()

        # Build chat history for prompt (last 10 messages)
        history_str = ""
        recent_history = state.chat_history[-10:]
        for msg in recent_history[:-1]:  # Exclude current message
            role = "User" if msg.role == "user" else "Assistant"
            history_str += f"{role}: {msg.content}\n\n"

        full_prompt = f"""You are a helpful AI assistant for brainstorming and ideation about a software project.

Project Context:
{context_str}

Previous conversation:
{history_str}

User: {message}

Please provide helpful, creative, and practical suggestions. You can:
- Suggest new features
- Identify potential improvements
- Help design solutions
- Answer questions about the codebase
- Brainstorm ideas for the project

Be conversational and helpful. If you need to look at specific files, you can use the Read tool."""

        logger.info(f"Ideation chat: {message[:50]}...")

        success, output = await run_claude_cli(
            prompt=full_prompt,
            cwd=str(self.project_path),
            allowed_tools=["Read", "Glob", "Grep"],
            max_turns=5,
            timeout=120,
            on_output=on_output
        )

        if not success:
            response = "I apologize, but I encountered an error processing your request. Please try again."
        else:
            response = output.strip()

        # Add assistant response to history
        assistant_msg = IdeationChatMessage(
            role="assistant",
            content=response,
            timestamp=datetime.now(timezone.utc)
        )
        state.chat_history.append(assistant_msg)
        self._save_state()

        return response

    def clear_chat_history(self):
        """Clear chat history."""
        state = self._load_state()
        state.chat_history = []
        self._save_state()

    def get_chat_history(self) -> list[IdeationChatMessage]:
        """Get chat history."""
        state = self._load_state()
        return state.chat_history


# Singleton pattern
_ideation_services: dict[str, IdeationService] = {}


def get_ideation_service(project_path: str) -> IdeationService:
    """Get IdeationService instance for a project."""
    if project_path not in _ideation_services:
        _ideation_services[project_path] = IdeationService(project_path)
    return _ideation_services[project_path]
