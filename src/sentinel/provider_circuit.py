"""Process-local booking outage guard; probes never perform a business write."""
import math
from threading import Lock
from time import monotonic


class CircuitOpen(Exception):
    pass


class ProviderCircuit:
    def __init__(self, *, failure_threshold=5, cooldown_seconds=30, clock=monotonic):
        if type(failure_threshold) is not int or not 1 <= failure_threshold <= 100:
            raise ValueError("Circuit failure threshold must be between 1 and 100.")
        if (type(cooldown_seconds) not in (int, float)
                or not math.isfinite(cooldown_seconds) or not 1 <= cooldown_seconds <= 3600):
            raise ValueError("Circuit cooldown must be between 1 and 3600 seconds.")
        self.threshold = failure_threshold
        self.cooldown = cooldown_seconds
        self.clock = clock
        self._lock = Lock()
        self._failures = 0
        self._retry_at = 0
        self._probing = False

    def record_failure(self):
        with self._lock:
            self._failures += 1
            if self._failures >= self.threshold:
                self._retry_at = self.clock() + self.cooldown

    def record_success(self):
        with self._lock:
            self._failures = 0
            self._retry_at = 0

    def snapshot(self):
        # Coarse shared-provider availability only: no cross-tenant failure counts.
        with self._lock:
            state = "probing" if self._probing else "open" if self._failures >= self.threshold else "closed"
            wait = max(0, math.ceil(self._retry_at - self.clock())) if state == "open" else 0
            return {"state": state, "retry_after_seconds": wait, "scope": "api_process"}

    def before_write(self, read_only_probe):
        with self._lock:
            if self._probing:
                raise CircuitOpen("Booking provider recovery probe is in progress.")
            if self._failures < self.threshold:
                return
            if self.clock() < self._retry_at:
                raise CircuitOpen("Booking provider is temporarily unavailable.")
            self._probing = True
        try:
            read_only_probe()
        except Exception:
            with self._lock:
                self._failures = max(self.threshold, self._failures)
                self._retry_at = self.clock() + self.cooldown
            raise CircuitOpen("Booking provider recovery probe failed.") from None
        else:
            self.record_success()
        finally:
            with self._lock:
                self._probing = False
