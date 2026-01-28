"""
Intelligent retry system for Claude CLI execution.

This module provides a RetryManager class that handles automatic retries
for recoverable errors with exponential backoff and jitter to avoid
thundering herd problems.
"""

import asyncio
import logging
import random
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from threading import Lock
from typing import Any, Awaitable, Callable, TypeVar

from backend.models import (
    RecoverableErrorType,
    RetryConfig,
    RetryState,
    RECOVERABLE_HTTP_CODES,
    FATAL_HTTP_CODES,
)

logger = logging.getLogger(__name__)

T = TypeVar("T")


class ErrorCategory(str, Enum):
    """Classification of errors for retry decisions."""
    RECOVERABLE = "recoverable"
    FATAL = "fatal"
    UNKNOWN = "unknown"


class CircuitState(str, Enum):
    """States for the circuit breaker pattern."""
    CLOSED = "closed"      # Normal operation, requests pass through
    OPEN = "open"          # Circuit is tripped, requests are blocked
    HALF_OPEN = "half_open"  # Testing if system has recovered


@dataclass
class RetryError:
    """Structured error information from a failed execution."""
    error_type: str
    message: str
    http_code: int | None = None
    category: ErrorCategory = ErrorCategory.UNKNOWN
    original_exception: Exception | None = None
    timestamp: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> dict:
        """Convert to dictionary for storage/serialization."""
        return {
            "error_type": self.error_type,
            "message": self.message,
            "http_code": self.http_code,
            "category": self.category.value,
            "timestamp": self.timestamp.isoformat(),
        }


@dataclass
class RetryContext:
    """
    Tracks the state of retry attempts during a single execution.

    This is used internally by RetryManager to maintain state during
    an execution cycle. For persistence, this can be converted to/from RetryState.
    """
    config: RetryConfig
    attempt: int = 0
    errors: list[RetryError] = field(default_factory=list)
    started_at: datetime = field(default_factory=datetime.now)
    last_retry_at: datetime | None = None
    total_delay_time: float = 0.0

    @property
    def is_first_attempt(self) -> bool:
        """Check if this is the initial attempt (not a retry)."""
        return self.attempt == 0

    @property
    def retries_remaining(self) -> int:
        """Get the number of retries remaining."""
        return max(0, self.config.max_retries - self.attempt)

    @property
    def elapsed_time(self) -> float:
        """Get total elapsed time in seconds."""
        return (datetime.now() - self.started_at).total_seconds()

    @property
    def has_time_remaining(self) -> bool:
        """Check if there's time remaining within the total timeout."""
        return self.elapsed_time < self.config.max_total_timeout

    def to_retry_state(self) -> RetryState:
        """Convert to RetryState for persistence/API responses."""
        last_error = self.errors[-1] if self.errors else None
        return RetryState(
            attempt=self.attempt,
            max_attempts=self.config.max_retries + 1,  # +1 because max_retries is retry count, not total attempts
            last_error_type=last_error.error_type if last_error else None,
            last_error_message=last_error.message if last_error else None,
            last_http_code=last_error.http_code if last_error else None,
            next_retry_at=None,  # Will be set when scheduling
            total_retry_time=self.total_delay_time,
            error_history=[e.to_dict() for e in self.errors],
            started_at=self.started_at,
        )


