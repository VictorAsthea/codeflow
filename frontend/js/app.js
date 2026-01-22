import { API } from './api.js';

document.addEventListener('DOMContentLoaded', async () => {
    console.log('Codeflow initialized');

    setupModals();
    setupSettings();
    setupSyncButton();

    console.log('Ready');
});

function setupModals() {
    const modals = document.querySelectorAll('.modal');

    modals.forEach(modal => {
        const closeButtons = modal.querySelectorAll('.btn-close');

        closeButtons.forEach(btn => {
            btn.addEventListener('click', () => {
                modal.classList.add('hidden');
            });
        });

        modal.addEventListener('click', (e) => {
            if (e.target === modal) {
                modal.classList.add('hidden');
            }
        });
    });
}

function setupSettings() {
    const settingsBtn = document.getElementById('settings-btn');
    const settingsModal = document.getElementById('settings-modal');
    const saveSettingsBtn = document.getElementById('btn-save-settings');

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

function setupSyncButton() {
    const syncBtn = document.getElementById('sync-btn');

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
