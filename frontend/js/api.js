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

        retrySubtask: (taskId, subtaskId) => fetchJSON(`${API_BASE}/tasks/${taskId}/subtasks/${subtaskId}/retry`, {
            method: 'POST',
        }),
    },

    settings: {
        get: () => fetchJSON(`${API_BASE}/settings`),

        update: (data) => fetchJSON(`${API_BASE}/settings`, {
            method: 'PATCH',
            body: JSON.stringify(data),
        }),

        getParallel: () => fetchJSON(`${API_BASE}/settings/parallel`),

        updateParallel: (maxParallelTasks) => fetchJSON(`${API_BASE}/settings/parallel`, {
            method: 'PATCH',
            body: JSON.stringify({ max_parallel_tasks: maxParallelTasks }),
        }),
    },

    git: {
        syncMain: () => fetchJSON(`${API_BASE}/sync-main`, {
            method: 'POST',
        }),
        syncStatus: () => fetchJSON(`${API_BASE}/git/sync-status`),
        sync: () => fetchJSON(`${API_BASE}/git/sync`, {
            method: 'POST',
        }),
    },

    queue: {
        status: () => fetchJSON(`${API_BASE}/queue/status`),

        detailed: () => fetchJSON(`${API_BASE}/queue/detailed`),

        batch: (tasks) => fetchJSON(`${API_BASE}/queue/batch`, {
            method: 'POST',
            body: JSON.stringify({ tasks }),
        }),

        reorder: (taskOrder) => fetchJSON(`${API_BASE}/queue/reorder`, {
            method: 'PUT',
            body: JSON.stringify({ task_order: taskOrder }),
        }),

        pause: () => fetchJSON(`${API_BASE}/queue/pause`, {
            method: 'POST',
        }),

        resume: () => fetchJSON(`${API_BASE}/queue/resume`, {
            method: 'POST',
        }),

        estimates: () => fetchJSON(`${API_BASE}/queue/estimates`),

        optimize: () => fetchJSON(`${API_BASE}/queue/optimize`, {
            method: 'POST',
        }),
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

    changelog: {
        get: (limit = 50, offset = 0, codeflowOnly = true) =>
            fetchJSON(`${API_BASE}/changelog?limit=${limit}&offset=${offset}&codeflow_only=${codeflowOnly}`),
    },

    memory: {
        list: (options = {}) => {
            const params = new URLSearchParams();
            if (options.projectPath) params.append('project_path', options.projectPath);
            if (options.includeWorktrees !== undefined) params.append('include_worktrees', options.includeWorktrees);
            if (options.limit) params.append('limit', options.limit);
            const query = params.toString();
            return fetchJSON(`${API_BASE}/memory/sessions${query ? '?' + query : ''}`);
        },

        get: (sessionId, projectPath = null) => {
            const params = projectPath ? `?project_path=${encodeURIComponent(projectPath)}` : '';
            return fetchJSON(`${API_BASE}/memory/sessions/${encodeURIComponent(sessionId)}${params}`);
        },

        delete: (sessionId, projectPath = null) => {
            const params = projectPath ? `?project_path=${encodeURIComponent(projectPath)}` : '';
            return fetchJSON(`${API_BASE}/memory/sessions/${encodeURIComponent(sessionId)}${params}`, {
                method: 'DELETE',
            });
        },

        resume: (sessionId, projectPath = null) => {
            const params = projectPath ? `?project_path=${encodeURIComponent(projectPath)}` : '';
            return fetchJSON(`${API_BASE}/memory/sessions/${encodeURIComponent(sessionId)}/resume${params}`, {
                method: 'POST',
            });
        },
    },

    ideation: {
        getData: () => fetchJSON(`${API_BASE}/ideation`),

        analyze: () => fetchJSON(`${API_BASE}/ideation/analyze`, {
            method: 'POST',
        }),

        getAnalysis: () => fetchJSON(`${API_BASE}/ideation/analysis`),

        suggest: () => fetchJSON(`${API_BASE}/ideation/suggest`, {
            method: 'POST',
        }),

        getSuggestions: () => fetchJSON(`${API_BASE}/ideation/suggestions`),

        acceptSuggestion: (id) => fetchJSON(`${API_BASE}/ideation/suggestions/${id}/accept`, {
            method: 'POST',
        }),

        dismissSuggestion: (id) => fetchJSON(`${API_BASE}/ideation/suggestions/${id}/dismiss`, {
            method: 'POST',
        }),

        deleteSuggestion: (id) => fetchJSON(`${API_BASE}/ideation/suggestions/${id}`, {
            method: 'DELETE',
        }),

        chat: (message, context = []) => fetchJSON(`${API_BASE}/ideation/chat`, {
            method: 'POST',
            body: JSON.stringify({ message, context }),
        }),

        clear: () => fetchJSON(`${API_BASE}/ideation`, {
            method: 'DELETE',
        }),
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
