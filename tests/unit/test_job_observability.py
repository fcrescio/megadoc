from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from api.services.job_observability import classify_failure, summarize_jobs


def _job(status, *, start=10, duration=20, error=None):
    created = datetime(2026, 1, 1, tzinfo=timezone.utc)
    started = created + timedelta(seconds=start) if start is not None else None
    finished = started + timedelta(seconds=duration) if started and duration is not None else None
    return SimpleNamespace(
        status=status, created_at=created, started_at=started,
        finished_at=finished, error_message=error,
    )


def test_failure_classification_is_stable():
    assert classify_failure("backend connection timed out") == "timeout"
    assert classify_failure("CUDA out of memory") == "resource_exhausted"
    assert classify_failure("invalid JSON schema") == "invalid_output"


def test_job_summary_reports_latency_throughput_and_failures():
    summary = summarize_jobs([
        _job("succeeded", start=5, duration=10),
        _job("completed", start=15, duration=30),
        _job("failed", start=20, duration=50, error="backend unavailable 503"),
        _job("queued", start=None, duration=None),
    ], window_hours=2)

    assert summary["throughput_per_hour"] == 1.0
    assert summary["duration_p50_seconds"] == 30
    assert summary["duration_p95_seconds"] == 50
    assert summary["queue_wait_p95_seconds"] == 20
    assert summary["failure_classes"] == {"backend_unavailable": 1}
