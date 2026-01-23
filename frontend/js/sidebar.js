import { API } from './api.js';

/**
 * Sidebar navigation manager
 */
class Sidebar {
  constructor() {
    this.sidebar = null;
    this.toggleBtn = null;
    this.isCollapsed = false;
    this.currentView = 'kanban';
    this.worktrees = [];
    this.refreshInterval = null;
  }

  /**
   * Initialize sidebar
   */
  init() {
    this.sidebar = document.getElementById('sidebar');
    this.toggleBtn = this.sidebar?.querySelector('.sidebar-toggle');

    if (!this.sidebar) {
      console.error('Sidebar element not found');
      return;
    }

    this.loadCollapsedState();
    this.setupToggle();
    this.setupNavigation();
    this.setupWorktrees();
    this.loadWorktrees();
    this.startAutoRefresh();

    console.log('Sidebar initialized');
  }

  /**
   * Load collapsed state from localStorage
   */
  loadCollapsedState() {
    this.isCollapsed = localStorage.getItem('sidebar-collapsed') === 'true';
    if (this.isCollapsed) {
      this.sidebar.classList.add('collapsed');
    }
  }

  /**
   * Setup toggle button
   */
  setupToggle() {
    this.toggleBtn?.addEventListener('click', () => {
      this.toggle();
    });
  }

  /**
   * Toggle sidebar collapsed state
   */
  toggle() {
    this.isCollapsed = !this.isCollapsed;
    this.sidebar.classList.toggle('collapsed', this.isCollapsed);
    localStorage.setItem('sidebar-collapsed', this.isCollapsed.toString());

    window.dispatchEvent(new CustomEvent('sidebar-toggled', {
      detail: { collapsed: this.isCollapsed }
    }));
  }

  /**
   * Collapse sidebar
   */
  collapse() {
    if (!this.isCollapsed) {
      this.toggle();
    }
  }

  /**
   * Expand sidebar
   */
  expand() {
    if (this.isCollapsed) {
      this.toggle();
    }
  }

  /**
   * Setup navigation items
   */
  setupNavigation() {
    const navItems = this.sidebar.querySelectorAll('.nav-item:not(.disabled)');

    navItems.forEach(item => {
      item.addEventListener('click', (e) => {
        e.preventDefault();
        const view = item.getAttribute('href')?.substring(1);
        if (view) {
          this.navigateTo(view);
        }
      });
    });

    const settingsBtn = this.sidebar.querySelector('a[href="#settings"]');
    settingsBtn?.addEventListener('click', (e) => {
      e.preventDefault();
      this.openSettings();
    });
  }

  /**
   * Navigate to view
   */
  navigateTo(view) {
    if (view === this.currentView) return;

    const navItems = this.sidebar.querySelectorAll('.nav-item');
    navItems.forEach(item => {
      const itemView = item.getAttribute('href')?.substring(1);
      item.classList.toggle('active', itemView === view);
    });

    this.currentView = view;

    window.dispatchEvent(new CustomEvent('sidebar-navigate', {
      detail: { view }
    }));

    console.log(`Navigated to: ${view}`);
  }

  /**
   * Open settings modal
   */
  openSettings() {
    const settingsBtn = document.getElementById('settings-btn');
    settingsBtn?.click();
  }

  /**
   * Setup worktrees section
   */
  setupWorktrees() {
    const worktreesHeader = this.sidebar.querySelector('.nav-section-header');
    worktreesHeader?.addEventListener('click', () => {
      console.log('Worktrees section clicked');
    });
  }

  /**
   * Load worktrees from API
   */
  async loadWorktrees() {
    try {
      const tasks = await API.tasks.list();

      this.worktrees = tasks
        .filter(task => task.worktree_path && task.status !== 'done')
        .map(task => ({
          id: task.id,
          title: task.title,
          branchName: task.branch_name,
          status: task.status,
          worktreePath: task.worktree_path
        }));

      this.renderWorktrees();
    } catch (error) {
      console.error('Failed to load worktrees:', error);
    }
  }

  /**
   * Render worktrees list
   */
  renderWorktrees() {
    const container = document.getElementById('worktrees-list');
    if (!container) return;

    if (this.worktrees.length === 0) {
      container.innerHTML = `
        <div class="worktree-empty">
          No active worktrees
        </div>
      `;
      return;
    }

    container.innerHTML = this.worktrees.map(wt => `
      <div class="worktree-item" data-task-id="${wt.id}" title="${wt.title}">
        <span class="branch-icon">🌿</span>
        <span class="branch-name">${this.escapeHtml(wt.branchName || wt.title)}</span>
        <span class="task-status ${wt.status}"></span>
      </div>
    `).join('');

    container.querySelectorAll('.worktree-item').forEach(item => {
      item.addEventListener('click', () => {
        const taskId = item.getAttribute('data-task-id');
        this.openTaskFromWorktree(taskId);
      });
    });
  }

  /**
   * Escape HTML to prevent XSS
   */
  escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
  }

  /**
   * Open task modal from worktree click
   */
  openTaskFromWorktree(taskId) {
    window.dispatchEvent(new CustomEvent('open-task-modal', {
      detail: { taskId }
    }));
  }

  /**
   * Start auto-refresh worktrees
   */
  startAutoRefresh() {
    this.refreshInterval = setInterval(() => {
      this.loadWorktrees();
    }, 10000);
  }

  /**
   * Stop auto-refresh
   */
  stopAutoRefresh() {
    if (this.refreshInterval) {
      clearInterval(this.refreshInterval);
      this.refreshInterval = null;
    }
  }

  /**
   * Cleanup
   */
  destroy() {
    this.stopAutoRefresh();
  }
}

export const sidebar = new Sidebar();

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', () => sidebar.init());
} else {
  sidebar.init();
}
