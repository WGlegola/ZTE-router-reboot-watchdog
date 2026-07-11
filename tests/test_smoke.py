def test_package_imports():
    import zte_watchdog
    assert isinstance(zte_watchdog.__version__, str)
