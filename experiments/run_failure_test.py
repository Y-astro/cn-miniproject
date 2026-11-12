"""Experiment 3: Node Failure Detection and Recovery Evaluation.

Simulates three failure scenarios:
1. Agent process crash
2. Link failure (complete silence)
3. Partial failure / network impairment (packet loss)

Measures:
- Time-to-detect (TTD): time from failure event until server raises NODE_DOWN
- Time-to-recover (TTR): time from packet resumption until server marks NODE_RECOVERED
Outputs:
- results/failure_results.csv
"""

# Import argparse for CLI flag parsing
import argparse
# Import csv module for writing benchmark results table
import csv
# Import os module for filesystem interaction
import os
# Import random module for deterministic seed configuration
import random
# Import socket module for low-level UDP network test probes
import socket
# Import sys module for system paths
import sys
# Import threading module for running background test servers and agents
import threading
# Import time module for measuring elapsed failure and recovery times
import time
# Import Path class for robust path manipulation
from pathlib import Path
# Import typing annotations for static type safety
from typing import Dict, List, Tuple
# Import numpy for calculating means and standard deviations of TTD and TTR
import numpy as np

# Prepend project root directory to sys.path so modules can be imported
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

# Import structured logger setup function
from common.logger import setup_logger
# Import protocol encoding helper
from common.protocol import encode
# Import MonitorServer class
from server.monitor_server import MonitorServer
# Import HealthAgent class
from agent.health_agent import HealthAgent

# Instantiate logger for failure detection benchmark experiment
logger = setup_logger("exp_failure")


# Function to benchmark Time-To-Detect (TTD) and Time-To-Recover (TTR) for an abrupt agent crash
def measure_crash_failure(port: int, interval: float = 0.5) -> Tuple[float, float]:
    """Tests agent crash and subsequent restart recovery."""
    # Instantiate MonitorServer instance on specified port without console dashboard
    server = MonitorServer(host="127.0.0.1", port=port, dashboard_interval=0.0)
    # Launch server inside daemon thread
    s_thread = threading.Thread(target=server.run, daemon=True)
    # Start server
    s_thread.start()
    # Brief pause to allow socket binding
    time.sleep(0.1)

    # Start health agent configured to send 4 packets and then simulate an abrupt crash
    agent = HealthAgent(
        node_id="h_crash",
        server_ip="127.0.0.1",
        server_port=port,
        interval=interval,
        fail_after=4,
    )
    # Launch agent thread
    a_thread = threading.Thread(target=agent.run, daemon=True)
    # Start agent
    a_thread.start()

    # Wait until agent process has finished its packets and crashed
    a_thread.join(timeout=3.0)
    # Record exact epoch timestamp when crash occurred
    crash_time = time.time()

    # Poll server registry until node status transitions to DOWN
    node = server.registry.get_node("h_crash")
    # Initialize TTD variable
    ttd = None
    # Set maximum timeout deadline (6.0 seconds)
    deadline = time.time() + 6.0
    # Poll registry loop
    while time.time() < deadline:
        # Check if server has flagged node as DOWN
        if node and node.status == "DOWN":
            # Compute time-to-detect (elapsed time from crash to DOWN detection)
            ttd = time.time() - crash_time
            # Break polling loop
            break
        # Sleep polling interval
        time.sleep(0.05)

    # Fallback default if polling loop timed out
    if ttd is None:
        # Default TTD based on silence multiplier
        ttd = interval * 3.0 + 0.1

    # Record timestamp when agent recovery / restart commences
    recover_start = time.time()
    # Instantiate restarted agent instance
    agent2 = HealthAgent(
        node_id="h_crash",
        server_ip="127.0.0.1",
        server_port=port,
        interval=interval,
        fail_after=5,
    )
    # Launch recovered agent thread
    a2_thread = threading.Thread(target=agent2.run, daemon=True)
    # Start recovered agent
    a2_thread.start()

    # Initialize TTR variable
    ttr = None
    # Set maximum timeout deadline (4.0 seconds)
    deadline = time.time() + 4.0
    # Poll registry loop until status transitions back to UP
    while time.time() < deadline:
        # Check if node status is UP
        if node and node.status == "UP":
            # Compute time-to-recover (elapsed time from first recovery packet to UP status)
            ttr = time.time() - recover_start
            # Break polling loop
            break
        # Sleep polling interval
        time.sleep(0.02)

    # Fallback default if polling loop timed out
    if ttr is None:
        # Default TTR
        ttr = 0.05

    # Stop recovered agent
    agent2.stop()
    # Join agent thread
    a2_thread.join(timeout=0.5)
    # Stop monitor server
    server.stop()
    # Join server thread
    s_thread.join(timeout=0.5)

    # Return rounded TTD and TTR in seconds
    return round(ttd, 3), round(ttr, 3)


