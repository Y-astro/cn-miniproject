"""Generates publication-quality charts and tables from experimental CSV data.

Produces:
1. results/latency_cdf.png (Histogram and Empirical CDF for One-Way Delay and Alert Latency)
2. results/congestion_comparison.png (Grouped bar chart for Priority OFF vs Priority ON)
3. results/failure_detection_boxplot.png (Box plot of Time-to-Detect across failure modes)
4. results/scalability_trends.png (Line plots of Throughput, Delay, Loss %, CPU % vs N)
5. results/overhead_summary.csv (Protocol overhead and bandwidth consumption analysis)
"""

# Import csv module for writing overhead summary tables
import csv
# Import os module for checking file existence and path resolution
import os
# Import sys module for system paths
import sys
# Import Path class for filesystem path management
from pathlib import Path
# Import matplotlib module for charting and data visualization
import matplotlib
# Enforce headless non-interactive Agg backend to support execution without an X11 display
matplotlib.use("Agg")
# Import pyplot submodule for figure and axes manipulation
import matplotlib.pyplot as plt
# Import numpy for array calculations and sorting
import numpy as np
# Import pandas for easy tabular CSV ingestion and column filtering
import pandas as pd

# Prepend project root directory to sys.path so modules can be imported
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
# Import structured logger setup function
from common.logger import setup_logger
# Import protocol encode helper to compute exact serialized payload sizes
from common.protocol import encode

# Instantiate dedicated logger for chart and plot generation
logger = setup_logger("plot_results")


# Function to plot latency histogram and empirical cumulative distribution function (CDF)
def plot_baseline_latency(csv_path: str = "results/latency_results.csv"):
    """Plots histogram and empirical CDF for baseline delay and alert latency."""
    # Check if input CSV file exists on disk
    if not os.path.exists(csv_path):
        # Log warning and skip plot if data is missing
        logger.warning(f"File not found: {csv_path}, skipping latency plot.")
        # Return early
        return

    # Ingest CSV file into pandas DataFrame
    df = pd.read_csv(csv_path)
    # Extract delay measurements array, dropping any NaN values
    delays = df["delay_ms"].dropna().values
    # Extract alert latency measurements array, dropping any NaN values
    alerts = df["alert_latency_ms"].dropna().values

    # Create figure with 1 row and 2 side-by-side subplot axes
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 5))

    # 1. Subplot 1: Normalized Probability Density Histogram
    ax1.hist(delays, bins=25, alpha=0.7, color="#1f77b4", label="One-Way Delay", density=True, edgecolor="black")
    # If alert latency measurements exist, plot overlay histogram
    if len(alerts) > 0:
        # Plot alert latency distribution
        ax1.hist(alerts, bins=25, alpha=0.6, color="#d62728", label="Alert Latency", density=True, edgecolor="black")
    # Configure X-axis label
    ax1.set_xlabel("Time (ms)")
    # Configure Y-axis label
    ax1.set_ylabel("Probability Density")
    # Set subplot title
    ax1.set_title("Latency Distribution (No Congestion)")
    # Enable dashed grid lines
    ax1.grid(True, linestyle="--", alpha=0.6)
    # Render legend
    ax1.legend()

    # 2. Subplot 2: Empirical Cumulative Distribution Function (CDF)
    sorted_d = np.sort(delays)
    # Calculate cumulative probabilities: P(X <= x)
    cdf_d = np.arange(1, len(sorted_d) + 1) / len(sorted_d)
    # Plot delay CDF curve
    ax2.plot(sorted_d, cdf_d, label="One-Way Delay CDF", color="#1f77b4", linewidth=2)

    # If alert measurements exist, plot alert latency CDF curve
    if len(alerts) > 0:
        # Sort alert latencies
        sorted_a = np.sort(alerts)
        # Calculate alert cumulative probabilities
        cdf_a = np.arange(1, len(sorted_a) + 1) / len(sorted_a)
        # Plot alert CDF curve with dashed line
        ax2.plot(sorted_a, cdf_a, label="Alert Latency CDF", color="#d62728", linewidth=2, linestyle="--")

    # Configure X-axis label
    ax2.set_xlabel("Time (ms)")
    # Configure Y-axis label
    ax2.set_ylabel("Cumulative Probability P(X <= x)")
    # Set subplot title
    ax2.set_title("Empirical Cumulative Distribution Function (CDF)")
    # Enable dashed grid lines
    ax2.grid(True, linestyle="--", alpha=0.6)
    # Render legend
    ax2.legend()

    # Automatically adjust subplot spacing
    plt.tight_layout()
    # Destination PNG output file path
    out_path = "results/latency_cdf.png"
    # Save high-resolution PNG figure (300 DPI)
    plt.savefig(out_path, dpi=300)
    # Close figure to free memory
    plt.close()
    # Log successful figure generation
    logger.info(f"Generated: {out_path}")


