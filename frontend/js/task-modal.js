import { API } from './api.js';

let currentTask = null;
let refreshInterval = null;

export function initTaskModal() {
    setupTabs();
    setupActions();
    setupModalObserver();

    window.addEventListener('open-task-modal', async (e) => {
        await openModal(e.detail.taskId);
    });
}

async function openModal(taskId) {
    try {
        currentTask = await API.tasks.get(taskId);
        renderModal();
        document.getElementById('task-modal').classList.remove('hidden');
        startAutoRefresh();
    } catch (error) {
        console.error('Failed to load task:', error);
        alert('Failed to load task: ' + error.message);
    }
}

function startAutoRefresh() {
    stopAutoRefresh();

    if (currentTask && currentTask.status === 'in_progress') {
        refreshInterval = setInterval(async () => {
            try {
                const updated = await API.tasks.get(currentTask.id);
                currentTask = updated;
                renderModal();

                if (updated.status !== 'in_progress') {
                    stopAutoRefresh();
                    window.dispatchEvent(new Event('task-updated'));
                }
            } catch (error) {
                console.error('Failed to refresh task:', error);
            }
        }, 3000);
    }
}

function stopAutoRefresh() {
    if (refreshInterval) {
        clearInterval(refreshInterval);
        refreshInterval = null;
    }
}

function setupModalObserver() {
    const taskModal = document.getElementById('task-modal');
    if (taskModal) {
        const observer = new MutationObserver((mutations) => {
            mutations.forEach((mutation) => {
                if (mutation.attributeName === 'class') {
                    const isHidden = taskModal.classList.contains('hidden');
                    if (isHidden) {
                        stopAutoRefresh();
                    }
                }
            });
        });

        observer.observe(taskModal, { attributes: true });
    }
}

function renderModal() {
    if (!currentTask) return;

    document.getElementById('modal-title').textContent = `Task: ${currentTask.id}`;

    renderOverviewTab();
    renderPhasesTab();
    renderLogsTab();
    updateActionButtons();
}

function renderOverviewTab() {
    const container = document.getElementById('tab-overview');

    const statusBadge = getStatusBadge(currentTask.status);

    container.innerHTML = `
        <div style="margin-bottom: 1.5rem;">
            <h3 style="margin-bottom: 0.5rem;">Title</h3>
            <p>${currentTask.title}</p>
        </div>

        <div style="margin-bottom: 1.5rem;">
            <h3 style="margin-bottom: 0.5rem;">Description</h3>
            <p>${currentTask.description}</p>
        </div>

        <div style="margin-bottom: 1.5rem;">
            <h3 style="margin-bottom: 0.5rem;">Status</h3>
            <p>${statusBadge}</p>
        </div>

        ${currentTask.branch_name ? `
        <div style="margin-bottom: 1.5rem;">
            <h3 style="margin-bottom: 0.5rem;">Branch</h3>
            <p style="font-family: monospace;">${currentTask.branch_name}</p>
        </div>
        ` : ''}

        ${currentTask.worktree_path ? `
        <div style="margin-bottom: 1.5rem;">
            <h3 style="margin-bottom: 0.5rem;">Worktree Path</h3>
            <p style="font-family: monospace; font-size: 0.85rem;">${currentTask.worktree_path}</p>
        </div>
        ` : ''}

        <div style="margin-bottom: 1.5rem;">
            <h3 style="margin-bottom: 0.5rem;">Timestamps</h3>
            <p style="font-size: 0.9rem; color: var(--text-secondary);">
                Created: ${new Date(currentTask.created_at).toLocaleString()}<br>
                Updated: ${new Date(currentTask.updated_at).toLocaleString()}
            </p>
        </div>
    `;
}