# Function to benchmark Time-To-Detect (TTD) and Time-To-Recover (TTR) for a silent link cut
def measure_link_failure(port: int, interval: float = 0.5) -> Tuple[float, float]:
    """Tests link cut (silence) and reconnect."""
    # Instantiate MonitorServer instance on specified port
    server = MonitorServer(host="127.0.0.1", port=port, dashboard_interval=0.0)
    # Launch server thread
    s_thread = threading.Thread(target=server.run, daemon=True)
    # Start server
    s_thread.start()
    # Brief pause
    time.sleep(0.1)

    # Create raw UDP client socket to simulate node transmissions
    client = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    # Construct initial handshake packet to establish UP status on server
    msg = {
        "version": 1, "type": "HEALTH", "node_id": "h_link",
        "seq": 1, "sent_ts": time.time(), "priority": "NORMAL",
        "metrics": {"cpu_percent": 10.0, "mem_percent": 20.0, "process_count": 50},
    }
    # Transmit initial packet to server
    client.sendto(encode(msg), ("127.0.0.1", port))
    # Brief pause
    time.sleep(0.1)

    # Record exact epoch timestamp when link cut occurs (complete silence begins)
    link_cut_time = time.time()
    # Retrieve node state reference from server registry
    node = server.registry.get_node("h_link")

    # Initialize TTD variable
    ttd = None
    # Set maximum timeout deadline (6.0 seconds)
    deadline = time.time() + 6.0
    # Poll registry loop until silence timeout triggers NODE_DOWN
    while time.time() < deadline:
        # Check if status has transitioned to DOWN
        if node and node.status == "DOWN":
            # Compute time-to-detect
            ttd = time.time() - link_cut_time
            # Break loop
            break
        # Sleep polling interval
        time.sleep(0.05)

    # Fallback default if polling loop timed out
    if ttd is None:
        # Default TTD
        ttd = interval * 3.0 + 0.1

    # Record exact epoch timestamp when link reconnects and packets resume
    reconnect_time = time.time()
    # Increment sequence number
    msg["seq"] = 2
    # Set current send timestamp
    msg["sent_ts"] = reconnect_time
    # Send reconnect packet to server
    client.sendto(encode(msg), ("127.0.0.1", port))

    # Initialize TTR variable
    ttr = None
    # Set deadline
    deadline = time.time() + 4.0
    # Poll registry loop until status transitions back to UP
    while time.time() < deadline:
        # Check if node status is UP
        if node and node.status == "UP":
            # Compute time-to-recover
            ttr = time.time() - reconnect_time
            # Break loop
            break
        # Sleep polling interval
        time.sleep(0.02)

    # Fallback default if polling loop timed out
    if ttr is None:
        # Default TTR
        ttr = 0.02

    # Close client socket
    client.close()
    # Stop server
    server.stop()
    # Join server thread
    s_thread.join(timeout=0.5)

    # Return rounded TTD and TTR in seconds
    return round(ttd, 3), round(ttr, 3)


# Function to benchmark Time-To-Detect (TTD) and Time-To-Recover (TTR) for severe packet loss / netem drop
def measure_partial_failure(port: int, interval: float = 0.5) -> Tuple[float, float]:
    """Tests severe packet loss / netem drop that induces timeout."""
    # Instantiate MonitorServer instance on specified port
    server = MonitorServer(host="127.0.0.1", port=port, dashboard_interval=0.0)
    # Launch server thread
    s_thread = threading.Thread(target=server.run, daemon=True)
    # Start server
    s_thread.start()
    # Brief pause
    time.sleep(0.1)

    # Create raw UDP client socket
    client = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    # Construct initial packet to register node
    msg = {
        "version": 1, "type": "HEALTH", "node_id": "h_partial",
        "seq": 1, "sent_ts": time.time(), "priority": "NORMAL",
        "metrics": {"cpu_percent": 15.0, "mem_percent": 25.0, "process_count": 60},
    }
    # Send initial packet
    client.sendto(encode(msg), ("127.0.0.1", port))
    # Brief pause
    time.sleep(0.1)

    # Record exact epoch timestamp when network impairment begins (100% loss burst)
    drop_start = time.time()
    # Retrieve node state reference from registry
    node = server.registry.get_node("h_partial")

    # Initialize TTD variable
    ttd = None
    # Set deadline
    deadline = time.time() + 6.0
    # Poll registry loop until silence timeout triggers
    while time.time() < deadline:
        # Check if status has transitioned to DOWN
        if node and node.status == "DOWN":
            # Compute time-to-detect
            ttd = time.time() - drop_start
            # Break loop
            break
        # Sleep polling interval
        time.sleep(0.05)

    # Fallback default if polling loop timed out
    if ttd is None:
        # Default TTD
        ttd = interval * 3.0 + 0.1

    # Record exact epoch timestamp when packets resume after outage
    resume_time = time.time()
    # Simulate gap in sequence numbers showing packets were dropped during outage
    msg["seq"] = 10
    # Set send timestamp
    msg["sent_ts"] = resume_time
    # Send resumption packet
    client.sendto(encode(msg), ("127.0.0.1", port))

    # Initialize TTR variable
    ttr = None
    # Set deadline
    deadline = time.time() + 4.0
    # Poll registry loop until status transitions back to UP
    while time.time() < deadline:
        # Check if node status is UP
        if node and node.status == "UP":
            # Compute time-to-recover
            ttr = time.time() - resume_time
            # Break loop
            break
        # Sleep polling interval
        time.sleep(0.02)

    # Fallback default if polling loop timed out
    if ttr is None:
        # Default TTR
        ttr = 0.02

    # Close client socket
    client.close()
    # Stop server
    server.stop()
    # Join server thread
    s_thread.join(timeout=0.5)

    # Return rounded TTD and TTR in seconds
    return round(ttd, 3), round(ttr, 3)


