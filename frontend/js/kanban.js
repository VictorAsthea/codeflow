import { API } from './api.js';
import { MentionAutocomplete } from './mention-autocomplete.js';
import { ImagePasteHandler } from './image-paste-handler.js';
import { FilePicker } from './file-picker.js';

let tasks = [];
let archivedCount = 0;
let mentionAutocomplete = null;
let imagePasteHandler = null;
let filePicker = null;
const fileReferences = new Set();
const screenshots = [];

// Multi-select state for batch queuing
let multiSelectMode = false;
let selectedTaskIds = new Set();

/**
 * Maps task status to the correct column identifier
 * @param {string} status - The task status
 * @returns {string} The column identifier
 */
function getColumnForStatus(status) {
    const statusMap = {
        'backlog': 'backlog',
        'queued': 'queued',
        'in_progress': 'in_progress',
        'ai_review': 'ai_review',
        'human_review': 'human_review',
        'done': 'done'
    };

    return statusMap[status] || 'backlog';
}

export async function initKanban() {
    await loadTasks();
    setupNewTaskButton();
    setupDragAndDrop();
    setupArchivedIndicator();
    setupBatchQueueControls();
    await updateQueueStatus();
    await updateArchivedCount();

    // Poll queue status every 5 seconds
    setInterval(updateQueueStatus, 5000);
}

/**
 * Set up the archived tasks indicator in the DONE column header
 */
function setupArchivedIndicator() {
    const indicator = document.getElementById('archived-indicator');
    if (!indicator) return;

    // Click handler to open archived tasks modal
    indicator.addEventListener('click', () => {
        const event = new CustomEvent('open-archived-tasks');
        window.dispatchEvent(event);
    });
}

/**
 * Set up batch queue controls for multi-select functionality
 */
function setupBatchQueueControls() {
    // Create the batch queue toolbar if it doesn't exist
    let toolbar = document.getElementById('batch-queue-toolbar');
    if (!toolbar) {
        toolbar = document.createElement('div');
        toolbar.id = 'batch-queue-toolbar';
        toolbar.className = 'batch-queue-toolbar hidden';
        toolbar.innerHTML = `
            <div class="batch-toolbar-left">
                <button class="btn-toggle-multiselect" id="btn-toggle-multiselect" title="Toggle multi-select mode">
                    <span class="multiselect-icon">☐</span>
                    <span class="multiselect-text">Multi-Select</span>
                </button>
                <span class="selected-count hidden" id="selected-count">0 selected</span>
            </div>
            <div class="batch-toolbar-right hidden" id="batch-actions">
                <select class="batch-priority-select" id="batch-priority">
                    <option value="high">High Priority</option>
                    <option value="normal" selected>Normal Priority</option>
                    <option value="low">Low Priority</option>
                </select>
                <button class="btn btn-primary btn-queue-selected" id="btn-queue-selected" disabled>
                    ⚡ Queue Selected
                </button>
                <button class="btn btn-secondary btn-clear-selection" id="btn-clear-selection">
                    Clear
                </button>
            </div>
        `;

        // Insert after the kanban board header or at the top of kanban view
        const kanbanView = document.getElementById('kanban-view');
        const kanbanBoard = kanbanView?.querySelector('.kanban-board');
        if (kanbanBoard) {
            kanbanView.insertBefore(toolbar, kanbanBoard);
        }
    }

    // Attach event listeners
    const toggleBtn = document.getElementById('btn-toggle-multiselect');
    const queueBtn = document.getElementById('btn-queue-selected');
    const clearBtn = document.getElementById('btn-clear-selection');

    toggleBtn?.addEventListener('click', toggleMultiSelectMode);
    queueBtn?.addEventListener('click', queueSelectedTasks);
    clearBtn?.addEventListener('click', clearTaskSelection);

    // Show the toolbar (but keep batch actions hidden until multi-select is enabled)
    toolbar.classList.remove('hidden');
}

/**
 * Toggle multi-select mode on/off
 */
