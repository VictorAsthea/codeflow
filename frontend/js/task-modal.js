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
    renderPhasesTab();
    renderLogsTab();
    updateActionButtons();
    updatePRReviewTabVisibility();
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

    if (currentTask.status === 'in_progress') {
        startBtn.classList.add('hidden');
        stopBtn.classList.remove('hidden');
    } else {
        startBtn.classList.remove('hidden');
        stopBtn.classList.add('hidden');
    }

    if (currentTask.status === 'human_review') {
        viewDiffBtn.classList.remove('hidden');
        createPRBtn.classList.remove('hidden');
    } else {
        viewDiffBtn.classList.add('hidden');
        createPRBtn.classList.add('hidden');
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

    if (currentTask && currentTask.pr_url) {
        tabBtn.style.display = 'block';
        startPRReviewPolling();
    } else {
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

    // Re-attach checkbox listeners
    container.querySelectorAll('.pr-comment-checkbox').forEach(checkbox => {
        checkbox.addEventListener('change', handleCommentCheckboxChange);
    });
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

    if (event.target.checked) {
        selectedCommentIds.add(commentId);
    } else {
        selectedCommentIds.delete(commentId);
    }

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

window.addEventListener('DOMContentLoaded', () => {
    initTaskModal();
});
