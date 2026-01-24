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

        listArchived: () => fetchJSON(`${API_BASE}/tasks?include_archived=true`).then(
            response => ({
                ...response,
                tasks: response.tasks.filter(t => t.archived)
            })
        ),

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

        queue: (id) => fetchJSON(`${API_BASE}/tasks/${id}/queue`, {
            method: 'POST',
        }),

        unqueue: (id) => fetchJSON(`${API_BASE}/tasks/${id}/queue`, {
            method: 'DELETE',
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

        syncPR: (id) => fetchJSON(`${API_BASE}/tasks/${id}/sync-pr`, {
            method: 'POST',
        }),

        checkConflicts: (id) => fetchJSON(`${API_BASE}/tasks/${id}/check-conflicts`),

        getPRReviews: (id) => fetchJSON(`${API_BASE}/tasks/${id}/pr-reviews`),

        fixComments: (id, commentIds) => fetchJSON(`${API_BASE}/tasks/${id}/fix-comments`, {
            method: 'POST',
            body: JSON.stringify({ comment_ids: commentIds }),
        }),

        resolveConflicts: (id) => fetchJSON(`${API_BASE}/tasks/${id}/resolve-conflicts`, {
            method: 'POST',
        }),

        archive: (id) => fetchJSON(`${API_BASE}/tasks/${id}/archive`, {
            method: 'PATCH',
        }),

        unarchive: (id) => fetchJSON(`${API_BASE}/tasks/${id}/unarchive`, {
            method: 'PATCH',
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

    queue: {
        status: () => fetchJSON(`${API_BASE}/queue/status`),
    },

    worktrees: {
        list: () => fetchJSON(`${API_BASE}/worktrees`),

        remove: (taskId) => fetchJSON(`${API_BASE}/worktrees/${taskId}`, {
            method: 'DELETE',
        }),

        merge: (taskId, target = 'develop') => fetchJSON(`${API_BASE}/worktrees/${taskId}/merge?target=${target}`, {
            method: 'POST',
        }),
    },

    context: {
        get: () => fetchJSON(`${API_BASE}/context`),
        refresh: () => fetchJSON(`${API_BASE}/context/refresh`, { method: 'POST' }),
        getSummary: () => fetchJSON(`${API_BASE}/context/summary`),
    },

    roadmap: {
        get: () => fetchJSON(`${API_BASE}/roadmap`),

        update: (data) => fetchJSON(`${API_BASE}/roadmap`, {
            method: 'PUT',
            body: JSON.stringify(data),
        }),

        clear: () => fetchJSON(`${API_BASE}/roadmap`, {
            method: 'DELETE',
        }),

        // Analysis status
        analysisStatus: () => fetchJSON(`${API_BASE}/roadmap/analysis-status`),

        // AI Generation phases
        analyze: (data) => fetchJSON(`${API_BASE}/roadmap/analyze`, {
            method: 'POST',
            body: JSON.stringify(data || {}),
        }),

        discover: (useExisting = false) => fetchJSON(`${API_BASE}/roadmap/discover`, {
            method: 'POST',
            body: JSON.stringify({ use_existing: useExisting }),
        }),

        generate: (useCompetitorAnalysis = true) => fetchJSON(`${API_BASE}/roadmap/generate`, {
            method: 'POST',
            body: JSON.stringify({ use_competitor_analysis: useCompetitorAnalysis }),
        }),

        // Feature CRUD
        createFeature: (data) => fetchJSON(`${API_BASE}/roadmap/features`, {
            method: 'POST',
            body: JSON.stringify(data),
        }),

        updateFeature: (id, data) => fetchJSON(`${API_BASE}/roadmap/features/${id}`, {
            method: 'PATCH',
            body: JSON.stringify(data),
        }),

        deleteFeature: (id) => fetchJSON(`${API_BASE}/roadmap/features/${id}`, {
            method: 'DELETE',
        }),

        updateFeatureStatus: (id, status) => fetchJSON(`${API_BASE}/roadmap/features/${id}/drag`, {
            method: 'PATCH',
            body: JSON.stringify({ status }),
        }),

        buildFeature: (id) => fetchJSON(`${API_BASE}/roadmap/features/${id}/build`, {
            method: 'POST',
        }),

        expandFeature: (id) => fetchJSON(`${API_BASE}/roadmap/features/${id}/expand`, {
            method: 'POST',
        }),
    },
};
