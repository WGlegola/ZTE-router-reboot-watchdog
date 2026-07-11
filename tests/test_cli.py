from zte_watchdog.config import Config
from zte_watchdog.__main__ import build_parser, heartbeat


class FakeGateway:
    def __init__(self):
        self.rebooted = 0
    def read_health(self):
        return {"ppp_status": "ppp_connected", "modem_main_state": "modem_init_complete"}
    def read_metrics(self):
        return {"network_type": "LTE", "lte_rsrp": "-109", "wan_active_band": "LTE BAND 7"}
    def reboot(self):
        self.rebooted += 1
        return {"result": "success"}


def test_parser_defaults_to_daemon():
    args = build_parser().parse_args([])
    assert args.heartbeat is False
    # default is None (not False) so an absent flag doesn't override config-file log_signal
    assert args.log_signal is None


def test_parser_flags():
    args = build_parser().parse_args(["--heartbeat", "--log-signal", "--fails", "2"])
    assert args.heartbeat is True
    assert args.log_signal is True
    assert args.fails == 2


def test_heartbeat_reboots_on_yes(monkeypatch):
    import zte_watchdog.__main__ as m
    monkeypatch.setattr(m, "tcp_reachable", lambda *a, **k: True)
    monkeypatch.setattr(m, "internet_up", lambda *a, **k: True)
    gw = FakeGateway()
    lines = []
    heartbeat(Config(password="x"), gw, prompt=lambda _: "y", out=lines.append)
    assert gw.rebooted == 1
    assert any("ppp_connected" in ln for ln in lines)


def test_heartbeat_declines_on_no(monkeypatch):
    import zte_watchdog.__main__ as m
    monkeypatch.setattr(m, "tcp_reachable", lambda *a, **k: True)
    monkeypatch.setattr(m, "internet_up", lambda *a, **k: False)
    gw = FakeGateway()
    heartbeat(Config(password="x"), gw, prompt=lambda _: "n", out=lambda _s: None)
    assert gw.rebooted == 0
