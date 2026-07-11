"""Pure parsing and interpretation of ZTE signal fields. No I/O."""

from __future__ import annotations

from dataclasses import dataclass

# Values that mean "not attached to this RAT" / unavailable rather than a reading.
_SENTINELS = {"-32768", "32767", "-3276.8", "3276.7"}

# (min_inclusive, label) thresholds, best first. Value >= min → that label.
_BANDS = {
    "rsrp": [(-90, "good"), (-100, "fair"), (-110, "poor")],
    "rsrq": [(-10, "good"), (-15, "fair"), (-20, "poor")],
    "sinr": [(20, "excellent"), (13, "good"), (0, "fair")],
}


def parse_number(raw) -> float | None:
    """Float for a numeric field, or None for empty/sentinel/unparseable."""
    if raw is None:
        return None
    s = str(raw).strip()
    if s == "" or s in _SENTINELS:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def quality(value: float | None, kind: str) -> str:
    if value is None:
        return "n/a"
    for threshold, label in _BANDS[kind]:
        if value >= threshold:
            return label
    return "very poor" if kind in ("rsrp", "rsrq") else "poor"


@dataclass
class Signal:
    network_type: str | None
    lte_rsrp: float | None
    lte_rsrq: float | None
    lte_snr: float | None
    nr_rsrp: float | None
    nr_rsrq: float | None
    nr_sinr: float | None
    band: str | None
    cell_id: str | None
    on_5g: bool

    @classmethod
    def from_raw(cls, raw: dict) -> "Signal":
        nr_rsrp = parse_number(raw.get("Z5g_rsrp"))
        nr_sinr = parse_number(raw.get("Z5g_SINR"))
        return cls(
            network_type=(raw.get("network_type") or "").strip() or None,
            lte_rsrp=parse_number(raw.get("lte_rsrp")),
            lte_rsrq=parse_number(raw.get("lte_rsrq")),
            lte_snr=parse_number(raw.get("lte_snr")),
            nr_rsrp=nr_rsrp,
            nr_rsrq=parse_number(raw.get("Z5g_rsrq")),
            nr_sinr=nr_sinr,
            band=(raw.get("wan_active_band") or "").strip() or None,
            cell_id=(raw.get("cell_id") or "").strip() or None,
            # 5G is attached iff a real NR metric came back (not a sentinel).
            on_5g=nr_rsrp is not None or nr_sinr is not None,
        )

    def summary(self) -> str:
        if self.on_5g:
            return (
                f"net={self.network_type} 5G RSRP {self.nr_rsrp} ({quality(self.nr_rsrp, 'rsrp')}) "
                f"SINR {self.nr_sinr} ({quality(self.nr_sinr, 'sinr')}) band={self.band} cell={self.cell_id}"
            )
        return (
            f"net={self.network_type} LTE RSRP {self.lte_rsrp} ({quality(self.lte_rsrp, 'rsrp')}) "
            f"RSRQ {self.lte_rsrq} ({quality(self.lte_rsrq, 'rsrq')}) "
            f"SINR {self.lte_snr} ({quality(self.lte_snr, 'sinr')}) band={self.band} cell={self.cell_id}"
        )
