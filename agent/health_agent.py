"""UDP Health-reporting agent running on simulated server nodes."""

# Import argparse for command-line argument parsing
import argparse
# Import os for operating system level path resolution
import os
# Import signal module for intercepting SIGINT and SIGTERM termination signals
import signal
# Import socket module for low-level UDP network communications
import socket
# Import sys for standard system operations, sys.path modification, and exit codes
import sys
# Import time for monotonic scheduling and epoch timestamps
import time
# Import typing annotations for type safety and code readability
from typing import Any, Dict, Optional

# Prepend project root directory to sys.path so modules like common/ and agent/ can be imported cleanly
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

# Import configuration file loader function
from common.config_loader import load_config
# Import structured logger factory function
from common.logger import setup_logger
# Import protocol encoding function and exception class
from common.protocol import encode, ProtocolError
# Import telemetry stats collector class
from agent.stats_collector import StatsCollector

# DSCP 46 (Expedited Forwarding - EF) shifted by 2 bits for IP_TOS: (46 << 2) = 184 (0xB8)
TOS_EF_CRITICAL = 0xB8
# Standard Best-Effort traffic TOS value (0x00) for normal non-urgent telemetry
TOS_BEST_EFFORT = 0x00


# Class representing an autonomous health-reporting agent on a network node
class HealthAgent:
    """UDP health monitoring reporting agent."""

    # Constructor initializing agent identity, target server, intervals, and modes
    def __init__(
        self,
        node_id: str,
        server_ip: str = "127.0.0.1",
        server_port: int = 5005,
        interval: float = 1.0,
        mode: str = "real",
        sim_pattern: str = "normal",
        fail_after: Optional[int] = None,
        recover_after: Optional[float] = None,
        config_path: str = "config.yaml",
        spike_interval: int = 5,
    ):
        # Validate that the reporting interval is strictly positive
        if interval <= 0:
            # Raise ValueError if reporting interval is <= 0
            raise ValueError(f"Interval must be positive, got {interval}")
        # Validate that the server UDP port is within the legal 16-bit range
        if not (1 <= server_port <= 65535):
            # Raise ValueError if server port is out of range
            raise ValueError(f"Port must be between 1 and 65535, got {server_port}")
        # Validate that node_id is provided as a non-empty string
        if not node_id or not isinstance(node_id, str):
            # Raise ValueError if node_id is empty or invalid
            raise ValueError("node_id must be a non-empty string")

        # Assign unique host/node identifier string
        self.node_id = node_id
        # Assign central monitoring server IP address
        self.server_ip = server_ip
        # Assign central monitoring server UDP listening port
        self.server_port = server_port
        # Assign reporting cadence in seconds
        self.interval = float(interval)
        # Collection mode: 'real' uses psutil; 'simulated' generates synthetic metrics
        self.mode = mode
        # Simulation pattern ('normal', 'spike', 'ramp-up', 'constant-high')
        self.sim_pattern = sim_pattern
        # Packet count threshold after which node simulates an abrupt crash failure
        self.fail_after = fail_after
        # Duration in seconds before recovering from simulated crash (None = permanent crash)
        self.recover_after = recover_after
        # Interval in ticks between periodic anomaly spikes in simulated mode
        self.spike_interval = spike_interval

        # Initialize dictionary to store parsed YAML configuration
        self.config = {}
        # Attempt to load configuration file from specified path
        try:
            # Load YAML configuration
            self.config = load_config(config_path)
        # Catch errors if configuration file cannot be loaded
        except Exception:
            # Default to empty config dictionary
            self.config = {}

        # Extract alert thresholds from configuration or apply built-in defaults
        self.thresholds = self.config.get("thresholds", {
            # CPU warning at 70%, critical at 90%
            "cpu_percent": {"warning": 70.0, "critical": 90.0},
            # RAM warning at 75%, critical at 90%
            "mem_percent": {"warning": 75.0, "critical": 90.0},
            # Process count warning at 300, critical at 500
            "process_count": {"warning": 300, "critical": 500},
        })

        # Set up a dedicated logger instance named after this node
        self.logger = setup_logger(f"agent_{node_id}")
        # Instantiate telemetry collector for querying local host metrics
        self.collector = StatsCollector(mode=mode, sim_pattern=sim_pattern, spike_interval=spike_interval)
        # Sequence number counter initialized to 0
        self.seq = 0
        # Execution loop control flag
        self.running = False
        # UDP socket reference initialized to None
        self.sock: Optional[socket.socket] = None
        # Track active IP_TOS value to avoid redundant setsockopt syscalls
        self._current_tos = -1

    # Private method to initialize the UDP socket and default QoS settings
    def _init_socket(self) -> None:
        """Initializes the UDP socket with default QoS options."""
        # Create standard IPv4 (AF_INET) datagram (SOCK_DGRAM) UDP socket
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        # Set default Best-Effort TOS value
        self._set_tos(TOS_BEST_EFFORT)

    # Private method to configure DSCP/TOS byte on the outbound UDP socket
    def _set_tos(self, tos_val: int) -> None:
        """Sets the DSCP/TOS field on the socket if changed."""
        # Check if socket exists and requested TOS differs from current setting
        if self.sock and self._current_tos != tos_val:
            # Attempt to set IP_TOS socket option via kernel setsockopt
            try:
                # Set IP_TOS option on IP level protocol layer (IPPROTO_IP)
                self.sock.setsockopt(socket.IPPROTO_IP, socket.IP_TOS, tos_val)
                # Cache newly assigned TOS value
                self._current_tos = tos_val
            # Catch OS-level socket configuration errors (e.g., privilege restrictions)
            except OSError as exc:
                # Emit rate-limited warning without crashing agent
                self.logger.rate_limited_warning("tos_error", f"Failed to set IP_TOS to {tos_val}: {exc}")

    # Method to determine if current metrics breach warning or critical thresholds
    def is_critical(self, metrics: Dict[str, Any]) -> bool:
        """Evaluates whether metrics violate warning or critical thresholds."""
        # Extract CPU usage percentage from metrics
        cpu = metrics.get("cpu_percent", 0.0)
        # Extract memory usage percentage from metrics
        mem = metrics.get("mem_percent", 0.0)
        # Extract total active process count from metrics
        procs = metrics.get("process_count", 0)

        # Retrieve CPU warning threshold (default: 70.0%)
        cpu_warn = self.thresholds.get("cpu_percent", {}).get("warning", 70.0)
        # Retrieve memory warning threshold (default: 75.0%)
        mem_warn = self.thresholds.get("mem_percent", {}).get("warning", 75.0)
        # Retrieve process count warning threshold (default: 300)
        proc_warn = self.thresholds.get("process_count", {}).get("warning", 300)

        # Return True if any single metric breaches its warning threshold
        return (cpu >= cpu_warn) or (mem >= mem_warn) or (procs >= proc_warn)

    # Method to gather metrics and construct standard protocol message dictionary
    def build_payload(self) -> Dict[str, Any]:
        """Collects metrics and builds the protocol message."""
        # Increment packet sequence number
        self.seq += 1
        # Record sender wall-clock timestamp
        sent_ts = time.time()

        # Wrap telemetry collection in try block to handle collection failures gracefully
        try:
            # Query stats collector for current system metrics
            metrics = self.collector.collect()
            # If collector reported internal failure, fall back to lightweight HEARTBEAT
            if "collector_error" in metrics:
                # Construct lightweight HEARTBEAT payload without detailed metrics
                return {
                    # Protocol version identifier
                    "version": 1,
                    # Message type HEARTBEAT indicates alive status without metrics
                    "type": "HEARTBEAT",
                    # Node identifier
                    "node_id": self.node_id,
                    # Sequence number
                    "seq": self.seq,
                    # Timestamp
                    "sent_ts": sent_ts,
                    # Normal priority
                    "priority": "NORMAL",
                }

            # Determine traffic priority: CRITICAL if thresholds breached, otherwise NORMAL
            priority = "CRITICAL" if self.is_critical(metrics) else "NORMAL"
            # Set message type: ALERT for critical conditions, HEALTH for regular reports
            msg_type = "ALERT" if priority == "CRITICAL" else "HEALTH"

            # Return complete health report dictionary
            return {
                # Protocol version 1
                "version": 1,
                # Message type (HEALTH or ALERT)
                "type": msg_type,
                # Node identifier string
                "node_id": self.node_id,
                # Monotonically increasing sequence number
                "seq": self.seq,
                # Exact epoch transmission timestamp
                "sent_ts": sent_ts,
                # Reporting interval for silence timeout calculation on server
                "interval": self.interval,
                # Traffic priority classification
                "priority": priority,
                # Collected system metrics dictionary
                "metrics": metrics,
            }
        # Catch unexpected errors during stats collection
        except Exception as exc:
            # Log warning about collection failure
            self.logger.warning(f"Error collecting stats: {exc}. Falling back to HEARTBEAT.")
            # Return safe fallback HEARTBEAT message
            return {
                # Protocol version 1
                "version": 1,
                # Message type HEARTBEAT
                "type": "HEARTBEAT",
                # Node identifier
                "node_id": self.node_id,
                # Sequence number
                "seq": self.seq,
                # Timestamp
                "sent_ts": sent_ts,
                # Interval
                "interval": self.interval,
                # Priority
                "priority": "NORMAL",
            }

    # Method to encode and transmit payload over UDP socket to the server
    def send_report(self, payload: Dict[str, Any]) -> bool:
        """Encodes and sends payload over UDP socket."""
        # Wrap network transmission in try block
        try:
            # Check if socket is open and ready
            if not self.sock:
                # Return False if socket is not initialized
                return False
            # Encode payload dictionary into validated UTF-8 JSON network bytes
            raw = encode(payload)
            # Determine appropriate IP_TOS marking based on message priority
            tos = TOS_EF_CRITICAL if payload.get("priority") == "CRITICAL" else TOS_BEST_EFFORT
            # Apply TOS value to socket before sending
            self._set_tos(tos)

            # Transmit UDP datagram to destination server IP and port
            self.sock.sendto(raw, (self.server_ip, self.server_port))
            # Return True indicating successful socket transmission
            return True
        # Catch network addressing and OS socket send errors
        except (socket.gaierror, OSError) as exc:
            # Log rate-limited transmission failure warning
            self.logger.rate_limited_warning("send_error", f"UDP send failed: {exc}")
            # Return False on send failure
            return False
        # Catch protocol encoding or validation errors
        except ProtocolError as exc:
            # Log protocol error
            self.logger.error(f"Protocol encoding error: {exc}")
            # Return False on protocol failure
            return False

    # Main execution loop of the reporting agent
    def run(self) -> None:
        """Main periodic reporting loop with monotonic scheduling."""
        # Initialize outbound UDP socket
        self._init_socket()
        # Set running state to True
        self.running = True
        # Log agent startup message with configuration details
        self.logger.info(
            f"HealthAgent [{self.node_id}] started -> {self.server_ip}:{self.server_port} "
            f"(interval={self.interval}s, mode={self.mode})"
        )

        # Counter tracking total successfully transmitted packets
        sent_count = 0
        # Initialize monotonic scheduler tick mark
        next_tick = time.monotonic()

        # Wrap main loop in try/finally to guarantee clean socket teardown
        try:
            # Continue running while self.running flag is True
            while self.running:
                # Check if simulated failure trigger has been reached
                if self.fail_after is not None and sent_count >= self.fail_after:
                    # Log failure simulation warning
                    self.logger.warning(f"Simulating node crash after {sent_count} packets sent.")
                    # Check if temporary recovery duration is configured
                    if self.recover_after is not None and self.recover_after > 0:
                        # Log temporary recovery sleep duration
                        self.logger.info(f"Sleeping for {self.recover_after}s before recovering...")
                        # Sleep to simulate node downtime
                        time.sleep(self.recover_after)
                        # Log resumption of reporting
                        self.logger.info("Agent recovered! Resuming reporting.")
                        # Clear fail_after so node resumes normal reporting indefinitely
                        self.fail_after = None
                        # Re-align next scheduled tick mark to current time
                        next_tick = time.monotonic()
                    # Otherwise node undergoes permanent unrecoverable failure
                    else:
                        # Log abrupt process termination
                        self.logger.info("Abruptly stopping agent process (unrecoverable crash).")
                        # Break out of reporting loop
                        break

                # Assemble outgoing health payload
                payload = self.build_payload()
                # Transmit payload over UDP socket
                if self.send_report(payload):
                    # Increment transmitted packet counter on success
                    sent_count += 1

                # Advance next scheduled tick mark by fixed interval duration
                next_tick += self.interval
                # Calculate required sleep duration using monotonic clock
                sleep_duration = next_tick - time.monotonic()
                # If ahead of schedule, sleep for the remaining duration
                if sleep_duration > 0:
                    # Sleep precisely until next tick
                    time.sleep(sleep_duration)
                # If execution lagged behind schedule (e.g. system stall), realign clock
                else:
                    # Realign next tick to current monotonic timestamp to prevent cascade catchup
                    next_tick = time.monotonic()

        # Handle user termination via Ctrl+C cleanly
        except KeyboardInterrupt:
            # Log receipt of keyboard interrupt
            self.logger.info("Agent received interrupt signal. Shutting down...")
        # Guarantee stop() is called regardless of termination path
        finally:
            # Perform clean shutdown and socket closure
            self.stop()

    # Method to gracefully stop the agent and close open sockets
    def stop(self) -> None:
        """Closes socket and terminates running loop."""
        # Set running flag to False to terminate loop
        self.running = False
        # Check if socket is open
        if self.sock:
            # Attempt clean socket close
            try:
                # Close the UDP socket
                self.sock.close()
            # Suppress any closing errors
            except Exception:
                # Ignore close exceptions
                pass
            # Clear socket reference
            self.sock = None
        # Log clean termination
        self.logger.info(f"HealthAgent [{self.node_id}] stopped.")


