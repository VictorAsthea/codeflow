/**
 * Parallel Execution Dashboard
 * Real-time monitoring and control of parallel task execution across worktrees.
 */

import { API } from './api.js';

// WebSocket connection state
let parallelSocket = null;
let reconnectAttempts = 0;
const MAX_RECONNECT_ATTEMPTS = 5;
const RECONNECT_DELAY_MS = 3000;

// Dashboard state
let runningTasks = [];
let queuedTasks = [];
let aggregateProgress = {};
let isPaused = false;
let draggedTaskId = null;
let queueEstimates = {};

/**
 * ParallelDashboard class - manages the parallel execution dashboard UI
 */
export class ParallelDashboard {
    constructor(containerId) {
        this.container = document.getElementById(containerId);
        this.isVisible = false;
        this.selectedTasks = new Set();

        if (this.container) {
            this.init();
        }
    }

    /**
     * Initialize the dashboard
     */
    init() {
        this.render();
        this.attachEventListeners();
        this.connectWebSocket();
    }

    /**
     * Show the dashboard
     */
    show() {
        this.isVisible = true;
        this.container?.classList.remove('hidden');
        this.refreshData();
    }

    /**
     * Hide the dashboard
     */
    hide() {
        this.isVisible = false;
        this.container?.classList.add('hidden');
    }

    /**
     * Toggle dashboard visibility
     */
    toggle() {
        if (this.isVisible) {
            this.hide();
        } else {
            this.show();
        }
    }

    /**
     * Render the dashboard HTML structure
     */
    render() {
        if (!this.container) return;

        this.container.innerHTML = `
            <div class="parallel-dashboard">
                <div class="dashboard-header">
                    <h2>Parallel Execution Dashboard</h2>
                    <div class="dashboard-actions">
                        <button class="btn-icon btn-refresh" title="Refresh">
                            <span>↻</span> Refresh
                        </button>
                        <button class="btn-icon btn-pause-queue" title="Pause/Resume Queue">
                            <span class="pause-icon">⏸</span> <span class="pause-text">Pause Queue</span>
                        </button>
                        <button class="btn-icon btn-close-dashboard" title="Close">✕</button>
                    </div>
                </div>

                <div class="dashboard-body">
                    <!-- Aggregate Progress Section -->
                    <div class="aggregate-section">
                        <div class="aggregate-stats">
                            <div class="stat-box">
                                <span class="stat-value" id="stat-running">0</span>
                                <span class="stat-label">Running</span>
                            </div>
                            <div class="stat-box">
                                <span class="stat-value" id="stat-queued">0</span>
                                <span class="stat-label">Queued</span>
                            </div>
                            <div class="stat-box">
                                <span class="stat-value" id="stat-completed">0</span>
                                <span class="stat-label">Completed</span>
                            </div>
                            <div class="stat-box">
                                <span class="stat-value" id="stat-failed">0</span>
                                <span class="stat-label">Failed</span>
                            </div>
                        </div>
                        <div class="estimate-summary" id="estimate-summary">
                            <span class="estimate-label">Estimated completion:</span>
                            <span class="estimate-value" id="estimate-all-complete">--</span>
                        </div>
                    </div>

                    <!-- Running Tasks Section -->
                    <div class="running-section">
                        <div class="section-header">
                            <h3>Running Tasks</h3>
                            <span class="section-count" id="running-count">0</span>
                        </div>
                        <div class="running-tasks-list" id="running-tasks-list">
                            <div class="empty-state">No tasks currently running</div>
                        </div>
                    </div>

                    <!-- Queue Section -->
                    <div class="queue-section">
                        <div class="section-header">
                            <h3>Task Queue</h3>
                            <span class="section-count" id="queue-count">0</span>
                            <div class="queue-actions">
                                <button class="btn-small btn-batch-start" id="btn-batch-start" disabled>
                                    ▶ Start Selected
                                </button>
                                <button class="btn-small btn-select-all" id="btn-select-all">
                                    Select All
                                </button>
                            </div>
                        </div>
                        <div class="queue-list" id="queue-list">
                            <div class="empty-state">No tasks in queue</div>
                        </div>
                        <div class="queue-drop-hint hidden" id="queue-drop-hint">
                            Drop here to reorder
                        </div>
                    </div>
                </div>

                <div class="dashboard-footer">
                    <div class="connection-status" id="ws-connection-status">
                        <span class="status-dot disconnected"></span>
                        <span class="status-text">Disconnected</span>
                    </div>
                    <div class="last-update" id="last-update">
                        Last update: --
                    </div>
                </div>
            </div>
        `;
    }

