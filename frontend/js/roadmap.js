/**
 * Roadmap module - Main roadmap functionality
 */

import { API } from './api.js';

// State
let roadmapData = null;
let currentView = 'board'; // 'board' or 'list'
let currentFeatureId = null;
let initialized = false;

// Priority labels
const PRIORITY_LABELS = {
    must: 'Indispensable',
    should: 'Important',
    could: 'Souhaitable',
    wont: 'Exclu'
};

// Phase labels
const PHASE_LABELS = {
    foundation: 'Fondation',
    core: 'Cœur',
    enhancement: 'Amélioration',
    polish: 'Finition'
};

// Status mapping for columns
const STATUS_COLUMN_MAP = {
    under_review: 'column-under_review',
    planned: 'column-planned',
    in_progress: 'column-in_progress_rm',
    done: 'column-done_rm'
};

/**
 * Initialize roadmap when view is activated
 */
export async function initRoadmap() {
    await loadRoadmap();

    // Only setup once
    if (!initialized) {
        setupEventListeners();
        initialized = true;
    }

    setupDragDrop();
}

/**
 * Load roadmap data from API
 */
export async function loadRoadmap() {
    try {
        const response = await API.roadmap.get();
        roadmapData = response.roadmap;

        if (!roadmapData || !roadmapData.features || roadmapData.features.length === 0) {
            showEmptyState();
        } else {
            hideEmptyState();
            renderRoadmap();
        }
    } catch (error) {
        console.error('Failed to load roadmap:', error);
        showEmptyState();
    }
}

/**
 * Show empty state with generate button
 */
function showEmptyState() {
    const board = document.getElementById('roadmap-board');
    const list = document.getElementById('roadmap-list');

    board.innerHTML = `
        <div class="roadmap-empty" style="grid-column: 1 / -1;">
            <h3>Aucune fonctionnalité</h3>
            <p>Générez votre roadmap produit avec l'IA ou ajoutez des fonctionnalités manuellement.</p>
            <button class="btn btn-primary btn-generate-roadmap" id="btn-generate-wizard">
                Générer la Roadmap
            </button>
        </div>
    `;

    list.innerHTML = '';

    // Bind generate button
    document.getElementById('btn-generate-wizard')?.addEventListener('click', () => {
        window.dispatchEvent(new CustomEvent('open-roadmap-wizard'));
    });
}

/**
 * Hide empty state and restore columns
 */
function hideEmptyState() {
    const board = document.getElementById('roadmap-board');

    // Check if columns exist
    if (!document.getElementById('column-under_review')) {
        board.innerHTML = `
            <div class="roadmap-column" data-status="under_review">
                <div class="roadmap-column-header">
                    <h3>À examiner</h3>
                    <span class="roadmap-count" id="count-under_review">0</span>
                </div>
                <div class="roadmap-column-body" id="column-under_review"></div>
            </div>

            <div class="roadmap-column" data-status="planned">
                <div class="roadmap-column-header">
                    <h3>Planifié</h3>
                    <span class="roadmap-count" id="count-planned">0</span>
                </div>
                <div class="roadmap-column-body" id="column-planned"></div>
            </div>

            <div class="roadmap-column" data-status="in_progress">
                <div class="roadmap-column-header">
                    <h3>En cours</h3>
                    <span class="roadmap-count" id="count-in_progress_rm">0</span>
                </div>
                <div class="roadmap-column-body" id="column-in_progress_rm"></div>
            </div>

            <div class="roadmap-column" data-status="done">
                <div class="roadmap-column-header">
                    <h3>Terminé</h3>
                    <span class="roadmap-count" id="count-done_rm">0</span>
                </div>
                <div class="roadmap-column-body" id="column-done_rm"></div>
            </div>
        `;

        setupDragDrop();
    }
}

/**
 * Render the roadmap
 */
function renderRoadmap() {
    if (!roadmapData) return;

    updateStats();

    if (currentView === 'board') {
        renderBoard();
    } else {
        renderList();
    }
}

/**
 * Update roadmap stats
 */
