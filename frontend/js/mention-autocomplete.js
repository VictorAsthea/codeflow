export class MentionAutocomplete {
    constructor(textarea, options = {}) {
        this.textarea = textarea;
        this.options = {
            onSelect: options.onSelect || (() => {}),
            apiEndpoint: options.apiEndpoint || '/api/files/search',
            trigger: options.trigger || '@'
        };

        this.dropdown = null;
        this.suggestions = [];
        this.selectedIndex = -1;
        this.mentionStart = -1;

        this.init();
    }

    init() {
        this.textarea.addEventListener('input', (e) => this.handleInput(e));
        this.textarea.addEventListener('keydown', (e) => this.handleKeydown(e));
        document.addEventListener('click', (e) => this.handleClickOutside(e));
    }

    async handleInput(e) {
        const cursorPos = this.textarea.selectionStart;
        const text = this.textarea.value.substring(0, cursorPos);
        const lastAtIndex = text.lastIndexOf(this.options.trigger);

        if (lastAtIndex === -1 || (lastAtIndex > 0 && /\S/.test(text[lastAtIndex - 1]))) {
            this.hideDropdown();
            return;
        }

        const searchTerm = text.substring(lastAtIndex + 1);

        if (searchTerm.includes(' ') || searchTerm.includes('\n')) {
            this.hideDropdown();
            return;
        }

        this.mentionStart = lastAtIndex;
        await this.searchFiles(searchTerm);
    }

    async searchFiles(query) {
        try {
            const response = await fetch(`${this.options.apiEndpoint}?q=${encodeURIComponent(query)}`);
            if (!response.ok) throw new Error('Failed to search files');

            const data = await response.json();
            this.suggestions = data.files || [];

            if (this.suggestions.length > 0) {
                this.showDropdown();
            } else {
                this.hideDropdown();
            }
        } catch (error) {
            console.error('File search error:', error);
            this.suggestions = [];
            this.hideDropdown();
        }
    }

    showDropdown() {
        if (!this.dropdown) {
            this.dropdown = document.createElement('div');
            this.dropdown.className = 'mention-autocomplete-dropdown';
            document.body.appendChild(this.dropdown);
        }

        this.dropdown.innerHTML = this.suggestions
            .map((file, index) => `
                <div class="mention-item ${index === this.selectedIndex ? 'selected' : ''}" data-index="${index}">
                    <span class="file-icon">📄</span>
                    <span class="file-path">${file}</span>
                </div>
            `)
            .join('');

        this.positionDropdown();

        this.dropdown.querySelectorAll('.mention-item').forEach(item => {
            item.addEventListener('click', () => {
                const index = parseInt(item.dataset.index);
                this.selectSuggestion(index);
            });
        });

        this.dropdown.style.display = 'block';
    }

    positionDropdown() {
        const textareaRect = this.textarea.getBoundingClientRect();
        const lineHeight = parseInt(window.getComputedStyle(this.textarea).lineHeight) || 20;

        const lines = this.textarea.value.substring(0, this.mentionStart).split('\n');
        const currentLine = lines.length;

        this.dropdown.style.left = `${textareaRect.left}px`;
        this.dropdown.style.top = `${textareaRect.top + (currentLine * lineHeight)}px`;
        this.dropdown.style.maxWidth = `${textareaRect.width}px`;
    }

    hideDropdown() {
        if (this.dropdown) {
            this.dropdown.style.display = 'none';
            this.dropdown.remove();
            this.dropdown = null;
        }
        this.selectedIndex = -1;
    }

    handleKeydown(e) {
        if (!this.dropdown || this.dropdown.style.display === 'none') {
            return;
        }

        switch (e.key) {
            case 'ArrowDown':
                e.preventDefault();
                this.selectedIndex = Math.min(this.selectedIndex + 1, this.suggestions.length - 1);
                this.updateDropdownSelection();
                break;

            case 'ArrowUp':
                e.preventDefault();
                this.selectedIndex = Math.max(this.selectedIndex - 1, 0);
                this.updateDropdownSelection();
                break;

            case 'Enter':
            case 'Tab':
                if (this.selectedIndex >= 0) {
                    e.preventDefault();
                    this.selectSuggestion(this.selectedIndex);
                }
                break;

            case 'Escape':
                e.preventDefault();
                this.hideDropdown();
                break;
        }
    }

    updateDropdownSelection() {
        const items = this.dropdown.querySelectorAll('.mention-item');
        items.forEach((item, index) => {
            item.classList.toggle('selected', index === this.selectedIndex);
        });

        if (this.selectedIndex >= 0 && items[this.selectedIndex]) {
            items[this.selectedIndex].scrollIntoView({ block: 'nearest' });
        }
    }

    selectSuggestion(index) {
        const file = this.suggestions[index];
        if (!file) return;

        const cursorPos = this.textarea.selectionStart;
        const textBefore = this.textarea.value.substring(0, this.mentionStart);
        const textAfter = this.textarea.value.substring(cursorPos);

        this.textarea.value = textBefore + this.options.trigger + file + ' ' + textAfter;

        const newCursorPos = textBefore.length + file.length + 2;
        this.textarea.setSelectionRange(newCursorPos, newCursorPos);

        this.options.onSelect(file);
        this.hideDropdown();

        this.textarea.focus();
    }

    handleClickOutside(e) {
        if (this.dropdown && !this.dropdown.contains(e.target) && e.target !== this.textarea) {
            this.hideDropdown();
        }
    }

    destroy() {
        this.hideDropdown();
        document.removeEventListener('click', this.handleClickOutside);
    }
}