# Function to generate comparative grouped bar chart comparing Priority OFF vs Priority ON
def plot_congestion_comparison(csv_path: str = "results/congestion_results.csv"):
    """Plots comparative grouped bars showing impact of SDN QoS prioritization."""
    # Check if CSV file exists on disk
    if not os.path.exists(csv_path):
        # Log warning and return if missing
        logger.warning(f"File not found: {csv_path}, skipping congestion plot.")
        # Return early
        return

    # Ingest CSV file into pandas DataFrame
    df = pd.read_csv(csv_path)
    # Categorize and order priority modes: OFF first, ON second
    df["priority_mode"] = pd.Categorical(df["priority_mode"], ["OFF", "ON"])
    # Sort DataFrame by priority mode
    df = df.sort_values("priority_mode")

    # Extract distinct priority mode labels
    modes = df["priority_mode"].values
    # Compute horizontal X coordinate indices
    x = np.arange(len(modes))
    # Width of individual bars
    width = 0.35

    # Create figure with 2 side-by-side subplots
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(13, 5))

    # Subplot 1: Packet Loss Percentage Comparison
    crit_loss = df["crit_loss_pct"].values
    # Normal traffic loss values
    norm_loss = df["norm_loss_pct"].values

    # Render critical monitoring bars offset to the left
    ax1.bar(x - width/2, crit_loss, width, label="Critical Monitoring", color="#d62728")
    # Render normal monitoring bars offset to the right
    ax1.bar(x + width/2, norm_loss, width, label="Normal Monitoring", color="#1f77b4")
    # Configure X-axis tick positions
    ax1.set_xticks(x)
    # Configure X-axis tick labels
    ax1.set_xticklabels([f"Priority {m}" for m in modes])
    # Configure Y-axis label
    ax1.set_ylabel("Packet Loss (%)")
    # Set subplot title
    ax1.set_title("Packet Loss Under Congestion (12 Mbps on 10 Mbps Link)")
    # Enable dashed grid lines along Y-axis
    ax1.grid(True, linestyle="--", alpha=0.6, axis="y")
    # Render legend
    ax1.legend()

    # Subplot 2: 95th Percentile Delay Comparison
    crit_delay = df["crit_delay_p95_ms"].values
    # Normal traffic delay values
    norm_delay = df["norm_delay_p95_ms"].values

    # Render critical delay bars offset to the left
    ax2.bar(x - width/2, crit_delay, width, label="Critical Delay (p95)", color="#d62728")
    # Render normal delay bars offset to the right
    ax2.bar(x + width/2, norm_delay, width, label="Normal Delay (p95)", color="#1f77b4")
    # Configure X-axis tick positions
    ax2.set_xticks(x)
    # Configure X-axis tick labels
    ax2.set_xticklabels([f"Priority {m}" for m in modes])
    # Configure Y-axis label
    ax2.set_ylabel("95th Percentile Delay (ms)")
    # Set subplot title
    ax2.set_title("Queueing Delay Under Congestion")
    # Enable dashed grid lines along Y-axis
    ax2.grid(True, linestyle="--", alpha=0.6, axis="y")
    # Render legend
    ax2.legend()

    # Automatically adjust subplot spacing
    plt.tight_layout()
    # Destination PNG output file path
    out_path = "results/congestion_comparison.png"
    # Save high-resolution PNG figure (300 DPI)
    plt.savefig(out_path, dpi=300)
    # Close figure to free memory
    plt.close()
    # Log successful figure generation
    logger.info(f"Generated: {out_path}")


