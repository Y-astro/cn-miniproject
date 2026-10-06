"""Unit tests for stats collector (S1 - S4)."""

import pytest
from unittest.mock import patch
import psutil
from agent.stats_collector import StatsCollector


def test_s1_real_mode_valid_ranges():
    """S1: Real mode returns all required keys with valid numeric ranges."""
    collector = StatsCollector(mode="real")
    stats = collector.collect()

    assert "cpu_percent" in stats
    assert "mem_percent" in stats
    assert "process_count" in stats
    assert "top_processes" in stats
    assert "net" in stats

    assert 0.0 <= stats["cpu_percent"] <= 100.0
    assert 0.0 <= stats["mem_percent"] <= 100.0
    assert stats["process_count"] >= 0
    assert isinstance(stats["top_processes"], list)
    assert isinstance(stats["net"], dict)
    assert stats["net"]["bytes_sent"] >= 0


def test_s2_simulated_spike_mode():
    """S2: Simulated spike mode produces CPU >= 90 on configured tick."""
    spike_interval = 3
    collector = StatsCollector(mode="simulated", sim_pattern="spike", spike_interval=spike_interval)

    # Tick 1: normal
    s1 = collector.collect()
    assert s1["cpu_percent"] < 70.0

    # Tick 2: normal
    s2 = collector.collect()
    assert s2["cpu_percent"] < 70.0

    # Tick 3: spike tick (3 % 3 == 0)
    s3 = collector.collect()
    assert s3["cpu_percent"] >= 90.0
    assert s3["mem_percent"] >= 90.0
    assert s3["process_count"] >= 500


def test_s3_simulated_normal_stays_below_warning():
    """S3: Simulated normal mode stays below the WARNING threshold (70%)."""
    collector = StatsCollector(mode="simulated", sim_pattern="normal")
    for _ in range(20):
        stats = collector.collect()
        assert stats["cpu_percent"] < 70.0
        assert stats["mem_percent"] < 70.0
        assert stats["process_count"] < 300


def test_s4_psutil_exception_fallback():
    """S4: psutil raising an exception triggers fallback without crashing."""
    collector = StatsCollector(mode="real")
    with patch("psutil.cpu_percent", side_effect=RuntimeError("psutil hardware read failed")):
        stats = collector.collect()
        assert stats["cpu_percent"] == 0.0
        assert "collector_error" in stats
