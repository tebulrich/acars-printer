from __future__ import annotations

from acars_bridge.services.debug_log import DebugLog


def test_debug_log_writes_ring_and_file(tmp_path):
    path = tmp_path / "debug.log"
    log = DebugLog(path, max_lines=5)
    log.action("start", mode="observer", callsign="SWR14")
    log.toast("Check ok", error=False)
    log.error("poller", message="boom", last_hoppie_type="peek")

    text = log.text()
    assert "[ACTION] start" in text
    assert "mode=observer" in text
    assert "[TOAST] ok" in text
    assert "[ERROR] poller" in text
    assert path.exists()
    assert "boom" in path.read_text(encoding="utf-8")

    paste = log.paste_block(header={"version": "0.1.0", "mode": "observer"})
    assert paste.startswith("=== ACARS Print Bridge debug log ===")
    assert "version: 0.1.0" in paste
    assert "=== end ===" in paste


def test_debug_log_clear(tmp_path):
    path = tmp_path / "debug.log"
    log = DebugLog(path)
    log.info("keep_me")
    log.clear()
    assert "keep_me" not in log.text()
    assert "log_cleared" in log.text()


def test_debug_log_redacts_logon(tmp_path):
    path = tmp_path / "debug.log"
    secret = "MySecretLogon99"
    log = DebugLog(path, get_logon=lambda: secret)
    log.info("tap_dbg", message=f"path='/acars/system/connect.html?logon={secret}&from=X'")
    text = log.text()
    assert secret not in text
    assert "REDACTED_LOGON" in text
    paste = log.paste_block()
    assert secret not in paste
