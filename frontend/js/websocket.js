let activeConnections = {};

export function connectToTaskLogs(taskId) {
    if (activeConnections[taskId]) {
        console.log(`Already connected to task ${taskId}`);
        return activeConnections[taskId];
    }

    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${protocol}//${window.location.host}/ws/logs/${taskId}`;

    const ws = new WebSocket(wsUrl);

    ws.onopen = () => {
        console.log(`WebSocket connected for task ${taskId}`);
    };

    ws.onmessage = (event) => {
        const message = event.data;

        // Try to parse as JSON for enriched messages
        try {
            const data = JSON.parse(message);

            // Handle subtask events - trigger task refresh
            if (data.type && data.type.startsWith('subtask:')) {
                console.log('[WebSocket] Subtask event:', data.type);
                window.dispatchEvent(new Event('task-updated'));
            }

            // Handle phase events
            if (data.type && data.type.startsWith('phase:')) {
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
    };

    ws.onclose = () => {
        console.log(`WebSocket closed for task ${taskId}`);
        delete activeConnections[taskId];
    };

    activeConnections[taskId] = ws;
    return ws;
}

export function disconnectFromTaskLogs(taskId) {
    const ws = activeConnections[taskId];
    if (ws) {
        ws.close();
        delete activeConnections[taskId];
        console.log(`Disconnected from task ${taskId}`);
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