    /**
     * Attach event listeners
     */
    attachEventListeners() {
        if (!this.container) return;

        // Refresh button
        this.container.querySelector('.btn-refresh')?.addEventListener('click', () => {
            this.refreshData();
        });

        // Pause/Resume queue button
        this.container.querySelector('.btn-pause-queue')?.addEventListener('click', () => {
            this.toggleQueuePause();
        });

        // Close button
        this.container.querySelector('.btn-close-dashboard')?.addEventListener('click', () => {
            this.hide();
        });

        // Batch start button
        this.container.querySelector('#btn-batch-start')?.addEventListener('click', () => {
            this.batchStartSelected();
        });

        // Select all button
        this.container.querySelector('#btn-select-all')?.addEventListener('click', () => {
            this.toggleSelectAll();
        });

        // Delegate click events for task cards
        this.container.addEventListener('click', (e) => {
            const taskCard = e.target.closest('.parallel-task-card');
            if (taskCard) {
                const taskId = taskCard.dataset.taskId;

                // Handle checkbox click
                if (e.target.classList.contains('task-checkbox')) {
                    this.toggleTaskSelection(taskId);
                    return;
                }

                // Handle action buttons
                if (e.target.closest('.btn-cancel')) {
                    this.cancelTask(taskId);
                    return;
                }

                if (e.target.closest('.btn-unqueue')) {
                    this.unqueueTask(taskId);
                    return;
                }

                if (e.target.closest('.btn-priority')) {
                    const newPriority = e.target.dataset.priority;
                    this.updateTaskPriority(taskId, newPriority);
                    return;
                }
            }
        });

        // Setup drag and drop for queue reordering
        this.setupDragAndDrop();
    }

    /**
     * Setup drag and drop for queue reordering
     */
    setupDragAndDrop() {
        const queueList = this.container?.querySelector('#queue-list');
        if (!queueList) return;

        queueList.addEventListener('dragstart', (e) => {
            const taskCard = e.target.closest('.parallel-task-card');
            if (taskCard) {
                draggedTaskId = taskCard.dataset.taskId;
                taskCard.classList.add('dragging');
                e.dataTransfer.effectAllowed = 'move';
                e.dataTransfer.setData('text/plain', draggedTaskId);
            }
        });

        queueList.addEventListener('dragend', (e) => {
            const taskCard = e.target.closest('.parallel-task-card');
            if (taskCard) {
                taskCard.classList.remove('dragging');
                draggedTaskId = null;
            }
            this.container?.querySelector('#queue-drop-hint')?.classList.add('hidden');
        });

        queueList.addEventListener('dragover', (e) => {
            e.preventDefault();
            e.dataTransfer.dropEffect = 'move';

            const dropHint = this.container?.querySelector('#queue-drop-hint');
            dropHint?.classList.remove('hidden');

            // Find the task card being dragged over
            const afterElement = this.getDragAfterElement(queueList, e.clientY);
            const draggingCard = queueList.querySelector('.dragging');

            if (draggingCard) {
                if (afterElement) {
                    queueList.insertBefore(draggingCard, afterElement);
                } else {
                    queueList.appendChild(draggingCard);
                }
            }
        });

        queueList.addEventListener('dragleave', (e) => {
            if (!e.relatedTarget?.closest('#queue-list')) {
                this.container?.querySelector('#queue-drop-hint')?.classList.add('hidden');
            }
        });

        queueList.addEventListener('drop', async (e) => {
            e.preventDefault();
            this.container?.querySelector('#queue-drop-hint')?.classList.add('hidden');

            // Get the new order from the DOM
            const taskCards = queueList.querySelectorAll('.parallel-task-card');
            const newOrder = Array.from(taskCards).map(card => card.dataset.taskId);

            await this.reorderQueue(newOrder);
        });
    }

