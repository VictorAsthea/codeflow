# Auto-Stop Tasks When PR is Merged

Cette fonctionnalité détecte automatiquement quand une Pull Request est mergée et nettoie la tâche associée en arrêtant le worktree et en marquant la tâche comme terminée.

## Fonctionnement

### Détection des PR mergées

Le système utilise deux méthodes complémentaires :

1. **Webhooks GitHub (temps réel)** - Recommandé pour un traitement immédiat
2. **Polling périodique** - Fallback qui vérifie régulièrement le statut des PR

### Actions automatiques

Quand une PR est détectée comme mergée :

1. Le worktree de la tâche est automatiquement supprimé
2. La tâche est marquée avec `pr_merged = true`
3. La date de merge est enregistrée dans `pr_merged_at`
4. Les ressources du système sont libérées

## Configuration

### Variables d'environnement

Ajoutez ces variables dans votre fichier `.env` :

```bash
# Activer/désactiver le monitoring des PR
CODEFLOW_PR_MONITORING_ENABLED=true

# Intervalle de vérification en secondes (polling)
CODEFLOW_PR_CHECK_INTERVAL=300

# Secret pour vérifier les webhooks GitHub (optionnel mais recommandé)
CODEFLOW_GITHUB_WEBHOOK_SECRET=your-secret-here
```

### Paramètres par défaut

- `PR_MONITORING_ENABLED`: `true` (activé par défaut)
- `PR_CHECK_INTERVAL`: `300` secondes (5 minutes)
- `GITHUB_WEBHOOK_SECRET`: vide (pas de vérification de signature)

## Configuration des Webhooks GitHub

### 1. Créer un webhook dans votre repository GitHub

1. Allez dans Settings → Webhooks → Add webhook
2. Payload URL: `http://your-server:8765/api/webhooks/github`
3. Content type: `application/json`
4. Secret: (optionnel) générez un secret sécurisé et ajoutez-le dans `.env`
5. Events: Sélectionnez "Pull requests"
6. Active: Cochez la case

### 2. Pour un tunnel local (développement)

Si vous développez en local, utilisez un service comme ngrok :

```bash
# Démarrer un tunnel ngrok
ngrok http 8765

# Utilisez l'URL ngrok comme Payload URL
# Exemple: https://abc123.ngrok.io/api/webhooks/github
```

### 3. Générer un secret sécurisé

```bash
# Générer un secret aléatoire
openssl rand -hex 32

# Ajoutez-le dans votre .env
CODEFLOW_GITHUB_WEBHOOK_SECRET=<votre-secret>
```

## Migration de la base de données

Si vous avez une base de données existante, exécutez le script de migration :

```bash
python backend/database_migration.py
```

Ce script ajoute les colonnes suivantes à la table `tasks` :
- `pr_url` (TEXT)
- `pr_number` (INTEGER)
- `pr_merged` (INTEGER/BOOLEAN)
- `pr_merged_at` (TEXT/DATETIME)

## Utilisation

### Mode automatique (recommandé)

1. Créez une tâche normalement via l'interface
2. Lancez l'exécution de la tâche
3. Créez la PR depuis l'interface (bouton "Create PR")
4. Le système extrait automatiquement le numéro de PR
5. Quand la PR est mergée sur GitHub, le système détecte le merge automatiquement
6. Le worktree est nettoyé et la tâche est marquée comme terminée

### Vérification manuelle

Le système vérifie périodiquement toutes les tâches avec des PR ouvertes :
- Seules les tâches avec statut `DONE` sont vérifiées
- Seules les PR non encore mergées sont vérifiées
- L'intervalle de vérification est configurable via `PR_CHECK_INTERVAL`

## Logs et monitoring

Les événements suivants sont loggés :

```
INFO - PR monitor started
INFO - Webhook received: PR #123 merged for task 001-example
INFO - PR #123 merged for task 001-example, cleaning up...
INFO - Worktree removed for task 001-example
INFO - Task 001-example marked as merged and cleaned up
```

## Dépannage

### Le monitoring ne démarre pas

Vérifiez que :
- `CODEFLOW_PR_MONITORING_ENABLED=true` dans `.env`
- Le service démarre sans erreur (vérifiez les logs)
- GitHub CLI (`gh`) est installé et configuré

### Les webhooks ne fonctionnent pas

Vérifiez que :
- L'URL du webhook est accessible depuis GitHub
- Le secret est identique dans GitHub et dans `.env`
- Les événements "Pull requests" sont sélectionnés dans GitHub
- Les logs montrent la réception du webhook

### Le polling ne détecte pas les PR mergées

Vérifiez que :
- GitHub CLI (`gh`) est installé : `gh --version`
- GitHub CLI est authentifié : `gh auth status`
- Vous avez accès au repository : `gh pr list`

## Prérequis

- **GitHub CLI** (`gh`) installé et configuré
- **Accès au repository** via GitHub CLI
- **Python 3.10+** avec FastAPI et aiosqlite

## Architecture technique

### Composants

1. **PRMonitor** (`backend/services/pr_monitor.py`)
   - Service de monitoring en arrière-plan
   - Polling périodique des PR
   - Gestion du cleanup des worktrees

2. **Webhook Handler** (`backend/routers/webhooks.py`)
   - Endpoint `/api/webhooks/github`
   - Vérification des signatures
   - Traitement des événements GitHub

3. **Database Schema** (`backend/database.py`)
   - Champs `pr_url`, `pr_number`, `pr_merged`, `pr_merged_at`
   - Migration automatique au démarrage

### Flux de données

```
GitHub PR Merged
    ↓
[Webhook] → FastAPI → PRMonitor.check_pr_status_by_webhook()
                              ↓
                      Cleanup worktree + Update task
                              ↓
                      Task marked as merged

[Polling] → PRMonitor._monitor_loop() → Check all PRs
                              ↓
                      Cleanup worktree + Update task
                              ↓
                      Task marked as merged
```

## Sécurité

- **Vérification de signature** : Le secret webhook empêche les requêtes non autorisées
- **Isolation** : Chaque worktree est isolé dans `.worktrees/<task-id>`
- **Cleanup sécurisé** : Utilise `git worktree remove --force` pour éviter les erreurs
- **Logs détaillés** : Toutes les opérations sont loggées pour audit

## Performance

- **Polling** : Vérifie toutes les 5 minutes par défaut (configurable)
- **Webhooks** : Traitement en temps réel (< 1 seconde)
- **Async** : Toutes les opérations sont asynchrones
- **Impact minimal** : Le monitoring s'exécute en arrière-plan sans bloquer les autres tâches
