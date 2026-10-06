"""Unit tests for UDP message protocol (P1 - P10)."""

import pytest
import time
from common.protocol import encode, decode, validate, ProtocolError, MAX_DATAGRAM_SIZE


def make_valid_message():
    return {
        "version": 1,
        "type": "HEALTH",
        "node_id": "h1",
        "seq": 1042,
        "sent_ts": time.time(),
        "priority": "NORMAL",
        "metrics": {
            "cpu_percent": 73.2,
            "mem_percent": 61.5,
            "process_count": 182,
            "top_processes": [{"name": "python", "cpu": 12.1}],
            "net": {
                "bytes_sent": 123456,
                "bytes_recv": 654321,
                "packets_sent": 900,
                "packets_recv": 1100,
                "errors": 0,
            },
        },
    }


def test_p1_encode_decode_round_trip():
    """P1: Encode -> decode a valid message results in round-trip equality."""
    msg = make_valid_message()
    encoded = encode(msg)
    assert isinstance(encoded, bytes)
    assert len(encoded) <= MAX_DATAGRAM_SIZE
    decoded = decode(encoded)
    assert decoded == msg


def test_p2_missing_node_id():
    """P2: Missing node_id raises ProtocolError."""
    msg = make_valid_message()
    del msg["node_id"]
    with pytest.raises(ProtocolError, match="Invalid node_id"):
        encode(msg)


def test_p3_invalid_cpu_percent():
    """P3: cpu_percent = 150 or -5 raises ProtocolError."""
    msg = make_valid_message()
    msg["metrics"]["cpu_percent"] = 150.0
    with pytest.raises(ProtocolError, match="Invalid cpu_percent"):
        encode(msg)

    msg["metrics"]["cpu_percent"] = -5.0
    with pytest.raises(ProtocolError, match="Invalid cpu_percent"):
        encode(msg)


def test_p4_mem_percent_string():
    """P4: mem_percent is a string raises ProtocolError."""
    msg = make_valid_message()
    msg["metrics"]["mem_percent"] = "61.5%"
    with pytest.raises(ProtocolError, match="Invalid mem_percent"):
        encode(msg)


def test_p5_invalid_json_bytes():
    """P5: Invalid JSON bytes raises ProtocolError without crashing."""
    garbage = b"\xff\x00garbage"
    with pytest.raises(ProtocolError):
        decode(garbage)


def test_p6_empty_payload():
    """P6: Empty payload raises ProtocolError."""
    with pytest.raises(ProtocolError, match="empty or zero-length"):
        decode(b"")


def test_p7_unknown_type_and_priority():
    """P7: Unknown type or priority raises ProtocolError."""
    msg = make_valid_message()
    msg["type"] = "UNKNOWN_TYPE"
    with pytest.raises(ProtocolError, match="Invalid message type"):
        encode(msg)

    msg = make_valid_message()
    msg["priority"] = "URGENT"
    with pytest.raises(ProtocolError, match="Invalid priority"):
        encode(msg)


def test_p8_unsupported_version():
    """P8: Unsupported version raises ProtocolError."""
    msg = make_valid_message()
    msg["version"] = 2
    with pytest.raises(ProtocolError, match="Unsupported protocol version"):
        encode(msg)


def test_p9_payload_exceeds_1400_bytes():
    """P9: Payload > 1400 bytes raises ProtocolError."""
    msg = make_valid_message()
    # Inflate payload with a very large top_processes list
    msg["metrics"]["top_processes"] = [
        {"name": f"process_with_very_long_name_{i}", "cpu": 1.0, "extra": "x" * 100}
        for i in range(50)
    ]
    with pytest.raises(ProtocolError, match="exceeds maximum datagram size"):
        encode(msg)


def test_p10_negative_seq_and_process_count():
    """P10: Negative seq, process_count raises ProtocolError."""
    msg = make_valid_message()
    msg["seq"] = -1
    with pytest.raises(ProtocolError, match="Invalid sequence number"):
        encode(msg)

    msg = make_valid_message()
    msg["metrics"]["process_count"] = -10
    with pytest.raises(ProtocolError, match="Invalid process_count"):
        encode(msg)
