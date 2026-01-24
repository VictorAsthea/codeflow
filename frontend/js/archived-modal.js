import { API } from './api.js';
import { updateArchivedCount } from './kanban.js';

let archivedTasks = [];

export function initArchivedModal() {
    setupModalClose();

    // Listen for open event from kanban indicator
    window.addEventListener('open-archived-tasks', async () => {
        await openArchivedModal();
    });
}

async function openArchivedModal() {
    const modal = document.getElementById('archived-tasks-modal');
    const listContainer = document.getElementById('archived-tasks-list');

    if (!modal || !listContainer) return;

    // Show modal with loading state
    modal.classList.remove('hidden');
    listContainer.innerHTML = '<p class="loading-text">Loading archived tasks...</p>';

    try {
        const response = await API.tasks.listArchived();
        archivedTasks = response.tasks;
        renderArchivedTasks();
    } catch (error) {
        console.error('Failed to load archived tasks:', error);
        listContainer.innerHTML = '<p class="error-text">Failed to load archived tasks.</p>';
    }
}

function renderArchivedTasks() {
    const listContainer = document.getElementById('archived-tasks-list');
    if (!listContainer) return;

    if (archivedTasks.length === 0) {
        listContainer.innerHTML = `
            <div class="archived-empty-state">
                <div class="empty-icon">📭</div>
                <p>No archived tasks yet.</p>
            </div>
        `;
        return;
    }

    const html = archivedTasks.map(task => {
        const completedDate = formatDate(task.updated_at);

        return `
            <div class="archived-task-card" data-task-id="${task.id}">
                <div class="archived-task-info">
                    <div class="archived-task-title" title="${escapeHtml(task.title)}">${escapeHtml(task.title)}</div>
                    <div class="archived-task-meta">
                        <span class="archived-task-id">${task.id}</span>
                        <span class="archived-task-date">
                            <span>Completed:</span>
                            <span>${completedDate}</span>
                        </span>
                    </div>
                </div>
                <div class="archived-task-actions">
                    <button class="btn-unarchive" data-task-id="${task.id}">
                        Unarchive
                    </button>
                </div>
            </div>
        `;
    }).join('');

    listContainer.innerHTML = html;

    // Add click handlers for unarchive buttons
    listContainer.querySelectorAll('.btn-unarchive').forEach(btn => {
        btn.addEventListener('click', handleUnarchive);
    });
}

async function handleUnarchive(event) {
    const btn = event.target;
    const taskId = btn.dataset.taskId;

    if (!taskId) return;

    btn.disabled = true;
    btn.textContent = 'Restoring...';

    try {
        await API.tasks.unarchive(taskId);

        // Remove from local array
        archivedTasks = archivedTasks.filter(t => t.id !== taskId);

        // Re-render the list
        renderArchivedTasks();

        // Update the kanban board and archived count
        window.dispatchEvent(new Event('task-updated'));
        await updateArchivedCount();

        // Close modal if no more archived tasks
        if (archivedTasks.length === 0) {
            closeModal();
        }
    } catch (error) {
        console.error('Failed to unarchive task:', error);
        alert('Failed to unarchive task: ' + error.message);
        btn.disabled = false;
        btn.textContent = 'Unarchive';
    }
}

function setupModalClose() {
    const modal = document.getElementById('archived-tasks-modal');
    if (!modal) return;

    // Close button
    const closeBtn = modal.querySelector('.btn-close');
    if (closeBtn) {
        closeBtn.addEventListener('click', closeModal);
    }

    // Click outside modal to close
    modal.addEventListener('click', (e) => {
        if (e.target === modal) {
            closeModal();
        }
    });

    // ESC key to close
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape' && !modal.classList.contains('hidden')) {
            closeModal();
        }
    });
}

function closeModal() {
    const modal = document.getElementById('archived-tasks-modal');
    if (modal) {
        modal.classList.add('hidden');
    }
}

function formatDate(dateString) {
    const date = new Date(dateString);
    return date.toLocaleDateString('en-US', {
        month: 'short',
        day: 'numeric',
        year: 'numeric'
    });
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

// Initialize when DOM is ready
window.addEventListener('DOMContentLoaded', () => {
    initArchivedModal();
});
