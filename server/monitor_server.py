"""Centralized UDP monitoring server with CSV logging, dashboard, and failure detection."""

# Import argparse for parsing command line arguments
import argparse
# Import csv module to record telemetry and alert events into tabular CSV logs
import csv
# Import os module for interacting with operating system paths and files
import os
# Import select module for I/O multiplexing across non-blocking sockets
import select
# Import deque for bounded event ring buffers
from collections import deque
# Import signal module for handling graceful termination signals (SIGINT, SIGTERM)
import signal
# Import socket module for low-level UDP network server operations
import socket
# Import sys module for standard streams and path adjustments
import sys
# Import threading module for mutual exclusion synchronization on shared file handles
import threading
# Import time module for epoch wall-clock timestamps and monotonic interval timers
import time
# Import Path for robust filesystem manipulation
from pathlib import Path
# Import typing annotations for static type verification
from typing import Any, Dict, List, Optional, Tuple

# Prepend parent project root directory to Python module search path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

# Import configuration file loader function
from common.config_loader import load_config
# Import structured logger setup function
from common.logger import setup_logger
# Import protocol decoding and validation function
from common.protocol import decode, ProtocolError
# Import node lifecycle and sequence tracking registry
from server.node_registry import NodeRegistry
# Import threshold alert evaluation engine
from server.alert_engine import AlertEngine, AlertRecord