function updateStats() {
    if (!roadmapData || !roadmapData.features) return;

    const features = roadmapData.features;
    const stats = document.getElementById('roadmap-stats');

    const mustHave = features.filter(f => f.priority === 'must').length;
    const inProgress = features.filter(f => f.status === 'in_progress').length;
    const done = features.filter(f => f.status === 'done').length;

    stats.innerHTML = `
        <span class="roadmap-stat">
            <span class="roadmap-stat-value">${features.length}</span> fonctionnalités
        </span>
        <span class="roadmap-stat">
            <span class="roadmap-stat-value">${mustHave}</span> indispensables
        </span>
        <span class="roadmap-stat">
            <span class="roadmap-stat-value">${inProgress}</span> en cours
        </span>
        <span class="roadmap-stat">
            <span class="roadmap-stat-value">${done}</span> terminées
        </span>
    `;

    // Update subtitle
    if (roadmapData.project_name) {
        document.getElementById('roadmap-subtitle').textContent =
            `${roadmapData.project_name} - ${roadmapData.project_description || 'Roadmap produit'}`;
    }
}

/**
 * Render board view
 */
function renderBoard() {
    if (!roadmapData || !roadmapData.features) return;

    // Clear columns
    Object.values(STATUS_COLUMN_MAP).forEach(columnId => {
        const column = document.getElementById(columnId);
        if (column) column.innerHTML = '';
    });

    // Group features by status
    const byStatus = {
        under_review: [],
        planned: [],
        in_progress: [],
        done: []
    };

    roadmapData.features.forEach(feature => {
        const status = feature.status || 'under_review';
        if (byStatus[status]) {
            byStatus[status].push(feature);
        }
    });

    // Render each status group
    Object.entries(byStatus).forEach(([status, features]) => {
        const columnId = STATUS_COLUMN_MAP[status];
        const column = document.getElementById(columnId);
        if (!column) return;

        // Update count
        const countEl = document.getElementById(`count-${columnId.replace('column-', '')}`);
        if (countEl) countEl.textContent = features.length;

        // Render cards
        features.forEach(feature => {
            column.appendChild(createFeatureCard(feature));
        });
    });
}

/**
 * Render list view
 */
function renderList() {
    if (!roadmapData || !roadmapData.features) return;

    const tbody = document.getElementById('roadmap-table-body');
    if (!tbody) return;

    tbody.innerHTML = roadmapData.features.map(feature => `
        <tr data-feature-id="${feature.id}">
            <td>
                <strong>${escapeHtml(feature.title)}</strong>
                <br>
                <small style="color: var(--text-secondary)">${escapeHtml(feature.description.substring(0, 100))}...</small>
            </td>
            <td><span class="feature-badge phase-${feature.phase}">${PHASE_LABELS[feature.phase]}</span></td>
            <td><span class="feature-badge priority-${feature.priority}">${PRIORITY_LABELS[feature.priority]}</span></td>
            <td><span class="feature-badge complexity-${feature.complexity}">${feature.complexity}</span></td>
            <td><span class="feature-badge impact-${feature.impact}">${feature.impact}</span></td>
            <td>${feature.status.replace('_', ' ')}</td>
            <td>
                <button class="btn btn-small btn-secondary btn-view-feature" data-id="${feature.id}">Voir</button>
                ${!feature.task_id ? `<button class="btn btn-small btn-success btn-build-feature" data-id="${feature.id}">Créer</button>` : ''}
            </td>
        </tr>
    `).join('');

    // Bind row actions
    tbody.querySelectorAll('.btn-view-feature').forEach(btn => {
        btn.addEventListener('click', (e) => {
            e.stopPropagation();
            openFeatureDetail(btn.dataset.id);
        });
    });

    tbody.querySelectorAll('.btn-build-feature').forEach(btn => {
        btn.addEventListener('click', (e) => {
            e.stopPropagation();
            buildFeature(btn.dataset.id);
        });
    });
}

/**
 * Create a feature card element
 */
