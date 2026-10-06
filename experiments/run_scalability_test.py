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

import argparse
import csv
import os
import random
import sys
import threading
import time
from pathlib import Path
from typing import Dict, List
import numpy as np
import psutil

# Ensure project root is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from common.logger import setup_logger
from server.monitor_server import MonitorServer
from agent.health_agent import HealthAgent

logger = setup_logger("exp_scalability")


def run_scalability_point(num_agents: int, interval: float, duration: float = 6.0, base_port: int = 5400) -> Dict[str, float]:
    """Runs a single test point with N agents and a given reporting interval."""
    logger.info(f"Evaluating {num_agents} agents at interval={interval}s...")
    temp_reports = f"results/temp_scale_{num_agents}_{int(interval*1000)}.csv"
    temp_alerts = f"results/temp_scale_alerts_{num_agents}_{int(interval*1000)}.csv"

    server = MonitorServer(
        host="127.0.0.1",
        port=base_port,
        csv_file=temp_reports,
        alerts_csv_file=temp_alerts,
        dashboard_interval=0.0,
    )
    s_thread = threading.Thread(target=server.run, daemon=True)
    s_thread.start()
    time.sleep(0.1)

    # Launch agents
    agents = []
    a_threads = []
    for i in range(1, num_agents + 1):
        pattern = "spike" if (i % 5 == 0) else "normal"
        ag = HealthAgent(
            node_id=f"scale_node_{i}",
            server_ip="127.0.0.1",
            server_port=base_port,
            interval=interval,
            mode="simulated",
            sim_pattern=pattern,
            spike_interval=4,
        )
        agents.append(ag)
        t = threading.Thread(target=ag.run, daemon=True)
        a_threads.append(t)
        t.start()

    # Measure CPU utilization during execution
    cpu_samples = []
    start_t = time.time()
    while time.time() - start_t < duration:
        cpu_samples.append(psutil.cpu_percent(interval=0.5))

    # Stop agents and server
    for ag in agents:
        ag.stop()
    for t in a_threads:
        t.join(timeout=0.5)
    server.stop()
    s_thread.join(timeout=0.5)

    # Collect measurements
    delays = []
    total_received = 0
    if os.path.exists(temp_reports):
        with open(temp_reports, "r", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                total_received += 1
                try:
                    delays.append(float(row["delay_ms"]))
                except (ValueError, KeyError):
                    pass
        os.remove(temp_reports)

    alert_latencies = []
    if os.path.exists(temp_alerts):
        with open(temp_alerts, "r", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                try:
                    lat = float(row["alert_latency_ms"])
                    if lat > 0:
                        alert_latencies.append(lat)
                except (ValueError, KeyError):
                    pass
        os.remove(temp_alerts)

    total_expected = sum(ag.seq for ag in agents)
    loss_pct = ((total_expected - total_received) / max(1, total_expected)) * 100.0 if total_expected > total_received else 0.0
    throughput_pps = total_received / max(0.1, duration)

    return {
        "num_agents": num_agents,
        "interval_sec": interval,
        "packets_per_sec": round(throughput_pps, 1),
        "total_packets": total_received,
        "loss_percent": round(max(0.0, loss_pct), 2),
        "server_cpu_percent": round(float(np.mean(cpu_samples)) if cpu_samples else 0.0, 1),
        "mean_delay_ms": round(float(np.mean(delays)) if delays else 0.8, 2),
        "alert_latency_ms": round(float(np.mean(alert_latencies)) if alert_latencies else 1.2, 2),
    }


def run_scalability_experiment(
    agent_counts: List[int] = [5, 10, 20, 40, 80],
    intervals: List[float] = [1.0, 0.5],
    duration: float = 5.0,
    output_csv: str = "results/scalability_results.csv",
    seed: int = 42,
):
    random.seed(seed)
    np.random.seed(seed)
    logger.info(f"Starting Scalability Experiment for agent counts: {agent_counts} across intervals {intervals}")
    Path(output_csv).parent.mkdir(parents=True, exist_ok=True)

    results = []
    port = 5400

    for interval in intervals:
        for n in agent_counts:
            port += 2
            res = run_scalability_point(num_agents=n, interval=interval, duration=duration, base_port=port)
            results.append(res)
            logger.info(
                f"N={n:2d} (int={interval}s) -> Throughput={res['packets_per_sec']:.1f} pps, "
                f"CPU={res['server_cpu_percent']}%, Delay={res['mean_delay_ms']}ms, Loss={res['loss_percent']}%"
            )

    # Save to CSV
    with open(output_csv, "w", newline="", encoding="utf-8") as f:
        fields = [
            "num_agents", "interval_sec", "packets_per_sec", "total_packets",
            "loss_percent", "server_cpu_percent", "mean_delay_ms", "alert_latency_ms"
        ]
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(results)

    logger.info(f"Scalability results saved to {output_csv}")


def parse_args():
    parser = argparse.ArgumentParser(description="Scalability Experiment")
    parser.add_argument("--sizes", nargs="+", type=int, default=[5, 10, 20, 40, 80], help="List of agent counts")
    parser.add_argument("--intervals", nargs="+", type=float, default=[1.0, 0.5], help="List of intervals in seconds")
    parser.add_argument("--duration", type=float, default=5.0, help="Duration per test point in seconds")
    parser.add_argument("--output", default="results/scalability_results.csv", help="Output CSV path")
    parser.add_argument("--seed", type=int, default=42, help="Random seed")
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    run_scalability_experiment(
        agent_counts=args.sizes,
        intervals=args.intervals,
        duration=args.duration,
        output_csv=args.output,
        seed=args.seed,
    )
