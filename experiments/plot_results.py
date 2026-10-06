"""Generates publication-quality charts and tables from experimental CSV data.

Produces:
1. results/latency_cdf.png (Histogram and Empirical CDF for One-Way Delay and Alert Latency)
2. results/congestion_comparison.png (Grouped bar chart for Priority OFF vs Priority ON)
3. results/failure_detection_boxplot.png (Box plot of Time-to-Detect across failure modes)
4. results/scalability_trends.png (Line plots of Throughput, Delay, Loss %, CPU % vs N)
5. results/overhead_summary.csv (Protocol overhead and bandwidth consumption analysis)
"""

import csv
import os
import sys
from pathlib import Path
import matplotlib
matplotlib.use("Agg")  # Non-interactive backend
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

# Ensure project root is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from common.logger import setup_logger
from common.protocol import encode

logger = setup_logger("plot_results")


def plot_baseline_latency(csv_path: str = "results/latency_results.csv"):
    """Plots histogram and empirical CDF for baseline delay and alert latency."""
    if not os.path.exists(csv_path):
        logger.warning(f"File not found: {csv_path}, skipping latency plot.")
        return

    df = pd.read_csv(csv_path)
    delays = df["delay_ms"].dropna().values
    alerts = df["alert_latency_ms"].dropna().values

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 5))

    # 1. Histogram
    ax1.hist(delays, bins=25, alpha=0.7, color="#1f77b4", label="One-Way Delay", density=True, edgecolor="black")
    if len(alerts) > 0:
        ax1.hist(alerts, bins=25, alpha=0.6, color="#d62728", label="Alert Latency", density=True, edgecolor="black")
    ax1.set_xlabel("Time (ms)")
    ax1.set_ylabel("Probability Density")
    ax1.set_title("Latency Distribution (No Congestion)")
    ax1.grid(True, linestyle="--", alpha=0.6)
    ax1.legend()

    # 2. Empirical CDF
    sorted_d = np.sort(delays)
    cdf_d = np.arange(1, len(sorted_d) + 1) / len(sorted_d)
    ax2.plot(sorted_d, cdf_d, label="One-Way Delay CDF", color="#1f77b4", linewidth=2)

    if len(alerts) > 0:
        sorted_a = np.sort(alerts)
        cdf_a = np.arange(1, len(sorted_a) + 1) / len(sorted_a)
        ax2.plot(sorted_a, cdf_a, label="Alert Latency CDF", color="#d62728", linewidth=2, linestyle="--")

    ax2.set_xlabel("Time (ms)")
    ax2.set_ylabel("Cumulative Probability P(X <= x)")
    ax2.set_title("Empirical Cumulative Distribution Function (CDF)")
    ax2.grid(True, linestyle="--", alpha=0.6)
    ax2.legend()

    plt.tight_layout()
    out_path = "results/latency_cdf.png"
    plt.savefig(out_path, dpi=300)
    plt.close()
    logger.info(f"Generated: {out_path}")


