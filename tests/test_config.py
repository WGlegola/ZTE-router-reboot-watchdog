from zte_watchdog.config import Config, load_config


def test_defaults_and_derived():
    cfg = load_config(env={}, cli={})
    assert cfg.ip == "192.168.7.1"
    assert cfg.base_url == "http://192.168.7.1"
    assert cfg.fails == 3
    assert cfg.log_signal is False
    assert cfg.parsed_targets[0] == ("1.1.1.1", 443)
    assert cfg.password is None


def test_env_supplies_password_and_ip():
    cfg = load_config(env={"ZTE_PASSWORD": "pw", "ZTE_IP": "10.0.0.1"}, cli={})
    assert cfg.password == "pw"
    assert cfg.ip == "10.0.0.1"


def test_precedence_cli_over_env_over_file(tmp_path):
    f = tmp_path / "config.toml"
    f.write_text('ip = "1.2.3.4"\nfails = 9\ninterval = 45\n')
    cfg = load_config(path=str(f), env={"ZTE_IP": "5.6.7.8"}, cli={"fails": 2})
    assert cfg.ip == "5.6.7.8"   # env beats file
    assert cfg.fails == 2         # cli beats file
    assert cfg.interval == 45     # file beats default


def test_cli_none_values_are_ignored():
    cfg = load_config(env={}, cli={"fails": None, "log_signal": True})
    assert cfg.fails == 3
    assert cfg.log_signal is True
