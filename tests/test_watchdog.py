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


def test_declined_reboot_is_not_sent_or_counted(monkeypatch):
    import zte_watchdog.watchdog as w
    # Sustained hung session, but the approve callback declines every reboot.
    monkeypatch.setattr(w, "tcp_reachable", lambda *a, **k: True)
    monkeypatch.setattr(w, "internet_up", lambda *a, **k: False)
    gw = FakeGateway({"ppp_status": "ppp_connected", "modem_main_state": "x"})
    cfg = _cfg()
    clock = iter([1, 2, 3, 4]).__next__
    mon = Monitor(cfg, gw, clock=clock, sleep=lambda s: None, approve=lambda obs: False)
    mon.run(max_cycles=3)
    assert gw.rebooted == 0                       # declined -> never rebooted
    assert mon.state.reboot_times == []           # declined reboots don't count toward the cap
    assert mon.state.cooldown_until == 3 + cfg.cooldown   # cooldown kept -> re-ask after cooldown


def test_report_called_each_cycle_with_observation(monkeypatch):
    import zte_watchdog.watchdog as w
    monkeypatch.setattr(w, "tcp_reachable", lambda *a, **k: True)
    monkeypatch.setattr(w, "internet_up", lambda *a, **k: True)
    gw = FakeGateway({"ppp_status": "ppp_connected"})
    seen = []
    clock = iter([1, 2, 3]).__next__
    mon = Monitor(_cfg(), gw, clock=clock, sleep=lambda s: None,
                  report=lambda obs, now: seen.append((obs.internet_up, now)))
    mon.run(max_cycles=2)
    assert seen == [(True, 1), (True, 2)]


def test_declined_reboot_reasks_after_cooldown(monkeypatch):
    # A sustained drop the user keeps declining: prompt once, stay quiet through
    # the cooldown, then prompt AGAIN once the cooldown expires (not every cycle).
    import zte_watchdog.watchdog as w
    monkeypatch.setattr(w, "tcp_reachable", lambda *a, **k: True)
    monkeypatch.setattr(w, "internet_up", lambda *a, **k: False)
    gw = FakeGateway({"ppp_status": "ppp_connected", "modem_main_state": "x"})
    cfg = _cfg()
    cfg.cooldown = 5
    calls = {"n": 0}

    def decline(obs):
        calls["n"] += 1
        return False

    clock = iter([1, 2, 3, 9, 10, 11]).__next__   # reboot@t=3 (cooldown->8), re-reboot@t=11
    mon = Monitor(cfg, gw, clock=clock, sleep=lambda s: None, approve=decline)
    mon.run(max_cycles=6)
    assert calls["n"] == 2                 # asked at the first drop and again after cooldown
    assert gw.rebooted == 0
    assert mon.state.reboot_times == []    # declines never count toward the cap


def test_supervised_confirm_triggers_reboot(monkeypatch):
    # Supervised loop: on a sustained drop, approving actually reboots and counts.
    import zte_watchdog.watchdog as w
    monkeypatch.setattr(w, "tcp_reachable", lambda *a, **k: True)
    monkeypatch.setattr(w, "internet_up", lambda *a, **k: False)
    gw = FakeGateway({"ppp_status": "ppp_connected", "modem_main_state": "x"})
    calls = {"n": 0}

    def approve(obs):
        calls["n"] += 1
        return True

    clock = iter([1, 2, 3, 4]).__next__
    mon = Monitor(_cfg(), gw, clock=clock, sleep=lambda s: None, approve=approve)
    mon.run(max_cycles=3)
    assert calls["n"] == 1
    assert gw.rebooted == 1
    assert mon.state.reboot_times == [3]   # an approved reboot IS counted toward the cap


def test_signal_logged_and_throttled_when_enabled(monkeypatch, caplog):
    import zte_watchdog.watchdog as w
    monkeypatch.setattr(w, "tcp_reachable", lambda *a, **k: True)
    monkeypatch.setattr(w, "internet_up", lambda *a, **k: True)

    class SignalGateway:
        def __init__(self):
            self.reads = 0
        def read_health(self):
            return {"ppp_status": "ppp_connected"}
        def read_metrics(self):
            self.reads += 1
            return {"network_type": "LTE", "lte_rsrp": "-100", "wan_active_band": "LTE BAND 3"}

    gw = SignalGateway()
    cfg = _cfg()
    cfg.log_signal = True
    cfg.metrics_interval = 1000        # long -> logs once, then throttled
    clock = iter([1, 2, 3]).__next__
    mon = Monitor(cfg, gw, clock=clock, sleep=lambda s: None)
    caplog.set_level(logging.INFO, logger="zte_watchdog")
    mon.run(max_cycles=3)
    assert caplog.text.count("signal:") == 1   # gated by metrics_interval
    assert gw.reads == 1
    assert "RSRP -100" in caplog.text


def test_uses_fail_interval_once_a_failure_is_counted(monkeypatch):
    import zte_watchdog.watchdog as w
    monkeypatch.setattr(w, "tcp_reachable", lambda *a, **k: True)
    ups = iter([True, False, False]).__next__      # healthy, then two failures
    monkeypatch.setattr(w, "internet_up", lambda *a, **k: ups())
    gw = FakeGateway({"ppp_status": "ppp_connected", "modem_main_state": "x"})
    cfg = _cfg()
    cfg.interval = 30
    cfg.fail_interval = 5
    sleeps = []
    clock = iter([1, 2, 3]).__next__
    mon = Monitor(cfg, gw, clock=clock, sleep=sleeps.append)
    mon.run(max_cycles=3)
    # healthy cycle sleeps at interval; once consecutive_fails>0 it uses fail_interval
    assert sleeps == [30, 5]


def test_health_snapshot_reflects_healthy_state(monkeypatch):
    import zte_watchdog.watchdog as w
    monkeypatch.setattr(w, "tcp_reachable", lambda *a, **k: True)
    monkeypatch.setattr(w, "internet_up", lambda *a, **k: True)
    gw = FakeGateway({"ppp_status": "ppp_connected", "modem_main_state": "x"})
    clock = iter([100, 101, 102]).__next__
    mon = Monitor(_cfg(), gw, clock=clock, sleep=lambda s: None)
    mon.run(max_cycles=2)
    snap = mon.health_snapshot(now=105)
    assert snap["status"] == "healthy"
    assert snap["internet_up"] is True
    assert snap["consecutive_fails"] == 0
    assert snap["reboots_last_hour"] == 0
    assert snap["seconds_since_check"] == 4.0    # last check ran at now=101
    assert snap["uptime_seconds"] == 5.0         # started at now=100


def test_health_snapshot_degraded_during_hung_session(monkeypatch):
    import zte_watchdog.watchdog as w
    monkeypatch.setattr(w, "tcp_reachable", lambda *a, **k: True)
    monkeypatch.setattr(w, "internet_up", lambda *a, **k: False)
    gw = FakeGateway({"ppp_status": "ppp_connected", "modem_main_state": "x"})
    clock = iter([1, 2]).__next__
    mon = Monitor(_cfg(), gw, clock=clock, sleep=lambda s: None)
    mon.run(max_cycles=1)
    snap = mon.health_snapshot(now=2)
    assert snap["status"] == "degraded"          # internet down, gw up, ppp connected
    assert snap["internet_up"] is False
    assert snap["consecutive_fails"] == 1