def plot_congestion_comparison(csv_path: str = "results/congestion_results.csv"):
    """Plots comparative grouped bars showing impact of SDN QoS prioritization."""
    if not os.path.exists(csv_path):
        logger.warning(f"File not found: {csv_path}, skipping congestion plot.")
        return

    df = pd.read_csv(csv_path)
    # Sort by OFF, ON
    df["priority_mode"] = pd.Categorical(df["priority_mode"], ["OFF", "ON"])
    df = df.sort_values("priority_mode")

    modes = df["priority_mode"].values
    x = np.arange(len(modes))
    width = 0.35

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(13, 5))

    # Bar 1: Packet Loss %
    crit_loss = df["crit_loss_pct"].values
    norm_loss = df["norm_loss_pct"].values

    ax1.bar(x - width/2, crit_loss, width, label="Critical Monitoring", color="#d62728")
    ax1.bar(x + width/2, norm_loss, width, label="Normal Monitoring", color="#1f77b4")
    ax1.set_xticks(x)
    ax1.set_xticklabels([f"Priority {m}" for m in modes])
    ax1.set_ylabel("Packet Loss (%)")
    ax1.set_title("Packet Loss Under Congestion (12 Mbps on 10 Mbps Link)")
    ax1.grid(True, linestyle="--", alpha=0.6, axis="y")
    ax1.legend()

    # Bar 2: p95 Delay (ms)
    crit_delay = df["crit_delay_p95_ms"].values
    norm_delay = df["norm_delay_p95_ms"].values

    ax2.bar(x - width/2, crit_delay, width, label="Critical Delay (p95)", color="#d62728")
    ax2.bar(x + width/2, norm_delay, width, label="Normal Delay (p95)", color="#1f77b4")
    ax2.set_xticks(x)
    ax2.set_xticklabels([f"Priority {m}" for m in modes])
    ax2.set_ylabel("95th Percentile Delay (ms)")
    ax2.set_title("Queueing Delay Under Congestion")
    ax2.grid(True, linestyle="--", alpha=0.6, axis="y")
    ax2.legend()

    plt.tight_layout()
    out_path = "results/congestion_comparison.png"
    plt.savefig(out_path, dpi=300)
    plt.close()
    logger.info(f"Generated: {out_path}")


def plot_failure_detection(csv_path: str = "results/failure_results.csv"):
    """Generates box plots of Time-to-Detect (TTD) across failure modes."""
    if not os.path.exists(csv_path):
        logger.warning(f"File not found: {csv_path}, skipping failure plot.")
        return

    df = pd.read_csv(csv_path)
    failure_types = ["agent_crash", "link_failure", "partial_loss"]
    data = [df[df["failure_type"] == ft]["ttd_sec"].dropna().values for ft in failure_types]
    labels = ["Agent Crash", "Link Failure", "Partial Loss"]

    fig, ax = plt.subplots(figsize=(8, 5))
    box = ax.boxplot(data, tick_labels=labels, patch_artist=True)

    colors = ["#ff9999", "#66b3ff", "#99ff99"]
    for patch, color in zip(box["boxes"], colors):
        patch.set_facecolor(color)

    ax.set_ylabel("Time-to-Detect (seconds)")
    ax.set_title("Failure Detection Latency across Multiple Failure Modes")
    ax.grid(True, linestyle="--", alpha=0.6, axis="y")

    plt.tight_layout()
    out_path = "results/failure_detection_boxplot.png"
    plt.savefig(out_path, dpi=300)
    plt.close()
    logger.info(f"Generated: {out_path}")


def plot_scalability_trends(csv_path: str = "results/scalability_results.csv"):
    """Plots line trends of throughput, CPU, and delay vs number of agent nodes."""
    if not os.path.exists(csv_path):
        logger.warning(f"File not found: {csv_path}, skipping scalability plot.")
        return

    df = pd.read_csv(csv_path)
    intervals = df["interval_sec"].unique()

    fig, ((ax1, ax2), (ax3, ax4)) = plt.subplots(2, 2, figsize=(13, 9))

    markers = ["o-", "s--"]
    colors = ["#1f77b4", "#ff7f0e"]

    for idx, inv in enumerate(sorted(intervals, reverse=True)):
        sub = df[df["interval_sec"] == inv].sort_values("num_agents")
        lbl = f"Interval = {inv}s"

        ax1.plot(sub["num_agents"], sub["packets_per_sec"], markers[idx % 2], color=colors[idx % 2], label=lbl, linewidth=2)
        ax2.plot(sub["num_agents"], sub["server_cpu_percent"], markers[idx % 2], color=colors[idx % 2], label=lbl, linewidth=2)
        ax3.plot(sub["num_agents"], sub["mean_delay_ms"], markers[idx % 2], color=colors[idx % 2], label=lbl, linewidth=2)
        ax4.plot(sub["num_agents"], sub["loss_percent"], markers[idx % 2], color=colors[idx % 2], label=lbl, linewidth=2)

    ax1.set_xlabel("Number of Agent Nodes (N)")
    ax1.set_ylabel("Throughput (packets / sec)")
    ax1.set_title("Throughput vs Node Count")
    ax1.grid(True, linestyle="--", alpha=0.6)
    ax1.legend()

    ax2.set_xlabel("Number of Agent Nodes (N)")
    ax2.set_ylabel("Server CPU Utilization (%)")
    ax2.set_title("Server CPU Load vs Node Count")
    ax2.grid(True, linestyle="--", alpha=0.6)
    ax2.legend()

    ax3.set_xlabel("Number of Agent Nodes (N)")
    ax3.set_ylabel("Mean Delay (ms)")
    ax3.set_title("End-to-End Latency vs Node Count")
    ax3.grid(True, linestyle="--", alpha=0.6)
    ax3.legend()

    ax4.set_xlabel("Number of Agent Nodes (N)")
    ax4.set_ylabel("Packet Loss (%)")
    ax4.set_title("Packet Loss vs Node Count")
    ax4.grid(True, linestyle="--", alpha=0.6)
    ax4.legend()

    plt.tight_layout()
    out_path = "results/scalability_trends.png"
    plt.savefig(out_path, dpi=300)
    plt.close()
    logger.info(f"Generated: {out_path}")


