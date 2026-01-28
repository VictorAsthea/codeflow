import { API } from './api.js';
import { sidebar } from './sidebar.js';
import { keyboard } from './keyboard.js';

// Sync status check interval (5 minutes)
const SYNC_CHECK_INTERVAL = 5 * 60 * 1000;
let syncCheckTimer = null;

document.addEventListener('DOMContentLoaded', async () => {
    console.log('Codeflow initialized');

    setupModals();
    setupSettings();
    setupSyncButton();
    setupSyncStatusIndicator();

    // Check sync status on load and periodically
    checkSyncStatus();
    syncCheckTimer = setInterval(checkSyncStatus, SYNC_CHECK_INTERVAL);

    // Listen for WebSocket sync events
    setupSyncWebSocketListeners();

    console.log('Ready');
});

function setupModals() {
    const modals = document.querySelectorAll('.modal');

    modals.forEach(modal => {
        const closeButtons = modal.querySelectorAll('.btn-close');

        closeButtons.forEach(btn => {
            btn.addEventListener('click', () => {
                modal.classList.add('hidden');
                keyboard.enable();
            });
        });

        // Prevent clicks inside modal-content from bubbling to the overlay
        const modalContent = modal.querySelector('.modal-content');
        if (modalContent) {
            modalContent.addEventListener('click', (e) => {
                e.stopPropagation();
            });
        }

        modal.addEventListener('click', (e) => {
            if (e.target === modal) {
                modal.classList.add('hidden');
                keyboard.enable();
            }
        });

        const observer = new MutationObserver((mutations) => {
            mutations.forEach((mutation) => {
                if (mutation.attributeName === 'class') {
                    if (modal.classList.contains('hidden')) {
                        keyboard.enable();
                    } else {
                        keyboard.disable();
                    }
                }
            });
        });

        observer.observe(modal, { attributes: true });
    });
}

function setupSettings() {
    const settingsBtn = document.getElementById('settings-btn');
    const settingsModal = document.getElementById('settings-modal');
    const saveSettingsBtn = document.getElementById('btn-save-settings');

    if (!settingsBtn || !settingsModal) {
        console.warn('Settings elements not found, skipping setup');
        return;
    }

    settingsBtn.addEventListener('click', async () => {
        try {
            const config = await API.settings.get();

            document.getElementById('default-model').value = config.default_model;
            document.getElementById('default-intensity').value = config.default_intensity;
            document.getElementById('project-path').value = config.project_path;
            document.getElementById('auto-review').checked = config.auto_review;

            settingsModal.classList.remove('hidden');
        } catch (error) {
            console.error('Failed to load settings:', error);
            alert('Failed to load settings: ' + error.message);
        }
    });

    if (saveSettingsBtn) {
        saveSettingsBtn.addEventListener('click', async () => {
            try {
                const config = {
                    default_model: document.getElementById('default-model').value,
                    default_intensity: document.getElementById('default-intensity').value,
                    project_path: document.getElementById('project-path').value,
                    auto_review: document.getElementById('auto-review').checked,
                };

                await API.settings.update(config);
                settingsModal.classList.add('hidden');
                alert('Settings saved successfully');
            } catch (error) {
                console.error('Failed to save settings:', error);
                alert('Failed to save settings: ' + error.message);
            }
        });
    }
}

function setupSyncButton() {
    const syncBtn = document.getElementById('sync-btn');

    if (!syncBtn) {
        console.warn('Sync button not found, skipping setup');
        return;
    }

    syncBtn.addEventListener('click', async () => {
        if (!confirm('Sync main with develop? This will merge all changes from develop into main.')) {
            return;
        }

        syncBtn.disabled = true;
        syncBtn.textContent = '🔄 Syncing...';

        try {
            const result = await API.git.syncMain();
            alert('Main synced successfully with develop!');
            console.log('Sync result:', result);
        } catch (error) {
            console.error('Failed to sync main:', error);
            alert('Failed to sync main: ' + error.message);
        } finally {
            syncBtn.disabled = false;
            syncBtn.textContent = '🔄 Sync Main';
        }
    });
}

