import { API } from './api.js';

let tasks = [];

export async function initKanban() {
    await loadTasks();
    setupNewTaskButton();
    setupDragAndDrop();
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
        const column = columns[task.status];
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

    card.innerHTML = `
        <h3>${task.title} ${skipBadge}</h3>
        <p>${task.description}</p>
        <div class="task-phases">
            ${phaseBars}
        </div>
        <div class="task-footer">
            <span>⏱️ ${timeAgo}</span>
            <span>${task.id}</span>
        </div>
    `;

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

function setupNewTaskButton() {
    const newTaskBtn = document.querySelector('.btn-new-task');
    const newTaskModal = document.getElementById('new-task-modal');
    const createTaskBtn = document.getElementById('btn-create-task');
    const form = document.getElementById('new-task-form');

    newTaskBtn.addEventListener('click', () => {
        form.reset();
        newTaskModal.classList.remove('hidden');
    });

    createTaskBtn.addEventListener('click', async () => {
        const title = document.getElementById('task-title').value.trim();
        const description = document.getElementById('task-description').value.trim();
        const skipAiReview = document.getElementById('skip-ai-review').checked;

        if (!title || !description) {
            alert('Please fill in all fields');
            return;
        }

        try {
            await API.tasks.create({ title, description, skip_ai_review: skipAiReview });
            newTaskModal.classList.add('hidden');
            form.reset();
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
});

window.addEventListener('DOMContentLoaded', () => {
    initKanban();
});