# Function to define and parse CLI command-line arguments
def parse_args():
    # Instantiate argument parser with descriptive help text
    parser = argparse.ArgumentParser(description="UDP Health-Reporting Agent")
    # Define mandatory node identifier flag
    parser.add_argument("--id", required=True, dest="node_id", help="Node ID (e.g. h1)")
    # Define optional monitoring server IP flag (defaults to localhost)
    parser.add_argument("--server", default="127.0.0.1", help="Monitoring server IP")
    # Define optional monitoring server UDP port flag (defaults to 5005)
    parser.add_argument("--port", type=int, default=5005, help="Monitoring server UDP port")
    # Define optional reporting interval flag (defaults to 1.0 second)
    parser.add_argument("--interval", type=float, default=1.0, help="Reporting interval in seconds")
    # Define optional collection mode ('real' vs 'simulated')
    parser.add_argument("--mode", choices=["real", "simulated"], default="real", help="Metrics collection mode")
    # Define simulation pattern flag
    parser.add_argument("--sim-pattern", choices=["normal", "spike", "ramp-up", "constant-high"], default="normal")
    # Define optional crash trigger after N packets
    parser.add_argument("--fail-after", type=int, default=None, help="Simulate crash after N packets sent")
    # Define optional recovery timeout in seconds
    parser.add_argument("--recover-after", type=float, default=None, help="Resume reporting after M seconds")
    # Define optional path to YAML config file
    parser.add_argument("--config", default="config.yaml", help="Path to configuration file")
    # Parse and return CLI argument namespace
    return parser.parse_args()


