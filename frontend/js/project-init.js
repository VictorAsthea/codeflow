/**
 * Gestion de l'initialisation de projet
 */

class ProjectInitManager {
    constructor() {
        this.modal = null;
        this.isInitializing = false;
    }

    async checkOnStartup() {
        try {
            const response = await fetch('/api/project/status');
            const status = await response.json();

            if (!status.initialized) {
                this.showInitModal(status);
            }
        } catch (error) {
            console.error('Failed to check project status:', error);
        }
    }

    async initialize() {
        if (this.isInitializing) return;

        this.isInitializing = true;
        this.showProgressState();

        try {
            const response = await fetch('/api/project/init', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({})
            });

            const result = await response.json();

            if (result.success) {
                this.showSuccessState(result);
            } else {
                window.showToast?.(result.message || 'Erreur', 'error');
            }
        } catch (error) {
            console.error('Failed to initialize:', error);
            window.showToast?.('Erreur lors de l\'initialisation', 'error');
        } finally {
            this.isInitializing = false;
        }
    }

    showInitModal(status) {
        const projectName = status?.project_name || 'le projet';
        const html = `
            <div class="modal" id="init-modal">
                <div class="modal-content init-modal">
                    <div class="modal-header">
                        <h2>Initialiser ${projectName}</h2>
                        <button class="btn-close" onclick="projectInit.closeModal()">&times;</button>
                    </div>
                    <div class="modal-body">
                        <p>Ce projet n'a pas Codeflow initialise. Voulez-vous le configurer ?</p>
                        <div class="init-info-box">
                            <p><strong>Ceci va :</strong></p>
                            <ul>
                                <li>Creer un dossier <code>.codeflow</code></li>
                                <li>Detecter le stack technique</li>
                                <li>Configurer les commandes autorisees</li>
                                <li>Activer les MCPs recommandes</li>
                                <li>Creer <code>CLAUDE.md</code></li>
                            </ul>
                        </div>
                    </div>
                    <div class="modal-footer">
                        <button class="btn btn-secondary" onclick="projectInit.closeModal()">Passer</button>
                        <button class="btn btn-primary" onclick="projectInit.initialize()">Initialiser</button>
                    </div>
                </div>
            </div>
        `;
        document.body.insertAdjacentHTML('beforeend', html);
        this.modal = document.getElementById('init-modal');
    }

    showProgressState() {
        if (!this.modal) return;
        this.modal.querySelector('.modal-body').innerHTML = `
            <div class="init-progress">
                <p>Initialisation en cours...</p>
                <div class="progress-bar"><div class="progress-fill" style="width: 50%"></div></div>
            </div>
        `;
        this.modal.querySelector('.modal-footer').innerHTML = '';
    }

    showSuccessState(result) {
        if (!this.modal) return;

        const stackTags = [...result.detected_stack.languages, ...result.detected_stack.frameworks]
            .map(s => `<span class="init-tag">${s}</span>`).join('') || '<span class="init-tag">Aucun</span>';

        const files = result.files_created.filter(f => f).map(f => `<li><code>${f}</code></li>`).join('');

        this.modal.querySelector('.modal-body').innerHTML = `
            <div class="init-success">
                <p><strong>Projet initialise !</strong></p>
                <div class="success-section">
                    <p class="success-label">Stack detecte :</p>
                    <div class="success-tags">${stackTags}</div>
                </div>
                <div class="success-section">
                    <p class="success-label">Fichiers crees :</p>
                    <ul class="success-files">${files}</ul>
                </div>
            </div>
        `;
        this.modal.querySelector('.modal-footer').innerHTML = `
            <button class="btn btn-primary" onclick="projectInit.closeModal()">Fermer</button>
        `;
    }

    closeModal() {
        if (this.modal) {
            this.modal.remove();
            this.modal = null;
        }
    }
}

const projectInit = new ProjectInitManager();

document.addEventListener('DOMContentLoaded', () => {
    setTimeout(() => projectInit.checkOnStartup(), 500);
});
