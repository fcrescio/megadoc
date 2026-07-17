from __future__ import annotations

import hashlib


def retry_delay_seconds(
    retry_number: int,
    *,
    key: str,
    base_seconds: int = 60,
    cap_seconds: int = 15 * 60,
    jitter_ratio: float = 0.20,
) -> int:
    """Return capped exponential backoff with stable per-task jitter."""
    exponential = min(cap_seconds, base_seconds * (2 ** max(0, retry_number)))
    digest = hashlib.sha256(f"{key}:{retry_number}".encode("utf-8")).digest()
    unit = int.from_bytes(digest[:4], "big") / (2**32 - 1)
    factor = 1 - jitter_ratio + (2 * jitter_ratio * unit)
    return max(1, min(cap_seconds, round(exponential * factor)))
