from datetime import datetime
from typing import Callable, Any
from backend.models import Task, Phase, PhaseStatus
from backend.services.claude_runner import run_claude_with_streaming
from backend.database import update_task


PHASE_PROMPTS = {
    "planning": """Tu es un architecte logiciel. Analyse cette tâche et crée un plan d'implémentation.

TÂCHE: {task_description}

Produis:
1. Liste des fichiers à créer/modifier
2. Étapes d'implémentation ordonnées
3. Tests à écrire
4. Risques potentiels

Format: Markdown structuré.""",

    "coding": """Tu es un développeur senior. Implémente cette tâche selon le plan.

TÂCHE: {task_description}

PLAN:
{planning_output}

Règles:
- Code propre et documenté
- Gestion d'erreurs
- Pas de TODO ou FIXME
- Commits atomiques avec messages clairs""",

    "validation": """Tu es un QA engineer. Valide l'implémentation.

TÂCHE: {task_description}

Vérifie:
1. Le code compile/s'exécute sans erreur
2. Les tests passent
3. Pas de régression
4. Code review (style, sécurité, performance)

Si problème trouvé, liste les corrections nécessaires.
Sinon, confirme que la tâche est prête pour review humaine."""
}


PHASE_TOOLS = {
    "planning": ["Read", "Grep", "Glob"],
    "coding": ["Read", "Edit", "Write", "Bash", "Grep", "Glob"],
    "validation": ["Read", "Bash", "Grep", "Glob"]
}


async def execute_phase(
    task: Task,
    phase_name: str,
    working_dir: str,
    log_callback: Callable[[str], Any] = None
) -> dict:
    """
    Execute a single phase of a task

    Args:
        task: The task to execute
        phase_name: Name of the phase (planning, coding, validation)
        working_dir: Working directory for execution
        log_callback: Optional callback for streaming logs

    Returns:
        dict with success status and output
    """
    if phase_name not in task.phases:
        raise ValueError(f"Unknown phase: {phase_name}")

    phase = task.phases[phase_name]
    phase.status = PhaseStatus.RUNNING
    phase.started_at = datetime.now()
    phase.logs = []

    await update_task(task)

    prompt_template = PHASE_PROMPTS[phase_name]
    planning_output = ""

    if phase_name == "coding" and "planning" in task.phases:
        planning_phase = task.phases["planning"]
        planning_output = "\n".join(planning_phase.logs)

    prompt = prompt_template.format(
        task_description=f"{task.title}\n\n{task.description}",
        planning_output=planning_output
    )

    async def phase_log_handler(line: str):
        phase.logs.append(line)
        if log_callback:
            await log_callback(line)

    try:
        result = await run_claude_with_streaming(
            prompt=prompt,
            working_dir=working_dir,
            model=phase.config.model,
            allowed_tools=PHASE_TOOLS.get(phase_name, []),
            max_turns=phase.config.max_turns,
            log_callback=phase_log_handler
        )

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


async def execute_all_phases(
    task: Task,
    working_dir: str,
    log_callback: Callable[[str], Any] = None
) -> dict:
    """
    Execute all phases of a task sequentially

    Args:
        task: The task to execute
        working_dir: Working directory for execution
        log_callback: Optional callback for streaming logs

    Returns:
        dict with overall success status
    """
    phases_to_run = ["planning", "coding", "validation"]
    results = {}

    for phase_name in phases_to_run:
        if log_callback:
            await log_callback(f"\n=== Starting {phase_name} phase ===\n")

        result = await execute_phase(task, phase_name, working_dir, log_callback)
        results[phase_name] = result

        if not result["success"]:
            if log_callback:
                await log_callback(f"\n=== Phase {phase_name} failed, stopping execution ===\n")
            break

    all_success = all(r["success"] for r in results.values())

    return {
        "success": all_success,
        "results": results
    }
