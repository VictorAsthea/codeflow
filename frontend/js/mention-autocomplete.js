export class MentionAutocomplete {
    constructor(textarea, options = {}) {
        this.textarea = textarea;
        this.onSelect = options.onSelect || (() => {});
        this.dropdown = null;
        this.currentSearch = '';
        this.mentionStart = -1;
        this.selectedIndex = -1;
        this.items = [];

        this.init();
    }

    init() {
        this.textarea.addEventListener('input', this.handleInput.bind(this));
        this.textarea.addEventListener('keydown', this.handleKeydown.bind(this));
        document.addEventListener('click', (e) => {
            if (this.dropdown && !this.dropdown.contains(e.target) && e.target !== this.textarea) {
                this.hideDropdown();
            }
        });
    }

    async handleInput(e) {
        const cursorPos = this.textarea.selectionStart;
        const text = this.textarea.value.substring(0, cursorPos);

        const match = text.match(/@([^\s]*)$/);

        if (match) {
            this.mentionStart = cursorPos - match[0].length;
            this.currentSearch = match[1];
            await this.showDropdown(match[1]);
        } else {
            this.hideDropdown();
        }
    }

    async showDropdown(query) {
        if (query.length < 1) {
            this.hideDropdown();
            return;
        }

        try {
            const response = await fetch(`/api/files/search?q=${encodeURIComponent(query)}`);
            const files = await response.json();

            if (files.length === 0) {
                this.hideDropdown();
                return;
            }

            this.items = files;
            this.selectedIndex = -1;

            if (!this.dropdown) {
                this.dropdown = document.createElement('div');
                this.dropdown.className = 'mention-dropdown';
                document.body.appendChild(this.dropdown);
            }

            const rect = this.textarea.getBoundingClientRect();
            const scrollTop = window.pageYOffset || document.documentElement.scrollTop;
            const scrollLeft = window.pageXOffset || document.documentElement.scrollLeft;

            this.dropdown.style.top = `${rect.bottom + scrollTop + 5}px`;
            this.dropdown.style.left = `${rect.left + scrollLeft}px`;
            this.dropdown.style.minWidth = `${rect.width}px`;

            this.dropdown.innerHTML = files.map((file, idx) =>
                `<div class="mention-item ${idx === this.selectedIndex ? 'selected' : ''}" data-index="${idx}" data-path="${file.path}">
                    <span class="mention-icon">📄</span>
                    <span class="mention-path">${file.path}</span>
                </div>`
            ).join('');

            this.dropdown.querySelectorAll('.mention-item').forEach(item => {
                item.addEventListener('click', () => {
                    this.selectFile(item.dataset.path);
                });
                item.addEventListener('mouseenter', () => {
                    this.selectedIndex = parseInt(item.dataset.index);
                    this.updateSelection();
                });
            });

            this.dropdown.classList.add('show');
        } catch (error) {
            console.error('Failed to fetch files:', error);
            this.hideDropdown();
        }
    }

    hideDropdown() {
        if (this.dropdown) {
            this.dropdown.classList.remove('show');
            this.selectedIndex = -1;
            this.items = [];
        }
    }

    selectFile(path) {
        const before = this.textarea.value.substring(0, this.mentionStart);
        const after = this.textarea.value.substring(this.textarea.selectionStart);

        this.textarea.value = `${before}@${path} ${after}`;
        const newPos = this.mentionStart + path.length + 2;
        this.textarea.setSelectionRange(newPos, newPos);

        this.hideDropdown();
        this.onSelect(path);
        this.textarea.focus();
    }

    handleKeydown(e) {
        if (!this.dropdown || !this.dropdown.classList.contains('show')) return;

        if (e.key === 'Escape') {
            this.hideDropdown();
            e.preventDefault();
            return;
        }

        if (e.key === 'ArrowDown') {
            e.preventDefault();
            this.selectedIndex = Math.min(this.selectedIndex + 1, this.items.length - 1);
            this.updateSelection();
            return;
        }

        if (e.key === 'ArrowUp') {
            e.preventDefault();
            this.selectedIndex = Math.max(this.selectedIndex - 1, 0);
            this.updateSelection();
            return;
        }

        if (e.key === 'Enter' && this.selectedIndex >= 0) {
            e.preventDefault();
            const selectedFile = this.items[this.selectedIndex];
            if (selectedFile) {
                this.selectFile(selectedFile.path);
            }
            return;
        }
    }

    updateSelection() {
        if (!this.dropdown) return;

        const items = this.dropdown.querySelectorAll('.mention-item');
        items.forEach((item, idx) => {
            if (idx === this.selectedIndex) {
                item.classList.add('selected');
                item.scrollIntoView({ block: 'nearest' });
            } else {
                item.classList.remove('selected');
            }
        });
    }

    destroy() {
        if (this.dropdown) {
            this.dropdown.remove();
            this.dropdown = null;
        }
    }
}
