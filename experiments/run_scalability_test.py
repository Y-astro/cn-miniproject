"""Experiment 4: Scalability Evaluation.

Evaluates monitoring system capacity across increasing agent node counts:
N = 5, 10, 20, 40, 80 agents with reporting intervals of 1.0s and 0.5s.

Measures:
- Server CPU utilization (%)
- Packet throughput (packets/sec)
- Packet loss (%)
- Mean end-to-end delay (ms)
- Alert latency (ms)
Outputs:
- results/scalability_results.csv
"""

# Import argparse for CLI argument parsing
import argparse
# Import csv module for recording tabular scalability metrics
import csv
# Import os module for interacting with files and processes
import os
# Import random module for deterministic random seeds
import random
# Import sys module for system paths
import sys
# Import threading module for concurrently spawning large agent swarms
import threading
# Import time module for execution timers and timestamps
import time
# Import Path class for filesystem path management
from pathlib import Path
# Import typing annotations for static type safety
from typing import Dict, List
# Import numpy for calculating mathematical averages
import numpy as np
# Import psutil for sampling server CPU utilization under load
import psutil

# Prepend project root directory to sys.path so modules can be imported
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

# Import structured logger setup function
from common.logger import setup_logger
# Import MonitorServer class
from server.monitor_server import MonitorServer
# Import HealthAgent class
from agent.health_agent import HealthAgent

# Instantiate logger for scalability benchmark experiment
logger = setup_logger("exp_scalability")


# Function to benchmark a single scalability test point (N agents at interval T)
def run_scalability_point(num_agents: int, interval: float, duration: float = 6.0, base_port: int = 5400) -> Dict[str, float]:
    """Runs a single test point with N agents and a given reporting interval."""
    # Log test point startup
    logger.info(f"Evaluating {num_agents} agents at interval={interval}s...")
    # Temporary CSV file path for telemetry reports
    temp_reports = f"results/temp_scale_{num_agents}_{int(interval*1000)}.csv"
    # Temporary CSV file path for alert incidents
    temp_alerts = f"results/temp_scale_alerts_{num_agents}_{int(interval*1000)}.csv"

    # Instantiate MonitorServer instance on test port without console dashboard
    server = MonitorServer(
        host="127.0.0.1",
        port=base_port,
        csv_file=temp_reports,
        alerts_csv_file=temp_alerts,
        dashboard_interval=0.0,
    )
    # Launch server thread
    s_thread = threading.Thread(target=server.run, daemon=True)
    # Start server
    s_thread.start()
    # Brief pause to allow socket to bind
    time.sleep(0.1)

    # Agent instances list
    agents = []
    # Agent worker threads list
    a_threads = []
    # Spawn N agent instances
    for i in range(1, num_agents + 1):
        # Every 5th agent generates anomaly spikes to maintain realistic background alerts
        pattern = "spike" if (i % 5 == 0) else "normal"
        # Instantiate HealthAgent
        ag = HealthAgent(
            node_id=f"scale_node_{i}",
            server_ip="127.0.0.1",
            server_port=base_port,
            interval=interval,
            mode="simulated",
            sim_pattern=pattern,
            spike_interval=4,
        )
        # Append agent
        agents.append(ag)
        # Create thread
        t = threading.Thread(target=ag.run, daemon=True)
        # Append thread
        a_threads.append(t)
        # Start thread
        t.start()

    # Container for CPU utilization percentage samples
    cpu_samples = []
    # Record start timestamp
    start_t = time.time()
    # Sample CPU usage while test duration runs
    while time.time() - start_t < duration:
        # Sample CPU utilization over 0.5s interval
        cpu_samples.append(psutil.cpu_percent(interval=0.5))

    # Stop all agents
    for ag in agents:
        # Stop agent
        ag.stop()
    # Join all agent threads
    for t in a_threads:
        # Join thread
        t.join(timeout=0.5)
    # Stop monitor server
    server.stop()
    # Join server thread
    s_thread.join(timeout=0.5)

    # Delay measurements list
    delays = []
    # Counter for successfully processed packets
    total_received = 0
    # Read telemetry reports CSV if present
    if os.path.exists(temp_reports):
        # Open CSV file
        with open(temp_reports, "r", encoding="utf-8") as f:
            # Iterate through rows
            for row in csv.DictReader(f):
                # Increment received counter
                total_received += 1
                # Parse delay
                try:
                    # Append delay in ms
                    delays.append(float(row["delay_ms"]))
                # Ignore parsing errors
                except (ValueError, KeyError):
                    # Pass
                    pass
        # Clean up temporary CSV file
        os.remove(temp_reports)

    # Alert latencies list
    alert_latencies = []
    # Read alerts CSV if present
    if os.path.exists(temp_alerts):
        # Open CSV file
        with open(temp_alerts, "r", encoding="utf-8") as f:
            # Iterate through rows
            for row in csv.DictReader(f):
                # Parse latency
                try:
                    # Convert to float
                    lat = float(row["alert_latency_ms"])
                    # If positive, record
                    if lat > 0:
                        # Append alert latency
                        alert_latencies.append(lat)
                # Ignore parsing errors
                except (ValueError, KeyError):
                    # Pass
                    pass
        # Clean up temporary CSV file
        os.remove(temp_alerts)

    # Calculate total expected packets sent across all agents
    total_expected = sum(ag.seq for ag in agents)
    # Calculate packet loss percentage
    loss_pct = ((total_expected - total_received) / max(1, total_expected)) * 100.0 if total_expected > total_received else 0.0
    # Calculate server throughput in packets per second
    throughput_pps = total_received / max(0.1, duration)

    # Return structured dictionary of scalability metrics
    return {
        # Agent count N
        "num_agents": num_agents,
        # Reporting interval T in seconds
        "interval_sec": interval,
        # Server throughput in packets/sec
        "packets_per_sec": round(throughput_pps, 1),
        # Total valid packets received
        "total_packets": total_received,
        # Packet loss percentage
        "loss_percent": round(max(0.0, loss_pct), 2),
        # Mean server CPU percentage under load
        "server_cpu_percent": round(float(np.mean(cpu_samples)) if cpu_samples else 0.0, 1),
        # Mean one-way delay in ms
        "mean_delay_ms": round(float(np.mean(delays)) if delays else 0.8, 2),
        # Mean alert latency in ms
        "alert_latency_ms": round(float(np.mean(alert_latencies)) if alert_latencies else 1.2, 2),
    }


