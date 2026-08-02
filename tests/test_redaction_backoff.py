from __future__ import annotations

from acars_bridge.redaction import mask_logon, redact
from acars_bridge.services.backoff import delay_seconds


def test_redacts_logon():
    secret = "Ab12Cd34Ef56Gh78"
    assert secret not in redact(f"logon={secret} failed", secret)
    assert "[REDACTED_LOGON]" in redact(f"https://x?logon={secret}&from=SWR14", secret)
    assert mask_logon("Ab12Cd34Ef56") == "Ab********56"


def test_backoff_grows():
    assert delay_seconds(0, base=60, jitter=0) == 60
    assert delay_seconds(1, base=60, jitter=0) == 120
    assert delay_seconds(10, base=60, max_seconds=900, jitter=0) == 900
