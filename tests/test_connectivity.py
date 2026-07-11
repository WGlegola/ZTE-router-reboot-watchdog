import zte_watchdog.connectivity as c


def test_parse_target_defaults_port_443():
    assert c.parse_target("1.1.1.1") == ("1.1.1.1", 443)
    assert c.parse_target("8.8.8.8:53") == ("8.8.8.8", 53)


def test_internet_up_true_if_any_target_answers(monkeypatch):
    def fake(host, port, timeout=4.0):
        return host == "8.8.8.8"
    monkeypatch.setattr(c, "tcp_reachable", fake)
    assert c.internet_up([("1.1.1.1", 443), ("8.8.8.8", 53)]) is True


def test_internet_up_false_if_none_answer(monkeypatch):
    monkeypatch.setattr(c, "tcp_reachable", lambda *a, **k: False)
    assert c.internet_up([("1.1.1.1", 443), ("8.8.8.8", 53)]) is False


def test_tcp_reachable_false_on_oserror(monkeypatch):
    def boom(addr, timeout=None):
        raise OSError("refused")
    monkeypatch.setattr(c.socket, "create_connection", boom)
    assert c.tcp_reachable("10.0.0.1", 80) is False
