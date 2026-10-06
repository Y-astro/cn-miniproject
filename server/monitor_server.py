"""Centralized UDP monitoring server with CSV logging, dashboard, and failure detection."""

import argparse
import csv
import os
import select
import signal
import socket
import sys
import threading
import time
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

# Ensure project root is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from common.config_loader import load_config
from common.logger import setup_logger
from common.protocol import decode, ProtocolError
from server.node_registry import NodeRegistry
from server.alert_engine import AlertEngine, AlertRecord


class MonitorServer:
    """Centralized UDP health monitoring server."""

    def __init__(
        self,
        host: str = "0.0.0.0",
        port: int = 5005,
        config_path: str = "config.yaml",
        csv_file: Optional[str] = None,
        alerts_csv_file: Optional[str] = None,
        dashboard_interval: float = 2.0,
    ):
        self.host = host
        self.port = int(port)
        self.dashboard_interval = dashboard_interval

        # Load and validate config
        self.config = load_config(config_path) if os.path.isfile(config_path) else {}
        server_cfg = self.config.get("server", {})

        self.buffer_size = server_cfg.get("buffer_size", 2048)
        self.max_delay_clamp_ms = server_cfg.get("max_delay_clamp_ms", 10000.0)

        # File paths
        self.csv_path = csv_file or server_cfg.get("csv_file", "results/server_reports.csv")
        self.alerts_csv_path = alerts_csv_file or "results/server_alerts.csv"

        self.logger = setup_logger("monitor_server")
        self.registry = NodeRegistry(
            default_interval=self.config.get("agent", {}).get("default_interval", 1.0),
            silence_multiplier=self.config.get("thresholds", {}).get("silence_multiplier", 3.0),
            event_callback=self._on_registry_event,
        )
        self.alert_engine = AlertEngine(self.config) if self.config else None

        self.sock: Optional[socket.socket] = None
        self.running = False
        self.bad_packet_count = 0
        self.valid_packet_count = 0

        # CSV writers and file handles
        self._csv_lock = threading.Lock()
        self._reports_f = None
        self._reports_writer = None
        self._alerts_f = None
        self._alerts_writer = None

        self._init_csv_writers()

    def _init_csv_writers(self) -> None:
        """Initializes CSV log files with headers."""
        reports_p = Path(self.csv_path)
        reports_p.parent.mkdir(parents=True, exist_ok=True)
        self._reports_f = open(reports_p, "w", newline="", encoding="utf-8")
        self._reports_writer = csv.writer(self._reports_f)
        self._reports_writer.writerow([
            "node_id", "seq", "sent_ts", "recv_ts", "delay_ms",
            "cpu_percent", "mem_percent", "process_count", "priority",
        ])
        self._reports_f.flush()

        alerts_p = Path(self.alerts_csv_path)
        alerts_p.parent.mkdir(parents=True, exist_ok=True)
        self._alerts_f = open(alerts_p, "w", newline="", encoding="utf-8")
        self._alerts_writer = csv.writer(self._alerts_f)
        self._alerts_writer.writerow([
            "alert_id", "node_id", "metric", "value", "threshold",
            "severity", "trigger_ts", "detect_ts", "alert_latency_ms",
        ])
        self._alerts_f.flush()

    def _on_registry_event(self, event_type: str, node_id: str, details: Dict[str, Any]) -> None:
        """Callback for node lifecycle events (down, recovered, etc.)."""
        if event_type == "NODE_DOWN":
            self.logger.warning(
                f"[NODE FAILURE] Node '{node_id}' is DOWN! "
                f"(Silence: {details.get('silence_sec')}s > limit {details.get('limit_sec')}s)"
            )
            # Record silence alert
            if self._alerts_writer:
                with self._csv_lock:
                    now = time.time()
                    self._alerts_writer.writerow([
                        f"silence_{node_id}", node_id, "node_silence",
                        details.get("silence_sec", 0.0), details.get("limit_sec", 0.0),
                        "CRITICAL", now, now, 0.0,
                    ])
                    self._alerts_f.flush()
        elif event_type == "NODE_RECOVERED":
            self.logger.info(f"[NODE RECOVERY] Node '{node_id}' has RECOVERED and is UP!")
        elif event_type == "NODE_REGISTERED":
            self.logger.info(f"[NODE REGISTERED] New node '{node_id}' detected.")

    def start_socket(self) -> None:
        """Binds the UDP socket to the specified host and port."""
        try:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.sock.bind((self.host, self.port))
            self.sock.setblocking(False)
            self.logger.info(f"MonitorServer socket bound to {self.host}:{self.port}")
        except OSError as exc:
            self.logger.error(f"Failed to bind socket on {self.host}:{self.port} - Port already in use: {exc}")
            raise

    def process_datagram(self, data: bytes, addr: Tuple[str, int], recv_ts: float) -> Optional[Dict[str, Any]]:
        """Processes a single incoming datagram safely."""
        try:
            msg = decode(data, max_bytes=self.buffer_size)
        except ProtocolError as exc:
            self.bad_packet_count += 1
            self.logger.rate_limited_warning("bad_packet", f"Dropped malformed packet from {addr}: {exc}")
            return None
        except Exception as exc:
            self.bad_packet_count += 1
            self.logger.rate_limited_warning("bad_packet_unexpected", f"Error decoding packet from {addr}: {exc}")
            return None

        self.valid_packet_count += 1
        node_id = msg["node_id"]
        seq = msg["seq"]
        sent_ts = msg["sent_ts"]
        priority = msg.get("priority", "NORMAL")
        metrics = msg.get("metrics", {})

        # Compute one-way delay (clamped)
        raw_delay_ms = (recv_ts - sent_ts) * 1000.0
        if raw_delay_ms < 0.0:
            # Clock jump or sync mismatch: clamp and flag
            self.logger.rate_limited_warning("clock_skew", f"Negative delay detected from {node_id} ({raw_delay_ms:.2f}ms). Clamping to 0.0.")
            delay_ms = 0.0
        else:
            delay_ms = min(raw_delay_ms, self.max_delay_clamp_ms)

        # Update node registry
        interval = msg.get("interval")
        self.registry.process_packet(
            node_id=node_id,
            seq=seq,
            sent_ts=sent_ts,
            recv_ts=recv_ts,
            metrics=metrics,
            interval=interval,
        )

        # Evaluate alerts
        if self.alert_engine and metrics:
            node = self.registry.get_node(node_id)
            loss_pct = node.loss_percent if node else 0.0
            alerts = self.alert_engine.evaluate_report(
                node_id=node_id,
                metrics=metrics,
                trigger_ts=sent_ts,
                packet_loss_percent=loss_pct,
                now=recv_ts,
            )
            for alert in alerts:
                self.logger.warning(
                    f"[ALERT] [{alert.severity}] Node '{node_id}' {alert.metric}={alert.value} "
                    f"(threshold={alert.threshold}) Latency={alert.alert_latency_ms:.1f}ms"
                )
                with self._csv_lock:
                    self._alerts_writer.writerow([
                        alert.alert_id, alert.node_id, alert.metric, alert.value,
                        alert.threshold, alert.severity, alert.trigger_ts,
                        alert.detect_ts, round(alert.alert_latency_ms, 2),
                    ])
                    self._alerts_f.flush()

        # Write report to CSV
        cpu = metrics.get("cpu_percent", 0.0) if metrics else 0.0
        mem = metrics.get("mem_percent", 0.0) if metrics else 0.0
        procs = metrics.get("process_count", 0) if metrics else 0
        with self._csv_lock:
            self._reports_writer.writerow([
                node_id, seq, sent_ts, recv_ts, round(delay_ms, 2),
                cpu, mem, procs, priority,
            ])

        return msg

    def display_dashboard(self) -> None:
        """Prints a periodic dashboard of active nodes and statistics."""
        if not self.registry.nodes:
            return

        lines = [
            "\n" + "=" * 78,
            f"HEALTH MONITOR DASHBOARD | Valid Packets: {self.valid_packet_count} | Dropped: {self.bad_packet_count}",
            "-" * 78,
            f"{'Node ID':<10} {'Status':<8} {'Loss %':<10} {'Avg Delay':<12} {'CPU %':<8} {'Mem %':<8} {'Procs':<8}",
            "-" * 78,
        ]
        for node_id, node in sorted(self.registry.nodes.items()):
            m = node.last_metrics
            cpu = m.get("cpu_percent", "-")
            mem = m.get("mem_percent", "-")
            procs = m.get("process_count", "-")
            lines.append(
                f"{node_id:<10} {node.status:<8} {node.loss_percent:<10.1f} "
                f"{node.avg_delay_ms:<12.1f} {str(cpu):<8} {str(mem):<8} {str(procs):<8}"
            )
        lines.append("=" * 78 + "\n")
        sys.stdout.write("\n".join(lines) + "\n")
        sys.stdout.flush()

    def run(self) -> None:
        """Main server receive loop using select for non-blocking I/O."""
        self.start_socket()
        self.running = True
        self.logger.info("MonitorServer loop running. Press Ctrl+C to stop.")

        last_dashboard_time = time.monotonic()
        last_liveness_check = time.monotonic()

        try:
            while self.running:
                readable, _, _ = select.select([self.sock], [], [], 0.1)
                recv_ts = time.time()

                if readable:
                    while self.running and self.sock:
                        try:
                            sock = self.sock
                            if sock is None:
                                break
                            data, addr = sock.recvfrom(self.buffer_size)
                            self.process_datagram(data, addr, recv_ts)
                        except (BlockingIOError, socket.error):
                            break

                now_mono = time.monotonic()

                # Periodic node silence check (every 0.5s)
                if now_mono - last_liveness_check >= 0.5:
                    self.registry.check_liveness(current_ts=recv_ts)
                    last_liveness_check = now_mono

                # Periodic dashboard output
                if self.dashboard_interval > 0 and (now_mono - last_dashboard_time >= self.dashboard_interval):
                    self.display_dashboard()
                    # Also flush CSVs periodically
                    with self._csv_lock:
                        if self._reports_f:
                            self._reports_f.flush()
                        if self._alerts_f:
                            self._alerts_f.flush()
                    last_dashboard_time = now_mono

        except KeyboardInterrupt:
            self.logger.info("Server received interrupt signal. Shutting down...")
        finally:
            self.stop()

    def stop(self) -> None:
        """Stops server, closes socket, and flushes CSV files."""
        self.running = False
        if self.sock:
            try:
                self.sock.close()
            except Exception:
                pass
            self.sock = None

        with self._csv_lock:
            if self._reports_f and not self._reports_f.closed:
                try:
                    self._reports_f.flush()
                    self._reports_f.close()
                except Exception:
                    pass
            if self._alerts_f and not self._alerts_f.closed:
                try:
                    self._alerts_f.flush()
                    self._alerts_f.close()
                except Exception:
                    pass

        self.logger.info("MonitorServer stopped cleanly.")


def parse_args():
    parser = argparse.ArgumentParser(description="Centralized UDP Health Monitoring Server")
    parser.add_argument("--host", default="0.0.0.0", help="Host address to bind")
    parser.add_argument("--port", type=int, default=5005, help="UDP port to bind")
    parser.add_argument("--config", default="config.yaml", help="Configuration file path")
    parser.add_argument("--csv", default=None, help="Output CSV path for reports")
    parser.add_argument("--dashboard-interval", type=float, default=2.0, help="Interval for console dashboard (0 to disable)")
    return parser.parse_args()


def main():
    args = parse_args()
    if not (1 <= args.port <= 65535):
        print(f"Error: Invalid port {args.port}", file=sys.stderr)
        sys.exit(1)

    server = MonitorServer(
        host=args.host,
        port=args.port,
        config_path=args.config,
        csv_file=args.csv,
        dashboard_interval=args.dashboard_interval,
    )

    def handle_signal(sig, frame):
        server.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    server.run()


if __name__ == "__main__":
    main()