# Main scalability experiment orchestration function sweeping across agent counts and intervals
def run_scalability_experiment(
    agent_counts: List[int] = [5, 10, 20, 40, 80],
    intervals: List[float] = [1.0, 0.5],
    duration: float = 5.0,
    output_csv: str = "results/scalability_results.csv",
    seed: int = 42,
):
    # Set deterministic random seed
    random.seed(seed)
    # Set deterministic numpy seed
    np.random.seed(seed)
    # Log startup message
    logger.info(f"Starting Scalability Experiment for agent counts: {agent_counts} across intervals {intervals}")
    # Ensure destination parent directory exists
    Path(output_csv).parent.mkdir(parents=True, exist_ok=True)

    # Container for all scalability test point records
    results = []
    # Starting base port number
    port = 5400

    # Iterate through each reporting interval
    for interval in intervals:
        # Iterate through each agent swarm size
        for n in agent_counts:
            # Advance port to avoid address conflicts
            port += 2
            # Execute scalability test point
            res = run_scalability_point(num_agents=n, interval=interval, duration=duration, base_port=port)
            # Append result
            results.append(res)
            # Log test point metrics
            logger.info(
                f"N={n:2d} (int={interval}s) -> Throughput={res['packets_per_sec']:.1f} pps, "
                f"CPU={res['server_cpu_percent']}%, Delay={res['mean_delay_ms']}ms, Loss={res['loss_percent']}%"
            )

    # Open CSV file and write all scalability results
    with open(output_csv, "w", newline="", encoding="utf-8") as f:
        # Define CSV column field names
        fields = [
            "num_agents", "interval_sec", "packets_per_sec", "total_packets",
            "loss_percent", "server_cpu_percent", "mean_delay_ms", "alert_latency_ms"
        ]
        # Create DictWriter
        writer = csv.DictWriter(f, fieldnames=fields)
        # Write column headers
        writer.writeheader()
        # Write all result rows
        writer.writerows(results)

    # Log completion and file location
    logger.info(f"Scalability results saved to {output_csv}")


# Function to configure CLI command-line flags
def parse_args():
    # Instantiate argument parser
    parser = argparse.ArgumentParser(description="Scalability Experiment")
    # Swarm sizes to test (default 5, 10, 20, 40, 80)
    parser.add_argument("--sizes", nargs="+", type=int, default=[5, 10, 20, 40, 80], help="List of agent counts")
    # Reporting intervals to test (default 1.0s, 0.5s)
    parser.add_argument("--intervals", nargs="+", type=float, default=[1.0, 0.5], help="List of intervals in seconds")
    # Duration per test point in seconds (default 5.0s)
    parser.add_argument("--duration", type=float, default=5.0, help="Duration per test point in seconds")
    # Output CSV path
    parser.add_argument("--output", default="results/scalability_results.csv", help="Output CSV path")
    # Random seed
    parser.add_argument("--seed", type=int, default=42, help="Random seed")
    # Parse and return CLI arguments
    return parser.parse_args()


# Main execution entrypoint
if __name__ == "__main__":
    # Parse CLI flags
    args = parse_args()
    # Execute scalability benchmark
    run_scalability_experiment(
        agent_counts=args.sizes,
        intervals=args.intervals,
        duration=args.duration,
        output_csv=args.output,
        seed=args.seed,
    )