function toggleMultiSelectMode() {
    multiSelectMode = !multiSelectMode;

    const toggleBtn = document.getElementById('btn-toggle-multiselect');
    const batchActions = document.getElementById('batch-actions');
    const selectedCountEl = document.getElementById('selected-count');

    if (multiSelectMode) {
        toggleBtn?.classList.add('active');
        batchActions?.classList.remove('hidden');
        selectedCountEl?.classList.remove('hidden');
        document.body.classList.add('multiselect-mode');
    } else {
        toggleBtn?.classList.remove('active');
        batchActions?.classList.add('hidden');
        selectedCountEl?.classList.add('hidden');
        document.body.classList.remove('multiselect-mode');
        clearTaskSelection();
    }

    // Re-render task cards to show/hide checkboxes
    renderAllTasks();
}

/**
 * Toggle task selection
 */
export function toggleTaskSelection(taskId, event) {
    if (!multiSelectMode) return;

    // Prevent the click from opening the task modal
    if (event) {
        event.stopPropagation();
    }

    if (selectedTaskIds.has(taskId)) {
        selectedTaskIds.delete(taskId);
    } else {
        selectedTaskIds.add(taskId);
    }

    updateTaskSelectionUI(taskId);
    updateBatchQueueButton();
}

/**
 * Update the visual selection state of a task card
 */
function updateTaskSelectionUI(taskId) {
    const card = document.querySelector(`.task-card[data-task-id="${taskId}"]`);
    if (!card) return;

    const checkbox = card.querySelector('.task-select-checkbox');
    const isSelected = selectedTaskIds.has(taskId);

    card.classList.toggle('selected', isSelected);
    if (checkbox) {
        checkbox.checked = isSelected;
    }
}

/**
 * Update the batch queue button state
 */
function updateBatchQueueButton() {
    const queueBtn = document.getElementById('btn-queue-selected');
    const selectedCountEl = document.getElementById('selected-count');

    const count = selectedTaskIds.size;

    if (queueBtn) {
        queueBtn.disabled = count === 0;
        queueBtn.textContent = count > 0 ? `⚡ Queue Selected (${count})` : '⚡ Queue Selected';
    }

    if (selectedCountEl) {
        selectedCountEl.textContent = `${count} selected`;
    }
}

/**
 * Clear all task selections
 */
function clearTaskSelection() {
    selectedTaskIds.forEach(taskId => {
        const card = document.querySelector(`.task-card[data-task-id="${taskId}"]`);
        if (card) {
            card.classList.remove('selected');
            const checkbox = card.querySelector('.task-select-checkbox');
            if (checkbox) {
                checkbox.checked = false;
            }
        }
    });

    selectedTaskIds.clear();
    updateBatchQueueButton();
}

/**
 * Queue all selected tasks for batch execution
 */
async function queueSelectedTasks() {
    if (selectedTaskIds.size === 0) return;

    const priority = document.getElementById('batch-priority')?.value || 'normal';

    const tasksToQueue = Array.from(selectedTaskIds).map(taskId => ({
        task_id: taskId,
        priority: priority
    }));

    try {
        const response = await API.queue.batch(tasksToQueue);

        if (response.results) {
            const successCount = response.results.filter(r => r.success).length;
            const failCount = response.results.filter(r => !r.success).length;

            if (failCount > 0) {
                window.showToast?.(`Queued ${successCount} tasks, ${failCount} failed`, 'warning');
            } else {
                window.showToast?.(`Queued ${successCount} tasks successfully`, 'success');
            }
        }

        // Clear selection and reload
        clearTaskSelection();
        await loadTasks();
        await updateQueueStatus();

        // Dispatch event for parallel dashboard
        window.dispatchEvent(new CustomEvent('tasks-batch-queued', {
            detail: { tasks: tasksToQueue, results: response.results }
        }));

    } catch (error) {
        console.error('Failed to batch queue tasks:', error);
        window.showToast?.('Failed to queue tasks: ' + error.message, 'error');
    }
}

/**
 * Update the archived tasks count
 */
export async function updateArchivedCount() {
    try {
        const response = await API.tasks.listArchived();
        archivedCount = response.tasks.length;
    } catch (error) {
        console.error('Failed to fetch archived tasks count:', error);
    }
}

