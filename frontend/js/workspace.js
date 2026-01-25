/**
 * Gestion du workspace multi-projets (onglets)
 */

class WorkspaceManager {
    constructor() {
        this.projects = [];
        this.activeProject = null;
        this.tabsContainer = null;
        this.currentBrowsePath = null;
        this.selectedPath = null;
    }

    async init() {
        this.tabsContainer = document.getElementById('project-tabs');
        await this.loadState();
        this.render();
    }

    async loadState() {
        try {
            const response = await fetch('/api/workspace/state');
            const data = await response.json();
            this.projects = data.open_projects || [];
            this.activeProject = data.active_project;
        } catch (error) {
            console.error('Failed to load workspace:', error);
        }
    }

    render() {
        if (!this.tabsContainer) return;

        const tabsHtml = this.projects.map(project => {
            const isActive = project.path === this.activeProject;
            const warning = !project.initialized ? '<span class="tab-status warning">⚠</span>' : '';

            return `
                <div class="project-tab ${isActive ? 'active' : ''}"
                     onclick="workspace.switchTo('${this.escapeJs(project.path)}')">
                    <span class="tab-name">${project.name}</span>
                    ${warning}
                    <button class="tab-close" onclick="event.stopPropagation(); workspace.close('${this.escapeJs(project.path)}')" title="Fermer">✕</button>
                </div>
            `;
        }).join('');

        this.tabsContainer.innerHTML = `
            ${tabsHtml}
            <button class="project-tab-add" onclick="workspace.showOpenModal()" title="Ouvrir un projet">+</button>
        `;
    }

