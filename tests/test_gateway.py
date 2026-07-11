import hashlib

import pytest

from zte_watchdog.gateway import Gateway, LoginError


class FakeResp:
    def __init__(self, payload):
        self._payload = payload
    def raise_for_status(self):
        pass
    def json(self):
        return self._payload


class FakeSession:
    """Routes GET by cmd and POST by goformId to canned JSON; records calls."""
    def __init__(self, get_map, post_map):
        self.headers = {}
        self.get_map = get_map
        self.post_map = post_map
        self.calls = []
    def get(self, url, params=None, timeout=None):
        self.calls.append(("GET", params))
        return FakeResp(self.get_map[params["cmd"]])
    def post(self, url, data=None, timeout=None):
        self.calls.append(("POST", data))
        return FakeResp(self.post_map[data["goformId"]])


def _expected_login_hash(pw, ld):
    inner = hashlib.sha256(pw.encode()).hexdigest().upper()
    return hashlib.sha256((inner + ld).encode()).hexdigest().upper()


def test_read_health_needs_no_login():
    sess = FakeSession(
        {"ppp_status,modem_main_state,signalbar":
             {"ppp_status": "ppp_connected", "modem_main_state": "modem_init_complete", "signalbar": "2"}},
        {},
    )
    gw = Gateway("http://192.168.7.1", session=sess)
    health = gw.read_health()
    assert health["ppp_status"] == "ppp_connected"
    assert all(call[0] == "GET" for call in sess.calls)   # never posted/logged in


def test_login_uses_variant_a_and_accepts_result_0():
    ld = "E29C9C180C6279B0"
    sess = FakeSession({"LD": {"LD": ld}}, {"LOGIN": {"result": "0"}})
    gw = Gateway("http://192.168.7.1", password="secret", session=sess)
    gw.login()
    login_call = [c for c in sess.calls if c[0] == "POST"][0]
    assert login_call[1]["password"] == _expected_login_hash("secret", ld)
    assert login_call[1]["goformId"] == "LOGIN"


def test_login_raises_on_result_3():
    sess = FakeSession({"LD": {"LD": "abc"}}, {"LOGIN": {"result": "3"}})
    gw = Gateway("http://192.168.7.1", password="wrong", session=sess)
    with pytest.raises(LoginError):
        gw.login()


def test_reboot_computes_ad_token_and_posts_reboot_device():
    import hashlib as h
    ld, rd = "abc", "6364d3f0f495b6ab9dcf8d3b5c6e0b01"
    ver = {"wa_inner_version": "BD_TMOPLMC801AV1.0.0B07", "cr_version": ""}
    sess = FakeSession(
        {"LD": {"LD": ld}, "loginfo": {"loginfo": "no"},
         "wa_inner_version,cr_version": ver, "RD": {"RD": rd}},
        {"LOGIN": {"result": "0"}, "REBOOT_DEVICE": {"result": "success"}},
    )
    gw = Gateway("http://192.168.7.1", password="secret", session=sess)
    gw.reboot()
    a = h.md5((ver["wa_inner_version"] + ver["cr_version"]).encode()).hexdigest()
    expected_ad = h.md5((a + rd).encode()).hexdigest()
    reboot_call = [c for c in sess.calls if c[0] == "POST" and c[1]["goformId"] == "REBOOT_DEVICE"][0]
    assert reboot_call[1]["AD"] == expected_ad
