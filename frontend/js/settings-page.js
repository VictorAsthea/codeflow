/**
 * Settings Page Handler
 * Manages the settings page view (not modal)
 */

// ============== TAB NAVIGATION ==============

function setupSettingsPageTabs() {
    const navItems = document.querySelectorAll('.settings-nav-item');
    const panels = document.querySelectorAll('.settings-page-panel');

    navItems.forEach(item => {
        item.addEventListener('click', () => {
            const targetTab = item.dataset.settingsTab;

            // Update nav active state
            navItems.forEach(n => n.classList.remove('active'));
            item.classList.add('active');

            // Update panel visibility
            panels.forEach(p => {
                p.classList.remove('active');
                p.classList.add('hidden');
            });

            const targetPanel = document.getElementById(`settings-page-${targetTab}`);
            if (targetPanel) {
                targetPanel.classList.remove('hidden');
                targetPanel.classList.add('active');
            }

            // Load content for the tab
            loadSettingsTabContent(targetTab);
        });
    });
}

function loadSettingsTabContent(tab) {
    switch (tab) {
        case 'general':
            loadGeneralSettings();
            break;
        case 'auth':
            loadAuthSettings();
            break;
        case 'branches':
            loadBranchesSettings();
            break;
        case 'github':
            loadGitHubSettings();
            break;
    }
}

// ============== GENERAL SETTINGS ==============

async function loadGeneralSettings() {
    try {
        const response = await fetch('/api/settings');
        if (!response.ok) return;

        const settings = await response.json();

        document.getElementById('settings-default-model').value = settings.default_model || 'claude-sonnet-4-20250514';
        document.getElementById('settings-default-intensity').value = settings.default_intensity || 'medium';
        document.getElementById('settings-project-path').value = settings.project_path || '';
        document.getElementById('settings-auto-review').checked = settings.auto_review || false;
    } catch (error) {
        console.error('Failed to load settings:', error);
    }
}

async function saveGeneralSettings() {
    const settings = {
        default_model: document.getElementById('settings-default-model').value,
        default_intensity: document.getElementById('settings-default-intensity').value,
        project_path: document.getElementById('settings-project-path').value,
        auto_review: document.getElementById('settings-auto-review').checked
    };

    try {
        const response = await fetch('/api/settings', {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(settings)
        });

        if (response.ok) {
            if (window.showToast) {
                window.showToast('Settings saved', 'success');
            }
        } else {
            throw new Error('Failed to save');
        }
    } catch (error) {
        if (window.showToast) {
            window.showToast('Failed to save settings', 'error');
        }
    }
}

// ============== AUTH SETTINGS ==============

async function loadAuthSettings() {
    const container = document.getElementById('settings-page-auth-content');
    if (!container) return;

    try {
        const response = await fetch('/api/auth/status');
        const status = await response.json();

        container.innerHTML = renderAuthContent(status);
    } catch (error) {
        container.innerHTML = `<p class="error-message">Erreur de chargement</p>`;
    }
}

function renderAuthContent(status) {
    if (!status.authenticated) {
        return `
            <div class="auth-status-card not-connected">
                <div class="auth-status-icon">&#128683;</div>
                <div class="auth-status-info">
                    <h4>Non connecte</h4>
                    <p>Aucune methode d'authentification configuree</p>
                </div>
                <button class="btn btn-primary" onclick="window.authManager?.showAuthModal();">
                    Se connecter
                </button>
            </div>
        `;
    }

    const isSubscription = status.method === 'subscription';
    const methodIcon = isSubscription ? '&#128100;' : '&#128273;';
    const methodName = isSubscription ? 'Abonnement Pro/Max' : 'Cle API Anthropic';
    const methodDesc = isSubscription
        ? 'Connecte via Claude CLI (OAuth)'
        : 'Connecte via cle API directe';

    let html = `
        <div class="auth-status-card connected">
            <div class="auth-status-icon">${methodIcon}</div>
            <div class="auth-status-info">
                <h4>${methodName}</h4>
                <p>${methodDesc}</p>
            </div>
            <span class="auth-status-badge">Connecte</span>
        </div>

        <div class="auth-methods-summary">
            <h4>Methodes disponibles</h4>
            <div class="auth-method-row">
                <span>Abonnement Pro/Max</span>
                <span class="auth-method-status ${status.subscription_available ? 'available' : 'unavailable'}">
                    ${status.subscription_available ? '&#10003; Disponible' : '&#10007; Non detecte'}
                </span>
            </div>
            <div class="auth-method-row">
                <span>Cle API</span>
                <span class="auth-method-status ${status.api_key_available ? 'available' : 'unavailable'}">
                    ${status.api_key_available ? '&#10003; Configuree' : '&#10007; Non configuree'}
                </span>
            </div>
        </div>
    `;

    if (status.api_key_available) {
        html += `
            <div class="auth-actions">
                <button class="btn btn-danger btn-small" onclick="window.authManager?.logout()">
                    Supprimer la cle API
                </button>
            </div>
        `;
    }

    return html;
}