function renderPhasesTab() {
    const container = document.getElementById('tab-phases');
    const phases = ['planning', 'coding', 'validation'];

    const phasesHtml = phases.map(phaseName => {
        const phase = currentTask.phases[phaseName];
        if (!phase) return '';

        const statusEmoji = getPhaseStatusEmoji(phase.status);
        const duration = getDuration(phase);

        return `
            <div style="padding: 1rem; background-color: var(--bg-tertiary); border-radius: 6px; margin-bottom: 1rem;">
                <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 0.5rem;">
                    <h3 style="text-transform: capitalize;">${statusEmoji} ${phaseName}</h3>
                    <span style="font-size: 0.9rem; color: var(--text-secondary);">${phase.status}</span>
                </div>

                ${duration ? `<p style="font-size: 0.85rem; color: var(--text-secondary); margin-bottom: 0.75rem;">Duration: ${duration}</p>` : ''}

                <div style="display: flex; gap: 0.5rem; align-items: center; margin-bottom: 0.75rem;">
                    <label style="font-size: 0.85rem; width: 80px;">Model:</label>
                    <select class="phase-model" data-phase="${phaseName}" style="flex: 1; padding: 0.25rem; background-color: var(--bg-secondary); border: 1px solid var(--border); color: var(--text-primary); border-radius: 4px;">
                        <option value="claude-sonnet-4-20250514" ${phase.config.model === 'claude-sonnet-4-20250514' ? 'selected' : ''}>Sonnet 4</option>
                        <option value="claude-opus-4-20250514" ${phase.config.model === 'claude-opus-4-20250514' ? 'selected' : ''}>Opus 4</option>
                    </select>
                </div>

                <div style="display: flex; gap: 0.5rem; align-items: center; margin-bottom: 0.75rem;">
                    <label style="font-size: 0.85rem; width: 80px;">Intensity:</label>
                    <select class="phase-intensity" data-phase="${phaseName}" style="flex: 1; padding: 0.25rem; background-color: var(--bg-secondary); border: 1px solid var(--border); color: var(--text-primary); border-radius: 4px;">
                        <option value="low" ${phase.config.intensity === 'low' ? 'selected' : ''}>Low</option>
                        <option value="medium" ${phase.config.intensity === 'medium' ? 'selected' : ''}>Medium</option>
                        <option value="high" ${phase.config.intensity === 'high' ? 'selected' : ''}>High</option>
                    </select>
                </div>

                <div style="display: flex; gap: 0.5rem; align-items: center;">
                    <label style="font-size: 0.85rem; width: 80px;">Max Turns:</label>
                    <input type="number" class="phase-max-turns" data-phase="${phaseName}" value="${phase.config.max_turns}" min="1" max="50" style="flex: 1; padding: 0.25rem; background-color: var(--bg-secondary); border: 1px solid var(--border); color: var(--text-primary); border-radius: 4px;">
                </div>

                ${phase.status === 'failed' ? `
                    <button class="btn btn-secondary" onclick="window.retryPhase('${phaseName}')" style="margin-top: 0.75rem; width: 100%;">Retry Phase</button>
                ` : ''}
            </div>
        `;
    }).join('');

    container.innerHTML = phasesHtml;

    setupPhaseConfigListeners();
}

function renderLogsTab() {
    const container = document.getElementById('tab-logs');
    const phases = ['planning', 'coding', 'validation'];

    let allLogs = [];
    phases.forEach(phaseName => {
        const phase = currentTask.phases[phaseName];
        if (phase && phase.logs && phase.logs.length > 0) {
            allLogs.push(`=== ${phaseName.toUpperCase()} ===`);
            allLogs.push(...phase.logs);
            allLogs.push('');
        }
    });

    const logsText = allLogs.length > 0 ? allLogs.join('\n') : 'No logs yet';

    container.innerHTML = `
        <div class="logs-container" id="logs-display">${logsText}</div>
    `;
}

function setupTabs() {
    const tabs = document.querySelectorAll('.tab');
    const panels = document.querySelectorAll('.tab-panel');

    tabs.forEach(tab => {
        tab.addEventListener('click', () => {
            const targetTab = tab.dataset.tab;

            tabs.forEach(t => t.classList.remove('active'));
            panels.forEach(p => p.classList.add('hidden'));

            tab.classList.add('active');
            document.getElementById(`tab-${targetTab}`).classList.remove('hidden');
        });
    });
}

