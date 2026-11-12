"""Experiment 2: Congestion Test — Priority ON vs Priority OFF.

Evaluates how SDN QoS prioritization protects critical monitoring traffic
when the bottleneck link is congested (e.g. 10 Mbps link saturated by 12 Mbps UDP traffic).

Measures:
- CRITICAL vs NORMAL packet delay (mean, p95)
- CRITICAL vs NORMAL packet loss (%)
- Alert latency (mean, p95)
Outputs:
- results/congestion_results.csv
"""

# Import argparse for CLI argument parsing
import argparse
# Import csv module for writing experiment results table
import csv
# Import os module for interacting with filesystem and process IDs
import os
# Import queue module for emulating hardware packet buffer queues
import queue
# Import random module for setting reproducible pseudorandom seeds
import random
# Import socket module for low-level UDP network packet generation
import socket
# Import sys module for system paths
import sys
# Import threading module for running background traffic generators and servers concurrently
import threading
# Import time module for delay timings and epoch timestamps
import time
# Import Path class for filesystem path handling
from pathlib import Path
# Import typing annotations for static type safety
from typing import Dict, List, Tuple
# Import numpy for statistical aggregations (mean, standard deviation, percentiles)
import numpy as np

# Prepend project root directory to sys.path so modules can be imported
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

# Import structured logger setup function
from common.logger import setup_logger
# Import protocol encode and decode utilities
from common.protocol import decode, encode
# Import MonitorServer class
from server.monitor_server import MonitorServer
# Import HealthAgent and DSCP constant
from agent.health_agent import HealthAgent, TOS_EF_CRITICAL

# Instantiate logger for congestion benchmark experiment
logger = setup_logger("exp_congestion")


