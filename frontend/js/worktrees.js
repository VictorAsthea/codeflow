import { API } from './api.js';

let worktreesData = [];

export function initWorktrees() {
    setupRefreshButton();
    setupViewChangeListener();
}

function setupRefreshButton() {
    const refreshBtn = document.getElementById('refresh-worktrees');
    if (refreshBtn) {
        refreshBtn.addEventListener('click', () => {
            loadWorktrees();
        });
    }
}

function setupViewChangeListener() {
    // Listen for view changes from sidebar navigation
    window.addEventListener('view-changed', (e) => {
        if (e.detail.view === 'worktrees') {
            loadWorktrees();
        }
    });
}

export async function loadWorktrees() {
    const container = document.getElementById('worktrees-cards');
    if (!container) return;

    container.innerHTML = '<p class="loading-text">Loading worktrees...</p>';

    try {
        const response = await API.worktrees.list();
        worktreesData = response.worktrees || [];
        renderWorktrees();
    } catch (error) {
        console.error('Failed to load worktrees:', error);
        container.innerHTML = `<p class="error-text">Failed to load worktrees: ${error.message}</p>`;
    }
}

function renderWorktrees() {
    const container = document.getElementById('worktrees-cards');
    if (!container) return;

    // Filter out main worktree
    const taskWorktrees = worktreesData.filter(wt => !wt.is_main && wt.task_id);

    if (taskWorktrees.length === 0) {
        container.innerHTML = `
            <div class="empty-state">
                <p>No task worktrees found.</p>
                <p class="hint">Worktrees are created automatically when you start a task.</p>
            </div>
        `;
        return;
    }

    container.innerHTML = taskWorktrees.map(wt => renderWorktreeCard(wt)).join('');

    // Attach event listeners
    container.querySelectorAll('.btn-merge').forEach(btn => {
        btn.addEventListener('click', () => handleMerge(btn.dataset.taskId));
    });

    container.querySelectorAll('.btn-copy-path').forEach(btn => {
        btn.addEventListener('click', () => handleCopyPath(btn.dataset.path));
    });

    container.querySelectorAll('.btn-delete-worktree').forEach(btn => {
        btn.addEventListener('click', () => handleDelete(btn.dataset.taskId));
    });

    container.querySelectorAll('.worktree-task-link').forEach(link => {
        link.addEventListener('click', (e) => {
            e.preventDefault();
            openTaskModal(link.dataset.taskId);
        });
    });
}

function renderWorktreeCard(wt) {
    const stats = formatStats(wt);

    return `
        <div class="worktree-card">
            <div class="worktree-main">
                <div class="worktree-branch">
                    <span class="branch-icon">🌿</span>
                    <span class="branch-name">${escapeHtml(wt.branch)}</span>
                </div>
                <div class="worktree-stats">
                    ${stats}
                </div>
                <div class="worktree-ref">
                    <span class="ref-base">${wt.base_branch}</span>
                    <span class="ref-arrow">→</span>
                    <span class="ref-branch">${escapeHtml(wt.branch)}</span>
                </div>
            </div>
            <div class="worktree-aside">
                <a href="#" class="worktree-task-link" data-task-id="${wt.task_id}">
                    ${wt.task_id}
                </a>
                <div class="worktree-actions">
                    <button class="btn btn-merge btn-small" data-task-id="${wt.task_id}" title="Merge to ${wt.base_branch}">
                        Merge
                    </button>
                    <button class="btn btn-copy-path btn-small btn-secondary" data-path="${escapeHtml(wt.path)}" title="Copy path">
                        Copy Path
                    </button>
                    <button class="btn btn-delete-worktree btn-small btn-danger-outline" data-task-id="${wt.task_id}" title="Delete worktree">
                        Delete
                    </button>
                </div>
            </div>
        </div>
    `;
}

function formatStats(wt) {
    const parts = [];

    if (wt.files_changed > 0) {
        parts.push(`<span class="stat-files">${wt.files_changed} file${wt.files_changed > 1 ? 's' : ''}</span>`);
    }

    if (wt.commits_ahead > 0) {
        parts.push(`<span class="stat-commits">${wt.commits_ahead} commit${wt.commits_ahead > 1 ? 's' : ''} ahead</span>`);
    }

    if (wt.lines_added > 0) {
        parts.push(`<span class="stat-added">+${wt.lines_added}</span>`);
    }

    if (wt.lines_removed > 0) {
        parts.push(`<span class="stat-removed">-${wt.lines_removed}</span>`);
    }

    if (parts.length === 0) {
        return '<span class="stat-empty">No changes</span>';
    }

    return parts.join('<span class="stat-separator">·</span>');
}

async function handleMerge(taskId) {
    const wt = worktreesData.find(w => w.task_id === taskId);
    if (!wt) return;

    if (!confirm(`Merge branch "${wt.branch}" into ${wt.base_branch}?`)) {
        return;
    }

    try {
        const result = await API.worktrees.merge(taskId, wt.base_branch);
        alert(result.message || 'Merge successful!');
        loadWorktrees();
    } catch (error) {
        console.error('Merge failed:', error);
        alert(`Merge failed: ${error.message}`);
    }
}

function handleCopyPath(path) {
    navigator.clipboard.writeText(path).then(() => {
        // Show brief feedback
        const btn = document.querySelector(`.btn-copy-path[data-path="${path}"]`);
        if (btn) {
            const originalText = btn.textContent;
            btn.textContent = 'Copied!';
            setTimeout(() => {
                btn.textContent = originalText;
            }, 1500);
        }
    }).catch(err => {
        console.error('Failed to copy path:', err);
        alert('Failed to copy path to clipboard');
    });
}

async function handleDelete(taskId) {
    const wt = worktreesData.find(w => w.task_id === taskId);
    if (!wt) return;

    if (!confirm(`Delete worktree for task "${taskId}"?\n\nThis will remove:\n- ${wt.path}\n- Local branch: ${wt.branch}`)) {
        return;
    }

    try {
        await API.worktrees.remove(taskId);
        loadWorktrees();
    } catch (error) {
        console.error('Delete failed:', error);
        alert(`Delete failed: ${error.message}`);
    }
}

function openTaskModal(taskId) {
    // Dispatch event to open task modal (handled by task-modal.js)
    window.dispatchEvent(new CustomEvent('open-task-modal', {
        detail: { taskId }
    }));
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

// Initialize on DOM ready
document.addEventListener('DOMContentLoaded', () => {
    initWorktrees();
});
