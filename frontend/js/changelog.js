/**
 * Changelog Page - Affiche l'historique des commits Codeflow
 */

import { API } from './api.js';

class ChangelogManager {
    constructor() {
        this.container = document.getElementById('changelog-content');
        this.refreshBtn = document.getElementById('refresh-changelog-btn');
        this.commits = [];
        this.isLoading = false;

        this.init();
    }

    init() {
        if (this.refreshBtn) {
            this.refreshBtn.addEventListener('click', () => this.refresh());
        }
    }

    /**
     * Fetch changelog data from the API
     */
    async fetchChangelog() {
        try {
            const response = await API.changelog.get();
            return response.commits || [];
        } catch (error) {
            console.error('Failed to fetch changelog:', error);
            throw error;
        }
    }

    /**
     * Load and display the changelog
     */
    async load() {
        if (!this.container || this.isLoading) return;

        this.isLoading = true;
        this.container.innerHTML = '<div class="loading">Chargement du changelog...</div>';

        try {
            this.commits = await this.fetchChangelog();
            this.renderChangelog();
        } catch (error) {
            console.error('Failed to load changelog:', error);
            this.container.innerHTML = `
                <div class="error-message">
                    Erreur lors du chargement du changelog: ${error.message}
                </div>
            `;
        } finally {
            this.isLoading = false;
        }
    }

    /**
     * Refresh the changelog data
     */
    async refresh() {
        if (!this.container || !this.refreshBtn) return;

        this.refreshBtn.disabled = true;
        this.refreshBtn.textContent = 'Chargement...';

        try {
            this.commits = await this.fetchChangelog();
            this.renderChangelog();
            window.showToast?.('Changelog rafraichi', 'success');
        } catch (error) {
            console.error('Failed to refresh changelog:', error);
            window.showToast?.('Erreur lors du rafraichissement', 'error');
        } finally {
            this.refreshBtn.disabled = false;
            this.refreshBtn.textContent = 'Rafraichir';
        }
    }

    /**
     * Group commits by day (Aujourd'hui, Hier, or formatted date)
     */
    groupCommitsByDay(commits) {
        const groups = new Map();
        const now = new Date();
        const today = this.getDateKey(now);
        const yesterday = this.getDateKey(new Date(now.getTime() - 86400000));

        for (const commit of commits) {
            const commitDate = new Date(commit.date);
            const dateKey = this.getDateKey(commitDate);

            // Determine the display label for this day
            let label;
            if (dateKey === today) {
                label = "Aujourd'hui";
            } else if (dateKey === yesterday) {
                label = 'Hier';
            } else {
                label = this.formatDateLabel(commitDate);
            }

            if (!groups.has(dateKey)) {
                groups.set(dateKey, { label, commits: [] });
            }
            groups.get(dateKey).commits.push(commit);
        }

        // Convert to array sorted by date (most recent first)
        return Array.from(groups.entries())
            .sort((a, b) => b[0].localeCompare(a[0]))
            .map(([, group]) => group);
    }

    /**
     * Get a sortable date key (YYYY-MM-DD) for grouping
     */
    getDateKey(date) {
        return date.toISOString().split('T')[0];
    }

    /**
     * Format a date for display as group header (e.g., "Lundi 20 janvier")
     */
    formatDateLabel(date) {
        return date.toLocaleDateString('fr-FR', {
            weekday: 'long',
            day: 'numeric',
            month: 'long'
        });
    }

    /**
     * Render the changelog commits in the DOM
     */
    renderChangelog() {
        if (!this.container) return;

        if (this.commits.length === 0) {
            this.container.innerHTML = `
                <div class="changelog-empty">
                    <span class="empty-icon">📝</span>
                    <p>Aucun commit Codeflow trouve.</p>
                    <p class="empty-hint">Les commits effectues par Codeflow apparaitront ici.</p>
                </div>
            `;
            return;
        }

        // Group commits by day
        const groupedCommits = this.groupCommitsByDay(this.commits);

        // Render each day group
        const groupsHtml = groupedCommits.map(group => this.renderDayGroup(group)).join('');

        this.container.innerHTML = `
            <div class="changelog-list">
                ${groupsHtml}
            </div>
        `;

        // Attach event listeners after rendering
        this.attachEventListeners();
    }

    /**
     * Attach event listeners to interactive elements
     */
    attachEventListeners() {
        if (!this.container) return;

        // File toggle buttons
        this.container.querySelectorAll('.changelog-files-toggle').forEach(btn => {
            btn.addEventListener('click', (e) => {
                e.preventDefault();
                e.stopPropagation();
                this.toggleFilesList(btn);
            });
        });

        // Task links - navigate to kanban view and open task modal
        this.container.querySelectorAll('.changelog-task-link').forEach(link => {
            link.addEventListener('click', (e) => {
                e.preventDefault();
                e.stopPropagation();
                const taskId = link.dataset.taskId;
                this.navigateToTask(taskId);
            });
        });
    }