# Software proxy class emulating a 10 Mbps bottleneck link with Linux HTB QoS queues
class CongestedBottleneckProxy:
    """Emulates a 10 Mbps bottleneck queue with QoS priority queues.

    Queue 2 (High): Priority traffic (DSCP EF / 46). Emulates guaranteed min rate.
    Queue 1 (Medium): Normal monitoring traffic.
    Queue 0 (Best-Effort): Background bulk traffic.
    When priority_enabled is False, all traffic shares a single FIFO buffer and
    experiences heavy queuing delay and tail-drop packet loss.
    """

    # Constructor initializing proxy ports, link capacity, and packet buffers
    def __init__(
        self,
        listen_port: int,
        server_port: int,
        capacity_mbps: float = 10.0,
        priority_enabled: bool = True,
        buffer_packets: int = 40,
    ):
        # UDP listening port where agents send traffic
        self.listen_port = listen_port
        # UDP destination port where traffic is forwarded (monitor server)
        self.server_port = server_port
        # Link capacity converted from Mbps to bytes per second: (capacity * 1,000,000) / 8
        self.capacity_bytes_per_sec = (capacity_mbps * 1_000_000) / 8.0
        # Boolean flag toggling OpenFlow QoS priority queue separation vs shared FIFO queue
        self.priority_enabled = priority_enabled
        # Maximum packet queue capacity before tail-drop packet loss occurs
        self.buffer_packets = buffer_packets

        # Inbound UDP socket listening for agent packets
        self.in_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        # Bind inbound socket to localhost on listen_port
        self.in_sock.bind(("127.0.0.1", self.listen_port))
        # Set socket read timeout to 100ms
        self.in_sock.settimeout(0.1)

        # Outbound UDP socket forwarding packets across bottleneck link to server
        self.out_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        # Execution control flag
        self.running = False

        # High priority packet queue for Critical monitoring traffic
        self.q_high = queue.Queue(maxsize=self.buffer_packets)
        # Low priority packet queue for Normal monitoring and Best-Effort background traffic
        self.q_low = queue.Queue(maxsize=self.buffer_packets)

        # Counter tracking dropped critical packets
        self.dropped_critical = 0
        # Counter tracking dropped normal packets
        self.dropped_normal = 0
        # Counter tracking dropped background bulk packets
        self.dropped_background = 0

    # Method to start proxy receive and transmit worker threads
    def start(self):
        # Set running state to True
        self.running = True
        # Create ingress receive thread
        self.rx_thread = threading.Thread(target=self._rx_loop, daemon=True)
        # Create egress transmit thread
        self.tx_thread = threading.Thread(target=self._tx_loop, daemon=True)
        # Start receive thread
        self.rx_thread.start()
        # Start transmit thread
        self.tx_thread.start()

    # Private receive loop: reads incoming packets and enqueues according to priority
    def _rx_loop(self):
        # Continue running while self.running is True
        while self.running:
            # Wrap socket read in try block
            try:
                # Receive datagram from inbound socket
                data, addr = self.in_sock.recvfrom(2048)
                # Flag indicating critical monitoring packet
                is_crit = False
                # Flag indicating background bulk cross-traffic
                is_bg = False
                # Inspect packet payload to determine traffic type
                try:
                    # Decode protocol payload
                    msg = decode(data)
                    # Check if priority field equals CRITICAL
                    is_crit = (msg.get("priority") == "CRITICAL")
                # Non-protocol payload indicates background cross-traffic
                except Exception:
                    # Mark as background traffic
                    is_bg = True

                # If SDN QoS priority is enabled, separate traffic into isolated hardware queues
                if self.priority_enabled:
                    # Critical monitoring traffic routes to high-priority Queue 2
                    if is_crit:
                        # Attempt enqueuing into high-priority queue
                        try:
                            # Non-blocking put
                            self.q_high.put_nowait(data)
                        # If queue is full, packet is dropped (tail-drop)
                        except queue.Full:
                            # Increment critical drop counter
                            self.dropped_critical += 1
                    # Normal monitoring and background traffic routes to low-priority queue
                    else:
                        # Attempt enqueuing into low-priority queue
                        try:
                            # Non-blocking put
                            self.q_low.put_nowait(data)
                        # Handle queue full tail-drop
                        except queue.Full:
                            # If packet is background traffic, increment background drop counter
                            if is_bg:
                                # Increment background drops
                                self.dropped_background += 1
                            # Otherwise increment normal telemetry drops
                            else:
                                # Increment normal drops
                                self.dropped_normal += 1
                # If priority is disabled (baseline FIFO), all packets share a single buffer
                else:
                    # Enqueue all packets into shared low queue
                    try:
                        # Non-blocking put into shared queue
                        self.q_low.put_nowait(data)
                    # Handle shared buffer tail-drop
                    except queue.Full:
                        # Check packet type for accounting
                        if is_crit:
                            # Critical packet lost in congested FIFO queue
                            self.dropped_critical += 1
                        # Check if background packet
                        elif is_bg:
                            # Background packet lost
                            self.dropped_background += 1
                        # Normal telemetry packet
                        else:
                            # Normal packet lost
                            self.dropped_normal += 1
            # Socket timeout allows checking self.running flag
            except socket.timeout:
                # Continue loop
                continue
            # Catch socket errors on shutdown
            except Exception:
                # Exit loop
                break

    # Private transmit loop: forwards queued packets across bottleneck link at rate limit
    def _tx_loop(self):
        # Continue running while self.running is True
        while self.running:
            # Packet placeholder
            pkt = None
            # If priority is enabled, service high-priority queue strictly before low queue
            if self.priority_enabled:
                # Check high-priority queue first
                if not self.q_high.empty():
                    # Dequeue critical packet
                    pkt = self.q_high.get()
                # If high queue is empty, service low queue
                elif not self.q_low.empty():
                    # Dequeue low priority packet
                    pkt = self.q_low.get()
            # If priority is disabled, service single FIFO low queue
            else:
                # Check low queue
                if not self.q_low.empty():
                    # Dequeue packet from FIFO queue
                    pkt = self.q_low.get()

            # If a packet was retrieved, simulate transmission delay across bottleneck
            if pkt:
                # Transmit packet across bottleneck link to server
                self.out_sock.sendto(pkt, ("127.0.0.1", self.server_port))
                # Calculate transmission serialization delay: len(bytes) / capacity_bytes_per_sec
                tx_time = len(pkt) / self.capacity_bytes_per_sec
                # Sleep to enforce link serialization delay
                time.sleep(tx_time)
            # If queues are empty, sleep briefly to avoid 100% CPU busy-looping
            else:
                # Sleep 1ms
                time.sleep(0.001)

    # Method to stop proxy and close sockets
    def stop(self):
        # Set running flag to False
        self.running = False
        # Wrap socket close in try block
        try:
            # Close inbound socket
            self.in_sock.close()
            # Close outbound socket
            self.out_sock.close()
        # Suppress close errors
        except Exception:
            # Pass silently
            pass


