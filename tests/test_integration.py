"""Integration tests for UDP Health Monitoring System (I1 - I7)."""

import os
import socket
import threading
import time
import pytest
from common.protocol import encode
from server.monitor_server import MonitorServer
from agent.health_agent import HealthAgent
from experiments.run_congestion_test import run_scenario


def get_ephemeral_port() -> int:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def test_i1_multiple_agents_reports_arrive(tmp_path):
    """I1: 3 hosts + server, all reports arrive within 2 intervals."""
    port = get_ephemeral_port()
    csv_file = str(tmp_path / "i1_reports.csv")

    server = MonitorServer(host="127.0.0.1", port=port, csv_file=csv_file, dashboard_interval=0.0)
    s_thread = threading.Thread(target=server.run, daemon=True)
    s_thread.start()
    time.sleep(0.1)

    interval = 0.2
    agents = [
        HealthAgent(node_id=f"h{i}", server_ip="127.0.0.1", server_port=port, interval=interval, mode="simulated")
        for i in range(1, 4)
    ]
    a_threads = [threading.Thread(target=ag.run, daemon=True) for ag in agents]
    for t in a_threads:
        t.start()

    time.sleep(interval * 2.5)

    for ag in agents:
        ag.stop()
    for t in a_threads:
        t.join(timeout=0.5)
    server.stop()
    s_thread.join(timeout=0.5)

    for i in range(1, 4):
        node = server.registry.get_node(f"h{i}")
        assert node is not None
        assert node.total_received >= 2
        assert node.status == "UP"


def test_i2_spike_triggers_critical_alert_low_latency(tmp_path):
    """I2: Simulated CPU spike on h2 -> CRITICAL alert on server with latency < 500ms."""
    port = get_ephemeral_port()
    csv_file = str(tmp_path / "i2_reports.csv")
    alerts_file = str(tmp_path / "i2_alerts.csv")

    server = MonitorServer(
        host="127.0.0.1",
        port=port,
        csv_file=csv_file,
        alerts_csv_file=alerts_file,
        dashboard_interval=0.0,
    )
    s_thread = threading.Thread(target=server.run, daemon=True)
    s_thread.start()
    time.sleep(0.1)

    agent = HealthAgent(
        node_id="h2",
        server_ip="127.0.0.1",
        server_port=port,
        interval=0.1,
        mode="simulated",
        sim_pattern="spike",
        spike_interval=1,  # Spikes immediately on first tick
    )
    a_thread = threading.Thread(target=agent.run, daemon=True)
    a_thread.start()

    time.sleep(0.3)

    agent.stop()
    a_thread.join(timeout=0.5)
    server.stop()
    s_thread.join(timeout=0.5)

    assert len(server.alert_engine.alert_history) >= 1
    critical_alerts = [a for a in server.alert_engine.alert_history if a.severity == "CRITICAL"]
    assert len(critical_alerts) >= 1
    alert = critical_alerts[0]
    assert alert.node_id == "h2"
    assert alert.alert_latency_ms < 500.0


def test_i3_kill_agent_and_recover(tmp_path):
    """I3: Kill agent h3 -> NODE_DOWN within 3*interval + 1s; restart -> NODE_RECOVERED."""
    port = get_ephemeral_port()
    server = MonitorServer(host="127.0.0.1", port=port, dashboard_interval=0.0)
    s_thread = threading.Thread(target=server.run, daemon=True)
    s_thread.start()
    time.sleep(0.1)

    interval = 0.2
    # Agent h3 stops after 3 packets
    agent = HealthAgent(node_id="h3", server_ip="127.0.0.1", server_port=port, interval=interval, fail_after=3)
    a_thread = threading.Thread(target=agent.run, daemon=True)
    a_thread.start()
    a_thread.join(timeout=2.0)

    # Wait for silence timeout (3 * 0.2 = 0.6s)
    time.sleep(interval * 3.0 + 0.8)
    node = server.registry.get_node("h3")
    assert node is not None
    assert node.status == "DOWN"

    # Restart agent h3
    agent_restart = HealthAgent(node_id="h3", server_ip="127.0.0.1", server_port=port, interval=interval, fail_after=2)
    ar_thread = threading.Thread(target=agent_restart.run, daemon=True)
    ar_thread.start()
    time.sleep(0.3)

    assert node.status == "UP"

    agent_restart.stop()
    ar_thread.join(timeout=0.5)
    server.stop()
    s_thread.join(timeout=0.5)


