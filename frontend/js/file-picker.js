export class FilePicker {
    constructor(options = {}) {
        this.onSelect = options.onSelect || (() => {});
        this.modal = null;
    }

    async show() {
        this.modal = document.createElement('div');
        this.modal.className = 'modal file-picker-modal show';
        this.modal.innerHTML = `
            <div class="modal-content">
                <div class="modal-header">
                    <h2>Browse Project Files</h2>
                    <button class="btn-close">&times;</button>
                </div>
                <div class="modal-body">
                    <input type="text" id="file-search" placeholder="Search files..." class="input file-search-input">
                    <div id="file-list" class="file-list">
                        <div class="loading-message">Loading files...</div>
                    </div>
                </div>
                <div class="modal-footer">
                    <button class="btn btn-secondary cancel-btn">Cancel</button>
                </div>
            </div>
        `;

        document.body.appendChild(this.modal);

        this.modal.querySelector('.btn-close').addEventListener('click', () => this.hide());
        this.modal.querySelector('.cancel-btn').addEventListener('click', () => this.hide());

        this.modal.addEventListener('click', (e) => {
            if (e.target === this.modal) {
                this.hide();
            }
        });

        const searchInput = this.modal.querySelector('#file-search');
        let searchTimeout;
        searchInput.addEventListener('input', (e) => {
            clearTimeout(searchTimeout);
            searchTimeout = setTimeout(() => {
                this.handleSearch(e.target.value);
            }, 300);
        });

        await this.loadFiles('');
    }

    hide() {
        if (this.modal) {
            this.modal.remove();
            this.modal = null;
        }
    }

    async handleSearch(query) {
        await this.loadFiles(query);
    }

    async loadFiles(query) {
        const fileList = this.modal.querySelector('#file-list');
        fileList.innerHTML = '<div class="loading-message">Loading...</div>';

        try {
            const endpoint = query
                ? `/api/files/search?q=${encodeURIComponent(query)}`
                : `/api/files/list?pattern=**/*.{js,py,html,css,json,md,txt,yml,yaml,toml}`;

            const response = await fetch(endpoint);
            const files = await response.json();

            if (files.length === 0) {
                fileList.innerHTML = '<div class="no-files-message">No files found</div>';
                return;
            }

            fileList.innerHTML = files.map(file => `
                <div class="file-item" data-path="${file.path}">
                    <span class="file-icon">📄</span>
                    <span class="file-path">${file.path}</span>
                    ${file.size ? `<span class="file-size">${this.formatSize(file.size)}</span>` : ''}
                </div>
            `).join('');

            fileList.querySelectorAll('.file-item').forEach(item => {
                item.addEventListener('click', () => {
                    this.onSelect(item.dataset.path);
                    this.hide();
                });
            });
        } catch (error) {
            console.error('Failed to load files:', error);
            fileList.innerHTML = '<div class="error-message">Failed to load files</div>';
        }
    }

    formatSize(bytes) {
        if (bytes < 1024) return `${bytes}B`;
        if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)}KB`;
        return `${Math.round(bytes / 1024 / 1024)}MB`;
    }
}
