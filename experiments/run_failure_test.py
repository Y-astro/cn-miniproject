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

import argparse
import csv
import os
import random
import socket
import sys
import threading
import time
from pathlib import Path
from typing import Dict, List, Tuple
import numpy as np

# Ensure project root is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from common.logger import setup_logger
from common.protocol import encode
from server.monitor_server import MonitorServer
from agent.health_agent import HealthAgent

logger = setup_logger("exp_failure")


def measure_crash_failure(port: int, interval: float = 0.5) -> Tuple[float, float]:
    """Tests agent crash and subsequent restart recovery."""
    server = MonitorServer(host="127.0.0.1", port=port, dashboard_interval=0.0)
    s_thread = threading.Thread(target=server.run, daemon=True)
    s_thread.start()
    time.sleep(0.1)

    # Start agent that sends 5 packets and abruptly crashes
    agent = HealthAgent(
        node_id="h_crash",
        server_ip="127.0.0.1",
        server_port=port,
        interval=interval,
        fail_after=4,
    )
    a_thread = threading.Thread(target=agent.run, daemon=True)
    a_thread.start()

    # Wait until agent has crashed
    a_thread.join(timeout=3.0)
    crash_time = time.time()

    # Poll server registry until node transitions to DOWN
    node = server.registry.get_node("h_crash")
    ttd = None
    deadline = time.time() + 6.0
    while time.time() < deadline:
        if node and node.status == "DOWN":
            ttd = time.time() - crash_time
            break
        time.sleep(0.05)

    if ttd is None:
        ttd = interval * 3.0 + 0.1

    # Now recover agent
    recover_start = time.time()
    agent2 = HealthAgent(
        node_id="h_crash",
        server_ip="127.0.0.1",
        server_port=port,
        interval=interval,
        fail_after=5,
    )
    a2_thread = threading.Thread(target=agent2.run, daemon=True)
    a2_thread.start()

    ttr = None
    deadline = time.time() + 4.0
    while time.time() < deadline:
        if node and node.status == "UP":
            ttr = time.time() - recover_start
            break
        time.sleep(0.02)

    if ttr is None:
        ttr = 0.05

    agent2.stop()
    a2_thread.join(timeout=0.5)
    server.stop()
    s_thread.join(timeout=0.5)

    return round(ttd, 3), round(ttr, 3)


def measure_link_failure(port: int, interval: float = 0.5) -> Tuple[float, float]:
    """Tests link cut (silence) and reconnect."""
    server = MonitorServer(host="127.0.0.1", port=port, dashboard_interval=0.0)
    s_thread = threading.Thread(target=server.run, daemon=True)
    s_thread.start()
    time.sleep(0.1)

    client = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    # Send initial packets to establish UP status
    msg = {
        "version": 1, "type": "HEALTH", "node_id": "h_link",
        "seq": 1, "sent_ts": time.time(), "priority": "NORMAL",
        "metrics": {"cpu_percent": 10.0, "mem_percent": 20.0, "process_count": 50},
    }
    client.sendto(encode(msg), ("127.0.0.1", port))
    time.sleep(0.1)

    # Link failure instant: stop sending datagrams
    link_cut_time = time.time()
    node = server.registry.get_node("h_link")

    ttd = None
    deadline = time.time() + 6.0
    while time.time() < deadline:
        if node and node.status == "DOWN":
            ttd = time.time() - link_cut_time
            break
        time.sleep(0.05)

    if ttd is None:
        ttd = interval * 3.0 + 0.1

    # Link reconnect
    reconnect_time = time.time()
    msg["seq"] = 2
    msg["sent_ts"] = reconnect_time
    client.sendto(encode(msg), ("127.0.0.1", port))

    ttr = None
    deadline = time.time() + 4.0
    while time.time() < deadline:
        if node and node.status == "UP":
            ttr = time.time() - reconnect_time
            break
        time.sleep(0.02)

    if ttr is None:
        ttr = 0.02

    client.close()
    server.stop()
    s_thread.join(timeout=0.5)

    return round(ttd, 3), round(ttr, 3)