def generate_overhead_table(output_csv: str = "results/overhead_summary.csv"):
    """Calculates report payload sizes and monitoring bandwidth overhead."""
    sample_health = {
        "version": 1,
        "type": "HEALTH",
        "node_id": "h1",
        "seq": 1042,
        "sent_ts": 1730000000.123456,
        "priority": "NORMAL",
        "metrics": {
            "cpu_percent": 73.2,
            "mem_percent": 61.5,
            "process_count": 182,
            "top_processes": [
                {"name": "python3", "cpu": 12.1},
                {"name": "sys_daemon", "cpu": 5.4},
                {"name": "agent", "cpu": 1.2},
            ],
            "net": {
                "bytes_sent": 123456, "bytes_recv": 654321,
                "packets_sent": 900, "packets_recv": 1100, "errors": 0,
            },
        },
    }
    sample_heartbeat = {
        "version": 1,
        "type": "HEARTBEAT",
        "node_id": "h1",
        "seq": 1043,
        "sent_ts": 1730000000.123456,
        "priority": "NORMAL",
    }

    raw_health = encode(sample_health)
    raw_heartbeat = encode(sample_heartbeat)

    # UDP (8 bytes) + IP (20 bytes) + Ethernet (14 bytes) header overhead = 42 bytes
    l2_l4_header = 42

    records = [
        {
            "report_type": "HEALTH",
            "payload_bytes": len(raw_health),
            "wire_bytes": len(raw_health) + l2_l4_header,
            "kbps_at_1s_interval": round(((len(raw_health) + l2_l4_header) * 8.0) / 1000.0, 3),
            "kbps_at_0.5s_interval": round(((len(raw_health) + l2_l4_header) * 8.0 * 2.0) / 1000.0, 3),
        },
        {
            "report_type": "HEARTBEAT",
            "payload_bytes": len(raw_heartbeat),
            "wire_bytes": len(raw_heartbeat) + l2_l4_header,
            "kbps_at_1s_interval": round(((len(raw_heartbeat) + l2_l4_header) * 8.0) / 1000.0, 3),
            "kbps_at_0.5s_interval": round(((len(raw_heartbeat) + l2_l4_header) * 8.0 * 2.0) / 1000.0, 3),
        },
    ]

    with open(output_csv, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "report_type", "payload_bytes", "wire_bytes", "kbps_at_1s_interval", "kbps_at_0.5s_interval"
        ])
        writer.writeheader()
        writer.writerows(records)

    logger.info(f"Overhead analysis saved to {output_csv}")


def main():
    plot_baseline_latency()
    plot_congestion_comparison()
    plot_failure_detection()
    plot_scalability_trends()
    generate_overhead_table()
    logger.info("All plots and tables generated successfully in results/")


if __name__ == "__main__":
    main()
