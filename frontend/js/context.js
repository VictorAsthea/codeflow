/**
 * Context Page - Affiche le contexte du projet
 */

import { api } from './api.js';

class ContextManager {
    constructor() {
        this.container = document.getElementById('context-content');
        this.refreshBtn = document.getElementById('refresh-context-btn');
        this.contextData = null;

        this.init();
    }

    init() {
        if (this.refreshBtn) {
            this.refreshBtn.addEventListener('click', () => this.refresh());
        }
    }

    async load() {
        if (!this.container) return;

        this.container.innerHTML = '<div class="loading">Chargement du contexte...</div>';

        try {
            this.contextData = await api.context.get();
            this.render();
        } catch (error) {
            console.error('Failed to load context:', error);
            this.container.innerHTML = `
                <div class="error-message">
                    Erreur lors du chargement du contexte: ${error.message}
                </div>
            `;
        }
    }

    async refresh() {
        if (!this.container || !this.refreshBtn) return;

        this.refreshBtn.disabled = true;
        this.refreshBtn.textContent = 'Scan en cours...';

        try {
            const result = await api.context.refresh();
            this.contextData = result.context;
            this.render();
            window.showToast?.('Contexte rafraichi', 'success');
        } catch (error) {
            console.error('Failed to refresh context:', error);
            window.showToast?.('Erreur lors du rafraichissement', 'error');
        } finally {
            this.refreshBtn.disabled = false;
            this.refreshBtn.textContent = 'Rafraichir';
        }
    }

    render() {
        if (!this.contextData || !this.container) return;

        const ctx = this.contextData;
        const scannedAt = ctx.scanned_at ? this.formatRelativeTime(ctx.scanned_at) : 'Jamais';
        const isStale = this.isContextStale(ctx.scanned_at);

        this.container.innerHTML = `
            <!-- APERCU -->
            <div class="context-section">
                <div class="context-section-header">
                    <h3>Apercu</h3>
                </div>
                <div class="context-section-content">
                    <div class="context-info-grid">
                        <div class="context-info-item">
                            <span class="context-label">Projet</span>
                            <span class="context-value">${ctx.project_name || 'Non defini'}</span>
                        </div>
                        <div class="context-info-item">
                            <span class="context-label">Chemin</span>
                            <span class="context-value context-path">${ctx.project_path || '.'}</span>
                        </div>
                        <div class="context-info-item">
                            <span class="context-label">Scanne</span>
                            <span class="context-value">
                                ${scannedAt}
                                ${isStale ? '<span class="context-stale-badge">Perime</span>' : '<span class="context-valid-badge">Valide</span>'}
                            </span>
                        </div>
                    </div>
                </div>
            </div>

            <!-- STACK TECHNIQUE -->
            <div class="context-section">
                <div class="context-section-header">
                    <h3>Stack Technique</h3>
                </div>
                <div class="context-section-content">
                    <div class="context-tags">
                        ${this.renderStackTags(ctx.stack, ctx.frameworks)}
                    </div>
                </div>
            </div>

            <!-- STRUCTURE -->
            <div class="context-section">
                <div class="context-section-header">
                    <h3>Structure</h3>
                </div>
                <div class="context-section-content">
                    ${this.renderStructure(ctx)}
                </div>
            </div>

            <!-- CONVENTIONS -->
            <div class="context-section">
                <div class="context-section-header">
                    <h3>Conventions</h3>
                </div>
                <div class="context-section-content">
                    ${this.renderConventions(ctx.conventions)}
                </div>
            </div>

            <!-- ARBORESCENCE -->
            <div class="context-section">
                <div class="context-section-header">
                    <h3>Arborescence</h3>
                    <button class="context-toggle-btn" id="toggle-tree-btn">
                        Voir plus
                    </button>
                </div>
                <div class="context-section-content">
                    <div class="context-tree" id="context-tree">
                        ${this.renderTree(ctx.structure)}
                    </div>
                </div>
            </div>
        `;

        // Attach toggle event
        const toggleBtn = document.getElementById('toggle-tree-btn');
        if (toggleBtn) {
            toggleBtn.addEventListener('click', () => this.toggleTree());
        }
    }

    renderStackTags(stack = [], frameworks = []) {
        const allTags = [...stack, ...frameworks];

        if (allTags.length === 0) {
            return '<span class="context-empty">Aucun stack detecte</span>';
        }

        const icons = {
            'python': 'P',
            'node': 'N',
            'typescript': 'TS',
            'javascript': 'JS',
            'react': 'R',
            'vue': 'V',
            'nextjs': 'Nx',
            'fastapi': 'FA',
            'django': 'Dj',
            'flask': 'Fl',
            'express': 'Ex',
            'tailwind': 'TW',
            'tailwindcss': 'TW'
        };

        return allTags.map(tag => {
            const icon = icons[tag.toLowerCase()] || tag.charAt(0).toUpperCase();
            return `<span class="context-tag"><span class="tag-icon">${icon}</span> ${this.capitalize(tag)}</span>`;
        }).join('');
    }

