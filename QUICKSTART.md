# ⚡ QuickStart - Lancer le Bootstrap

## Étape 1: Récupérer les fichiers

Copie ce dossier `codeflow/` sur ton PC dans l'emplacement de ton choix.

## Étape 2: Initialiser Git

```bash
cd codeflow

# Init git
git init
git add .
git commit -m "chore: initial project setup with specs"

# Créer develop
git checkout -b develop
git checkout main
```

## Étape 3: Lancer Claude Code

```bash
cd codeflow

# Option A: Mode interactif
claude

# Puis tape:
# "Lis SPEC.md et commence l'implémentation étape par étape"

# Option B: One-shot (moins recommandé pour un gros projet)
claude -p "Lis SPEC.md et implémente l'étape 1: Setup Initial"
```

## Étape 4: Itérer

Claude Code va te montrer ce qu'il crée. Valide chaque étape avant de continuer.

Quand une étape est terminée:
```
"Continue avec l'étape suivante"
```

## Étape 5: Commit régulièrement

Après chaque étape validée:
```bash
git add .
git commit -m "feat: complete step X - description"
```

## Étape 6: Push sur GitHub

```bash
# Créer le repo sur GitHub d'abord, puis:
git remote add origin https://github.com/TON_USER/codeflow.git
git push -u origin main
git push -u origin develop
```

---

## 🎯 Commandes Claude Code Utiles

```bash
# Voir l'état du projet
claude -p "Donne-moi un résumé de l'état actuel du projet"

# Continuer après une pause
claude -p "Continue l'implémentation de SPEC.md là où on s'est arrêté"

# Corriger un bug
claude -p "Il y a une erreur: [description]. Corrige-la."

# Ajouter une feature
claude -p "Ajoute cette feature: [description]"
```

---

## 🔄 Le Loop Méta

Une fois le MVP fonctionnel:

1. Lance Codeflow: `python run.py`
2. Crée une tâche: "Add feature X to Codeflow"
3. Codeflow utilise Claude Code pour développer... Codeflow 🤯

**C'est ça le but !**
