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
    def __init__(self, cfg, gateway, clock=time.time, sleep=time.sleep,
                 approve=None, report=None):
        self.cfg = cfg
        self.gateway = gateway
        self.clock = clock
        self.sleep = sleep
        # approve(obs) -> bool gates each reboot; the default auto-approves (the
        # autonomous daemon). Supervised --heartbeat injects a y/N prompt here.
        # report(obs, now) is an optional per-cycle live display (--heartbeat).
        self._approve = approve if approve is not None else (lambda obs: True)
        self._report = report
        self.state = WatchdogState()
        self._next_metrics = 0.0
        self._last_fails_logged = 0
        # Post-reboot recovery verification. The REBOOT_DEVICE AD token is
        # inferred, not confirmed on this firmware, so a reboot that "succeeds"
        # (HTTP 200) may actually do nothing — detect that and warn loudly.
        self._reboot_pending = False
        self._reboot_check_at = 0.0
        self._saw_unreachable = False

    def observe(self) -> Observation:
        reachable = tcp_reachable(self.cfg.ip, 80)
        up = internet_up(self.cfg.parsed_targets)
        ppp = False
        if reachable:
            try:
                ppp = self.gateway.read_health().get("ppp_status") == "ppp_connected"
            except Exception as e:  # noqa: BLE001
                log.warning("health read failed: %s", e)
        return Observation(up, reachable, ppp)

    def _maybe_log_signal(self, now: float) -> None:
        if not self.cfg.log_signal or now < self._next_metrics:
            return
        self._next_metrics = now + self.cfg.metrics_interval
        try:
            log.info("signal: %s", Signal.from_raw(self.gateway.read_metrics()).summary())
        except Exception as e:  # noqa: BLE001
            log.warning("metrics read failed: %s", e)

    def _verify_recovery(self, obs: Observation, now: float) -> None:
        """After a reboot + cooldown, confirm the gateway actually rebooted or the
        internet recovered; warn if a reboot was sent but nothing changed (a likely
        sign the REBOOT_DEVICE AD token is wrong for this firmware)."""
        if not self._reboot_pending:
            return
        if not obs.gateway_reachable:
            self._saw_unreachable = True  # the reboot is taking effect
        if now >= self._reboot_check_at:
            if self._saw_unreachable or obs.internet_up:
                log.info("reboot confirmed: gateway recovered")
            else:
                log.warning(
                    "reboot was sent but the gateway never went unreachable and "
                    "internet is still down — the REBOOT_DEVICE AD token may be wrong "
                    "for this firmware; check the reboot() response and web-UI JS")
            self._reboot_pending = False

    def run(self, max_cycles: int | None = None) -> None:
        log.info("watchdog started (ip=%s interval=%ss fails=%s)",
                 self.cfg.ip, self.cfg.interval, self.cfg.fails)
        cycles = 0
        while max_cycles is None or cycles < max_cycles:
            now = self.clock()
            obs = self.observe()
            self._verify_recovery(obs, now)
            if self._report is not None:
                self._report(obs, now)
            action = decide(self.state, obs, self.cfg, now)
            if action == Action.REBOOT:
                if self._approve(obs):
                    log.warning("sustained hung session — rebooting gateway")
                    try:
                        resp = self.gateway.reboot()
                        log.warning("reboot sent (response=%s); cooling down %ss while it re-attaches",
                                    resp, self.cfg.cooldown)
                        self._reboot_pending = True
                        self._reboot_check_at = now + self.cfg.cooldown
                        self._saw_unreachable = False
                    except Exception as e:  # noqa: BLE001
                        log.error("reboot failed: %s", e)
                else:
                    # Declined (supervised mode): undo the cap bookkeeping decide()
                    # recorded, but keep its cooldown so we re-ask after the cooldown
                    # rather than nagging every cycle.
                    if self.state.reboot_times:
                        self.state.reboot_times.pop()
                    log.info("reboot declined — monitoring continues "
                             "(will re-check after %ss cooldown)", self.cfg.cooldown)
            elif action == Action.BACKOFF:
                log.error("reboot cap reached (%s/hr) — assuming real outage, backing off",
                          self.cfg.max_reboots_per_hour)
            elif action == Action.HEALTHY:
                if self._last_fails_logged > 0:
                    log.info("internet recovered")
                    self._last_fails_logged = 0
            elif action == Action.WAIT and not obs.internet_up:
                if self.state.consecutive_fails != self._last_fails_logged:
                    if self.state.consecutive_fails > 0:
                        log.info("no internet (fails=%s/%s, ppp=%s)",
                                 self.state.consecutive_fails, self.cfg.fails, obs.ppp_connected)
                    self._last_fails_logged = self.state.consecutive_fails
            self._maybe_log_signal(now)
            cycles += 1
            if max_cycles is None or cycles < max_cycles:
                self.sleep(self.cfg.interval)
