"""Unit tests for Server UDP communication on localhost (U1 - U5)."""

import os
import socket
import threading
import time
import pytest
from common.protocol import encode
from server.monitor_server import MonitorServer


@pytest.fixture
def test_server(tmp_path):
    csv_file = str(tmp_path / "reports.csv")
    alerts_file = str(tmp_path / "alerts.csv")
    # Bind to an ephemeral port
    temp_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    temp_sock.bind(("127.0.0.1", 0))
    port = temp_sock.getsockname()[1]
    temp_sock.close()

    server = MonitorServer(
        host="127.0.0.1",
        port=port,
        config_path="config.yaml",
        csv_file=csv_file,
        alerts_csv_file=alerts_file,
        dashboard_interval=0.0,
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    time.sleep(0.1)  # Allow socket to bind

    yield server, port

    server.stop()
    thread.join(timeout=1.0)


def test_u1_valid_packet_updates_registry(test_server):
    """U1: Valid packet -> server logs it and updates registry."""
    server, port = test_server
    client = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    msg = {
        "version": 1,
        "type": "HEALTH",
        "node_id": "h_test1",
        "seq": 1,
        "sent_ts": time.time(),
        "priority": "NORMAL",
        "metrics": {"cpu_percent": 45.0, "mem_percent": 50.0, "process_count": 120},
    }
    client.sendto(encode(msg), ("127.0.0.1", port))
    client.close()

    # Wait briefly for processing
    time.sleep(0.2)
    node = server.registry.get_node("h_test1")
    assert node is not None
    assert node.total_received >= 1
    assert node.status == "UP"


def test_u2_burst_of_malformed_packets_server_survives(test_server):
    """U2: 1000 malformed packets in a burst -> server still alive and answers valid packet."""
    server, port = test_server
    client = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    garbage_payloads = [
        b"\x00\xff\xfe\xaaGarbage",
        b"{malformed json",
        b'{"version": 999}',
        b"",
        b"A" * 1500,
    ]

    for i in range(1000):
        client.sendto(garbage_payloads[i % len(garbage_payloads)], ("127.0.0.1", port))

    time.sleep(0.2)
    assert server.bad_packet_count > 0

    # Server should still be alive and accept a valid packet
    valid_msg = {
        "version": 1,
        "type": "HEALTH",
        "node_id": "h_after_burst",
        "seq": 1,
        "sent_ts": time.time(),
        "priority": "NORMAL",
        "metrics": {"cpu_percent": 15.0, "mem_percent": 25.0, "process_count": 80},
    }
    client.sendto(encode(valid_msg), ("127.0.0.1", port))
    client.close()

    time.sleep(0.2)
    node = server.registry.get_node("h_after_burst")
    assert node is not None
    assert node.total_received >= 1


def test_u3_concurrent_senders_load(test_server):
    """U3: 20 concurrent sender threads x 50 packets -> valid packets counted."""
    server, port = test_server
    num_senders = 20
    packets_per_sender = 50

    def sender_worker(sender_id: int):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        node_id = f"worker_{sender_id}"
        for s in range(1, packets_per_sender + 1):
            msg = {
                "version": 1,
                "type": "HEALTH",
                "node_id": node_id,
                "seq": s,
                "sent_ts": time.time(),
                "priority": "NORMAL",
                "metrics": {"cpu_percent": 20.0, "mem_percent": 30.0, "process_count": 90},
            }
            sock.sendto(encode(msg), ("127.0.0.1", port))
            time.sleep(0.001)
        sock.close()

    threads = [threading.Thread(target=sender_worker, args=(i,)) for i in range(num_senders)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=5.0)

    time.sleep(0.5)
    total_expected = num_senders * packets_per_sender
    total_received = server.valid_packet_count
    loss_rate = ((total_expected - total_received) / total_expected) * 100.0
    print(f"\nU3 Load Test: Sent={total_expected}, Received={total_received}, Loss={loss_rate:.2f}%")
    # On loopback UDP, receive rate is usually > 95%
    assert total_received >= total_expected * 0.80


def test_u4_port_already_in_use():
    """U4: Port already in use raises OSError cleanly."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]

    server = MonitorServer(host="127.0.0.1", port=port, config_path="config.yaml")
    with pytest.raises(OSError):
        server.start_socket()

    sock.close()


def test_u5_shutdown_signal_closes_socket_and_flushes_csv(tmp_path):
    """U5: Shutdown closes socket and flushes CSV."""
    csv_file = str(tmp_path / "u5_reports.csv")
    alerts_file = str(tmp_path / "u5_alerts.csv")
    temp_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    temp_sock.bind(("127.0.0.1", 0))
    port = temp_sock.getsockname()[1]
    temp_sock.close()

    server = MonitorServer(
        host="127.0.0.1",
        port=port,
        config_path="config.yaml",
        csv_file=csv_file,
        alerts_csv_file=alerts_file,
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    time.sleep(0.1)

    # Send one packet
    client = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    msg = {
        "version": 1,
        "type": "HEALTH",
        "node_id": "h_u5",
        "seq": 1,
        "sent_ts": time.time(),
        "priority": "NORMAL",
        "metrics": {"cpu_percent": 10.0, "mem_percent": 20.0, "process_count": 50},
    }
    client.sendto(encode(msg), ("127.0.0.1", port))
    client.close()
    time.sleep(0.2)

    server.stop()
    thread.join(timeout=1.0)

    assert server.sock is None
    # Check that CSV has header + report
    with open(csv_file, "r", encoding="utf-8") as f:
        lines = f.readlines()
        assert len(lines) >= 2  # Header + at least 1 record