# Function to generate box plot comparing Time-to-Detect (TTD) across failure scenarios
def plot_failure_detection(csv_path: str = "results/failure_results.csv"):
    """Generates box plots of Time-to-Detect (TTD) across failure modes."""
    # Check if CSV file exists on disk
    if not os.path.exists(csv_path):
        # Log warning and return if missing
        logger.warning(f"File not found: {csv_path}, skipping failure plot.")
        # Return early
        return

    # Ingest CSV file into pandas DataFrame
    df = pd.read_csv(csv_path)
    # List of failure types to plot
    failure_types = ["agent_crash", "link_failure", "partial_loss"]
    # Extract TTD measurement arrays for each failure type
    data = [df[df["failure_type"] == ft]["ttd_sec"].dropna().values for ft in failure_types]
    # Human-readable labels for the X-axis
    labels = ["Agent Crash", "Link Failure", "Partial Loss"]

    # Create figure and single axes
    fig, ax = plt.subplots(figsize=(8, 5))
    # Render box plots with solid color fill
    box = ax.boxplot(data, tick_labels=labels, patch_artist=True)

    # Distinct pastel fill colors for each failure category box
    colors = ["#ff9999", "#66b3ff", "#99ff99"]
    # Apply face colors to individual box artists
    for patch, color in zip(box["boxes"], colors):
        # Set fill color
        patch.set_facecolor(color)

    # Configure Y-axis label
    ax.set_ylabel("Time-to-Detect (seconds)")
    # Set plot title
    ax.set_title("Failure Detection Latency across Multiple Failure Modes")
    # Enable dashed grid lines along Y-axis
    ax.grid(True, linestyle="--", alpha=0.6, axis="y")

    # Adjust layout
    plt.tight_layout()
    # Destination PNG output file path
    out_path = "results/failure_detection_boxplot.png"
    # Save high-resolution PNG figure (300 DPI)
    plt.savefig(out_path, dpi=300)
    # Close figure
    plt.close()
    # Log successful figure generation
    logger.info(f"Generated: {out_path}")


# Function to plot multi-panel line trends of Throughput, CPU, Delay, and Loss vs Node Count N
def plot_scalability_trends(csv_path: str = "results/scalability_results.csv"):
    """Plots line trends of throughput, CPU, and delay vs number of agent nodes."""
    # Check if CSV file exists on disk
    if not os.path.exists(csv_path):
        # Log warning and return if missing
        logger.warning(f"File not found: {csv_path}, skipping scalability plot.")
        # Return early
        return

    # Ingest CSV file into pandas DataFrame
    df = pd.read_csv(csv_path)
    # Extract unique reporting intervals tested
    intervals = df["interval_sec"].unique()

    # Create 2x2 grid of subplots (4 panels)
    fig, ((ax1, ax2), (ax3, ax4)) = plt.subplots(2, 2, figsize=(13, 9))

    # Point markers for interval lines
    markers = ["o-", "s--"]
    # Line colors
    colors = ["#1f77b4", "#ff7f0e"]

    # Iterate through unique interval curves
    for idx, inv in enumerate(sorted(intervals, reverse=True)):
        # Filter subset of data matching this interval, sorted by node count N
        sub = df[df["interval_sec"] == inv].sort_values("num_agents")
        # Line legend label
        lbl = f"Interval = {inv}s"

        # Panel 1: Throughput (packets/sec) vs N
        ax1.plot(sub["num_agents"], sub["packets_per_sec"], markers[idx % 2], color=colors[idx % 2], label=lbl, linewidth=2)
        # Panel 2: Server CPU Load (%) vs N
        ax2.plot(sub["num_agents"], sub["server_cpu_percent"], markers[idx % 2], color=colors[idx % 2], label=lbl, linewidth=2)
        # Panel 3: One-Way Delay (ms) vs N
        ax3.plot(sub["num_agents"], sub["mean_delay_ms"], markers[idx % 2], color=colors[idx % 2], label=lbl, linewidth=2)
        # Panel 4: Packet Loss (%) vs N
        ax4.plot(sub["num_agents"], sub["loss_percent"], markers[idx % 2], color=colors[idx % 2], label=lbl, linewidth=2)

    # Panel 1 labels and grid
    ax1.set_xlabel("Number of Agent Nodes (N)")
    # Y-axis label
    ax1.set_ylabel("Throughput (packets / sec)")
    # Title
    ax1.set_title("Throughput vs Node Count")
    # Grid
    ax1.grid(True, linestyle="--", alpha=0.6)
    # Legend
    ax1.legend()

    # Panel 2 labels and grid
    ax2.set_xlabel("Number of Agent Nodes (N)")
    # Y-axis label
    ax2.set_ylabel("Server CPU Utilization (%)")
    # Title
    ax2.set_title("Server CPU Load vs Node Count")
    # Grid
    ax2.grid(True, linestyle="--", alpha=0.6)
    # Legend
    ax2.legend()

    # Panel 3 labels and grid
    ax3.set_xlabel("Number of Agent Nodes (N)")
    # Y-axis label
    ax3.set_ylabel("Mean Delay (ms)")
    # Title
    ax3.set_title("End-to-End Latency vs Node Count")
    # Grid
    ax3.grid(True, linestyle="--", alpha=0.6)
    # Legend
    ax3.legend()

    # Panel 4 labels and grid
    ax4.set_xlabel("Number of Agent Nodes (N)")
    # Y-axis label
    ax4.set_ylabel("Packet Loss (%)")
    # Title
    ax4.set_title("Packet Loss vs Node Count")
    # Grid
    ax4.grid(True, linestyle="--", alpha=0.6)
    # Legend
    ax4.legend()

    # Adjust subplot spacing
    plt.tight_layout()
    # Destination PNG output file path
    out_path = "results/scalability_trends.png"
    # Save high-resolution PNG figure (300 DPI)
    plt.savefig(out_path, dpi=300)
    # Close figure
    plt.close()
    # Log successful figure generation
    logger.info(f"Generated: {out_path}")