function setupSyncStatusIndicator() {
    const syncDevelopBtn = document.getElementById('sync-develop-btn');

    if (syncDevelopBtn) {
        syncDevelopBtn.addEventListener('click', async () => {
            await performSync();
        });
    }
}

async function checkSyncStatus() {
    const indicator = document.getElementById('sync-status-indicator');
    const statusText = document.getElementById('sync-status-text');

    if (!indicator || !statusText) return;

    try {
        const status = await API.git.syncStatus();

        if (status.is_behind && status.behind_count > 0) {
            indicator.classList.remove('hidden');
            indicator.classList.add('behind');
            statusText.textContent = `${status.behind_count} commit${status.behind_count > 1 ? 's' : ''} behind`;
        } else {
            indicator.classList.add('hidden');
            indicator.classList.remove('behind');
        }
    } catch (error) {
        console.error('Failed to check sync status:', error);
        // Don't show indicator on error
        indicator.classList.add('hidden');
    }
}

async function performSync() {
    const indicator = document.getElementById('sync-status-indicator');
    const statusText = document.getElementById('sync-status-text');
    const syncBtn = document.getElementById('sync-develop-btn');

    if (!indicator || !statusText || !syncBtn) return;

    syncBtn.disabled = true;
    statusText.textContent = 'Syncing...';
    indicator.classList.add('syncing');

    try {
        const result = await API.git.sync();
        console.log('Sync completed:', result);

        // Update indicator after sync
        indicator.classList.remove('syncing', 'behind');
        indicator.classList.add('synced');
        statusText.textContent = 'Synced!';

        // Hide after a moment
        setTimeout(() => {
            indicator.classList.add('hidden');
            indicator.classList.remove('synced');
        }, 3000);

    } catch (error) {
        console.error('Failed to sync:', error);
        indicator.classList.remove('syncing');
        indicator.classList.add('error');
        statusText.textContent = 'Sync failed';

        setTimeout(() => {
            indicator.classList.remove('error');
            checkSyncStatus();
        }, 3000);
    } finally {
        syncBtn.disabled = false;
    }
}

function setupSyncWebSocketListeners() {
    // Listen for custom sync events dispatched by kanban-sync.js
    document.addEventListener('git:syncing', (e) => {
        const indicator = document.getElementById('sync-status-indicator');
        const statusText = document.getElementById('sync-status-text');

        if (indicator && statusText) {
            indicator.classList.remove('hidden');
            indicator.classList.add('syncing');
            statusText.textContent = e.detail?.message || 'Syncing...';
        }
    });

    document.addEventListener('git:synced', (e) => {
        const indicator = document.getElementById('sync-status-indicator');
        const statusText = document.getElementById('sync-status-text');

        if (indicator && statusText) {
            indicator.classList.remove('syncing', 'behind');
            indicator.classList.add('synced');
            const commits = e.detail?.commits_pulled || 0;
            statusText.textContent = commits > 0 ? `Pulled ${commits} commit(s)` : 'Synced!';

            // Hide after a moment
            setTimeout(() => {
                indicator.classList.add('hidden');
                indicator.classList.remove('synced');
            }, 5000);
        }

        console.log('Git synced:', e.detail);
    });

    document.addEventListener('git:sync_error', (e) => {
        const indicator = document.getElementById('sync-status-indicator');
        const statusText = document.getElementById('sync-status-text');

        if (indicator && statusText) {
            indicator.classList.remove('syncing');
            indicator.classList.add('error');
            statusText.textContent = 'Sync failed';

            setTimeout(() => {
                indicator.classList.remove('error');
                checkSyncStatus();
            }, 5000);
        }

        console.error('Git sync error:', e.detail);
    });
}
