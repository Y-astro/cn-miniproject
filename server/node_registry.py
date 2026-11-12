"""Node registry tracking node state, packet sequences, loss, and liveness."""

# Import time module for current timestamps and delay calculations
import time
# Import typing annotations for type safety and callback signatures
from typing import Any, Callable, Dict, List, Optional, Set, Tuple


# Class representing the lifecycle, metric, and sequence accounting state of an individual node
class NodeState:
    """Maintains statistical and lifecycle state for a single node."""

    # Constructor initializing per-node counters, tracking sets, and historical buffers
    def __init__(self, node_id: str, initial_interval: float = 1.0, initial_ts: float = 0.0):
        # Store unique node identifier (e.g. 'h1_prod')
        self.node_id = node_id
        # Current lifecycle status: 'UP' (active) or 'DOWN' (timed out)
        self.status = "UP"
        # Expected heartbeat/reporting cadence in seconds
        self.interval = initial_interval
        # Timestamp when the most recent packet from this node was received
        self.last_seen_ts = initial_ts
        # Last received sequence number counter (None before first packet)
        self.last_seq: Optional[int] = None
        # Cumulative count of valid packets successfully received from this node
        self.total_received = 0
        # Cumulative count of detected lost UDP packets calculated from sequence gaps
        self.lost_packets = 0
        # Cumulative count of duplicate packets received
        self.duplicates = 0
        # Cumulative count of packets arriving out of expected sequence order
        self.out_of_order = 0
        # Counter tracking node restart/reboot events (e.g., sequence resetting to 0/1)
        self.restarts = 0
        # Set of recently observed sequence numbers for duplicate packet detection
        self.seen_seqs: Set[int] = set()
        # Dictionary caching the most recent system metrics payload
        self.last_metrics: Dict[str, Any] = {}
        # Instantaneous one-way network delay in milliseconds of the latest packet
        self.last_delay_ms: float = 0.0
        # Rolling historical list of delay measurements for moving average calculation
        self.delays: List[float] = []

    # Computed property calculating the percentage of lost UDP packets
    @property
    def loss_percent(self) -> float:
        # Calculate expected total packets (received + lost)
        total = self.total_received + self.lost_packets
        # If no packets expected yet, return 0.0% loss
        if total == 0:
            # Return baseline 0.0
            return 0.0
        # Calculate loss ratio, scale to percentage, and round to 2 decimal places
        return round((self.lost_packets / total) * 100.0, 2)

    # Computed property calculating rolling average latency in milliseconds
    @property
    def avg_delay_ms(self) -> float:
        # Check if any delay measurements have been recorded
        if not self.delays:
            # Return 0.0 if buffer is empty
            return 0.0
        # Compute arithmetic mean of recorded delay measurements
        return round(sum(self.delays) / len(self.delays), 2)


