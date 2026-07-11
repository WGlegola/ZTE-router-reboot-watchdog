"""HTTP client for the ZTE MC801A goform API. All device I/O lives here."""

from __future__ import annotations

import hashlib

import requests

_GET_PATH = "/goform/goform_get_cmd_process"
_SET_PATH = "/goform/goform_set_cmd_process"


class GatewayError(Exception):
    pass


class LoginError(GatewayError):
    pass


def _sha256_upper(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest().upper()


def _md5_lower(s: str) -> str:
    return hashlib.md5(s.encode()).hexdigest()


class Gateway:
    def __init__(self, base_url: str, password: str | None = None,
                 timeout: float = 10.0, session=None):
        self.base_url = base_url.rstrip("/")
        self.password = password
        self.timeout = timeout
        self.session = session or requests.Session()
        self.session.headers.update(
            {"Referer": self.base_url + "/", "User-Agent": "Mozilla/5.0"}
        )
        self._logged_in = False

    def _get(self, cmd: str, multi: bool = False) -> dict:
        params = {"isTest": "false", "cmd": cmd}
        if multi:
            params["multi_data"] = "1"
        r = self.session.get(self.base_url + _GET_PATH, params=params, timeout=self.timeout)
        r.raise_for_status()
        return r.json()

    def _post(self, data: dict) -> dict:
        r = self.session.post(
            self.base_url + _SET_PATH, data={"isTest": "false", **data}, timeout=self.timeout
        )
        r.raise_for_status()
        return r.json()

    # --- unauthenticated ---
    def read_health(self) -> dict:
        return self._get("ppp_status,modem_main_state,signalbar", multi=True)

    # --- authenticated ---
    def login(self) -> None:
        if not self.password:
            raise LoginError("no password configured")
        ld = self._get("LD")["LD"]
        hashed = _sha256_upper(_sha256_upper(self.password) + ld)
        resp = self._post({"goformId": "LOGIN", "password": hashed})
        if str(resp.get("result")) != "0":   # 0 = success on this firmware; 3 = failure
            raise LoginError(f"login failed (result={resp.get('result')})")
        self._logged_in = True

    def ensure_login(self) -> None:
        if self._logged_in:
            try:
                if self._get("loginfo").get("loginfo") == "ok":
                    return
            except Exception:  # noqa: BLE001 - any failure just falls through to a fresh login
                pass
        self._logged_in = False
        self.login()

    def read_metrics(self) -> dict:
        self.ensure_login()
        fields = ("network_type,lte_rsrp,lte_rsrq,lte_snr,wan_active_band,"
                  "Z5g_rsrp,Z5g_rsrq,Z5g_SINR,nr5g_action_band,cell_id")
        return self._get(fields, multi=True)

    def reboot(self) -> dict:
        self.ensure_login()
        ver = self._get("wa_inner_version,cr_version", multi=True)
        a = _md5_lower(ver.get("wa_inner_version", "") + ver.get("cr_version", ""))
        rd = self._get("RD")["RD"]
        ad = _md5_lower(a + rd)
        return self._post({"goformId": "REBOOT_DEVICE", "AD": ad})
