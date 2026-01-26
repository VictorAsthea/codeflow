/**
 * MCP Servers Configuration Page
 * Similar to Auto-Claude's MCP overview
 */

const MCP_ICONS = {
    context7: '🔍',
    github: '🐙',
    puppeteer: '🌐',
    memory: '🧠',
    default: '🔌'
};

const MCP_DESCRIPTIONS = {
    context7: 'Recherche de documentation pour les bibliothèques',
    github: 'Intégration GitHub (PR, Issues, Webhooks)',
    puppeteer: 'Automatisation du navigateur web pour les tests',
    memory: 'Mémoire persistante entre les sessions',
    default: 'Serveur MCP personnalisé'
};

let mcpData = null;
let securityData = null;
let githubData = null;

async function loadMCPConfig() {
    try {
        const response = await fetch('/api/project/mcp');
        if (!response.ok) {
            if (response.status === 404) {
                return { error: 'not_initialized' };
            }
            throw new Error('Failed to load MCP config');
        }
        return await response.json();
    } catch (error) {
        console.error('Error loading MCP config:', error);
        return { error: error.message };
    }
}

async function loadSecurityConfig() {
    try {
        const response = await fetch('/api/project/security');
        if (!response.ok) {
            if (response.status === 404) {
                return { error: 'not_initialized' };
            }
            throw new Error('Failed to load security config');
        }
        return await response.json();
    } catch (error) {
        console.error('Error loading security config:', error);
        return { error: error.message };
    }
}

async function toggleMCP(serverName, enabled) {
    try {
        const response = await fetch('/api/project/mcp', {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ server_name: serverName, enabled })
        });

        if (!response.ok) {
            throw new Error('Failed to update MCP');
        }

        // Reload the page data
        await renderMCPPage();

        // Show toast
        if (window.showToast) {
            window.showToast(`${serverName} ${enabled ? 'activé' : 'désactivé'}`, 'success');
        }
    } catch (error) {
        console.error('Error toggling MCP:', error);
        if (window.showToast) {
            window.showToast('Erreur lors de la mise à jour', 'error');
        }
    }
}

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
        await renderGitHubSection();

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

function renderGitHubSection(data) {
    if (!data || data.error) {
        return `
            <div class="mcp-not-initialized">
                <p>⚠️ Configuration GitHub non disponible</p>
            </div>
        `;
    }

    const github = data.github || {};
    const connection = data.connection || {};

    return `
        <div class="github-config-card">
            <div class="github-field">
                <label>Repository</label>
                <div class="github-input-row">
                    <input type="text"
                           id="github-repo-input"
                           class="github-input"
                           value="${github.repo || ''}"
                           placeholder="owner/repo (ex: VictorAsthea/Codeflow)">
                    <button class="btn btn-small btn-secondary" onclick="window.saveGitHubRepo()">
                        Enregistrer
                    </button>
                </div>
            </div>

            <div class="github-field">
                <label>Connection Status</label>
                <div id="github-connection-status" class="github-connection-status">
                    ${connection.connected
                        ? `<span class="github-status connected"><span class="status-icon">✓</span> Connecté à ${connection.repo}</span>`
                        : `<span class="github-status disconnected"><span class="status-icon">✗</span> ${connection.error || 'Non connecté'}</span>`
                    }
                </div>
                <button class="btn btn-small btn-secondary" onclick="window.verifyGitHubConnection()">
                    Vérifier
                </button>
            </div>

            <div class="github-field">
                <label>Default Branch</label>
                <select id="github-branch-select"
                        class="github-select"
                        onchange="window.updateGitHubConfig('default_branch', this.value)">
                    <option value="main" ${github.default_branch === 'main' ? 'selected' : ''}>main</option>
                    <option value="develop" ${github.default_branch === 'develop' ? 'selected' : ''}>develop</option>
                </select>
            </div>

            <div class="github-toggles">
                <label class="github-toggle-label">
                    <span>Auto-créer les PRs</span>
                    <label class="mcp-toggle">
                        <input type="checkbox"
                               ${github.auto_create_pr ? 'checked' : ''}
                               onchange="window.updateGitHubConfig('auto_create_pr', this.checked)">
                        <span class="mcp-toggle-slider"></span>
                    </label>
                </label>
            </div>
        </div>
    `;
}

window.saveGitHubRepo = async function() {
    const input = document.getElementById('github-repo-input');
    if (input && input.value.trim()) {
        await updateGitHubConfig('repo', input.value.trim());
    }
};

window.verifyGitHubConnection = verifyGitHubConnection;
window.updateGitHubConfig = updateGitHubConfig;

