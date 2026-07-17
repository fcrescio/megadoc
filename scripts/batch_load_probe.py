#!/usr/bin/env python3
from __future__ import annotations

import argparse
import concurrent.futures
import json
import statistics
import subprocess
import time
import uuid
from pathlib import Path
from typing import Any

import httpx


def stratified_sample(root: Path, limit: int) -> list[Path]:
    files = sorted(
        (path for path in root.rglob("*.pdf") if path.is_file()),
        key=lambda path: path.stat().st_size,
    )
    if len(files) <= limit:
        return files
    return [files[round(index * (len(files) - 1) / (limit - 1))] for index in range(limit)]


def upload(api_url: str, path: Path, external_id: str) -> dict[str, Any]:
    started = time.monotonic()
    with path.open("rb") as handle, httpx.Client(timeout=180) as client:
        response = client.post(
            f"{api_url}/documents/upload",
            params={"auto_submit": "true", "external_id": external_id},
            files={"file": (path.name, handle, "application/pdf")},
        )
        response.raise_for_status()
        payload = response.json()
    return {
        "path": str(path),
        "document_id": payload.get("document_id"),
        "job_id": payload.get("job_id"),
        "deduplicated": payload.get("deduplicated"),
        "latency_seconds": round(time.monotonic() - started, 3),
    }


def wait_for_drain(api_url: str, timeout_seconds: int, poll_seconds: int = 10) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_seconds
    last = {}
    with httpx.Client(timeout=30) as client:
        while time.monotonic() < deadline:
            last = client.get(f"{api_url}/jobs/background-activity").json()
            if last.get("active_count") == 0 and last.get("possibly_stale_count") == 0:
                return last
            time.sleep(poll_seconds)
    raise TimeoutError(f"queues did not drain within {timeout_seconds}s; last state={last}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Stratified PDF upload and recovery probe.")
    parser.add_argument("directory", type=Path)
    parser.add_argument("--api-url", default="http://127.0.0.1:8080")
    parser.add_argument("--limit", type=int, default=500)
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument("--drain-timeout", type=int, default=24 * 60 * 60)
    parser.add_argument("--execute", action="store_true", help="Actually upload documents; omitted means plan only.")
    args = parser.parse_args()

    sample = stratified_sample(args.directory, args.limit)
    sizes = [path.stat().st_size for path in sample]
    plan = {
        "directory": str(args.directory),
        "selected": len(sample),
        "size_min": min(sizes) if sizes else None,
        "size_median": statistics.median(sizes) if sizes else None,
        "size_max": max(sizes) if sizes else None,
        "execute": args.execute,
    }
    if not args.execute:
        print(json.dumps({"status": "plan_only", **plan}, indent=2))
        return 0

    run_id = uuid.uuid4().hex[:10]
    started = time.monotonic()
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.concurrency) as executor:
        futures = [
            executor.submit(upload, args.api_url.rstrip("/"), path, f"load-{run_id}-{index:04d}")
            for index, path in enumerate(sample, start=1)
        ]
        uploads = [future.result() for future in concurrent.futures.as_completed(futures)]
    activity = wait_for_drain(args.api_url.rstrip("/"), args.drain_timeout)
    with httpx.Client(timeout=30) as client:
        metrics = client.get(f"{args.api_url.rstrip('/')}/jobs/metrics", params={"hours": 24 * 30}).json()
    consistency = subprocess.run(
        ["python", "scripts/pipeline_consistency_probe.py"],
        check=False,
        capture_output=True,
        text=True,
    )
    report = {
        "status": "completed" if consistency.returncode == 0 else "inconsistent",
        **plan,
        "run_id": run_id,
        "elapsed_seconds": round(time.monotonic() - started, 3),
        "upload_latency_p50": statistics.median(row["latency_seconds"] for row in uploads) if uploads else None,
        "uploads": uploads,
        "final_activity": activity,
        "metrics": metrics,
        "consistency": json.loads(consistency.stdout) if consistency.stdout.strip() else {"stderr": consistency.stderr},
    }
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0 if report["status"] == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