    /**
     * Get the element to insert after during drag
     */
    getDragAfterElement(container, y) {
        const draggableElements = [...container.querySelectorAll('.parallel-task-card:not(.dragging)')];

        return draggableElements.reduce((closest, child) => {
            const box = child.getBoundingClientRect();
            const offset = y - box.top - box.height / 2;

            if (offset < 0 && offset > closest.offset) {
                return { offset, element: child };
            } else {
                return closest;
            }
        }, { offset: Number.NEGATIVE_INFINITY }).element;
    }

    /**
     * Connect to the parallel status WebSocket
     */
    connectWebSocket() {
        if (parallelSocket && parallelSocket.readyState === WebSocket.OPEN) {
            return;
        }

        const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        const wsUrl = `${protocol}//${window.location.host}/ws/parallel-status`;

        parallelSocket = new WebSocket(wsUrl);

        parallelSocket.onopen = () => {
            console.log('Parallel status WebSocket connected');
            reconnectAttempts = 0;
            this.updateConnectionStatus(true);
            this.requestRefresh();
        };

        parallelSocket.onmessage = (event) => {
            try {
                const message = JSON.parse(event.data);
                this.handleWebSocketMessage(message);
            } catch (error) {
                console.error('Failed to parse parallel status message:', error);
            }
        };

        parallelSocket.onerror = (error) => {
            console.error('Parallel status WebSocket error:', error);
        };

        parallelSocket.onclose = () => {
            console.log('Parallel status WebSocket closed');
            this.updateConnectionStatus(false);
            this.attemptReconnect();
        };
    }

    /**
     * Attempt to reconnect after connection loss
     */
    attemptReconnect() {
        if (reconnectAttempts >= MAX_RECONNECT_ATTEMPTS) {
            console.log('Max reconnect attempts reached for parallel status WebSocket');
            return;
        }

        reconnectAttempts++;
        console.log(`Attempting to reconnect parallel status WebSocket (${reconnectAttempts}/${MAX_RECONNECT_ATTEMPTS})`);

        setTimeout(() => {
            this.connectWebSocket();
        }, RECONNECT_DELAY_MS);
    }

    /**
     * Request a refresh from the WebSocket
     */
    requestRefresh() {
        if (parallelSocket && parallelSocket.readyState === WebSocket.OPEN) {
            parallelSocket.send(JSON.stringify({ type: 'refresh' }));
        }
    }

    /**
     * Handle incoming WebSocket messages
     */
    handleWebSocketMessage(message) {
        const { type, ...data } = message;

        switch (type) {
            case 'initial_state':
            case 'refresh_response':
                runningTasks = data.running_tasks || [];
                aggregateProgress = data.aggregate_progress || {};
                this.updateRunningTasks();
                this.updateAggregateStats();
                break;

            case 'task_started':
                this.handleTaskStarted(data);
                break;

            case 'task_completed':
                this.handleTaskCompleted(data);
                break;

            case 'task_failed':
                this.handleTaskFailed(data);
                break;

            case 'phase_changed':
                this.handlePhaseChanged(data);
                break;

            case 'subtask_progress':
                this.handleSubtaskProgress(data);
                break;

            case 'queue_changed':
                this.handleQueueChanged(data);
                break;

            default:
                console.log('Unknown parallel status message type:', type);
        }

        this.updateLastUpdate();
    }

    /**
     * Handle task started event
     */
    handleTaskStarted(data) {
        const task = data.task || data;
        const existingIndex = runningTasks.findIndex(t => t.task_id === task.task_id);

        if (existingIndex === -1) {
            runningTasks.push(task);
        } else {
            runningTasks[existingIndex] = task;
        }

        // Remove from queued tasks if present
        queuedTasks = queuedTasks.filter(t => t.task_id !== task.task_id);

        this.updateRunningTasks();
        this.updateQueuedTasks();
        this.updateAggregateStats();

        // Dispatch event for other components
        window.dispatchEvent(new CustomEvent('parallel:task-started', { detail: task }));
    }