// ============== BRANCHES SETTINGS ==============

async function loadBranchesSettings() {
    const container = document.getElementById('settings-page-branches-content');
    if (!container) return;

    container.innerHTML = '<div class="loading">Chargement des branches...</div>';

    try {
        const response = await fetch('/api/git/branches');
        if (!response.ok) throw new Error('Failed to load branches');

        const data = await response.json();
        container.innerHTML = renderBranchesContent(data);
    } catch (error) {
        container.innerHTML = `<p class="error-message">Erreur: ${error.message}</p>`;
    }
}

function renderBranchesContent(data) {
    const { current_branch, total, merged_count, branches } = data;

    let html = `
        <div class="branches-summary">
            <div class="branches-stat">
                <span class="stat-value">${total}</span>
                <span class="stat-label">Branches</span>
            </div>
            <div class="branches-stat">
                <span class="stat-value">${merged_count}</span>
                <span class="stat-label">A supprimer</span>
            </div>
            <div class="branches-stat current">
                <span class="stat-value">${current_branch}</span>
                <span class="stat-label">Branche actuelle</span>
            </div>
        </div>
    `;

    if (merged_count > 0) {
        html += `
            <div class="branches-actions">
                <button class="btn btn-danger" onclick="cleanupMergedBranches()">
                    Supprimer ${merged_count} branche(s) mergee(s)
                </button>
            </div>
        `;
    }

    html += '<div class="branches-list">';

    for (const branch of branches) {
        const statusClass = branch.is_current ? 'current' :
                           branch.is_protected ? 'protected' :
                           branch.is_merged ? 'merged' : '';
        const statusBadge = branch.is_current ? '<span class="branch-badge current">actuelle</span>' :
                           branch.is_protected ? '<span class="branch-badge protected">protegee</span>' :
                           branch.is_merged ? '<span class="branch-badge merged">mergee</span>' : '';

        html += `
            <div class="branch-item ${statusClass}">
                <div class="branch-info">
                    <span class="branch-name">${branch.name}</span>
                    ${statusBadge}
                </div>
                <div class="branch-meta">
                    <span class="branch-date">${branch.last_commit}</span>
                    ${branch.can_delete ? `<button class="btn btn-small btn-danger" onclick="deleteBranch('${branch.name}')">Supprimer</button>` : ''}
                </div>
            </div>
        `;
    }

    html += '</div>';
    return html;
}

async function cleanupMergedBranches() {
    if (!confirm('Supprimer toutes les branches mergees (sauf main/develop)?')) return;

    try {
        const response = await fetch('/api/git/cleanup-merged', { method: 'POST' });
        const result = await response.json();

        if (result.deleted_count > 0) {
            if (window.showToast) {
                window.showToast(`${result.deleted_count} branche(s) supprimee(s)`, 'success');
            }
        } else {
            if (window.showToast) {
                window.showToast('Aucune branche a supprimer', 'info');
            }
        }

        loadBranchesSettings();
    } catch (error) {
        if (window.showToast) {
            window.showToast(`Erreur: ${error.message}`, 'error');
        }
    }
}

async function deleteBranch(branchName) {
    if (!confirm(`Supprimer la branche "${branchName}"?`)) return;

    try {
        const response = await fetch('/api/git/branches', {
            method: 'DELETE',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ branches: [branchName], force: false })
        });
        const result = await response.json();

        if (result.deleted_count > 0) {
            if (window.showToast) {
                window.showToast(`Branche "${branchName}" supprimee`, 'success');
            }
        } else if (result.failed.length > 0) {
            if (window.showToast) {
                window.showToast(`Erreur: ${result.failed[0].reason}`, 'error');
            }
        }

        loadBranchesSettings();
    } catch (error) {
        if (window.showToast) {
            window.showToast(`Erreur: ${error.message}`, 'error');
        }
    }
}

// ============== GITHUB SETTINGS ==============

async function loadGitHubSettings() {
    const container = document.getElementById('settings-page-github-content');
    if (!container) return;

    container.innerHTML = '<div class="loading">Chargement...</div>';

    try {
        const response = await fetch('/api/project/github');
        if (response.status === 404) {
            container.innerHTML = `
                <div class="settings-not-initialized">
                    <p>Projet non initialise avec Codeflow</p>
                    <p>Initialisez le projet pour configurer GitHub</p>
                </div>
            `;
            return;
        }

        const data = await response.json();
        container.innerHTML = renderGitHubContent(data);
    } catch (error) {
        container.innerHTML = `<p class="error-message">Erreur: ${error.message}</p>`;
    }
}

