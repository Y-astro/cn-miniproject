"""Unit tests for alert engine (A1 - A6)."""

import pytest
from server.alert_engine import AlertEngine
from common.config_loader import ConfigError


def get_base_config():
    return {
        "server": {"port": 5005, "failure_timeout_multiplier": 3.0},
        "agent": {"default_interval": 1.0},
        "thresholds": {
            "cpu_percent": {"warning": 70.0, "critical": 90.0},
            "mem_percent": {"warning": 75.0, "critical": 90.0},
            "process_count": {"warning": 300, "critical": 500},
            "packet_loss_percent": {"warning": 5.0, "critical": 20.0},
            "silence_multiplier": 3.0,
        },
        "alerts": {
            "cooldown_seconds": 5.0,
            "hysteresis_percent": 2.0,
        },
    }


def test_a1_cpu_boundary_values():
    """A1: CPU 69 -> no alert; 70 -> WARNING; 90 -> CRITICAL."""
    engine = AlertEngine(get_base_config())

    # CPU 69 -> no alert
    a1 = engine.evaluate_metric("h1", "cpu_percent", 69.0, trigger_ts=100.0, now=100.01)
    assert a1 is None

    # CPU 70 -> WARNING
    a2 = engine.evaluate_metric("h1", "cpu_percent", 70.0, trigger_ts=101.0, now=101.01)
    assert a2 is not None
    assert a2.severity == "WARNING"
    assert a2.threshold == 70.0

    # CPU 90 -> CRITICAL
    a3 = engine.evaluate_metric("h1", "cpu_percent", 90.0, trigger_ts=102.0, now=102.01)
    assert a3 is not None
    assert a3.severity == "CRITICAL"
    assert a3.threshold == 90.0


def test_a2_memory_and_process_count_thresholds():
    """A2: Memory and process-count thresholds behave the same way."""
    engine = AlertEngine(get_base_config())

    # Memory: 74 -> None, 75 -> WARNING, 90 -> CRITICAL
    assert engine.evaluate_metric("h1", "mem_percent", 74.0, trigger_ts=1.0, now=1.01) is None
    m_warn = engine.evaluate_metric("h1", "mem_percent", 75.0, trigger_ts=2.0, now=2.01)
    assert m_warn.severity == "WARNING"
    m_crit = engine.evaluate_metric("h1", "mem_percent", 90.0, trigger_ts=3.0, now=3.01)
    assert m_crit.severity == "CRITICAL"

    # Process count: 299 -> None, 300 -> WARNING, 500 -> CRITICAL
    assert engine.evaluate_metric("h1", "process_count", 299, trigger_ts=4.0, now=4.01) is None
    p_warn = engine.evaluate_metric("h1", "process_count", 300, trigger_ts=5.0, now=5.01)
    assert p_warn.severity == "WARNING"
    p_crit = engine.evaluate_metric("h1", "process_count", 500, trigger_ts=6.0, now=6.01)
    assert p_crit.severity == "CRITICAL"


def test_a3_cooldown_window():
    """A3: The same alert is not re-fired within the cooldown window."""
    cfg = get_base_config()
    cfg["alerts"]["cooldown_seconds"] = 10.0
    engine = AlertEngine(cfg)

    # First fire at t=100
    a1 = engine.evaluate_metric("h1", "cpu_percent", 75.0, trigger_ts=100.0, now=100.0)
    assert a1 is not None

    # Same metric and severity within cooldown (t=105, 5s < 10s cooldown) -> suppressed
    a2 = engine.evaluate_metric("h1", "cpu_percent", 76.0, trigger_ts=105.0, now=105.0)
    assert a2 is None

    # After cooldown elapsed (t=111, 11s > 10s cooldown) -> re-fired
    a3 = engine.evaluate_metric("h1", "cpu_percent", 76.0, trigger_ts=111.0, now=111.0)
    assert a3 is not None
    assert a3.severity == "WARNING"


def test_a4_hysteresis_clearing():
    """A4: Alert clears when the metric drops below the threshold - hysteresis."""
    cfg = get_base_config()
    cfg["thresholds"]["cpu_percent"]["warning"] = 70.0
    cfg["alerts"]["hysteresis_percent"] = 2.0
    engine = AlertEngine(cfg)

    # Fire warning at 70
    a1 = engine.evaluate_metric("h1", "cpu_percent", 70.0, trigger_ts=1.0, now=1.0)
    assert a1 is not None

    # Drops to 69.0 (inside hysteresis deadband 70.0 - 2.0 = 68.0): remains active, not cleared yet
    assert ("h1", "cpu_percent") in engine._active_states

    # Drops to 67.5 (< 68.0 clear threshold): alert clears
    engine.evaluate_metric("h1", "cpu_percent", 67.5, trigger_ts=2.0, now=2.0)
    assert ("h1", "cpu_percent") not in engine._active_states


def test_a5_multiple_metrics_over_threshold():
    """A5: Multiple metrics over threshold -> multiple alerts with severities."""
    engine = AlertEngine(get_base_config())
    metrics = {
        "cpu_percent": 95.0,    # CRITICAL
        "mem_percent": 80.0,    # WARNING
        "process_count": 100,   # NORMAL
    }
    alerts = engine.evaluate_report("h1", metrics, trigger_ts=10.0, now=10.05)
    assert len(alerts) == 2
    severities = {a.severity for a in alerts}
    assert "CRITICAL" in severities
    assert "WARNING" in severities


def test_a6_invalid_config_raises():
    """A6: Invalid config (WARNING >= CRITICAL, negative number, missing key) raises on load."""
    bad_cfg1 = get_base_config()
    bad_cfg1["thresholds"]["cpu_percent"]["warning"] = 95.0  # warn > crit (95 > 90)
    with pytest.raises(ConfigError):
        AlertEngine(bad_cfg1)

    bad_cfg2 = get_base_config()
    bad_cfg2["thresholds"]["mem_percent"]["critical"] = -10.0  # negative
    with pytest.raises(ConfigError):
        AlertEngine(bad_cfg2)

    bad_cfg3 = get_base_config()
    del bad_cfg3["thresholds"]["cpu_percent"]  # missing key
    with pytest.raises(ConfigError):
        AlertEngine(bad_cfg3)