    renderStructure(ctx) {
        const keyDirs = ctx.key_directories || [];
        const keyFiles = ctx.key_files || [];

        let html = '';

        if (keyDirs.length > 0) {
            html += `
                <div class="context-structure-group">
                    <div class="context-structure-label">Repertoires cles</div>
                    <div class="context-structure-items">
                        ${keyDirs.map(dir => `<span class="context-dir">${dir}/</span>`).join('')}
                    </div>
                </div>
            `;
        }

        if (keyFiles.length > 0) {
            html += `
                <div class="context-structure-group">
                    <div class="context-structure-label">Fichiers cles</div>
                    <div class="context-structure-items">
                        ${keyFiles.map(file => `<span class="context-file">${file}</span>`).join('')}
                    </div>
                </div>
            `;
        }

        if (html === '') {
            html = '<span class="context-empty">Aucune structure detectee</span>';
        }

        return html;
    }

    renderConventions(conventions = {}) {
        const items = [
            { key: 'typescript', label: 'TypeScript' },
            { key: 'eslint', label: 'ESLint' },
            { key: 'prettier', label: 'Prettier' },
            { key: 'styling', label: 'Styling' }
        ];

        const hasAny = Object.keys(conventions).length > 0;

        if (!hasAny) {
            return '<span class="context-empty">Aucune convention detectee</span>';
        }

        return `
            <div class="context-conventions-grid">
                ${items.map(item => {
                    const value = conventions[item.key];
                    if (value === undefined) return '';

                    const isEnabled = value === true || (typeof value === 'string' && value);
                    const displayValue = typeof value === 'string' ? value : (isEnabled ? 'Active' : 'Non');
                    const statusClass = isEnabled ? 'enabled' : 'disabled';

                    return `
                        <div class="context-convention-item ${statusClass}">
                            <span class="convention-label">${item.label}</span>
                            <span class="convention-value">${isEnabled ? 'Oui' : 'Non'} ${typeof value === 'string' ? `(${displayValue})` : ''}</span>
                        </div>
                    `;
                }).join('')}
            </div>
        `;
    }

    renderTree(structure = {}, level = 0) {
        if (Object.keys(structure).length === 0) {
            return '<span class="context-empty">Arborescence vide</span>';
        }

        const maxInitialItems = level === 0 ? 10 : 5;
        const entries = Object.entries(structure);
        const visibleEntries = entries.slice(0, maxInitialItems);
        const hiddenCount = entries.length - maxInitialItems;

        let html = '<ul class="context-tree-list">';

        for (const [name, value] of visibleEntries) {
            const isDir = typeof value === 'object';

            html += `<li class="context-tree-item ${isDir ? 'is-dir' : 'is-file'}">`;
            html += `<span class="tree-name">${name}</span>`;

            if (isDir && Object.keys(value).length > 0 && level < 2) {
                html += this.renderTree(value, level + 1);
            }

            html += '</li>';
        }

        if (hiddenCount > 0) {
            html += `<li class="context-tree-more">... et ${hiddenCount} autres</li>`;
        }

        html += '</ul>';
        return html;
    }

    toggleTree() {
        const tree = document.getElementById('context-tree');
        const btn = document.getElementById('toggle-tree-btn');
        if (tree) {
            tree.classList.toggle('expanded');
            if (btn) {
                btn.textContent = tree.classList.contains('expanded') ? 'Voir moins' : 'Voir plus';
            }
        }
    }

    formatRelativeTime(isoString) {
        if (!isoString) return 'Jamais';

        const date = new Date(isoString);
        const now = new Date();
        const diffMs = now - date;
        const diffMins = Math.floor(diffMs / 60000);
        const diffHours = Math.floor(diffMs / 3600000);
        const diffDays = Math.floor(diffMs / 86400000);

        if (diffMins < 1) return 'A l\'instant';
        if (diffMins < 60) return `il y a ${diffMins} min`;
        if (diffHours < 24) return `il y a ${diffHours}h`;
        if (diffDays < 7) return `il y a ${diffDays}j`;

        return date.toLocaleDateString('fr-FR');
    }

    isContextStale(isoString) {
        if (!isoString) return true;

        const date = new Date(isoString);
        const now = new Date();
        const diffHours = (now - date) / 3600000;

        return diffHours > 24; // Perime si > 24h
    }

    capitalize(str) {
        return str.charAt(0).toUpperCase() + str.slice(1);
    }
}

// Instance globale
let contextManager;

// Export for use in navigation
export function initContext() {
    if (!contextManager) {
        contextManager = new ContextManager();
    }
    contextManager.load();
}

// Listen for view changes
window.addEventListener('view-changed', (e) => {
    if (e.detail.view === 'context') {
        initContext();
    }
});

// Initialize on DOM ready
document.addEventListener('DOMContentLoaded', () => {
    contextManager = new ContextManager();
});

export { contextManager };
