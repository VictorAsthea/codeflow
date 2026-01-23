export class ImagePasteHandler {
    constructor(textarea, options = {}) {
        this.textarea = textarea;
        this.options = {
            onPaste: options.onPaste || (() => {}),
            maxSizeMB: options.maxSizeMB || 1,
            quality: options.quality || 0.8
        };

        this.init();
    }

    init() {
        this.textarea.addEventListener('paste', (e) => this.handlePaste(e));
    }

    async handlePaste(e) {
        const items = e.clipboardData?.items;
        if (!items) return;

        for (let i = 0; i < items.length; i++) {
            const item = items[i];

            if (item.type.indexOf('image') !== -1) {
                e.preventDefault();

                const blob = item.getAsFile();
                if (!blob) continue;

                const compressedDataUrl = await this.compressImage(blob);

                if (compressedDataUrl) {
                    this.options.onPaste(compressedDataUrl);
                }
            }
        }
    }

    async compressImage(blob) {
        return new Promise((resolve, reject) => {
            const reader = new FileReader();

            reader.onload = (e) => {
                const img = new Image();

                img.onload = () => {
                    const canvas = document.createElement('canvas');
                    const ctx = canvas.getContext('2d');

                    let { width, height } = img;
                    const maxDimension = 1920;

                    if (width > maxDimension || height > maxDimension) {
                        if (width > height) {
                            height = (height / width) * maxDimension;
                            width = maxDimension;
                        } else {
                            width = (width / height) * maxDimension;
                            height = maxDimension;
                        }
                    }

                    canvas.width = width;
                    canvas.height = height;

                    ctx.drawImage(img, 0, 0, width, height);

                    let quality = this.options.quality;
                    let dataUrl = canvas.toDataURL('image/jpeg', quality);

                    const maxSizeBytes = this.options.maxSizeMB * 1024 * 1024;
                    let currentSize = this.getBase64Size(dataUrl);

                    while (currentSize > maxSizeBytes && quality > 0.1) {
                        quality -= 0.1;
                        dataUrl = canvas.toDataURL('image/jpeg', quality);
                        currentSize = this.getBase64Size(dataUrl);
                    }

                    if (currentSize > maxSizeBytes) {
                        console.warn('Image still too large after compression');
                    }

                    resolve(dataUrl);
                };

                img.onerror = () => {
                    reject(new Error('Failed to load image'));
                };

                img.src = e.target.result;
            };

            reader.onerror = () => {
                reject(new Error('Failed to read file'));
            };

            reader.readAsDataURL(blob);
        });
    }

    getBase64Size(base64String) {
        const base64Data = base64String.split(',')[1] || base64String;
        const padding = (base64Data.match(/=/g) || []).length;
        return (base64Data.length * 0.75) - padding;
    }

    destroy() {
        this.textarea.removeEventListener('paste', this.handlePaste);
    }
}
