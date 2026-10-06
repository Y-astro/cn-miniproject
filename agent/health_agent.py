"""UDP Health-reporting agent running on simulated server nodes."""

import argparse
import os
import signal
import socket
import sys
import time
from typing import Any, Dict, Optional

# Ensure project root is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from common.config_loader import load_config
from common.logger import setup_logger
from common.protocol import encode, ProtocolError
from agent.stats_collector import StatsCollector

# IP_TOS values
# DSCP 46 (Expedited Forwarding - EF) -> DSCP << 2 = 184 = 0xB8
TOS_EF_CRITICAL = 0xB8
TOS_BEST_EFFORT = 0x00


class HealthAgent:
    """UDP health monitoring reporting agent."""

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
        if interval <= 0:
            raise ValueError(f"Interval must be positive, got {interval}")
        if not (1 <= server_port <= 65535):
            raise ValueError(f"Port must be between 1 and 65535, got {server_port}")
        if not node_id or not isinstance(node_id, str):
            raise ValueError("node_id must be a non-empty string")

        self.node_id = node_id
        self.server_ip = server_ip
        self.server_port = server_port
        self.interval = float(interval)
        self.mode = mode
        self.sim_pattern = sim_pattern
        self.fail_after = fail_after
        self.recover_after = recover_after
        self.spike_interval = spike_interval

        # Load config for thresholds
        self.config = {}
        try:
            self.config = load_config(config_path)
        except Exception:
            self.config = {}

        self.thresholds = self.config.get("thresholds", {
            "cpu_percent": {"warning": 70.0, "critical": 90.0},
            "mem_percent": {"warning": 75.0, "critical": 90.0},
            "process_count": {"warning": 300, "critical": 500},
        })

        self.logger = setup_logger(f"agent_{node_id}")
        self.collector = StatsCollector(mode=mode, sim_pattern=sim_pattern, spike_interval=spike_interval)
        self.seq = 0
        self.running = False
        self.sock: Optional[socket.socket] = None
        self._current_tos = -1

    def _init_socket(self) -> None:
        """Initializes the UDP socket with default QoS options."""
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._set_tos(TOS_BEST_EFFORT)

    def _set_tos(self, tos_val: int) -> None:
        """Sets the DSCP/TOS field on the socket if changed."""
        if self.sock and self._current_tos != tos_val:
            try:
                self.sock.setsockopt(socket.IPPROTO_IP, socket.IP_TOS, tos_val)
                self._current_tos = tos_val
            except OSError as exc:
                self.logger.rate_limited_warning("tos_error", f"Failed to set IP_TOS to {tos_val}: {exc}")

    def is_critical(self, metrics: Dict[str, Any]) -> bool:
        """Evaluates whether metrics violate warning or critical thresholds."""
        cpu = metrics.get("cpu_percent", 0.0)
        mem = metrics.get("mem_percent", 0.0)
        procs = metrics.get("process_count", 0)

        cpu_warn = self.thresholds.get("cpu_percent", {}).get("warning", 70.0)
        mem_warn = self.thresholds.get("mem_percent", {}).get("warning", 75.0)
        proc_warn = self.thresholds.get("process_count", {}).get("warning", 300)

        return (cpu >= cpu_warn) or (mem >= mem_warn) or (procs >= proc_warn)

    def build_payload(self) -> Dict[str, Any]:
        """Collects metrics and builds the protocol message."""
        self.seq += 1
        sent_ts = time.time()

        try:
            metrics = self.collector.collect()
            if "collector_error" in metrics:
                # Stats collection failed -> send lightweight HEARTBEAT
                return {
                    "version": 1,
                    "type": "HEARTBEAT",
                    "node_id": self.node_id,
                    "seq": self.seq,
                    "sent_ts": sent_ts,
                    "priority": "NORMAL",
                }

            priority = "CRITICAL" if self.is_critical(metrics) else "NORMAL"
            msg_type = "ALERT" if priority == "CRITICAL" else "HEALTH"

            return {
                "version": 1,
                "type": msg_type,
                "node_id": self.node_id,
                "seq": self.seq,
                "sent_ts": sent_ts,
                "interval": self.interval,
                "priority": priority,
                "metrics": metrics,
            }
        except Exception as exc:
            self.logger.warning(f"Error collecting stats: {exc}. Falling back to HEARTBEAT.")
            return {
                "version": 1,
                "type": "HEARTBEAT",
                "node_id": self.node_id,
                "seq": self.seq,
                "sent_ts": sent_ts,
                "interval": self.interval,
                "priority": "NORMAL",
            }

    def send_report(self, payload: Dict[str, Any]) -> bool:
        """Encodes and sends payload over UDP socket."""
        try:
            raw = encode(payload)
            # Mark TOS/DSCP based on priority
            tos = TOS_EF_CRITICAL if payload.get("priority") == "CRITICAL" else TOS_BEST_EFFORT
            self._set_tos(tos)

            self.sock.sendto(raw, (self.server_ip, self.server_port))
            return True
        except (socket.gaierror, OSError) as exc:
            self.logger.rate_limited_warning("send_error", f"UDP send failed: {exc}")
            return False
        except ProtocolError as exc:
            self.logger.error(f"Protocol encoding error: {exc}")
            return False

    def run(self) -> None:
        """Main periodic reporting loop with monotonic scheduling."""
        self._init_socket()
        self.running = True
        self.logger.info(
            f"HealthAgent [{self.node_id}] started -> {self.server_ip}:{self.server_port} "
            f"(interval={self.interval}s, mode={self.mode})"
        )

        sent_count = 0
        next_tick = time.monotonic()

        try:
            while self.running:
                # Check crash simulation
                if self.fail_after is not None and sent_count >= self.fail_after:
                    self.logger.warning(f"Simulating node crash after {sent_count} packets sent.")
                    if self.recover_after is not None and self.recover_after > 0:
                        self.logger.info(f"Sleeping for {self.recover_after}s before recovering...")
                        time.sleep(self.recover_after)
                        self.logger.info("Agent recovered! Resuming reporting.")
                        # Reset crash trigger so it continues unless reconfigured
                        self.fail_after = None
                        next_tick = time.monotonic()
                    else:
                        self.logger.info("Abruptly stopping agent process (unrecoverable crash).")
                        break

                payload = self.build_payload()
                if self.send_report(payload):
                    sent_count += 1

                # Monotonic sleep to prevent clock drift
                next_tick += self.interval
                sleep_duration = next_tick - time.monotonic()
                if sleep_duration > 0:
                    time.sleep(sleep_duration)
                else:
                    # In case of drift/lag, realign next_tick
                    next_tick = time.monotonic()

        except KeyboardInterrupt:
            self.logger.info("Agent received interrupt signal. Shutting down...")
        finally:
            self.stop()

    def stop(self) -> None:
        """Closes socket and terminates running loop."""
        self.running = False
        if self.sock:
            try:
                self.sock.close()
            except Exception:
                pass
            self.sock = None
        self.logger.info(f"HealthAgent [{self.node_id}] stopped.")


def parse_args():
    parser = argparse.ArgumentParser(description="UDP Health-Reporting Agent")
    parser.add_argument("--id", required=True, dest="node_id", help="Node ID (e.g. h1)")
    parser.add_argument("--server", default="127.0.0.1", help="Monitoring server IP")
    parser.add_argument("--port", type=int, default=5005, help="Monitoring server UDP port")
    parser.add_argument("--interval", type=float, default=1.0, help="Reporting interval in seconds")
    parser.add_argument("--mode", choices=["real", "simulated"], default="real", help="Metrics collection mode")
    parser.add_argument("--sim-pattern", choices=["normal", "spike", "ramp-up", "constant-high"], default="normal")
    parser.add_argument("--fail-after", type=int, default=None, help="Simulate crash after N packets sent")
    parser.add_argument("--recover-after", type=float, default=None, help="Resume reporting after M seconds")
    parser.add_argument("--config", default="config.yaml", help="Path to configuration file")
    return parser.parse_args()


def main():
    args = parse_args()
    if args.interval <= 0:
        print(f"Error: --interval must be > 0, got {args.interval}", file=sys.stderr)
        sys.exit(1)

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

    def handle_signal(sig, frame):
        agent.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    agent.run()


if __name__ == "__main__":
    main()
