"""Negative and robustness tests (N1 - N4)."""

import pytest
import subprocess
import sys
import time
from unittest.mock import patch
from server.monitor_server import MonitorServer
from agent.health_agent import HealthAgent


def test_n1_server_bad_config_exits(tmp_path):
    """N1: Server started with bad config exits with non-zero exit code."""
    bad_cfg = tmp_path / "bad_config.yaml"
    bad_cfg.write_text("thresholds:\n  cpu_percent:\n    warning: 95\n    critical: 50\n")

    res = subprocess.run(
        [sys.executable, "server/monitor_server.py", "--config", str(bad_cfg)],
        capture_output=True,
        text=True,
    )
    assert res.returncode != 0
    assert ("strictly less than" in res.stderr or "ConfigError" in res.stderr or "strictly less than" in res.stdout)


def test_n2_agent_unreachable_server():
    """N2: Agent started with unreachable/invalid IP keeps running, logs errors, does not crash."""
    agent = HealthAgent(
        node_id="h_unreachable",
        server_ip="192.0.2.1",  # Test-net unreachable IP
        server_port=5005,
        interval=0.05,
        fail_after=5,
    )
    # Should complete without uncaught exceptions
    agent.run()
    assert agent.seq >= 5


def test_n3_agent_negative_or_zero_interval():
    """N3: Agent started with --interval 0 or negative causes argument error."""
    res1 = subprocess.run(
        [sys.executable, "agent/health_agent.py", "--id", "h1", "--interval", "0"],
        capture_output=True,
        text=True,
    )
    assert res1.returncode != 0

    res2 = subprocess.run(
        [sys.executable, "agent/health_agent.py", "--id", "h1", "--interval", "-2"],
        capture_output=True,
        text=True,
    )
    assert res2.returncode != 0


def test_n4_clock_jump_negative_delay_clamped(tmp_path):
    """N4: Simulated clock jump backward -> server does not produce negative delay."""
    csv_file = str(tmp_path / "n4_reports.csv")
    server = MonitorServer(
        host="127.0.0.1",
        port=0,
        config_path="config.yaml",
        csv_file=csv_file,
        dashboard_interval=0.0,
    )

    # Agent packet has sent_ts in future relative to server recv_ts
    agent_sent_ts = 2000.0
    server_recv_ts = 1990.0  # Clock jumped backwards on server

    msg = {
        "version": 1,
        "type": "HEALTH",
        "node_id": "h_clock_jump",
        "seq": 1,
        "sent_ts": agent_sent_ts,
        "priority": "NORMAL",
        "metrics": {"cpu_percent": 10.0, "mem_percent": 10.0, "process_count": 10},
    }
    from common.protocol import encode
    data = encode(msg)

    server.process_datagram(data, ("127.0.0.1", 5005), recv_ts=server_recv_ts)
    node = server.registry.get_node("h_clock_jump")
    assert node is not None
    # Delay must be clamped to 0.0, not negative
    assert node.last_delay_ms == 0.0
