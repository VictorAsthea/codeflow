# ⚡ Codeflow - Spec de Bootstrap

> **Instructions pour Claude Code:** Lis ce fichier en entier, puis implémente le MVP étape par étape. Demande confirmation avant de passer à l'étape suivante.

---

## 📋 Projet

| | |
|---|---|
| **Nom** | Codeflow |
| **Description** | Gestionnaire de tâches Kanban avec orchestration Claude Code CLI |
| **Stack** | Python (FastAPI) + Vanilla JS + SQLite |
| **Licence** | AGPL-3.0 |
| **Auteur** | [TON NOM] |

---

## 🎯 Objectif MVP

Application web locale permettant de :
1. Gérer des tâches via un tableau Kanban (4 colonnes avec drag & drop)
2. Exécuter chaque tâche via Claude Code CLI en 3 phases
3. Isoler chaque tâche dans un git worktree séparé
4. Configurer le modèle et l'intensité par phase
5. Voir les logs en temps réel via WebSocket

---

## 📁 Structure à Créer

```
codeflow/
├── backend/
│   ├── __init__.py
│   ├── main.py                 # FastAPI + WebSocket + static files
│   ├── models.py               # Pydantic models
│   ├── database.py             # SQLite async (aiosqlite)
│   ├── config.py               # Settings globaux
│   ├── services/
│   │   ├── __init__.py
│   │   ├── claude_runner.py    # Spawn Claude Code CLI
│   │   ├── worktree_manager.py # Git worktrees (Windows compatible)
│   │   └── phase_executor.py   # Orchestration des 3 phases
│   └── routers/
│       ├── __init__.py
│       ├── tasks.py            # CRUD tâches
│       └── settings.py         # Config globale
├── frontend/
│   ├── index.html
│   ├── css/
│   │   └── style.css
│   └── js/
│       ├── app.js              # Init + routing
│       ├── kanban.js           # Board + drag & drop
│       ├── task-modal.js       # Modal détail tâche
│       ├── api.js              # Fetch wrapper
│       └── websocket.js        # Logs temps réel
├── data/
│   └── .gitkeep
├── .env.example
├── .gitignore
├── requirements.txt
├── run.py                      # Point d'entrée
├── README.md
└── LICENSE
```

---

## 🗄️ Modèles de Données

### Task
```python
class TaskStatus(str, Enum):
    BACKLOG = "backlog"
    IN_PROGRESS = "in_progress"
    AI_REVIEW = "ai_review"
    HUMAN_REVIEW = "human_review"
    DONE = "done"

class PhaseStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"

class PhaseConfig(BaseModel):
    model: str = "claude-sonnet-4-20250514"  # ou opus
    intensity: str = "medium"  # low, medium, high
    max_turns: int = 10

class Phase(BaseModel):
    name: str  # "planning", "coding", "validation"
    status: PhaseStatus = PhaseStatus.PENDING
    config: PhaseConfig
    logs: list[str] = []
    started_at: datetime | None = None
    completed_at: datetime | None = None

class Task(BaseModel):
    id: str  # format: "001-slug-name"
    title: str
    description: str
    status: TaskStatus = TaskStatus.BACKLOG
    phases: dict[str, Phase]  # planning, coding, validation
    worktree_path: str | None = None
    branch_name: str | None = None
    created_at: datetime
    updated_at: datetime
```

### GlobalConfig
```python
class GlobalConfig(BaseModel):
    default_model: str = "claude-sonnet-4-20250514"
    default_intensity: str = "medium"
    project_path: str  # Chemin du projet cible
    auto_review: bool = True
```

---

## 🔌 API Endpoints

### Tasks
```
GET    /api/tasks              # Liste toutes les tâches
POST   /api/tasks              # Créer une tâche
GET    /api/tasks/{id}         # Détail d'une tâche
PATCH  /api/tasks/{id}         # Modifier une tâche
DELETE /api/tasks/{id}         # Supprimer une tâche
POST   /api/tasks/{id}/start   # Démarrer l'exécution
POST   /api/tasks/{id}/stop    # Arrêter l'exécution
POST   /api/tasks/{id}/resume  # Reprendre une tâche
PATCH  /api/tasks/{id}/status  # Changer de colonne (drag & drop)
```

### Phases
```
PATCH  /api/tasks/{id}/phases/{phase}         # Modifier config d'une phase
POST   /api/tasks/{id}/phases/{phase}/retry   # Relancer une phase failed
```

### Settings
```
GET    /api/settings           # Config globale
PATCH  /api/settings           # Modifier config globale
```

### WebSocket
```
WS     /ws/logs/{task_id}      # Stream des logs en temps réel
```

---

