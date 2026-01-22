/**
 * PRO LOGS VIEWER
 * Parseur et afficheur de logs pour Claude CLI
 */

class LogEntry {
  constructor({ timestamp, type, summary, content, rawData }) {
    this.id = crypto.randomUUID();
    this.timestamp = timestamp || new Date().toISOString();
    this.type = type;
    this.summary = summary;
    this.content = content;
    this.rawData = rawData;
    this.collapsed = true;
  }
}

class LogViewer {
  constructor(containerSelector) {
    this.container = document.querySelector(containerSelector);
    this.entries = [];
    this.filteredEntries = [];
    this.currentFilter = 'all';
    this.searchQuery = '';
    this.autoScroll = true;

    this.init();
  }

  init() {
    if (!this.container) {
      console.error('LogViewer: Container not found');
      return;
    }

    this.setupEventListeners();
    this.render();
  }

  setupEventListeners() {
    const parent = this.container.closest('.log-viewer');
    if (!parent) return;

    // Filtres pills
    const filterPills = parent.querySelectorAll('.log-filter-pill');
    filterPills.forEach(pill => {
      pill.addEventListener('click', () => {
        const type = pill.dataset.type;
        this.filterByType(type);

        // Toggle active class
        filterPills.forEach(p => p.classList.remove('active'));
        pill.classList.add('active');
      });
    });

    // Recherche
    const searchInput = parent.querySelector('.log-search');
    if (searchInput) {
      let searchTimeout;
      searchInput.addEventListener('input', (e) => {
        clearTimeout(searchTimeout);
        searchTimeout = setTimeout(() => {
          this.searchLogs(e.target.value);
        }, 300);
      });
    }

    // Expand/Collapse All
    const expandAllBtn = parent.querySelector('.btn-expand-all');
    const collapseAllBtn = parent.querySelector('.btn-collapse-all');

    if (expandAllBtn) {
      expandAllBtn.addEventListener('click', () => this.expandAll());
    }

    if (collapseAllBtn) {
      collapseAllBtn.addEventListener('click', () => this.collapseAll());
    }

    // Auto-scroll toggle
    const autoScrollToggle = parent.querySelector('.log-auto-scroll-toggle');
    if (autoScrollToggle) {
      autoScrollToggle.addEventListener('click', () => {
        this.autoScroll = !this.autoScroll;
        autoScrollToggle.classList.toggle('active', this.autoScroll);
      });
    }

    // Scroll to bottom button
    const scrollToBottomBtn = parent.querySelector('.log-scroll-to-bottom');
    if (scrollToBottomBtn) {
      scrollToBottomBtn.addEventListener('click', () => {
        this.scrollToBottom();
      });
    }

    // Détection scroll manuel
    this.container.addEventListener('scroll', () => {
      const isAtBottom = this.container.scrollHeight - this.container.scrollTop <= this.container.clientHeight + 50;

      if (!isAtBottom) {
        this.autoScroll = false;
        if (autoScrollToggle) {
          autoScrollToggle.classList.remove('active');
        }
      }

      // Show/hide scroll to bottom button
      if (scrollToBottomBtn) {
        scrollToBottomBtn.classList.toggle('hidden', isAtBottom);
      }
    });

    // Event delegation pour les toggles de log entries
    this.container.addEventListener('click', (e) => {
      const header = e.target.closest('.log-entry-header');
      if (header) {
        const entryElement = header.closest('.log-entry');
        const entryId = entryElement.dataset.entryId;
        this.toggleEntry(entryId);
      }
    });
  }

  /**
   * Parse le stream JSON de Claude CLI
   */
  parseClaudeStream(jsonStream) {
    const lines = jsonStream.split('\n').filter(line => line.trim());
    const entries = [];

    lines.forEach(line => {
      try {
        const data = JSON.parse(line);
        const entry = this.parseLogData(data);
        if (entry) {
          entries.push(entry);
        }
      } catch (e) {
        // Si ce n'est pas du JSON, créer une entry info basique
        if (line.trim()) {
          entries.push(new LogEntry({
            type: 'info',
            summary: line.substring(0, 100),
            content: line,
            rawData: { text: line }
          }));
        }
      }
    });

    return entries;
  }

