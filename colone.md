Implémente la fonctionnalité complète "Create PR + colonne Done" dans Codeflow:

## 1. Backend - Models (backend/models.py)

Modifications:
- Ajouter DONE = "done" dans l'enum TaskStatus
- Ajouter le champ `pr_url: str | None = None` dans le model Task

## 2. Backend - API (backend/routers/tasks.py)

Nouvel endpoint POST /api/tasks/{task_id}/create-pr:
- Vérifier que la tâche existe et est en status "human_review"
- Vérifier que task.branch_name existe
- Exécuter via subprocess: gh pr create --base main --head {task.branch_name} --title "{task.title}" --body "{task.description}"
- Parser la sortie pour récupérer l'URL de la PR
- Sauvegarder l'URL dans task.pr_url
- Changer task.status = TaskStatus.DONE
- Retourner {"message": "PR created", "pr_url": url, "task": task}
- Gérer les erreurs (gh non installé, pas authentifié, PR existe déjà)

## 3. Frontend - HTML (frontend/index.html)

- Ajouter la 5ème colonne "Done" après "Human Review" dans le board
- Dans le task-modal, section overview: ajouter un div pour afficher le lien PR si pr_url existe
- Dans le task-modal, section actions: ajouter les boutons "View Diff" et "Create PR"

## 4. Frontend - CSS (frontend/css/style.css)

- Style pour la colonne Done: border-left: 3px solid #3fb950 (vert bright)
- Style bouton "Create PR": background #238636, hover #2ea043
- Style bouton "View Diff": background #1f6feb, hover #388bfd
- Style pour le lien PR affiché (icône GitHub + lien cliquable)
- Les boutons Create PR et View Diff ne sont visibles que en status human_review

## 5. Frontend - JavaScript (frontend/js/kanban.js)

- Ajouter "done" dans la liste des colonnes
- Gérer le rendu des cartes Done avec affichage du lien PR
- Afficher une icône ✓ ou 🎉 pour les tâches Done

## 6. Frontend - JavaScript (frontend/js/task-modal.js)

- Ajouter bouton "View Diff" qui appelle: window.open() vers GitHub compare URL
- Ajouter bouton "Create PR" qui:
  - Appelle POST /api/tasks/{id}/create-pr
  - Affiche un loader pendant l'appel
  - En cas de succès: affiche le lien, rafraîchit le board
  - En cas d'erreur: affiche le message d'erreur
- Les boutons ne sont visibles que si task.status === "human_review"
- Si task.pr_url existe, afficher le lien vers la PR dans l'overview

## 7. Frontend - JavaScript (frontend/js/api.js)

- Ajouter fonction createPR(taskId) qui appelle POST /api/tasks/{id}/create-pr

## Workflow final attendu:

Backlog → In Progress → AI Review → Human Review → [Bouton Create PR] → Done (avec lien PR cliquable)

## Tests à effectuer:

1. Vérifier que la colonne Done s'affiche
2. Créer une tâche, la faire passer en Human Review
3. Vérifier que les boutons View Diff et Create PR apparaissent
4. Cliquer Create PR et vérifier:
   - La PR est créée sur GitHub
   - La tâche passe en Done
   - Le lien PR est affiché

## Notes techniques:

- Utiliser subprocess.run avec capture_output=True pour gh cli
- Le format de sortie de `gh pr create` donne l'URL directement
- Pour View Diff, construire l'URL: https://github.com/{owner}/{repo}/compare/main...{branch_name}
- Gérer le cas où gh cli n'est pas installé avec un message d'erreur clair

Commit message: "feat: add Create PR button and Done column"