## 🖥️ Interface Utilisateur

### Layout Principal
```
+----------------------------------------------------------+
|  Codeflow                           [⚙️ Settings]       |
+----------------------------------------------------------+
|  +------------+ +------------+ +------------+ +----------+|
|  | Backlog    | | En cours   | | Review IA  | | Review   ||
|  | (3)        | | (1)        | | (0)        | | Humaine  ||
|  +------------+ +------------+ +------------+ +----------+|
|  |            | |            | |            | |          ||
|  | [Task 1]   | | [Task 4]   | |            | | [Task 2] ||
|  | [Task 3]   | |   🔄       | |            | |   ✅     ||
|  | [Task 5]   | |            | |            | |          ||
|  |            | |            | |            | |          ||
|  | [+ New]    | |            | |            | |          ||
|  +------------+ +------------+ +------------+ +----------+|
+----------------------------------------------------------+
```

### Card de Tâche
```
+----------------------------------+
| 📋 Task Title                    |
| "Description courte..."          |
+----------------------------------+
| Planning  [====    ] Sonnet Med  |
| Coding    [        ] Pending     |
| Validation[        ] Pending     |
+----------------------------------+
| ⏱️ 2 min ago        [▶️] [⋮]    |
+----------------------------------+
```

### Modal Détail Tâche
```
+------------------------------------------------+
| Task: 001-feature-name              [X]        |
| Status: In Progress                            |
+------------------------------------------------+
| [Overview] [Phases] [Logs] [Files]             |
+------------------------------------------------+
|                                                |
| ✏️ Planning                        [Sonnet ▼]  |
|   Status: ✅ Done                  [Med ▼]     |
|   Duration: 45s                                |
|                                                |
| 💻 Coding                          [Sonnet ▼]  |
|   Status: 🔄 Running               [Med ▼]     |
|   Progress: Turn 3/10                          |
|                                                |
| ✅ Validation                      [Sonnet ▼]  |
|   Status: ⏳ Pending               [Med ▼]     |
|                                                |
+------------------------------------------------+
| [Delete Task]              [Stop] [Resume]     |
+------------------------------------------------+
```

---

## ⚙️ Services Clés

### claude_runner.py
```python
import asyncio
import subprocess

async def run_claude(
    prompt: str,
    working_dir: str,
    model: str = "claude-sonnet-4-20250514",
    allowed_tools: list[str] = None,
    on_output: callable = None  # Callback pour streaming
) -> dict:
    """
    Lance Claude Code CLI et stream la sortie.
    
    Commande générée:
    claude -p "prompt" --model model --allowedTools Edit Bash --output-format json
    """
    cmd = [
        "claude",
        "-p", prompt,
        "--model", model,
        "--output-format", "stream-json"
    ]
    
    if allowed_tools:
        cmd.extend(["--allowedTools", *allowed_tools])
    
    process = await asyncio.create_subprocess_exec(
        *cmd,
        cwd=working_dir,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )
    
    # Stream stdout
    async for line in process.stdout:
        if on_output:
            await on_output(line.decode())
    
    await process.wait()
    return {"exit_code": process.returncode}
```

### worktree_manager.py
```python
import subprocess
from pathlib import Path

class WorktreeManager:
    def __init__(self, project_path: str):
        self.project_path = Path(project_path)
        self.worktrees_dir = self.project_path / ".worktrees"
    
    def create(self, task_id: str, branch_name: str) -> Path:
        """Crée un worktree isolé pour la tâche."""
        worktree_path = self.worktrees_dir / task_id
        
        # Créer la branche et le worktree
        subprocess.run(
            ["git", "worktree", "add", "-b", branch_name, str(worktree_path)],
            cwd=self.project_path,
            check=True
        )
        return worktree_path
    
    def remove(self, task_id: str):
        """Supprime le worktree."""
        worktree_path = self.worktrees_dir / task_id
        subprocess.run(
            ["git", "worktree", "remove", str(worktree_path), "--force"],
            cwd=self.project_path
        )
    
    def merge_to_main(self, task_id: str, target_branch: str = "main"):
        """Merge le worktree dans la branche principale."""
        # ... implementation
```

