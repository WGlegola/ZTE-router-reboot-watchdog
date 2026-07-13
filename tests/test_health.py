import errno
import json
import urllib.error
import urllib.request

import pytest

from zte_watchdog.health import is_fresh, start_health_server


class FakeMonitor:
    def __init__(self, snap):
        self._snap = snap
    def health_snapshot(self):
        return self._snap


def test_is_fresh_boundary():
    assert is_fresh({"seconds_since_check": 5.0}, 60) is True
    assert is_fresh({"seconds_since_check": 60}, 60) is True       # inclusive
    assert is_fresh({"seconds_since_check": 60.1}, 60) is False
    assert is_fresh({"seconds_since_check": None}, 60) is False    # no check yet
    assert is_fresh({}, 60) is False


def _server(snap):
    # Binding a loopback listen socket is denied in some sandboxes; skip ONLY on a
    # permission denial — any other bind failure is a real error and must surface.
    try:
        return start_health_server(FakeMonitor(snap), "127.0.0.1", 0, stale_after=60)
    except OSError as e:
        if e.errno in (errno.EACCES, errno.EPERM):
            pytest.skip(f"socket bind not permitted here: {e}")
        raise


def _get(port):
    return urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=3)


def test_health_server_returns_200_and_snapshot_when_fresh():
    server = _server({"status": "healthy", "seconds_since_check": 2.0, "consecutive_fails": 0})
    try:
        with _get(server.server_address[1]) as r:
            assert r.status == 200
            data = json.loads(r.read())
        assert data["status"] == "healthy"
        assert data["ok"] is True
        assert data["consecutive_fails"] == 0
    finally:
        server.shutdown()


def test_health_server_returns_503_when_stale():
    server = _server({"status": "degraded", "seconds_since_check": 999.0})
    try:
        try:
            _get(server.server_address[1])
            raise AssertionError("expected HTTP 503")
        except urllib.error.HTTPError as e:
            assert e.code == 503
            assert json.loads(e.read())["ok"] is False
    finally:
        server.shutdown()


def test_health_server_503_before_first_check():
    server = _server({"status": "starting", "seconds_since_check": None})
    try:
        try:
            _get(server.server_address[1])
            raise AssertionError("expected HTTP 503")
        except urllib.error.HTTPError as e:
            assert e.code == 503
    finally:
        server.shutdown()
