/**
 * Authentication Manager for Codeflow
 *
 * Handles:
 * - Checking auth status on startup
 * - Displaying auth modal when not authenticated
 * - Managing subscription (Claude CLI) and API key auth methods
 */

class AuthManager {
    constructor() {
        this.modal = document.getElementById('auth-modal');
        this.status = null;
        this.isChecking = false;
    }

    /**
     * Check authentication status and show modal if needed
     */
    async checkAuth() {
        if (this.isChecking) return;
        this.isChecking = true;

        try {
            const response = await fetch('/api/auth/status');
            this.status = await response.json();

            if (!this.status.authenticated) {
                this.showAuthModal();
            } else {
                console.log(`Authenticated via ${this.status.method}`);
            }
        } catch (error) {
            console.error('Failed to check auth status:', error);
            // Show modal on error to allow user to authenticate
            this.showAuthModal();
        } finally {
            this.isChecking = false;
        }
    }

    /**
     * Show the authentication modal
     */
    showAuthModal() {
        if (this.modal) {
            this.modal.classList.remove('hidden');
            // Focus on API key input if visible
            const apiKeyInput = document.getElementById('api-key-input');
            if (apiKeyInput) {
                setTimeout(() => apiKeyInput.focus(), 100);
            }
        }
    }

    /**
     * Hide the authentication modal
     */
    hideAuthModal() {
        if (this.modal) {
            this.modal.classList.add('hidden');
        }
    }

    /**
     * Launch CLI login and show instructions
     */
    async loginWithSubscription() {
        const btn = document.querySelector('#auth-modal .auth-option-card:first-child .btn-primary');
        const instructions = document.getElementById('subscription-instructions');
        const originalText = btn?.textContent || 'Connexion via CLI';

        try {
            if (btn) {
                btn.disabled = true;
                btn.textContent = 'Lancement...';
            }

            const response = await fetch('/api/auth/login-cli', {
                method: 'POST'
            });

            if (response.ok) {
                // Show instructions for verification
                if (instructions) {
                    instructions.classList.remove('hidden');
                }
                this.showToast('Navigateur ouvert. Completez l\'authentification.', 'success');
            } else {
                const error = await response.json();
                this.showToast(error.detail || 'Erreur lors du lancement', 'error');
            }
        } catch (error) {
            console.error('Failed to launch CLI login:', error);
            this.showToast('Erreur de connexion au serveur', 'error');
        } finally {
            if (btn) {
                btn.disabled = false;
                btn.textContent = originalText;
            }
        }
    }

    /**
     * Verify subscription after user runs `claude login`
     */
    async verifySubscription() {
        const verifyBtn = document.querySelector('#subscription-instructions button');
        const originalText = verifyBtn?.textContent || 'Verify';

        try {
            if (verifyBtn) {
                verifyBtn.disabled = true;
                verifyBtn.textContent = 'Verifying...';
            }

            const response = await fetch('/api/auth/verify-subscription', {
                method: 'POST'
            });

            const status = await response.json();
            this.status = status;

            if (status.subscription_available) {
                this.hideAuthModal();
                this.showToast('Connected via subscription', 'success');
            } else {
                this.showToast('Subscription not detected. Make sure you ran "claude login" and completed the login.', 'error');
            }
        } catch (error) {
            console.error('Failed to verify subscription:', error);
            this.showToast('Failed to verify subscription', 'error');
        } finally {
            if (verifyBtn) {
                verifyBtn.disabled = false;
                verifyBtn.textContent = originalText;
            }
        }
    }

