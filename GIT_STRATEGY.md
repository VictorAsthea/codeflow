# 🌿 Codeflow - Stratégie Git

## Branches Principales

```
main                 # Production stable, protégée
└── develop          # Intégration, base pour les features
    ├── feature/*    # Nouvelles fonctionnalités
    ├── fix/*        # Corrections de bugs
    └── refactor/*   # Refactoring sans nouvelle feature
```

---

## 🚀 Workflow Initial (Bootstrap)

```bash
# 1. Créer le repo
mkdir codeflow && cd codeflow
git init

# 2. Premier commit (après SPEC.md créé)
git add .
git commit -m "chore: initial project setup"

# 3. Créer develop
git checkout -b develop

# 4. Push initial
git remote add origin https://github.com/TON_USER/codeflow.git
git push -u origin main
git push -u origin develop
```

---

## 📝 Convention de Nommage des Branches

```
feature/short-description    # Nouvelle fonctionnalité
fix/issue-description        # Bug fix
refactor/what-is-refactored  # Refactoring
docs/what-documented         # Documentation
chore/maintenance-task       # Maintenance, deps, CI
```

**Exemples:**
```
feature/kanban-drag-drop
feature/claude-runner
feature/websocket-logs
fix/worktree-windows-path
refactor/task-model
docs/readme-installation
chore/update-dependencies
```

---

## 📝 Convention de Commits

Format: `type(scope): description`

### Types
| Type | Description |
|------|-------------|
| `feat` | Nouvelle fonctionnalité |
| `fix` | Correction de bug |
| `refactor` | Refactoring (pas de new feature, pas de fix) |
| `docs` | Documentation |
| `style` | Formatting, pas de changement de code |
| `test` | Ajout/modification de tests |
| `chore` | Maintenance, build, CI |

### Scopes (optionnel)
```
backend, frontend, api, ui, db, claude, worktree, config
```

### Exemples
```bash
feat(api): add task CRUD endpoints
feat(ui): implement kanban drag and drop
fix(worktree): handle Windows paths correctly
refactor(claude): extract phase prompts to config
docs: add installation instructions
chore: update fastapi to 0.109.0
```

---

## 🔄 Workflow de Développement

### Créer une Feature

```bash
# 1. Partir de develop à jour
git checkout develop
git pull origin develop

# 2. Créer la branche feature
git checkout -b feature/kanban-board

# 3. Développer avec des commits atomiques
git add backend/routers/tasks.py
git commit -m "feat(api): add GET /tasks endpoint"

git add frontend/js/kanban.js
git commit -m "feat(ui): render kanban columns"

# 4. Push régulièrement
git push -u origin feature/kanban-board

# 5. Quand c'est prêt, créer une PR vers develop
```

### Merge une Feature

```bash
# Option A: Via GitHub PR (recommandé)
# Créer PR: feature/kanban-board → develop
# Review, puis "Squash and merge" ou "Merge"

# Option B: En local
git checkout develop
git pull origin develop
git merge --no-ff feature/kanban-board
git push origin develop

# Nettoyer
git branch -d feature/kanban-board
git push origin --delete feature/kanban-board
```

### Release vers Main

```bash
# Quand develop est stable
git checkout main
git pull origin main
git merge --no-ff develop
git tag -a v0.1.0 -m "MVP release"
git push origin main --tags
```

---

## 🏷️ Versioning (SemVer)

```
v0.1.0   # MVP initial
v0.2.0   # Ajout feature majeure
v0.2.1   # Bug fix
v1.0.0   # Première version stable/publique
```

---

## 📋 Checklist avant Push

- [ ] Code fonctionne localement
- [ ] Pas de `print()` de debug oubliés
- [ ] Pas de secrets/credentials dans le code
- [ ] Commits atomiques et bien nommés
- [ ] Branche à jour avec develop

---

## 🚫 Règles

1. **Jamais** push directement sur `main`
2. **Jamais** force push sur `main` ou `develop`
3. **Toujours** partir de `develop` pour une feature
4. **Toujours** tester avant de merge
5. **Préférer** des commits petits et fréquents

---

## 🤖 Pour le Développement avec Codeflow

Une fois le projet fonctionnel, tu utiliseras Codeflow lui-même pour créer des features:

```
1. Créer une tâche dans Codeflow: "Add dark/light theme toggle"
2. Codeflow crée automatiquement:
   - Branche: feature/001-dark-light-theme
   - Worktree: .worktrees/001-dark-light-theme
3. Claude Code exécute les 3 phases dans le worktree
4. Tu review dans "Review Humaine"
5. Tu merges → Codeflow merge la branche dans develop
```

C'est le loop méta parfait 🔄