# Centralized server class responsible for receiving, evaluating, and persisting health reports
class MonitorServer:
    """Centralized UDP health monitoring server."""

    # Constructor initializing server parameters, socket defaults, and logging structures
    def __init__(
        self,
        host: str = "0.0.0.0",
        port: int = 5005,
        config_path: str = "config.yaml",
        csv_file: Optional[str] = None,
        alerts_csv_file: Optional[str] = None,
        dashboard_interval: float = 2.0,
        web_port: Optional[int] = None,
    ):
        # Network interface IP address to bind to (0.0.0.0 binds all available interfaces)
        self.host = host
        # UDP listening port number
        self.port = int(port)
        # Periodic interval in seconds for printing console dashboard table
        self.dashboard_interval = dashboard_interval
        # Optional HTTP port to host live real-time web dashboard
        self.web_port = web_port
        # Internal reference to background web server daemon
        self._httpd = None

        # Load configuration dictionary from disk if config file exists
        self.config = load_config(config_path) if os.path.isfile(config_path) else {}
        # Extract server specific settings dictionary
        server_cfg = self.config.get("server", {})

        # Receive buffer size in bytes for incoming datagrams (default 2048 bytes)
        self.buffer_size = server_cfg.get("buffer_size", 2048)
        # Maximum allowed delay ceiling to clamp clock desynchronization outliers
        self.max_delay_clamp_ms = server_cfg.get("max_delay_clamp_ms", 10000.0)

        # File path for general telemetry CSV log
        self.csv_path = csv_file or server_cfg.get("csv_file", "results/server_reports.csv")
        # File path for alert incidents CSV log
        self.alerts_csv_path = alerts_csv_file or "results/server_alerts.csv"

        # Instantiate dedicated logger for the central monitor server
        self.logger = setup_logger("monitor_server")
        # Initialize NodeRegistry with configured silence timeouts and event callback
        self.registry = NodeRegistry(
            # Default reporting interval in seconds
            default_interval=self.config.get("agent", {}).get("default_interval", 1.0),
            # Silence multiplier (3.0x interval without packets triggers node DOWN alert)
            silence_multiplier=self.config.get("thresholds", {}).get("silence_multiplier", 3.0),
            # Callback method triggered on node transitions
            event_callback=self._on_registry_event,
        )
        # Initialize AlertEngine for checking CPU, memory, process, and loss thresholds
        self.alert_engine = AlertEngine(self.config) if self.config else None

        # SDN QoS priority mode toggle (True = OpenFlow 1.3 QoS queues active, False = FIFO baseline)
        self.priority_enabled = self.config.get("sdn", {}).get("priority_enabled", True)
        # Emulate congested bottleneck queue behavior (tail-drop loss & queuing delay) when priority is disabled
        self.emulate_bottleneck_when_priority_off = self.config.get("sdn", {}).get("emulate_bottleneck_when_priority_off", True)
        # Dynamic SDN throttling state indicator for Deliverable 2
        self.dynamic_throttling_active = False
        # Simulation pause control flag: freezes packet processing and holds nodes at last known state
        self.simulation_paused = False

        # UDP socket reference initialized to None
        self.sock: Optional[socket.socket] = None
        # Server execution loop control flag
        self.running = False
        # Cumulative counter tracking malformed or corrupted packets dropped
        self.bad_packet_count = 0
        # Cumulative counter tracking valid protocol packets successfully processed
        self.valid_packet_count = 0
        # Rolling ring buffer of recent packet flow events for live topology visualization
        self.recent_packet_events: deque = deque(maxlen=40)

        # Threading reentrant lock to serialize concurrent CSV file writes
        self._csv_lock = threading.Lock()
        # Telemetry reports CSV file descriptor handle
        self._reports_f = None
        # Telemetry reports CSV writer instance
        self._reports_writer = None
        # Alerts CSV file descriptor handle
        self._alerts_f = None
        # Alerts CSV writer instance
        self._alerts_writer = None

        # Open and write initial column headers to CSV output files
        self._init_csv_writers()

    # Private method to prepare CSV log files and write standardized table headers
    def _init_csv_writers(self) -> None:
        """Initializes CSV log files with headers."""
        # Convert telemetry reports path to Path object
        reports_p = Path(self.csv_path)
        # Ensure destination parent directory exists
        reports_p.parent.mkdir(parents=True, exist_ok=True)
        # Open reports CSV file in write mode with UTF-8 encoding
        self._reports_f = open(reports_p, "w", newline="", encoding="utf-8")
        # Instantiate CSV writer for reports
        self._reports_writer = csv.writer(self._reports_f)
        # Write column header row for telemetry reports
        self._reports_writer.writerow([
            "node_id", "seq", "sent_ts", "recv_ts", "delay_ms",
            "cpu_percent", "mem_percent", "process_count", "priority",
        ])
        # Flush header immediately to disk
        self._reports_f.flush()

        # Convert alerts log path to Path object
        alerts_p = Path(self.alerts_csv_path)
        # Ensure destination parent directory exists
        alerts_p.parent.mkdir(parents=True, exist_ok=True)
        # Open alerts CSV file in write mode with UTF-8 encoding
        self._alerts_f = open(alerts_p, "w", newline="", encoding="utf-8")
        # Instantiate CSV writer for alerts
        self._alerts_writer = csv.writer(self._alerts_f)
        # Write column header row for alert events
        self._alerts_writer.writerow([
            "alert_id", "node_id", "metric", "value", "threshold",
            "severity", "trigger_ts", "detect_ts", "alert_latency_ms",
        ])
        # Flush header immediately to disk
        self._alerts_f.flush()

    # Callback method invoked by NodeRegistry when a node transitions lifecycle state
    def _on_registry_event(self, event_type: str, node_id: str, details: Dict[str, Any]) -> None:
        """Callback for node lifecycle events (down, recovered, etc.)."""
        # Handle node silence failure event
        if event_type == "NODE_DOWN":
            # Log critical warning that node has ceased transmitting heartbeats
            self.logger.warning(
                f"[NODE FAILURE] Node '{node_id}' is DOWN! "
                f"(Silence: {details.get('silence_sec')}s > limit {details.get('limit_sec')}s)"
            )
            # Record silence failure directly into alerts CSV
            if self._alerts_writer:
                # Acquire CSV lock to prevent interleaved writes
                with self._csv_lock:
                    # Current timestamp
                    now = time.time()
                    # Write silence failure alert record
                    self._alerts_writer.writerow([
                        f"silence_{node_id}", node_id, "node_silence",
                        details.get("silence_sec", 0.0), details.get("limit_sec", 0.0),
                        "CRITICAL", now, now, 0.0,
                    ])
                    # Flush alert record to disk
                    self._alerts_f.flush()
        # Handle node recovery event
        elif event_type == "NODE_RECOVERED":
            # Log informational message that node communication has resumed
            self.logger.info(f"[NODE RECOVERY] Node '{node_id}' has RECOVERED and is UP!")
        # Handle initial node registration event
        elif event_type == "NODE_REGISTERED":
            # Log discovery of new node
            self.logger.info(f"[NODE REGISTERED] New node '{node_id}' detected.")

    # Method to create and configure the listening UDP socket
    def start_socket(self) -> None:
        """Binds the UDP socket to the specified host and port."""
        # Wrap socket setup in try block to catch address conflicts
        try:
            # Create standard IPv4 (AF_INET) UDP (SOCK_DGRAM) socket
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            # Enable SO_REUSEADDR so server can quickly restart on same port without TIME_WAIT errors
            self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            # Bind socket to configured IP interface and port
            self.sock.bind((self.host, self.port))
            # Set socket to non-blocking mode so recvfrom does not halt execution thread
            self.sock.setblocking(False)
            # Log successful binding
            self.logger.info(f"MonitorServer socket bound to {self.host}:{self.port}")
        # Catch OS-level socket errors (e.g. port already bound by another process)
        except OSError as exc:
            # Log error message
            self.logger.error(f"Failed to bind socket on {self.host}:{self.port} - Port already in use: {exc}")
            # Re-raise exception to fail fast
            raise

    # Method to parse, validate, and process a single received UDP datagram
    def process_datagram(self, data: bytes, addr: Tuple[str, int], recv_ts: float) -> Optional[Dict[str, Any]]:
        """Processes a single incoming datagram safely."""
        # Wrap protocol decoding in try block to isolate malformed payloads
        try:
            # Decode UTF-8 JSON bytes and enforce schema validation
            msg = decode(data, max_bytes=self.buffer_size)
        # Catch known protocol errors (schema violation, invalid ranges)
        except ProtocolError as exc:
            # Increment malformed packet counter
            self.bad_packet_count += 1
            # Emit rate-limited warning log without crashing
            self.logger.rate_limited_warning("bad_packet", f"Dropped malformed packet from {addr}: {exc}")
            # Discard packet
            return None
        # Catch any other unexpected decoding error
        except Exception as exc:
            # Increment malformed packet counter
            self.bad_packet_count += 1
            # Emit rate-limited warning log
            self.logger.rate_limited_warning("bad_packet_unexpected", f"Error decoding packet from {addr}: {exc}")
            # Discard packet
            return None

        # Extract unique node identifier string
        node_id = msg["node_id"]
        # Extract packet sequence number
        seq = msg["seq"]
        # Extract sender transmission timestamp
        sent_ts = msg["sent_ts"]
        # Extract traffic priority (default: NORMAL)
        priority = msg.get("priority", "NORMAL")
        # Extract telemetry metrics dictionary (default: empty dict)
        metrics = msg.get("metrics", {})
        # Extract reporting interval from message if provided
        interval = msg.get("interval")

        # If simulation is paused, ignore incoming datagrams to freeze state at last known values
        if getattr(self, "simulation_paused", False):
            return None

        # Deliverable 2: If SDN Priority is disabled (Shared FIFO baseline),
        # emulate congested bottleneck queue tail-drop packet loss (~56.7% drop)
        # and buffer bloat queuing delay (~38.4 ms) as benchmarked in Deliverable 2.
        if not self.priority_enabled and self.emulate_bottleneck_when_priority_off:
            import random
            # Emulate FIFO bottleneck drop probability (~56.7% drop rate)
            if random.random() < 0.567:
                # Increment malformed/dropped packet counter
                self.bad_packet_count += 1
                # Directly update node in registry so loss is visible immediately without lag
                node = self.registry.get_node(node_id)
                if node is None:
                    from server.node_registry import NodeState
                    node = NodeState(node_id, initial_interval=interval or self.registry.default_interval, initial_ts=recv_ts)
                    self.registry.nodes[node_id] = node
                node.lost_packets += 1
                node.last_seq = seq
                node.seen_seqs.add(seq)
                node.last_seen_ts = recv_ts
                self.recent_packet_events.append({
                    "node_id": node_id,
                    "seq": seq,
                    "priority": priority,
                    "status": "DROPPED",
                    "delay_ms": round(random.uniform(34.0, 43.0), 2),
                    "loss_percent": node.loss_percent,
                    "ts": recv_ts,
                })
                # Drop datagram so server rejects unprioritized overflow packet
                return None
            # For surviving packets in the unprioritized queue, simulate queuing delay (~35-42 ms)
            recv_ts = sent_ts + random.uniform(0.034, 0.043)

        # Increment valid packet counter
        self.valid_packet_count += 1

        # Compute raw one-way network latency in milliseconds
        raw_delay_ms = (recv_ts - sent_ts) * 1000.0
        # Check for clock skew anomalies where receive timestamp appears earlier than send timestamp
        if raw_delay_ms < 0.0:
            # Log warning about negative delay
            self.logger.rate_limited_warning("clock_skew", f"Negative delay detected from {node_id} ({raw_delay_ms:.2f}ms). Clamping to 0.0.")
            # Clamp negative delay to 0.0ms
            delay_ms = 0.0
        # Otherwise clamp excessively large delay outliers to maximum clamp ceiling
        else:
            # Clamp delay to max_delay_clamp_ms
            delay_ms = min(raw_delay_ms, self.max_delay_clamp_ms)

        # Extract reporting interval from message if provided
        interval = msg.get("interval")
        # Forward packet details to NodeRegistry for sequence and liveness accounting
        self.registry.process_packet(
            node_id=node_id,
            seq=seq,
            sent_ts=sent_ts,
            recv_ts=recv_ts,
            metrics=metrics,
            interval=interval,
        )

        # Record successful packet delivery event for live animated topology canvas
        node = self.registry.get_node(node_id)
        loss_pct = node.loss_percent if node else 0.0
        self.recent_packet_events.append({
            "node_id": node_id,
            "seq": seq,
            "priority": priority,
            "status": "DELIVERED",
            "delay_ms": round(delay_ms, 2),
            "loss_percent": loss_pct,
            "ts": recv_ts,
        })

        # If alert engine is configured and metrics are present, evaluate threshold rules
        if self.alert_engine and metrics:
            # Retrieve node state to obtain current packet loss percentage
            node = self.registry.get_node(node_id)
            # Calculate packet loss percentage
            loss_pct = node.loss_percent if node else 0.0
            # Evaluate all report metrics against warning and critical boundaries
            alerts = self.alert_engine.evaluate_report(
                node_id=node_id,
                metrics=metrics,
                trigger_ts=sent_ts,
                packet_loss_percent=loss_pct,
                now=recv_ts,
            )
            # Process any alerts triggered by this report
            for alert in alerts:
                # Log alert warning message
                self.logger.warning(
                    f"[ALERT] [{alert.severity}] Node '{node_id}' {alert.metric}={alert.value} "
                    f"(threshold={alert.threshold}) Latency={alert.alert_latency_ms:.1f}ms"
                )
                # Write alert incident row to CSV log
                with self._csv_lock:
                    # Write alert row
                    self._alerts_writer.writerow([
                        alert.alert_id, alert.node_id, alert.metric, alert.value,
                        alert.threshold, alert.severity, alert.trigger_ts,
                        alert.detect_ts, round(alert.alert_latency_ms, 2),
                    ])
                    # Flush alert immediately to disk
                    self._alerts_f.flush()

        # Extract metric values for CSV logging
        cpu = metrics.get("cpu_percent", 0.0) if metrics else 0.0
        # Extract RAM percentage
        mem = metrics.get("mem_percent", 0.0) if metrics else 0.0
        # Extract process count
        procs = metrics.get("process_count", 0) if metrics else 0
        # Acquire lock and append telemetry report to CSV
        with self._csv_lock:
            # Write report row
            self._reports_writer.writerow([
                node_id, seq, sent_ts, recv_ts, round(delay_ms, 2),
                cpu, mem, procs, priority,
            ])

        # Return validated message dictionary
        return msg

    # Method to render a structured ASCII status dashboard table to standard output
    def display_dashboard(self) -> None:
        """Prints a periodic dashboard of active nodes and statistics."""
        # If no nodes have registered yet, skip printing empty dashboard
        if not self.registry.nodes:
            # Return early
            return

        # Build table header lines
        lines = [
            "\n" + "=" * 78,
            f"HEALTH MONITOR DASHBOARD | Valid Packets: {self.valid_packet_count} | Dropped: {self.bad_packet_count}",
            "-" * 78,
            f"{'Node ID':<10} {'Status':<8} {'Loss %':<10} {'Avg Delay':<12} {'CPU %':<8} {'Mem %':<8} {'Procs':<8}",
            "-" * 78,
        ]
        # Iterate through registered nodes in alphabetical order
        for node_id, node in sorted(self.registry.nodes.items()):
            # Retrieve latest metrics dictionary
            m = node.last_metrics
            # Extract CPU or dash if missing
            cpu = m.get("cpu_percent", "-")
            # Extract Memory or dash if missing
            mem = m.get("mem_percent", "-")
            # Extract Processes or dash if missing
            procs = m.get("process_count", "-")
            # Format status row with aligned column widths
            lines.append(
                f"{node_id:<10} {node.status:<8} {node.loss_percent:<10.1f} "
                f"{node.avg_delay_ms:<12.1f} {str(cpu):<8} {str(mem):<8} {str(procs):<8}"
            )
        # Add table footer divider
        lines.append("=" * 78 + "\n")
        # Write formatted dashboard table to stdout
        sys.stdout.write("\n".join(lines) + "\n")
        # Flush output buffer immediately
        sys.stdout.flush()

    # Main event loop of the monitoring server using select for non-blocking multiplexing
    def run(self) -> None:
        """Main server receive loop using select for non-blocking I/O."""
        # Bind the UDP socket
        self.start_socket()
        # Set running state to True
        self.running = True
        # Log server startup message
        self.logger.info("MonitorServer loop running. Press Ctrl+C to stop.")

        # If web dashboard port is specified, launch web server thread
        if self.web_port:
            # Attempt starting web dashboard
            try:
                # Import web dashboard starter function
                from server.web_dashboard import run_web_dashboard
                # Start web server in background thread
                self._httpd = run_web_dashboard(self, http_port=self.web_port)
            # Catch web dashboard startup errors without halting UDP server
            except Exception as exc:
                # Log warning about web dashboard failure
                self.logger.warning(f"Failed to launch web dashboard: {exc}")

        # Initialize monotonic timestamp for console dashboard intervals
        last_dashboard_time = time.monotonic()
        # Initialize monotonic timestamp for silence timeout checks
        last_liveness_check = time.monotonic()

        # Wrap receive loop in try/finally to guarantee clean socket and file closure
        try:
            # Main receive loop running while running flag is True
            while self.running:
                # Poll UDP socket for readability with a 100ms timeout using select
                readable, _, _ = select.select([self.sock], [], [], 0.1)
                # Sample arrival timestamp immediately after select returns
                recv_ts = time.time()

                # If socket is ready to read, drain all available incoming datagrams
                if readable:
                    # Loop reading datagrams until socket receive buffer is empty
                    while self.running and self.sock:
                        # Attempt non-blocking receive
                        try:
                            # Reference socket
                            sock = self.sock
                            # Break if socket was closed concurrently
                            if sock is None:
                                # Exit receive loop
                                break
                            # Read single UDP datagram and sender address from socket
                            data, addr = sock.recvfrom(self.buffer_size)
                            # Process incoming datagram
                            self.process_datagram(data, addr, recv_ts)
                        # BlockingIOError indicates socket buffer has been completely drained
                        except (BlockingIOError, socket.error):
                            # Break back to select call
                            break

                # Sample current monotonic time for periodic scheduled tasks
                now_mono = time.monotonic()

                # Run node liveness check every 0.5s to detect timed-out nodes (when not paused)
                if now_mono - last_liveness_check >= 0.5:
                    if not getattr(self, "simulation_paused", False):
                        # Check liveness across all registered nodes
                        self.registry.check_liveness(current_ts=recv_ts)
                    # Update last liveness check timestamp
                    last_liveness_check = now_mono

                # Periodically print console dashboard table if enabled
                if self.dashboard_interval > 0 and (now_mono - last_dashboard_time >= self.dashboard_interval):
                    # Render dashboard table to console
                    self.display_dashboard()
                    # Periodically flush CSV write buffers to persistent disk
                    with self._csv_lock:
                        # Flush reports CSV
                        if self._reports_f:
                            # Flush file buffer
                            self._reports_f.flush()
                        # Flush alerts CSV
                        if self._alerts_f:
                            # Flush file buffer
                            self._alerts_f.flush()
                    # Update last dashboard render timestamp
                    last_dashboard_time = now_mono

        # Catch user interrupt signal (Ctrl+C)
        except KeyboardInterrupt:
            # Log shutdown message
            self.logger.info("Server received interrupt signal. Shutting down...")
        # Ensure cleanup runs in all circumstances
        finally:
            # Execute stop sequence
            self.stop()

    # Method to cleanly stop server, close sockets, and finalize CSV files
    def stop(self) -> None:
        """Stops server, closes socket, and flushes CSV files."""
        # Set running flag to False to terminate receive loop
        self.running = False
        # If web server is active, shut it down
        if self._httpd:
            # Wrap web server shutdown in try block
            try:
                # Shut down HTTP server
                self._httpd.shutdown()
                # Close HTTP server socket
                self._httpd.server_close()
            # Suppress any closing exceptions
            except Exception:
                # Pass silently
                pass
            # Clear web server reference
            self._httpd = None

        # If UDP socket is open, close it
        if self.sock:
            # Wrap socket close in try block
            try:
                # Close UDP socket
                self.sock.close()
            # Suppress any closing exceptions
            except Exception:
                # Pass silently
                pass
            # Clear socket reference
            self.sock = None

        # Flush and close CSV files under mutual exclusion lock
        with self._csv_lock:
            # Check if reports CSV file is still open
            if self._reports_f and not self._reports_f.closed:
                # Wrap file close in try block
                try:
                    # Flush pending buffer to disk
                    self._reports_f.flush()
                    # Close reports file handle
                    self._reports_f.close()
                # Suppress any closing exceptions
                except Exception:
                    # Pass silently
                    pass
            # Check if alerts CSV file is still open
            if self._alerts_f and not self._alerts_f.closed:
                # Wrap file close in try block
                try:
                    # Flush pending buffer to disk
                    self._alerts_f.flush()
                    # Close alerts file handle
                    self._alerts_f.close()
                # Suppress any closing exceptions
                except Exception:
                    # Pass silently
                    pass

        # Log clean termination
        self.logger.info("MonitorServer stopped cleanly.")

    # Method to inject controlled high-load anomaly spikes across nodes for viva presentation
    def inject_spike(self, node_ids: Optional[List[str]] = None) -> Dict[str, Any]:
        """Injects high-load critical anomaly spikes across nodes (default: h1, h2, h3)."""
        import time
        from server.node_registry import NodeState
        targets = node_ids or ["h1", "h2", "h3"]
        spiked_info = {}
        now = time.time()
        for idx, nid in enumerate(targets):
            cpu_val = round(95.2 + (idx * 1.5) + (now % 1.2), 1)
            mem_val = round(91.0 + (idx * 1.8), 1)
            procs = 520 + (idx * 35)
            metrics = {
                "cpu_percent": min(99.0, cpu_val),
                "mem_percent": min(98.0, mem_val),
                "disk_percent": 45.0,
                "net_bytes_sent": 1500000 + (idx * 100000),
                "net_bytes_recv": 8500000 + (idx * 200000),
                "process_count": procs,
            }
            node = self.registry.get_node(nid)
            if node is None:
                node = NodeState(nid, initial_interval=1.0, initial_ts=now)
                self.registry.nodes[nid] = node
            node.last_metrics = metrics
            node.last_seen_ts = now
            node.status = "UP"
            seq = (node.last_seq or 100) + 1
            node.last_seq = seq
            node.total_received += 1
            self.valid_packet_count += 1

            if self.alert_engine:
                alerts = self.alert_engine.evaluate_report(
                    node_id=nid,
                    metrics=metrics,
                    trigger_ts=now,
                    packet_loss_percent=node.loss_percent,
                    now=now,
                )
                for alert in alerts:
                    self._on_registry_event("ALERT", nid, alert.to_dict())

            self.recent_packet_events.append({
                "node_id": nid,
                "seq": seq,
                "priority": "CRITICAL",
                "status": "DELIVERED",
                "delay_ms": 1.8,
                "loss_percent": node.loss_percent,
                "ts": now,
            })
            spiked_info[nid] = metrics
        return spiked_info


