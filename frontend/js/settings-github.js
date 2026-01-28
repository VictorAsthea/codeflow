/**
 * Settings modal - GitHub configuration tab
 */

let githubData = null;

async function loadGitHubConfig() {
    try {
        const response = await fetch('/api/project/github');
        if (!response.ok) {
            if (response.status === 404) {
                return { error: 'not_initialized' };
            }
            throw new Error('Failed to load GitHub config');
        }
        return await response.json();
    } catch (error) {
        console.error('Error loading GitHub config:', error);
        return { error: error.message };
    }
}

async function updateGitHubConfig(field, value) {
    try {
        const response = await fetch('/api/project/github', {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ [field]: value })
        });

        if (!response.ok) {
            throw new Error('Failed to update GitHub config');
        }

        // Reload GitHub section
        await renderSettingsGitHub();

        if (window.showToast) {
            window.showToast('Configuration GitHub mise à jour', 'success');
        }
    } catch (error) {
        console.error('Error updating GitHub config:', error);
        if (window.showToast) {
            window.showToast('Erreur lors de la mise à jour', 'error');
        }
    }
}

async function verifyGitHubConnection() {
    const statusEl = document.getElementById('github-connection-status');
    if (statusEl) {
        statusEl.innerHTML = '<span class="github-status checking">Vérification...</span>';
    }

    try {
        const response = await fetch('/api/project/github/verify');
        const result = await response.json();

        if (statusEl) {
            if (result.connected) {
                statusEl.innerHTML = `
                    <span class="github-status connected">
                        <span class="status-icon">✓</span>
                        Connecté à ${result.repo}
                    </span>
                `;
            } else {
                statusEl.innerHTML = `
                    <span class="github-status disconnected">
                        <span class="status-icon">✗</span>
                        ${result.error || 'Non connecté'}
                    </span>
                `;
            }
        }
    } catch (error) {
        if (statusEl) {
            statusEl.innerHTML = '<span class="github-status error">Erreur de vérification</span>';
        }
    }
}

function renderGitHubContent(data) {
    if (!data || data.error) {
        return `
            <div class="settings-not-initialized">
                <p>⚠️ Projet non initialisé avec Codeflow</p>
                <p>Initialisez le projet pour configurer GitHub</p>
            </div>
        `;
    }

    const github = data.github || {};
    const connection = data.connection || {};

    return `
        <div class="github-config-form">
            <div class="form-group">
                <label for="github-repo-input">Repository</label>
                <div class="input-with-button">
                    <input type="text"
                           id="github-repo-input"
                           class="input"
                           value="${github.repo || ''}"
                           placeholder="owner/repo (ex: VictorAsthea/Codeflow)">
                    <button class="btn btn-secondary" onclick="window.saveGitHubRepo()">
                        Enregistrer
                    </button>
                </div>
                <small>Format: owner/repo - Auto-détecté depuis git remote</small>
            </div>

            <div class="form-group">
                <label>Connection Status</label>
                <div class="connection-status-row">
                    <div id="github-connection-status">
                        ${connection.connected
                            ? `<span class="github-status connected"><span class="status-icon">✓</span> Connecté à ${connection.repo}</span>`
                            : `<span class="github-status disconnected"><span class="status-icon">✗</span> ${connection.error || 'Non connecté'}</span>`
                        }
                    </div>
                    <button class="btn btn-secondary btn-small" onclick="window.verifyGitHubConnection()">
                        Vérifier
                    </button>
                </div>
            </div>

            <div class="form-group">
                <label for="github-branch-select">Default Branch</label>
                <select id="github-branch-select"
                        class="input"
                        onchange="window.updateGitHubConfig('default_branch', this.value)">
                    <option value="main" ${github.default_branch === 'main' ? 'selected' : ''}>main</option>
                    <option value="develop" ${github.default_branch === 'develop' ? 'selected' : ''}>develop</option>
                </select>
                <small>Branche de base pour créer les worktrees de tâches</small>
            </div>
        </div>
    `;
}

async function renderSettingsGitHub() {
    const container = document.getElementById('settings-github-content');
    if (!container) return;

    container.innerHTML = '<div class="loading">Chargement...</div>';

    githubData = await loadGitHubConfig();
    container.innerHTML = renderGitHubContent(githubData);
}

window.saveGitHubRepo = async function() {
    const input = document.getElementById('github-repo-input');
    if (input && input.value.trim()) {
        await updateGitHubConfig('repo', input.value.trim());
    }
};

window.verifyGitHubConnection = verifyGitHubConnection;
window.updateGitHubConfig = updateGitHubConfig;

// Setup settings tabs
function setupSettingsTabs() {
    const tabs = document.querySelectorAll('.settings-tab');
    const panels = document.querySelectorAll('.settings-panel');

    tabs.forEach(tab => {
        tab.addEventListener('click', () => {
            const targetTab = tab.dataset.tab;

            // Update tab active state
            tabs.forEach(t => t.classList.remove('active'));
            tab.classList.add('active');

            // Update panel visibility
            panels.forEach(p => p.classList.add('hidden'));
            const targetPanel = document.getElementById(`settings-tab-${targetTab}`);
            if (targetPanel) {
                targetPanel.classList.remove('hidden');
            }

            // Load content when switching tabs
            if (targetTab === 'github') {
                renderSettingsGitHub();
            } else if (targetTab === 'auth') {
                window.authManager?.loadSettingsAuthStatus();
            } else if (targetTab === 'branches') {
                loadBranchesTab();
            }
        });
    });
}


// ============== BRANCHES TAB ==============

async function loadBranchesTab() {
    const container = document.getElementById('settings-branches-content');
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

        // Reload the tab
        loadBranchesTab();
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

        // Reload the tab
        loadBranchesTab();
    } catch (error) {
        if (window.showToast) {
            window.showToast(`Erreur: ${error.message}`, 'error');
        }
    }
}

window.cleanupMergedBranches = cleanupMergedBranches;
window.deleteBranch = deleteBranch;

// Initialize when settings modal opens
document.addEventListener('DOMContentLoaded', () => {
    setupSettingsTabs();

    // Load GitHub config when settings modal opens
    const settingsModal = document.getElementById('settings-modal');
    if (settingsModal) {
        const observer = new MutationObserver((mutations) => {
            mutations.forEach((mutation) => {
                if (mutation.attributeName === 'class') {
                    if (!settingsModal.classList.contains('hidden')) {
                        // Modal just opened - check if on GitHub tab
                        const githubTab = document.querySelector('.settings-tab[data-tab="github"]');
                        if (githubTab && githubTab.classList.contains('active')) {
                            renderSettingsGitHub();
                        }
                    }
                }
            });
        });
        observer.observe(settingsModal, { attributes: true });
    }
});

export { renderSettingsGitHub, loadGitHubConfig };