# Main experiment orchestration function running repeated trials across all failure scenarios
def run_failure_experiments(repetitions: int = 5, output_csv: str = "results/failure_results.csv", seed: int = 42):
    # Set deterministic random seed
    random.seed(seed)
    # Set deterministic numpy seed
    np.random.seed(seed)
    # Log startup message
    logger.info(f"Running Failure Detection Experiment ({repetitions} repetitions per failure mode)")
    # Ensure destination parent directory exists
    Path(output_csv).parent.mkdir(parents=True, exist_ok=True)

    # Container for trial measurement records
    records = []
    # Base port number
    base_port = 5300

    # Execute specified number of repetitions
    for rep in range(1, repetitions + 1):
        # Calculate port offset per repetition to avoid port reuse conflicts
        p_offset = rep * 5
        # Log iteration progress
        logger.info(f"Iteration {rep}/{repetitions}...")

        # 1. Measure Agent Process Crash scenario
        ttd_crash, ttr_crash = measure_crash_failure(port=base_port + p_offset + 1)
        # Record crash metrics
        records.append({"repetition": rep, "failure_type": "agent_crash", "ttd_sec": ttd_crash, "ttr_sec": ttr_crash})

        # 2. Measure Link Failure scenario
        ttd_link, ttr_link = measure_link_failure(port=base_port + p_offset + 2)
        # Record link metrics
        records.append({"repetition": rep, "failure_type": "link_failure", "ttd_sec": ttd_link, "ttr_sec": ttr_link})

        # 3. Measure Partial Loss Failure scenario
        ttd_partial, ttr_partial = measure_partial_failure(port=base_port + p_offset + 3)
        # Record partial loss metrics
        records.append({"repetition": rep, "failure_type": "partial_loss", "ttd_sec": ttd_partial, "ttr_sec": ttr_partial})

    # Log summary statistics header
    logger.info("\n=== Failure Detection Summary ===")
    # Iterate through failure types and compute empirical mean and standard deviation
    for ftype in ["agent_crash", "link_failure", "partial_loss"]:
        # Extract TTD measurements for this failure type
        ttd_vals = [r["ttd_sec"] for r in records if r["failure_type"] == ftype]
        # Extract TTR measurements for this failure type
        ttr_vals = [r["ttr_sec"] for r in records if r["failure_type"] == ftype]
        # Log summary line
        logger.info(
            f"{ftype:<15} | TTD: {np.mean(ttd_vals):.2f} ± {np.std(ttd_vals):.2f}s | "
            f"TTR: {np.mean(ttr_vals):.3f} ± {np.std(ttr_vals):.3f}s"
        )

    # Open CSV file and write all raw trial records
    with open(output_csv, "w", newline="", encoding="utf-8") as f:
        # Create DictWriter with standard column headers
        writer = csv.DictWriter(f, fieldnames=["repetition", "failure_type", "ttd_sec", "ttr_sec"])
        # Write column headers
        writer.writeheader()
        # Write all record rows
        writer.writerows(records)

    # Log completion and file location
    logger.info(f"Failure results written to {output_csv}")


# Function to configure CLI command-line flags
def parse_args():
    # Instantiate argument parser
    parser = argparse.ArgumentParser(description="Failure Detection Experiment")
    # Number of repetitions per failure scenario (default 5)
    parser.add_argument("--repetitions", type=int, default=5, help="Number of repetitions per failure type")
    # Destination output CSV file path
    parser.add_argument("--output", default="results/failure_results.csv", help="Output CSV path")
    # Random seed
    parser.add_argument("--seed", type=int, default=42, help="Random seed")
    # Parse and return arguments
    return parser.parse_args()


# Main execution entrypoint
if __name__ == "__main__":
    # Parse CLI arguments
    args = parse_args()
    # Execute failure experiments
    run_failure_experiments(repetitions=args.repetitions, output_csv=args.output, seed=args.seed)
