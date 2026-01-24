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
    await updateQueueStatus();
    await updateArchivedCount();

    // Poll queue status every 5 seconds
    setInterval(updateQueueStatus, 5000);
}

/**
 * Set up the archived tasks indicator in the DONE column header
 */
function setupArchivedIndicator() {
    const doneColumn = document.querySelector('.column[data-status="done"]');
    if (!doneColumn) return;

    const header = doneColumn.querySelector('.column-header');
    if (!header) return;

    // Create archived indicator (hidden by default)
    const indicator = document.createElement('button');
    indicator.id = 'archived-indicator';
    indicator.className = 'archived-indicator hidden';
    indicator.title = 'View archived tasks';
    indicator.innerHTML = '<span class="archived-icon">📦</span><span class="archived-count">0</span>';

    // Insert before the count badge
    const countBadge = header.querySelector('.count');
    if (countBadge) {
        header.insertBefore(indicator, countBadge);
    } else {
        header.appendChild(indicator);
    }

    // Click handler to open archived tasks modal
    indicator.addEventListener('click', () => {
        const event = new CustomEvent('open-archived-tasks');
        window.dispatchEvent(event);
    });
}

/**
 * Update the archived tasks count indicator
 */
export async function updateArchivedCount() {
    try {
        const response = await API.tasks.listArchived();
        archivedCount = response.tasks.length;

        const indicator = document.getElementById('archived-indicator');
        if (indicator) {
            const countEl = indicator.querySelector('.archived-count');
            if (countEl) {
                countEl.textContent = archivedCount;
            }

            // Show/hide based on count
            if (archivedCount > 0) {
                indicator.classList.remove('hidden');
            } else {
                indicator.classList.add('hidden');
            }
        }
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

    const phases = ['planning', 'coding', 'validation'];
    const phaseBars = phases.map(phaseName => {
        const phase = task.phases[phaseName];
        if (!phase) return '';

        let progressWidth = 0;
        let progressClass = '';
        let statusText = 'Pending';

        if (phase.status === 'running') {
            progressWidth = 50;
            progressClass = '';
            statusText = 'Running';
        } else if (phase.status === 'done') {
            progressWidth = 100;
            progressClass = 'done';
            statusText = 'Done';
        } else if (phase.status === 'failed') {
            progressWidth = 100;
            progressClass = 'failed';
            statusText = 'Failed';
        }

        return `
            <div class="phase-bar">
                <span class="phase-name">${phaseName}</span>
                <div class="progress-bar">
                    <div class="progress-fill ${progressClass}" style="width: ${progressWidth}%"></div>
                </div>
                <span class="phase-status">${statusText}</span>
            </div>
        `;
    }).join('');

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

    // Action buttons (only for backlog tasks)
    let actionButtons = '';
    if (task.status === 'backlog') {
        actionButtons = `
            <div class="task-card-actions">
                <button class="btn-small btn-start" data-action="start" data-task-id="${task.id}">▶️ Start</button>
            </div>
        `;
    }

    card.innerHTML = `
        <h3>${task.title} ${skipBadge} ${statusBadge}</h3>
        <p>${task.description}</p>
        <div class="task-phases">
            ${phaseBars}
        </div>
        ${actionButtons}
        <div class="task-footer">
            <span>⏱️ ${timeAgo}</span>
            <span>${task.id}</span>
        </div>
    `;

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

    card.addEventListener('click', () => {
        openTaskModal(task.id);
    });

    return card;
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