### phase_executor.py
```python
PHASE_PROMPTS = {
    "planning": """
Tu es un architecte logiciel. Analyse cette tâche et crée un plan d'implémentation.

TÂCHE: {task_description}

Produis:
1. Liste des fichiers à créer/modifier
2. Étapes d'implémentation ordonnées
3. Tests à écrire
4. Risques potentiels

Format: Markdown structuré.
""",
    
    "coding": """
Tu es un développeur senior. Implémente cette tâche selon le plan.

TÂCHE: {task_description}

PLAN:
{planning_output}

Règles:
- Code propre et documenté
- Gestion d'erreurs
- Pas de TODO ou FIXME
- Commit atomiques avec messages clairs
""",
    
    "validation": """
Tu es un QA engineer. Valide l'implémentation.

TÂCHE: {task_description}

Vérifie:
1. Le code compile/s'exécute sans erreur
2. Les tests passent
3. Pas de régression
4. Code review (style, sécurité, performance)

Si problème trouvé, liste les corrections nécessaires.
Sinon, confirme que la tâche est prête pour review humaine.
"""
}
```

---

## 🚀 Étapes d'Implémentation

### Étape 1: Setup Initial
1. Créer la structure de dossiers
2. Créer `requirements.txt`:
   ```
   fastapi>=0.109.0
   uvicorn[standard]>=0.27.0
   aiosqlite>=0.19.0
   pydantic>=2.5.0
   pydantic-settings>=2.1.0
   python-dotenv>=1.0.0
   ```
3. Créer `.gitignore`
4. Créer `.env.example`
5. Créer `LICENSE` (AGPL-3.0)

### Étape 2: Backend Core
1. `config.py` - Settings avec pydantic-settings
2. `database.py` - Init SQLite + migrations simples
3. `models.py` - Tous les Pydantic models
4. `main.py` - FastAPI app + static files mounting

### Étape 3: API Tasks
1. `routers/tasks.py` - CRUD complet
2. Tests manuels avec curl/httpie

### Étape 4: Services
1. `services/worktree_manager.py`
2. `services/claude_runner.py`
3. `services/phase_executor.py`

### Étape 5: WebSocket
1. Endpoint `/ws/logs/{task_id}`
2. Intégration avec claude_runner pour streaming

### Étape 6: Frontend Base
1. `index.html` - Structure HTML
2. `css/style.css` - Styles (dark theme comme Auto-Claude)
3. `js/api.js` - Wrapper fetch

### Étape 7: Kanban Board
1. `js/kanban.js` - Rendu des colonnes et cards
2. Drag & drop natif (HTML5 API)
3. Mise à jour via API

### Étape 8: Task Modal
1. `js/task-modal.js` - Modal détail
2. Config des phases
3. Actions (start/stop/resume)

### Étape 9: Logs Temps Réel
1. `js/websocket.js` - Connexion WS
2. Affichage streaming dans le modal

### Étape 10: Polish
1. `run.py` - Script de lancement (ouvre le navigateur)
2. `README.md` - Documentation
3. Gestion d'erreurs globale
4. Messages utilisateur (toasts)

---

## 🎨 Design Specs

### Couleurs (Dark Theme)
```css
:root {
  --bg-primary: #0d1117;
  --bg-secondary: #161b22;
  --bg-tertiary: #21262d;
  --border: #30363d;
  --text-primary: #e6edf3;
  --text-secondary: #8b949e;
  --accent-yellow: #d29922;
  --accent-green: #3fb950;
  --accent-red: #f85149;
  --accent-blue: #58a6ff;
}
```

### Colonnes Kanban
- **Backlog**: border-left neutre
- **En cours**: border-left jaune `#d29922`
- **Review IA**: border-left bleue `#58a6ff`
- **Review Humaine**: border-left verte `#3fb950`

---

## ✅ Critères de Validation MVP

- [ ] On peut créer/modifier/supprimer des tâches
- [ ] Drag & drop fonctionne entre colonnes
- [ ] Une tâche peut être démarrée et exécute les 3 phases
- [ ] Les logs s'affichent en temps réel
- [ ] Le worktree est créé/supprimé correctement
- [ ] La config par phase est modifiable
- [ ] L'app se lance avec `python run.py`
- [ ] Fonctionne sur Windows

---

## 📝 Notes pour Claude Code

1. **Toujours** utiliser des chemins compatibles Windows (pathlib)
2. **Toujours** gérer les erreurs avec try/except
3. **Jamais** de dépendances inutiles
4. **Préférer** vanilla JS à tout framework
5. **Commits** atomiques et descriptifs en anglais

---

## 🏁 Commande de Lancement

Une fois implémenté, l'utilisateur pourra lancer:

```bash
# Premier lancement
pip install -r requirements.txt
python run.py

# Lancements suivants
python run.py
```

Le script `run.py` doit:
1. Vérifier que les dépendances sont installées
2. Initialiser la DB si nécessaire
3. Lancer le serveur FastAPI
4. Ouvrir automatiquement le navigateur sur `http://localhost:8765`

---

**Maintenant, commence par l'Étape 1: Setup Initial. Montre-moi ce que tu crées et attends ma validation avant de continuer.**