    /**
     * Handle task completed event
     */
    handleTaskCompleted(data) {
        runningTasks = runningTasks.filter(t => t.task_id !== data.task_id);
        this.updateRunningTasks();
        this.updateAggregateStats();

        // Dispatch event for other components
        window.dispatchEvent(new CustomEvent('parallel:task-completed', { detail: data }));
    }

    /**
     * Handle task failed event
     */
    handleTaskFailed(data) {
        runningTasks = runningTasks.filter(t => t.task_id !== data.task_id);
        this.updateRunningTasks();
        this.updateAggregateStats();

        // Dispatch event for other components
        window.dispatchEvent(new CustomEvent('parallel:task-failed', { detail: data }));
    }

    /**
     * Handle phase changed event
     */
    handlePhaseChanged(data) {
        const task = runningTasks.find(t => t.task_id === data.task_id);
        if (task) {
            task.current_phase = data.phase;
            task.phase_status = data.status;
            this.updateTaskCard(data.task_id);
        }
    }

    /**
     * Handle subtask progress event
     */
    handleSubtaskProgress(data) {
        const task = runningTasks.find(t => t.task_id === data.task_id);
        if (task) {
            task.subtask_progress = data.progress;
            task.current_subtask = data.current_subtask;
            this.updateTaskCard(data.task_id);
        }
    }

    /**
     * Handle queue changed event
     */
    handleQueueChanged(data) {
        queuedTasks = data.queued_tasks || [];
        isPaused = data.paused || false;
        this.updateQueuedTasks();
        this.updatePauseButton();
        this.updateAggregateStats();
    }

    /**
     * Refresh data from the API
     */
    async refreshData() {
        try {
            // Get queue status and estimates in parallel
            const [queueStatus, estimates] = await Promise.all([
                API.queue.detailed(),
                API.queue.estimates()
            ]);

            queuedTasks = queueStatus.queued_tasks || [];
            runningTasks = queueStatus.running_tasks || [];
            isPaused = queueStatus.paused || false;
            queueEstimates = estimates || {};

            // Request WebSocket refresh for running tasks
            this.requestRefresh();

            this.updateRunningTasks();
            this.updateQueuedTasks();
            this.updatePauseButton();
            this.updateAggregateStats();
            this.updateEstimates();
        } catch (error) {
            console.error('Failed to refresh parallel dashboard data:', error);
        }
    }

    /**
     * Update estimated completion times display
     */
    updateEstimates() {
        const summaryEl = this.container?.querySelector('#estimate-all-complete');
        if (!summaryEl) return;

        if (queueEstimates.all_complete_at) {
            const completeAt = new Date(queueEstimates.all_complete_at);
            const totalSeconds = queueEstimates.total_estimated_seconds || 0;
            summaryEl.textContent = `${completeAt.toLocaleTimeString()} (${formatDuration(totalSeconds)})`;
        } else if (runningTasks.length === 0 && queuedTasks.length === 0) {
            summaryEl.textContent = 'No tasks pending';
        } else {
            summaryEl.textContent = '--';
        }
    }

    /**
     * Update the running tasks display
     */
    updateRunningTasks() {
        const container = this.container?.querySelector('#running-tasks-list');
        const countEl = this.container?.querySelector('#running-count');

        if (!container) return;

        if (runningTasks.length === 0) {
            container.innerHTML = '<div class="empty-state">No tasks currently running</div>';
        } else {
            container.innerHTML = runningTasks.map(task => this.renderRunningTaskCard(task)).join('');
        }

        if (countEl) {
            countEl.textContent = runningTasks.length;
        }

        // Update stat box
        const statRunning = this.container?.querySelector('#stat-running');
        if (statRunning) {
            statRunning.textContent = runningTasks.length;
        }
    }

    /**
     * Update the queued tasks display
     */
    updateQueuedTasks() {
        const container = this.container?.querySelector('#queue-list');
        const countEl = this.container?.querySelector('#queue-count');

        if (!container) return;

        if (queuedTasks.length === 0) {
            container.innerHTML = '<div class="empty-state">No tasks in queue</div>';
        } else {
            container.innerHTML = queuedTasks.map(task => this.renderQueuedTaskCard(task)).join('');
        }

        if (countEl) {
            countEl.textContent = queuedTasks.length;
        }

        // Update stat box
        const statQueued = this.container?.querySelector('#stat-queued');
        if (statQueued) {
            statQueued.textContent = queuedTasks.length;
        }

        // Update batch start button state
        this.updateBatchStartButton();
    }