function createFeatureCard(feature) {
    const card = document.createElement('div');
    card.className = 'feature-card';
    card.draggable = true;
    card.dataset.featureId = feature.id;

    card.innerHTML = `
        <div class="feature-card-header">
            <h4 class="feature-card-title">${escapeHtml(feature.title)}</h4>
        </div>
        <div class="feature-card-badges">
            <span class="feature-badge priority-${feature.priority}">${PRIORITY_LABELS[feature.priority]}</span>
            <span class="feature-badge phase-${feature.phase}">${PHASE_LABELS[feature.phase]}</span>
        </div>
        <p class="feature-card-description">${escapeHtml(feature.description)}</p>
        <div class="feature-card-footer">
            ${feature.task_id
                ? `<a href="#" class="feature-task-link" data-task-id="${feature.task_id}">${feature.task_id}</a>`
                : `<button class="btn-feature-action btn-build" data-id="${feature.id}">Créer</button>`
            }
        </div>
    `;

    // Click to open detail
    card.addEventListener('click', (e) => {
        if (e.target.closest('.btn-feature-action') || e.target.closest('.feature-task-link')) {
            return;
        }
        openFeatureDetail(feature.id);
    });

    // Build button
    const buildBtn = card.querySelector('.btn-build');
    if (buildBtn) {
        buildBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            buildFeature(feature.id);
        });
    }

    // Task link
    const taskLink = card.querySelector('.feature-task-link');
    if (taskLink) {
        taskLink.addEventListener('click', (e) => {
            e.preventDefault();
            e.stopPropagation();
            window.dispatchEvent(new CustomEvent('open-task-modal', {
                detail: { taskId: feature.task_id }
            }));
        });
    }

    return card;
}

/**
 * Setup event listeners
 */
function setupEventListeners() {
    // View tabs
    document.querySelectorAll('.roadmap-tab').forEach(tab => {
        tab.addEventListener('click', () => {
            document.querySelectorAll('.roadmap-tab').forEach(t => t.classList.remove('active'));
            tab.classList.add('active');

            currentView = tab.dataset.tab;

            const board = document.getElementById('roadmap-board');
            const list = document.getElementById('roadmap-list');

            if (currentView === 'board') {
                board.classList.remove('hidden');
                list.classList.add('hidden');
            } else {
                board.classList.add('hidden');
                list.classList.remove('hidden');
            }

            renderRoadmap();
        });
    });

    // Add feature button
    document.getElementById('add-feature-btn')?.addEventListener('click', openAddFeatureModal);

    // Regenerate roadmap button
    document.getElementById('regenerate-roadmap-btn')?.addEventListener('click', regenerateRoadmap);

    // Add feature modal
    setupAddFeatureModal();

    // Feature detail modal
    setupFeatureDetailModal();
}

/**
 * Setup drag and drop
 */
function setupDragDrop() {
    const columns = document.querySelectorAll('.roadmap-column-body');

    columns.forEach(column => {
        column.addEventListener('dragover', (e) => {
            e.preventDefault();
            column.classList.add('drag-over');
        });

        column.addEventListener('dragleave', () => {
            column.classList.remove('drag-over');
        });

        column.addEventListener('drop', async (e) => {
            e.preventDefault();
            column.classList.remove('drag-over');

            const featureId = e.dataTransfer.getData('text/plain');
            const newStatus = column.closest('.roadmap-column').dataset.status;

            if (featureId && newStatus) {
                await updateFeatureStatus(featureId, newStatus);
            }
        });
    });

    // Make cards draggable
    document.querySelectorAll('.feature-card').forEach(card => {
        card.addEventListener('dragstart', (e) => {
            e.dataTransfer.setData('text/plain', card.dataset.featureId);
            card.classList.add('dragging');
        });

        card.addEventListener('dragend', () => {
            card.classList.remove('dragging');
        });
    });
}

/**
 * Update feature status via drag-drop
 */
async function updateFeatureStatus(featureId, newStatus) {
    try {
        await API.roadmap.updateFeatureStatus(featureId, newStatus);
        await loadRoadmap();
    } catch (error) {
        console.error('Failed to update feature status:', error);
    }
}

/**
 * Open add feature modal
 */
function openAddFeatureModal() {
    const modal = document.getElementById('add-feature-modal');
    modal.classList.remove('hidden');

    // Reset form
    document.getElementById('add-feature-form').reset();
}

/**
 * Setup add feature modal
 */
