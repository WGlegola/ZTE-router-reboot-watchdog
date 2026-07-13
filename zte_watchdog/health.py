"""Optional read-only HTTP health endpoint for external liveness/state probes.

Serves the monitor's health_snapshot() as JSON on any GET. Returns 200 while the
loop's last check is recent, and 503 once it goes stale (the loop is wedged) so
an uptime check catches a hung watchdog, not just a dead process. The payload
contains no secrets.
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


def start_health_server(monitor, host: str, port: int, stale_after: float):
    """Start a daemon-thread HTTP server exposing monitor.health_snapshot().
    Returns the server object (call .shutdown() to stop it)."""

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            snap = monitor.health_snapshot()
            secs = snap.get("seconds_since_check")
            ok = secs is not None and secs <= stale_after
            body = json.dumps({**snap, "ok": ok}, default=str).encode()
            self.send_response(200 if ok else 503)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):   # don't echo every request to stderr
            pass

    server = ThreadingHTTPServer((host, port), Handler)
    threading.Thread(target=server.serve_forever, daemon=True,
                     name="zte-health").start()
    return server
