/**
 * Kanban WebSocket Sync
 * Handles real-time synchronization of kanban board events across all connected clients.
 */

let kanbanSocket = null;
let reconnectAttempts = 0;
const MAX_RECONNECT_ATTEMPTS = 5;
const RECONNECT_DELAY_MS = 3000;

/**
 * Initialize the kanban WebSocket connection
 */
export function initKanbanSync() {
    connectToKanbanSocket();
}

/**
 * Connect to the kanban WebSocket endpoint
 */
function connectToKanbanSocket() {
    if (kanbanSocket && kanbanSocket.readyState === WebSocket.OPEN) {
        console.log('Kanban WebSocket already connected');
        return;
    }

    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${protocol}//${window.location.host}/ws/kanban`;

    kanbanSocket = new WebSocket(wsUrl);

    kanbanSocket.onopen = () => {
        console.log('Kanban WebSocket connected');
        reconnectAttempts = 0;
    };

    kanbanSocket.onmessage = (event) => {
        try {
            const message = JSON.parse(event.data);
            handleKanbanEvent(message);
        } catch (error) {
            console.error('Failed to parse kanban WebSocket message:', error);
        }
    };

    kanbanSocket.onerror = (error) => {
        console.error('Kanban WebSocket error:', error);
    };

    kanbanSocket.onclose = () => {
        console.log('Kanban WebSocket closed');
        attemptReconnect();
    };
}

/**
 * Handle incoming kanban events
 * @param {Object} message - The WebSocket message
 */
function handleKanbanEvent(message) {
    const { type, data } = message;

    switch (type) {
        case 'task_archived':
            console.log('Task archived:', data.task_id);
            // Dispatch task-updated event to refresh the kanban board
            window.dispatchEvent(new Event('task-updated'));
            break;

        case 'task_unarchived':
            console.log('Task unarchived:', data.task_id);
            // Dispatch task-updated event to refresh the kanban board
            window.dispatchEvent(new Event('task-updated'));
            break;

        default:
            console.log('Unknown kanban event:', type);
    }
}

/**
 * Attempt to reconnect after connection loss
 */
function attemptReconnect() {
    if (reconnectAttempts >= MAX_RECONNECT_ATTEMPTS) {
        console.log('Max reconnect attempts reached for kanban WebSocket');
        return;
    }

    reconnectAttempts++;
    console.log(`Attempting to reconnect kanban WebSocket (attempt ${reconnectAttempts}/${MAX_RECONNECT_ATTEMPTS})`);

    setTimeout(() => {
        connectToKanbanSocket();
    }, RECONNECT_DELAY_MS);
}

/**
 * Disconnect from the kanban WebSocket
 */
export function disconnectKanbanSync() {
    if (kanbanSocket) {
        kanbanSocket.close();
        kanbanSocket = null;
    }
}

// Initialize when DOM is ready
window.addEventListener('DOMContentLoaded', () => {
    initKanbanSync();
});

// Clean up on page unload
window.addEventListener('beforeunload', () => {
    disconnectKanbanSync();
});
