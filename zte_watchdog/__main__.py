"""CLI: default runs the autonomous auto-reboot daemon; --heartbeat runs a
supervised monitor that prints a live readout and asks before rebooting."""

from __future__ import annotations

import argparse
import logging
import sys

from .config import load_config
from .gateway import Gateway
from .metrics import Signal
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
    p.add_argument("--interval", type=int, help="seconds between checks")
    p.add_argument("--fails", type=int, help="consecutive fails before reboot")
    p.add_argument("--cooldown", type=int, help="seconds to wait after a reboot")
    p.add_argument("--max-reboots-per-hour", dest="max_reboots_per_hour", type=int)
    return p


def _cli_overrides(args) -> dict:
    keys = ("ip", "interval", "fails", "cooldown", "max_reboots_per_hour", "log_signal")
    return {k: getattr(args, k) for k in keys}


def _confirm_reboot(prompt=input):
    """Return an approve(obs) callback that asks the user before a reboot."""
    def approve(obs) -> bool:
        ans = prompt("\n>>> Connection drop detected — reboot gateway now? [y/N] ")
        return str(ans).strip().lower().startswith("y")
    return approve


def _heartbeat_report(cfg, gateway, out=print):
    """Return a report(obs, now) callback that prints a live heartbeat line each
    cycle. Reads (authenticated) signal metrics when a password is configured."""
    def report(obs, now) -> None:
        line = "heartbeat: " + "  ".join((
            "internet=" + ("up" if obs.internet_up else "DOWN"),
            "gateway=" + ("reachable" if obs.gateway_reachable else "unreachable"),
            "ppp=" + ("connected" if obs.ppp_connected else "no"),
        ))
        if cfg.password and obs.gateway_reachable:
            try:
                line += "  |  " + Signal.from_raw(gateway.read_metrics()).summary()
            except Exception as e:            # noqa: BLE001
                line += f"  |  signal read failed: {e}"
        out(line)
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
                          report=_heartbeat_report(cfg, gateway))
        monitor.run(max_cycles=1 if args.once else None)
        return 0

    monitor = Monitor(cfg, gateway)
    monitor.run(max_cycles=1 if args.once else None)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        logging.getLogger("zte_watchdog").info("stopped")
