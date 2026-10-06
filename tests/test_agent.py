"""Unit tests for UDP Health Agent."""

import socket
import time
import pytest
from unittest.mock import patch, MagicMock
from agent.health_agent import HealthAgent, TOS_EF_CRITICAL, TOS_BEST_EFFORT


def test_agent_initialization_invalid_args():
    """Agent raises ValueError on invalid arguments."""
    with pytest.raises(ValueError, match="Interval must be positive"):
        HealthAgent(node_id="h1", interval=-1.0)

    with pytest.raises(ValueError, match="Interval must be positive"):
        HealthAgent(node_id="h1", interval=0.0)

    with pytest.raises(ValueError, match="Port must be between 1 and 65535"):
        HealthAgent(node_id="h1", server_port=99999)

    with pytest.raises(ValueError, match="node_id must be a non-empty string"):
        HealthAgent(node_id="")


def test_agent_is_critical_logic():
    """Agent correctly evaluates critical threshold violations."""
    agent = HealthAgent(node_id="h1", interval=1.0)
    # Normal metrics
    assert not agent.is_critical({"cpu_percent": 30.0, "mem_percent": 40.0, "process_count": 100})

    # High CPU
    assert agent.is_critical({"cpu_percent": 75.0, "mem_percent": 40.0, "process_count": 100})

    # High Memory
    assert agent.is_critical({"cpu_percent": 30.0, "mem_percent": 80.0, "process_count": 100})

    # High Process count
    assert agent.is_critical({"cpu_percent": 30.0, "mem_percent": 40.0, "process_count": 350})


def test_agent_build_payload():
    """Agent increments sequence and formats payload properly."""
    agent = HealthAgent(node_id="h1", interval=1.0, mode="simulated", sim_pattern="normal")
    p1 = agent.build_payload()
    assert p1["seq"] == 1
    assert p1["node_id"] == "h1"
    assert p1["priority"] == "NORMAL"
    assert p1["type"] == "HEALTH"

    p2 = agent.build_payload()
    assert p2["seq"] == 2


def test_agent_build_payload_fallback_on_error():
    """Agent falls back to HEARTBEAT if collector fails."""
    agent = HealthAgent(node_id="h1", interval=1.0)
    with patch.object(agent.collector, "collect", side_effect=RuntimeError("Collector failed")):
        payload = agent.build_payload()
        assert payload["type"] == "HEARTBEAT"
        assert payload["priority"] == "NORMAL"
        assert "metrics" not in payload


def test_agent_send_report_and_tos():
    """Agent transmits packet and applies TOS."""
    temp_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    temp_sock.bind(("127.0.0.1", 0))
    port = temp_sock.getsockname()[1]

    agent = HealthAgent(node_id="h1", server_ip="127.0.0.1", server_port=port, interval=1.0)
    agent._init_socket()

    payload_normal = agent.build_payload()
    assert agent.send_report(payload_normal) is True
    data, addr = temp_sock.recvfrom(2048)
    assert len(data) > 0

    # Test critical payload TOS change
    payload_crit = agent.build_payload()
    payload_crit["priority"] = "CRITICAL"
    assert agent.send_report(payload_crit) is True
    assert agent._current_tos == TOS_EF_CRITICAL

    agent.stop()
    temp_sock.close()


def test_agent_network_error_resilience():
    """Agent handles send errors gracefully without crashing."""
    agent = HealthAgent(node_id="h1", server_ip="999.999.999.999", server_port=5005, interval=1.0)
    agent._init_socket()
    payload = agent.build_payload()
    # Sending to invalid IP address raises socket error or OSError
    result = agent.send_report(payload)
    assert result is False
    agent.stop()


def test_agent_fail_after_simulation():
    """Agent simulates crash after fail_after packets."""
    agent = HealthAgent(node_id="h1", interval=0.01, fail_after=3)
    agent._init_socket()
    agent.run()
    assert agent.seq >= 3
    assert not agent.running
