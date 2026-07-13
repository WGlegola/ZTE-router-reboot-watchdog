"""Minimal sd_notify: talk to systemd's $NOTIFY_SOCKET with no dependency.

Every call is a graceful no-op when not run under systemd (Type=notify), so the
daemon behaves identically when launched by hand. Used to send READY=1 at
startup and a WATCHDOG=1 keep-alive each loop cycle; with WatchdogSec set in the
unit, systemd restarts the service if the loop stops pinging (self-healing). The
optional STATUS text shows up in `systemctl status`.
"""

from __future__ import annotations

import os
import socket


def _send(msg: bytes) -> None:
    addr = os.environ.get("NOTIFY_SOCKET")
    if not addr:
        return
    raw = ("\0" + addr[1:]) if addr.startswith("@") else addr   # abstract namespace
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as s:
            s.sendto(msg, raw.encode())
    except OSError:
        pass


def _msg(base: str, status: str | None) -> bytes:
    return (f"{base}\nSTATUS={status}" if status else base).encode()


def ready(status: str | None = None) -> None:
    _send(_msg("READY=1", status))


def watchdog(status: str | None = None) -> None:
    _send(_msg("WATCHDOG=1", status))
