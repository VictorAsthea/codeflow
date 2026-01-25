import { updateTaskCard } from './kanban.js';

let activeConnections = {};
let reconnectAttempts = {};
let pendingUpdates = {};
let updateTimers = {};

// Configuration for reconnection
const RECONNECT_BASE_DELAY = 1000; // 1 second
const RECONNECT_MAX_DELAY = 30000; // 30 seconds
const RECONNECT_MAX_ATTEMPTS = 10;

// Configuration for debouncing
const UPDATE_DEBOUNCE_MS = 100; // Debounce rapid updates

// Debug mode - set to true to enable verbose logging
const DEBUG_WEBSOCKET = true;

/**
 * Debug log helper - only logs if DEBUG_WEBSOCKET is true
 */
function debugLog(...args) {
    if (DEBUG_WEBSOCKET) {
        console.log('[WebSocket Debug]', ...args);
    }
}

export function connectToTaskLogs(taskId) {
    if (activeConnections[taskId]) {
        debugLog(`Already connected to task ${taskId}`);
        return activeConnections[taskId];
    }

    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${protocol}//${window.location.host}/ws/logs/${taskId}`;

    debugLog(`Connecting to WebSocket: ${wsUrl}`);
    const ws = new WebSocket(wsUrl);

    ws.onopen = () => {
        console.log(`WebSocket connected for task ${taskId}`);
        // Reset reconnect attempts on successful connection
        reconnectAttempts[taskId] = 0;
        debugLog(`Connection established, reconnect attempts reset for task ${taskId}`);
    };

    ws.onmessage = (event) => {
        const message = event.data;

        // Try to parse as JSON for enriched messages
        try {
            const data = JSON.parse(message);

            // Handle subtask:started - update specific card with in_progress status
            if (data.type === 'subtask:started' && data.task_id && data.subtask) {
                console.log('[WebSocket] Subtask started:', data.subtask.title);
                handleSubtaskStarted(data.task_id, data.subtask);
            }
            // Handle subtask:completed - update specific card with completed status
            else if (data.type === 'subtask:completed' && data.task_id && data.subtask) {
                console.log('[WebSocket] Subtask completed:', data.subtask.title);
                handleSubtaskCompleted(data.task_id, data.subtask);
            }
            // Handle other subtask events - trigger task refresh for now
            else if (data.type && data.type.startsWith('subtask:')) {
                console.log('[WebSocket] Subtask event:', data.type);
                window.dispatchEvent(new Event('task-updated'));
            }

            // Handle phase:completed - update phase steps on the card
            if (data.type === 'phase:completed' && data.task_id && data.phase) {
                console.log('[WebSocket] Phase completed:', data.phase);
                handlePhaseCompleted(data.task_id, data.phase, data.result);
            }
            // Handle other phase events - trigger task refresh for now
            else if (data.type && data.type.startsWith('phase:')) {
                console.log('[WebSocket] Phase event:', data.type);
                window.dispatchEvent(new Event('task-updated'));
            }

            // Handle task status changes
            if (data.type === 'task:status_changed' || data.type === 'task:failed') {
                console.log('[WebSocket] Task status event:', data.type);
                window.dispatchEvent(new Event('task-updated'));
            }

            // Pass log content to appendLog
            if (data.type === 'log' && data.content) {
                appendLog(taskId, data.content);
            } else if (data.raw) {
                appendLog(taskId, data.raw);
            }
        } catch (e) {
            // Plain text message
            appendLog(taskId, message);
        }
    };

    ws.onerror = (error) => {
        console.error(`WebSocket error for task ${taskId}:`, error);
        debugLog(`WebSocket error details:`, error);
    };

    ws.onclose = (event) => {
        console.log(`WebSocket closed for task ${taskId}`);
        debugLog(`Close event - code: ${event.code}, reason: ${event.reason}, wasClean: ${event.wasClean}`);
        delete activeConnections[taskId];

        // Attempt reconnection if it wasn't a clean close and we haven't exceeded max attempts
        if (!event.wasClean && shouldReconnect(taskId)) {
            scheduleReconnect(taskId);
        }
    };

    activeConnections[taskId] = ws;
    return ws;
}

/**
 * Check if we should attempt to reconnect for a given task
 * @param {string} taskId - The task ID
 * @returns {boolean} Whether to attempt reconnection
 */
function shouldReconnect(taskId) {
    const attempts = reconnectAttempts[taskId] || 0;
    const shouldTry = attempts < RECONNECT_MAX_ATTEMPTS;
    debugLog(`shouldReconnect(${taskId}): attempts=${attempts}, max=${RECONNECT_MAX_ATTEMPTS}, result=${shouldTry}`);
    return shouldTry;
}

/**
 * Schedule a reconnection attempt with exponential backoff
 * @param {string} taskId - The task ID to reconnect
 */
