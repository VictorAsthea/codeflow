from datetime import datetime, timedelta
from typing import Callable, Any
import subprocess
import re
from backend.models import Task, Phase, PhaseStatus
from backend.services.claude_runner import run_claude_with_streaming
from backend.database import update_task


PHASE_PROMPTS = {
    "planning": """Tu es un architecte logiciel. Analyse cette tâche et crée un plan d'implémentation.

TÂCHE: {task_description}

Produis un plan détaillé avec:
1. Liste des fichiers à créer/modifier
2. Étapes d'implémentation ordonnées
3. Tests à écrire
4. Risques potentiels

IMPORTANT: Ne pose AUCUNE question. Prends des décisions basées sur la description de la tâche.
Format: Markdown structuré.""",

    "coding": """Tu es un développeur senior. Implémente cette tâche MAINTENANT.

TÂCHE: {task_description}

PLAN:
{planning_output}

IMPLÉMENTE DIRECTEMENT sans attendre de réponse:
- Crée/modifie les fichiers nécessaires
- Code propre et documenté
- Gestion d'erreurs appropriée
- Pas de TODO ou FIXME
- Commits atomiques avec messages clairs

IMPORTANT: N'attends AUCUNE réponse utilisateur. Implémente directement selon la description.""",

    "validation": """Tu es un QA engineer. Valide l'implémentation MAINTENANT.

TÂCHE: {task_description}

Vérifie:
1. Le code compile/s'exécute sans erreur
2. Les tests passent
3. Pas de régression
4. Code review (style, sécurité, performance)

Si problème trouvé, liste les corrections nécessaires.
Sinon, confirme que la tâche est prête pour review humaine.

IMPORTANT: Ne pose AUCUNE question. Exécute les vérifications directement."""
}


PHASE_TOOLS = {
    "planning": ["Read", "Grep", "Glob"],
    "coding": ["Read", "Edit", "Write", "Bash", "Grep", "Glob"],
    "validation": ["Read", "Bash", "Grep", "Glob"]
}


def parse_turn_from_log(line: str) -> int | None:
    """
    Parse turn number from Claude log line

    Supports formats like:
    - "Turn 5/10"
    - "Starting turn 3"
    - "Claude turn: 7"

    Returns:
        Turn number if found, None otherwise
    """
    patterns = [
        r'Turn\s+(\d+)(?:/\d+)?',
        r'turn\s+(\d+)',
        r'Claude\s+turn:\s*(\d+)'
    ]

    for pattern in patterns:
        match = re.search(pattern, line, re.IGNORECASE)
        if match:
            return int(match.group(1))

    return None


async def execute_phase(
    task: Task,
    phase_name: str,
    working_dir: str,
    log_callback: Callable[[str], Any] = None,
    websocket_manager = None
) -> dict:
    """
    Execute a single phase of a task

    Args:
        task: The task to execute
        phase_name: Name of the phase (planning, coding, validation)
        working_dir: Working directory for execution
        log_callback: Optional callback for streaming logs
        websocket_manager: WebSocket manager for broadcasting progress updates

    Returns:
        dict with success status and output
    """
    if phase_name not in task.phases:
        raise ValueError(f"Unknown phase: {phase_name}")

    phase = task.phases[phase_name]
    phase.status = PhaseStatus.RUNNING
    phase.started_at = datetime.now()
    phase.logs = []
    phase.metrics.current_turn = 0
    phase.metrics.estimated_turns = phase.config.max_turns
    phase.metrics.elapsed_time = 0.0
    phase.metrics.estimated_remaining = None
    phase.metrics.progress_percentage = 0
    phase.metrics.last_log_preview = ""

    await update_task(task)

    last_broadcast_time = None
    BROADCAST_THROTTLE = timedelta(milliseconds=500)

    prompt_template = PHASE_PROMPTS[phase_name]
    planning_output = ""

    if phase_name == "coding" and "planning" in task.phases:
        planning_phase = task.phases["planning"]
        planning_output = "\n".join(planning_phase.logs)

    prompt = prompt_template.format(
        task_description=f"{task.title}\n\n{task.description}",
        planning_output=planning_output
    )

    print(f"[DEBUG] execute_phase: {phase_name}, callback: {log_callback is not None}")

    if phase_name == "coding":
        print(f"[DEBUG] ========== CODING PHASE PROMPT ==========")
        print(f"[DEBUG] {prompt}")
        print(f"[DEBUG] ===========================================")

    log_count = 0

    async def phase_log_handler(line: str):
        nonlocal log_count, last_broadcast_time
        log_count += 1
        if log_count <= 3 or log_count % 10 == 0:
            print(f"[DEBUG] phase_log_handler called (count: {log_count}): {line[:50]}...")
        phase.logs.append(line)

        turn = parse_turn_from_log(line)
        if turn is not None:
            phase.metrics.current_turn = turn
            phase.metrics.progress_percentage = min(
                int((turn / phase.config.max_turns) * 100), 100
            )

            elapsed = (datetime.now() - phase.started_at).total_seconds()
            phase.metrics.elapsed_time = elapsed

            if turn > 0:
                avg_per_turn = elapsed / turn
                remaining_turns = max(phase.config.max_turns - turn, 0)
                phase.metrics.estimated_remaining = avg_per_turn * remaining_turns

        phase.metrics.last_log_preview = line[:100]

        now = datetime.now()
        if websocket_manager and (not last_broadcast_time or (now - last_broadcast_time) > BROADCAST_THROTTLE):
            await websocket_manager.send_progress_update(
                task.id,
                phase_name,
                {
                    "current_turn": phase.metrics.current_turn,
                    "estimated_turns": phase.metrics.estimated_turns,
                    "elapsed_time": phase.metrics.elapsed_time,
                    "estimated_remaining": phase.metrics.estimated_remaining,
                    "progress_percentage": phase.metrics.progress_percentage,
                    "last_log_preview": phase.metrics.last_log_preview
                }
            )
            last_broadcast_time = now

        if log_callback:
            await log_callback(line)

    try:
        print(f"[DEBUG] Calling run_claude_with_streaming for phase {phase_name}")
        result = await run_claude_with_streaming(
            prompt=prompt,
            working_dir=working_dir,
            model=phase.config.model,
            allowed_tools=PHASE_TOOLS.get(phase_name, []),
            max_turns=phase.config.max_turns,
            log_callback=phase_log_handler
        )
        print(f"[DEBUG] run_claude_with_streaming returned, phase_log_handler called {log_count} times")

        if result["exit_code"] == 0:
            phase.status = PhaseStatus.DONE
        else:
            phase.status = PhaseStatus.FAILED

        phase.completed_at = datetime.now()
        await update_task(task)

        return {
            "success": result["exit_code"] == 0,
            "output": result["output"]
        }

    except Exception as e:
        phase.status = PhaseStatus.FAILED
        phase.completed_at = datetime.now()
        phase.logs.append(f"ERROR: {str(e)}")
        await update_task(task)

        return {
            "success": False,
            "output": str(e)
        }


