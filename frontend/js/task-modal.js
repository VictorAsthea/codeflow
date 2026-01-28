import { API } from './api.js';

let currentTask = null;
let refreshInterval = null;
let prReviewPollingInterval = null;
let selectedCommentIds = new Set();
let prReviewData = null;
let conflictData = null;

export function initTaskModal() {
    setupTabs();
    setupActions();
    setupPRReviewActions();
    setupModalObserver();

    window.addEventListener('open-task-modal', async (e) => {
        await openModal(e.detail.taskId);
    });
}

async function openModal(taskId) {
    try {
        currentTask = await API.tasks.get(taskId);

        // Auto-sync PR info if task has branch but no PR url
        if (currentTask.branch_name && !currentTask.pr_url) {
            console.log('[Task Modal] Task has branch but no PR url - syncing...');
            try {
                const syncResult = await API.tasks.syncPR(taskId);
                if (syncResult.synced) {
                    console.log('[Task Modal] PR synced:', syncResult.pr_url);
                    // Reload task with updated PR info
                    currentTask = await API.tasks.get(taskId);
                }
            } catch (syncError) {
                console.log('[Task Modal] PR sync failed (no PR exists?):', syncError.message);
            }
        }

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
                        stopPRReviewPolling();
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
    renderSubtasksTab();
    renderPhasesTab();
    renderLogsTab();
    updateActionButtons();
    updatePRReviewTabVisibility();
    updateSubtasksTabVisibility();
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

        ${currentTask.pr_url ? `
        <div style="margin-bottom: 1.5rem;">
            <h3 style="margin-bottom: 0.5rem;">Pull Request</h3>
            <p>
                <a href="${currentTask.pr_url}" target="_blank" style="color: var(--accent-blue); text-decoration: none;">
                    🔗 ${currentTask.pr_url}
                </a>
            </p>
        </div>
        ` : ''}

        <div style="margin-bottom: 1.5rem;">
            <h3 style="margin-bottom: 0.5rem;">Timestamps</h3>
            <p style="font-size: 0.9rem; color: var(--text-secondary);">
                Created: ${new Date(currentTask.created_at).toLocaleString()}<br>
                Updated: ${new Date(currentTask.updated_at).toLocaleString()}
            </p>
        </div>

        ${currentTask.screenshots && currentTask.screenshots.length > 0 ? `
        <div style="margin-bottom: 1.5rem;">
            <h3 style="margin-bottom: 0.5rem;">Screenshots (${currentTask.screenshots.length})</h3>
            <div class="screenshots-gallery">
                ${currentTask.screenshots.map((screenshot, i) => `
                    <img src="${screenshot}" alt="Screenshot ${i+1}" class="screenshot-thumbnail" data-index="${i}">
                `).join('')}
            </div>
        </div>
        ` : ''}

        ${currentTask.cleanup_performed && currentTask.cleanup_files && currentTask.cleanup_files.length > 0 ? `
        <div style="margin-bottom: 1.5rem;">
            <h3 style="margin-bottom: 0.5rem;">Cleanup Summary</h3>
            <div style="padding: 0.75rem; background-color: var(--bg-tertiary); border-radius: 6px; border-left: 3px solid var(--accent-green);">
                <p style="margin-bottom: 0.5rem; color: var(--accent-green);">
                    ${currentTask.cleanup_files.length} test/debug file(s) cleaned before review
                </p>
                <details style="font-size: 0.85rem; color: var(--text-secondary);">
                    <summary style="cursor: pointer; margin-bottom: 0.5rem;">View cleaned files</summary>
                    <ul style="margin: 0; padding-left: 1.5rem; max-height: 150px; overflow-y: auto;">
                        ${currentTask.cleanup_files.map(f => `<li style="font-family: monospace; font-size: 0.8rem;">${escapeHtml(f)}</li>`).join('')}
                    </ul>
                </details>
            </div>
        </div>
        ` : ''}
    `;

    // Add click handlers for screenshot lightbox
    if (currentTask.screenshots && currentTask.screenshots.length > 0) {
        container.querySelectorAll('.screenshot-thumbnail').forEach(img => {
            img.addEventListener('click', () => {
                openScreenshotLightbox(currentTask.screenshots, parseInt(img.dataset.index));
            });
        });
    }
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
    const logEntriesContainer = document.getElementById('log-entries');
    if (!logEntriesContainer) return;

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

    const logsStream = allLogs.join('\n');

    if (window.logViewer) {
        window.logViewer.loadLogs(logsStream);
    } else {
        window.logViewer = new LogViewer('#log-entries');
        window.logViewer.loadLogs(logsStream);
    }
}

function renderSubtasksTab() {
    const container = document.getElementById('tab-subtasks');
    if (!container) return;

    const subtasks = currentTask.subtasks || [];
    const progress = calculateSubtaskProgress(subtasks);

    if (subtasks.length === 0) {
        container.innerHTML = `
            <div class="subtasks-tab">
                <div style="text-align: center; padding: 2rem; color: var(--text-secondary);">
                    <p>No subtasks generated yet.</p>
                    <p style="font-size: 0.85rem; margin-top: 0.5rem;">Subtasks are generated during the Planning phase.</p>
                </div>
            </div>
        `;
        return;
    }

    container.innerHTML = `
        <div class="subtasks-tab">
            <div class="subtasks-header">
                <span class="subtasks-count">
                    ${progress.completed} of ${progress.total} completed
                </span>
                <span class="subtasks-percentage">${progress.percentage}%</span>
            </div>

            <div class="subtasks-progress-bar">
                <div class="subtasks-progress-fill" style="width: ${progress.percentage}%"></div>
            </div>

            <div class="subtasks-list">
                ${subtasks.map(subtask => renderSubtaskItem(subtask)).join('')}
            </div>
        </div>
    `;

    // Add retry button handlers
    container.querySelectorAll('.btn-retry-subtask').forEach(btn => {
        btn.addEventListener('click', async (e) => {
            e.stopPropagation();
            const subtaskId = btn.dataset.subtaskId;
            try {
                await API.tasks.retrySubtask(currentTask.id, subtaskId);
                await openModal(currentTask.id);
            } catch (error) {
                console.error('Failed to retry subtask:', error);
                alert('Failed to retry subtask: ' + error.message);
            }
        });
    });
}

function renderSubtaskItem(subtask) {
    const statusIcon = getSubtaskStatusIcon(subtask.status);
    const statusClass = `subtask-${subtask.status}`;
    const isActive = currentTask.current_subtask_id === subtask.id;

    let retryButton = '';
    if (subtask.status === 'failed') {
        retryButton = `<button class="btn btn-small btn-retry-subtask" data-subtask-id="${subtask.id}">Retry</button>`;
    }

    return `
        <div class="subtask-item ${statusClass} ${isActive ? 'active' : ''}">
            <div class="subtask-icon">${statusIcon}</div>
            <div class="subtask-number">#${subtask.order}</div>
            <div class="subtask-content">
                <div class="subtask-title">${escapeHtml(subtask.title)}</div>
                ${subtask.description ? `<div class="subtask-description">${escapeHtml(subtask.description)}</div>` : ''}
                ${subtask.error ? `<div class="subtask-error" style="color: var(--accent-red); font-size: 0.8rem; margin-top: 0.25rem;">Error: ${escapeHtml(subtask.error)}</div>` : ''}
            </div>
            ${retryButton}
        </div>
    `;
}

function getSubtaskStatusIcon(status) {
    switch (status) {
        case 'completed': return '✓';
        case 'in_progress': return '●';
        case 'failed': return '✗';
        default: return '○';
    }
}

function calculateSubtaskProgress(subtasks) {
    const total = subtasks.length;
    const completed = subtasks.filter(s => s.status === 'completed').length;
    return {
        total,
        completed,
        percentage: total > 0 ? Math.round((completed / total) * 100) : 0
    };
}

function updateSubtasksTabVisibility() {
    const tabBtn = document.getElementById('tab-btn-subtasks');
    if (!tabBtn) return;

    // Show subtasks tab only if task has subtasks or is in progress
    const hasSubtasks = currentTask.subtasks && currentTask.subtasks.length > 0;
    const isInProgress = currentTask.status === 'in_progress';

    if (hasSubtasks || isInProgress) {
        tabBtn.style.display = 'block';
    } else {
        tabBtn.style.display = 'none';
    }
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
    const archiveBtn = document.getElementById('btn-archive-task');

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

    archiveBtn.addEventListener('click', async () => {
        if (!currentTask) return;

        archiveBtn.disabled = true;
        archiveBtn.textContent = 'Archiving...';

        try {
            await API.tasks.archive(currentTask.id);
            document.getElementById('task-modal').classList.add('hidden');
            window.dispatchEvent(new Event('task-updated'));
        } catch (error) {
            console.error('Failed to archive task:', error);
            alert('Failed to archive task: ' + error.message);
        } finally {
            archiveBtn.disabled = false;
            archiveBtn.textContent = 'Archive';
        }
    });

    const viewDiffBtn = document.getElementById('btn-view-diff');
    const createPRBtn = document.getElementById('btn-create-pr');

    viewDiffBtn.addEventListener('click', () => {
        if (!currentTask || !currentTask.branch_name) return;

        const repoUrl = 'https://github.com/VictorAsthea/codeflow';
        const diffUrl = `${repoUrl}/compare/develop...${currentTask.branch_name}`;
        window.open(diffUrl, '_blank');
    });

    createPRBtn.addEventListener('click', async () => {
        if (!currentTask) return;

        // If PR already exists, open it in a new tab
        if (currentTask.pr_url) {
            window.open(currentTask.pr_url, '_blank');
            return;
        }

        // Create a new PR
        createPRBtn.disabled = true;
        createPRBtn.textContent = 'Creating PR...';

        try {
            const result = await API.tasks.createPR(currentTask.id);
            alert(`PR created successfully!\n${result.pr_url}`);
            window.dispatchEvent(new Event('task-updated'));
            await openModal(currentTask.id);
        } catch (error) {
            console.error('Failed to create PR:', error);
            alert('Failed to create PR: ' + error.message);
        } finally {
            createPRBtn.disabled = false;
            createPRBtn.textContent = 'Create PR';
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
    const viewDiffBtn = document.getElementById('btn-view-diff');
    const createPRBtn = document.getElementById('btn-create-pr');
    const archiveBtn = document.getElementById('btn-archive-task');

    if (currentTask.status === 'in_progress') {
        startBtn.classList.add('hidden');
        stopBtn.classList.remove('hidden');
    } else if (currentTask.status === 'done') {
        // Hide both start and stop for completed tasks
        startBtn.classList.add('hidden');
        stopBtn.classList.add('hidden');
    } else {
        startBtn.classList.remove('hidden');
        stopBtn.classList.add('hidden');
    }

    if (currentTask.status === 'human_review') {
        viewDiffBtn.classList.remove('hidden');
        createPRBtn.classList.remove('hidden');

        // Change button text based on PR status
        createPRBtn.textContent = currentTask.pr_url ? 'View PR' : 'Create PR';
    } else {
        viewDiffBtn.classList.add('hidden');
        createPRBtn.classList.add('hidden');
    }

    // Show archive button only for completed tasks that are not already archived
    if (currentTask.status === 'done' && !currentTask.archived) {
        archiveBtn.classList.remove('hidden');
    } else {
        archiveBtn.classList.add('hidden');
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

// PR Review Tab Functions

function updatePRReviewTabVisibility() {
    const tabBtn = document.getElementById('tab-btn-pr-review');
    if (!tabBtn) return;

    console.log('[PR Review Tab] Checking visibility:', {
        hasTask: !!currentTask,
        pr_url: currentTask?.pr_url,
        pr_number: currentTask?.pr_number,
        status: currentTask?.status
    });

    if (currentTask && currentTask.pr_url) {
        console.log('[PR Review Tab] Showing tab - PR exists');
        tabBtn.style.display = 'block';
        startPRReviewPolling();
    } else {
        console.log('[PR Review Tab] Hiding tab - No PR');
        tabBtn.style.display = 'none';
        stopPRReviewPolling();
    }
}

function startPRReviewPolling() {
    stopPRReviewPolling();

    if (currentTask && currentTask.pr_number) {
        loadPRReviewData();

        prReviewPollingInterval = setInterval(() => {
            loadPRReviewData();
        }, 30000);
    }
}

function stopPRReviewPolling() {
    if (prReviewPollingInterval) {
        clearInterval(prReviewPollingInterval);
        prReviewPollingInterval = null;
    }
}

async function loadPRReviewData() {
    if (!currentTask || !currentTask.pr_number) return;

    try {
        const [reviews, conflicts] = await Promise.all([
            API.tasks.getPRReviews(currentTask.id),
            API.tasks.checkConflicts(currentTask.id)
        ]);

        prReviewData = reviews;
        conflictData = conflicts;
        renderPRReviewTab();
    } catch (error) {
        console.error('Failed to load PR review data:', error);
    }
}

function renderPRReviewTab() {
    const container = document.getElementById('pr-comments-container');
    const mergeableBadge = document.getElementById('pr-mergeable-badge');
    const conflictsBadge = document.getElementById('pr-conflicts-badge');
    const resolveBtn = document.getElementById('btn-resolve-conflicts');

    if (!container || !prReviewData) return;

    // Update status badges
    const prStatus = prReviewData.pr_status || {};
    if (prStatus.mergeable === 'MERGEABLE') {
        mergeableBadge.textContent = 'Mergeable';
        mergeableBadge.className = 'badge badge-mergeable';
    } else if (prStatus.mergeable === 'CONFLICTING') {
        mergeableBadge.textContent = 'Conflicting';
        mergeableBadge.className = 'badge badge-conflicting';
    } else {
        mergeableBadge.textContent = prStatus.mergeable || 'Unknown';
        mergeableBadge.className = 'badge';
    }

    // Update conflicts badge and resolve button
    if (conflictData && conflictData.has_conflicts) {
        conflictsBadge.textContent = `${conflictData.conflicting_files?.length || 0} conflicts`;
        conflictsBadge.classList.remove('hidden');
        resolveBtn.classList.remove('hidden');
    } else {
        conflictsBadge.classList.add('hidden');
        resolveBtn.classList.add('hidden');
    }

    // Render comments grouped by file
    const groupedByFile = prReviewData.grouped_by_file || {};
    const files = Object.keys(groupedByFile);

    if (files.length === 0) {
        container.innerHTML = '<p class="no-comments">No review comments yet.</p>';
        return;
    }

    let html = '';
    for (const filePath of files) {
        const comments = groupedByFile[filePath];
        html += `
            <div class="pr-file-group">
                <div class="pr-file-header">
                    <span class="pr-file-path">${escapeHtml(filePath)}</span>
                    <span class="pr-file-count">${comments.length} comment(s)</span>
                </div>
                <div class="pr-file-comments">
                    ${comments.map(comment => renderComment(comment)).join('')}
                </div>
            </div>
        `;
    }

    container.innerHTML = html;

    // Use event delegation for checkbox clicks - more reliable than individual listeners
    // Remove old listener first to avoid duplicates
    container.removeEventListener('change', handleContainerChange);
    container.addEventListener('change', handleContainerChange);
}

function handleContainerChange(event) {
    console.log('[PR Review] Container change event:', event.target.tagName, event.target.className);
    if (event.target.classList.contains('pr-comment-checkbox')) {
        handleCommentCheckboxChange(event);
    }
}

function renderComment(comment) {
    const isSelected = selectedCommentIds.has(comment.id);
    const isBot = ['coderabbitai[bot]', 'gemini-code-review[bot]', 'github-actions[bot]'].includes(comment.author);

    return `
        <div class="pr-comment ${isBot ? 'pr-comment-bot' : ''}">
            <div class="pr-comment-header">
                <label class="pr-comment-checkbox-label">
                    <input type="checkbox" class="pr-comment-checkbox" data-comment-id="${comment.id}" ${isSelected ? 'checked' : ''}>
                    <span class="pr-comment-author">${escapeHtml(comment.author)}</span>
                </label>
                ${comment.line ? `<span class="pr-comment-line">Line ${comment.line}</span>` : ''}
            </div>
            <div class="pr-comment-body">${escapeHtml(comment.body)}</div>
            ${comment.diff_hunk ? `
                <details class="pr-comment-diff">
                    <summary>View diff context</summary>
                    <pre><code>${escapeHtml(comment.diff_hunk)}</code></pre>
                </details>
            ` : ''}
        </div>
    `;
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

function handleCommentCheckboxChange(event) {
    const commentId = parseInt(event.target.dataset.commentId, 10);
    console.log('[PR Review] Checkbox changed:', commentId, 'checked:', event.target.checked);

    if (event.target.checked) {
        selectedCommentIds.add(commentId);
    } else {
        selectedCommentIds.delete(commentId);
    }

    console.log('[PR Review] Selected comments:', Array.from(selectedCommentIds));
    updateFixSelectedButton();
}

function updateFixSelectedButton() {
    const btn = document.getElementById('btn-fix-selected');
    if (!btn) return;

    const count = selectedCommentIds.size;
    btn.textContent = `Fix Selected (${count})`;
    btn.disabled = count === 0;
}

function setupPRReviewActions() {
    const refreshBtn = document.getElementById('btn-refresh-pr');
    const fixBtn = document.getElementById('btn-fix-selected');
    const resolveBtn = document.getElementById('btn-resolve-conflicts');

    if (refreshBtn) {
        refreshBtn.addEventListener('click', async () => {
            refreshBtn.disabled = true;
            refreshBtn.textContent = 'Refreshing...';
            try {
                await loadPRReviewData();
            } finally {
                refreshBtn.disabled = false;
                refreshBtn.textContent = 'Refresh';
            }
        });
    }

    if (fixBtn) {
        fixBtn.addEventListener('click', async () => {
            if (selectedCommentIds.size === 0) return;

            fixBtn.disabled = true;
            fixBtn.textContent = 'Fixing...';

            try {
                const result = await API.tasks.fixComments(currentTask.id, Array.from(selectedCommentIds));
                if (result.success) {
                    alert(`Fixed ${result.fixed_count} comment(s). Commit: ${result.commit_sha?.slice(0, 8) || 'N/A'}`);
                    selectedCommentIds.clear();
                    updateFixSelectedButton();
                    await loadPRReviewData();
                } else {
                    alert('Failed to fix comments: ' + (result.error || 'Unknown error'));
                }
            } catch (error) {
                console.error('Failed to fix comments:', error);
                alert('Failed to fix comments: ' + error.message);
            } finally {
                fixBtn.disabled = false;
                updateFixSelectedButton();
            }
        });
    }

    if (resolveBtn) {
        resolveBtn.addEventListener('click', async () => {
            if (!confirm('This will attempt to merge develop and resolve conflicts using Claude. Continue?')) {
                return;
            }

            resolveBtn.disabled = true;
            resolveBtn.textContent = 'Resolving...';

            try {
                const result = await API.tasks.resolveConflicts(currentTask.id);
                if (result.success) {
                    alert(`Resolved ${result.conflict_count} conflict(s) in ${result.resolved_files?.length || 0} file(s).`);
                    await loadPRReviewData();
                } else {
                    alert('Failed to resolve conflicts: ' + (result.error || 'Unknown error'));
                }
            } catch (error) {
                console.error('Failed to resolve conflicts:', error);
                alert('Failed to resolve conflicts: ' + error.message);
            } finally {
                resolveBtn.disabled = false;
                resolveBtn.textContent = 'Resolve Conflicts';
            }
        });
    }
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

// Screenshot Lightbox Functions
function openScreenshotLightbox(screenshots, startIndex = 0) {
    // Create lightbox overlay
    const overlay = document.createElement('div');
    overlay.className = 'screenshot-lightbox-overlay';
    overlay.innerHTML = `
        <div class="screenshot-lightbox">
            <button class="lightbox-close">&times;</button>
            <button class="lightbox-nav lightbox-prev">&lt;</button>
            <img src="${screenshots[startIndex]}" class="lightbox-image" alt="Screenshot">
            <button class="lightbox-nav lightbox-next">&gt;</button>
            <div class="lightbox-counter">${startIndex + 1} / ${screenshots.length}</div>
        </div>
    `;

    let currentIndex = startIndex;

    const updateImage = () => {
        overlay.querySelector('.lightbox-image').src = screenshots[currentIndex];
        overlay.querySelector('.lightbox-counter').textContent = `${currentIndex + 1} / ${screenshots.length}`;
    };

    // Close on overlay click
    overlay.addEventListener('click', (e) => {
        if (e.target === overlay || e.target.classList.contains('lightbox-close')) {
            overlay.remove();
        }
    });

    // Navigation
    overlay.querySelector('.lightbox-prev').addEventListener('click', (e) => {
        e.stopPropagation();
        currentIndex = (currentIndex - 1 + screenshots.length) % screenshots.length;
        updateImage();
    });

    overlay.querySelector('.lightbox-next').addEventListener('click', (e) => {
        e.stopPropagation();
        currentIndex = (currentIndex + 1) % screenshots.length;
        updateImage();
    });

    // Keyboard navigation
    const handleKeydown = (e) => {
        if (e.key === 'Escape') {
            overlay.remove();
            document.removeEventListener('keydown', handleKeydown);
        } else if (e.key === 'ArrowLeft') {
            currentIndex = (currentIndex - 1 + screenshots.length) % screenshots.length;
            updateImage();
        } else if (e.key === 'ArrowRight') {
            currentIndex = (currentIndex + 1) % screenshots.length;
            updateImage();
        }
    };
    document.addEventListener('keydown', handleKeydown);

    document.body.appendChild(overlay);
}

window.addEventListener('DOMContentLoaded', () => {
    initTaskModal();
});