# Main execution entrypoint for running the agent directly from CLI
def main():
    # Parse CLI arguments
    args = parse_args()
    # Validate reporting interval is positive
    if args.interval <= 0:
        # Print error message to stderr
        print(f"Error: --interval must be > 0, got {args.interval}", file=sys.stderr)
        # Exit with error code 1
        sys.exit(1)

    # Instantiate HealthAgent with parsed command-line parameters
    agent = HealthAgent(
        node_id=args.node_id,
        server_ip=args.server,
        server_port=args.port,
        interval=args.interval,
        mode=args.mode,
        sim_pattern=args.sim_pattern,
        fail_after=args.fail_after,
        recover_after=args.recover_after,
        config_path=args.config,
    )

    # Signal handler for clean termination on SIGINT (Ctrl+C) and SIGTERM (kill)
    def handle_signal(sig, frame):
        # Stop agent execution
        agent.stop()
        # Exit cleanly with status 0
        sys.exit(0)

    # Register signal handler for SIGINT
    signal.signal(signal.SIGINT, handle_signal)
    # Register signal handler for SIGTERM
    signal.signal(signal.SIGTERM, handle_signal)

    # Start main reporting loop
    agent.run()


# Standard Python script entrypoint idiom
if __name__ == "__main__":
    # Execute main function
    main()