    /**
     * Update a single task card
     */
    updateTaskCard(taskId) {
        const card = this.container?.querySelector(`.parallel-task-card[data-task-id="${taskId}"]`);
        if (!card) return;

        const task = runningTasks.find(t => t.task_id === taskId);
        if (!task) return;

        // Update progress bar
        const progressFill = card.querySelector('.progress-fill');
        const progressText = card.querySelector('.progress-text');

        if (progressFill && task.subtask_progress) {
            const percentage = task.subtask_progress.percentage || 0;
            progressFill.style.width = `${percentage}%`;
        }

        if (progressText && task.subtask_progress) {
            progressText.textContent = `${task.subtask_progress.completed || 0}/${task.subtask_progress.total || 0}`;
        }

        // Update phase badge
        const phaseBadge = card.querySelector('.phase-badge');
        if (phaseBadge && task.current_phase) {
            phaseBadge.textContent = task.current_phase;
            phaseBadge.className = `phase-badge phase-${task.current_phase}`;
        }
    }

    /**
     * Render a running task card
     */
    renderRunningTaskCard(task) {
        const progress = task.subtask_progress || { completed: 0, total: 0, percentage: 0 };
        const phase = task.current_phase || 'planning';
        const startedAt = task.started_at ? new Date(task.started_at).toLocaleTimeString() : '--';

        // Get estimate info
        const estimate = queueEstimates.running_tasks?.[task.task_id] || task;
        const remainingSeconds = estimate.remaining_seconds || estimate.estimated_remaining;
        const estimatedCompletion = estimate.estimated_completion;

        let estimateHtml = '';
        if (remainingSeconds > 0) {
            estimateHtml = `<span class="task-estimate" title="Estimated completion: ${estimatedCompletion ? new Date(estimatedCompletion).toLocaleTimeString() : '--'}">~${formatDuration(remainingSeconds)} remaining</span>`;
        }

        return `
            <div class="parallel-task-card running" data-task-id="${task.task_id}">
                <div class="task-card-header">
                    <span class="task-title">${escapeHtml(task.title || task.task_id)}</span>
                    <span class="phase-badge phase-${phase}">${phase}</span>
                </div>
                <div class="task-progress">
                    <div class="progress-bar">
                        <div class="progress-fill" style="width: ${progress.percentage}%"></div>
                    </div>
                    <span class="progress-text">${progress.completed}/${progress.total}</span>
                </div>
                <div class="task-card-footer">
                    <span class="task-meta">Started: ${startedAt}</span>
                    ${estimateHtml}
                    <div class="task-actions">
                        <button class="btn-small btn-cancel" title="Cancel task">✕ Cancel</button>
                    </div>
                </div>
            </div>
        `;
    }

