"""Additional unit tests to maximize test coverage across core modules."""

import time
import pytest
from common.protocol import validate, encode, ProtocolError
from common.config_loader import validate_config, ConfigError
from server.monitor_server import MonitorServer, parse_args as parse_server_args
from agent.health_agent import parse_args as parse_agent_args
from server.alert_engine import AlertEngine


def test_protocol_additional_branches():
    """Test top_processes and net stats validation branches."""
    base = {
        "version": 1, "type": "HEALTH", "node_id": "h1",
        "seq": 1, "sent_ts": 100.0, "priority": "NORMAL",
        "metrics": {"cpu_percent": 10.0, "top_processes": "not_a_list"},
    }
    with pytest.raises(ProtocolError, match="top_processes must be a list"):
        validate(base)

    base["metrics"]["top_processes"] = []
    base["metrics"]["net"] = "not_a_dict"
    with pytest.raises(ProtocolError, match="'net' metrics must be a dict"):
        validate(base)

    base["metrics"]["net"] = {"bytes_sent": -5}
    with pytest.raises(ProtocolError, match="Invalid net stat"):
        validate(base)

    base["metrics"]["net"] = {"bytes_sent": "string"}
    with pytest.raises(ProtocolError, match="Invalid net stat"):
        validate(base)


def test_config_loader_additional_branches():
    """Test server section, timeout_multiplier, and silence_multiplier validation."""
    with pytest.raises(ConfigError, match="Missing or invalid 'server'"):
        validate_config({"server": "invalid"})

    with pytest.raises(ConfigError, match="Invalid failure_timeout_multiplier"):
        validate_config({"server": {"port": 5005, "failure_timeout_multiplier": -1.0}})

    with pytest.raises(ConfigError, match="Invalid 'agent'"):
        validate_config({"server": {"port": 5005}, "agent": "invalid"})

    with pytest.raises(ConfigError, match="Missing or invalid 'thresholds'"):
        validate_config({"server": {"port": 5005}, "agent": {}, "thresholds": "invalid"})

    with pytest.raises(ConfigError, match="Invalid silence_multiplier"):
        validate_config({
            "server": {"port": 5005},
            "agent": {},
            "thresholds": {
                "cpu_percent": {"warning": 70, "critical": 90},
                "mem_percent": {"warning": 75, "critical": 90},
                "process_count": {"warning": 300, "critical": 500},
                "packet_loss_percent": {"warning": 5, "critical": 20},
                "silence_multiplier": -1.0,
            },
        })


def test_monitor_server_dashboard(tmp_path, capsys):
    """Test console dashboard rendering in MonitorServer."""
    server = MonitorServer(
        host="127.0.0.1",
        port=0,
        config_path="config.yaml",
        csv_file=str(tmp_path / "dash.csv"),
    )
    # With no nodes
    server.display_dashboard()

    # With a registered node
    server.registry.process_packet(
        node_id="h_dash",
        seq=1,
        sent_ts=100.0,
        recv_ts=100.01,
        metrics={"cpu_percent": 35.0, "mem_percent": 40.0, "process_count": 150},
    )
    server.display_dashboard()
    captured = capsys.readouterr()
    assert "HEALTH MONITOR DASHBOARD" in captured.out
    assert "h_dash" in captured.out


def test_parse_args_coverage(monkeypatch):
    """Test parse_args helper functions."""
    monkeypatch.setattr("sys.argv", ["monitor_server.py", "--port", "6000"])
    args = parse_server_args()
    assert args.port == 6000

    monkeypatch.setattr("sys.argv", ["health_agent.py", "--id", "h_test", "--interval", "2.0"])
    args_agent = parse_agent_args()
    assert args_agent.node_id == "h_test"
    assert args_agent.interval == 2.0


def test_web_dashboard_endpoints(tmp_path):
    """Test web dashboard HTML and D2 priority toggle REST endpoints."""
    import urllib.request
    import json
    import socket
    import time
    from server.web_dashboard import run_web_dashboard

    server = MonitorServer(
        host="127.0.0.1",
        port=0,
        config_path="config.yaml",
        csv_file=str(tmp_path / "web_rep.csv"),
    )
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]

    httpd = run_web_dashboard(server, http_port=port)
    assert httpd is not None
    time.sleep(0.2)

    try:
        # 1. Fetch HTML index
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/") as res:
            html = res.read().decode("utf-8")
            assert "SDN Priority: ON (D2)" in html
            assert "Deliverable 2: OpenFlow 1.3 QoS" in html

        # 2. Fetch /api/status
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/status") as res:
            data = json.loads(res.read().decode("utf-8"))
            assert data["priority_enabled"] is True
            assert data["dynamic_throttling_active"] is False

        # 3. Toggle priority via /api/toggle_priority
        req = urllib.request.Request(f"http://127.0.0.1:{port}/api/toggle_priority", method="POST")
        with urllib.request.urlopen(req) as res:
            data = json.loads(res.read().decode("utf-8"))
            assert data["priority_enabled"] is False
            assert server.priority_enabled is False

        # 4. Toggle throttle via /api/toggle_throttle
        req = urllib.request.Request(f"http://127.0.0.1:{port}/api/toggle_throttle", method="POST")
        with urllib.request.urlopen(req) as res:
            data = json.loads(res.read().decode("utf-8"))
            assert data["dynamic_throttling_active"] is True
            assert server.dynamic_throttling_active is True
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_priority_toggle_loss_emulation_and_reset(tmp_path):
    """Verify that toggling priority_enabled off emulates congested FIFO loss and reset_loss_stats clears state."""
    from common.protocol import encode

    server = MonitorServer(
        host="127.0.0.1",
        port=0,
        config_path="config.yaml",
        csv_file=str(tmp_path / "rep.csv"),
    )
    # 1. Under priority ON, 10 packets are processed with 0 drops
    server.priority_enabled = True
    for seq in range(1, 11):
        payload = {
            "version": 1,
            "type": "HEALTH",
            "node_id": "h_test",
            "seq": seq,
            "sent_ts": time.time(),
            "interval": 1.0,
            "priority": "NORMAL",
            "metrics": {"cpu_percent": 10.0, "mem_percent": 20.0, "process_count": 50},
        }
        res = server.process_datagram(encode(payload), ("127.0.0.1", 5005), time.time())
        assert res is not None

    node = server.registry.get_node("h_test")
    assert node is not None
    assert node.total_received == 10
    assert node.lost_packets == 0
    assert node.loss_percent == 0.0

    # 2. Toggle priority OFF -> emulates bottleneck drop
    server.priority_enabled = False
    server.registry.reset_loss_stats()
    assert node.total_received == 0
    assert node.lost_packets == 0

    dropped = 0
    received = 0
    for seq in range(1, 101):
        payload = {
            "version": 1,
            "type": "HEALTH",
            "node_id": "h_test",
            "seq": seq,
            "sent_ts": time.time(),
            "interval": 1.0,
            "priority": "NORMAL",
            "metrics": {"cpu_percent": 10.0, "mem_percent": 20.0, "process_count": 50},
        }
        res = server.process_datagram(encode(payload), ("127.0.0.1", 5005), time.time())
        if res is None:
            dropped += 1
        else:
            received += 1

    # Over 100 packets with ~56.7% drop probability, dropped packets should be > 20 and received > 20
    assert dropped > 20
    assert received > 20
    assert node.lost_packets > 10
    assert node.loss_percent > 20.0

    # 3. Toggle back ON and reset stats
    server.priority_enabled = True
    server.registry.reset_loss_stats()
    assert node.loss_percent == 0.0
    assert node.lost_packets == 0
