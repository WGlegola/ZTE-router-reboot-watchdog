"""Reboot decision logic (pure) and the monitor loop (thin I/O)."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from enum import Enum

from .connectivity import internet_up, tcp_reachable
from .metrics import Signal

log = logging.getLogger("zte_watchdog")

_HOUR = 3600


class Action(Enum):
    HEALTHY = "healthy"
    WAIT = "wait"
    REBOOT = "reboot"
    BACKOFF = "backoff"


@dataclass
class Observation:
    internet_up: bool
    gateway_reachable: bool
    ppp_connected: bool


@dataclass
class WatchdogState:
    consecutive_fails: int = 0
    reboot_times: list = field(default_factory=list)
    cooldown_until: float = 0.0


def decide(state: WatchdogState, obs: Observation, cfg, now: float) -> Action:
    """Pure decision (mutates `state` deterministically; no I/O)."""
    if now < state.cooldown_until:
        return Action.WAIT
    if not obs.gateway_reachable:          # likely mid-reboot / off
        state.consecutive_fails = 0
        return Action.WAIT
    if obs.internet_up:
        state.consecutive_fails = 0
        return Action.HEALTHY
    if not obs.ppp_connected:              # modem knows it's down; re-attaching
        state.consecutive_fails = 0
        return Action.WAIT

    # Internet dead + gateway reachable + ppp_connected == hung session.
    state.consecutive_fails += 1
    if state.consecutive_fails < cfg.fails:
        return Action.WAIT

    state.reboot_times[:] = [t for t in state.reboot_times if now - t <= _HOUR]
    if len(state.reboot_times) >= cfg.max_reboots_per_hour:
        state.consecutive_fails = 0
        state.cooldown_until = now + cfg.cooldown
        return Action.BACKOFF

    state.reboot_times.append(now)
    state.consecutive_fails = 0
    state.cooldown_until = now + cfg.cooldown
    return Action.REBOOT


class Monitor:
    def __init__(self, cfg, gateway, clock=time.time, sleep=time.sleep):
        self.cfg = cfg
        self.gateway = gateway
        self.clock = clock
        self.sleep = sleep
        self.state = WatchdogState()
        self._next_metrics = 0.0

    def observe(self) -> Observation:
        reachable = tcp_reachable(self.cfg.ip, 80)
        up = internet_up(self.cfg.parsed_targets)
        ppp = False
        if reachable:
            try:
                ppp = self.gateway.read_health().get("ppp_status") == "ppp_connected"
            except Exception as e:            # noqa: BLE001
                log.warning("health read failed: %s", e)
        return Observation(up, reachable, ppp)

    def _maybe_log_signal(self, now: float) -> None:
        if not self.cfg.log_signal or now < self._next_metrics:
            return
        self._next_metrics = now + self.cfg.metrics_interval
        try:
            log.info("signal: %s", Signal.from_raw(self.gateway.read_metrics()).summary())
        except Exception as e:                # noqa: BLE001
            log.warning("metrics read failed: %s", e)

    def run(self, max_cycles: int | None = None) -> None:
        log.info("watchdog started (ip=%s interval=%ss fails=%s)",
                 self.cfg.ip, self.cfg.interval, self.cfg.fails)
        cycles = 0
        while max_cycles is None or cycles < max_cycles:
            now = self.clock()
            obs = self.observe()
            action = decide(self.state, obs, self.cfg, now)
            if action == Action.REBOOT:
                log.warning("sustained hung session — rebooting gateway")
                try:
                    self.gateway.reboot()
                    log.warning("reboot sent; cooling down %ss", self.cfg.cooldown)
                except Exception as e:        # noqa: BLE001
                    log.error("reboot failed: %s", e)
            elif action == Action.BACKOFF:
                log.error("reboot cap reached (%s/hr) — assuming real outage, backing off",
                          self.cfg.max_reboots_per_hour)
            elif action == Action.WAIT and not obs.internet_up:
                log.info("no internet (fails=%s/%s, ppp=%s)",
                         self.state.consecutive_fails, self.cfg.fails, obs.ppp_connected)
            self._maybe_log_signal(now)
            cycles += 1
            if max_cycles is None or cycles < max_cycles:
                self.sleep(self.cfg.interval)
