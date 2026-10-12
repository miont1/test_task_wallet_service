import time
from collections import defaultdict, deque


class InMemoryRateLimiter:
    """Sliding-window rate limiter per API key.

    Tracks request timestamps within a sliding window.
    Thread-safe within asyncio event loop.
    """

    def __init__(self, max_requests: int = 30, window_seconds: float = 60.0) -> None:
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._history: dict[str, deque[float]] = defaultdict(deque)

    def is_rate_limited(
        self, key: str, current_time: float | None = None
    ) -> tuple[bool, int]:
        """Checks if a request under `key` exceeds the allowed rate.

        Returns (is_limited, retry_after_seconds).
        If not limited, records the request timestamp and returns (False, 0).
        """
        now = current_time if current_time is not None else time.time()
        window_start = now - self.window_seconds
        records = self._history[key]

        # Evict timestamps older than sliding window
        while records and records[0] <= window_start:
            records.popleft()

        if len(records) >= self.max_requests:
            oldest = records[0]
            retry_after = max(1, int(self.window_seconds - (now - oldest)) + 1)
            return True, retry_after

        # Record this request
        records.append(now)
        return False, 0

    def reset(self) -> None:
        """Clears all rate limit state (useful between tests)."""
        self._history.clear()


# Global singleton instance
rate_limiter = InMemoryRateLimiter(max_requests=30, window_seconds=60.0)