export async function updateQueueStatus() {
    // Count running tasks from loaded tasks array
    const running = tasks.filter(t => t.status === 'in_progress').length;
    const maxConcurrent = 3; // Could be fetched from settings

    document.getElementById('queue-running').textContent = running;
    document.getElementById('queue-max').textContent = maxConcurrent;

    const queuedContainer = document.getElementById('queue-queued-container');
    const queueStatus = document.getElementById('queue-status');

    // Hide queued counter (no longer using queue)
    queuedContainer?.classList.add('hidden');

    if (running > 0) {
        queueStatus?.classList.add('has-running');
    } else {
        queueStatus?.classList.remove('has-running');
    }
}

export async function loadTasks() {
    try {
        const response = await API.tasks.list();
        tasks = response.tasks;
        renderAllTasks();
        updateCounts();
    } catch (error) {
        console.error('Failed to load tasks:', error);
    }
}

function renderAllTasks() {
    const columns = {
        backlog: document.getElementById('column-backlog'),
        queued: document.getElementById('column-queued'),
        in_progress: document.getElementById('column-in_progress'),
        ai_review: document.getElementById('column-ai_review'),
        human_review: document.getElementById('column-human_review'),
        done: document.getElementById('column-done'),
    };

    Object.values(columns).forEach(col => {
        const existingCards = col.querySelectorAll('.task-card');
        existingCards.forEach(card => card.remove());
    });

    tasks.forEach(task => {
        const card = createTaskCard(task);
        const columnKey = getColumnForStatus(task.status);
        const column = columns[columnKey];
        if (column) {
            const newTaskBtn = column.querySelector('.btn-new-task');
            if (newTaskBtn) {
                column.insertBefore(card, newTaskBtn);
            } else {
                column.appendChild(card);
            }
        }
    });
}

function createTaskCard(task) {
    const card = document.createElement('div');
    card.className = 'task-card';
    card.draggable = true;
    card.dataset.taskId = task.id;

    // Add selected class if task is selected
    if (selectedTaskIds.has(task.id)) {
        card.classList.add('selected');
    }

    // Phase steps (compact view)
    const phaseSteps = renderPhaseSteps(task);

    // Subtask progress (if any)
    const subtaskProgress = renderSubtaskProgress(task);

    const timeAgo = getTimeAgo(new Date(task.updated_at));
    const skipBadge = task.skip_ai_review ? '<span class="badge-skip-ai">⏭️ Skip AI Review</span>' : '';

    // Status badges
    let statusBadge = '';
    if (task.status === 'queued') {
        statusBadge = '<span class="badge-queued">⏳ Queued</span>';
    } else if (task.status === 'in_progress') {
        statusBadge = '<span class="badge-running">▶️ Running</span>';
    } else if (task.status === 'ai_review') {
        const reviewText = task.review_status === 'in_progress' ? '🔍 Reviewing...' : '🔍 AI Review';
        statusBadge = `<span class="badge-reviewing">${reviewText}</span>`;
    }

    // Multi-select checkbox (only for backlog tasks, shown in multi-select mode)
    const canBeQueued = task.status === 'backlog';
    const checkboxHtml = canBeQueued && multiSelectMode
        ? `<input type="checkbox" class="task-select-checkbox" ${selectedTaskIds.has(task.id) ? 'checked' : ''} />`
        : '';

    // Action buttons (only for backlog tasks)
    let actionButtons = '';
    if (task.status === 'backlog') {
        actionButtons = `
            <div class="task-card-actions">
                <button class="btn-small btn-start" data-action="start" data-task-id="${task.id}">▶️ Start</button>
            </div>
        `;
    }

    // Truncate description
    const truncatedDesc = task.description.length > 100
        ? task.description.substring(0, 100) + '...'
        : task.description;

    card.innerHTML = `
        <div class="task-card-header-row">
            ${checkboxHtml}
            <h3>${task.title} ${skipBadge} ${statusBadge}</h3>
        </div>
        <p>${truncatedDesc}</p>
        ${subtaskProgress}
        <div class="task-card-phases">
            ${phaseSteps}
        </div>
        ${actionButtons}
        <div class="task-footer">
            <span>⏱️ ${timeAgo}</span>
            <span>${task.id}</span>
        </div>
    `;

    // Multi-select checkbox handler
    const checkbox = card.querySelector('.task-select-checkbox');
    if (checkbox) {
        checkbox.addEventListener('click', (e) => {
            e.stopPropagation();
            toggleTaskSelection(task.id, e);
        });
    }

    // Action button handler
    const startBtn = card.querySelector('[data-action="start"]');

    if (startBtn) {
        startBtn.addEventListener('click', async (e) => {
            e.stopPropagation();
            try {
                await API.tasks.start(task.id);
                await loadTasks();
                updateQueueStatus();
            } catch (error) {
                console.error('Failed to start task:', error);
                alert('Failed to start task: ' + error.message);
            }
        });
    }

    card.addEventListener('click', (e) => {
        // In multi-select mode, clicking the card toggles selection for backlog tasks
        if (multiSelectMode && canBeQueued) {
            toggleTaskSelection(task.id, e);
        } else {
            openTaskModal(task.id);
        }
    });

    return card;
}

