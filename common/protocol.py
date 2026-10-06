"""Message protocol implementation for UDP health monitoring."""

import json
from typing import Any, Dict, List, Optional

MAX_DATAGRAM_SIZE = 1400
SUPPORTED_VERSION = 1
VALID_TYPES = {"HEALTH", "HEARTBEAT", "ALERT"}
VALID_PRIORITIES = {"NORMAL", "CRITICAL"}


class ProtocolError(Exception):
    """Raised when encoding, decoding, or validating a message fails."""
    pass


def validate(msg: Dict[str, Any]) -> None:
    """Validates message structure, types, and metric ranges.

    Args:
        msg: Parsed message dictionary.

    Raises:
        ProtocolError: If any validation rule fails.
    """
    if not isinstance(msg, dict):
        raise ProtocolError(f"Message must be a dictionary, got {type(msg).__name__}")

    # Version check
    version = msg.get("version")
    if version != SUPPORTED_VERSION:
        raise ProtocolError(f"Unsupported protocol version: {version}. Expected: {SUPPORTED_VERSION}")

    # Type check
    msg_type = msg.get("type")
    if msg_type not in VALID_TYPES:
        raise ProtocolError(f"Invalid message type '{msg_type}'. Expected one of {sorted(VALID_TYPES)}")

    # Node ID check
    node_id = msg.get("node_id")
    if not isinstance(node_id, str) or not node_id.strip():
        raise ProtocolError(f"Invalid node_id: '{node_id}'. Must be a non-empty string.")

    # Sequence number check
    seq = msg.get("seq")
    if not isinstance(seq, int) or isinstance(seq, bool) or seq < 0:
        raise ProtocolError(f"Invalid sequence number: {seq}. Must be an integer >= 0.")

    # Timestamp check
    sent_ts = msg.get("sent_ts")
    if not isinstance(sent_ts, (int, float)) or isinstance(sent_ts, bool) or sent_ts <= 0:
        raise ProtocolError(f"Invalid sent_ts timestamp: {sent_ts}. Must be a positive float/int.")

    # Priority check
    priority = msg.get("priority")
    if priority not in VALID_PRIORITIES:
        raise ProtocolError(f"Invalid priority '{priority}'. Expected one of {sorted(VALID_PRIORITIES)}")

    # Metrics validation (required for HEALTH and ALERT, optional for HEARTBEAT)
    metrics = msg.get("metrics")
    if msg_type in {"HEALTH", "ALERT"}:
        if not isinstance(metrics, dict):
            raise ProtocolError(f"Message type '{msg_type}' requires a 'metrics' dict.")

    if metrics is not None:
        if not isinstance(metrics, dict):
            raise ProtocolError(f"'metrics' must be a dict, got {type(metrics).__name__}")

        # CPU percent check
        cpu = metrics.get("cpu_percent")
        if cpu is not None:
            if not isinstance(cpu, (int, float)) or isinstance(cpu, bool) or not (0.0 <= cpu <= 100.0):
                raise ProtocolError(f"Invalid cpu_percent: {cpu}. Must be between 0.0 and 100.0.")

        # Memory percent check
        mem = metrics.get("mem_percent")
        if mem is not None:
            if not isinstance(mem, (int, float)) or isinstance(mem, bool) or not (0.0 <= mem <= 100.0):
                raise ProtocolError(f"Invalid mem_percent: {mem}. Must be between 0.0 and 100.0.")

        # Process count check
        proc_count = metrics.get("process_count")
        if proc_count is not None:
            if not isinstance(proc_count, int) or isinstance(proc_count, bool) or proc_count < 0:
                raise ProtocolError(f"Invalid process_count: {proc_count}. Must be an integer >= 0.")

        # Top processes check
        top_procs = metrics.get("top_processes")
        if top_procs is not None and not isinstance(top_procs, list):
            raise ProtocolError(f"top_processes must be a list, got {type(top_procs).__name__}")

        # Network stats check
        net = metrics.get("net")
        if net is not None:
            if not isinstance(net, dict):
                raise ProtocolError(f"'net' metrics must be a dict, got {type(net).__name__}")
            for net_key in ["bytes_sent", "bytes_recv", "packets_sent", "packets_recv", "errors"]:
                if net_key in net:
                    val = net[net_key]
                    if not isinstance(val, int) or isinstance(val, bool) or val < 0:
                        raise ProtocolError(f"Invalid net stat '{net_key}': {val}. Must be an int >= 0.")


def encode(msg: Dict[str, Any], max_bytes: int = MAX_DATAGRAM_SIZE) -> bytes:
    """Validates and encodes a message dictionary to UTF-8 JSON bytes.

    Args:
        msg: Message dictionary.
        max_bytes: Maximum allowed payload size.

    Returns:
        bytes: Encoded payload.

    Raises:
        ProtocolError: If message is invalid or exceeds max_bytes.
    """
    validate(msg)
    try:
        raw = json.dumps(msg, separators=(",", ":")).encode("utf-8")
    except Exception as exc:
        raise ProtocolError(f"Failed to JSON-encode message: {exc}") from exc

    if len(raw) > max_bytes:
        raise ProtocolError(
            f"Encoded payload size ({len(raw)} bytes) exceeds maximum datagram size ({max_bytes} bytes)"
        )
    return raw


def decode(data: bytes, max_bytes: int = MAX_DATAGRAM_SIZE) -> Dict[str, Any]:
    """Decodes raw UDP datagram bytes to a validated message dictionary.

    Args:
        data: Raw payload bytes received from UDP socket.
        max_bytes: Maximum acceptable payload size.

    Returns:
        Dict[str, Any]: Validated message dict.

    Raises:
        ProtocolError: On empty payload, JSON decode failure, or validation failure.
    """
    if not data:
        raise ProtocolError("Received empty or zero-length payload")

    if len(data) > max_bytes:
        raise ProtocolError(f"Received payload size ({len(data)} bytes) exceeds maximum limit ({max_bytes} bytes)")

    try:
        text = data.decode("utf-8")
        msg = json.loads(text)
    except UnicodeDecodeError as exc:
        raise ProtocolError(f"UTF-8 decoding error: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise ProtocolError(f"Invalid JSON payload: {exc}") from exc
    except Exception as exc:
        raise ProtocolError(f"Malformed payload: {exc}") from exc

    validate(msg)
    return msg
