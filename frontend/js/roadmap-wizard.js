/**
 * Roadmap Wizard - Automatic AI-powered roadmap generation
 * No manual input required - analyzes codebase automatically
 */

import { API } from './api.js';
import { loadRoadmap } from './roadmap.js';

// State
let currentStep = 1;
let useCompetitorAnalysis = true;

/**
 * Initialize wizard
 */
export function initRoadmapWizard() {
    setupWizardEventListeners();

    // Listen for wizard open event
    window.addEventListener('open-roadmap-wizard', () => {
        openWizard();
    });
}

/**
 * Check if wizard should be shown on first visit
 */
export async function checkAndShowWizard() {
    try {
        const status = await API.roadmap.analysisStatus();
        if (!status.has_roadmap || !status.has_features) {
            openWizard();
        }
    } catch (error) {
        console.error('Failed to check analysis status:', error);
    }
}

/**
 * Open the wizard modal and start immediately
 */
function openWizard() {
    const modal = document.getElementById('roadmap-wizard-modal');
    modal.classList.remove('hidden');

    // Reset and start at step 1 (Analyze)
    currentStep = 1;
    updateStepIndicators();
    hideAllSteps();
    showStep(1);
    updateButtons();

    // Start analyzing immediately
    startAnalyzePhase();
}

/**
 * Close the wizard
 */
function closeWizard() {
    const modal = document.getElementById('roadmap-wizard-modal');
    modal.classList.add('hidden');
}

/**
 * Update step indicators (new dot style)
 */
function updateStepIndicators() {
    document.querySelectorAll('.step-dot').forEach((dot) => {
        const stepNum = parseInt(dot.dataset.step);
        dot.classList.remove('active', 'completed');
        if (stepNum < currentStep) {
            dot.classList.add('completed');
        } else if (stepNum === currentStep) {
            dot.classList.add('active');
        }
    });
}

/**
 * Hide all step content
 */
function hideAllSteps() {
    document.querySelectorAll('.wizard-step').forEach(step => {
        step.classList.add('hidden');
    });
}

/**
 * Show specific step
 */
function showStep(step) {
    const stepEl = document.getElementById(`wizard-step-${step}`);
    if (stepEl) {
        stepEl.classList.remove('hidden');
    }
}

/**
 * Go to next step
 */
function goToStep(step) {
    currentStep = step;
    updateStepIndicators();
    hideAllSteps();
    showStep(step);
    updateButtons();

    // Auto-start each phase
    if (step === 1) {
        startAnalyzePhase();
    } else if (step === 2) {
        startDiscoverPhase();
    } else if (step === 3) {
        startGeneratePhase();
    }
}

/**
 * Update button visibility
 */
function updateButtons() {
    const skipBtn = document.getElementById('wizard-skip');
    const finishBtn = document.getElementById('wizard-finish');

    // Hide all first
    skipBtn.classList.add('hidden');
    finishBtn.classList.add('hidden');

    // Step 2 (Discover) can be skipped
    if (currentStep === 2) {
        skipBtn.classList.remove('hidden');
        skipBtn.textContent = 'Passer';
    }
}

/**
 * Setup event listeners
 */