function scheduleReconnect(taskId) {
    const attempts = reconnectAttempts[taskId] || 0;
    const delay = Math.min(RECONNECT_BASE_DELAY * Math.pow(2, attempts), RECONNECT_MAX_DELAY);

    reconnectAttempts[taskId] = attempts + 1;

    console.log(`[WebSocket] Scheduling reconnect for task ${taskId} in ${delay}ms (attempt ${attempts + 1}/${RECONNECT_MAX_ATTEMPTS})`);
    debugLog(`Reconnect scheduled with exponential backoff: ${delay}ms`);

    setTimeout(() => {
        // Only reconnect if we're not already connected
        if (!activeConnections[taskId]) {
            debugLog(`Executing scheduled reconnect for task ${taskId}`);
            connectToTaskLogs(taskId);
        } else {
            debugLog(`Skipping reconnect - already connected to task ${taskId}`);
        }
    }, delay);
}

export function disconnectFromTaskLogs(taskId) {
    const ws = activeConnections[taskId];
    if (ws) {
        ws.close();
        delete activeConnections[taskId];
        // Clean up reconnect state - we don't want to auto-reconnect after manual disconnect
        delete reconnectAttempts[taskId];
        // Clear any pending updates
        delete pendingUpdates[taskId];
        if (updateTimers[taskId]) {
            clearTimeout(updateTimers[taskId]);
            delete updateTimers[taskId];
        }
        console.log(`Disconnected from task ${taskId}`);
        debugLog(`Cleaned up all state for task ${taskId}`);
    }
}

export function disconnectAll() {
    Object.keys(activeConnections).forEach(taskId => {
        disconnectFromTaskLogs(taskId);
    });
}

function appendLog(taskId, message) {
    const logsDisplay = document.getElementById('logs-display');

    if (!logsDisplay) {
        console.log(`[${taskId}] ${message}`);
        return;
    }

    const currentContent = logsDisplay.textContent;

    if (currentContent === 'No logs yet') {
        logsDisplay.textContent = message;
    } else {
        logsDisplay.textContent = currentContent + '\n' + message;
    }

    logsDisplay.scrollTop = logsDisplay.scrollHeight;
}

/**
 * Debounced update scheduler - queues updates and processes them after a delay
 * This prevents race conditions when multiple updates arrive rapidly
 * @param {string} taskId - The task ID
 * @param {Object} updateData - The update data to apply
 */
function scheduleCardUpdate(taskId, updateData) {
    // Initialize pending updates for this task if needed
    if (!pendingUpdates[taskId]) {
        pendingUpdates[taskId] = [];
    }

    // Queue this update
    pendingUpdates[taskId].push(updateData);
    debugLog(`Queued update for task ${taskId}, queue size: ${pendingUpdates[taskId].length}`);

    // Clear existing timer and set a new one
    if (updateTimers[taskId]) {
        clearTimeout(updateTimers[taskId]);
    }

    updateTimers[taskId] = setTimeout(() => {
        processQueuedUpdates(taskId);
    }, UPDATE_DEBOUNCE_MS);
}

/**
 * Process all queued updates for a task
 * @param {string} taskId - The task ID
 */
function processQueuedUpdates(taskId) {
    const updates = pendingUpdates[taskId] || [];
    if (updates.length === 0) return;

    debugLog(`Processing ${updates.length} queued updates for task ${taskId}`);

    // Clear the queue
    pendingUpdates[taskId] = [];
    delete updateTimers[taskId];

    // Apply each update in order
    updates.forEach(updateData => {
        updateTaskCard(taskId, updateData);
    });
}

/**
 * Handle case where card doesn't exist in DOM
 * This can happen if a task was created by another user or the page is out of sync
 * @param {string} taskId - The task ID
 * @param {string} eventType - The type of event that triggered this
 */
function handleMissingCard(taskId, eventType) {
    console.warn(`[WebSocket] Card not found for task ${taskId} during ${eventType} - triggering full refresh`);
    debugLog(`Missing card detected, dispatching task-updated event to refresh kanban`);

    // Dispatch event to trigger a full kanban reload
    window.dispatchEvent(new Event('task-updated'));
}

/**
 * Handle subtask:started WebSocket event
 * Updates the kanban card to show the subtask as in_progress
 * @param {string} taskId - The task ID
 * @param {Object} subtask - The subtask data from the event
 */
