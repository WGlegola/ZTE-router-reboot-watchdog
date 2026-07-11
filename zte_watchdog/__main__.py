"""CLI: default runs the autonomous daemon; --heartbeat is the interactive tool."""

from __future__ import annotations

import argparse
import logging
import sys

from .config import load_config
from .connectivity import internet_up, tcp_reachable
from .gateway import Gateway
from .metrics import Signal
from .watchdog import Monitor


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="zte-watchdog",
                                description="ZTE MC801A hung-session watchdog.")
    p.add_argument("--config", help="path to config.toml")
    p.add_argument("--ip", help="gateway IP (default 192.168.7.1)")
    p.add_argument("--heartbeat", action="store_true",
                   help="print a live readout and prompt to reboot, then exit")
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


def heartbeat(cfg, gateway, prompt=input, out=print) -> None:
    reachable = tcp_reachable(cfg.ip, 80)
    out(f"gateway {cfg.ip} web UI reachable: {reachable}")
    for host, port in cfg.parsed_targets:
        out(f"  reach {host}:{port} -> {tcp_reachable(host, port)}")
    out(f"internet_up (any target): {internet_up(cfg.parsed_targets)}")
    if reachable:
        try:
            h = gateway.read_health()
            out(f"gateway health: ppp={h.get('ppp_status')} modem={h.get('modem_main_state')}")
        except Exception as e:                # noqa: BLE001
            out(f"health read failed: {e}")
    if cfg.password:
        try:
            out("signal: " + Signal.from_raw(gateway.read_metrics()).summary())
        except Exception as e:                # noqa: BLE001
            out(f"metrics read failed (auth?): {e}")
    else:
        out("signal: skipped (no ZTE_PASSWORD set)")
    if str(prompt("Reboot gateway now? [y/N] ")).strip().lower().startswith("y"):
        try:
            out(f"reboot result: {gateway.reboot()}")
        except Exception as e:                # noqa: BLE001
            out(f"reboot failed: {e}")
    else:
        out("no reboot.")


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    cfg = load_config(path=args.config, cli=_cli_overrides(args))
    logging.basicConfig(
        level=getattr(logging, cfg.log_level, logging.INFO),
        format="%(asctime)s %(levelname)s %(message)s",
    )
    gateway = Gateway(cfg.base_url, password=cfg.password)

    if args.heartbeat:
        heartbeat(cfg, gateway)
        return 0

    monitor = Monitor(cfg, gateway)
    monitor.run(max_cycles=1 if args.once else None)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        logging.getLogger("zte_watchdog").info("stopped")
