# Remote System Health Monitoring (UDP + SDN) — Project No. 11

[![Python Tests](https://img.shields.io/badge/pytest-60%20passed-brightgreen.svg)]()
[![Coverage](https://img.shields.io/badge/coverage-87%25-green.svg)]()
[![OpenFlow](https://img.shields.io/badge/OpenFlow-1.3-blue.svg)]()
[![Protocol](https://img.shields.io/badge/Protocol-UDP-orange.svg)]()

A distributed, low-latency remote system health monitoring application that couples a custom **UDP telemetry protocol** with an **OpenFlow 1.3 SDN controller (Ryu + Open vSwitch)** to guarantee delivery and strict priority for critical monitoring traffic over congested network bottlenecks.

---

## 1. Project Overview

In distributed computing clusters, server nodes must report vital operating statistics (CPU, memory, process count, network I/O) to a central monitoring server. While standard TCP monitoring incurs connection handshake overhead and head-of-line blocking under packet loss, raw UDP provides lightweight, connectionless transmission. However, under network congestion, UDP packets suffer indiscriminate drops.

This project solves this challenge by integrating **SDN-based traffic prioritization**:
- **Application Level:** Agents mark critical telemetry with **DSCP 46 (Expedited Forwarding)**.
- **SDN Control Plane:** The Ryu controller installs proactive OpenFlow rules mapping DSCP 46 to high-priority OVS HTB QoS queues with guaranteed minimum bandwidth.
- **Empirical Validation:** Rigorous benchmarks show that enabling SDN QoS reduces critical packet loss from **56.67% to 0.0%** and cuts 95th percentile queueing delay by **95.2%**.

---

## 2. Directory Structure

```
project11_health_monitor/
├── README.md                   # This documentation
├── requirements.txt            # Python dependencies
├── config.yaml                 # System configuration, ports, thresholds, QoS
├── common/
│   ├── protocol.py             # Message formatting, JSON encode/decode, validation
│   ├── config_loader.py        # YAML config loader with invariant validation
│   └── logger.py               # Structured logger with rate-limiting support
├── agent/
│   ├── health_agent.py         # UDP agent with DSCP marking and crash simulation
│   └── stats_collector.py      # Real (psutil) and simulated metrics collector
├── server/
│   ├── monitor_server.py       # Centralized non-blocking UDP server + console dashboard
│   ├── alert_engine.py         # Threshold evaluator with cooldown & hysteresis
│   └── node_registry.py        # Tracks last-seen, UP/DOWN lifecycle, loss & seq gaps
├── sdn/
│   ├── ryu_controller.py       # Ryu OpenFlow 1.3 app (L2 learning, QoS queues, stats)
│   └── topology.py             # Mininet star topology with 10 Mbps bottleneck link
├── experiments/
│   ├── run_latency_test.py     # Measures baseline delay and alert latency percentiles
│   ├── run_congestion_test.py  # Evaluates Priority ON vs Priority OFF under load
│   ├── run_failure_test.py     # Evaluates crash, link, and loss failure detection
│   ├── run_scalability_test.py # Scalability benchmarking across N = 5 to 80 nodes
│   └── plot_results.py         # Generates publication plots and overhead tables
├── tests/
│   ├── test_protocol.py        # Protocol unit tests (P1 - P10)
│   ├── test_stats_collector.py # Stats collector unit tests (S1 - S4)
│   ├── test_alert_engine.py    # Alert engine unit tests (A1 - A6)
│   ├── test_node_registry.py   # Node registry unit tests (R1 - R7)
│   ├── test_server_udp.py      # Real socket server tests (U1 - U5)
│   ├── test_robustness.py      # Negative and robustness tests (N1 - N4)
│   └── test_integration.py     # End-to-end integration tests (I1 - I7)
├── results/                    # CSV datasets, summary files, and plots
└── docs/
    └── report.md               # Final comprehensive technical report
```

---

## 3. Installation & Prerequisites

### System Requirements
- Linux (Ubuntu 20.04+, Debian 11+, or Arch / CachyOS)
- Python 3.8 to 3.10 (Python 3.10 recommended for Ryu compatibility)
- Mininet and Open vSwitch (required for live SDN network emulation)

```bash
# 1. Install system network tools (Ubuntu / Debian)
sudo apt update && sudo apt install -y mininet openvswitch-switch iperf

# 2. Set up virtual environment and install dependencies
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

---

## 4. How to Run

### Step 1: Start the SDN Controller
In Terminal 1, start the Ryu OpenFlow 1.3 controller:
```bash
# Enable traffic prioritization (default)
ryu-manager sdn/ryu_controller.py --verbose

# To disable prioritization for baseline comparison:
# (Set priority_enabled: false in config.yaml)
ryu-manager sdn/ryu_controller.py
```

### Step 2: Start Mininet Topology
In Terminal 2, launch the Mininet star topology with 5 hosts, bottleneck link, and auto-launched agents:
```bash
sudo python3 sdn/topology.py --hosts 5 --interval 1
```

### Running Standalone on Localhost (No Root Required)
The agent and server can also be launched directly on plain localhost without Mininet:
```bash
# Terminal 1: Launch server
python3 server/monitor_server.py --port 5005

# Terminal 2: Launch agent
python3 agent/health_agent.py --id h1 --server 127.0.0.1 --port 5005 --interval 1 --mode real
```

---

## 5. Running Tests

The test suite contains **60 tests** covering all specifications (P1–P10, S1–S4, A1–A6, R1–R7, U1–U5, I1–I7, N1–N4) with **87% overall test coverage**:

```bash
# Run all unit, robustness, and integration tests
pytest tests/ -v --cov=common --cov=server --cov=agent --cov-report=term-missing
```

---

## 6. Running Experiments & Generating Plots

Every experiment runs unattended, records real network telemetry into CSV files, and computes statistics:

```bash
# 1. Baseline Latency Experiment
python3 experiments/run_latency_test.py --runs 3

# 2. Bottleneck Congestion Experiment (Priority ON vs Priority OFF)
python3 experiments/run_congestion_test.py --runs 3

# 3. Failure Detection Experiment (Crash, Link cut, Loss)
python3 experiments/run_failure_test.py --repetitions 5

# 4. Scalability Experiment (N = 5, 10, 20, 40, 80 nodes)
python3 experiments/run_scalability_test.py --sizes 5 10 20 40 80 --intervals 1.0 0.5

# 5. Generate Figures and Summary Tables
python3 experiments/plot_results.py

# 6. Mininet Environment Cleanup (if Mininet was used)
sudo mn -c
```

### Generated Figures in `results/`:
- `results/latency_cdf.png`: Latency Histogram & Empirical CDF.
- `results/congestion_comparison.png`: Packet Loss % and Delay under Congestion.
- `results/failure_detection_boxplot.png`: Time-to-Detect (TTD) Box Plot across failure modes.
- `results/scalability_trends.png`: Throughput, CPU, and Latency Scaling vs Node Count.

---

## 7. Key Empirical Findings

| Metric | Priority OFF (Standard FIFO) | Priority ON (SDN QoS) | Improvement |
|---|---|---|---|
| **Critical Packet Loss under Congestion** | **56.67% ± 10.27%** | **0.00% ± 0.00%** | **100% loss eliminated** |
| **95th Percentile Delay (Critical)** | **30.75 ms** | **1.48 ms** | **95.2% reduction** |
| **Baseline Alert Latency** | 0.26 ms | 0.26 ms | Sub-millisecond response |
| **Cluster Scalability ($N=80$ nodes)** | 184.2 pkts/sec | 0.0% loss | Server CPU < 5% |

---

## 8. Troubleshooting

1. **Port 5005 Already in Use:**
   Kill any lingering server processes:
   ```bash
   fuser -k 5005/udp
   ```
2. **Mininet / Open vSwitch Permission Errors:**
   Mininet requires root privileges. Ensure you run with `sudo -E python3 sdn/topology.py`.
   Clean orphaned switches using:
   ```bash
   sudo mn -c
   ```
3. **Ryu Controller Version Compatibility:**
   Ryu runs on Python 3.8 through 3.10 with `eventlet<=0.33.3`. The project includes automatic `sitecustomize` compatibility patches for eventlet wsgi handling.

---

## 9. License

This project is created for academic research in Computer Networks and SDN. Free to use and modify for educational purposes.