def test_i4_link_down_and_up_events():
    """I4: Link down/up on h1 -> DOWN then RECOVERED."""
    port = get_ephemeral_port()
    server = MonitorServer(host="127.0.0.1", port=port, dashboard_interval=0.0)
    s_thread = threading.Thread(target=server.run, daemon=True)
    s_thread.start()
    time.sleep(0.1)

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    msg = {
        "version": 1, "type": "HEALTH", "node_id": "h1", "seq": 1,
        "sent_ts": time.time(), "priority": "NORMAL",
        "metrics": {"cpu_percent": 10.0, "mem_percent": 20.0, "process_count": 50},
    }
    sock.sendto(encode(msg), ("127.0.0.1", port))
    time.sleep(0.1)
    node = server.registry.get_node("h1")
    assert node.status == "UP"

    # Simulate link failure (silence > 3*interval)
    # Default interval is 1.0s, so silence limit is 3.0s
    time.sleep(3.6)
    assert node.status == "DOWN"

    # Resume link
    msg["seq"] = 2
    msg["sent_ts"] = time.time()
    sock.sendto(encode(msg), ("127.0.0.1", port))
    time.sleep(0.2)
    assert node.status == "UP"

    sock.close()
    server.stop()
    s_thread.join(timeout=0.5)


def test_i5_congestion_priority_on_vs_off():
    """I5: Under bottleneck congestion, Priority ON yields lower critical loss and delay."""
    off_res = run_scenario(priority_enabled=False, duration=4.0, base_port=5600)
    on_res = run_scenario(priority_enabled=True, duration=4.0, base_port=5610)

    # Priority ON should have critical loss < 1%
    assert on_res["crit_loss_percent"] < 1.0
    # Priority ON should have lower or equal p95 delay for critical traffic
    assert on_res["crit_delay_p95_ms"] <= off_res["crit_delay_p95_ms"]


def test_i6_server_restart_recovery():
    """I6: Server restart -> agents continue sending and re-register without crash."""
    port = get_ephemeral_port()
    server1 = MonitorServer(host="127.0.0.1", port=port, dashboard_interval=0.0)
    s1_thread = threading.Thread(target=server1.run, daemon=True)
    s1_thread.start()
    time.sleep(0.1)

    agent = HealthAgent(node_id="h_reconnect", server_ip="127.0.0.1", server_port=port, interval=0.1)
    a_thread = threading.Thread(target=agent.run, daemon=True)
    a_thread.start()
    time.sleep(0.3)

    # Stop server 1 (simulate crash/restart)
    server1.stop()
    s1_thread.join(timeout=0.5)

    time.sleep(0.2)

    # Start server 2 on same port
    server2 = MonitorServer(host="127.0.0.1", port=port, dashboard_interval=0.0)
    s2_thread = threading.Thread(target=server2.run, daemon=True)
    s2_thread.start()

    time.sleep(0.4)

    node = server2.registry.get_node("h_reconnect")
    assert node is not None
    assert node.total_received >= 1

    agent.stop()
    a_thread.join(timeout=0.5)
    server2.stop()
    s2_thread.join(timeout=0.5)


def test_i7_20_agents_low_loss():
    """I7: 20 agents at 0.2s interval -> server loss < 5% on localhost."""
    port = get_ephemeral_port()
    server = MonitorServer(host="127.0.0.1", port=port, dashboard_interval=0.0)
    s_thread = threading.Thread(target=server.run, daemon=True)
    s_thread.start()
    time.sleep(0.1)

    agents = [
        HealthAgent(node_id=f"agent_scale_{i}", server_ip="127.0.0.1", server_port=port, interval=0.1, mode="simulated")
        for i in range(20)
    ]
    a_threads = [threading.Thread(target=ag.run, daemon=True) for ag in agents]
    for t in a_threads:
        t.start()

    time.sleep(1.0)

    for ag in agents:
        ag.stop()
    for t in a_threads:
        t.join(timeout=0.5)
    server.stop()
    s_thread.join(timeout=0.5)

    total_expected = sum(ag.seq for ag in agents)
    total_received = server.valid_packet_count
    loss_pct = ((total_expected - total_received) / total_expected) * 100.0 if total_expected > total_received else 0.0
    assert loss_pct < 5.0
