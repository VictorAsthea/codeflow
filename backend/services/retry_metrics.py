"""
Retry metrics tracking for Claude CLI execution.

This module provides the RetryMetrics class for tracking retry statistics
including success rates, recovery times, and error distributions.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime
from threading import Lock
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class RetryAttemptRecord:
    """Record of a single retry operation."""
    task_id: str
    started_at: datetime
    ended_at: datetime | None = None
    total_attempts: int = 1
    successful: bool = False
    error_types: list[str] = field(default_factory=list)
    recovery_time_seconds: float = 0.0

    def to_dict(self) -> dict:
        """Convert to dictionary for serialization."""
        return {
            "task_id": self.task_id,
            "started_at": self.started_at.isoformat(),
            "ended_at": self.ended_at.isoformat() if self.ended_at else None,
            "total_attempts": self.total_attempts,
            "successful": self.successful,
            "error_types": self.error_types,
            "recovery_time_seconds": self.recovery_time_seconds,
        }


class RetryMetrics:
    """
    Tracks metrics for the retry system including success rates and error distributions.

    This class is thread-safe and maintains aggregated statistics about retry operations
    that can be exposed through the API for monitoring purposes.

    Metrics tracked:
    - total_retries: Total number of operations that triggered retries
    - successful_retries: Operations that eventually succeeded after retry
    - failed_retries: Operations that failed after exhausting all retries
    - average_recovery_time: Mean time to recover from transient errors
    - error_type_distribution: Count of each error type encountered

    Usage:
        metrics = RetryMetrics()

        # Record a retry operation
        metrics.record_retry_start("task-123")
        # ... retry operation completes ...
        metrics.record_retry_end("task-123", successful=True, attempts=2, recovery_time=4.5)

        # Get aggregated metrics
        stats = metrics.get_metrics()
    """

    # Singleton instance
    _instance: "RetryMetrics | None" = None
    _instance_lock = Lock()

    def __new__(cls) -> "RetryMetrics":
        """Ensure singleton pattern for global metrics tracking."""
        with cls._instance_lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._initialized = False
            return cls._instance

    def __init__(self):
        """Initialize the metrics tracker."""
        if getattr(self, "_initialized", False):
            return

        self._lock = Lock()

        # Aggregated counters
        self._total_retries = 0
        self._successful_retries = 0
        self._failed_retries = 0

        # Recovery time tracking
        self._total_recovery_time = 0.0
        self._recovery_count = 0

        # Error type distribution
        self._error_type_counts: dict[str, int] = {}

        # Recent retry records for detailed analysis (keep last 100)
        self._recent_records: list[RetryAttemptRecord] = []
        self._max_recent_records = 100

        # In-flight retry operations
        self._active_retries: dict[str, RetryAttemptRecord] = {}

        # Timestamp tracking
        self._first_recorded_at: datetime | None = None
        self._last_recorded_at: datetime | None = None

        self._initialized = True
        logger.debug("RetryMetrics initialized")

    def record_retry_start(self, task_id: str, error_type: str | None = None) -> None:
        """
        Record the start of a retry operation.

        Args:
            task_id: The task identifier
            error_type: Optional error type that triggered the retry
        """
        with self._lock:
            record = RetryAttemptRecord(
                task_id=task_id,
                started_at=datetime.now(),
                error_types=[error_type] if error_type else [],
            )
            self._active_retries[task_id] = record

            if self._first_recorded_at is None:
                self._first_recorded_at = datetime.now()

            logger.debug(f"Retry started for task {task_id}")

    def record_retry_attempt(self, task_id: str, error_type: str) -> None:
        """
        Record an additional retry attempt for an ongoing operation.

        Args:
            task_id: The task identifier
            error_type: The error type encountered
        """
        with self._lock:
            record = self._active_retries.get(task_id)
            if record:
                record.total_attempts += 1
                if error_type and error_type not in record.error_types:
                    record.error_types.append(error_type)

                # Update error type distribution
                self._error_type_counts[error_type] = self._error_type_counts.get(error_type, 0) + 1

                logger.debug(f"Retry attempt {record.total_attempts} for task {task_id}: {error_type}")

    def record_retry_end(
        self,
        task_id: str,
        successful: bool,
        total_attempts: int | None = None,
        recovery_time: float | None = None,
        final_error_type: str | None = None,
    ) -> None:
        """
        Record the completion of a retry operation.

        Args:
            task_id: The task identifier
            successful: Whether the operation eventually succeeded
            total_attempts: Total number of attempts made (optional, uses tracked value if not provided)
            recovery_time: Time spent on retries in seconds (optional, calculated if not provided)
            final_error_type: The final error type if failed
        """
        with self._lock:
            now = datetime.now()
            record = self._active_retries.pop(task_id, None)

            if record:
                record.ended_at = now
                record.successful = successful

                if total_attempts is not None:
                    record.total_attempts = total_attempts

                if recovery_time is not None:
                    record.recovery_time_seconds = recovery_time
                else:
                    record.recovery_time_seconds = (now - record.started_at).total_seconds()

                if final_error_type and final_error_type not in record.error_types:
                    record.error_types.append(final_error_type)
            else:
                # Create a record if we didn't track the start
                record = RetryAttemptRecord(
                    task_id=task_id,
                    started_at=now,
                    ended_at=now,
                    total_attempts=total_attempts or 1,
                    successful=successful,
                    error_types=[final_error_type] if final_error_type else [],
                    recovery_time_seconds=recovery_time or 0.0,
                )

            # Update aggregated metrics
            self._total_retries += 1

            if successful:
                self._successful_retries += 1
                self._total_recovery_time += record.recovery_time_seconds
                self._recovery_count += 1
            else:
                self._failed_retries += 1
                if final_error_type:
                    self._error_type_counts[final_error_type] = self._error_type_counts.get(final_error_type, 0) + 1

            # Update error types for all encountered errors
            for error_type in record.error_types:
                if error_type:
                    self._error_type_counts[error_type] = self._error_type_counts.get(error_type, 0) + 1

            # Store in recent records
            self._recent_records.append(record)
            if len(self._recent_records) > self._max_recent_records:
                self._recent_records.pop(0)

            self._last_recorded_at = now

            status = "successful" if successful else "failed"
            logger.info(
                f"Retry {status} for task {task_id}: "
                f"{record.total_attempts} attempts, {record.recovery_time_seconds:.2f}s recovery time"
            )

    def record_error(self, error_type: str) -> None:
        """
        Record an error occurrence without a full retry operation context.

        Args:
            error_type: The error type encountered
        """
        with self._lock:
            self._error_type_counts[error_type] = self._error_type_counts.get(error_type, 0) + 1

            if self._first_recorded_at is None:
                self._first_recorded_at = datetime.now()
            self._last_recorded_at = datetime.now()

    @property
    def total_retries(self) -> int:
        """Total number of operations that triggered retries."""
        with self._lock:
            return self._total_retries

    @property
    def successful_retries(self) -> int:
        """Operations that eventually succeeded after retry."""
        with self._lock:
            return self._successful_retries

    @property
    def failed_retries(self) -> int:
        """Operations that failed after exhausting all retries."""
        with self._lock:
            return self._failed_retries

    @property
    def average_recovery_time(self) -> float:
        """Mean time to recover from transient errors (in seconds)."""
        with self._lock:
            if self._recovery_count == 0:
                return 0.0
            return self._total_recovery_time / self._recovery_count

    @property
    def success_rate(self) -> float:
        """Percentage of retry operations that succeeded (0-100)."""
        with self._lock:
            if self._total_retries == 0:
                return 0.0
            return (self._successful_retries / self._total_retries) * 100

    @property
    def error_type_distribution(self) -> dict[str, int]:
        """Count of each error type encountered."""
        with self._lock:
            return dict(self._error_type_counts)

    def get_metrics(self) -> dict[str, Any]:
        """
        Get all metrics as a dictionary suitable for API responses.

        Returns:
            Dictionary containing all retry metrics
        """
        with self._lock:
            return {
                "total_retries": self._total_retries,
                "successful_retries": self._successful_retries,
                "failed_retries": self._failed_retries,
                "success_rate": (self._successful_retries / self._total_retries * 100) if self._total_retries > 0 else 0.0,
                "average_recovery_time": (self._total_recovery_time / self._recovery_count) if self._recovery_count > 0 else 0.0,
                "error_type_distribution": dict(self._error_type_counts),
                "active_retries": len(self._active_retries),
                "first_recorded_at": self._first_recorded_at.isoformat() if self._first_recorded_at else None,
                "last_recorded_at": self._last_recorded_at.isoformat() if self._last_recorded_at else None,
            }

    def get_recent_records(self, limit: int = 10) -> list[dict]:
        """
        Get recent retry records for detailed analysis.

        Args:
            limit: Maximum number of records to return

        Returns:
            List of retry records as dictionaries
        """
        with self._lock:
            records = self._recent_records[-limit:]
            return [r.to_dict() for r in reversed(records)]

    def reset(self) -> None:
        """Reset all metrics to initial state."""
        with self._lock:
            self._total_retries = 0
            self._successful_retries = 0
            self._failed_retries = 0
            self._total_recovery_time = 0.0
            self._recovery_count = 0
            self._error_type_counts.clear()
            self._recent_records.clear()
            self._active_retries.clear()
            self._first_recorded_at = None
            self._last_recorded_at = None
            logger.info("RetryMetrics reset")


# Global singleton instance
_metrics: RetryMetrics | None = None


def get_retry_metrics() -> RetryMetrics:
    """
    Get the global retry metrics instance.

    Returns:
        The singleton RetryMetrics instance
    """
    global _metrics
    if _metrics is None:
        _metrics = RetryMetrics()
    return _metrics


def record_retry_start(task_id: str, error_type: str | None = None) -> None:
    """Convenience function to record retry start."""
    get_retry_metrics().record_retry_start(task_id, error_type)


def record_retry_attempt(task_id: str, error_type: str) -> None:
    """Convenience function to record retry attempt."""
    get_retry_metrics().record_retry_attempt(task_id, error_type)


def record_retry_end(
    task_id: str,
    successful: bool,
    total_attempts: int | None = None,
    recovery_time: float | None = None,
    final_error_type: str | None = None,
) -> None:
    """Convenience function to record retry end."""
    get_retry_metrics().record_retry_end(
        task_id, successful, total_attempts, recovery_time, final_error_type
    )


def get_metrics_summary() -> dict[str, Any]:
    """Convenience function to get metrics summary."""
    return get_retry_metrics().get_metrics()
