export class ImagePasteHandler {
    constructor(textarea, options = {}) {
        this.textarea = textarea;
        this.onPaste = options.onPaste || (() => {});
        this.maxSize = options.maxSize || 5 * 1024 * 1024;

        this.init();
    }

    init() {
        this.textarea.addEventListener('paste', this.handlePaste.bind(this));
    }

    async handlePaste(e) {
        const items = e.clipboardData?.items;
        if (!items) return;

        for (const item of items) {
            if (item.type.startsWith('image/')) {
                e.preventDefault();

                const file = item.getAsFile();
                if (!file) continue;

                if (file.size > this.maxSize) {
                    alert(`Image too large (max ${Math.round(this.maxSize / 1024 / 1024)}MB)`);
                    return;
                }

                try {
                    const base64 = await this.fileToBase64(file);
                    this.onPaste(base64, file.name || 'pasted-image.png');

                    const cursorPos = this.textarea.selectionStart;
                    const before = this.textarea.value.substring(0, cursorPos);
                    const after = this.textarea.value.substring(cursorPos);

                    this.textarea.value = `${before}\n[📷 Screenshot: ${file.name || 'pasted-image.png'}]\n${after}`;

                    const newPos = cursorPos + file.name.length + 20;
                    this.textarea.setSelectionRange(newPos, newPos);
                    this.textarea.focus();
                } catch (error) {
                    console.error('Failed to process image:', error);
                    alert('Failed to process image');
                }
            }
        }
    }

    fileToBase64(file) {
        return new Promise((resolve, reject) => {
            const reader = new FileReader();
            reader.onload = () => resolve(reader.result);
            reader.onerror = reject;
            reader.readAsDataURL(file);
        });
    }

    destroy() {
        this.textarea.removeEventListener('paste', this.handlePaste.bind(this));
    }
}
