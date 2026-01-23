export class FilePicker {
    constructor(triggerButton, options = {}) {
        this.triggerButton = triggerButton;
        this.options = {
            onSelect: options.onSelect || (() => {}),
            apiEndpoint: options.apiEndpoint || '/api/files/tree'
        };

        this.modal = null;
        this.selectedFiles = new Set();

        this.init();
    }

    init() {
        this.triggerButton.addEventListener('click', () => this.show());
    }

    async show() {
        await this.loadFileTree();
        this.createModal();
    }

    async loadFileTree() {
        try {
            const response = await fetch(this.options.apiEndpoint);
            if (!response.ok) throw new Error('Failed to load file tree');
            this.fileTree = await response.json();
        } catch (error) {
            console.error('File tree load error:', error);
            this.fileTree = { files: [] };
        }
    }

    createModal() {
        if (this.modal) {
            this.modal.remove();
        }

        this.modal = document.createElement('div');
        this.modal.className = 'file-picker-modal';
        this.modal.innerHTML = `
            <div class="file-picker-overlay"></div>
            <div class="file-picker-content">
                <div class="file-picker-header">
                    <h3>Select Files</h3>
                    <button class="close-btn">&times;</button>
                </div>
                <div class="file-picker-search">
                    <input type="text" placeholder="Search files..." class="search-input">
                </div>
                <div class="file-picker-tree"></div>
                <div class="file-picker-footer">
                    <button class="btn-cancel">Cancel</button>
                    <button class="btn-select">Select (${this.selectedFiles.size})</button>
                </div>
            </div>
        `;

        document.body.appendChild(this.modal);

        this.renderFileTree(this.fileTree.files || []);
        this.attachModalListeners();
    }

    renderFileTree(files, container = null) {
        if (!container) {
            container = this.modal.querySelector('.file-picker-tree');
            container.innerHTML = '';
        }

        const ul = document.createElement('ul');
        ul.className = 'file-tree';

        files.forEach(file => {
            const li = document.createElement('li');
            li.className = 'file-item';

            if (file.type === 'directory') {
                li.innerHTML = `
                    <div class="file-row">
                        <span class="folder-icon">📁</span>
                        <span class="file-name">${file.name}</span>
                    </div>
                `;
                if (file.children && file.children.length > 0) {
                    const childrenContainer = document.createElement('div');
                    childrenContainer.className = 'file-children';
                    this.renderFileTree(file.children, childrenContainer);
                    li.appendChild(childrenContainer);
                }
            } else {
                const isSelected = this.selectedFiles.has(file.path);
                li.innerHTML = `
                    <div class="file-row ${isSelected ? 'selected' : ''}" data-path="${file.path}">
                        <span class="file-icon">📄</span>
                        <span class="file-name">${file.name}</span>
                    </div>
                `;

                li.querySelector('.file-row').addEventListener('click', (e) => {
                    this.toggleFileSelection(file.path, e.currentTarget);
                });
            }

            ul.appendChild(li);
        });

        container.appendChild(ul);
    }

    toggleFileSelection(filePath, element) {
        if (this.selectedFiles.has(filePath)) {
            this.selectedFiles.delete(filePath);
            element.classList.remove('selected');
        } else {
            this.selectedFiles.add(filePath);
            element.classList.add('selected');
        }

        this.modal.querySelector('.btn-select').textContent = `Select (${this.selectedFiles.size})`;
    }

    attachModalListeners() {
        const overlay = this.modal.querySelector('.file-picker-overlay');
        const closeBtn = this.modal.querySelector('.close-btn');
        const cancelBtn = this.modal.querySelector('.btn-cancel');
        const selectBtn = this.modal.querySelector('.btn-select');
        const searchInput = this.modal.querySelector('.search-input');

        const close = () => {
            this.modal.remove();
            this.modal = null;
        };

        overlay.addEventListener('click', close);
        closeBtn.addEventListener('click', close);
        cancelBtn.addEventListener('click', close);

        selectBtn.addEventListener('click', () => {
            this.options.onSelect(Array.from(this.selectedFiles));
            this.selectedFiles.clear();
            close();
        });

        searchInput.addEventListener('input', (e) => {
            this.filterFiles(e.target.value);
        });
    }

    filterFiles(searchTerm) {
        const allFileRows = this.modal.querySelectorAll('.file-row');
        const lowerSearch = searchTerm.toLowerCase();

        allFileRows.forEach(row => {
            const fileName = row.querySelector('.file-name').textContent.toLowerCase();
            const matches = fileName.includes(lowerSearch);
            row.closest('.file-item').style.display = matches ? '' : 'none';
        });
    }

    destroy() {
        if (this.modal) {
            this.modal.remove();
        }
    }
}