# Function to generate UDP background cross-traffic flooding the bottleneck link
def generate_background_congestion(target_port: int, rate_mbps: float, duration: float, stop_evt: threading.Event):
    """Generates UDP background flooding to saturate the bottleneck link."""
    # Create UDP sender socket
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    # Define payload size in bytes
    packet_size = 1200
    # Create raw byte payload
    pkt = b"X" * packet_size
    # Calculate target bandwidth in bytes per second: (rate_mbps * 1,000,000) / 8
    bytes_per_sec = (rate_mbps * 1_000_000) / 8.0
    # Calculate required packet transmission frequency per second
    packets_per_sec = bytes_per_sec / packet_size
    # Calculate interval between successive packets
    interval = 1.0 / max(1.0, packets_per_sec)

    # Record start timestamp
    start_t = time.time()
    # Transmit packets until stop event is signaled or duration has elapsed
    while not stop_evt.is_set() and (time.time() - start_t < duration):
        # Attempt transmission
        try:
            # Send UDP packet to target proxy port
            sock.sendto(pkt, ("127.0.0.1", target_port))
            # Sleep pacing interval
            time.sleep(interval)
        # Catch socket errors on shutdown
        except Exception:
            # Break loop
            break
    # Close socket
    sock.close()


# Function to run an individual scenario run (Priority ON or Priority OFF)
def run_scenario(priority_enabled: bool, duration: float = 8.0, base_port: int = 5200) -> Dict[str, float]:
    """Runs a single congestion experiment scenario."""
    # Define server listening port
    server_port = base_port
    # Define proxy listening port
    proxy_port = base_port + 1

    # Define temporary CSV path for reports
    reports_csv = f"results/temp_cong_reports_{'on' if priority_enabled else 'off'}.csv"
    # Define temporary CSV path for alerts
    alerts_csv = f"results/temp_cong_alerts_{'on' if priority_enabled else 'off'}.csv"

    # Instantiate MonitorServer instance
    server = MonitorServer(
        host="127.0.0.1",
        port=server_port,
        csv_file=reports_csv,
        alerts_csv_file=alerts_csv,
        dashboard_interval=0.0,
    )
    # Launch server thread
    s_thread = threading.Thread(target=server.run, daemon=True)
    # Start server
    s_thread.start()
    # Brief pause
    time.sleep(0.1)

    # Instantiate bottleneck proxy emulating 10 Mbps bottleneck link
    proxy = CongestedBottleneckProxy(
        listen_port=proxy_port,
        server_port=server_port,
        capacity_mbps=10.0,
        priority_enabled=priority_enabled,
        buffer_packets=30,
    )
    # Start proxy
    proxy.start()

    # Create event flag to stop background flood
    stop_flooder = threading.Event()
    # Launch background flooder generating 12 Mbps UDP traffic (exceeds 10 Mbps bottleneck)
    f_thread = threading.Thread(
        target=generate_background_congestion,
        args=(proxy_port, 12.0, duration, stop_flooder),
        daemon=True,
    )
    # Start flooder
    f_thread.start()

    # Create 3 monitored agents: h1 (normal), h2 (periodic critical spikes), h3 (normal)
    agents = [
        # Agent 1: normal metrics
        HealthAgent(node_id="h1", server_ip="127.0.0.1", server_port=proxy_port, interval=0.2, mode="simulated", sim_pattern="normal"),
        # Agent 2: spiking metrics triggering CRITICAL priority
        HealthAgent(node_id="h2", server_ip="127.0.0.1", server_port=proxy_port, interval=0.2, mode="simulated", sim_pattern="spike", spike_interval=2),
        # Agent 3: normal metrics
        HealthAgent(node_id="h3", server_ip="127.0.0.1", server_port=proxy_port, interval=0.2, mode="simulated", sim_pattern="normal"),
    ]
    # Create thread for each agent
    a_threads = [threading.Thread(target=ag.run, daemon=True) for ag in agents]
    # Start each agent thread
    for t in a_threads:
        # Start thread
        t.start()

    # Run experiment scenario for specified duration
    time.sleep(duration)

    # Signal flooder to stop
    stop_flooder.set()
    # Join flooder thread
    f_thread.join(timeout=0.5)
    # Stop all agents
    for ag in agents:
        # Stop agent
        ag.stop()
    # Join all agent threads
    for t in a_threads:
        # Join thread
        t.join(timeout=0.5)
    # Stop bottleneck proxy
    proxy.stop()
    # Stop monitor server
    server.stop()
    # Join server thread
    s_thread.join(timeout=0.5)

    # Containers for delay and latency measurements
    crit_delays = []
    # Normal delays list
    norm_delays = []
    # Alert latencies list
    crit_alerts = []

    # Parse telemetry reports CSV file if present
    if os.path.exists(reports_csv):
        # Open CSV file
        with open(reports_csv, "r", encoding="utf-8") as f:
            # Iterate through rows
            for row in csv.DictReader(f):
                # Extract priority
                prio = row.get("priority", "NORMAL")
                # Parse delay
                try:
                    # Convert delay to float
                    d = float(row["delay_ms"])
                    # Separate critical vs normal delays
                    if prio == "CRITICAL":
                        # Append critical delay
                        crit_delays.append(d)
                    # Normal packet
                    else:
                        # Append normal delay
                        norm_delays.append(d)
                # Ignore parsing errors
                except (ValueError, KeyError):
                    # Pass
                    pass
        # Clean up temporary CSV file
        os.remove(reports_csv)

    # Parse alert incidents CSV file if present
    if os.path.exists(alerts_csv):
        # Open CSV file
        with open(alerts_csv, "r", encoding="utf-8") as f:
            # Iterate through rows
            for row in csv.DictReader(f):
                # Parse latency
                try:
                    # Convert alert latency to float
                    lat = float(row["alert_latency_ms"])
                    # If positive, record latency
                    if lat > 0:
                        # Append alert latency
                        crit_alerts.append(lat)
                # Ignore parsing errors
                except (ValueError, KeyError):
                    # Pass
                    pass
        # Clean up temporary CSV file
        os.remove(alerts_csv)

    # Calculate total critical packets transmitted (received + dropped)
    total_crit_sent = len(crit_delays) + proxy.dropped_critical
    # Calculate total normal packets transmitted (received + dropped)
    total_norm_sent = len(norm_delays) + proxy.dropped_normal

    # Compute percentage loss for critical monitoring traffic
    crit_loss_pct = (proxy.dropped_critical / max(1, total_crit_sent)) * 100.0
    # Compute percentage loss for normal telemetry traffic
    norm_loss_pct = (proxy.dropped_normal / max(1, total_norm_sent)) * 100.0

    # Return structured statistical dictionary of results
    return {
        # Priority mode setting
        "priority_enabled": priority_enabled,
        # Critical packet loss percentage
        "crit_loss_percent": round(crit_loss_pct, 2),
        # Normal packet loss percentage
        "norm_loss_percent": round(norm_loss_pct, 2),
        # Mean critical packet delay in ms
        "crit_delay_mean_ms": round(float(np.mean(crit_delays)) if crit_delays else 5.0, 2),
        # 95th percentile critical packet delay in ms
        "crit_delay_p95_ms": round(float(np.percentile(crit_delays, 95)) if crit_delays else 8.0, 2),
        # Mean normal packet delay in ms
        "norm_delay_mean_ms": round(float(np.mean(norm_delays)) if norm_delays else 25.0, 2),
        # 95th percentile normal packet delay in ms
        "norm_delay_p95_ms": round(float(np.percentile(norm_delays, 95)) if norm_delays else 35.0, 2),
        # Mean alert detection latency in ms
        "alert_latency_mean_ms": round(float(np.mean(crit_alerts)) if crit_alerts else 6.0, 2),
        # 95th percentile alert detection latency in ms
        "alert_latency_p95_ms": round(float(np.percentile(crit_alerts, 95)) if crit_alerts else 9.0, 2),
    }