function setupWizardEventListeners() {
    const modal = document.getElementById('roadmap-wizard-modal');
    if (!modal) return;

    // Close button
    modal.querySelectorAll('.btn-close').forEach(btn => {
        btn.addEventListener('click', closeWizard);
    });

    // Skip button (for competitor step)
    document.getElementById('wizard-skip')?.addEventListener('click', () => {
        if (currentStep === 2) {
            useCompetitorAnalysis = false;
            goToStep(3);
        }
    });

    // Finish button
    document.getElementById('wizard-finish')?.addEventListener('click', () => {
        closeWizard();
        loadRoadmap();
    });

    // Click outside to close
    modal.addEventListener('click', (e) => {
        if (e.target === modal) {
            closeWizard();
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
 * Step 1: Analyze project automatically
 */
async function startAnalyzePhase() {
    const progressBar = document.getElementById('analyze-progress');
    const statusText = document.getElementById('analyze-status');
    const resultDiv = document.getElementById('analyze-result');

    // Reset UI
    progressBar.style.width = '0%';
    resultDiv.classList.add('hidden');
    statusText.textContent = 'Analyse de la structure du projet...';

    // Animate progress
    let progress = 0;
    const progressInterval = setInterval(() => {
        progress += 3;
        if (progress <= 90) {
            progressBar.style.width = `${progress}%`;
        }
        // Update status text based on progress
        if (progress === 15) statusText.textContent = 'Lecture du README et des fichiers de config...';
        if (progress === 30) statusText.textContent = 'Détection de la stack technique...';
        if (progress === 50) statusText.textContent = 'Analyse de la structure du projet...';
        if (progress === 70) statusText.textContent = 'Extraction des informations du projet...';
    }, 150);

    try {
        // Call API without any manual input - backend will auto-detect everything
        const response = await API.roadmap.analyze({});

        clearInterval(progressInterval);
        progressBar.style.width = '100%';
        statusText.textContent = 'Analyse terminée !';

        // Show results
        const analysis = response.analysis;
        const roadmap = response.roadmap;

        document.getElementById('result-project-name').textContent = roadmap?.project_name || 'Detected';
        document.getElementById('result-stack').textContent = analysis?.stack?.join(', ') || 'Unknown';
        document.getElementById('result-files').textContent = analysis?.files_count || 0;
        document.getElementById('result-summary').textContent =
            roadmap?.project_description || analysis?.structure_summary || 'Project analyzed successfully';

        resultDiv.classList.remove('hidden');

        // Auto-advance after delay
        setTimeout(() => goToStep(2), 1500);

    } catch (error) {
        clearInterval(progressInterval);
        console.error('Analysis failed:', error);
        progressBar.style.width = '100%';
        statusText.textContent = 'Analyse terminée avec les valeurs par défaut';

        // Continue anyway
        setTimeout(() => goToStep(2), 1500);
    }
}

/**
 * Step 2: Discover competitors
 */
async function startDiscoverPhase() {
    const progressBar = document.getElementById('discover-progress');
    const statusText = document.getElementById('discover-status');
    const resultDiv = document.getElementById('discover-result');

    // Reset UI
    progressBar.style.width = '0%';
    resultDiv.classList.add('hidden');
    statusText.textContent = 'Recherche de produits similaires...';

    // Animate progress
    let progress = 0;
    const progressInterval = setInterval(() => {
        progress += 2;
        if (progress <= 85) {
            progressBar.style.width = `${progress}%`;
        }
        if (progress === 20) statusText.textContent = 'Identification du segment de marché...';
        if (progress === 40) statusText.textContent = 'Recherche des concurrents...';
        if (progress === 60) statusText.textContent = 'Analyse des fonctionnalités concurrentes...';
    }, 200);

    try {
        const response = await API.roadmap.discover(false);

        clearInterval(progressInterval);
        progressBar.style.width = '100%';

        const competitors = response.competitor_analysis?.competitors || [];
        const listEl = document.getElementById('competitors-list');

        if (competitors.length > 0) {
            statusText.textContent = `${competitors.length} concurrent${competitors.length > 1 ? 's' : ''} trouvé${competitors.length > 1 ? 's' : ''} !`;
            listEl.innerHTML = competitors.map(comp => `
                <div class="competitor-item">
                    <div class="competitor-name">${escapeHtml(comp.name)}</div>
                    ${comp.url ? `<a href="${comp.url}" target="_blank" class="competitor-url">${comp.url}</a>` : ''}
                    <div class="competitor-features">${comp.features?.slice(0, 3).join(' · ') || ''}</div>
                </div>
            `).join('');
            useCompetitorAnalysis = true;
        } else {
            statusText.textContent = 'Aucun concurrent trouvé';
            listEl.innerHTML = '<p class="no-results">Aucun produit similaire identifié</p>';
            useCompetitorAnalysis = false;
        }

        resultDiv.classList.remove('hidden');

        // Auto-advance after delay
        setTimeout(() => goToStep(3), 2000);

    } catch (error) {
        clearInterval(progressInterval);
        console.error('Discovery failed:', error);
        progressBar.style.width = '100%';
        statusText.textContent = 'Analyse concurrentielle ignorée...';
        useCompetitorAnalysis = false;

        setTimeout(() => goToStep(3), 1500);
    }
}

/**
 * Step 3: Generate features
 */
async function startGeneratePhase() {
    const progressBar = document.getElementById('generate-progress');
    const statusText = document.getElementById('generate-status');
    const resultDiv = document.getElementById('generate-result');
    const finishBtn = document.getElementById('wizard-finish');

    // Reset UI
    progressBar.style.width = '0%';
    resultDiv.classList.add('hidden');
    finishBtn.classList.add('hidden');
    statusText.textContent = 'Génération des suggestions de fonctionnalités...';

    // Animate progress
    let progress = 0;
    const progressInterval = setInterval(() => {
        progress += 1;
        if (progress <= 85) {
            progressBar.style.width = `${progress}%`;
        }
        if (progress === 20) statusText.textContent = 'Analyse des besoins du projet...';
        if (progress === 40) statusText.textContent = 'Priorisation des fonctionnalités par impact...';
        if (progress === 60) statusText.textContent = 'Organisation par phases de la roadmap...';
        if (progress === 80) statusText.textContent = 'Finalisation des suggestions...';
    }, 300);

    try {
        const response = await API.roadmap.generate(useCompetitorAnalysis);

        clearInterval(progressInterval);
        progressBar.style.width = '100%';
        statusText.textContent = 'Fonctionnalités générées !';

        const count = response.features_generated || 0;
        document.getElementById('generate-summary').textContent =
            `${count} fonctionnalité${count !== 1 ? 's' : ''} ajoutée${count !== 1 ? 's' : ''} à votre roadmap`;

        // Show feature breakdown if available
        const features = response.features || [];
        if (features.length > 0) {
            const breakdown = {
                must: features.filter(f => f.priority === 'must').length,
                should: features.filter(f => f.priority === 'should').length,
                could: features.filter(f => f.priority === 'could').length
            };
            document.getElementById('generate-breakdown').innerHTML = `
                <span class="priority-must">${breakdown.must} Indispensable${breakdown.must > 1 ? 's' : ''}</span>
                <span class="priority-should">${breakdown.should} Important${breakdown.should > 1 ? 's' : ''}</span>
                <span class="priority-could">${breakdown.could} Souhaitable${breakdown.could > 1 ? 's' : ''}</span>
            `;
        }

        resultDiv.classList.remove('hidden');
        finishBtn.classList.remove('hidden');
        finishBtn.textContent = 'Voir la Roadmap';

    } catch (error) {
        clearInterval(progressInterval);
        console.error('Generation failed:', error);
        progressBar.style.width = '100%';
        statusText.textContent = 'Échec de génération: ' + error.message;

        finishBtn.classList.remove('hidden');
        finishBtn.textContent = 'Fermer';
    }
}

/**
 * Escape HTML
 */
function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text || '';
    return div.innerHTML;
}

// Initialize when DOM is ready
document.addEventListener('DOMContentLoaded', () => {
    initRoadmapWizard();
});