async def commit_changes(
    task: Task,
    working_dir: str,
    log_callback: Callable[[str], Any] = None
) -> bool:
    """
    Commit changes in the worktree

    Args:
        task: The task to commit changes for
        working_dir: Working directory (worktree path)
        log_callback: Optional callback for streaming logs

    Returns:
        bool indicating if commit was successful
    """
    try:
        if log_callback:
            await log_callback("\n=== Committing changes ===\n")

        # Check if there are changes
        status_result = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=working_dir,
            capture_output=True,
            text=True,
            check=True
        )

        if not status_result.stdout.strip():
            if log_callback:
                await log_callback("No changes to commit\n")
            return True

        # Add all changes
        subprocess.run(
            ["git", "add", "."],
            cwd=working_dir,
            capture_output=True,
            text=True,
            check=True
        )

        if log_callback:
            await log_callback("Changes staged for commit\n")

        # Commit with task title
        commit_message = f"feat: {task.title}"
        subprocess.run(
            ["git", "commit", "-m", commit_message],
            cwd=working_dir,
            capture_output=True,
            text=True,
            check=True
        )

        if log_callback:
            await log_callback(f"Committed changes: {commit_message}\n")

        return True

    except subprocess.CalledProcessError as e:
        error_msg = e.stderr.strip() if e.stderr else str(e)
        if log_callback:
            await log_callback(f"Failed to commit: {error_msg}\n")
        return False
    except Exception as e:
        if log_callback:
            await log_callback(f"Failed to commit: {str(e)}\n")
        return False


async def execute_all_phases(
    task: Task,
    working_dir: str,
    log_callback: Callable[[str], Any] = None,
    websocket_manager = None
) -> dict:
    """
    Execute all phases of a task sequentially

    Args:
        task: The task to execute
        working_dir: Working directory for execution
        log_callback: Optional callback for streaming logs
        websocket_manager: WebSocket manager for broadcasting progress updates

    Returns:
        dict with overall success status
    """
    phases_to_run = ["planning", "coding", "validation"]
    results = {}

    for phase_name in phases_to_run:
        if log_callback:
            await log_callback(f"\n=== Starting {phase_name} phase ===\n")

        result = await execute_phase(task, phase_name, working_dir, log_callback, websocket_manager)
        results[phase_name] = result

        if not result["success"]:
            if log_callback:
                await log_callback(f"\n=== Phase {phase_name} failed, stopping execution ===\n")
            break

        # Commit changes after coding phase
        if phase_name == "coding" and result["success"]:
            commit_success = await commit_changes(task, working_dir, log_callback)
            if not commit_success:
                if log_callback:
                    await log_callback("\n=== Warning: Failed to commit changes ===\n")

    all_success = all(r["success"] for r in results.values())

    return {
        "success": all_success,
        "results": results
    }
