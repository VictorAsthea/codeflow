/**
 * Ideation Page - AI-powered project analysis and suggestions
 */

import { API } from './api.js';

class IdeationManager {
    constructor() {
        this.analysisContent = document.getElementById('ideation-analysis-content');
        this.suggestionsList = document.getElementById('ideation-suggestions-list');
        this.chatMessages = document.getElementById('ideation-chat-messages');
        this.chatInput = document.getElementById('ideation-chat-input');

        this.analyzeBtn = document.getElementById('ideation-analyze-btn');
        this.suggestBtn = document.getElementById('ideation-suggest-btn');
        this.chatSendBtn = document.getElementById('ideation-chat-send');
        this.filterCategory = document.getElementById('ideation-filter-category');
        this.filterStatus = document.getElementById('ideation-filter-status');

        this.suggestions = [];
        this.analysis = null;
        this.chatHistory = [];
        this.isLoading = false;

        this.init();
    }

    init() {
        // Button listeners
        this.analyzeBtn?.addEventListener('click', () => this.analyzeProject());
        this.suggestBtn?.addEventListener('click', () => this.generateSuggestions());
        this.chatSendBtn?.addEventListener('click', () => this.sendChatMessage());

        // Chat input enter key
        this.chatInput?.addEventListener('keypress', (e) => {
            if (e.key === 'Enter') this.sendChatMessage();
        });

        // Filter listeners
        this.filterCategory?.addEventListener('change', () => this.renderSuggestions());
        this.filterStatus?.addEventListener('change', () => this.renderSuggestions());

        // Listen for view changes to load data when ideation view is shown
        window.addEventListener('view-changed', (e) => {
            if (e.detail?.view === 'ideation') {
                this.load();
            }
        });
    }

    async load() {
        if (this.isLoading) return;
        this.isLoading = true;

        try {
            const data = await API.ideation.getData();
            this.analysis = data.analysis;
            this.suggestions = data.suggestions || [];

            this.renderAnalysis();
            this.renderSuggestions();
        } catch (error) {
            console.error('Failed to load ideation data:', error);
        } finally {
            this.isLoading = false;
        }
    }

    async analyzeProject() {
        if (!this.analyzeBtn) return;

        this.analyzeBtn.disabled = true;
        this.analyzeBtn.textContent = '🔄 Analyse en cours...';
        this.analysisContent.innerHTML = '<div class="loading">Analyse du projet en cours...</div>';

        try {
            const result = await API.ideation.analyze();
            this.analysis = result.analysis;
            this.renderAnalysis();
            window.showToast?.('Analyse terminée', 'success');
        } catch (error) {
            console.error('Analysis failed:', error);
            this.analysisContent.innerHTML = `<div class="error-message">Erreur: ${error.message}</div>`;
            window.showToast?.('Erreur lors de l\'analyse', 'error');
        } finally {
            this.analyzeBtn.disabled = false;
            this.analyzeBtn.textContent = '🔍 Analyser';
        }
    }

    async generateSuggestions() {
        if (!this.suggestBtn) return;

        this.suggestBtn.disabled = true;
        this.suggestBtn.textContent = '🔄 Génération...';
        this.suggestionsList.innerHTML = '<div class="loading">Génération des suggestions en cours...</div>';

        try {
            const result = await API.ideation.suggest();
            // Merge new suggestions with existing
            const existingIds = new Set(this.suggestions.map(s => s.id));
            const newSuggestions = result.suggestions.filter(s => !existingIds.has(s.id));
            this.suggestions = [...this.suggestions, ...newSuggestions];

            this.renderSuggestions();
            window.showToast?.(`${result.count} suggestions générées`, 'success');
        } catch (error) {
            console.error('Suggestion generation failed:', error);
            this.suggestionsList.innerHTML = `<div class="error-message">Erreur: ${error.message}</div>`;
            window.showToast?.('Erreur lors de la génération', 'error');
        } finally {
            this.suggestBtn.disabled = false;
            this.suggestBtn.textContent = '✨ Générer suggestions';
        }
    }

    async acceptSuggestion(suggestionId) {
        try {
            const result = await API.ideation.acceptSuggestion(suggestionId);

            // Update local state
            const suggestion = this.suggestions.find(s => s.id === suggestionId);
            if (suggestion) {
                suggestion.status = 'accepted';
                suggestion.task_id = result.task_id;
            }

            this.renderSuggestions();
            window.showToast?.('Tâche créée depuis la suggestion', 'success');
        } catch (error) {
            console.error('Failed to accept suggestion:', error);
            window.showToast?.('Erreur lors de l\'acceptation', 'error');
        }
    }

    async dismissSuggestion(suggestionId) {
        try {
            await API.ideation.dismissSuggestion(suggestionId);

            // Update local state
            const suggestion = this.suggestions.find(s => s.id === suggestionId);
            if (suggestion) {
                suggestion.status = 'dismissed';
            }

            this.renderSuggestions();
            window.showToast?.('Suggestion ignorée', 'info');
        } catch (error) {
            console.error('Failed to dismiss suggestion:', error);
            window.showToast?.('Erreur', 'error');
        }
    }