function renderPhaseSteps(task) {
    const phases = task.phases || {};

    const getPhaseIcon = (status) => {
        switch (status) {
            case 'done':
            case 'completed': return '✓';
            case 'running':
            case 'in_progress': return '●';
            case 'failed': return '✗';
            default: return '○';
        }
    };

    const planStatus = phases.planning?.status || 'pending';
    const codeStatus = phases.coding?.status || 'pending';
    const qaStatus = phases.validation?.status || 'pending';

    return `
        <div class="phase-steps">
            <span class="phase-step ${planStatus}">
                ${getPhaseIcon(planStatus)} Plan
            </span>
            <span class="phase-separator">—</span>
            <span class="phase-step ${codeStatus}">
                ${getPhaseIcon(codeStatus)} Code
            </span>
            <span class="phase-separator">—</span>
            <span class="phase-step ${qaStatus}">
                ${getPhaseIcon(qaStatus)} QA
            </span>
        </div>
    `;
}

function renderSubtaskProgress(task) {
    const subtasks = task.subtasks || [];
    if (subtasks.length === 0) return '';

    const total = subtasks.length;
    const completed = subtasks.filter(s => s.status === 'completed').length;
    const percentage = Math.round((completed / total) * 100);

    return `
        <div class="task-card-progress">
            <div class="progress-label">
                <span>Progress</span>
                <span>${completed}/${total} (${percentage}%)</span>
            </div>
            <div class="progress-bar">
                <div class="progress-fill" style="width: ${percentage}%"></div>
            </div>
            <div class="subtask-dots">
                ${subtasks.map(s => `<span class="subtask-dot ${s.status}"></span>`).join('')}
            </div>
        </div>
    `;
}

/**
 * Update a specific task card without re-rendering the entire kanban
 * Called by WebSocket event handlers when subtask/phase status changes
 * @param {string} taskId - The task ID to update
 * @param {Object} data - Updated task data (subtasks, phases, status, etc.)
 */
export function updateTaskCard(taskId, data) {
    // Find the card element
    const card = document.querySelector(`.task-card[data-task-id="${taskId}"]`);
    if (!card) {
        console.warn(`updateTaskCard: Card not found for task ${taskId}`);
        return;
    }

    // Update the local tasks array with new data
    const taskIndex = tasks.findIndex(t => t.id === taskId);
    if (taskIndex !== -1) {
        // Handle partial subtask updates via _subtaskUpdate field
        if (data._subtaskUpdate) {
            const { order, status, subtask } = data._subtaskUpdate;
            const existingSubtasks = tasks[taskIndex].subtasks || [];

            // Find and update the specific subtask by order
            const subtaskIndex = existingSubtasks.findIndex(s => s.order === order);
            if (subtaskIndex !== -1) {
                existingSubtasks[subtaskIndex] = { ...existingSubtasks[subtaskIndex], ...subtask, status };
            } else {
                // Add the new subtask if it doesn't exist
                existingSubtasks.push({ ...subtask, status });
                // Optionally, sort to maintain order
                existingSubtasks.sort((a, b) => a.order - b.order);
            }

            tasks[taskIndex].subtasks = existingSubtasks;
        }
        // Handle partial phase updates via _phaseUpdate field
        else if (data._phaseUpdate) {
            const { phase, status } = data._phaseUpdate;
            const existingPhases = tasks[taskIndex].phases || {};

            // Update the specific phase status
            if (!existingPhases[phase]) {
                existingPhases[phase] = {};
            }
            existingPhases[phase].status = status;

            tasks[taskIndex].phases = existingPhases;
        } else {
            // Merge the new data into the existing task
            tasks[taskIndex] = { ...tasks[taskIndex], ...data };
        }
    }

    // Get the updated task (either from merged data or use provided data)
    const task = taskIndex !== -1 ? tasks[taskIndex] : data;

    // Update progress bar and subtask dots
    updateCardProgress(card, task);

    // Update phase steps
    updateCardPhases(card, task);

    // Update status badge if status changed
    if (data.status !== undefined) {
        updateCardStatusBadge(card, task);
    }
}

