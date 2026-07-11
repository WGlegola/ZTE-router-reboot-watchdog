from zte_watchdog.config import Config
from zte_watchdog.watchdog import Observation
from zte_watchdog.__main__ import build_parser, _confirm_reboot, _heartbeat_report


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


def test_confirm_reboot_true_on_yes():
    approve = _confirm_reboot(prompt=lambda _: "y")
    assert approve(object()) is True


def test_confirm_reboot_false_on_no_or_empty():
    assert _confirm_reboot(prompt=lambda _: "n")(object()) is False
    assert _confirm_reboot(prompt=lambda _: "")(object()) is False


def test_heartbeat_report_prints_status_and_signal():
    lines = []
    report = _heartbeat_report(Config(password="x"), FakeGateway(), out=lines.append)
    report(Observation(internet_up=True, gateway_reachable=True, ppp_connected=True), now=1.0)
    assert lines and "internet=up" in lines[0]
    assert "ppp=connected" in lines[0]
    assert "RSRP" in lines[0]   # signal appended because password set + gateway reachable


def test_heartbeat_report_skips_signal_without_password():
    lines = []
    report = _heartbeat_report(Config(password=None), FakeGateway(), out=lines.append)
    report(Observation(internet_up=False, gateway_reachable=True, ppp_connected=False), now=1.0)
    assert "internet=DOWN" in lines[0]
    assert "RSRP" not in lines[0]   # no authenticated signal read without a password