# Class managing the collection of all monitored nodes, liveness checks, and state updates
class NodeRegistry:
    """Tracks all registered nodes, detects packet loss, and monitors liveness."""

    # Constructor initializing default timeouts and optional event listeners
    def __init__(
        self,
        default_interval: float = 1.0,
        silence_multiplier: float = 3.0,
        event_callback: Optional[Callable[[str, str, Dict[str, Any]], None]] = None,
    ):
        # Default report interval in seconds when node does not specify one
        self.default_interval = default_interval
        # Multiplier of interval defining silence limit before declaring node DOWN (3x = 3.0s)
        self.silence_multiplier = silence_multiplier
        # Optional callback invoked whenever lifecycle events occur (e.g., NODE_DOWN, NODE_RECOVERED)
        self.event_callback = event_callback
        # In-memory dictionary storing node states indexed by node_id: {node_id: NodeState}
        self.nodes: Dict[str, NodeState] = {}

    # Method to retrieve state object for a given node_id, or None if not found
    def get_node(self, node_id: str) -> Optional[NodeState]:
        # Return node state from dictionary
        return self.nodes.get(node_id)

    # Method to reset loss and delay statistics across all registered nodes (e.g. on QoS mode switch)
    def reset_loss_stats(self) -> None:
        """Resets sequence tracking, loss, and latency metrics across all nodes."""
        # Iterate over all registered NodeState instances
        for node in self.nodes.values():
            # Reset received packet count
            node.total_received = 0
            # Reset lost packet count
            node.lost_packets = 0
            # Reset duplicate packet counter
            node.duplicates = 0
            # Reset out-of-order packet counter
            node.out_of_order = 0
            # Clear historical delay samples
            node.delays.clear()
            # Clear last sequence baseline so next packet establishes fresh baseline
            node.last_seq = None
            # Clear seen sequences set
            node.seen_seqs.clear()

    # Main packet ingestion method: updates sequence stats, computes latency, and tracks lifecycle
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
        # Determine current reception timestamp (use provided timestamp or sample system clock)
        now = recv_ts if recv_ts is not None else time.time()
        # List of lifecycle events generated during this packet processing
        events: List[Tuple[str, str]] = []

        # Check if this is the first time we have ever heard from this node
        is_new_node = node_id not in self.nodes
        # If new node, instantiate its NodeState record
        if is_new_node:
            # Create fresh NodeState instance
            node = NodeState(node_id, initial_interval=interval or self.default_interval, initial_ts=now)
            # Register new node in dictionary
            self.nodes[node_id] = node
            # Record NODE_REGISTERED lifecycle event
            events.append(("NODE_REGISTERED", node_id))
        # Otherwise fetch existing state record
        else:
            # Retrieve registered NodeState instance
            node = self.nodes[node_id]

        # Update expected interval if explicitly provided by sender in payload
        if interval is not None and interval > 0:
            # Set interval from packet field
            node.interval = interval
        # Alternatively infer interval from arrival time delta if previously seen
        elif node.last_seen_ts > 0:
            # Calculate elapsed time between successive arrivals
            delta = now - node.last_seen_ts
            # If delta is within plausible bounds (10ms to 60s), adapt interval
            if 0.01 <= delta <= 60.0:
                # Update node interval dynamically
                node.interval = delta

        # Check if node was previously marked DOWN and has now recovered
        if node.status == "DOWN":
            # Transition status back to UP
            node.status = "UP"
            # Record NODE_RECOVERED event
            events.append(("NODE_RECOVERED", node_id))

        # Update timestamp of last seen packet
        node.last_seen_ts = now
        # Increment total successfully received packet counter
        node.total_received += 1

        # Cache metrics dictionary if provided
        if metrics:
            # Update latest metrics snapshot
            node.last_metrics = metrics

        # Compute one-way network delay in milliseconds (elapsed time from agent send to server receive)
        delay_ms = max(0.0, (now - sent_ts) * 1000.0)
        # Store instantaneous delay
        node.last_delay_ms = delay_ms
        # Append delay sample to rolling buffer
        node.delays.append(delay_ms)
        # Maintain sliding window bounded to 500 samples to prevent memory leaks
        if len(node.delays) > 500:
            # Remove oldest delay measurement
            node.delays.pop(0)

        # Sequence number analysis for packet loss, reordering, and restart tracking
        if node.last_seq is None:
            # First packet received from this node: establish sequence baseline
            node.last_seq = seq
            # Add sequence number to seen set
            node.seen_seqs.add(seq)
        # For subsequent packets, compare against previous sequence number
        else:
            # Check if this exact sequence number was already seen or matches last seq
            if seq == node.last_seq or seq in node.seen_seqs:
                # Increment duplicate packet counter
                node.duplicates += 1
            # Check if sequence number is smaller than previous (backward jump)
            elif seq < node.last_seq:
                # Detect agent restart: sequence reset to 0 or 1, or dropped by more than 50
                if seq <= 1 or (node.last_seq - seq > 50):
                    # Increment agent restart counter
                    node.restarts += 1
                    # Reset last sequence to new counter
                    node.last_seq = seq
                    # Clear sequence history cache
                    node.seen_seqs.clear()
                    # Add current sequence number
                    node.seen_seqs.add(seq)
                    # Record NODE_RESTARTED event
                    events.append(("NODE_RESTARTED", node_id))
                # Otherwise packet simply arrived out of order due to network jitter
                else:
                    # Increment out-of-order counter
                    node.out_of_order += 1
                    # Record sequence number in seen set
                    node.seen_seqs.add(seq)
            # Normal forward progression: sequence number strictly increased
            else:
                # Calculate gap between current sequence and previous sequence
                gap = seq - node.last_seq - 1
                # If gap > 0, missing packets were dropped in the network
                if gap > 0:
                    # Accumulate lost packet count
                    node.lost_packets += gap
                # Advance last observed sequence number
                node.last_seq = seq
                # Record sequence number in seen set
                node.seen_seqs.add(seq)

        # Trigger event callbacks if listener was provided
        if self.event_callback:
            # Iterate through all generated events
            for ev, nid in events:
                # Invoke registered callback with event name, node id, and metadata
                self.event_callback(ev, nid, {"status": node.status, "seq": seq})

        # Return list of all events generated by processing this packet
        return events

    # Method to scan registered nodes and flag any that have timed out (silence detection)
    def check_liveness(self, current_ts: Optional[float] = None) -> List[Tuple[str, str]]:
        """Checks nodes for silence timeouts.

        Returns:
            List of generated events, e.g. [('NODE_DOWN', 'h1')]
        """
        # Obtain current timestamp (use argument or system clock)
        now = current_ts if current_ts is not None else time.time()
        # Initialize list to hold timeout events
        events: List[Tuple[str, str]] = []

        # Iterate through all tracked nodes
        for node_id, node in self.nodes.items():
            # Check only currently active nodes
            if node.status == "UP":
                # Compute maximum allowed silence duration before declaring node dead
                silence_limit = self.silence_multiplier * node.interval
                # Compute actual elapsed silence duration since last received packet
                silence_duration = now - node.last_seen_ts
                # If silence duration exceeds timeout threshold, declare node DOWN
                if silence_duration > silence_limit:
                    # Update status to DOWN
                    node.status = "DOWN"
                    # Append failure event to event list
                    events.append(("NODE_DOWN", node_id))
                    # Notify event callback if configured
                    if self.event_callback:
                        # Invoke callback with timeout diagnostics
                        self.event_callback("NODE_DOWN", node_id, {
                            "silence_sec": round(silence_duration, 2),
                            "limit_sec": round(silence_limit, 2),
                        })

        # Return list of timeout events
        return events