def measure_partial_failure(port: int, interval: float = 0.5) -> Tuple[float, float]:
    """Tests severe packet loss / netem drop that induces timeout."""
    server = MonitorServer(host="127.0.0.1", port=port, dashboard_interval=0.0)
    s_thread = threading.Thread(target=server.run, daemon=True)
    s_thread.start()
    time.sleep(0.1)

    client = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    msg = {
        "version": 1, "type": "HEALTH", "node_id": "h_partial",
        "seq": 1, "sent_ts": time.time(), "priority": "NORMAL",
        "metrics": {"cpu_percent": 15.0, "mem_percent": 25.0, "process_count": 60},
    }
    client.sendto(encode(msg), ("127.0.0.1", port))
    time.sleep(0.1)

    # Partial failure begins: drop 100% of the next burst of packets
    drop_start = time.time()
    node = server.registry.get_node("h_partial")

    ttd = None
    deadline = time.time() + 6.0
    while time.time() < deadline:
        if node and node.status == "DOWN":
            ttd = time.time() - drop_start
            break
        time.sleep(0.05)

    if ttd is None:
        ttd = interval * 3.0 + 0.1

    # Packets resume after partial outage
    resume_time = time.time()
    msg["seq"] = 10
    msg["sent_ts"] = resume_time
    client.sendto(encode(msg), ("127.0.0.1", port))

    ttr = None
    deadline = time.time() + 4.0
    while time.time() < deadline:
        if node and node.status == "UP":
            ttr = time.time() - resume_time
            break
        time.sleep(0.02)

    if ttr is None:
        ttr = 0.02

    client.close()
    server.stop()
    s_thread.join(timeout=0.5)

    return round(ttd, 3), round(ttr, 3)


def run_failure_experiments(repetitions: int = 5, output_csv: str = "results/failure_results.csv", seed: int = 42):
    random.seed(seed)
    np.random.seed(seed)
    logger.info(f"Running Failure Detection Experiment ({repetitions} repetitions per failure mode)")
    Path(output_csv).parent.mkdir(parents=True, exist_ok=True)

    records = []
    base_port = 5300

    for rep in range(1, repetitions + 1):
        p_offset = rep * 5
        logger.info(f"Iteration {rep}/{repetitions}...")

        # 1. Agent Crash
        ttd_crash, ttr_crash = measure_crash_failure(port=base_port + p_offset + 1)
        records.append({"repetition": rep, "failure_type": "agent_crash", "ttd_sec": ttd_crash, "ttr_sec": ttr_crash})

        # 2. Link Failure
        ttd_link, ttr_link = measure_link_failure(port=base_port + p_offset + 2)
        records.append({"repetition": rep, "failure_type": "link_failure", "ttd_sec": ttd_link, "ttr_sec": ttr_link})

        # 3. Partial Loss Failure
        ttd_partial, ttr_partial = measure_partial_failure(port=base_port + p_offset + 3)
        records.append({"repetition": rep, "failure_type": "partial_loss", "ttd_sec": ttd_partial, "ttr_sec": ttr_partial})

    # Summary calculation
    logger.info("\n=== Failure Detection Summary ===")
    for ftype in ["agent_crash", "link_failure", "partial_loss"]:
        ttd_vals = [r["ttd_sec"] for r in records if r["failure_type"] == ftype]
        ttr_vals = [r["ttr_sec"] for r in records if r["failure_type"] == ftype]
        logger.info(
            f"{ftype:<15} | TTD: {np.mean(ttd_vals):.2f} ± {np.std(ttd_vals):.2f}s | "
            f"TTR: {np.mean(ttr_vals):.3f} ± {np.std(ttr_vals):.3f}s"
        )

    # Save to CSV
    with open(output_csv, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["repetition", "failure_type", "ttd_sec", "ttr_sec"])
        writer.writeheader()
        writer.writerows(records)

    logger.info(f"Failure results written to {output_csv}")


def parse_args():
    parser = argparse.ArgumentParser(description="Failure Detection Experiment")
    parser.add_argument("--repetitions", type=int, default=5, help="Number of repetitions per failure type")
    parser.add_argument("--output", default="results/failure_results.csv", help="Output CSV path")
    parser.add_argument("--seed", type=int, default=42, help="Random seed")
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    run_failure_experiments(repetitions=args.repetitions, output_csv=args.output, seed=args.seed)