function setupAddFeatureModal() {
    const modal = document.getElementById('add-feature-modal');
    if (!modal) return;

    // Close buttons
    modal.querySelectorAll('.btn-close').forEach(btn => {
        btn.addEventListener('click', () => {
            modal.classList.add('hidden');
        });
    });

    // Save button
    document.getElementById('btn-save-feature')?.addEventListener('click', async () => {
        const title = document.getElementById('feature-title').value.trim();
        const description = document.getElementById('feature-description').value.trim();
        const justification = document.getElementById('feature-justification').value.trim();
        const phase = document.getElementById('feature-phase').value;
        const priority = document.getElementById('feature-priority').value;
        const complexity = document.getElementById('feature-complexity').value;
        const impact = document.getElementById('feature-impact').value;

        if (!title || !description) {
            alert('Veuillez remplir le titre et la description');
            return;
        }

        try {
            await API.roadmap.createFeature({
                title,
                description,
                justification: justification || null,
                phase,
                priority,
                complexity,
                impact
            });

            modal.classList.add('hidden');
            await loadRoadmap();
        } catch (error) {
            console.error('Failed to create feature:', error);
            alert('Échec de création: ' + error.message);
        }
    });

    // Click outside to close
    modal.addEventListener('click', (e) => {
        if (e.target === modal) {
            modal.classList.add('hidden');
        }
    });

    // Prevent clicks inside modal-content from bubbling to overlay
    const modalContent = modal.querySelector('.modal-content');
    if (modalContent) {
        modalContent.addEventListener('click', (e) => {
            e.stopPropagation();
        });
    }
}

/**
 * Open feature detail modal
 */
function openFeatureDetail(featureId) {
    currentFeatureId = featureId;
    const feature = roadmapData?.features?.find(f => f.id === featureId);
    if (!feature) return;

    const modal = document.getElementById('feature-detail-modal');

    document.getElementById('feature-detail-title').textContent = feature.title;
    document.getElementById('detail-priority').textContent = PRIORITY_LABELS[feature.priority];
    document.getElementById('detail-priority').className = `feature-badge priority-badge priority-${feature.priority}`;
    document.getElementById('detail-phase').textContent = PHASE_LABELS[feature.phase];
    document.getElementById('detail-phase').className = `feature-badge phase-badge phase-${feature.phase}`;
    document.getElementById('detail-complexity').textContent = `Complexité: ${feature.complexity}`;
    document.getElementById('detail-complexity').className = `feature-badge complexity-badge complexity-${feature.complexity}`;
    document.getElementById('detail-impact').textContent = `Impact: ${feature.impact}`;
    document.getElementById('detail-impact').className = `feature-badge impact-badge impact-${feature.impact}`;
    document.getElementById('detail-description').textContent = feature.description;

    const justificationSection = document.getElementById('detail-justification-section');
    if (feature.justification) {
        justificationSection.style.display = 'block';
        document.getElementById('detail-justification').textContent = feature.justification;
    } else {
        justificationSection.style.display = 'none';
    }

    const taskSection = document.getElementById('detail-task-section');
    if (feature.task_id) {
        taskSection.style.display = 'block';
        const taskLink = document.getElementById('detail-task-link');
        taskLink.textContent = feature.task_id;
        taskLink.onclick = (e) => {
            e.preventDefault();
            modal.classList.add('hidden');
            window.dispatchEvent(new CustomEvent('open-task-modal', {
                detail: { taskId: feature.task_id }
            }));
        };
    } else {
        taskSection.style.display = 'none';
    }

    // Update build button visibility
    const buildBtn = document.getElementById('btn-build-feature');
    if (feature.task_id) {
        buildBtn.style.display = 'none';
    } else {
        buildBtn.style.display = 'inline-block';
    }

    modal.classList.remove('hidden');
}

/**
 * Setup feature detail modal
 */