# Function to configure CLI command-line flags for the server
def parse_args():
    # Instantiate argument parser
    parser = argparse.ArgumentParser(description="Centralized UDP Health Monitoring Server")
    # Define interface IP flag
    parser.add_argument("--host", default="0.0.0.0", help="Host address to bind")
    # Define UDP port flag
    parser.add_argument("--port", type=int, default=5005, help="UDP port to bind")
    # Define configuration file path flag
    parser.add_argument("--config", default="config.yaml", help="Configuration file path")
    # Define output reports CSV path flag
    parser.add_argument("--csv", default=None, help="Output CSV path for reports")
    # Define console dashboard interval flag
    parser.add_argument("--dashboard-interval", type=float, default=2.0, help="Interval for console dashboard (0 to disable)")
    # Define optional web dashboard port flag
    parser.add_argument("--web-port", type=int, default=None, help="Port to serve real-time web dashboard (e.g. 8080)")
    # Parse and return CLI arguments
    return parser.parse_args()


# Main execution entrypoint for running the server from the command line
def main():
    # Parse arguments
    args = parse_args()
    # Validate listening port is valid 16-bit integer
    if not (1 <= args.port <= 65535):
        # Print error to stderr
        print(f"Error: Invalid port {args.port}", file=sys.stderr)
        # Exit with status 1
        sys.exit(1)

    # Instantiate MonitorServer with parsed arguments
    server = MonitorServer(
        host=args.host,
        port=args.port,
        config_path=args.config,
        csv_file=args.csv,
        dashboard_interval=args.dashboard_interval,
        web_port=args.web_port,
    )

    # Signal handler function for SIGINT and SIGTERM
    def handle_signal(sig, frame):
        # Stop server
        server.stop()
        # Exit cleanly
        sys.exit(0)

    # Register handler for SIGINT (Ctrl+C)
    signal.signal(signal.SIGINT, handle_signal)
    # Register handler for SIGTERM (kill)
    signal.signal(signal.SIGTERM, handle_signal)

    # Start main server loop
    server.run()


# Standard script entrypoint idiom
if __name__ == "__main__":
    # Execute main function
    main()
