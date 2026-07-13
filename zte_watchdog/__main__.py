"""CLI: default runs the autonomous auto-reboot daemon; --heartbeat runs a
supervised monitor that prints a live readout and asks before rebooting."""

from __future__ import annotations

import argparse
import logging
import sys
import time

from . import notify as sd
from .config import load_config
from .gateway import Gateway
from .metrics import Signal, quality
from .watchdog import Monitor


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="zte-watchdog",
                                description="ZTE MC801A hung-session watchdog.")
    p.add_argument("--config", help="path to config.toml")
    p.add_argument("--ip", help="gateway IP (default 192.168.7.1)")
    p.add_argument("--heartbeat", action="store_true",
                   help="supervised mode: continuously print a live readout and "
                        "prompt before rebooting, only when a drop is detected")
    p.add_argument("--log-signal", dest="log_signal", action="store_true", default=None,
                   help="daemon: also log signal metrics each cycle (opt-in)")
    p.add_argument("--once", action="store_true",
                   help="run a single monitor evaluation and exit")
    p.add_argument("--interval", type=int, help="seconds between checks while healthy")
    p.add_argument("--fail-interval", dest="fail_interval", type=int,
                   help="seconds between checks once a failure is detected (faster escalation)")
    p.add_argument("--fails", type=int, help="consecutive fails before reboot")
    p.add_argument("--cooldown", type=int, help="seconds to wait after a reboot")
    p.add_argument("--max-reboots-per-hour", dest="max_reboots_per_hour", type=int)
    p.add_argument("--health-port", dest="health_port", type=int,
                   help="serve a read-only JSON /health endpoint on this port (0=off)")
    p.add_argument("--health-host", dest="health_host",
                   help="bind address for --health-port (default 127.0.0.1; "
                        "use 0.0.0.0 to allow probes from other machines)")
    return p


def _cli_overrides(args) -> dict:
    keys = ("ip", "interval", "fail_interval", "fails", "cooldown",
            "max_reboots_per_hour", "log_signal", "health_host", "health_port")
    return {k: getattr(args, k) for k in keys}


def _confirm_reboot(prompt=input):
    """Return an approve(obs) callback that asks the user before a reboot."""
    def approve(obs) -> bool:
        ans = prompt("\n>>> Connection drop detected — reboot gateway now? [y/N] ")
        return str(ans).strip().lower().startswith("y")
    return approve


def _num(value) -> str:
    return "n/a" if value is None else f"{value:.1f}"


def _qual(value, kind) -> str:
    return f"({quality(value, kind)})"


def _heartbeat_report(cfg, gateway, out=print):
    """Return a report(obs, now) callback that prints one fixed-width, column-
    aligned heartbeat line per cycle, so successive lines line up for quick
    comparison. Reads (authenticated) signal metrics when a password is set."""
    def report(obs, now) -> None:
        cols = [
            time.strftime("%H:%M:%S", time.localtime(now)),
            f"internet={'up' if obs.internet_up else 'DOWN':<4}",
            f"gw={'reachable' if obs.gateway_reachable else 'unreachable':<11}",
            f"ppp={'connected' if obs.ppp_connected else 'no':<9}",
        ]
        if cfg.password and obs.gateway_reachable:
            try:
                s = Signal.from_raw(gateway.read_metrics())
                rat, rsrp, rsrq, sinr, band = s.active()
                cols += [
                    f"net={rat:<4}",
                    f"RSRP {_num(rsrp):>6} {_qual(rsrp, 'rsrp'):<11}",
                    f"RSRQ {_num(rsrq):>6} {_qual(rsrq, 'rsrq'):<11}",
                    f"SINR {_num(sinr):>6} {_qual(sinr, 'sinr'):<11}",
                    f"band={(band or '?'):<11}",
                    f"cell={s.cell_id or '?'}",
                ]
            except Exception as e:            # noqa: BLE001
                cols.append(f"signal read failed: {e}")
        out("  ".join(cols))
    return report


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    cfg = load_config(path=args.config, cli=_cli_overrides(args))
    logging.basicConfig(
        level=getattr(logging, cfg.log_level, logging.INFO),
        format="%(asctime)s %(levelname)s %(message)s",
    )
    gateway = Gateway(cfg.base_url, password=cfg.password)

    if args.heartbeat:
        print("Supervised heartbeat monitor — prints status each cycle, prompts "
              "only when a drop is detected. Ctrl-C to stop.", flush=True)
        monitor = Monitor(cfg, gateway,
                          approve=_confirm_reboot(),
                          report=_heartbeat_report(cfg, gateway),
                          notify=sd.watchdog)
    else:
        monitor = Monitor(cfg, gateway, notify=sd.watchdog)

    server = None
    if cfg.health_port:
        from .health import start_health_server
        # Consider the loop wedged after ~3 intervals without a check (min 60s):
        # generous enough to tolerate slow cycles (login timeouts) without a
        # false 503, tight enough to catch a genuinely hung loop.
        stale_after = max(cfg.interval * 3, 60)
        server = start_health_server(monitor, cfg.health_host, cfg.health_port, stale_after)
        logging.getLogger("zte_watchdog").info(
            "health endpoint: http://%s:%s/health", cfg.health_host, cfg.health_port)

    sd.ready("watchdog started")   # systemd Type=notify: mark started (no-op otherwise)
    try:
        monitor.run(max_cycles=1 if args.once else None)
    finally:
        if server is not None:
            server.shutdown()
    return 0


def _raise_keyboard_interrupt(*_args):
    """SIGTERM handler: turn systemd's stop signal into a clean shutdown, handled
    by the KeyboardInterrupt path below exactly like Ctrl-C."""
    raise KeyboardInterrupt


if __name__ == "__main__":
    import signal

    signal.signal(signal.SIGTERM, _raise_keyboard_interrupt)
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        logging.getLogger("zte_watchdog").info("stopped")