/**
 * Update the progress bar and subtask dots on a card
 * @param {HTMLElement} card - The card DOM element
 * @param {Object} task - The task data
 */
function updateCardProgress(card, task) {
    const subtasks = task.subtasks || [];
    const progressContainer = card.querySelector('.task-card-progress');

    // If no subtasks, remove progress section if it exists
    if (subtasks.length === 0) {
        if (progressContainer) {
            progressContainer.remove();
        }
        return;
    }

    const total = subtasks.length;
    const completed = subtasks.filter(s => s.status === 'completed').length;
    const percentage = Math.round((completed / total) * 100);

    if (progressContainer) {
        // Update existing progress elements
        const progressLabel = progressContainer.querySelector('.progress-label span:last-child');
        if (progressLabel) {
            progressLabel.textContent = `${completed}/${total} (${percentage}%)`;
        }

        const progressFill = progressContainer.querySelector('.progress-fill');
        if (progressFill) {
            progressFill.style.width = `${percentage}%`;
        }

        // Update subtask dots
        const dotsContainer = progressContainer.querySelector('.subtask-dots');
        if (dotsContainer) {
            dotsContainer.innerHTML = subtasks.map(s =>
                `<span class="subtask-dot ${s.status}"></span>`
            ).join('');
        }
    } else {
        // Create progress section if it doesn't exist but we have subtasks
        const progressHtml = renderSubtaskProgress(task);
        if (progressHtml) {
            const phasesContainer = card.querySelector('.task-card-phases');
            if (phasesContainer) {
                phasesContainer.insertAdjacentHTML('beforebegin', progressHtml);
            }
        }
    }
}

/**
 * Update the phase steps on a card
 * @param {HTMLElement} card - The card DOM element
 * @param {Object} task - The task data
 */
function updateCardPhases(card, task) {
    const phasesContainer = card.querySelector('.task-card-phases');
    if (!phasesContainer) return;

    // Re-render the phase steps using the existing function
    phasesContainer.innerHTML = renderPhaseSteps(task);
}

/**
 * Update the status badge on a card
 * @param {HTMLElement} card - The card DOM element
 * @param {Object} task - The task data
 */
function updateCardStatusBadge(card, task) {
    const h3 = card.querySelector('h3');
    if (!h3) return;

    // Remove existing status badges
    const existingBadges = h3.querySelectorAll('.badge-queued, .badge-running, .badge-reviewing');
    existingBadges.forEach(badge => badge.remove());

    // Add new status badge if applicable
    let statusBadge = '';
    if (task.status === 'queued') {
        statusBadge = '<span class="badge-queued">⏳ Queued</span>';
    } else if (task.status === 'in_progress') {
        statusBadge = '<span class="badge-running">▶️ Running</span>';
    } else if (task.status === 'ai_review') {
        const reviewText = task.review_status === 'in_progress' ? '🔍 Reviewing...' : '🔍 AI Review';
        statusBadge = `<span class="badge-reviewing">${reviewText}</span>`;
    }

    if (statusBadge) {
        h3.insertAdjacentHTML('beforeend', ` ${statusBadge}`);
    }
}