    /**
     * Login with API key
     */
    async loginWithApiKey() {
        const input = document.getElementById('api-key-input');
        const key = input?.value?.trim();

        if (!key) {
            this.showToast('Please enter your API key', 'error');
            return;
        }

        if (!key.startsWith('sk-ant-')) {
            this.showToast('Invalid API key format. Key should start with "sk-ant-"', 'error');
            return;
        }

        const loginBtn = document.querySelector('#auth-modal .auth-option-card:last-child .btn-primary');
        const originalText = loginBtn?.textContent || 'Connect';

        try {
            if (loginBtn) {
                loginBtn.disabled = true;
                loginBtn.textContent = 'Connecting...';
            }

            const response = await fetch('/api/auth/api-key', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ key })
            });

            if (response.ok) {
                this.hideAuthModal();
                this.showToast('Connected with API key', 'success');
                // Clear the input
                if (input) input.value = '';
            } else {
                const error = await response.json();
                this.showToast(error.detail || 'Invalid API key', 'error');
            }
        } catch (error) {
            console.error('Failed to set API key:', error);
            this.showToast('Failed to connect with API key', 'error');
        } finally {
            if (loginBtn) {
                loginBtn.disabled = false;
                loginBtn.textContent = originalText;
            }
        }
    }

    /**
     * Clear stored credentials (logout)
     */
    async logout() {
        try {
            await fetch('/api/auth/api-key', { method: 'DELETE' });
            this.status = null;
            this.showToast('Logged out', 'success');
            this.showAuthModal();
        } catch (error) {
            console.error('Failed to logout:', error);
            this.showToast('Failed to logout', 'error');
        }
    }

    /**
     * Get current auth method
     */
    getAuthMethod() {
        return this.status?.method || null;
    }

    /**
     * Check if authenticated
     */
    isAuthenticated() {
        return this.status?.authenticated || false;
    }

    /**
     * Load and display auth status in settings
     */
    async loadSettingsAuthStatus() {
        const container = document.getElementById('settings-auth-content');
        if (!container) return;

        try {
            const response = await fetch('/api/auth/status');
            const status = await response.json();
            this.status = status;

            container.innerHTML = this.renderAuthStatus(status);
        } catch (error) {
            container.innerHTML = `<p class="error-message">Erreur de chargement</p>`;
        }
    }

    /**
     * Render auth status HTML
     */
    renderAuthStatus(status) {
        if (!status.authenticated) {
            return `
                <div class="auth-status-card not-connected">
                    <div class="auth-status-icon">&#128683;</div>
                    <div class="auth-status-info">
                        <h4>Non connecte</h4>
                        <p>Aucune methode d'authentification configuree</p>
                    </div>
                    <button class="btn btn-primary" onclick="document.getElementById('settings-modal').classList.add('hidden'); authManager.showAuthModal();">
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

        // Add logout button for API key
        if (status.api_key_available) {
            html += `
                <div class="auth-actions">
                    <button class="btn btn-danger btn-small" onclick="authManager.logout()">
                        Supprimer la cle API
                    </button>
                </div>
            `;
        }

        return html;
    }

    /**
     * Show toast notification
     */
    showToast(message, type = 'info') {
        // Use existing toast system if available
        if (typeof window.showToast === 'function') {
            window.showToast(message, type);
            return;
        }

        // Fallback: create simple toast
        const toast = document.createElement('div');
        toast.className = `toast toast-${type}`;
        toast.textContent = message;
        toast.style.cssText = `
            position: fixed;
            bottom: 20px;
            right: 20px;
            padding: 12px 24px;
            border-radius: 6px;
            color: white;
            font-size: 14px;
            z-index: 10001;
            animation: fadeIn 0.3s ease;
            background-color: ${type === 'success' ? '#3fb950' : type === 'error' ? '#f85149' : '#58a6ff'};
        `;

        document.body.appendChild(toast);

        setTimeout(() => {
            toast.style.animation = 'fadeOut 0.3s ease';
            setTimeout(() => toast.remove(), 300);
        }, 3000);
    }

    /**
     * Fetch and display rate limit status
     */
    async loadRateLimitStatus() {
        const indicator = document.getElementById('rate-limit-indicator');
        const text = document.getElementById('rate-limit-text');
        if (!indicator || !text) return;

        try {
            const response = await fetch('/api/auth/rate-limit');
            const data = await response.json();

            if (!data.method) {
                text.textContent = '--';
                indicator.classList.remove('warning', 'danger', 'subscription');
                return;
            }

            // Format display based on method
            if (data.method === 'subscription') {
                const tierLabel = data.tier?.includes('max_5x') ? 'Max' :
                                  data.tier?.includes('pro') ? 'Pro' : 'Sub';
                text.textContent = tierLabel;
                indicator.classList.remove('warning', 'danger');
                indicator.classList.add('subscription');
            } else if (data.method === 'api_key') {
                text.textContent = 'API';
                indicator.classList.remove('warning', 'danger', 'subscription');
            }

            // Also fetch usage data for the dropdown
            this.loadUsageData();
        } catch (error) {
            console.error('Failed to load rate limit:', error);
            text.textContent = '--';
        }
    }

    /**
     * Fetch and display usage data in dropdown
     */
    async loadUsageData() {
        try {
            const response = await fetch('/api/auth/usage');
            const data = await response.json();

            if (data.error) {
                console.warn('Usage data error:', data.error);
                return;
            }

            // Update session usage
            this.updateUsageBar('session', data.session_percentage, data.session_reset_text);

            // Update weekly usage
            this.updateUsageBar('weekly', data.weekly_percentage, data.weekly_reset_text);

            // Update sonnet usage
            this.updateUsageBar('sonnet', data.sonnet_percentage, data.sonnet_reset_text);

            // Update last updated
            const lastUpdated = document.getElementById('usage-last-updated');
            if (lastUpdated && data.last_updated) {
                const date = new Date(data.last_updated);
                lastUpdated.textContent = `Mis a jour: ${date.toLocaleTimeString()}`;
            }

            // Update main indicator with session percentage
            if (data.session_percentage !== null) {
                const indicator = document.getElementById('rate-limit-indicator');
                const text = document.getElementById('rate-limit-text');
                if (indicator && text) {
                    text.textContent = `${data.session_percentage}%`;
                    indicator.classList.remove('warning', 'danger');
                    if (data.session_percentage > 80) {
                        indicator.classList.add('danger');
                    } else if (data.session_percentage > 60) {
                        indicator.classList.add('warning');
                    }
                }
            }
        } catch (error) {
            console.error('Failed to load usage data:', error);
        }
    }

    /**
     * Update a usage bar
     */
    updateUsageBar(type, percentage, resetText) {
        const bar = document.getElementById(`usage-${type}-bar`);
        const percentEl = document.getElementById(`usage-${type}-percent`);
        const resetEl = document.getElementById(`usage-${type}-reset`);

        if (bar) {
            if (percentage !== null) {
                bar.style.width = `${percentage}%`;
                bar.classList.remove('warning', 'danger');
                if (percentage > 80) {
                    bar.classList.add('danger');
                } else if (percentage > 60) {
                    bar.classList.add('warning');
                }
            } else {
                bar.style.width = '0%';
            }
        }

        if (percentEl) {
            percentEl.textContent = percentage !== null ? `${percentage}% utilise` : '--%';
        }

        if (resetEl) {
            resetEl.textContent = resetText || '';
        }
    }

    /**
     * Setup dropdown toggle
     */
    setupUsageDropdown() {
        const wrapper = document.getElementById('rate-limit-wrapper');
        const indicator = document.getElementById('rate-limit-indicator');
        const dropdown = document.getElementById('rate-limit-dropdown');
        const refreshBtn = document.getElementById('usage-refresh-btn');

        if (!wrapper || !indicator || !dropdown) return;

        // Toggle on click
        indicator.addEventListener('click', (e) => {
            e.stopPropagation();
            wrapper.classList.toggle('open');
            dropdown.classList.toggle('hidden');
            // No auto-refresh on open - user must click refresh button
        });

        // Manual refresh button
        if (refreshBtn) {
            refreshBtn.addEventListener('click', async (e) => {
                e.stopPropagation();
                refreshBtn.disabled = true;
                refreshBtn.textContent = '⏳';
                try {
                    await this.loadUsageData();
                } finally {
                    refreshBtn.disabled = false;
                    refreshBtn.textContent = '🔄';
                }
            });
        }

        // Close on click outside
        document.addEventListener('click', (e) => {
            if (!wrapper.contains(e.target)) {
                wrapper.classList.remove('open');
                dropdown.classList.add('hidden');
            }
        });
    }

    /**
     * Initialize rate limit display (no auto-refresh)
     */
    startRateLimitRefresh() {
        // Setup dropdown with manual refresh button
        this.setupUsageDropdown();
        // Initial load only - no periodic refresh
        // User can click refresh button to update
        this.loadRateLimitStatus();
    }

    /**
     * Stop rate limit refresh (kept for compatibility)
     */
    stopRateLimitRefresh() {
        // No interval to clear anymore
    }
}

// Initialize AuthManager on DOM ready
document.addEventListener('DOMContentLoaded', () => {
    window.authManager = new AuthManager();

    // Check auth status with a small delay (like project-init)
    setTimeout(() => {
        window.authManager.checkAuth();
        window.authManager.startRateLimitRefresh();
    }, 300);
});

// Handle Enter key in API key input
document.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && e.target.id === 'api-key-input') {
        e.preventDefault();
        window.authManager?.loginWithApiKey();
    }
});
