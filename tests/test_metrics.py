from zte_watchdog.metrics import parse_number, quality, Signal


def test_parse_number_handles_values_empties_and_sentinels():
    assert parse_number("-109") == -109.0
    assert parse_number("7.0") == 7.0
    assert parse_number("") is None
    assert parse_number(None) is None
    assert parse_number("-32768") is None      # 5G "not attached" sentinel
    assert parse_number("-3276.8") is None      # 5G SINR sentinel
    assert parse_number("garbage") is None


def test_quality_bands():
    assert quality(-85, "rsrp") == "good"
    assert quality(-95, "rsrp") == "fair"
    assert quality(-109, "rsrp") == "poor"
    assert quality(-120, "rsrp") == "very poor"
    assert quality(None, "rsrp") == "n/a"
    assert quality(7, "sinr") == "fair"
    assert quality(-12, "rsrq") == "fair"
    assert quality(-18, "rsrq") == "poor"


def test_signal_from_raw_lte_only_marks_no_5g():
    raw = {
        "network_type": "LTE", "lte_rsrp": "-109", "lte_rsrq": "-15",
        "lte_snr": "7.0", "wan_active_band": "LTE BAND 7", "cell_id": "3b09623",
        "Z5g_rsrp": "-32768", "Z5g_rsrq": "", "Z5g_SINR": "-3276.8",
    }
    s = Signal.from_raw(raw)
    assert s.lte_rsrp == -109.0
    assert s.on_5g is False
    assert s.nr_rsrp is None
    assert s.band == "LTE BAND 7"
    assert "RSRP -109" in s.summary()
    assert "LTE" in s.summary()


def test_signal_from_raw_detects_5g_when_nr_metrics_present():
    raw = {"network_type": "ENDC", "Z5g_rsrp": "-95", "Z5g_SINR": "12"}
    s = Signal.from_raw(raw)
    assert s.on_5g is True
    assert s.nr_rsrp == -95.0
