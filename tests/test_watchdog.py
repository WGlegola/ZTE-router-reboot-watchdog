import logging

from zte_watchdog.config import Config
from zte_watchdog.watchdog import Action, Observation, WatchdogState, decide, Monitor


def _cfg(**kw):
    return Config(fails=3, cooldown=300, max_reboots_per_hour=3, **kw)


def test_internet_up_is_healthy_and_resets_fails():
    st = WatchdogState(consecutive_fails=2)
    a = decide(st, Observation(True, True, True), _cfg(), now=100)
    assert a == Action.HEALTHY
    assert st.consecutive_fails == 0


def test_gateway_unreachable_waits_and_resets():
    st = WatchdogState(consecutive_fails=2)
    a = decide(st, Observation(False, False, False), _cfg(), now=100)
    assert a == Action.WAIT
    assert st.consecutive_fails == 0


def test_down_but_modem_not_connected_does_not_count():
    st = WatchdogState(consecutive_fails=2)
    a = decide(st, Observation(False, True, False), _cfg(), now=100)
    assert a == Action.WAIT
    assert st.consecutive_fails == 0


def test_hung_session_reboots_only_after_threshold():
    st = WatchdogState()
    cfg = _cfg()
    hung = Observation(False, True, True)
    assert decide(st, hung, cfg, now=1) == Action.WAIT   # 1
    assert decide(st, hung, cfg, now=2) == Action.WAIT   # 2
    a = decide(st, hung, cfg, now=3)                      # 3 -> reboot
    assert a == Action.REBOOT
    assert st.consecutive_fails == 0
    assert st.reboot_times == [3]
    assert st.cooldown_until == 3 + 300


def test_cooldown_suppresses_action():
    st = WatchdogState(cooldown_until=500, consecutive_fails=2)
    a = decide(st, Observation(False, True, True), _cfg(), now=400)
    assert a == Action.WAIT
    assert st.consecutive_fails == 2   # cooldown returns before the increment; count untouched


def test_per_hour_cap_backs_off():
    st = WatchdogState(reboot_times=[10, 20, 30], consecutive_fails=2)
    cfg = _cfg()
    a = decide(st, Observation(False, True, True), cfg, now=40)  # 3 within the hour
    assert a == Action.BACKOFF
    assert st.reboot_times == [10, 20, 30]   # unchanged; no new reboot
    assert st.cooldown_until == 40 + 300


def test_old_reboots_outside_hour_are_purged():
    st = WatchdogState(reboot_times=[1, 2, 3], consecutive_fails=2)
    cfg = _cfg()
    a = decide(st, Observation(False, True, True), cfg, now=4000)  # all > 3600 old
    assert a == Action.REBOOT
    assert st.reboot_times == [4000]


class FakeGateway:
    def __init__(self, health):
        self._health = health
        self.rebooted = 0
    def read_health(self):
        return self._health
    def reboot(self):
        self.rebooted += 1
        return {"result": "success"}


def test_monitor_observe_reads_ppp(monkeypatch):
    import zte_watchdog.watchdog as w
    monkeypatch.setattr(w, "tcp_reachable", lambda *a, **k: True)
    monkeypatch.setattr(w, "internet_up", lambda *a, **k: False)
    gw = FakeGateway({"ppp_status": "ppp_connected", "modem_main_state": "x"})
    mon = Monitor(_cfg(), gw)
    obs = mon.observe()
    assert obs.internet_up is False and obs.gateway_reachable is True and obs.ppp_connected is True


def test_monitor_run_reboots_on_sustained_hang(monkeypatch):
    import zte_watchdog.watchdog as w
    monkeypatch.setattr(w, "tcp_reachable", lambda *a, **k: True)
    monkeypatch.setattr(w, "internet_up", lambda *a, **k: False)
    gw = FakeGateway({"ppp_status": "ppp_connected", "modem_main_state": "x"})
    clock = iter([1, 2, 3, 4, 5]).__next__
    mon = Monitor(_cfg(), gw, clock=clock, sleep=lambda s: None)
    mon.run(max_cycles=3)
    assert gw.rebooted == 1


def test_monitor_warns_when_reboot_does_not_recover(monkeypatch, caplog):
    import zte_watchdog.watchdog as w
    # gateway always reachable, internet always down, ppp connected => hung; the
    # reboot "succeeds" (returns a dict) but nothing changes -> must WARN.
    monkeypatch.setattr(w, "tcp_reachable", lambda *a, **k: True)
    monkeypatch.setattr(w, "internet_up", lambda *a, **k: False)
    gw = FakeGateway({"ppp_status": "ppp_connected", "modem_main_state": "x"})
    cfg = _cfg()
    cfg.cooldown = 10
    clock = iter([1, 2, 3, 20]).__next__   # ramp to reboot at t=3, verify at t=20 (>=13)
    mon = Monitor(cfg, gw, clock=clock, sleep=lambda s: None)
    caplog.set_level(logging.INFO, logger="zte_watchdog")
    mon.run(max_cycles=4)
    assert gw.rebooted == 1
    assert "AD token may be wrong" in caplog.text


def test_monitor_confirms_recovery_after_reboot(monkeypatch, caplog):
    import zte_watchdog.watchdog as w
    reach = iter([True, True, True, False, True]).__next__   # unreachable while rebooting
    up = iter([False, False, False, False, True]).__next__
    monkeypatch.setattr(w, "tcp_reachable", lambda *a, **k: reach())
    monkeypatch.setattr(w, "internet_up", lambda *a, **k: up())
    gw = FakeGateway({"ppp_status": "ppp_connected", "modem_main_state": "x"})
    cfg = _cfg()
    cfg.cooldown = 10
    clock = iter([1, 2, 3, 11, 14]).__next__   # reboot at t=3 (check_at=13), recover at t=14
    mon = Monitor(cfg, gw, clock=clock, sleep=lambda s: None)
    caplog.set_level(logging.INFO, logger="zte_watchdog")
    mon.run(max_cycles=5)
    assert gw.rebooted == 1
    assert "reboot confirmed" in caplog.text


def test_no_internet_not_logged_every_cycle(monkeypatch, caplog):
    import zte_watchdog.watchdog as w
    monkeypatch.setattr(w, "tcp_reachable", lambda *a, **k: True)
    monkeypatch.setattr(w, "internet_up", lambda *a, **k: False)
    gw = FakeGateway({"ppp_status": "ppp_connected"})
    cfg = _cfg()
    cfg.cooldown = 10000   # long cooldown -> daemon stays quiet after the reboot
    clock = iter(range(1, 12)).__next__
    mon = Monitor(cfg, gw, clock=clock, sleep=lambda s: None)
    caplog.set_level(logging.INFO, logger="zte_watchdog")
    mon.run(max_cycles=10)
    # only the ramp (fails=1,2) logs "no internet"; the long cooldown does not repeat it
    assert caplog.text.count("no internet") <= cfg.fails