function setupActions() {
    const startBtn = document.getElementById('btn-start-task');
    const stopBtn = document.getElementById('btn-stop-task');
    const deleteBtn = document.getElementById('btn-delete-task');

    startBtn.addEventListener('click', async () => {
        try {
            await API.tasks.start(currentTask.id);
            window.dispatchEvent(new Event('task-updated'));
            await openModal(currentTask.id);
        } catch (error) {
            console.error('Failed to start task:', error);
            alert('Failed to start task: ' + error.message);
        }
    });

    stopBtn.addEventListener('click', async () => {
        try {
            await API.tasks.stop(currentTask.id);
            window.dispatchEvent(new Event('task-updated'));
            await openModal(currentTask.id);
        } catch (error) {
            console.error('Failed to stop task:', error);
            alert('Failed to stop task: ' + error.message);
        }
    });

    deleteBtn.addEventListener('click', async () => {
        if (!confirm(`Are you sure you want to delete task "${currentTask.title}"?`)) {
            return;
        }

        try {
            await API.tasks.delete(currentTask.id);
            document.getElementById('task-modal').classList.add('hidden');
            window.dispatchEvent(new Event('task-updated'));
        } catch (error) {
            console.error('Failed to delete task:', error);
            alert('Failed to delete task: ' + error.message);
        }
    });
}

function setupPhaseConfigListeners() {
    const modelSelects = document.querySelectorAll('.phase-model');
    const intensitySelects = document.querySelectorAll('.phase-intensity');
    const maxTurnsInputs = document.querySelectorAll('.phase-max-turns');

    const updatePhaseConfig = async (phaseName, config) => {
        try {
            await API.tasks.updatePhase(currentTask.id, phaseName, config);
            await openModal(currentTask.id);
        } catch (error) {
            console.error('Failed to update phase config:', error);
            alert('Failed to update phase config: ' + error.message);
        }
    };

    modelSelects.forEach(select => {
        select.addEventListener('change', (e) => {
            const phaseName = e.target.dataset.phase;
            updatePhaseConfig(phaseName, { model: e.target.value });
        });
    });

    intensitySelects.forEach(select => {
        select.addEventListener('change', (e) => {
            const phaseName = e.target.dataset.phase;
            updatePhaseConfig(phaseName, { intensity: e.target.value });
        });
    });

    maxTurnsInputs.forEach(input => {
        input.addEventListener('change', (e) => {
            const phaseName = e.target.dataset.phase;
            const value = parseInt(e.target.value, 10);
            if (value >= 1 && value <= 50) {
                updatePhaseConfig(phaseName, { max_turns: value });
            }
        });
    });
}

function updateActionButtons() {
    const startBtn = document.getElementById('btn-start-task');
    const stopBtn = document.getElementById('btn-stop-task');

    if (currentTask.status === 'in_progress') {
        startBtn.classList.add('hidden');
        stopBtn.classList.remove('hidden');
    } else {
        startBtn.classList.remove('hidden');
        stopBtn.classList.add('hidden');
    }
}

function getStatusBadge(status) {
    const badges = {
        backlog: '<span style="padding: 0.25rem 0.5rem; background-color: var(--bg-tertiary); border-radius: 4px;">Backlog</span>',
        in_progress: '<span style="padding: 0.25rem 0.5rem; background-color: var(--accent-yellow); color: black; border-radius: 4px;">In Progress</span>',
        ai_review: '<span style="padding: 0.25rem 0.5rem; background-color: var(--accent-blue); color: white; border-radius: 4px;">AI Review</span>',
        human_review: '<span style="padding: 0.25rem 0.5rem; background-color: var(--accent-green); color: white; border-radius: 4px;">Human Review</span>',
        done: '<span style="padding: 0.25rem 0.5rem; background-color: var(--accent-green); color: white; border-radius: 4px;">Done</span>',
    };

    return badges[status] || status;
}

function getPhaseStatusEmoji(status) {
    const emojis = {
        pending: '⏳',
        running: '🔄',
        done: '✅',
        failed: '❌',
    };

    return emojis[status] || '⏳';
}

function getDuration(phase) {
    if (!phase.started_at) return null;

    const start = new Date(phase.started_at);
    const end = phase.completed_at ? new Date(phase.completed_at) : new Date();
    const seconds = Math.floor((end - start) / 1000);

    if (seconds < 60) return `${seconds}s`;
    if (seconds < 3600) return `${Math.floor(seconds / 60)}m ${seconds % 60}s`;
    return `${Math.floor(seconds / 3600)}h ${Math.floor((seconds % 3600) / 60)}m`;
}

window.retryPhase = async function(phaseName) {
    try {
        await API.tasks.retryPhase(currentTask.id, phaseName);
        await openModal(currentTask.id);
    } catch (error) {
        console.error('Failed to retry phase:', error);
        alert('Failed to retry phase: ' + error.message);
    }
};

window.addEventListener('DOMContentLoaded', () => {
    initTaskModal();
});
