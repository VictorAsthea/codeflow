const API_BASE = '/api';

async function fetchJSON(url, options = {}) {
    const response = await fetch(url, {
        ...options,
        headers: {
            'Content-Type': 'application/json',
            ...options.headers,
        },
    });

    if (!response.ok) {
        const error = await response.json().catch(() => ({ detail: 'Unknown error' }));
        throw new Error(error.detail || `HTTP ${response.status}`);
    }

    return response.json();
}

export const API = {
    tasks: {
        list: () => fetchJSON(`${API_BASE}/tasks`),

        get: (id) => fetchJSON(`${API_BASE}/tasks/${id}`),

        create: (data) => fetchJSON(`${API_BASE}/tasks`, {
            method: 'POST',
            body: JSON.stringify(data),
        }),

        update: (id, data) => fetchJSON(`${API_BASE}/tasks/${id}`, {
            method: 'PATCH',
            body: JSON.stringify(data),
        }),

        delete: (id) => fetchJSON(`${API_BASE}/tasks/${id}`, {
            method: 'DELETE',
        }),

        start: (id) => fetchJSON(`${API_BASE}/tasks/${id}/start`, {
            method: 'POST',
        }),

        stop: (id) => fetchJSON(`${API_BASE}/tasks/${id}/stop`, {
            method: 'POST',
        }),

        resume: (id) => fetchJSON(`${API_BASE}/tasks/${id}/resume`, {
            method: 'POST',
        }),

        changeStatus: (id, status) => fetchJSON(`${API_BASE}/tasks/${id}/status`, {
            method: 'PATCH',
            body: JSON.stringify({ status }),
        }),

        updatePhase: (id, phaseName, config) => fetchJSON(`${API_BASE}/tasks/${id}/phases/${phaseName}`, {
            method: 'PATCH',
            body: JSON.stringify(config),
        }),

        retryPhase: (id, phaseName) => fetchJSON(`${API_BASE}/tasks/${id}/phases/${phaseName}/retry`, {
            method: 'POST',
        }),

        createPR: (id) => fetchJSON(`${API_BASE}/tasks/${id}/create-pr`, {
            method: 'POST',
        }),
    },

    settings: {
        get: () => fetchJSON(`${API_BASE}/settings`),

        update: (data) => fetchJSON(`${API_BASE}/settings`, {
            method: 'PATCH',
            body: JSON.stringify(data),
        }),
    },

    git: {
        syncMain: () => fetchJSON(`${API_BASE}/sync-main`, {
            method: 'POST',
        }),
    },
};