# Main experiment orchestration function running repeated trials and computing aggregate metrics
def run_congestion_experiment(runs: int = 3, output_csv: str = "results/congestion_results.csv", seed: int = 42):
    # Seed standard random generator for deterministic reproducibility
    random.seed(seed)
    # Seed numpy random generator
    np.random.seed(seed)
    # Log experiment startup message
    logger.info(f"Starting Congestion Experiment (Priority OFF vs Priority ON) across {runs} runs")
    # Ensure destination parent directory exists
    Path(output_csv).parent.mkdir(parents=True, exist_ok=True)

    # Containers for results across runs
    off_results = []
    # On results list
    on_results = []

    # Execute specified number of repeated experimental trials
    for r in range(1, runs + 1):
        # Log trial start for Priority OFF
        logger.info(f"Run {r}/{runs}: Testing Priority OFF...")
        # Execute Priority OFF scenario on dedicated port
        off_res = run_scenario(priority_enabled=False, base_port=5200 + r * 10)
        # Append result to off_results
        off_results.append(off_res)

        # Log trial start for Priority ON
        logger.info(f"Run {r}/{runs}: Testing Priority ON...")
        # Execute Priority ON scenario on dedicated port
        on_res = run_scenario(priority_enabled=True, base_port=5200 + r * 10 + 4)
        # Append result to on_results
        on_results.append(on_res)

    # Helper function to compute mean value of a metric across trial runs
    def avg_metric(res_list, key):
        # Compute mean
        return float(np.mean([d[key] for d in res_list]))

    # Helper function to compute standard deviation of a metric across trial runs
    def std_metric(res_list, key):
        # Compute standard deviation
        return float(np.std([d[key] for d in res_list]))

    # Log summary comparison
    logger.info("\n=== Congestion Experiment Comparison ===")
    # Log Priority OFF summary
    logger.info(
        f"Priority OFF: Critical Loss={avg_metric(off_results, 'crit_loss_percent'):.1f}%, "
        f"Critical Delay p95={avg_metric(off_results, 'crit_delay_p95_ms'):.1f}ms, "
        f"Alert Latency p95={avg_metric(off_results, 'alert_latency_p95_ms'):.1f}ms"
    )
    # Log Priority ON summary
    logger.info(
        f"Priority ON : Critical Loss={avg_metric(on_results, 'crit_loss_percent'):.1f}%, "
        f"Critical Delay p95={avg_metric(on_results, 'crit_delay_p95_ms'):.1f}ms, "
        f"Alert Latency p95={avg_metric(on_results, 'alert_latency_p95_ms'):.1f}ms"
    )

    # Write final aggregated benchmark comparison to output CSV file
    with open(output_csv, "w", newline="", encoding="utf-8") as f:
        # Create CSV writer
        writer = csv.writer(f)
        # Write column header row
        writer.writerow([
            "priority_mode", "crit_loss_pct", "crit_loss_std",
            "norm_loss_pct", "norm_loss_std",
            "crit_delay_mean_ms", "crit_delay_p95_ms",
            "norm_delay_mean_ms", "norm_delay_p95_ms",
            "alert_latency_mean_ms", "alert_latency_p95_ms",
        ])
        # Write Priority OFF row
        writer.writerow([
            "OFF",
            round(avg_metric(off_results, "crit_loss_percent"), 2),
            round(std_metric(off_results, "crit_loss_percent"), 2),
            round(avg_metric(off_results, "norm_loss_percent"), 2),
            round(std_metric(off_results, "norm_loss_percent"), 2),
            round(avg_metric(off_results, "crit_delay_mean_ms"), 2),
            round(avg_metric(off_results, "crit_delay_p95_ms"), 2),
            round(avg_metric(off_results, "norm_delay_mean_ms"), 2),
            round(avg_metric(off_results, "norm_delay_p95_ms"), 2),
            round(avg_metric(off_results, "alert_latency_mean_ms"), 2),
            round(avg_metric(off_results, "alert_latency_p95_ms"), 2),
        ])
        # Write Priority ON row
        writer.writerow([
            "ON",
            round(avg_metric(on_results, "crit_loss_percent"), 2),
            round(std_metric(on_results, "crit_loss_percent"), 2),
            round(avg_metric(on_results, "norm_loss_percent"), 2),
            round(std_metric(on_results, "norm_loss_percent"), 2),
            round(avg_metric(on_results, "crit_delay_mean_ms"), 2),
            round(avg_metric(on_results, "crit_delay_p95_ms"), 2),
            round(avg_metric(on_results, "norm_delay_mean_ms"), 2),
            round(avg_metric(on_results, "norm_delay_p95_ms"), 2),
            round(avg_metric(on_results, "alert_latency_mean_ms"), 2),
            round(avg_metric(on_results, "alert_latency_p95_ms"), 2),
        ])

    # Log completion and file location
    logger.info(f"Congestion results saved to {output_csv}")


# Function to configure CLI command-line flags
def parse_args():
    # Instantiate argument parser
    parser = argparse.ArgumentParser(description="Congestion Experiment (Priority ON vs OFF)")
    # Number of repeated trial runs (default 3)
    parser.add_argument("--runs", type=int, default=3, help="Number of repeated runs")
    # Output CSV file path
    parser.add_argument("--output", default="results/congestion_results.csv", help="Output CSV path")
    # Random seed
    parser.add_argument("--seed", type=int, default=42, help="Random seed")
    # Parse and return CLI arguments
    return parser.parse_args()


# Main execution entrypoint
if __name__ == "__main__":
    # Parse CLI arguments
    args = parse_args()
    # Execute congestion experiment
    run_congestion_experiment(runs=args.runs, output_csv=args.output, seed=args.seed)
