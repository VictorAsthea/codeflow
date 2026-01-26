/**
 * Toast notification system for Codeflow
 * Provides non-intrusive notifications to replace alert() dialogs
 */

class ToastManager {
    constructor() {
        this.container = null;
        this.toasts = new Map();
        this.nextId = 1;
        this.initialized = false;
    }

    /**
     * Initialize the toast container
     */
    init() {
        if (this.initialized) return;

        // Create container element
        this.container = document.createElement('div');
        this.container.className = 'toast-container';
        this.container.setAttribute('aria-live', 'polite');
        this.container.setAttribute('aria-label', 'Notifications');

        // Insert container into DOM
        document.body.appendChild(this.container);
        this.initialized = true;
    }

    /**
     * Show a success toast notification
     * @param {string} message - The message to display
     * @param {Object} options - Additional options
     */
    success(message, options = {}) {
        return this.show(message, 'success', options);
    }

    /**
     * Show an error toast notification
     * @param {string} message - The message to display
     * @param {Object} options - Additional options
     */
    error(message, options = {}) {
        return this.show(message, 'error', { duration: 8000, ...options });
    }

    /**
     * Show an info toast notification
     * @param {string} message - The message to display
     * @param {Object} options - Additional options
     */
    info(message, options = {}) {
        return this.show(message, 'info', options);
    }

    /**
     * Show a warning toast notification
     * @param {string} message - The message to display
     * @param {Object} options - Additional options
     */
    warning(message, options = {}) {
        return this.show(message, 'warning', { duration: 7000, ...options });
    }

    /**
     * Show a toast notification
     * @param {string} message - The message to display
     * @param {string} type - Type of toast (success, error, info, warning)
     * @param {Object} options - Additional options
     */
    show(message, type = 'info', options = {}) {
        if (!this.initialized) {
            this.init();
        }

        const {
            duration = 5000,
            persistent = false,
            onClick = null,
            actionText = null,
            onAction = null
        } = options;

        const toastId = this.nextId++;
        const toast = this.createToastElement(toastId, message, type, {
            duration,
            persistent,
            onClick,
            actionText,
            onAction
        });

        // Add to container with animation
        this.container.appendChild(toast);
        this.toasts.set(toastId, toast);

        // Trigger slide-in animation
        requestAnimationFrame(() => {
            toast.classList.add('toast-visible');
        });

        // Auto-dismiss if not persistent
        if (!persistent && duration > 0) {
            setTimeout(() => {
                this.dismiss(toastId);
            }, duration);
        }

        return toastId;
    }