  /**
   * Parse un objet de log et retourne une LogEntry
   */
  parseLogData(data) {
    if (!data) return null;

    const type = data.type || 'info';
    let logType = 'info';
    let summary = '';
    let content = '';

    switch (type) {
      case 'assistant':
        logType = 'info';
        summary = this.truncate(data.content || data.text || 'Assistant message', 100);
        content = data.content || data.text || '';
        break;

      case 'tool_use':
        const toolName = (data.name || '').toLowerCase();
        logType = this.mapToolToType(toolName);
        summary = `${data.name || 'Tool'}: ${this.formatToolInput(data.input)}`;
        content = JSON.stringify(data.input || {}, null, 2);
        break;

      case 'tool_result':
        logType = 'tool';
        summary = 'Tool Result';
        content = typeof data.content === 'string' ? data.content : JSON.stringify(data.content, null, 2);
        break;

      case 'error':
        logType = 'error';
        summary = data.message || 'Error occurred';
        content = data.stack || data.details || data.message || JSON.stringify(data, null, 2);
        break;

      default:
        // Fallback pour les types inconnus
        logType = 'info';
        summary = data.message || data.summary || JSON.stringify(data).substring(0, 100);
        content = JSON.stringify(data, null, 2);
    }

    return new LogEntry({
      timestamp: data.timestamp || new Date().toISOString(),
      type: logType,
      summary,
      content,
      rawData: data
    });
  }

  /**
   * Mappe le nom d'un tool vers un type de log
   */
  mapToolToType(toolName) {
    if (!toolName) return 'tool';

    if (toolName.includes('read') || toolName.includes('grep') || toolName.includes('glob')) {
      return 'read';
    }
    if (toolName.includes('write') || toolName.includes('edit')) {
      return 'write';
    }
    if (toolName.includes('bash') || toolName.includes('command') || toolName.includes('shell')) {
      return 'bash';
    }

    return 'tool';
  }

  /**
   * Formate l'input d'un tool pour l'affichage
   */
  formatToolInput(input) {
    if (!input) return '';

    if (input.file_path) {
      return input.file_path;
    }
    if (input.command) {
      return input.command.substring(0, 50);
    }
    if (input.pattern) {
      return `Pattern: ${input.pattern}`;
    }

    const str = JSON.stringify(input);
    return str.length > 50 ? str.substring(0, 50) + '...' : str;
  }

  /**
   * Charge les logs depuis un stream JSON ou un array
   */
  loadLogs(data) {
    if (typeof data === 'string') {
      this.entries = this.parseClaudeStream(data);
    } else if (Array.isArray(data)) {
      this.entries = data.map(item => {
        if (item instanceof LogEntry) {
          return item;
        }
        return this.parseLogData(item);
      }).filter(Boolean);
    } else {
      console.error('LogViewer: Invalid data format');
      return;
    }

    this.applyFilters();
    this.render();

    if (this.autoScroll) {
      this.scrollToBottom();
    }
  }

  /**
   * Ajoute une nouvelle entry
   */
  addEntry(data) {
    let entry;

    if (data instanceof LogEntry) {
      entry = data;
    } else if (typeof data === 'string') {
      const parsed = this.parseClaudeStream(data);
      entry = parsed[0];
    } else {
      entry = this.parseLogData(data);
    }

    if (entry) {
      this.entries.push(entry);
      this.applyFilters();
      this.renderEntry(entry);
      this.updateCounter();

      if (this.autoScroll) {
        this.scrollToBottom();
      }
    }
  }

  /**
   * Filtre par type
   */
  filterByType(type) {
    this.currentFilter = type;
    this.applyFilters();
    this.render();
  }

  /**
   * Recherche textuelle
   */
  searchLogs(query) {
    this.searchQuery = query.toLowerCase();
    this.applyFilters();
    this.render();
  }

  /**
   * Applique les filtres et la recherche
   */
  applyFilters() {
    this.filteredEntries = this.entries.filter(entry => {
      // Filtre par type
      if (this.currentFilter !== 'all' && entry.type !== this.currentFilter) {
        return false;
      }

      // Recherche textuelle
      if (this.searchQuery) {
        const summary = (entry.summary || '').toLowerCase();
        const content = (entry.content || '').toLowerCase();

        if (!summary.includes(this.searchQuery) && !content.includes(this.searchQuery)) {
          return false;
        }
      }

      return true;
    });
  }

  /**
   * Expand toutes les entries
   */
  expandAll() {
    this.entries.forEach(entry => entry.collapsed = false);
    this.render();
  }

  /**
   * Collapse toutes les entries
   */
  collapseAll() {
    this.entries.forEach(entry => entry.collapsed = true);
    this.render();
  }

  /**
   * Toggle une entry spécifique
   */
  toggleEntry(entryId) {
    const entry = this.entries.find(e => e.id === entryId);
    if (entry) {
      entry.collapsed = !entry.collapsed;

      // Re-render uniquement cette entry
      const entryElement = this.container.querySelector(`[data-entry-id="${entryId}"]`);
      if (entryElement) {
        entryElement.classList.toggle('collapsed', entry.collapsed);
      }
    }
  }

