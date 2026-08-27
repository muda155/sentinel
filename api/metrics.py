"""Minimal in-process counters rendered in Prometheus text format (NFR-6).
Tracked: cluster/hotspot count, alert count, LLM latency, fallback rate, and
translation requests, cache hits, errors and latency (FR-30)."""
from __future__ import annotations

import threading


class _Metrics:
    def __init__(self) -> None:
        self._c: dict[str, float] = {}
        self._lock = threading.Lock()

    def inc(self, name: str, amount: float = 1) -> None:
        with self._lock:
            self._c[name] = self._c.get(name, 0) + amount

    def observe(self, name: str, value: float) -> None:
        with self._lock:
            self._c[f"{name}_sum"] = self._c.get(f"{name}_sum", 0) + value
            self._c[f"{name}_count"] = self._c.get(f"{name}_count", 0) + 1

    def snapshot(self) -> dict[str, float]:
        with self._lock:
            return dict(self._c)

    def reset(self) -> None:
        with self._lock:
            self._c.clear()


METRICS = _Metrics()


def render_prometheus() -> str:
    return "\n".join(f"{k} {v:g}" for k, v in sorted(METRICS.snapshot().items())) + "\n"