function renderMCPServer(name, config) {
    const icon = MCP_ICONS[name] || MCP_ICONS.default;
    const description = config.description || MCP_DESCRIPTIONS[name] || MCP_DESCRIPTIONS.default;
    const isEnabled = config.enabled;

    return `
        <div class="mcp-server-card ${isEnabled ? 'enabled' : 'disabled'}">
            <div class="mcp-server-icon">${icon}</div>
            <div class="mcp-server-info">
                <h4 class="mcp-server-name">${capitalizeFirst(name)}</h4>
                <p class="mcp-server-description">${description}</p>
            </div>
            <label class="mcp-toggle">
                <input type="checkbox"
                       ${isEnabled ? 'checked' : ''}
                       onchange="window.toggleMCP('${name}', this.checked)">
                <span class="mcp-toggle-slider"></span>
            </label>
        </div>
    `;
}

function renderCommandsSection(securityData) {
    if (!securityData || securityData.error) {
        return `<p class="mcp-error">Projet non initialisé</p>`;
    }

    const baseCommands = securityData.security?.base_commands || [];
    const stackCommands = securityData.security?.stack_commands || [];
    const customCommands = securityData.security?.custom_commands || [];
    const detectedStack = securityData.security?.detected_stack || {};

    const stackInfo = [
        ...detectedStack.languages || [],
        ...detectedStack.frameworks || []
    ].join(', ') || 'Non détecté';

    return `
        <div class="mcp-commands-grid">
            <div class="mcp-commands-card">
                <div class="mcp-commands-header">
                    <span class="mcp-commands-icon">🛠️</span>
                    <span class="mcp-commands-title">Commandes de base</span>
                    <span class="mcp-commands-count">${baseCommands.length}</span>
                </div>
                <div class="mcp-commands-list">
                    ${baseCommands.slice(0, 20).map(cmd => `<code>${cmd}</code>`).join('')}
                    ${baseCommands.length > 20 ? `<span class="mcp-commands-more">+${baseCommands.length - 20} autres</span>` : ''}
                </div>
            </div>

            <div class="mcp-commands-card">
                <div class="mcp-commands-header">
                    <span class="mcp-commands-icon">📦</span>
                    <span class="mcp-commands-title">Commandes Stack</span>
                    <span class="mcp-commands-count">${stackCommands.length}</span>
                </div>
                <p class="mcp-stack-info">Stack détecté: ${stackInfo}</p>
                <div class="mcp-commands-list">
                    ${stackCommands.map(cmd => `<code>${cmd}</code>`).join('') || '<span class="mcp-no-commands">Aucune</span>'}
                </div>
            </div>

            <div class="mcp-commands-card">
                <div class="mcp-commands-header">
                    <span class="mcp-commands-icon">✨</span>
                    <span class="mcp-commands-title">Commandes personnalisées</span>
                    <span class="mcp-commands-count">${customCommands.length}</span>
                </div>
                <div class="mcp-commands-list">
                    ${customCommands.map(cmd => `<code>${cmd}</code>`).join('') || '<span class="mcp-no-commands">Aucune ajoutée</span>'}
                </div>
            </div>
        </div>

        <div class="mcp-total-commands">
            Total: <strong>${baseCommands.length + stackCommands.length + customCommands.length}</strong> commandes autorisées
        </div>
    `;
}

async function renderMCPPage() {
    const serversList = document.getElementById('mcp-servers-list');
    const commandsSummary = document.getElementById('mcp-commands-summary');
    const activeCount = document.getElementById('mcp-active-count');

    if (!serversList || !commandsSummary) return;

    // Load configs in parallel
    const [mcpResult, securityResult] = await Promise.all([
        loadMCPConfig(),
        loadSecurityConfig()
    ]);

    mcpData = mcpResult;
    securityData = securityResult;

    // Render MCP servers
    if (mcpData.error === 'not_initialized') {
        serversList.innerHTML = `
            <div class="mcp-not-initialized">
                <p>⚠️ Projet non initialisé avec Codeflow</p>
                <p>Initialisez le projet pour configurer les MCPs</p>
            </div>
        `;
        activeCount.textContent = '0 serveurs activés';
    } else if (mcpData.error) {
        serversList.innerHTML = `<p class="mcp-error">Erreur: ${mcpData.error}</p>`;
    } else {
        const servers = mcpData.mcp?.servers || {};
        const enabledCount = Object.values(servers).filter(s => s.enabled).length;

        serversList.innerHTML = Object.entries(servers)
            .map(([name, config]) => renderMCPServer(name, config))
            .join('');

        activeCount.textContent = `${enabledCount} serveur${enabledCount !== 1 ? 's' : ''} activé${enabledCount !== 1 ? 's' : ''}`;
    }

    // Render commands summary
    commandsSummary.innerHTML = renderCommandsSection(securityResult);
}

function capitalizeFirst(str) {
    return str.charAt(0).toUpperCase() + str.slice(1);
}

// Make toggleMCP available globally
window.toggleMCP = toggleMCP;

// Initialize when view becomes visible
document.addEventListener('DOMContentLoaded', () => {
    // Listen for view changes via sidebar
    window.addEventListener('view-changed', (e) => {
        if (e.detail.view === 'mcp') {
            renderMCPPage();
        }
    });

    // Also load if already on MCP view
    if (window.location.hash === '#mcp') {
        setTimeout(renderMCPPage, 100);
    }
});

// Export for use by other modules
export { renderMCPPage };