    /**
     * Toggle the visibility of a files list
     */
    toggleFilesList(button) {
        const targetId = button.dataset.target;
        const target = document.getElementById(targetId);
        if (!target) return;

        const isExpanded = button.getAttribute('aria-expanded') === 'true';
        button.setAttribute('aria-expanded', !isExpanded);

        // Toggle icon
        const icon = button.querySelector('.toggle-icon');
        if (icon) {
            icon.textContent = isExpanded ? '▶' : '▼';
        }

        // Toggle visibility
        target.classList.toggle('hidden', isExpanded);
    }

    /**
     * Navigate to a task in the kanban view
     */
    navigateToTask(taskId) {
        // Switch to kanban view
        const kanbanNav = document.querySelector('[data-view="kanban"]');
        if (kanbanNav) {
            kanbanNav.click();
        }

        // Wait for view to switch, then try to open the task
        setTimeout(() => {
            // Find the task card
            const taskCard = document.querySelector(`.task-card[data-id="${taskId}"]`);
            if (taskCard) {
                taskCard.click();
            } else {
                // Task not visible on kanban, show a toast
                window.showToast?.(`Tache #${taskId} non trouvee sur le tableau`, 'warning');
            }
        }, 100);
    }

    /**
     * Render a day group with header and commits
     */
    renderDayGroup(group) {
        const commitsHtml = group.commits.map(commit => this.renderCommit(commit)).join('');

        return `
            <div class="changelog-day-group">
                <div class="changelog-day-header">${group.label}</div>
                <div class="changelog-day-commits">
                    ${commitsHtml}
                </div>
            </div>
        `;
    }

    /**
     * Render a single commit entry
     */
    renderCommit(commit) {
        const time = this.formatTime(commit.date);
        const filesCount = commit.files?.length || 0;
        const filesText = filesCount === 1 ? '1 fichier modifie' : `${filesCount} fichiers modifies`;
        const commitId = `commit-${commit.hash}`;

        // Render task link if task_id is present
        const taskLink = commit.task_id
            ? `<a href="#" class="changelog-task-link" data-task-id="${commit.task_id}" title="Voir la tache #${commit.task_id}">#${commit.task_id}</a>`
            : '';

        // Render expandable file list
        const filesHtml = this.renderFilesList(commit.files, commitId);

        return `
            <div class="changelog-item" data-hash="${commit.hash}">
                <div class="changelog-item-header">
                    <span class="changelog-time">${time}</span>
                    <span class="changelog-hash">${commit.hash}</span>
                </div>
                <div class="changelog-message">${this.escapeHtml(commit.message)}</div>
                <div class="changelog-meta">
                    ${filesCount > 0 ? `
                        <button class="changelog-files-toggle" data-target="${commitId}-files" aria-expanded="false">
                            <span class="toggle-icon">▶</span>
                            <span class="files-icon">📁</span>
                            <span>${filesText}</span>
                        </button>
                    ` : `
                        <span class="changelog-files-empty">📁 Aucun fichier</span>
                    `}
                    ${taskLink}
                </div>
                ${filesHtml}
            </div>
        `;
    }

    /**
     * Render the expandable files list
     */
    renderFilesList(files, commitId) {
        if (!files || files.length === 0) {
            return '';
        }

        const filesHtml = files.map(file => {
            const icon = this.getFileIcon(file);
            return `<li class="changelog-file-item"><span class="file-icon">${icon}</span>${this.escapeHtml(file)}</li>`;
        }).join('');

        return `
            <div class="changelog-files-list hidden" id="${commitId}-files">
                <ul>${filesHtml}</ul>
            </div>
        `;
    }

    /**
     * Get an appropriate icon for a file based on its extension
     */
    getFileIcon(filename) {
        const ext = filename.split('.').pop()?.toLowerCase();
        const icons = {
            'js': '📜',
            'ts': '📜',
            'jsx': '⚛️',
            'tsx': '⚛️',
            'py': '🐍',
            'css': '🎨',
            'html': '🌐',
            'json': '📋',
            'md': '📝',
            'yml': '⚙️',
            'yaml': '⚙️',
            'sql': '🗄️',
            'sh': '💻',
            'bat': '💻',
        };
        return icons[ext] || '📄';
    }

    /**
     * Format date to display time only (HH:MM)
     */
    formatTime(isoString) {
        if (!isoString) return '--:--';

        const date = new Date(isoString);
        return date.toLocaleTimeString('fr-FR', {
            hour: '2-digit',
            minute: '2-digit'
        });
    }

    /**
     * Escape HTML special characters
     */
    escapeHtml(text) {
        if (!text) return '';
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }
}

// Instance globale
let changelogManager;

// Export for use in navigation
export function initChangelog() {
    if (!changelogManager) {
        changelogManager = new ChangelogManager();
    }
    changelogManager.load();
}

// Listen for view changes
window.addEventListener('view-changed', (e) => {
    if (e.detail.view === 'changelog') {
        initChangelog();
    }
});

// Initialize on DOM ready
document.addEventListener('DOMContentLoaded', () => {
    changelogManager = new ChangelogManager();
});

export { changelogManager };