# Function to compute exact network payload sizes, wire bytes, and bandwidth consumption
def generate_overhead_table(output_csv: str = "results/overhead_summary.csv"):
    """Calculates report payload sizes and monitoring bandwidth overhead."""
    # Representative HEALTH telemetry message dictionary
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
    # Representative lightweight HEARTBEAT message dictionary
    sample_heartbeat = {
        "version": 1,
        "type": "HEARTBEAT",
        "node_id": "h1",
        "seq": 1043,
        "sent_ts": 1730000000.123456,
        "priority": "NORMAL",
    }

    # Encode sample HEALTH payload into UTF-8 JSON bytes
    raw_health = encode(sample_health)
    # Encode sample HEARTBEAT payload into UTF-8 JSON bytes
    raw_heartbeat = encode(sample_heartbeat)

    # Combined lower-layer headers: Ethernet (14B) + IPv4 (20B) + UDP (8B) = 42 bytes overhead
    l2_l4_header = 42

    # Assemble analysis records
    records = [
        # Full telemetry HEALTH message analysis
        {
            # Message type
            "report_type": "HEALTH",
            # Encoded application payload size in bytes
            "payload_bytes": len(raw_health),
            # Total wire size including L2-L4 transport headers
            "wire_bytes": len(raw_health) + l2_l4_header,
            # Bandwidth consumption at 1.0s reporting interval (kbps)
            "kbps_at_1s_interval": round(((len(raw_health) + l2_l4_header) * 8.0) / 1000.0, 3),
            # Bandwidth consumption at 0.5s reporting interval (kbps)
            "kbps_at_0.5s_interval": round(((len(raw_health) + l2_l4_header) * 8.0 * 2.0) / 1000.0, 3),
        },
        # Lightweight HEARTBEAT message analysis
        {
            # Message type
            "report_type": "HEARTBEAT",
            # Encoded application payload size in bytes
            "payload_bytes": len(raw_heartbeat),
            # Total wire size including L2-L4 transport headers
            "wire_bytes": len(raw_heartbeat) + l2_l4_header,
            # Bandwidth consumption at 1.0s reporting interval (kbps)
            "kbps_at_1s_interval": round(((len(raw_heartbeat) + l2_l4_header) * 8.0) / 1000.0, 3),
            # Bandwidth consumption at 0.5s reporting interval (kbps)
            "kbps_at_0.5s_interval": round(((len(raw_heartbeat) + l2_l4_header) * 8.0 * 2.0) / 1000.0, 3),
        },
    ]

    # Open CSV file and write overhead summary table
    with open(output_csv, "w", newline="", encoding="utf-8") as f:
        # Create DictWriter
        writer = csv.DictWriter(f, fieldnames=[
            "report_type", "payload_bytes", "wire_bytes", "kbps_at_1s_interval", "kbps_at_0.5s_interval"
        ])
        # Write column headers
        writer.writeheader()
        # Write record rows
        writer.writerows(records)

    # Log completion
    logger.info(f"Overhead analysis saved to {output_csv}")


# Main execution entrypoint to generate all figures and tables
def main():
    # Generate baseline latency histogram and CDF plot
    plot_baseline_latency()
    # Generate comparative congestion grouped bar chart
    plot_congestion_comparison()
    # Generate failure detection box plots
    plot_failure_detection()
    # Generate multi-panel scalability line charts
    plot_scalability_trends()
    # Generate protocol overhead summary table
    generate_overhead_table()
    # Log overall completion message
    logger.info("All plots and tables generated successfully in results/")


# Standard script entrypoint idiom
if __name__ == "__main__":
    # Execute main
    main()
