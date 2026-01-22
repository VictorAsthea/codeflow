export function initLogFilters() {
    const logsContainer = document.getElementById('logs-container');
    const filterButtons = document.querySelectorAll('.log-filter');
    const logCountElements = {};

    // Initialize log count elements
    filterButtons.forEach(button => {
        const filter = button.getAttribute('data-filter');
        logCountElements[filter] = document.getElementById(`log-count-${filter}`);
    });

    // Add click event to filter buttons
    filterButtons.forEach(button => {
        button.addEventListener('click', () => {
            const selectedFilter = button.getAttribute('data-filter');

            // Toggle active state
            filterButtons.forEach(btn => btn.classList.remove('active'));
            button.classList.add('active');

            // Apply filter
            const logEntries = document.querySelectorAll('.log-entry');
            let filteredCount = 0;

            logEntries.forEach(entry => {
                const entryType = entry.classList.contains(`log-${selectedFilter}`) || selectedFilter === 'all';
                entry.style.display = entryType ? 'block' : 'none';

                if (entryType && selectedFilter !== 'all') {
                    filteredCount++;
                } else if (selectedFilter === 'all') {
                    filteredCount = logEntries.length;
                }
            });

            // Update filter count
            logCountElements[selectedFilter].textContent = filteredCount;
        });
    });

    return {
        addLogEntry(type, message) {
            if (!['info', 'tool', 'bash', 'error'].includes(type)) {
                console.error('Invalid log type');
                return;
            }

            const logEntry = document.createElement('div');
            logEntry.classList.add('log-entry', `log-${type}`);
            logEntry.textContent = message;
            logsContainer.appendChild(logEntry);

            // Update counts
            filterButtons.forEach(button => {
                const filter = button.getAttribute('data-filter');
                const countElement = logCountElements[filter];
                const currentCount = parseInt(countElement.textContent, 10);

                if (filter === type || filter === 'all') {
                    countElement.textContent = currentCount + 1;
                }
            });
        },
        clearLogs() {
            logsContainer.innerHTML = '';
            filterButtons.forEach(button => {
                const filter = button.getAttribute('data-filter');
                logCountElements[filter].textContent = '0';
            });
        }
    };
}