    async switchTo(projectPath) {
        if (projectPath === this.activeProject) return;

        try {
            const response = await fetch('/api/workspace/set-active', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ project_path: projectPath })
            });

            const result = await response.json();

            if (result.success) {
                this.activeProject = projectPath;
                this.render();
                await this.reloadProjectData();

                const project = this.projects.find(p => p.path === projectPath);
                if (project && !project.initialized && typeof projectInit !== 'undefined') {
                    projectInit.showInitModal({ project_name: project.name });
                }
            }
        } catch (error) {
            console.error('Failed to switch:', error);
            window.showToast?.('Erreur', 'error');
        }
    }

    showOpenModal() {
        const html = `
            <div class="modal-overlay active" id="open-project-modal">
                <div class="modal folder-browser-modal">
                    <div class="modal-header">
                        <h2>Ouvrir un projet</h2>
                        <button class="modal-close" onclick="workspace.closeModal()">✕</button>
                    </div>
                    <div class="modal-body">
                        <!-- Breadcrumb path -->
                        <div class="browser-breadcrumb" id="browser-breadcrumb">
                            Chargement...
                        </div>

                        <!-- Folder list -->
                        <div class="browser-folders" id="browser-folders">
                            <div class="browser-loading">Chargement...</div>
                        </div>

                        <!-- Recent projects -->
                        <div class="browser-recent" id="browser-recent"></div>
                    </div>
                    <div class="modal-footer">
                        <div class="selected-folder" id="selected-folder">Aucun dossier selectionne</div>
                        <button class="btn btn-secondary" onclick="workspace.closeModal()">Annuler</button>
                        <button class="btn btn-primary" id="btn-open-folder" onclick="workspace.confirmOpen()" disabled>Ouvrir</button>
                    </div>
                </div>
            </div>
        `;
        document.body.insertAdjacentHTML('beforeend', html);
        this.browseTo(null); // Start at default location
        this.loadRecentProjects();
    }

    async browseTo(path) {
        try {
            const url = path ? `/api/workspace/browse?path=${encodeURIComponent(path)}` : '/api/workspace/browse';
            const response = await fetch(url);
            const data = await response.json();

            this.currentBrowsePath = data.current;
            this.renderBreadcrumb(data.current);
            this.renderFolders(data.folders, data.current);
        } catch (error) {
            console.error('Failed to browse:', error);
            window.showToast?.('Erreur de navigation', 'error');
        }
    }

    renderBreadcrumb(currentPath) {
        const container = document.getElementById('browser-breadcrumb');
        if (!container) return;

        // Split path into parts
        const isWindows = currentPath.includes('\\');
        const separator = isWindows ? '\\' : '/';
        const parts = currentPath.split(separator).filter(p => p);

        let breadcrumbHtml = '';
        let accumulatedPath = isWindows ? '' : '/';

        // Add root
        breadcrumbHtml += `<span class="breadcrumb-item" onclick="workspace.browseTo('${isWindows ? 'C:\\\\' : '/'}')">🏠</span>`;

        parts.forEach((part, index) => {
            accumulatedPath += (isWindows && index === 0) ? part : (separator + part);
            if (isWindows && index === 0) accumulatedPath += '\\';

            breadcrumbHtml += `
                <span class="breadcrumb-sep">/</span>
                <span class="breadcrumb-item" onclick="workspace.browseTo('${this.escapeJs(accumulatedPath)}')">${part}</span>
            `;
        });

        container.innerHTML = breadcrumbHtml;
    }

    renderFolders(folders, currentPath) {
        const container = document.getElementById('browser-folders');
        if (!container) return;

        if (!folders || folders.length === 0) {
            container.innerHTML = '<div class="browser-empty">Aucun sous-dossier</div>';
            return;
        }

        const foldersHtml = folders.map(folder => {
            const icon = folder.is_project ? '📦' : '📁';
            const badge = folder.is_project ? '<span class="folder-badge">Projet</span>' : '';

            return `
                <div class="browser-folder ${folder.is_project ? 'is-project' : ''}"
                     onclick="workspace.selectFolder(this, '${this.escapeJs(folder.path)}')"
                     ondblclick="workspace.browseTo('${this.escapeJs(folder.path)}')">
                    <span class="folder-icon">${icon}</span>
                    <span class="folder-name">${folder.name}</span>
                    ${badge}
                    <button class="folder-open-btn" onclick="event.stopPropagation(); workspace.browseTo('${this.escapeJs(folder.path)}')" title="Ouvrir">→</button>
                </div>
            `;
        }).join('');

        container.innerHTML = foldersHtml;
    }

    selectFolder(element, path) {
        // Update selection UI
        document.querySelectorAll('.browser-folder').forEach(f => f.classList.remove('selected'));
        element.classList.add('selected');

        // Update selected path display
        const selectedDisplay = document.getElementById('selected-folder');
        const openBtn = document.getElementById('btn-open-folder');

        if (selectedDisplay) {
            selectedDisplay.innerHTML = `<strong>Selectionne:</strong> ${path}`;
        }
        if (openBtn) {
            openBtn.disabled = false;
        }

        this.selectedPath = path;
    }

    async loadRecentProjects() {
        try {
            const response = await fetch('/api/workspace/recent');
            const data = await response.json();

            const container = document.getElementById('browser-recent');
            if (!container || !data.recent_projects?.length) return;

            container.innerHTML = `
                <div class="recent-header">Projets recents</div>
                ${data.recent_projects.slice(0, 5).map(path => `
                    <div class="recent-item" onclick="workspace.openDirect('${this.escapeJs(path)}')">
                        <span class="recent-icon">📦</span>
                        <span class="recent-name">${path.split(/[/\\]/).pop()}</span>
                    </div>
                `).join('')}
            `;
        } catch (error) {
            console.error('Failed to load recent:', error);
        }
    }

    async openDirect(path) {
        this.selectedPath = path;
        await this.confirmOpen();
    }

    async confirmOpen() {
        const path = this.selectedPath;
        if (!path) {
            window.showToast?.('Selectionnez un dossier', 'warning');
            return;
        }

        try {
            const response = await fetch('/api/workspace/open', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ project_path: path })
            });

            const result = await response.json();

            if (result.success) {
                this.closeModal();
                await this.loadState();
                this.render();
                this.activeProject = path;
                await this.reloadProjectData();

                if (!result.initialized && typeof projectInit !== 'undefined') {
                    projectInit.showInitModal({ project_name: result.project?.name });
                } else {
                    window.showToast?.(`Projet "${result.project?.name}" ouvert`, 'success');
                }
            } else {
                window.showToast?.(result.error || 'Erreur', 'error');
            }
        } catch (error) {
            console.error('Failed to open:', error);
            window.showToast?.('Erreur', 'error');
        }
    }

    async close(projectPath) {
        if (this.projects.length <= 1) {
            window.showToast?.('Impossible de fermer le dernier projet', 'warning');
            return;
        }

        try {
            const response = await fetch('/api/workspace/close', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ project_path: projectPath })
            });

            const result = await response.json();
            if (result.success) {
                await this.loadState();
                this.render();
                if (result.active_project !== projectPath) {
                    await this.reloadProjectData();
                }
            }
        } catch (error) {
            console.error('Failed to close:', error);
        }
    }

    async reloadProjectData() {
        // Reload kanban
        if (typeof loadKanban === 'function') {
            await loadKanban();
        } else if (typeof window.kanbanManager !== 'undefined') {
            await window.kanbanManager.loadTasks();
        }

        // Reload context if visible
        if (typeof contextManager !== 'undefined') {
            await contextManager.load();
        }

        // Reload settings
        if (typeof loadSettings === 'function') {
            await loadSettings();
        }
    }

    closeModal() {
        document.getElementById('open-project-modal')?.remove();
        this.selectedPath = null;
    }

    escapeJs(str) {
        return str.replace(/\\/g, '\\\\').replace(/'/g, "\\'");
    }
}

const workspace = new WorkspaceManager();

document.addEventListener('DOMContentLoaded', () => {
    workspace.init();
});