function handleSubtaskStarted(taskId, subtask) {
    debugLog(`handleSubtaskStarted called for task ${taskId}, subtask:`, subtask);

    const card = document.querySelector(`.task-card[data-task-id="${taskId}"]`);
    if (!card) {
        handleMissingCard(taskId, 'subtask:started');
        return;
    }

    // Immediate visual feedback: update the specific subtask dot
    const dots = card.querySelectorAll('.subtask-dot');
    if (dots.length > 0 && subtask.order) {
        const dotIndex = subtask.order - 1;
        if (dots[dotIndex]) {
            dots[dotIndex].className = 'subtask-dot in_progress';
            debugLog(`Updated dot ${dotIndex} to in_progress for task ${taskId}`);
        }
    }

    // Schedule debounced update for full consistency
    scheduleCardUpdate(taskId, {
        _subtaskUpdate: {
            order: subtask.order,
            status: 'in_progress',
            subtask: subtask
        }
    });
}

/**
 * Handle subtask:completed WebSocket event
 * Updates the kanban card to show the subtask as completed and recalculates progress
 * @param {string} taskId - The task ID
 * @param {Object} subtask - The subtask data from the event
 */
function handleSubtaskCompleted(taskId, subtask) {
    debugLog(`handleSubtaskCompleted called for task ${taskId}, subtask:`, subtask);

    const card = document.querySelector(`.task-card[data-task-id="${taskId}"]`);
    if (!card) {
        handleMissingCard(taskId, 'subtask:completed');
        return;
    }

    // Immediate visual feedback: update the specific subtask dot to completed
    const dots = card.querySelectorAll('.subtask-dot');
    if (dots.length > 0 && subtask.order) {
        const dotIndex = subtask.order - 1;
        if (dots[dotIndex]) {
            dots[dotIndex].className = 'subtask-dot completed';
            debugLog(`Updated dot ${dotIndex} to completed for task ${taskId}`);
        }
    }

    // Schedule debounced update for full consistency
    // This will also recalculate and update the progress bar
    scheduleCardUpdate(taskId, {
        _subtaskUpdate: {
            order: subtask.order,
            status: 'completed',
            subtask: subtask
        }
    });
}

/**
 * Handle phase:completed WebSocket event
 * Updates the kanban card's phase steps indicator when a phase completes
 * @param {string} taskId - The task ID
 * @param {string} phaseName - The phase that completed ("planning", "coding", or "validation")
 * @param {Object} result - Optional result data (for validation phase)
 */
function handlePhaseCompleted(taskId, phaseName, result) {
    debugLog(`handlePhaseCompleted called for task ${taskId}, phase: ${phaseName}, result:`, result);

    const card = document.querySelector(`.task-card[data-task-id="${taskId}"]`);
    if (!card) {
        handleMissingCard(taskId, 'phase:completed');
        return;
    }

    // Map backend phase names to the phases object structure
    const phaseKey = phaseName; // "planning", "coding", "validation"

    // Immediate visual feedback: update the specific phase step to completed
    const phaseSteps = card.querySelectorAll('.phase-step');
    const phaseIndexMap = { planning: 0, coding: 1, validation: 2 };
    const phaseIndex = phaseIndexMap[phaseKey];

    if (phaseSteps.length > 0 && phaseIndex !== undefined) {
        const phaseStep = phaseSteps[phaseIndex];
        if (phaseStep) {
            // Update the class to completed status
            phaseStep.className = `phase-step completed`;
            // Update the icon to checkmark
            const stepText = phaseStep.textContent.trim();
            const labelMatch = stepText.match(/[○●✓✗]\s*(\w+)/);
            if (labelMatch) {
                phaseStep.innerHTML = `✓ ${labelMatch[1]}`;
            }
            debugLog(`Updated phase step ${phaseKey} to completed for task ${taskId}`);
        }
    }

    // Schedule debounced update for full consistency
    scheduleCardUpdate(taskId, {
        _phaseUpdate: {
            phase: phaseKey,
            status: 'completed',
            result: result
        }
    });

    // If validation phase completed, the task might move to ai_review or human_review
    // Trigger a full refresh to handle potential column changes
    if (phaseName === 'validation') {
        debugLog(`Validation phase completed for task ${taskId}, triggering full refresh for column change`);
        window.dispatchEvent(new Event('task-updated'));
    }
}

window.addEventListener('open-task-modal', (e) => {
    const taskId = e.detail?.taskId;

    if (!taskId || taskId.length < 3) {
        console.log('Invalid task ID, skipping WebSocket connection');
        return;
    }

    setTimeout(() => {
        connectToTaskLogs(taskId);
    }, 500);
});

window.addEventListener('beforeunload', () => {
    disconnectAll();
});

const taskModal = document.getElementById('task-modal');
if (taskModal) {
    const observer = new MutationObserver((mutations) => {
        mutations.forEach((mutation) => {
            if (mutation.attributeName === 'class') {
                const isHidden = taskModal.classList.contains('hidden');

                if (isHidden) {
                    disconnectAll();
                }
            }
        });
    });

    observer.observe(taskModal, { attributes: true });
}