    /**
     * Create the toast DOM element
     * @param {number} id - Toast ID
     * @param {string} message - Message to display
     * @param {string} type - Toast type
     * @param {Object} options - Additional options
     */
    createToastElement(id, message, type, options) {
        const toast = document.createElement('div');
        toast.className = `toast toast-${type}`;
        toast.setAttribute('role', 'alert');
        toast.setAttribute('data-toast-id', id);

        // Create toast content
        const content = document.createElement('div');
        content.className = 'toast-content';

        // Icon
        const icon = document.createElement('div');
        icon.className = 'toast-icon';
        icon.innerHTML = this.getIcon(type);

        // Message
        const messageEl = document.createElement('div');
        messageEl.className = 'toast-message';
        messageEl.textContent = message;

        // Actions container
        const actions = document.createElement('div');
        actions.className = 'toast-actions';

        // Custom action button if provided
        if (options.actionText && options.onAction) {
            const actionBtn = document.createElement('button');
            actionBtn.className = 'toast-action-btn';
            actionBtn.textContent = options.actionText;
            actionBtn.addEventListener('click', (e) => {
                e.stopPropagation();
                options.onAction();
                this.dismiss(id);
            });
            actions.appendChild(actionBtn);
        }

        // Close button
        const closeBtn = document.createElement('button');
        closeBtn.className = 'toast-close-btn';
        closeBtn.setAttribute('aria-label', 'Close notification');
        closeBtn.innerHTML = '×';
        closeBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            this.dismiss(id);
        });
        actions.appendChild(closeBtn);

        // Assemble toast
        content.appendChild(icon);
        content.appendChild(messageEl);
        content.appendChild(actions);
        toast.appendChild(content);

        // Add click handler if provided
        if (options.onClick) {
            toast.style.cursor = 'pointer';
            toast.addEventListener('click', () => {
                options.onClick();
                this.dismiss(id);
            });
        }

        return toast;
    }

    /**
     * Get icon SVG for toast type
     * @param {string} type - Toast type
     */
    getIcon(type) {
        const icons = {
            success: `<svg viewBox="0 0 20 20" fill="currentColor">
                <path fill-rule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.707-9.293a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z" clip-rule="evenodd"/>
            </svg>`,
            error: `<svg viewBox="0 0 20 20" fill="currentColor">
                <path fill-rule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zM8.707 7.293a1 1 0 00-1.414 1.414L8.586 10l-1.293 1.293a1 1 0 101.414 1.414L10 11.414l1.293 1.293a1 1 0 001.414-1.414L11.414 10l1.293-1.293a1 1 0 00-1.414-1.414L10 8.586 8.707 7.293z" clip-rule="evenodd"/>
            </svg>`,
            warning: `<svg viewBox="0 0 20 20" fill="currentColor">
                <path fill-rule="evenodd" d="M8.257 3.099c.765-1.36 2.722-1.36 3.486 0l5.58 9.92c.75 1.334-.213 2.98-1.742 2.98H4.42c-1.53 0-2.493-1.646-1.743-2.98l5.58-9.92zM11 13a1 1 0 11-2 0 1 1 0 012 0zm-1-8a1 1 0 00-1 1v3a1 1 0 002 0V6a1 1 0 00-1-1z" clip-rule="evenodd"/>
            </svg>`,
            info: `<svg viewBox="0 0 20 20" fill="currentColor">
                <path fill-rule="evenodd" d="M18 10a8 8 0 11-16 0 8 8 0 0116 0zm-7-4a1 1 0 11-2 0 1 1 0 012 0zM9 9a1 1 0 000 2v3a1 1 0 001 1h1a1 1 0 100-2v-3a1 1 0 00-1-1H9z" clip-rule="evenodd"/>
            </svg>`
        };
        return icons[type] || icons.info;
    }

    /**
     * Dismiss a toast notification
     * @param {number} toastId - ID of the toast to dismiss
     */
    dismiss(toastId) {
        const toast = this.toasts.get(toastId);
        if (!toast) return;

        // Add fade-out class
        toast.classList.add('toast-dismissing');

        // Remove from DOM after animation
        setTimeout(() => {
            if (toast.parentNode) {
                toast.parentNode.removeChild(toast);
            }
            this.toasts.delete(toastId);
        }, 300);
    }

    /**
     * Dismiss all toast notifications
     */
    dismissAll() {
        Array.from(this.toasts.keys()).forEach(id => {
            this.dismiss(id);
        });
    }

    /**
     * Get number of active toasts
     */
    getActiveCount() {
        return this.toasts.size;
    }
}

// Create singleton instance
const toast = new ToastManager();

// Export for ES6 modules
export default toast;

// Create global function with method shortcuts
// Supports both: window.showToast('message', 'error') and window.showToast.error('message')
const showToastFn = (message, type = 'info', options = {}) => {
    const method = toast[type] || toast.info;
    return method.call(toast, message, options);
};

showToastFn.success = (message, options) => toast.success(message, options);
showToastFn.error = (message, options) => toast.error(message, options);
showToastFn.info = (message, options) => toast.info(message, options);
showToastFn.warning = (message, options) => toast.warning(message, options);
showToastFn.dismiss = (id) => toast.dismiss(id);
showToastFn.dismissAll = () => toast.dismissAll();

window.showToast = showToastFn;

// Auto-initialize on DOM ready
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => toast.init());
} else {
    toast.init();
}