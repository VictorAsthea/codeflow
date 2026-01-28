/**
 * Discussion Modal - Chat interface for refining features and suggestions
 */

import { API } from './api.js';

class DiscussionModal {
    constructor() {
        this.modal = null;
        this.messagesContainer = null;
        this.input = null;
        this.sendBtn = null;

        this.currentItem = null;  // { id, type, title, description }
        this.messages = [];
        this.pendingUpdate = null;
        this.isLoading = false;

        this.onDescriptionUpdated = null;  // Callback when description is updated
    }

    /**
     * Open discussion modal for an item
     * @param {Object} item - { id, type: 'feature'|'suggestion', title, description }
     * @param {Function} onUpdate - Callback when description is updated
     */
    async open(item, onUpdate = null) {
        this.currentItem = item;
        this.onDescriptionUpdated = onUpdate;
        this.pendingUpdate = null;

        this.createModal();
        await this.loadHistory();
        this.modal.classList.remove('hidden');
        this.input?.focus();
    }

    close() {
        if (this.modal) {
            this.modal.classList.add('hidden');
            this.modal.remove();
            this.modal = null;
        }
        this.currentItem = null;
        this.messages = [];
        this.pendingUpdate = null;
    }

    createModal() {
        // Remove existing if any
        document.getElementById('discussion-modal')?.remove();

        const typeLabel = this.currentItem.type === 'feature' ? 'Feature' : 'Suggestion';

        const html = `
            <div id="discussion-modal" class="modal">
                <div class="modal-content discussion-modal-content">
                    <div class="modal-header">
                        <h2>💬 Discussion: ${this.escapeHtml(this.currentItem.title)}</h2>
                        <span class="discussion-type-badge">${typeLabel}</span>
                        <button class="btn-close" onclick="window.discussionModal.close()">&times;</button>
                    </div>

                    <div class="discussion-body">
                        <div class="discussion-context">
                            <strong>Description actuelle:</strong>
                            <p id="discussion-current-desc">${this.escapeHtml(this.currentItem.description || 'Pas de description')}</p>
                        </div>

                        <div class="discussion-messages" id="discussion-messages">
                            <div class="discussion-welcome">
                                <p>💡 Discutez de cette ${typeLabel.toLowerCase()} avec l'IA pour la raffiner.</p>
                                <p class="text-secondary">Posez des questions, demandez des clarifications, ou proposez des améliorations.</p>
                            </div>
                        </div>

                        <div id="discussion-update-banner" class="discussion-update-banner hidden">
                            <span>✨ Mise à jour suggérée</span>
                            <div class="discussion-update-actions">
                                <button class="btn btn-small btn-primary" onclick="window.discussionModal.applyUpdate()">Appliquer</button>
                                <button class="btn btn-small btn-secondary" onclick="window.discussionModal.dismissUpdate()">Ignorer</button>
                            </div>
                        </div>
                    </div>

                    <div class="discussion-footer">
                        <input type="text"
                               id="discussion-input"
                               class="input discussion-input"
                               placeholder="Votre message..."
                               onkeypress="if(event.key==='Enter') window.discussionModal.send()">
                        <button id="discussion-send-btn" class="btn btn-primary" onclick="window.discussionModal.send()">
                            Envoyer
                        </button>
                        <button id="discussion-finalize-btn" class="btn btn-success" onclick="window.discussionModal.finalize()" title="Générer la description enrichie">
                            ✓ Finaliser
                        </button>
                    </div>
                </div>
            </div>
        `;

        document.body.insertAdjacentHTML('beforeend', html);

        this.modal = document.getElementById('discussion-modal');
        this.messagesContainer = document.getElementById('discussion-messages');
        this.input = document.getElementById('discussion-input');
        this.sendBtn = document.getElementById('discussion-send-btn');

        // Close on backdrop click
        this.modal.addEventListener('click', (e) => {
            if (e.target === this.modal) this.close();
        });
    }

    async loadHistory() {
        try {
            const data = await API.discussions.get(this.currentItem.id);
            this.messages = data.messages || [];
            this.renderMessages();
        } catch (error) {
            console.error('Failed to load discussion history:', error);
        }
    }