function renderGitHubContent(data) {
    const github = data.github || {};
    const connection = data.connection || {};

    return `
        <div class="github-config-form">
            <div class="form-group">
                <label for="github-repo-input-page">Repository</label>
                <div class="input-with-button">
                    <input type="text"
                           id="github-repo-input-page"
                           class="input"
                           value="${github.repo || ''}"
                           placeholder="owner/repo (ex: VictorAsthea/Codeflow)">
                    <button class="btn btn-secondary" onclick="saveGitHubRepoPage()">
                        Enregistrer
                    </button>
                </div>
                <small>Format: owner/repo - Auto-detecte depuis git remote</small>
            </div>

            <div class="form-group">
                <label>Connection Status</label>
                <div class="connection-status-row">
                    <div id="github-connection-status-page">
                        ${connection.connected
                            ? `<span class="github-status connected"><span class="status-icon">&#10003;</span> Connecte a ${connection.repo}</span>`
                            : `<span class="github-status disconnected"><span class="status-icon">&#10007;</span> ${connection.error || 'Non connecte'}</span>`
                        }
                    </div>
                    <button class="btn btn-secondary btn-small" onclick="verifyGitHubConnectionPage()">
                        Verifier
                    </button>
                </div>
            </div>

            <div class="form-group">
                <label for="github-branch-select-page">Default Branch</label>
                <select id="github-branch-select-page"
                        class="input"
                        onchange="updateGitHubConfigPage('default_branch', this.value)">
                    <option value="main" ${github.default_branch === 'main' ? 'selected' : ''}>main</option>
                    <option value="develop" ${github.default_branch === 'develop' ? 'selected' : ''}>develop</option>
                </select>
                <small>Branche de base pour creer les worktrees de taches</small>
            </div>
        </div>
    `;
}

async function saveGitHubRepoPage() {
    const input = document.getElementById('github-repo-input-page');
    if (input && input.value.trim()) {
        await updateGitHubConfigPage('repo', input.value.trim());
    }
}

async function verifyGitHubConnectionPage() {
    const statusEl = document.getElementById('github-connection-status-page');
    if (statusEl) {
        statusEl.innerHTML = '<span class="github-status checking">Verification...</span>';
    }

    try {
        const response = await fetch('/api/project/github/verify');
        const result = await response.json();

        if (statusEl) {
            if (result.connected) {
                statusEl.innerHTML = `
                    <span class="github-status connected">
                        <span class="status-icon">&#10003;</span>
                        Connecte a ${result.repo}
                    </span>
                `;
            } else {
                statusEl.innerHTML = `
                    <span class="github-status disconnected">
                        <span class="status-icon">&#10007;</span>
                        ${result.error || 'Non connecte'}
                    </span>
                `;
            }
        }
    } catch (error) {
        if (statusEl) {
            statusEl.innerHTML = '<span class="github-status error">Erreur de verification</span>';
        }
    }
}

async function updateGitHubConfigPage(field, value) {
    try {
        const response = await fetch('/api/project/github', {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ [field]: value })
        });

        if (response.ok) {
            loadGitHubSettings();
            if (window.showToast) {
                window.showToast('Configuration GitHub mise a jour', 'success');
            }
        }
    } catch (error) {
        if (window.showToast) {
            window.showToast('Erreur lors de la mise a jour', 'error');
        }
    }
}

// ============== INITIALIZATION ==============

// Load settings when view becomes visible
function onSettingsViewVisible() {
    loadGeneralSettings();
}

// Setup event listeners
document.addEventListener('DOMContentLoaded', () => {
    setupSettingsPageTabs();

    // Save button
    const saveBtn = document.getElementById('btn-save-settings-page');
    if (saveBtn) {
        saveBtn.addEventListener('click', saveGeneralSettings);
    }

    // Watch for settings view becoming visible
    const settingsView = document.getElementById('settings-view');
    if (settingsView) {
        const observer = new MutationObserver((mutations) => {
            mutations.forEach((mutation) => {
                if (mutation.attributeName === 'class') {
                    if (!settingsView.classList.contains('hidden')) {
                        onSettingsViewVisible();
                    }
                }
            });
        });
        observer.observe(settingsView, { attributes: true });
    }
});

// Export functions for global access
window.cleanupMergedBranches = cleanupMergedBranches;
window.deleteBranch = deleteBranch;
window.saveGitHubRepoPage = saveGitHubRepoPage;
window.verifyGitHubConnectionPage = verifyGitHubConnectionPage;
window.updateGitHubConfigPage = updateGitHubConfigPage;
