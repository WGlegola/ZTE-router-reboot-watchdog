import socket

import pytest

from zte_watchdog import notify


def test_message_format(monkeypatch):
    sent = []
    monkeypatch.setattr(notify, "_send", lambda m: sent.append(m))
    notify.ready()
    notify.ready("up")
    notify.watchdog("degraded")
    assert sent == [b"READY=1", b"READY=1\nSTATUS=up", b"WATCHDOG=1\nSTATUS=degraded"]


def test_send_is_noop_without_socket(monkeypatch):
    monkeypatch.delenv("NOTIFY_SOCKET", raising=False)
    notify.ready("x")        # must not raise
    notify.watchdog("y")


def test_send_delivers_to_notify_socket(tmp_path, monkeypatch):
    # Use a relative name so the AF_UNIX sun_path stays short (macOS limit ~104).
    monkeypatch.chdir(tmp_path)
    rx = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
    try:
        rx.bind("n.sock")
    except OSError as e:
        pytest.skip(f"AF_UNIX bind not permitted here: {e}")
    try:
        rx.settimeout(2)
        monkeypatch.setenv("NOTIFY_SOCKET", "n.sock")
        notify.watchdog("healthy")
        assert rx.recv(256) == b"WATCHDOG=1\nSTATUS=healthy"
    finally:
        rx.close()