    renderMessages() {
        if (!this.messagesContainer) return;

        if (this.messages.length === 0) {
            this.messagesContainer.innerHTML = `
                <div class="discussion-welcome">
                    <p>💡 Discutez de cette ${this.currentItem.type === 'feature' ? 'feature' : 'suggestion'} avec l'IA pour la raffiner.</p>
                    <p class="text-secondary">Posez des questions, demandez des clarifications, ou proposez des améliorations.</p>
                </div>
            `;
            return;
        }

        this.messagesContainer.innerHTML = this.messages.map(msg => `
            <div class="discussion-message ${msg.role}">
                <div class="discussion-message-avatar">
                    ${msg.role === 'user' ? '👤' : '🤖'}
                </div>
                <div class="discussion-message-content">
                    ${this.formatMessage(msg.content)}
                </div>
            </div>
        `).join('');

        // Scroll to bottom
        this.messagesContainer.scrollTop = this.messagesContainer.scrollHeight;
    }

    formatMessage(content) {
        // Basic markdown-like formatting
        return this.escapeHtml(content)
            .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
            .replace(/\*(.*?)\*/g, '<em>$1</em>')
            .replace(/`(.*?)`/g, '<code>$1</code>')
            .replace(/\n/g, '<br>');
    }

    async send() {
        const message = this.input?.value?.trim();
        if (!message || this.isLoading) return;

        this.isLoading = true;
        this.sendBtn.disabled = true;
        this.sendBtn.textContent = '...';
        this.input.value = '';

        // Add user message immediately
        this.messages.push({ role: 'user', content: message });
        this.renderMessages();

        // Add loading indicator
        const loadingHtml = `
            <div class="discussion-message assistant loading" id="discussion-loading">
                <div class="discussion-message-avatar">🤖</div>
                <div class="discussion-message-content">
                    <span class="typing-indicator">...</span>
                </div>
            </div>
        `;
        this.messagesContainer.insertAdjacentHTML('beforeend', loadingHtml);
        this.messagesContainer.scrollTop = this.messagesContainer.scrollHeight;

        try {
            const result = await API.discussions.chat(
                this.currentItem.id,
                message,
                this.currentItem.type,
                this.currentItem.title,
                this.currentItem.description
            );

            // Remove loading
            document.getElementById('discussion-loading')?.remove();

            // Add assistant message
            this.messages.push({ role: 'assistant', content: result.response });
            this.renderMessages();

            // Check for description update
            if (result.description_update) {
                this.pendingUpdate = result.description_update;
                this.showUpdateBanner();
            }

        } catch (error) {
            console.error('Discussion chat failed:', error);
            document.getElementById('discussion-loading')?.remove();
            this.messages.push({ role: 'assistant', content: 'Désolé, une erreur est survenue. Réessayez.' });
            this.renderMessages();
        } finally {
            this.isLoading = false;
            this.sendBtn.disabled = false;
            this.sendBtn.textContent = 'Envoyer';
        }
    }

    showUpdateBanner() {
        const banner = document.getElementById('discussion-update-banner');
        if (banner) {
            banner.classList.remove('hidden');
        }
    }

    hideUpdateBanner() {
        const banner = document.getElementById('discussion-update-banner');
        if (banner) {
            banner.classList.add('hidden');
        }
    }

    async applyUpdate() {
        if (!this.pendingUpdate) return;

        try {
            await API.discussions.applyUpdate(
                this.currentItem.id,
                this.currentItem.type,
                this.pendingUpdate
            );

            // Update local state
            this.currentItem.description = this.pendingUpdate;
            document.getElementById('discussion-current-desc').textContent = this.pendingUpdate;

            // Notify parent
            if (this.onDescriptionUpdated) {
                this.onDescriptionUpdated(this.currentItem.id, this.pendingUpdate);
            }

            window.showToast?.('Description mise à jour', 'success');
            this.hideUpdateBanner();
            this.pendingUpdate = null;

        } catch (error) {
            console.error('Failed to apply update:', error);
            window.showToast?.('Erreur lors de la mise à jour', 'error');
        }
    }

    dismissUpdate() {
        this.pendingUpdate = null;
        this.hideUpdateBanner();
    }

    async finalize() {
        const finalizeMessage = "FINALISER: Génère la description mise à jour (max 10 lignes, technique, concis).";
        this.input.value = finalizeMessage;
        await this.send();
    }

    escapeHtml(text) {
        if (!text) return '';
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }
}

// Create global instance
window.discussionModal = new DiscussionModal();

export { DiscussionModal };
