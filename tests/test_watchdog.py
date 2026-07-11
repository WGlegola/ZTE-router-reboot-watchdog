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
    st = WatchdogState(cooldown_until=500)
    a = decide(st, Observation(False, True, True), _cfg(), now=400)
    assert a == Action.WAIT
    assert st.consecutive_fails == 0   # not counted during cooldown


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