    async sendChatMessage() {
        const message = this.chatInput?.value?.trim();
        if (!message || !this.chatMessages) return;

        // Add user message to UI
        this.chatHistory.push({ role: 'user', content: message });
        this.renderChat();
        this.chatInput.value = '';

        // Show loading
        const loadingMsg = document.createElement('div');
        loadingMsg.className = 'chat-message assistant loading';
        loadingMsg.textContent = '...';
        this.chatMessages.appendChild(loadingMsg);
        this.chatMessages.scrollTop = this.chatMessages.scrollHeight;

        try {
            const result = await API.ideation.chat(message, this.chatHistory.slice(0, -1));

            // Remove loading
            loadingMsg.remove();

            // Add assistant response
            this.chatHistory.push({ role: 'assistant', content: result.response });
            this.renderChat();
        } catch (error) {
            console.error('Chat failed:', error);
            loadingMsg.remove();
            this.chatHistory.push({ role: 'assistant', content: 'Erreur: impossible de répondre.' });
            this.renderChat();
        }
    }

    renderAnalysis() {
        if (!this.analysisContent) return;

        if (!this.analysis) {
            this.analysisContent.innerHTML = '<p class="ideation-placeholder">Cliquez sur "Analyser" pour scanner votre projet</p>';
            return;
        }

        const a = this.analysis;
        this.analysisContent.innerHTML = `
            <div class="analysis-grid">
                <div class="analysis-card">
                    <span class="analysis-label">Projet</span>
                    <span class="analysis-value">${a.project_name || 'N/A'}</span>
                </div>
                <div class="analysis-card">
                    <span class="analysis-label">Fichiers</span>
                    <span class="analysis-value">${a.files_count || 0}</span>
                </div>
                <div class="analysis-card">
                    <span class="analysis-label">Lignes de code</span>
                    <span class="analysis-value">${(a.lines_count || 0).toLocaleString()}</span>
                </div>
                <div class="analysis-card">
                    <span class="analysis-label">Stack</span>
                    <span class="analysis-value">${(a.stack || []).join(', ') || 'N/A'}</span>
                </div>
                <div class="analysis-card">
                    <span class="analysis-label">Frameworks</span>
                    <span class="analysis-value">${(a.frameworks || []).join(', ') || 'N/A'}</span>
                </div>
                <div class="analysis-card">
                    <span class="analysis-label">Patterns détectés</span>
                    <span class="analysis-value">${(a.patterns_detected || []).join(', ') || 'N/A'}</span>
                </div>
            </div>
        `;
    }

    renderSuggestions() {
        if (!this.suggestionsList) return;

        const categoryFilter = this.filterCategory?.value || 'all';
        const statusFilter = this.filterStatus?.value || 'pending';

        let filtered = this.suggestions;

        if (categoryFilter !== 'all') {
            filtered = filtered.filter(s => s.category === categoryFilter);
        }

        if (statusFilter !== 'all') {
            filtered = filtered.filter(s => s.status === statusFilter);
        }

        if (filtered.length === 0) {
            this.suggestionsList.innerHTML = '<p class="ideation-placeholder">Aucune suggestion correspondante.</p>';
            return;
        }

        const categoryEmojis = {
            security: '🔒',
            performance: '⚡',
            quality: '📝',
            feature: '✨'
        };

        const priorityClasses = {
            high: 'priority-high',
            medium: 'priority-medium',
            low: 'priority-low'
        };

        this.suggestionsList.innerHTML = filtered.map(s => `
            <div class="suggestion-card ${s.status}" data-id="${s.id}">
                <div class="suggestion-header">
                    <span class="suggestion-category">${categoryEmojis[s.category] || '💡'} ${s.category}</span>
                    <span class="suggestion-priority ${priorityClasses[s.priority] || ''}">${s.priority}</span>
                </div>
                <h4 class="suggestion-title">${s.title}</h4>
                <p class="suggestion-description">${s.description}</p>
                <div class="suggestion-actions">
                    ${s.status === 'pending' ? `
                        <button class="btn btn-sm btn-primary" onclick="window.ideationManager.acceptSuggestion('${s.id}')">
                            ✅ Créer tâche
                        </button>
                        <button class="btn btn-sm btn-secondary" onclick="window.ideationManager.dismissSuggestion('${s.id}')">
                            ❌ Ignorer
                        </button>
                    ` : s.status === 'accepted' ? `
                        <span class="suggestion-status-badge accepted">✅ Tâche créée</span>
                    ` : `
                        <span class="suggestion-status-badge dismissed">❌ Ignorée</span>
                    `}
                </div>
            </div>
        `).join('');
    }

    renderChat() {
        if (!this.chatMessages) return;

        if (this.chatHistory.length === 0) {
            this.chatMessages.innerHTML = '<p class="ideation-placeholder">Posez des questions sur votre projet ou demandez des idées...</p>';
            return;
        }

        this.chatMessages.innerHTML = this.chatHistory.map(msg => `
            <div class="chat-message ${msg.role}">
                <span class="chat-role">${msg.role === 'user' ? 'Vous' : 'IA'}</span>
                <p class="chat-content">${msg.content}</p>
            </div>
        `).join('');

        this.chatMessages.scrollTop = this.chatMessages.scrollHeight;
    }
}

// Create global instance
window.ideationManager = new IdeationManager();

export { IdeationManager };
