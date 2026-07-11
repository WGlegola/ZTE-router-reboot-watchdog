"""External reachability checks. Raw-IP TCP so it's independent of DNS."""

from __future__ import annotations

import socket


def tcp_reachable(host: str, port: int, timeout: float = 4.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def parse_target(item: str) -> tuple[str, int]:
    host, _, port = item.partition(":")
    return host, int(port) if port else 443


def internet_up(targets: list[tuple[str, int]], timeout: float = 4.0) -> bool:
    return any(tcp_reachable(h, p, timeout) for h, p in targets)
