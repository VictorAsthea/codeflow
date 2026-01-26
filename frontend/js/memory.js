/**
 * Memory Page - Displays Claude Code session history
 */

import { API } from './api.js';

/**
 * Session Detail Modal - Shows full conversation and allows resume
 */
class SessionDetailModal {
    constructor() {
        this.modal = document.getElementById('memory-detail-modal');
        this.titleEl = document.getElementById('memory-detail-title');
        this.metaEl = document.getElementById('memory-detail-meta');
        this.conversationEl = document.getElementById('memory-conversation');
        this.resumeBtn = document.getElementById('btn-resume-session');
        this.deleteBtn = document.getElementById('btn-delete-session');

        this.currentSession = null;

        this.init();
    }

    init() {
        if (!this.modal) return;

        // Close button
        const closeBtn = this.modal.querySelector('.btn-close');
        if (closeBtn) {
            closeBtn.addEventListener('click', () => this.close());
        }

        // Click outside to close
        this.modal.addEventListener('click', (e) => {
            if (e.target === this.modal) {
                this.close();
            }
        });

        // Resume button
        if (this.resumeBtn) {
            this.resumeBtn.addEventListener('click', () => this.handleResume());
        }

        // Delete button
        if (this.deleteBtn) {
            this.deleteBtn.addEventListener('click', () => this.handleDelete());
        }

        // Listen for view session events
        window.addEventListener('memory-view-session', (e) => {
            this.open(e.detail.sessionId);
        });

        // Listen for resume session events
        window.addEventListener('memory-resume-session', (e) => {
            this.resumeSession(e.detail.sessionId);
        });

        // Escape key to close
        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape' && !this.modal.classList.contains('hidden')) {
                this.close();
            }
        });
    }

    async open(sessionId) {
        if (!this.modal) return;

        this.modal.classList.remove('hidden');
        this.conversationEl.innerHTML = '<div class="loading">Chargement de la conversation...</div>';
        this.metaEl.innerHTML = '';

        try {
            const session = await API.memory.get(sessionId);
            this.currentSession = session;
            this.render(session);
        } catch (error) {
            console.error('Failed to load session detail:', error);
            this.conversationEl.innerHTML = `
                <div class="error-message">
                    Erreur lors du chargement: ${error.message}
                </div>
            `;
        }
    }

    close() {
        if (this.modal) {
            this.modal.classList.add('hidden');
        }
        this.currentSession = null;
    }

    render(session) {
        // Update title
        const title = session.task_id
            ? `Task #${session.task_id}`
            : (session.summary || session.first_prompt?.slice(0, 50) || 'Session');
        this.titleEl.textContent = title;

        // Render metadata
        this.metaEl.innerHTML = this.renderMeta(session);

        // Render conversation
        this.renderConversation(session.messages || []);

        // Show/hide resume button based on resumable status
        if (this.resumeBtn) {
            if (session.is_resumable) {
                this.resumeBtn.classList.remove('hidden');
            } else {
                this.resumeBtn.classList.add('hidden');
            }
        }
    }

    renderMeta(session) {
        const formatDate = (isoString) => {
            if (!isoString) return 'N/A';
            return new Date(isoString).toLocaleString('fr-FR', {
                day: 'numeric',
                month: 'short',
                year: 'numeric',
                hour: '2-digit',
                minute: '2-digit'
            });
        };

        const formatTokens = (count) => {
            if (!count) return '0';
            if (count >= 1000000) return `${(count / 1000000).toFixed(1)}M`;
            if (count >= 1000) return `${(count / 1000).toFixed(0)}k`;
            return count.toString();
        };

        const statusClass = session.is_resumable ? 'completed' : 'running';
        const statusLabel = session.is_resumable ? 'Completed' : 'Running';

        return `
            <div class="memory-detail-info">
                <div class="memory-detail-row">
                    <span class="memory-detail-label">Session ID:</span>
                    <span class="memory-detail-value monospace">${this.escapeHtml(session.session_id)}</span>
                </div>
                <div class="memory-detail-row">
                    <span class="memory-detail-label">Created:</span>
                    <span class="memory-detail-value">${formatDate(session.created_at)}</span>
                </div>
                <div class="memory-detail-row">
                    <span class="memory-detail-label">Modified:</span>
                    <span class="memory-detail-value">${formatDate(session.modified_at)}</span>
                </div>
                <div class="memory-detail-row">
                    <span class="memory-detail-label">Messages:</span>
                    <span class="memory-detail-value">${session.message_count || 0}</span>
                </div>
                <div class="memory-detail-row">
                    <span class="memory-detail-label">Tokens:</span>
                    <span class="memory-detail-value">${formatTokens(session.token_count)}</span>
                </div>
                <div class="memory-detail-row">
                    <span class="memory-detail-label">Status:</span>
                    <span class="memory-session-status ${statusClass}">${statusLabel}</span>
                </div>
                ${session.git_branch ? `
                <div class="memory-detail-row">
                    <span class="memory-detail-label">Branch:</span>
                    <span class="memory-detail-value monospace">${this.escapeHtml(session.git_branch)}</span>
                </div>
                ` : ''}
            </div>
        `;
    }

    renderConversation(messages) {
        if (!messages || messages.length === 0) {
            this.conversationEl.innerHTML = `
                <div class="memory-empty">
                    <p>Aucun message dans cette session.</p>
                </div>
            `;
            return;
        }

        const messagesHtml = messages.map(msg => this.renderMessage(msg)).join('');
        this.conversationEl.innerHTML = messagesHtml;
    }

    renderMessage(message) {
        const roleClass = message.role === 'user' ? 'user' : 'assistant';
        const roleLabel = message.role === 'user' ? 'Vous' : 'Claude';

        const formatTime = (isoString) => {
            if (!isoString) return '';
            return new Date(isoString).toLocaleTimeString('fr-FR', {
                hour: '2-digit',
                minute: '2-digit'
            });
        };

        // Format content - truncate very long content and handle code blocks
        let content = message.content || '';
        const maxLength = 2000;
        if (content.length > maxLength) {
            content = content.slice(0, maxLength) + '\n\n[... contenu tronque ...]';
        }

        return `
            <div class="memory-message ${roleClass}">
                <div class="memory-message-header">
                    <span class="memory-message-role">${roleLabel}</span>
                    <span class="memory-message-time">${formatTime(message.timestamp)}</span>
                </div>
                <div class="memory-message-content">${this.formatContent(content)}</div>
            </div>
        `;
    }

    formatContent(content) {
        // Escape HTML first
        let formatted = this.escapeHtml(content);

        // Convert markdown-like code blocks to HTML
        formatted = formatted.replace(/```(\w*)\n([\s\S]*?)```/g, (match, lang, code) => {
            return `<pre><code class="language-${lang || 'plaintext'}">${code}</code></pre>`;
        });

        // Convert inline code
        formatted = formatted.replace(/`([^`]+)`/g, '<code>$1</code>');

        // Convert newlines to br (outside of pre tags)
        formatted = formatted.replace(/\n/g, '<br>');

        return formatted;
    }

    async handleResume() {
        if (!this.currentSession) return;
        await this.resumeSession(this.currentSession.session_id);
    }

    async resumeSession(sessionId) {
        try {
            window.showToast?.('Lancement de la session...', 'info');

            const result = await API.memory.resume(sessionId);

            window.showToast?.('Session lancee dans un nouveau terminal', 'success');

            // Close the modal
            this.close();
        } catch (error) {
            console.error('Failed to resume session:', error);
            window.showToast?.(`Erreur: ${error.message}`, 'error');
        }
    }

    async handleDelete() {
        if (!this.currentSession) return;

        if (!confirm('Supprimer cette session ? Cette action est irreversible.')) {
            return;
        }

        try {
            await API.memory.delete(this.currentSession.session_id);

            window.showToast?.('Session supprimee', 'success');

            // Dispatch event to refresh sessions list
            window.dispatchEvent(new CustomEvent('memory-session-deleted', {
                detail: { sessionId: this.currentSession.session_id }
            }));

            this.close();
        } catch (error) {
            console.error('Failed to delete session:', error);
            window.showToast?.(`Erreur: ${error.message}`, 'error');
        }
    }

    escapeHtml(text) {
        if (!text) return '';
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }
}

class MemoryManager {
    constructor() {
        this.sessionsContainer = document.getElementById('memory-sessions-list');
        this.contextContainer = document.getElementById('memory-project-context');
        this.refreshBtn = document.getElementById('refresh-memory-btn');
        this.filterSelect = document.getElementById('memory-filter-select');

        this.sessions = [];
        this.isLoading = false;
        this.currentFilter = 'all';

        this.init();
    }

    init() {
        if (this.refreshBtn) {
            this.refreshBtn.addEventListener('click', () => this.refresh());
        }

        if (this.filterSelect) {
            this.filterSelect.addEventListener('change', (e) => {
                this.currentFilter = e.target.value;
                this.render();
            });
        }
    }

    /**
     * Fetch sessions from the API
     */
    async fetchSessions() {
        try {
            const sessions = await API.memory.list({
                includeWorktrees: true,
                limit: 50
            });
            return sessions || [];
        } catch (error) {
            console.error('Failed to fetch sessions:', error);
            throw error;
        }
    }

    /**
     * Fetch project context summary
     */
    async fetchContext() {
        try {
            const context = await API.context.getSummary();
            return context;
        } catch (error) {
            console.error('Failed to fetch context:', error);
            return null;
        }
    }

    /**
     * Load and display sessions
     */
    async load() {
        if (!this.sessionsContainer || this.isLoading) return;

        this.isLoading = true;
        this.sessionsContainer.innerHTML = '<div class="loading">Chargement des sessions...</div>';

        try {
            const [sessions, context] = await Promise.all([
                this.fetchSessions(),
                this.fetchContext()
            ]);

            this.sessions = sessions;
            this.render();
            this.renderContext(context);
        } catch (error) {
            console.error('Failed to load memory:', error);
            this.sessionsContainer.innerHTML = `
                <div class="error-message">
                    Erreur lors du chargement: ${error.message}
                </div>
            `;
        } finally {
            this.isLoading = false;
        }
    }

    /**
     * Refresh sessions
     */
    async refresh() {
        if (!this.sessionsContainer || !this.refreshBtn) return;

        this.refreshBtn.disabled = true;
        this.refreshBtn.textContent = 'Chargement...';

        try {
            this.sessions = await this.fetchSessions();
            this.render();
            window.showToast?.('Sessions rafraichies', 'success');
        } catch (error) {
            console.error('Failed to refresh sessions:', error);
            window.showToast?.('Erreur lors du rafraichissement', 'error');
        } finally {
            this.refreshBtn.disabled = false;
            this.refreshBtn.textContent = 'Rafraichir';
        }
    }

    /**
     * Render sessions list
     */
    render() {
        if (!this.sessionsContainer) return;

        // Apply filter
        let filteredSessions = this.sessions;
        if (this.currentFilter === 'task') {
            filteredSessions = this.sessions.filter(s => s.task_id);
        }

        if (filteredSessions.length === 0) {
            this.sessionsContainer.innerHTML = `
                <div class="memory-empty">
                    <span class="empty-icon">🧠</span>
                    <p>Aucune session trouvee.</p>
                    <p class="empty-hint">Les sessions Claude Code apparaitront ici.</p>
                </div>
            `;
            return;
        }

        // Group sessions by day
        const groupedSessions = this.groupSessionsByDay(filteredSessions);

        const groupsHtml = groupedSessions.map(group => this.renderDayGroup(group)).join('');

        this.sessionsContainer.innerHTML = `
            <div class="memory-sessions-grid">
                ${groupsHtml}
            </div>
        `;

        this.attachEventListeners();
    }

    /**
     * Group sessions by day
     */
    groupSessionsByDay(sessions) {
        const groups = new Map();
        const now = new Date();
        const today = this.getDateKey(now);
        const yesterday = this.getDateKey(new Date(now.getTime() - 86400000));

        for (const session of sessions) {
            const sessionDate = new Date(session.modified_at);
            const dateKey = this.getDateKey(sessionDate);

            let label;
            if (dateKey === today) {
                label = "Aujourd'hui";
            } else if (dateKey === yesterday) {
                label = 'Hier';
            } else {
                label = this.formatDateLabel(sessionDate);
            }

            if (!groups.has(dateKey)) {
                groups.set(dateKey, { label, sessions: [] });
            }
            groups.get(dateKey).sessions.push(session);
        }

        return Array.from(groups.entries())
            .sort((a, b) => b[0].localeCompare(a[0]))
            .map(([, group]) => group);
    }

    /**
     * Get sortable date key
     */
    getDateKey(date) {
        return date.toISOString().split('T')[0];
    }

    /**
     * Format date for display
     */
    formatDateLabel(date) {
        return date.toLocaleDateString('fr-FR', {
            weekday: 'long',
            day: 'numeric',
            month: 'long'
        });
    }

    /**
     * Render a day group
     */
    renderDayGroup(group) {
        const sessionsHtml = group.sessions.map(s => this.renderSessionCard(s)).join('');

        return `
            <div class="memory-day-group">
                <div class="memory-day-header">${group.label}</div>
                <div class="memory-day-sessions">
                    ${sessionsHtml}
                </div>
            </div>
        `;
    }

    /**
     * Render a single session card
     */
    renderSessionCard(session) {
        const relativeTime = this.formatRelativeTime(session.modified_at);
        const messageCount = session.message_count || 0;
        const tokenCount = session.token_count || 0;
        const tokenDisplay = this.formatTokenCount(tokenCount);

        // Determine session title
        const title = session.task_id
            ? `Task #${session.task_id}`
            : (session.summary || session.first_prompt?.slice(0, 50) || 'Session');

        // Determine status
        const status = session.is_resumable ? 'completed' : 'running';
        const statusLabel = session.is_resumable ? 'Completed' : 'Running';

        // Worktree info
        const worktreeInfo = session.git_branch
            ? `<span class="memory-session-worktree">Worktree: ${this.escapeHtml(session.git_branch)}</span>`
            : '';

        // Resume button only if resumable
        const resumeBtn = session.is_resumable
            ? `<button class="btn-action btn-resume" data-session-id="${session.session_id}" title="Reprendre">▶️ Reprendre</button>`
            : '';

        return `
            <div class="memory-session-card" data-session-id="${session.session_id}">
                <div class="memory-session-header">
                    <div class="memory-session-title">
                        <span class="memory-session-icon">📝</span>
                        <span class="memory-session-name">${this.escapeHtml(title)}</span>
                    </div>
                    <span class="memory-session-time">${relativeTime}</span>
                </div>
                <div class="memory-session-meta">
                    <span class="memory-session-messages">${messageCount} messages</span>
                    <span class="memory-session-tokens">${tokenDisplay} tokens</span>
                    <span class="memory-session-status ${status}">${statusLabel}</span>
                </div>
                ${worktreeInfo}
                <div class="memory-session-actions">
                    <button class="btn-action btn-view" data-session-id="${session.session_id}" title="Voir">👁️ Voir</button>
                    ${resumeBtn}
                    <button class="btn-action btn-delete" data-session-id="${session.session_id}" title="Supprimer">🗑️</button>
                </div>
            </div>
        `;
    }

    /**
     * Format token count for display
     */
    formatTokenCount(count) {
        if (count >= 1000000) {
            return `${(count / 1000000).toFixed(1)}M`;
        }
        if (count >= 1000) {
            return `${(count / 1000).toFixed(0)}k`;
        }
        return count.toString();
    }

    /**
     * Format relative time
     */
    formatRelativeTime(isoString) {
        if (!isoString) return '';

        const date = new Date(isoString);
        const now = new Date();
        const diffMs = now - date;
        const diffMins = Math.floor(diffMs / 60000);
        const diffHours = Math.floor(diffMs / 3600000);
        const diffDays = Math.floor(diffMs / 86400000);

        if (diffMins < 1) return "A l'instant";
        if (diffMins < 60) return `il y a ${diffMins} min`;
        if (diffHours < 24) return `il y a ${diffHours}h`;
        if (diffDays === 1) return 'Hier';
        if (diffDays < 7) return `il y a ${diffDays} jours`;

        return date.toLocaleDateString('fr-FR', {
            day: 'numeric',
            month: 'short'
        });
    }

    /**
     * Render project context summary
     */
    renderContext(context) {
        if (!this.contextContainer) return;

        if (!context) {
            this.contextContainer.innerHTML = `
                <div class="memory-context-summary">
                    <p class="memory-empty-hint">Aucune analyse disponible</p>
                </div>
            `;
            return;
        }

        const stack = context.stack || [];
        const patterns = context.patterns || [];
        const lastAnalysis = context.last_analysis
            ? this.formatRelativeTime(context.last_analysis)
            : 'Jamais';

        this.contextContainer.innerHTML = `
            <div class="memory-context-summary">
                <div class="memory-context-row">
                    <span class="memory-context-label">Stack:</span>
                    <span class="memory-context-value">${stack.length > 0 ? this.escapeHtml(stack.join(' + ')) : 'Non detecte'}</span>
                </div>
                <div class="memory-context-row">
                    <span class="memory-context-label">Patterns:</span>
                    <div class="memory-context-tags">
                        ${patterns.map(p => `<span class="memory-context-tag">${this.escapeHtml(p)}</span>`).join('')}
                    </div>
                </div>
                <div class="memory-context-row">
                    <span class="memory-context-label">Derniere analyse:</span>
                    <span class="memory-context-date">${lastAnalysis}</span>
                </div>
            </div>
        `;
    }

    /**
     * Attach event listeners to session cards
     */
    attachEventListeners() {
        if (!this.sessionsContainer) return;

        // View session buttons
        this.sessionsContainer.querySelectorAll('.btn-view').forEach(btn => {
            btn.addEventListener('click', (e) => {
                e.preventDefault();
                e.stopPropagation();
                const sessionId = btn.dataset.sessionId;
                this.viewSession(sessionId);
            });
        });

        // Resume session buttons
        this.sessionsContainer.querySelectorAll('.btn-resume').forEach(btn => {
            btn.addEventListener('click', (e) => {
                e.preventDefault();
                e.stopPropagation();
                const sessionId = btn.dataset.sessionId;
                this.resumeSession(sessionId);
            });
        });

        // Delete session buttons
        this.sessionsContainer.querySelectorAll('.btn-delete').forEach(btn => {
            btn.addEventListener('click', (e) => {
                e.preventDefault();
                e.stopPropagation();
                const sessionId = btn.dataset.sessionId;
                this.deleteSession(sessionId);
            });
        });

        // Click on card to view
        this.sessionsContainer.querySelectorAll('.memory-session-card').forEach(card => {
            card.addEventListener('click', (e) => {
                // Don't trigger if clicking a button
                if (e.target.closest('.btn-action')) return;
                const sessionId = card.dataset.sessionId;
                this.viewSession(sessionId);
            });
        });
    }

    /**
     * View session detail (opens modal)
     */
    viewSession(sessionId) {
        // Dispatch event for the detail modal to handle
        window.dispatchEvent(new CustomEvent('memory-view-session', {
            detail: { sessionId }
        }));
    }

    /**
     * Resume a session
     */
    resumeSession(sessionId) {
        // Dispatch event for resume action
        window.dispatchEvent(new CustomEvent('memory-resume-session', {
            detail: { sessionId }
        }));
    }

    /**
     * Handle session deleted event
     */
    handleSessionDeleted(sessionId) {
        // Remove from local list
        this.sessions = this.sessions.filter(s => s.session_id !== sessionId);
        this.render();
    }

    /**
     * Delete a session
     */
    async deleteSession(sessionId) {
        if (!confirm('Supprimer cette session ?')) {
            return;
        }

        try {
            await API.memory.delete(sessionId);

            // Remove from local list
            this.sessions = this.sessions.filter(s => s.session_id !== sessionId);
            this.render();

            window.showToast?.('Session supprimee', 'success');
        } catch (error) {
            console.error('Failed to delete session:', error);
            window.showToast?.('Erreur lors de la suppression', 'error');
        }
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

// Global instances
let memoryManager;
let sessionDetailModal;

/**
 * Initialize Memory view
 */
export function initMemory() {
    if (!memoryManager) {
        memoryManager = new MemoryManager();
    }
    if (!sessionDetailModal) {
        sessionDetailModal = new SessionDetailModal();
    }
    memoryManager.load();
}

/**
 * Open session detail modal (can be called externally)
 */
export function openSessionDetail(sessionId) {
    if (!sessionDetailModal) {
        sessionDetailModal = new SessionDetailModal();
    }
    sessionDetailModal.open(sessionId);
}

/**
 * Resume a session (can be called externally)
 */
export function resumeSession(sessionId) {
    if (!sessionDetailModal) {
        sessionDetailModal = new SessionDetailModal();
    }
    sessionDetailModal.resumeSession(sessionId);
}

// Listen for view changes
window.addEventListener('view-changed', (e) => {
    if (e.detail.view === 'memory') {
        initMemory();
    }
});

// Listen for session deleted events
window.addEventListener('memory-session-deleted', (e) => {
    if (memoryManager) {
        memoryManager.handleSessionDeleted(e.detail.sessionId);
    }
});

// Initialize on DOM ready
document.addEventListener('DOMContentLoaded', () => {
    memoryManager = new MemoryManager();
    sessionDetailModal = new SessionDetailModal();
});

export { memoryManager, sessionDetailModal };
