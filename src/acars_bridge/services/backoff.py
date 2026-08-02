from __future__ import annotations

import random

from acars_bridge.config import DEFAULT_POLL_INTERVAL_SECONDS, JITTER_SECONDS, MAX_BACKOFF_SECONDS


def delay_seconds(
    failure_count: int,
    *,
    base: int = DEFAULT_POLL_INTERVAL_SECONDS,
    max_seconds: int = MAX_BACKOFF_SECONDS,
    jitter: int = JITTER_SECONDS,
) -> int:
    failures = max(0, failure_count)
    exp = min(max_seconds, base * (2 ** min(failures, 4)))
    return exp + (random.randint(0, jitter) if jitter > 0 else 0)