function setupFeatureDetailModal() {
    const modal = document.getElementById('feature-detail-modal');
    if (!modal) return;

    // Close buttons
    modal.querySelectorAll('.btn-close').forEach(btn => {
        btn.addEventListener('click', () => {
            modal.classList.add('hidden');
        });
    });

    // Delete button
    document.getElementById('btn-delete-feature')?.addEventListener('click', async () => {
        if (!currentFeatureId) return;

        if (!confirm('Êtes-vous sûr de vouloir supprimer cette fonctionnalité ?')) return;

        try {
            await API.roadmap.deleteFeature(currentFeatureId);
            modal.classList.add('hidden');
            await loadRoadmap();
        } catch (error) {
            console.error('Failed to delete feature:', error);
            alert('Échec de suppression: ' + error.message);
        }
    });

    // Expand button
    document.getElementById('btn-expand-feature')?.addEventListener('click', async () => {
        if (!currentFeatureId) return;

        try {
            const btn = document.getElementById('btn-expand-feature');
            btn.textContent = 'Expansion...';
            btn.disabled = true;

            await API.roadmap.expandFeature(currentFeatureId);
            await loadRoadmap();

            // Refresh modal
            openFeatureDetail(currentFeatureId);

            btn.textContent = 'Enrichir avec l\'IA';
            btn.disabled = false;
        } catch (error) {
            console.error('Failed to expand feature:', error);
            alert('Échec de l\'expansion: ' + error.message);
            document.getElementById('btn-expand-feature').textContent = 'Enrichir avec l\'IA';
            document.getElementById('btn-expand-feature').disabled = false;
        }
    });

    // Build button
    document.getElementById('btn-build-feature')?.addEventListener('click', async () => {
        if (!currentFeatureId) return;
        await buildFeature(currentFeatureId);
        modal.classList.add('hidden');
    });

    // Click outside to close
    modal.addEventListener('click', (e) => {
        if (e.target === modal) {
            modal.classList.add('hidden');
        }
    });

    // Prevent clicks inside modal-content from bubbling to overlay
    const detailModalContent = modal.querySelector('.modal-content');
    if (detailModalContent) {
        detailModalContent.addEventListener('click', (e) => {
            e.stopPropagation();
        });
    }
}

/**
 * Build feature - create task from feature
 */
async function buildFeature(featureId) {
    try {
        const response = await API.roadmap.buildFeature(featureId);
        await loadRoadmap();

        // Open task modal
        if (response.task_id) {
            window.dispatchEvent(new CustomEvent('open-task-modal', {
                detail: { taskId: response.task_id }
            }));
        }
    } catch (error) {
        console.error('Failed to build feature:', error);
        alert('Échec de création de la tâche: ' + error.message);
    }
}

/**
 * Regenerate roadmap - clear all features and start wizard
 */
async function regenerateRoadmap() {
    if (!confirm('Êtes-vous sûr de vouloir supprimer toutes les fonctionnalités et régénérer la roadmap ?\n\nCette action est irréversible.')) {
        return;
    }

    const btn = document.getElementById('regenerate-roadmap-btn');
    const originalText = btn.textContent;

    try {
        btn.textContent = '⏳ Suppression...';
        btn.disabled = true;

        // Clear roadmap via API
        await API.roadmap.clear();

        // Reset local state
        roadmapData = null;

        btn.textContent = '✓ Supprimé';

        // Open wizard to regenerate
        setTimeout(() => {
            btn.textContent = originalText;
            btn.disabled = false;
            window.dispatchEvent(new CustomEvent('open-roadmap-wizard'));
        }, 500);

    } catch (error) {
        console.error('Failed to clear roadmap:', error);
        alert('Échec de la suppression: ' + error.message);
        btn.textContent = originalText;
        btn.disabled = false;
    }
}

/**
 * Escape HTML
 */
function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

// Initialize event listeners when module loads
function setupGlobalListeners() {
    // Listen for view change - this must be set up at module load
    window.addEventListener('view-changed', (e) => {
        if (e.detail.view === 'roadmap') {
            initRoadmap();
        }
    });

    // Listen for roadmap refresh
    window.addEventListener('roadmap-refresh', () => {
        loadRoadmap();
    });
}

// Setup global listeners immediately
setupGlobalListeners();

// Expose loadRoadmap globally for workspace switching
window.loadRoadmap = loadRoadmap;

// Export for other modules
export { roadmapData };