    /**
     * Render a queued task card
     */
    renderQueuedTaskCard(task) {
        const priority = task.priority || 'normal';
        const position = task.position || '?';
        const isSelected = this.selectedTasks.has(task.task_id);
        const queuedAt = task.queued_at ? new Date(task.queued_at).toLocaleTimeString() : '--';

        // Get estimate info
        const estimate = queueEstimates.queued_tasks?.[task.task_id] || task;
        const estimatedDuration = estimate.estimated_duration || task.estimated_duration;
        const estimatedStart = estimate.estimated_start;
        const waitTime = estimate.wait_time_seconds;

        let estimateHtml = '';
        if (estimatedDuration) {
            const durationStr = formatDuration(estimatedDuration);
            let startStr = '';
            if (estimatedStart) {
                const startTime = new Date(estimatedStart);
                if (waitTime < 60) {
                    startStr = 'Starting soon';
                } else {
                    startStr = `Starts ~${startTime.toLocaleTimeString()}`;
                }
            }
            estimateHtml = `<span class="task-estimate" title="Estimated duration: ${durationStr}">${startStr ? startStr + ' · ' : ''}~${durationStr}</span>`;
        }

        return `
            <div class="parallel-task-card queued ${isSelected ? 'selected' : ''}"
                 data-task-id="${task.task_id}"
                 draggable="true">
                <div class="task-card-header">
                    <input type="checkbox" class="task-checkbox" ${isSelected ? 'checked' : ''}>
                    <span class="queue-position">#${position}</span>
                    <span class="task-title">${escapeHtml(task.title || task.task_id)}</span>
                    <span class="priority-badge priority-${priority}">${priority}</span>
                </div>
                <div class="task-card-footer">
                    <span class="task-meta">Queued: ${queuedAt}</span>
                    ${estimateHtml}
                    <div class="task-actions">
                        <div class="priority-selector">
                            <button class="btn-small btn-priority ${priority === 'high' ? 'active' : ''}" data-priority="high" title="High priority">↑</button>
                            <button class="btn-small btn-priority ${priority === 'normal' ? 'active' : ''}" data-priority="normal" title="Normal priority">—</button>
                            <button class="btn-small btn-priority ${priority === 'low' ? 'active' : ''}" data-priority="low" title="Low priority">↓</button>
                        </div>
                        <button class="btn-small btn-unqueue" title="Remove from queue">✕</button>
                    </div>
                </div>
            </div>
        `;
    }

    /**
     * Update aggregate statistics
     */
    updateAggregateStats() {
        const stats = aggregateProgress || {};

        const statCompleted = this.container?.querySelector('#stat-completed');
        const statFailed = this.container?.querySelector('#stat-failed');

        if (statCompleted) {
            statCompleted.textContent = stats.completed_today || 0;
        }
        if (statFailed) {
            statFailed.textContent = stats.failed_today || 0;
        }
    }

    /**
     * Update connection status indicator
     */
    updateConnectionStatus(connected) {
        const statusEl = this.container?.querySelector('#ws-connection-status');
        if (!statusEl) return;

        const dot = statusEl.querySelector('.status-dot');
        const text = statusEl.querySelector('.status-text');

        if (connected) {
            dot?.classList.remove('disconnected');
            dot?.classList.add('connected');
            if (text) text.textContent = 'Connected';
        } else {
            dot?.classList.remove('connected');
            dot?.classList.add('disconnected');
            if (text) text.textContent = 'Disconnected';
        }
    }

    /**
     * Update last update timestamp
     */
    updateLastUpdate() {
        const el = this.container?.querySelector('#last-update');
        if (el) {
            el.textContent = `Last update: ${new Date().toLocaleTimeString()}`;
        }
    }

    /**
     * Update pause button state
     */
    updatePauseButton() {
        const btn = this.container?.querySelector('.btn-pause-queue');
        if (!btn) return;

        const icon = btn.querySelector('.pause-icon');
        const text = btn.querySelector('.pause-text');

        if (isPaused) {
            if (icon) icon.textContent = '▶';
            if (text) text.textContent = 'Resume Queue';
            btn.classList.add('paused');
        } else {
            if (icon) icon.textContent = '⏸';
            if (text) text.textContent = 'Pause Queue';
            btn.classList.remove('paused');
        }
    }

    /**
     * Update batch start button state
     */
    updateBatchStartButton() {
        const btn = this.container?.querySelector('#btn-batch-start');
        if (btn) {
            btn.disabled = this.selectedTasks.size === 0;
        }
    }

    /**
     * Toggle task selection
     */
    toggleTaskSelection(taskId) {
        if (this.selectedTasks.has(taskId)) {
            this.selectedTasks.delete(taskId);
        } else {
            this.selectedTasks.add(taskId);
        }

        // Update card visual state
        const card = this.container?.querySelector(`.parallel-task-card[data-task-id="${taskId}"]`);
        if (card) {
            card.classList.toggle('selected', this.selectedTasks.has(taskId));
        }

        this.updateBatchStartButton();
    }

