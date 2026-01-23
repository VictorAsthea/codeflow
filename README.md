# ⚡ Codeflow

**Gestionnaire de tâches Kanban avec orchestration Claude Code CLI**

[![GitHub Release](https://img.shields.io/github/v/release/VictorAsthea/codeflow?style=flat-square&logo=github)](https://github.com/VictorAsthea/codeflow/releases)
[![License: AGPL-3.0](https://img.shields.io/badge/License-AGPL%20v3-blue.svg?style=flat-square)](LICENSE)
[![Made with Claude](https://img.shields.io/badge/Made%20with-Claude-FF6B35?style=flat-square&logo=anthropic)](https://claude.ai)
[![Python Version](https://img.shields.io/badge/Python-3.10+-blue?style=flat-square&logo=python&logoColor=white)](https://python.org)

---

## 🎯 Qu'est-ce que Codeflow ?

Codeflow est une alternative légère à Auto-Claude. Une application web locale qui permet de :

- 📋 Gérer des tâches de développement via un tableau Kanban
- 🤖 Exécuter automatiquement les tâches via Claude Code CLI
- 🔀 Isoler chaque tâche dans un git worktree séparé
- ⚙️ Configurer le modèle et l'intensité par phase
- 📊 Suivre les logs en temps réel

### Pourquoi Codeflow ?

| | Auto-Claude | Codeflow |
|---|---|---|
| **Poids** | ~150MB (Electron) | ~0MB (Web locale) |
| **Installation** | .exe/.dmg | `pip install` |
| **Bugs packaging** | Nombreux | Aucun |
| **Contribution** | Complexe | Simple |
| **Core** | Identique | Identique |

---

## 🚀 Installation

### Prérequis

- Python 3.10+
- Git
- [Claude Code CLI](https://docs.anthropic.com/claude-code) installé et authentifié
- Abonnement Claude Pro ou Max

### Installation

```bash
# Cloner le repo
git clone https://github.com/VictorAsthea/codeflow.git
cd codeflow

# Installer les dépendances
pip install -r requirements.txt

# Configurer (optionnel)
cp .env.example .env

# Lancer
python run.py
```

L'application s'ouvre automatiquement dans votre navigateur sur `http://localhost:8765`

---

## 📖 Utilisation

### Créer une Tâche

1. Cliquez sur **"+ Nouvelle tâche"** dans la colonne Backlog
2. Donnez un titre et une description
3. La tâche apparaît dans le Backlog

### Exécuter une Tâche

1. Cliquez sur la tâche pour ouvrir le détail
2. Configurez les phases si nécessaire (modèle, intensité)
3. Cliquez sur **"▶️ Start"**
4. Codeflow:
   - Crée un worktree isolé
   - Exécute Planning → Coding → Validation
   - Déplace la tâche vers "Review IA" puis "Review Humaine"

### Workflow des Colonnes

```
Backlog → En cours → Review IA → Review Humaine → (Merge/Archive)
```

### Configurer une Phase

Chaque tâche a 3 phases configurables :

| Phase | Description | Modèle recommandé |
|-------|-------------|-------------------|
| **Planning** | Analyse et plan d'implémentation | Sonnet (rapide) |
| **Coding** | Implémentation du code | Sonnet ou Opus |
| **Validation** | Tests et review automatique | Sonnet |

---

## ⚙️ Configuration

### Variables d'Environnement

```env
# .env
CODEFLOW_PORT=8765
CODEFLOW_PROJECT_PATH=/path/to/your/project
CODEFLOW_DEFAULT_MODEL=claude-sonnet-4-20250514
CODEFLOW_DEFAULT_INTENSITY=medium
```

### Intensité

| Niveau | Max Turns | Usage |
|--------|-----------|-------|
| `low` | 5 | Tâches simples |
| `medium` | 10 | Tâches standard |
| `high` | 20 | Tâches complexes |

---

## 🛠️ Développement

### Structure du Projet

```
codeflow/
├── backend/          # API FastAPI
├── frontend/         # Interface web (Vanilla JS)
├── data/             # SQLite database
├── run.py            # Point d'entrée
└── SPEC.md           # Spécifications complètes
```

### Contribuer

```bash
# Fork et clone
git clone https://github.com/VictorAsthea/codeflow.git
cd codeflow

# Créer une branche
git checkout -b feature/ma-feature

# Développer...

# Push et créer une PR vers develop
```

Voir [GIT_STRATEGY.md](GIT_STRATEGY.md) pour les conventions.

---

## 📝 Roadmap

- [x] MVP Kanban + Claude Code
- [x] Streaming logs temps réel (WebSocket)
- [x] Auto-refresh des tâches en cours
- [ ] Subtasks
- [ ] Intégration GitHub Issues
- [ ] Thème clair
- [ ] Statistiques d'utilisation
- [ ] Export/Import de tâches

---

## 📄 Licence

[AGPL-3.0](LICENSE) - Libre d'utilisation. Si vous modifiez et distribuez, votre code doit aussi être open source.

---

## 🙏 Crédits

Inspiré par [Auto-Claude](https://github.com/AndyMik90/Auto-Claude) - merci à la communauté !

---

**Made with Claude 🤖**
