from __future__ import annotations

from acars_bridge.hoppie.types import HoppieMessage, MessageType
from acars_bridge.services.fingerprint import fingerprint_for


def test_stable_for_identical_content():
    a = HoppieMessage("SWR14", "LSAS_CTR", "SWR14", MessageType.TELEX, "raw", "HELLO")
    b = HoppieMessage("SWR14", "LSAS_CTR", "SWR14", MessageType.TELEX, "other", "HELLO")
    assert fingerprint_for(a) == fingerprint_for(b)


def test_differs_for_distinct_bodies():
    a = HoppieMessage("SWR14", "A", "SWR14", MessageType.TELEX, "raw", "ONE")
    b = HoppieMessage("SWR14", "A", "SWR14", MessageType.TELEX, "raw", "TWO")
    assert fingerprint_for(a) != fingerprint_for(b)
