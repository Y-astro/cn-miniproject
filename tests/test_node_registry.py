"""Unit tests for node registry (R1 - R7)."""

import pytest
from server.node_registry import NodeRegistry


def test_r1_new_node_registered_as_up():
    """R1: New node is registered as UP."""
    registry = NodeRegistry(default_interval=1.0)
    events = registry.process_packet(node_id="h1", seq=1, sent_ts=100.0, recv_ts=100.01)

    node = registry.get_node("h1")
    assert node is not None
    assert node.status == "UP"
    assert ("NODE_REGISTERED", "h1") in events


def test_r2_node_silence_timeout_down():
    """R2: No packets for > 3 * interval marks node DOWN using fake clock."""
    registry = NodeRegistry(default_interval=1.0, silence_multiplier=3.0)
    registry.process_packet(node_id="h1", seq=1, sent_ts=100.0, recv_ts=100.0)

    # At t = 102.0 (2s elapsed <= 3.0s limit): still UP
    down_events = registry.check_liveness(current_ts=102.0)
    assert not down_events
    assert registry.get_node("h1").status == "UP"

    # At t = 103.5 (3.5s elapsed > 3.0s limit): DOWN
    down_events = registry.check_liveness(current_ts=103.5)
    assert ("NODE_DOWN", "h1") in down_events
    assert registry.get_node("h1").status == "DOWN"


def test_r3_packets_resume_triggers_recovered():
    """R3: Packets resume after silence -> NODE_RECOVERED event and status is UP."""
    registry = NodeRegistry(default_interval=1.0, silence_multiplier=3.0)
    registry.process_packet(node_id="h1", seq=1, sent_ts=100.0, recv_ts=100.0)

    # Force DOWN
    registry.check_liveness(current_ts=105.0)
    assert registry.get_node("h1").status == "DOWN"

    # Resume packets
    events = registry.process_packet(node_id="h1", seq=2, sent_ts=106.0, recv_ts=106.01)
    assert ("NODE_RECOVERED", "h1") in events
    assert registry.get_node("h1").status == "UP"


def test_r4_sequence_gap_counts_loss():
    """R4: Sequence 1, 2, 4 -> 1 lost packet counted."""
    registry = NodeRegistry()
    registry.process_packet(node_id="h1", seq=1, sent_ts=1.0, recv_ts=1.01)
    registry.process_packet(node_id="h1", seq=2, sent_ts=2.0, recv_ts=2.01)
    registry.process_packet(node_id="h1", seq=4, sent_ts=3.0, recv_ts=3.01)

    node = registry.get_node("h1")
    assert node.lost_packets == 1
    assert node.total_received == 3


def test_r5_duplicate_sequence_counted():
    """R5: Duplicate seq -> ignored from loss and counted as duplicate."""
    registry = NodeRegistry()
    registry.process_packet(node_id="h1", seq=1, sent_ts=1.0, recv_ts=1.01)
    registry.process_packet(node_id="h1", seq=2, sent_ts=2.0, recv_ts=2.01)
    registry.process_packet(node_id="h1", seq=2, sent_ts=2.5, recv_ts=2.51)  # duplicate

    node = registry.get_node("h1")
    assert node.duplicates == 1
    assert node.lost_packets == 0
    assert node.total_received == 3


def test_r6_out_of_order_sequence_no_negative_loss():
    """R6: Out-of-order seq -> counted, no negative loss."""
    registry = NodeRegistry()
    registry.process_packet(node_id="h1", seq=1, sent_ts=1.0, recv_ts=1.01)
    registry.process_packet(node_id="h1", seq=5, sent_ts=2.0, recv_ts=2.01)  # gaps 2,3,4 = 3 lost
    node = registry.get_node("h1")
    assert node.lost_packets == 3

    # Out-of-order packet 3 arrives
    registry.process_packet(node_id="h1", seq=3, sent_ts=2.5, recv_ts=2.51)
    assert node.out_of_order == 1
    assert node.lost_packets == 3  # Does not become negative or corrupt state


def test_r7_sequence_reset_restart_handling():
    """R7: Seq drops back to 0/1 (agent restart) -> treated as restart, not huge loss."""
    registry = NodeRegistry()
    registry.process_packet(node_id="h1", seq=500, sent_ts=10.0, recv_ts=10.01)
    node = registry.get_node("h1")
    assert node.lost_packets == 0

    # Agent restarts and sends seq=0
    events = registry.process_packet(node_id="h1", seq=0, sent_ts=20.0, recv_ts=20.01)
    assert ("NODE_RESTARTED", "h1") in events
    assert node.restarts == 1
    assert node.lost_packets == 0  # Not counted as 4 billion packets lost!