function getTimeAgo(date) {
    const seconds = Math.floor((new Date() - date) / 1000);

    if (seconds < 60) return 'just now';
    if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
    if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`;
    return `${Math.floor(seconds / 86400)}d ago`;
}

function updateCounts() {
    const counts = {
        backlog: 0,
        queued: 0,
        in_progress: 0,
        ai_review: 0,
        human_review: 0,
        done: 0,
    };

    tasks.forEach(task => {
        if (counts[task.status] !== undefined) {
            counts[task.status]++;
        }
    });

    Object.keys(counts).forEach(status => {
        const countEl = document.getElementById(`count-${status}`);
        if (countEl) {
            countEl.textContent = counts[status];
        }
    });
}

function setupDragAndDrop() {
    const cards = document.querySelectorAll('.task-card');
    const columns = document.querySelectorAll('.column-body');

    document.addEventListener('dragstart', (e) => {
        if (e.target.classList.contains('task-card')) {
            e.target.classList.add('dragging');
        }
    });

    document.addEventListener('dragend', (e) => {
        if (e.target.classList.contains('task-card')) {
            e.target.classList.remove('dragging');
        }
    });

    columns.forEach(column => {
        column.addEventListener('dragover', (e) => {
            e.preventDefault();
            const dragging = document.querySelector('.dragging');
            if (dragging) {
                column.appendChild(dragging);
            }
        });

        column.addEventListener('drop', async (e) => {
            e.preventDefault();
            const dragging = document.querySelector('.dragging');
            if (!dragging) return;

            const taskId = dragging.dataset.taskId;
            const newStatus = column.parentElement.dataset.status;

            try {
                await API.tasks.changeStatus(taskId, newStatus);
                await loadTasks();
            } catch (error) {
                console.error('Failed to update task status:', error);
                alert('Failed to move task: ' + error.message);
                await loadTasks();
            }
        });
    });
}

function setupCollapsibleSections() {
    const triggers = document.querySelectorAll('.collapsible-trigger');
    triggers.forEach(trigger => {
        trigger.addEventListener('click', () => {
            const parent = trigger.closest('.collapsible');
            const content = parent.querySelector('.collapsible-content');
            const icon = trigger.querySelector('.collapse-icon');

            parent.classList.toggle('expanded');
            content.classList.toggle('hidden');
            icon.textContent = parent.classList.contains('expanded') ? '▼' : '▶';
        });
    });
}

function initializeFormModules() {
    const textarea = document.getElementById('task-description');
    const browseBtn = document.getElementById('browse-files-btn');

    if (!mentionAutocomplete) {
        mentionAutocomplete = new MentionAutocomplete(textarea, {
            onSelect: (file) => {
                addFileReference(file);
            }
        });
    }

    if (!imagePasteHandler) {
        imagePasteHandler = new ImagePasteHandler(textarea, {
            onPaste: (imageData) => {
                addScreenshot(imageData);
            }
        });
    }

    if (!filePicker && browseBtn) {
        filePicker = new FilePicker(browseBtn, {
            onSelect: (files) => {
                files.forEach(file => addFileReference(file));
            }
        });
    }
}

function addFileReference(filePath) {
    fileReferences.add(filePath);
    renderFileReferences();
}

function removeFileReference(filePath) {
    fileReferences.delete(filePath);
    renderFileReferences();
}

function renderFileReferences() {
    const container = document.getElementById('file-references-list');
    if (!container) return;

    if (fileReferences.size === 0) {
        container.innerHTML = '';
        return;
    }

    container.innerHTML = `
        <div class="references-header">📎 Referenced files (${fileReferences.size})</div>
        ${Array.from(fileReferences).map(file => `
            <span class="file-ref-tag">
                <span>📄 ${file}</span>
                <button type="button" class="remove-ref" data-file="${file}">&times;</button>
            </span>
        `).join('')}
    `;

    container.querySelectorAll('.remove-ref').forEach(btn => {
        btn.addEventListener('click', (e) => {
            const file = e.target.dataset.file;
            removeFileReference(file);
        });
    });
}

function addScreenshot(imageDataUrl) {
    screenshots.push(imageDataUrl);
    renderScreenshots();
}

function removeScreenshot(index) {
    screenshots.splice(index, 1);
    renderScreenshots();
}

function renderScreenshots() {
    const container = document.getElementById('screenshots-preview');
    if (!container) return;

    if (screenshots.length === 0) {
        container.innerHTML = '';
        return;
    }

    container.innerHTML = `
        <div class="screenshots-header">🖼️ Screenshots (${screenshots.length})</div>
        <div class="screenshot-grid">
            ${screenshots.map((img, idx) => `
                <div class="screenshot-item">
                    <img src="${img}" alt="Screenshot ${idx + 1}">
                    <button type="button" class="remove-screenshot" data-index="${idx}">&times;</button>
                </div>
            `).join('')}
        </div>
    `;

    container.querySelectorAll('.remove-screenshot').forEach(btn => {
        btn.addEventListener('click', (e) => {
            const index = parseInt(e.target.dataset.index);
            removeScreenshot(index);
        });
    });
}

function setupNewTaskButton() {
    const newTaskBtn = document.querySelector('.btn-new-task');
    const newTaskModal = document.getElementById('new-task-modal');
    const createTaskBtn = document.getElementById('btn-create-task');
    const form = document.getElementById('new-task-form');

    setupCollapsibleSections();

    newTaskBtn.addEventListener('click', () => {
        form.reset();
        fileReferences.clear();
        screenshots.length = 0;
        renderFileReferences();
        renderScreenshots();
        initializeFormModules();
        newTaskModal.classList.remove('hidden');
    });

    createTaskBtn.addEventListener('click', async () => {
        const title = document.getElementById('task-title')?.value.trim() || null;
        const description = document.getElementById('task-description').value.trim();

        if (!description) {
            alert('Please provide a task description');
            return;
        }

        const agentProfile = document.getElementById('agent-profile')?.value || 'balanced';

        const phaseConfig = {};
        const planningModel = document.getElementById('planning-model')?.value;
        const planningMaxTurns = document.getElementById('planning-max-turns')?.value;
        const codingModel = document.getElementById('coding-model')?.value;
        const codingMaxTurns = document.getElementById('coding-max-turns')?.value;
        const validationModel = document.getElementById('validation-model')?.value;
        const validationMaxTurns = document.getElementById('validation-max-turns')?.value;

        if (planningModel || planningMaxTurns) {
            phaseConfig.planning = {};
            if (planningModel) phaseConfig.planning.model = planningModel;
            if (planningMaxTurns) phaseConfig.planning.max_turns = parseInt(planningMaxTurns);
        }
        if (codingModel || codingMaxTurns) {
            phaseConfig.coding = {};
            if (codingModel) phaseConfig.coding.model = codingModel;
            if (codingMaxTurns) phaseConfig.coding.max_turns = parseInt(codingMaxTurns);
        }
        if (validationModel || validationMaxTurns) {
            phaseConfig.validation = {};
            if (validationModel) phaseConfig.validation.model = validationModel;
            if (validationMaxTurns) phaseConfig.validation.max_turns = parseInt(validationMaxTurns);
        }

        const requireReview = document.getElementById('require-review-before-coding')?.checked || false;
        const skipAiReview = document.getElementById('skip-ai-review')?.checked || false;

        const gitOptions = {};
        const branchName = document.getElementById('git-branch-name')?.value.trim();
        const targetBranch = document.getElementById('git-target-branch')?.value;
        if (branchName) gitOptions.branch_name = branchName;
        if (targetBranch) gitOptions.target_branch = targetBranch;

        const taskData = {
            title,
            description,
            agent_profile: agentProfile,
            phase_config: Object.keys(phaseConfig).length > 0 ? phaseConfig : null,
            require_human_review_before_coding: requireReview,
            skip_ai_review: skipAiReview,
            git_options: Object.keys(gitOptions).length > 0 ? gitOptions : null,
            file_references: Array.from(fileReferences),
            screenshots: screenshots.slice()
        };

        try {
            await API.tasks.create(taskData);
            newTaskModal.classList.add('hidden');
            form.reset();
            fileReferences.clear();
            screenshots.length = 0;
            renderFileReferences();
            renderScreenshots();
            await loadTasks();
        } catch (error) {
            console.error('Failed to create task:', error);
            alert('Failed to create task: ' + error.message);
        }
    });
}

function openTaskModal(taskId) {
    const event = new CustomEvent('open-task-modal', { detail: { taskId } });
    window.dispatchEvent(event);
}

window.addEventListener('task-updated', async () => {
    await loadTasks();
    await updateArchivedCount();
});

window.addEventListener('DOMContentLoaded', () => {
    initKanban();
});

// Expose globally for workspace.js
window.loadKanban = loadTasks;
