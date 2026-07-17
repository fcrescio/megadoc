from __future__ import annotations

import math
from collections import Counter
from datetime import datetime
from typing import Any


def classify_failure(message: str | None) -> str:
    text = (message or "").lower()
    if any(token in text for token in ("timeout", "timed out", "deadline")):
        return "timeout"
    if any(token in text for token in ("connection", "connect", "503", "unavailable")):
        return "backend_unavailable"
    if any(token in text for token in ("out of memory", "oom", "cuda")):
        return "resource_exhausted"
    if any(token in text for token in ("parse", "schema", "json", "validation")):
        return "invalid_output"
    if any(token in text for token in ("stale", "reconciled")):
        return "stale_recovered"
    return "unknown"


def nearest_rank(values: list[float], quantile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(0, math.ceil(len(ordered) * quantile) - 1)]


def summarize_jobs(jobs: list[Any], *, window_hours: float) -> dict[str, Any]:
    terminal = [job for job in jobs if job.status in {"succeeded", "completed", "failed"}]
    durations = [
        max(0.0, (job.finished_at - job.started_at).total_seconds())
        for job in terminal
        if isinstance(job.started_at, datetime) and isinstance(job.finished_at, datetime)
    ]
    queue_waits = [
        max(0.0, (job.started_at - job.created_at).total_seconds())
        for job in jobs
        if isinstance(job.started_at, datetime) and isinstance(job.created_at, datetime)
    ]
    succeeded = sum(job.status in {"succeeded", "completed"} for job in jobs)
    failed = [job for job in jobs if job.status == "failed"]
    failures = Counter(classify_failure(job.error_message) for job in failed)
    mean_duration = sum(durations) / len(durations) if durations else None
    return {
        "total": len(jobs),
        "succeeded": succeeded,
        "failed": len(failed),
        "active": sum(job.status in {"queued", "pending", "processing", "running"} for job in jobs),
        "throughput_per_hour": round(succeeded / max(window_hours, 1 / 60), 3),
        "mean_duration_seconds": round(mean_duration, 3) if mean_duration is not None else None,
        "duration_p50_seconds": _rounded(nearest_rank(durations, 0.50)),
        "duration_p95_seconds": _rounded(nearest_rank(durations, 0.95)),
        "queue_wait_p50_seconds": _rounded(nearest_rank(queue_waits, 0.50)),
        "queue_wait_p95_seconds": _rounded(nearest_rank(queue_waits, 0.95)),
        "failure_classes": dict(sorted(failures.items())),
    }


def _rounded(value: float | None) -> float | None:
    return round(value, 3) if value is not None else None