    /**
     * Toggle select all queued tasks
     */
    toggleSelectAll() {
        const allSelected = queuedTasks.every(t => this.selectedTasks.has(t.task_id));

        if (allSelected) {
            this.selectedTasks.clear();
        } else {
            queuedTasks.forEach(t => this.selectedTasks.add(t.task_id));
        }

        this.updateQueuedTasks();
    }

    /**
     * Toggle queue pause state
     */
    async toggleQueuePause() {
        try {
            if (isPaused) {
                await fetch('/api/queue/resume', { method: 'POST' });
            } else {
                await fetch('/api/queue/pause', { method: 'POST' });
            }
            isPaused = !isPaused;
            this.updatePauseButton();
        } catch (error) {
            console.error('Failed to toggle queue pause:', error);
        }
    }

    /**
     * Batch start selected tasks
     */
    async batchStartSelected() {
        if (this.selectedTasks.size === 0) return;

        const tasks = Array.from(this.selectedTasks).map(taskId => ({
            task_id: taskId,
            priority: 'normal'
        }));

        try {
            const response = await fetch('/api/queue/batch', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ tasks })
            });

            if (!response.ok) {
                throw new Error('Failed to batch queue tasks');
            }

            this.selectedTasks.clear();
            await this.refreshData();
        } catch (error) {
            console.error('Failed to batch start tasks:', error);
            alert('Failed to batch start tasks: ' + error.message);
        }
    }

    /**
     * Reorder the queue
     */
    async reorderQueue(newOrder) {
        try {
            const response = await fetch('/api/queue/reorder', {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ task_order: newOrder })
            });

            if (!response.ok) {
                throw new Error('Failed to reorder queue');
            }

            await this.refreshData();
        } catch (error) {
            console.error('Failed to reorder queue:', error);
            // Refresh to restore original order
            await this.refreshData();
        }
    }

    /**
     * Cancel a running task
     */
    async cancelTask(taskId) {
        if (!confirm(`Are you sure you want to cancel task ${taskId}?`)) {
            return;
        }

        try {
            await API.tasks.stop(taskId);
            await this.refreshData();
        } catch (error) {
            console.error('Failed to cancel task:', error);
            alert('Failed to cancel task: ' + error.message);
        }
    }

    /**
     * Remove a task from the queue
     */
    async unqueueTask(taskId) {
        try {
            await API.tasks.unqueue(taskId);
            await this.refreshData();
        } catch (error) {
            console.error('Failed to unqueue task:', error);
            alert('Failed to remove task from queue: ' + error.message);
        }
    }

    /**
     * Update task priority
     */
    async updateTaskPriority(taskId, priority) {
        try {
            const response = await fetch(`/api/tasks/${taskId}/priority`, {
                method: 'PATCH',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ priority })
            });

            if (!response.ok) {
                throw new Error('Failed to update priority');
            }

            await this.refreshData();
        } catch (error) {
            console.error('Failed to update task priority:', error);
        }
    }

    /**
     * Disconnect WebSocket
     */
    disconnect() {
        if (parallelSocket) {
            parallelSocket.close();
            parallelSocket = null;
        }
    }
}

/**
 * Escape HTML to prevent XSS
 */
function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

/**
 * Format duration in seconds to human-readable string
 */
function formatDuration(seconds) {
    if (!seconds || seconds <= 0) return '--';

    if (seconds < 60) {
        return `${Math.round(seconds)}s`;
    } else if (seconds < 3600) {
        const minutes = Math.floor(seconds / 60);
        const secs = Math.round(seconds % 60);
        return secs > 0 ? `${minutes}m ${secs}s` : `${minutes}m`;
    } else {
        const hours = Math.floor(seconds / 3600);
        const minutes = Math.floor((seconds % 3600) / 60);
        return minutes > 0 ? `${hours}h ${minutes}m` : `${hours}h`;
    }
}

// Initialize on DOM ready
let dashboardInstance = null;

export function initParallelDashboard(containerId = 'parallel-dashboard-container') {
    dashboardInstance = new ParallelDashboard(containerId);
    return dashboardInstance;
}

export function getParallelDashboard() {
    return dashboardInstance;
}

// Global accessor for workspace.js
window.initParallelDashboard = initParallelDashboard;
window.getParallelDashboard = getParallelDashboard;