  /**
   * Scroll vers le bas
   */
  scrollToBottom() {
    this.container.scrollTop = this.container.scrollHeight;
  }

  /**
   * Obtient l'icône pour un type
   */
  getIcon(type) {
    const icons = {
      info: '💬',
      tool: '🔧',
      read: '📖',
      write: '✏️',
      bash: '⚡',
      error: '❌'
    };
    return icons[type] || '📄';
  }

  /**
   * Formate un timestamp
   */
  formatTimestamp(timestamp) {
    try {
      const date = new Date(timestamp);
      const hours = String(date.getHours()).padStart(2, '0');
      const minutes = String(date.getMinutes()).padStart(2, '0');
      const seconds = String(date.getSeconds()).padStart(2, '0');
      return `${hours}:${minutes}:${seconds}`;
    } catch (e) {
      return timestamp;
    }
  }

  /**
   * Détecte le langage pour syntax highlighting
   */
  detectLanguage(content) {
    if (!content) return 'plaintext';

    const trimmed = content.trim();

    if (trimmed.startsWith('{') || trimmed.startsWith('[')) {
      return 'json';
    }
    if (trimmed.includes('def ') || trimmed.includes('import ')) {
      return 'python';
    }
    if (trimmed.includes('function ') || trimmed.includes('const ') || trimmed.includes('let ')) {
      return 'javascript';
    }
    if (trimmed.includes('cd ') || trimmed.includes('ls ') || trimmed.includes('git ')) {
      return 'bash';
    }

    return 'plaintext';
  }

  /**
   * Échappe le HTML
   */
  escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
  }

  /**
   * Tronque un texte
   */
  truncate(text, maxLength) {
    if (!text) return '';
    if (text.length <= maxLength) return text;
    return text.substring(0, maxLength) + '...';
  }

  /**
   * Render une entry
   */
  renderEntry(entry) {
    const isVisible = this.filteredEntries.includes(entry);

    const html = `
      <div class="log-entry log-${entry.type} ${entry.collapsed ? 'collapsed' : ''} ${isVisible ? '' : 'hidden'}"
           data-entry-id="${entry.id}">
        <div class="log-entry-header">
          <span class="log-icon">${this.getIcon(entry.type)}</span>
          <span class="log-timestamp">${this.formatTimestamp(entry.timestamp)}</span>
          <span class="log-badge log-badge-${entry.type}">${entry.type}</span>
          <span class="log-summary">${this.escapeHtml(entry.summary)}</span>
          <span class="log-toggle">▼</span>
        </div>
        <div class="log-entry-body">
          <pre><code class="language-${this.detectLanguage(entry.content)}">${this.escapeHtml(entry.content)}</code></pre>
        </div>
      </div>
    `;

    this.container.insertAdjacentHTML('beforeend', html);

    // Appliquer syntax highlighting si highlight.js est disponible
    if (window.hljs) {
      const codeBlock = this.container.querySelector(`[data-entry-id="${entry.id}"] code`);
      if (codeBlock) {
        hljs.highlightElement(codeBlock);
      }
    }
  }

  /**
   * Render toutes les entries
   */
  render() {
    // Clear container
    this.container.innerHTML = '';

    if (this.filteredEntries.length === 0) {
      this.renderEmptyState();
    } else {
      this.filteredEntries.forEach(entry => {
        this.renderEntry(entry);
      });
    }

    this.updateCounter();
  }

  /**
   * Render l'état vide
   */
  renderEmptyState() {
    const message = this.entries.length === 0
      ? 'No logs available yet'
      : 'No logs match your filters';

    const html = `
      <div class="log-empty-state">
        <div class="log-empty-state-icon">📭</div>
        <div class="log-empty-state-text">${message}</div>
        <div class="log-empty-state-subtext">Logs will appear here as the task runs</div>
      </div>
    `;

    this.container.innerHTML = html;
  }

  /**
   * Met à jour le counter
   */
  updateCounter() {
    const parent = this.container.closest('.log-viewer');
    if (!parent) return;

    const counter = parent.querySelector('.log-counter');
    if (counter) {
      counter.textContent = `${this.filteredEntries.length}/${this.entries.length} entries`;
    }
  }

  /**
   * Obtient les entries visibles
   */
  getVisibleEntries() {
    return this.filteredEntries;
  }

  /**
   * Clear tous les logs
   */
  clear() {
    this.entries = [];
    this.filteredEntries = [];
    this.render();
  }
}

// Export pour utilisation dans d'autres modules
if (typeof module !== 'undefined' && module.exports) {
  module.exports = { LogViewer, LogEntry };
}
