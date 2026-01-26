/**
 * Keyboard shortcuts manager
 */
class KeyboardManager {
  constructor() {
    this.shortcuts = new Map();
    this.enabled = true;
  }

  /**
   * Initialize keyboard manager
   */
  init() {
    document.addEventListener('keydown', (e) => {
      this.handleKeyDown(e);
    });

    this.registerDefaults();

    console.log('Keyboard manager initialized');
  }

  /**
   * Register default shortcuts
   */
  registerDefaults() {
    this.register('k', () => this.navigate('kanban'), 'Go to Kanban board');
    this.register('w', () => this.navigate('worktrees'), 'Go to Worktrees view');
    this.register('d', () => this.navigate('roadmap'), 'Go to Roadmap view');
    this.register('c', () => this.navigate('context'), 'Go to Context view');
    this.register('l', () => this.navigate('changelog'), 'Go to Changelog view');
    this.register('y', () => this.navigate('memory'), 'Go to Memory view');
    this.register('s', () => this.openSettings(), 'Open Settings');
    this.register('[', () => this.toggleSidebar(), 'Toggle sidebar');
    this.register('\\', () => this.toggleSidebar(), 'Toggle sidebar (alt)');
  }

  /**
   * Register a keyboard shortcut
   */
  register(key, callback, description = '') {
    this.shortcuts.set(key.toLowerCase(), {
      key,
      callback,
      description
    });
  }

  /**
   * Unregister a shortcut
   */
  unregister(key) {
    this.shortcuts.delete(key.toLowerCase());
  }

  /**
   * Handle keydown event
   */
  handleKeyDown(e) {
    if (!this.enabled) return;

    const target = e.target;
    if (target.tagName === 'INPUT' ||
        target.tagName === 'TEXTAREA' ||
        target.isContentEditable) {
      return;
    }

    if (e.ctrlKey || e.metaKey || e.altKey) {
      return;
    }

    const key = e.key.toLowerCase();
    const shortcut = this.shortcuts.get(key);

    if (shortcut) {
      e.preventDefault();
      shortcut.callback();
    }
  }

  /**
   * Navigate to view
   */
  navigate(view) {
    // Hide all views
    document.querySelectorAll('.view').forEach(v => v.classList.add('hidden'));

    // Show target view
    const targetView = document.getElementById(`${view}-view`);
    if (targetView) {
      targetView.classList.remove('hidden');
    }

    // Update nav active state
    const navItems = document.querySelectorAll('.nav-item');
    navItems.forEach(item => {
      const itemView = item.getAttribute('href')?.substring(1);
      item.classList.toggle('active', itemView === view);
    });

    // Dispatch event for view-specific initialization
    window.dispatchEvent(new CustomEvent('view-changed', {
      detail: { view }
    }));

    window.dispatchEvent(new CustomEvent('sidebar-navigate', {
      detail: { view }
    }));
  }

  /**
   * Toggle sidebar
   */
  toggleSidebar() {
    const sidebar = document.getElementById('sidebar');
    if (!sidebar) return;

    sidebar.classList.toggle('collapsed');

    const isCollapsed = sidebar.classList.contains('collapsed');
    localStorage.setItem('sidebar-collapsed', isCollapsed.toString());

    window.dispatchEvent(new CustomEvent('sidebar-toggled', {
      detail: { collapsed: isCollapsed }
    }));
  }

  /**
   * Toggle worktrees section focus
   */
  toggleWorktrees() {
    const worktreesList = document.getElementById('worktrees-list');
    const firstWorktree = worktreesList?.querySelector('.worktree-item');

    if (firstWorktree) {
      firstWorktree.click();
    } else {
      console.log('No active worktrees');
    }
  }

  /**
   * Open settings
   */
  openSettings() {
    const settingsBtn = document.getElementById('settings-btn');
    settingsBtn?.click();
  }

  /**
   * Enable shortcuts
   */
  enable() {
    this.enabled = true;
  }

  /**
   * Disable shortcuts
   */
  disable() {
    this.enabled = false;
  }

  /**
   * Get all registered shortcuts
   */
  getShortcuts() {
    return Array.from(this.shortcuts.values());
  }
}

export const keyboard = new KeyboardManager();

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', () => keyboard.init());
} else {
  keyboard.init();
}
