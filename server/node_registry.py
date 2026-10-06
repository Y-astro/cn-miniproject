"""Node registry tracking node state, packet sequences, loss, and liveness."""

import time
from typing import Any, Callable, Dict, List, Optional, Set, Tuple


class NodeState:
    """Maintains statistical and lifecycle state for a single node."""

    def __init__(self, node_id: str, initial_interval: float = 1.0, initial_ts: float = 0.0):
        self.node_id = node_id
        self.status = "UP"  # "UP" or "DOWN"
        self.interval = initial_interval
        self.last_seen_ts = initial_ts
        self.last_seq: Optional[int] = None
        self.total_received = 0
        self.lost_packets = 0
        self.duplicates = 0
        self.out_of_order = 0
        self.restarts = 0
        self.seen_seqs: Set[int] = set()
        self.last_metrics: Dict[str, Any] = {}
        self.last_delay_ms: float = 0.0
        self.delays: List[float] = []

    @property
    def loss_percent(self) -> float:
        total = self.total_received + self.lost_packets
        if total == 0:
            return 0.0
        return round((self.lost_packets / total) * 100.0, 2)

    @property
    def avg_delay_ms(self) -> float:
        if not self.delays:
            return 0.0
        return round(sum(self.delays) / len(self.delays), 2)


class NodeRegistry:
    """Tracks all registered nodes, detects packet loss, and monitors liveness."""

    def __init__(
        self,
        default_interval: float = 1.0,
        silence_multiplier: float = 3.0,
        event_callback: Optional[Callable[[str, str, Dict[str, Any]], None]] = None,
    ):
        self.default_interval = default_interval
        self.silence_multiplier = silence_multiplier
        self.event_callback = event_callback
        self.nodes: Dict[str, NodeState] = {}

    def get_node(self, node_id: str) -> Optional[NodeState]:
        return self.nodes.get(node_id)

    def process_packet(
        self,
        node_id: str,
        seq: int,
        sent_ts: float,
        recv_ts: Optional[float] = None,
        metrics: Optional[Dict[str, Any]] = None,
        interval: Optional[float] = None,
    ) -> List[Tuple[str, str]]:
        """Processes an incoming packet and updates node state.

        Returns:
            List of generated events [(event_name, node_id), ...]
        """
        now = recv_ts if recv_ts is not None else time.time()
        events: List[Tuple[str, str]] = []

        is_new_node = node_id not in self.nodes
        if is_new_node:
            node = NodeState(node_id, initial_interval=interval or self.default_interval, initial_ts=now)
            self.nodes[node_id] = node
            events.append(("NODE_REGISTERED", node_id))
        else:
            node = self.nodes[node_id]

        if interval is not None and interval > 0:
            node.interval = interval
        elif node.last_seen_ts > 0:
            delta = now - node.last_seen_ts
            if 0.01 <= delta <= 60.0:
                node.interval = delta

        # Check recovery if node was DOWN
        if node.status == "DOWN":
            node.status = "UP"
            events.append(("NODE_RECOVERED", node_id))

        node.last_seen_ts = now
        node.total_received += 1

        if metrics:
            node.last_metrics = metrics

        # Compute delay
        delay_ms = max(0.0, (now - sent_ts) * 1000.0)
        node.last_delay_ms = delay_ms
        node.delays.append(delay_ms)
        if len(node.delays) > 500:
            node.delays.pop(0)

        # Sequence number and loss tracking
        if node.last_seq is None:
            # First sequence packet
            node.last_seq = seq
            node.seen_seqs.add(seq)
        else:
            if seq == node.last_seq or seq in node.seen_seqs:
                # Duplicate packet (R5)
                node.duplicates += 1
            elif seq < node.last_seq:
                # Agent restart detection: seq dropped to 0 or 1, or dropped significantly (R7)
                if seq <= 1 or (node.last_seq - seq > 50):
                    node.restarts += 1
                    node.last_seq = seq
                    node.seen_seqs.clear()
                    node.seen_seqs.add(seq)
                    events.append(("NODE_RESTARTED", node_id))
                else:
                    # Out of order packet (R6)
                    node.out_of_order += 1
                    node.seen_seqs.add(seq)
            else:
                # Normal forward sequence (R4)
                gap = seq - node.last_seq - 1
                if gap > 0:
                    node.lost_packets += gap
                node.last_seq = seq
                node.seen_seqs.add(seq)

        # Fire callbacks
        if self.event_callback:
            for ev, nid in events:
                self.event_callback(ev, nid, {"status": node.status, "seq": seq})

        return events

    def check_liveness(self, current_ts: Optional[float] = None) -> List[Tuple[str, str]]:
        """Checks nodes for silence timeouts.

        Returns:
            List of generated events, e.g. [('NODE_DOWN', 'h1')]
        """
        now = current_ts if current_ts is not None else time.time()
        events: List[Tuple[str, str]] = []

        for node_id, node in self.nodes.items():
            if node.status == "UP":
                silence_limit = self.silence_multiplier * node.interval
                silence_duration = now - node.last_seen_ts
                if silence_duration > silence_limit:
                    node.status = "DOWN"
                    events.append(("NODE_DOWN", node_id))
                    if self.event_callback:
                        self.event_callback("NODE_DOWN", node_id, {
                            "silence_sec": round(silence_duration, 2),
                            "limit_sec": round(silence_limit, 2),
                        })

        return events