@dataclass
class CircuitBreakerState:
    """Persistent state for circuit breaker serialization."""
    state: str
    failure_count: int
    last_failure_time: datetime | None
    opened_at: datetime | None
    half_open_successes: int

    def to_dict(self) -> dict:
        """Convert to dictionary for storage."""
        return {
            "state": self.state,
            "failure_count": self.failure_count,
            "last_failure_time": self.last_failure_time.isoformat() if self.last_failure_time else None,
            "opened_at": self.opened_at.isoformat() if self.opened_at else None,
            "half_open_successes": self.half_open_successes,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "CircuitBreakerState":
        """Create from dictionary."""
        return cls(
            state=data.get("state", CircuitState.CLOSED.value),
            failure_count=data.get("failure_count", 0),
            last_failure_time=datetime.fromisoformat(data["last_failure_time"]) if data.get("last_failure_time") else None,
            opened_at=datetime.fromisoformat(data["opened_at"]) if data.get("opened_at") else None,
            half_open_successes=data.get("half_open_successes", 0),
        )


class CircuitBreaker:
    """
    Circuit breaker pattern implementation to prevent cascading failures.

    The circuit breaker monitors failures across all tasks and temporarily
    disables retries when the system appears to be unhealthy. This prevents
    wasting resources on retries when the underlying issue is systemic.

    States:
    - CLOSED: Normal operation. Requests pass through and failures are counted.
    - OPEN: Circuit is tripped. Requests are blocked for a recovery period.
    - HALF_OPEN: Testing recovery. A limited number of requests pass through.

    Usage:
        breaker = CircuitBreaker(failure_threshold=5, recovery_timeout=60.0)

        if breaker.can_execute():
            try:
                result = await some_operation()
                breaker.record_success()
            except Exception as e:
                breaker.record_failure()
                raise
        else:
            # Circuit is open, skip retry
            pass
    """

    def __init__(
        self,
        failure_threshold: int = 5,
        recovery_timeout: float = 60.0,
        half_open_max_calls: int = 3,
        enabled: bool = True,
    ):
        """
        Initialize the circuit breaker.

        Args:
            failure_threshold: Number of consecutive failures before opening circuit
            recovery_timeout: Seconds to wait before transitioning to half-open
            half_open_max_calls: Number of successful calls in half-open to close circuit
            enabled: Whether the circuit breaker is active
        """
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.half_open_max_calls = half_open_max_calls
        self.enabled = enabled

        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._last_failure_time: datetime | None = None
        self._opened_at: datetime | None = None
        self._half_open_successes = 0
        self._lock = Lock()

        logger.debug(
            f"CircuitBreaker initialized: threshold={failure_threshold}, "
            f"recovery_timeout={recovery_timeout}s, enabled={enabled}"
        )

    @property
    def state(self) -> CircuitState:
        """Get the current circuit state (may trigger state transition)."""
        with self._lock:
            self._check_state_transition()
            return self._state

    @property
    def failure_count(self) -> int:
        """Get current failure count."""
        return self._failure_count

    @property
    def is_open(self) -> bool:
        """Check if circuit is currently open (blocking requests)."""
        return self.state == CircuitState.OPEN

    @property
    def is_closed(self) -> bool:
        """Check if circuit is closed (normal operation)."""
        return self.state == CircuitState.CLOSED

    @property
    def time_until_recovery(self) -> float | None:
        """Get seconds until circuit attempts recovery (None if not open)."""
        if self._state != CircuitState.OPEN or self._opened_at is None:
            return None
        elapsed = (datetime.now() - self._opened_at).total_seconds()
        remaining = self.recovery_timeout - elapsed
        return max(0.0, remaining)

    def _check_state_transition(self) -> None:
        """Check if state should transition based on timing."""
        if self._state == CircuitState.OPEN and self._opened_at:
            elapsed = (datetime.now() - self._opened_at).total_seconds()
            if elapsed >= self.recovery_timeout:
                self._transition_to_half_open()

    def _transition_to_open(self) -> None:
        """Transition circuit to OPEN state."""
        prev_state = self._state
        self._state = CircuitState.OPEN
        self._opened_at = datetime.now()
        self._half_open_successes = 0
        logger.warning(
            f"Circuit breaker OPENED after {self._failure_count} failures. "
            f"Recovery in {self.recovery_timeout}s. Previous state: {prev_state.value}"
        )

    def _transition_to_half_open(self) -> None:
        """Transition circuit to HALF_OPEN state."""
        self._state = CircuitState.HALF_OPEN
        self._half_open_successes = 0
        logger.info(
            f"Circuit breaker transitioning to HALF_OPEN. "
            f"Testing recovery with up to {self.half_open_max_calls} calls."
        )

    def _transition_to_closed(self) -> None:
        """Transition circuit to CLOSED state."""
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._opened_at = None
        self._half_open_successes = 0
        logger.info("Circuit breaker CLOSED. Normal operation resumed.")

    def can_execute(self) -> tuple[bool, str]:
        """
        Check if an execution attempt is allowed.

        Returns:
            Tuple of (allowed: bool, reason: str)
        """
        if not self.enabled:
            return True, "Circuit breaker disabled"

        with self._lock:
            self._check_state_transition()

            if self._state == CircuitState.CLOSED:
                return True, "Circuit closed - normal operation"

            if self._state == CircuitState.OPEN:
                remaining = self.time_until_recovery
                return False, f"Circuit open - recovery in {remaining:.1f}s"

            if self._state == CircuitState.HALF_OPEN:
                return True, "Circuit half-open - testing recovery"

            return True, "Unknown state - allowing execution"

    def record_failure(self, error: RetryError | None = None) -> None:
        """
        Record a failed execution.

        Args:
            error: Optional error information for logging
        """
        if not self.enabled:
            return

        with self._lock:
            self._failure_count += 1
            self._last_failure_time = datetime.now()

            error_info = f" ({error.error_type})" if error else ""
            logger.debug(
                f"Circuit breaker recorded failure{error_info}. "
                f"Count: {self._failure_count}/{self.failure_threshold}"
            )

            if self._state == CircuitState.HALF_OPEN:
                # Any failure in half-open immediately opens the circuit
                logger.warning("Failure in HALF_OPEN state - reopening circuit")
                self._transition_to_open()
            elif self._state == CircuitState.CLOSED:
                if self._failure_count >= self.failure_threshold:
                    self._transition_to_open()

    def record_success(self) -> None:
        """Record a successful execution."""
        if not self.enabled:
            return

        with self._lock:
            if self._state == CircuitState.HALF_OPEN:
                self._half_open_successes += 1
                logger.debug(
                    f"Circuit breaker recorded success in HALF_OPEN. "
                    f"Count: {self._half_open_successes}/{self.half_open_max_calls}"
                )
                if self._half_open_successes >= self.half_open_max_calls:
                    self._transition_to_closed()
            elif self._state == CircuitState.CLOSED:
                # Reset failure count on success in closed state
                if self._failure_count > 0:
                    logger.debug(f"Resetting failure count from {self._failure_count} to 0")
                    self._failure_count = 0

    def reset(self) -> None:
        """Manually reset the circuit breaker to closed state."""
        with self._lock:
            logger.info("Circuit breaker manually reset")
            self._transition_to_closed()

    def get_state(self) -> CircuitBreakerState:
        """Get the current state for persistence/API responses."""
        with self._lock:
            self._check_state_transition()
            return CircuitBreakerState(
                state=self._state.value,
                failure_count=self._failure_count,
                last_failure_time=self._last_failure_time,
                opened_at=self._opened_at,
                half_open_successes=self._half_open_successes,
            )

    def restore_state(self, state: CircuitBreakerState) -> None:
        """Restore state from persistence."""
        with self._lock:
            self._state = CircuitState(state.state)
            self._failure_count = state.failure_count
            self._last_failure_time = state.last_failure_time
            self._opened_at = state.opened_at
            self._half_open_successes = state.half_open_successes
            logger.debug(f"Circuit breaker state restored: {self._state.value}")


# Error patterns for classification
TIMEOUT_PATTERNS = [
    r"timeout",
    r"timed?\s*out",
    r"deadline\s*exceeded",
    r"request\s*timeout",
    r"ETIMEDOUT",
]

CONNECTION_ERROR_PATTERNS = [
    r"connection\s*(error|refused|reset|closed)",
    r"ECONNREFUSED",
    r"ECONNRESET",
    r"EPIPE",
    r"network\s*(error|unreachable)",
    r"socket\s*error",
    r"EOF\s*error",
]

RATE_LIMIT_PATTERNS = [
    r"rate\s*limit",
    r"too\s*many\s*requests",
    r"throttl",
    r"quota\s*exceeded",
    r"429",
]

DNS_ERROR_PATTERNS = [
    r"dns\s*(error|failed|lookup)",
    r"ENOTFOUND",
    r"getaddrinfo",
    r"name\s*resolution",
]

SSL_ERROR_PATTERNS = [
    r"ssl\s*(error|handshake|certificate)",
    r"tls\s*error",
    r"certificate\s*(error|verify|invalid)",
    r"CERT_",
]

AUTH_ERROR_PATTERNS = [
    r"unauthorized",
    r"authentication\s*failed",
    r"invalid\s*(token|credentials|api\s*key)",
    r"401",
    r"403",
]

BAD_REQUEST_PATTERNS = [
    r"bad\s*request",
    r"invalid\s*request",
    r"malformed",
    r"validation\s*error",
    r"400",
]


class RetryManager:
    """
    Manages intelligent retry logic for Claude CLI execution.

    Features:
    - Error classification (recoverable vs fatal)
    - Exponential backoff with jitter
    - Total timeout enforcement
    - Circuit breaker pattern for system-wide failure protection
    - Callback hooks for notifications

    Usage:
        config = RetryConfig(max_retries=4, base_delay=2.0)
        manager = RetryManager(config)

        async def my_operation():
            # ... operation that might fail
            pass

        result = await manager.execute_with_retry(
            my_operation,
            on_retry=lambda ctx: print(f"Retry {ctx.attempt}/{config.max_retries}")
        )
    """

    # Global circuit breaker instance shared across all RetryManager instances
    _global_circuit_breaker: CircuitBreaker | None = None
    _circuit_breaker_lock = Lock()

    def __init__(
        self,
        config: RetryConfig | None = None,
        circuit_breaker: CircuitBreaker | None = None,
    ):
        """
        Initialize RetryManager with configuration.

        Args:
            config: RetryConfig instance. If None, uses default settings.
            circuit_breaker: Optional CircuitBreaker instance. If None, uses global instance.
        """
        self.config = config or RetryConfig()
        self._compile_patterns()

        # Use provided circuit breaker or get/create global instance
        if circuit_breaker is not None:
            self.circuit_breaker = circuit_breaker
        else:
            self.circuit_breaker = self._get_global_circuit_breaker()

    @classmethod
    def _get_global_circuit_breaker(cls) -> CircuitBreaker:
        """Get or create the global circuit breaker instance."""
        with cls._circuit_breaker_lock:
            if cls._global_circuit_breaker is None:
                from backend.config import settings
                cls._global_circuit_breaker = CircuitBreaker(
                    failure_threshold=settings.circuit_breaker_failure_threshold,
                    recovery_timeout=settings.circuit_breaker_recovery_timeout,
                    enabled=settings.circuit_breaker_enabled,
                )
                logger.info(
                    f"Global circuit breaker initialized: threshold={settings.circuit_breaker_failure_threshold}, "
                    f"recovery_timeout={settings.circuit_breaker_recovery_timeout}s, enabled={settings.circuit_breaker_enabled}"
                )
            return cls._global_circuit_breaker

    @classmethod
    def reset_global_circuit_breaker(cls) -> None:
        """Reset the global circuit breaker (useful for testing or manual recovery)."""
        with cls._circuit_breaker_lock:
            if cls._global_circuit_breaker is not None:
                cls._global_circuit_breaker.reset()
                logger.info("Global circuit breaker reset")

    def _compile_patterns(self) -> None:
        """Pre-compile regex patterns for error classification."""
        self._timeout_re = re.compile(
            "|".join(TIMEOUT_PATTERNS), re.IGNORECASE
        )
        self._connection_re = re.compile(
            "|".join(CONNECTION_ERROR_PATTERNS), re.IGNORECASE
        )
        self._rate_limit_re = re.compile(
            "|".join(RATE_LIMIT_PATTERNS), re.IGNORECASE
        )
        self._dns_re = re.compile(
            "|".join(DNS_ERROR_PATTERNS), re.IGNORECASE
        )
        self._ssl_re = re.compile(
            "|".join(SSL_ERROR_PATTERNS), re.IGNORECASE
        )
        self._auth_re = re.compile(
            "|".join(AUTH_ERROR_PATTERNS), re.IGNORECASE
        )
        self._bad_request_re = re.compile(
            "|".join(BAD_REQUEST_PATTERNS), re.IGNORECASE
        )

    def classify_error(
        self,
        error: Exception | str,
        http_code: int | None = None
    ) -> RetryError:
        """
        Classify an error and determine if it's recoverable.

        Args:
            error: The exception or error message to classify
            http_code: Optional HTTP status code if available

        Returns:
            RetryError with classification information
        """
        message = str(error)
        error_type = "unknown"
        category = ErrorCategory.UNKNOWN

        # First check HTTP status code if provided
        if http_code is not None:
            if http_code in RECOVERABLE_HTTP_CODES:
                if http_code == 429:
                    error_type = RecoverableErrorType.RATE_LIMIT.value
                else:
                    error_type = RecoverableErrorType.SERVER_ERROR.value
                category = ErrorCategory.RECOVERABLE
                logger.debug(f"Classified HTTP {http_code} as recoverable ({error_type})")
                return RetryError(
                    error_type=error_type,
                    message=message,
                    http_code=http_code,
                    category=category,
                    original_exception=error if isinstance(error, Exception) else None,
                )
            elif http_code in FATAL_HTTP_CODES:
                error_type = "fatal_http_error"
                category = ErrorCategory.FATAL
                logger.debug(f"Classified HTTP {http_code} as fatal")
                return RetryError(
                    error_type=error_type,
                    message=message,
                    http_code=http_code,
                    category=category,
                    original_exception=error if isinstance(error, Exception) else None,
                )

        # Check against recoverable patterns
        if self._timeout_re.search(message):
            error_type = RecoverableErrorType.TIMEOUT.value
            category = ErrorCategory.RECOVERABLE
        elif self._rate_limit_re.search(message):
            error_type = RecoverableErrorType.RATE_LIMIT.value
            category = ErrorCategory.RECOVERABLE
        elif self._connection_re.search(message):
            error_type = RecoverableErrorType.CONNECTION_ERROR.value
            category = ErrorCategory.RECOVERABLE
        elif self._dns_re.search(message):
            error_type = RecoverableErrorType.DNS_ERROR.value
            category = ErrorCategory.RECOVERABLE
        elif self._ssl_re.search(message):
            error_type = RecoverableErrorType.SSL_ERROR.value
            category = ErrorCategory.RECOVERABLE
        # Check against fatal patterns
        elif self._auth_re.search(message):
            error_type = "authentication_error"
            category = ErrorCategory.FATAL
        elif self._bad_request_re.search(message):
            error_type = "bad_request"
            category = ErrorCategory.FATAL

        # Check exception type for additional classification
        if isinstance(error, asyncio.TimeoutError):
            error_type = RecoverableErrorType.TIMEOUT.value
            category = ErrorCategory.RECOVERABLE
        elif isinstance(error, ConnectionError):
            error_type = RecoverableErrorType.CONNECTION_ERROR.value
            category = ErrorCategory.RECOVERABLE
        elif isinstance(error, OSError) and error.errno in (110, 111, 113):  # ETIMEDOUT, ECONNREFUSED, EHOSTUNREACH
            error_type = RecoverableErrorType.CONNECTION_ERROR.value
            category = ErrorCategory.RECOVERABLE

        logger.debug(f"Classified error as {error_type} ({category.value}): {message[:100]}...")

        return RetryError(
            error_type=error_type,
            message=message,
            http_code=http_code,
            category=category,
            original_exception=error if isinstance(error, Exception) else None,
        )

    def calculate_delay(self, attempt: int) -> float:
        """
        Calculate the delay before the next retry attempt.

        Uses exponential backoff with jitter to avoid thundering herd.
        Formula: delay = base_delay * (multiplier ^ attempt) * random(1 ± jitter)

        Args:
            attempt: Current attempt number (0-indexed)

        Returns:
            Delay in seconds
        """
        base = self.config.base_delay * (self.config.multiplier ** attempt)
        jitter_range = base * self.config.jitter_factor
        jitter = random.uniform(-jitter_range, jitter_range)
        delay = max(0.1, base + jitter)  # Minimum 100ms

        logger.debug(f"Calculated delay for attempt {attempt}: {delay:.2f}s (base={base:.2f}s, jitter={jitter:.2f}s)")
        return delay

    def should_retry(
        self,
        context: RetryContext,
        error: RetryError
    ) -> tuple[bool, str]:
        """
        Determine if a retry should be attempted.

        Args:
            context: Current retry context
            error: The error that occurred

        Returns:
            Tuple of (should_retry: bool, reason: str)
        """
        # Check circuit breaker first (system-wide health check)
        can_execute, circuit_reason = self.circuit_breaker.can_execute()
        if not can_execute:
            return False, f"Circuit breaker: {circuit_reason}"

        # Check if error is fatal
        if error.category == ErrorCategory.FATAL:
            return False, f"Fatal error: {error.error_type}"

        # Check if we've exhausted retries
        if context.retries_remaining <= 0:
            return False, f"Max retries ({self.config.max_retries}) exhausted"

        # Check total timeout
        if not context.has_time_remaining:
            return False, f"Total timeout ({self.config.max_total_timeout}s) exceeded"

        # Check if error type is configured for retry
        recoverable_types = [e.value for e in self.config.recoverable_error_types]
        if error.error_type not in recoverable_types and error.category != ErrorCategory.RECOVERABLE:
            return False, f"Error type '{error.error_type}' not configured for retry"

        # Check if HTTP code is configured for retry (if applicable)
        if error.http_code and error.http_code not in self.config.recoverable_http_codes:
            if error.category != ErrorCategory.RECOVERABLE:
                return False, f"HTTP {error.http_code} not configured for retry"

        return True, "Error is recoverable"

    async def execute_with_retry(
        self,
        operation: Callable[[], Awaitable[T]],
        on_retry: Callable[[RetryContext, RetryError, float], Awaitable[None] | None] | None = None,
        on_success: Callable[[RetryContext, T], Awaitable[None] | None] | None = None,
        on_failure: Callable[[RetryContext, RetryError], Awaitable[None] | None] | None = None,
        task_id: str | None = None,
    ) -> tuple[bool, T | None, RetryContext]:
        """
        Execute an async operation with automatic retry on recoverable errors.

        Args:
            operation: Async function to execute (no arguments)
            on_retry: Callback before each retry (context, error, delay)
            on_success: Callback on successful completion
            on_failure: Callback on final failure (all retries exhausted)
            task_id: Optional task ID for metrics tracking

        Returns:
            Tuple of (success: bool, result: T | None, context: RetryContext)

        Example:
            async def call_claude():
                return await claude_cli.run(...)

            success, result, context = await manager.execute_with_retry(
                call_claude,
                on_retry=lambda ctx, err, delay: notify_user(f"Retry {ctx.attempt} in {delay}s"),
                task_id="task-123"
            )
        """
        context = RetryContext(config=self.config)
        metrics_task_id = task_id or f"anonymous-{id(operation)}"
        retry_started = False  # Track if we've entered retry mode

        # Check circuit breaker before first attempt
        can_execute, circuit_reason = self.circuit_breaker.can_execute()
        if not can_execute:
            logger.warning(f"Circuit breaker preventing execution: {circuit_reason}")
            # Create a synthetic error for the context
            error = RetryError(
                error_type="circuit_breaker_open",
                message=f"Circuit breaker is open: {circuit_reason}",
                category=ErrorCategory.FATAL,
            )
            context.errors.append(error)

            # Record in metrics
            self._record_metrics_end(metrics_task_id, False, 1, 0.0, error.error_type)

            if on_failure:
                callback_result = on_failure(context, error)
                if asyncio.iscoroutine(callback_result):
                    await callback_result
            return False, None, context

        while True:
            try:
                logger.info(f"Executing operation (attempt {context.attempt + 1}/{self.config.max_retries + 1})")
                result = await operation()

                # Success! Record with circuit breaker
                self.circuit_breaker.record_success()

                # Record metrics if we did any retries
                if retry_started:
                    self._record_metrics_end(
                        metrics_task_id,
                        True,
                        context.attempt + 1,
                        context.total_delay_time,
                        None
                    )

                if on_success:
                    callback_result = on_success(context, result)
                    if asyncio.iscoroutine(callback_result):
                        await callback_result

                logger.info(f"Operation succeeded on attempt {context.attempt + 1}")
                return True, result, context

            except Exception as e:
                # Classify the error
                error = self.classify_error(e)
                context.errors.append(error)

                # Record failure with circuit breaker (only for recoverable errors)
                if error.category == ErrorCategory.RECOVERABLE:
                    self.circuit_breaker.record_failure(error)

                logger.warning(
                    f"Operation failed (attempt {context.attempt + 1}): "
                    f"{error.error_type} - {error.message[:100]}..."
                )

                # Check if we should retry
                should_retry, reason = self.should_retry(context, error)

                if not should_retry:
                    logger.error(f"Not retrying: {reason}")

                    # Record metrics
                    if retry_started:
                        self._record_metrics_end(
                            metrics_task_id,
                            False,
                            context.attempt + 1,
                            context.total_delay_time,
                            error.error_type
                        )
                    else:
                        # First attempt failed without retry - still record error
                        self._record_metrics_error(error.error_type)

                    if on_failure:
                        callback_result = on_failure(context, error)
                        if asyncio.iscoroutine(callback_result):
                            await callback_result
                    return False, None, context

                # Start tracking retries on first retry
                if not retry_started:
                    retry_started = True
                    self._record_metrics_start(metrics_task_id, error.error_type)

                # Calculate delay and increment attempt
                context.attempt += 1
                delay = self.calculate_delay(context.attempt - 1)  # 0-indexed for delay calculation

                # Record retry attempt in metrics
                self._record_metrics_attempt(metrics_task_id, error.error_type)

                # Check if delay would exceed total timeout
                remaining_time = self.config.max_total_timeout - context.elapsed_time
                if delay > remaining_time:
                    delay = max(0.1, remaining_time - 1)  # Leave 1s buffer

                # Notify about retry
                if on_retry:
                    callback_result = on_retry(context, error, delay)
                    if asyncio.iscoroutine(callback_result):
                        await callback_result

                logger.info(
                    f"Retrying in {delay:.2f}s (attempt {context.attempt + 1}/{self.config.max_retries + 1}, "
                    f"{context.retries_remaining} retries remaining)"
                )

                # Wait before retry (non-blocking)
                context.last_retry_at = datetime.now()
                await asyncio.sleep(delay)
                context.total_delay_time += delay

    def _record_metrics_start(self, task_id: str, error_type: str | None) -> None:
        """Record the start of a retry operation in metrics."""
        try:
            from backend.services.retry_metrics import record_retry_start
            record_retry_start(task_id, error_type)
        except Exception as e:
            logger.debug(f"Failed to record metrics start: {e}")

    def _record_metrics_attempt(self, task_id: str, error_type: str) -> None:
        """Record a retry attempt in metrics."""
        try:
            from backend.services.retry_metrics import record_retry_attempt
            record_retry_attempt(task_id, error_type)
        except Exception as e:
            logger.debug(f"Failed to record metrics attempt: {e}")

    def _record_metrics_end(
        self,
        task_id: str,
        successful: bool,
        total_attempts: int,
        recovery_time: float,
        final_error_type: str | None
    ) -> None:
        """Record the end of a retry operation in metrics."""
        try:
            from backend.services.retry_metrics import record_retry_end
            record_retry_end(task_id, successful, total_attempts, recovery_time, final_error_type)
        except Exception as e:
            logger.debug(f"Failed to record metrics end: {e}")

    def _record_metrics_error(self, error_type: str) -> None:
        """Record an error in metrics without full retry tracking."""
        try:
            from backend.services.retry_metrics import get_retry_metrics
            get_retry_metrics().record_error(error_type)
        except Exception as e:
            logger.debug(f"Failed to record metrics error: {e}")


def create_retry_manager_from_settings() -> RetryManager:
    """
    Create a RetryManager instance from application settings.

    Returns:
        Configured RetryManager instance
    """
    from backend.config import settings
    config = settings.get_retry_config()
    return RetryManager(config)


def create_circuit_breaker_from_settings() -> CircuitBreaker:
    """
    Create a CircuitBreaker instance from application settings.

    Returns:
        Configured CircuitBreaker instance
    """
    from backend.config import settings
    return CircuitBreaker(
        failure_threshold=settings.circuit_breaker_failure_threshold,
        recovery_timeout=settings.circuit_breaker_recovery_timeout,
        enabled=settings.circuit_breaker_enabled,
    )


def get_global_circuit_breaker() -> CircuitBreaker:
    """
    Get the global circuit breaker instance.

    Returns:
        The shared CircuitBreaker instance used across all RetryManagers
    """
    return RetryManager._get_global_circuit_breaker()


def get_circuit_breaker_status() -> dict:
    """
    Get the current status of the global circuit breaker.

    Returns:
        Dictionary with circuit breaker state information
    """
    breaker = get_global_circuit_breaker()
    state = breaker.get_state()
    return {
        "enabled": breaker.enabled,
        "state": state.state,
        "failure_count": state.failure_count,
        "failure_threshold": breaker.failure_threshold,
        "recovery_timeout": breaker.recovery_timeout,
        "last_failure_time": state.last_failure_time.isoformat() if state.last_failure_time else None,
        "opened_at": state.opened_at.isoformat() if state.opened_at else None,
        "time_until_recovery": breaker.time_until_recovery,
        "half_open_successes": state.half_open_successes,
        "half_open_max_calls": breaker.half_open_max_calls,
    }


def reset_circuit_breaker() -> None:
    """Reset the global circuit breaker to closed state."""
    RetryManager.reset_global_circuit_breaker()
