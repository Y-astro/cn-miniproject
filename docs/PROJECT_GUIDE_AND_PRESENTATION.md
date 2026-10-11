# Remote System Health Monitoring (UDP + SDN)
## Complete Technical Reference & 3-Member Presentation Guide

**Project No. 11 — Computer Networks & Software-Defined Networking**  
**Team Members & SRNs:**  
- **Member 1 (`PES2UG25CS609`):** Architecture & Protocol Lead (Problem Context, UDP Protocol Design, Agent Sampling & DSCP Marking)  
- **Member 2 (`PES2UG25CS642` / Y-astro):** Core Systems & SDN Technical Lead (Server Non-Blocking I/O, Alert Engine & Hysteresis, OpenFlow 1.3 QoS, Live Demo)  
- **Member 3 (`PES2UG25CS620`):** Reliability & Evaluation Lead (Failure Detection & Silence, Empirical Benchmarks & Graphs, Automated Tests & Conclusions)  

**Repository:** [https://github.com/Y-astro/cn-miniproject.git](https://github.com/Y-astro/cn-miniproject.git)  
**Presentation Slides:**
- PDF Deck: [`data/Remote-System-Health-Monitoring.pdf`](file:///run/media/astro/New%20Volume/Sem3/CN/miniproject/data/Remote-System-Health-Monitoring.pdf) (Mirror: [`docs/Remote-System-Health-Monitoring.pdf`](file:///run/media/astro/New%20Volume/Sem3/CN/miniproject/docs/Remote-System-Health-Monitoring.pdf))
- PPTX Source: [`data/Remote-System-Health-Monitoring.pptx`](file:///run/media/astro/New%20Volume/Sem3/CN/miniproject/data/Remote-System-Health-Monitoring.pptx) (Mirror: [`docs/Remote-System-Health-Monitoring.pptx`](file:///run/media/astro/New%20Volume/Sem3/CN/miniproject/docs/Remote-System-Health-Monitoring.pptx))

---

# Table of Contents
1. [Executive Summary & Problem Statement](#1-executive-summary--problem-statement)
2. [End-to-End System Architecture](#2-end-to-end-system-architecture)
3. [Deep Dive: Module-by-Module Breakdown](#3-deep-dive-module-by-module-breakdown)
   - [3.1 Message Protocol (`common/protocol.py`)](#31-message-protocol-commonprotocolpy)
   - [3.2 Health Agent (`agent/health_agent.py` & `stats_collector.py`)](#32-health-agent-agenthealth_agentpy--statscollectorpy)
   - [3.3 Central Monitoring Server (`server/monitor_server.py`)](#33-central-monitoring-server-servermonitor_serverpy)
   - [3.4 Node State & Sequence Tracking (`server/node_registry.py`)](#34-node-state--sequence-tracking-servernode_registrypy)
   - [3.5 Alert Engine & Hysteresis (`server/alert_engine.py`)](#35-alert-engine--hysteresis-serveralert_enginepy)
   - [3.6 SDN OpenFlow 1.3 Controller (`sdn/ryu_controller.py`)](#36-sdn-openflow-13-controller-sdnryu_controllerpy)
   - [3.7 Mininet Topology & HTB QoS (`sdn/topology.py`)](#37-mininet-topology--htb-qos-sdntopologypy)
   - [3.8 Automated Test Suite (`tests/`)](#38-automated-test-suite-tests)
   - [3.9 Empirical Evaluation Suite (`experiments/`)](#39-empirical-evaluation-suite-experiments)
4. [Step-by-Step Execution Guide](#4-step-by-step-execution-guide)
   - [Setup & Environment](#setup--environment)
   - [Running the Unit & Integration Tests](#running-the-unit--integration-tests)
   - [Localhost Execution (No Root / No Mininet)](#localhost-execution-no-root--no-mininet)
   - [Full SDN Mininet Network Emulation](#full-sdn-mininet-network-emulation)
   - [Executing Benchmark Experiments & Generating Plots](#executing-benchmark-experiments--generating-plots)
5. [3-Member Team Presentation & Teacher Viva Defense Guide](#5-3-member-team-presentation--teacher-viva-defense-guide)
   - [5.1 Team Division of Responsibilities & Role Matrix](#51-team-division-of-responsibilities--role-matrix)
   - [5.2 Slide-by-Slide 3-Member Presentation Script & Transitions](#52-slide-by-slide-3-member-presentation-script--transitions)
   - [5.3 Live Demonstration Coordination Runbook](#53-live-demonstration-coordination-runbook)
   - [5.4 Team Viva Defense: Assigned Examiner Questions & Expert Answers](#54-team-viva-defense-assigned-examiner-questions--expert-answers)
   - [5.5 Key Empirical Metrics Cheat Sheet for Viva](#55-key-empirical-metrics-cheat-sheet-for-viva)

---

# 1. Executive Summary & Problem Statement

### The Problem
In modern data centers and cloud clusters, thousands of server nodes must continuously report their health metrics (CPU, RAM, process count, network bandwidth) to a central monitoring node.
- **Traditional Approach (TCP):** Protocols like HTTP/TCP introduce three-way handshakes, connection state exhaustion on the server, and **head-of-line blocking**. If a single packet is lost on a congested link, TCP stalls all subsequent telemetry waiting for retransmissions.
- **Naive UDP Approach:** UDP is lightweight and connectionless, but UDP datagrams have **no guaranteed delivery or congestion control**. When network links become congested (e.g., due to background data transfers or video streaming), intermediate switch buffers overflow, and critical health alerts are dropped indiscriminately alongside bulk data.

### The Solution: UDP + OpenFlow 1.3 SDN Prioritization
This project combines the low latency and simplicity of UDP with the intelligent traffic engineering of **Software-Defined Networking (SDN)**:
1. **Host-Side Classification:** Monitoring agents inspect system vitals. If any metric crosses a warning/critical threshold, the agent sets the **IP Type of Service (TOS) / DSCP field** on the UDP socket to **DSCP 46 (Expedited Forwarding - EF)**. Normal telemetry uses **DSCP 0 (Best Effort)**.
2. **SDN Switch Prioritization:** A centralized **Ryu OpenFlow 1.3 controller** installs proactive flow entries on Open vSwitch (OVS). When packets arrive at the switch:
   - Packets with `UDP + DSCP 46` are steered into a **high-priority Linux HTB QoS queue** with guaranteed minimum bandwidth (5 Mbps on a 10 Mbps bottleneck link).
   - Normal health reports (`UDP + DSCP 0`) are steered into Queue 1 (3 Mbps guaranteed).
   - Background bulk traffic (e.g., `iperf`) is relegated to Queue 0 (best-effort).
3. **Result:** Under severe network congestion (12 Mbps UDP traffic flooded across a 10 Mbps link), critical health alerts experience **0.0% packet loss** and **1.48 ms p95 delay**, compared to **56.67% loss and 30.75 ms delay** when SDN prioritization is disabled.

---

# 2. End-to-End System Architecture

```
                                  +-------------------------------------------------+
                                  |              RYU SDN CONTROLLER                 |
                                  |               (OpenFlow 1.3)                    |
                                  |  - Proactive flow installation                  |
                                  |  - DSCP 46 (EF) -> Queue 2 (Critical)           |
                                  |  - DSCP 0  (BE) -> Queue 1 (Normal)             |
                                  |  - Background   -> Queue 0 (Best Effort)        |
                                  |  - 2s Periodic flow & port stats polling        |
                                  +------------------------+------------------------+
                                                           | OpenFlow Control Channel
                                                           | (TCP 6633)
                                                           v
+--------------------+            +-------------------------------------------------+            +--------------------+
|   Agent Node h1    |            |               Open vSwitch (s1)                 |            | Monitoring Server  |
| - psutil telemetry | 100 Mbps   |                                                 | 10 Mbps    |     (h_server)     |
| - DSCP 0 / 46 mark +----------->+ [Port 1]        OVS HTB QoS Queues     [Port 2] +----------->+ - Port 5005 UDP    |
+--------------------+            |                 ==================              | Bottleneck | - Select loop (I/O)|
                                  |                 Queue 2: 5M Min, 10M Max (Crit) |            | - Seq & loss track |
+--------------------+            |                 Queue 1: 3M Min, 10M Max (Norm) |            | - Alert engine     |
|   Agent Node h2    | 100 Mbps   |                 Queue 0: 1M Min, 10M Max (Bulk) |            | - CSV & Dashboard  |
| - Spike simulation +----------->+ [Port 3]                                        |            +--------------------+
+--------------------+            |                                                 |
                                  |                                                 |
+--------------------+            |                                                 |
| Bulk Traffic Node  | 100 Mbps   |                                                 |
| - iperf flood      +----------->+ [Port 4]                                        |
+--------------------+            +-------------------------------------------------+
```

---

# 3. Deep Dive: Module-by-Module Breakdown

## 3.1 Message Protocol (`common/protocol.py`)
- **Transport:** UDP over IPv4.
- **Payload Format:** Strict, compact JSON.
- **MTU Safety:** Payloads are constrained to $\le 1400$ bytes to guarantee that datagrams fit within standard 1500-byte Ethernet MTUs without IP fragmentation.
- **Fields:**
  - `version`: Integer (strictly `1`).
  - `type`: String (`"HEALTH"`, `"HEARTBEAT"`, or `"ALERT"`).
  - `node_id`: Non-empty string identifier (e.g., `"h1"`).
  - `seq`: Monotonically increasing sequence number ($\ge 0$).
  - `sent_ts`: Unix timestamp with microsecond resolution (`time.time()`).
  - `interval`: Floating-point reporting period in seconds.
  - `priority`: String (`"NORMAL"` or `"CRITICAL"`).
  - `metrics`: Dictionary containing `cpu_percent`, `mem_percent`, `process_count`, `top_processes`, and `net` I/O counters.
- **Validation:** The `validate()` function enforces type checks and boundary invariants ($0 \le \text{cpu, mem} \le 100$, non-negative counters). Any malformed packet immediately raises a `ProtocolError` with descriptive error messages.

## 3.2 Health Agent (`agent/health_agent.py` & `stats_collector.py`)
- **Execution Loop:** Uses monotonic clock scheduling (`time.monotonic()`) to eliminate clock drift over extended runtimes.
- **QoS Marking:** Employs socket-level options:
  ```python
  # DSCP 46 (EF) is shifted left by 2 bits to set the 8-bit IP TOS field:
  # 46 << 2 = 184 = 0xB8
  sock.setsockopt(socket.IPPROTO_IP, socket.IP_TOS, 0xB8)
  ```
- **Resilience:** If local metrics collection fails, the agent falls back to emitting a lightweight `HEARTBEAT` datagram to maintain node liveness on the server.
- **Simulation Capabilities:**
  - `stats_collector.py` provides deterministic patterns:
    - `normal`: Metrics stay safely below warning thresholds.
    - `spike`: Deterministically elevates CPU to $\ge 95\%$ and processes to $550$ on configured ticks.
    - `ramp-up`: Linearly increases load across cycles.
    - `constant-high`: Persistently alerts at critical thresholds.
  - `--fail-after N`: Simulates sudden process crash after transmitting $N$ packets.
  - `--recover-after M`: Simulates automated recovery after $M$ seconds of silence.

## 3.3 Central Monitoring Server (`server/monitor_server.py`)
- **Concurrency Architecture:** Uses a single non-blocking UDP socket managed via the POSIX `select` multiplexer. This avoids the thread-per-client overhead of TCP and easily handles hundreds of datagrams per second.
- **Latency Measurement:** Immediately upon receiving a datagram, records `recv_ts = time.time()`. One-way delay is computed as:
  $$\text{Delay (ms)} = (\text{recv\_ts} - \text{sent\_ts}) \times 1000$$
  Clock jumps or NTP skew anomalies are bounded and clamped to $0.0\text{ ms}$ with warnings.
- **Data Persistence:** Automatically appends structured telemetry to CSV files:
  - `results/server_reports.csv`: Per-packet report details (delay, node, metrics, priority).
  - `results/server_alerts.csv`: Fired alerts (metric, value, threshold, alert latency).
- **Console Dashboard:** Prints a periodic ASCII status table showing node states, packet loss %, average latency, and live vitals.

## 3.4 Node State & Sequence Tracking (`server/node_registry.py`)
- **Loss Computation:** Tracks expected vs. received sequence numbers:
  $$\text{Gap} = seq - last\_seq - 1$$
  $$\text{Loss Rate (\%)} = \frac{\text{lost\_packets}}{\text{total\_received} + \text{lost\_packets}} \times 100$$
- **Anomaly Handling:**
  - Duplicate packets ($seq == last\_seq$) are counted separately and discarded.
  - Out-of-order packets ($seq < last\_seq$) increment an `out_of_order` counter without corrupting loss totals.
  - Restart detection: If sequence resets to $0$ or $1$, it triggers a `NODE_RESTARTED` event rather than reporting a massive sequence gap.
- **Liveness & Silence Monitoring:** Every $0.5$s, the server evaluates node silence:
  $$\text{Silence Threshold} = 3.0 \times \text{interval}$$
  If no packet arrives within this duration, the server transitions the node to `DOWN` and raises a `NODE_DOWN` alert. Upon packet resumption, it raises `NODE_RECOVERED`.

## 3.5 Alert Engine & Hysteresis (`server/alert_engine.py`)
- **Threshold Hierarchy:**
  - CPU: Warning $\ge 70\%$, Critical $\ge 90\%$
  - RAM: Warning $\ge 75\%$, Critical $\ge 90\%$
  - Processes: Warning $\ge 300$, Critical $\ge 500$
  - Loss Rate: Warning $\ge 5\%$, Critical $\ge 20\%$
  - Silence: Critical $> 3 \times \text{interval}$
- **Cooldown (5.0s):** Once an alert fires for a given metric and severity, duplicate alerts are suppressed for 5 seconds to prevent log flooding.
- **Hysteresis Deadband (2.0%):** To prevent flapping when a metric hovers right around a threshold (e.g., oscillating between 69.9% and 70.1%), an alert clears only when the value drops below $\text{threshold} - \text{hysteresis}$ (e.g., $< 68.0\%$).
- **Alert Latency:** Measures end-to-end reaction time from metric generation on the agent to alert generation on the server:
  $$\text{Alert Latency} = \text{detect\_ts} - \text{trigger\_ts}$$

## 3.6 SDN OpenFlow 1.3 Controller (`sdn/ryu_controller.py`)
- **OpenFlow Version:** OpenFlow 1.3.
- **Learning Switch Base:** Handles L2 MAC learning (`OFPPacketIn`, `OFPPacketOut`) for general connectivity.
- **Proactive QoS Flows:** On switch handshake (`EventOFPSwitchFeatures`), installs proactive classification rules:
  1. **Priority 100:** Matches `eth_type=0x0800, ip_proto=17, udp_dst=5005, ip_dscp=46` $\to$ Action: `OFPActionSetQueue(queue_id=2)`, `output:NORMAL`.
  2. **Priority 50:** Matches `eth_type=0x0800, ip_proto=17, udp_dst=5005, ip_dscp=0` $\to$ Action: `OFPActionSetQueue(queue_id=1)`, `output:NORMAL`.
  3. **Priority 10:** Matches `eth_type=0x0800, ip_proto=17` $\to$ Action: `OFPActionSetQueue(queue_id=0)`, `output:NORMAL`.
- **Dynamic Monitoring:** Spawns a green thread polling port and flow stats every 2.0s via `OFPPortStatsRequest`. If the egress link toward the monitoring server exceeds 80% capacity (8 Mbps on a 10 Mbps link), the controller logs congestion alerts to `results/sdn_flow_stats.csv`.

## 3.7 Mininet Topology & HTB QoS (`sdn/topology.py`)
- **Topology:** Star network centered around Open vSwitch `s1`.
- **Hosts:** $N$ agent hosts (`10.0.0.1` to `10.0.0.N`) with 100 Mbps links; 1 monitoring server host (`10.0.0.100`) connected via a **10 Mbps bottleneck link** (`TCLink`, delay=2ms).
- **OVS HTB QoS Configuration:**
  Configured directly via `ovs-vsctl` on the server port (`s1-eth1`):
  - **Queue 2 (Critical):** Guaranteed min-rate = 5 Mbps, max-rate = 10 Mbps.
  - **Queue 1 (Normal):** Guaranteed min-rate = 3 Mbps, max-rate = 10 Mbps.
  - **Queue 0 (Best Effort):** Min-rate = 1 Mbps, max-rate = 10 Mbps.

## 3.8 Automated Test Suite (`tests/`)
Comprises **60 unit, integration, and robustness tests** achieving **87% code coverage**:
- `test_protocol.py`: P1–P10 (Round-trip equality, missing fields, out-of-range metrics, corrupted bytes, empty payload, oversized payloads >1400B).
- `test_stats_collector.py`: S1–S4 (Real psutil sampling, spike mode, normal mode, psutil exception fallback).
- `test_alert_engine.py`: A1–A6 (Boundary values, cooldown window, hysteresis deadband, multi-metric alerts, config validation).
- `test_node_registry.py`: R1–R7 (New node registration, silence timeout, recovery, sequence gaps, duplicates, out-of-order, restart handling).
- `test_server_udp.py`: U1–U5 (Live UDP socket ingestion, 1000 malformed burst survival, concurrent multi-threading load, port conflict error, clean shutdown).
- `test_robustness.py`: N1–N4 (Invalid config exit, unreachable agent resilience, negative intervals, clock jump clamping).
- `test_integration.py`: I1–I7 (Multi-agent telemetry, spike alerts, kill/restart recovery, link silence, Priority ON vs. OFF under congestion, server restart recovery, 20-agent load test).

## 3.9 Empirical Evaluation Suite (`experiments/`)
- `run_latency_test.py`: Measures one-way transmission delay and alert latency over repeated runs.
- `run_congestion_test.py`: Injects a 12 Mbps UDP congestion flood across a 10 Mbps bottleneck and records metrics under Priority OFF vs. Priority ON.
- `run_failure_test.py`: Measures Time-to-Detect (TTD) and Time-to-Recover (TTR) across 5 repetitions of agent crash, link failure, and partial loss.
- `run_scalability_test.py`: Evaluates throughput, packet loss, server CPU, and latency across $N = 5, 10, 20, 40, 80$ nodes at 1.0s and 0.5s intervals.
- `plot_results.py`: Reads the CSVs and produces high-resolution PNG plots and overhead summaries.

---

# 4. Step-by-Step Execution Guide

## Setup & Environment
Ensure you are in the project root:
```bash
cd "/run/media/astro/New Volume/Sem3/CN/miniproject"

# Activate the project virtual environment
source .venv/bin/activate
```

## Running the Unit & Integration Tests
Run the complete automated test suite with coverage reporting:
```bash
pytest tests/ -v --cov=common --cov=server --cov=agent --cov-report=term-missing
```
**Expected Output:**
```
============================= 60 passed in ~22s ==============================
TOTAL Coverage: 87%
```

---

## Localhost Execution (No Root / No Mininet)
You can run the server and agents on localhost in separate terminal windows:

### Terminal 1: Launch the Central Server
```bash
python3 server/monitor_server.py --port 5005
```
*You will see the live ASCII dashboard refreshing every 2 seconds.*

### Terminal 2: Launch a Normal Agent
```bash
python3 agent/health_agent.py --id h1 --server 127.0.0.1 --port 5005 --interval 1.0 --mode real
```

### Terminal 3: Launch a Spiking Agent (Simulated Alerts)
```bash
python3 agent/health_agent.py --id h2 --server 127.0.0.1 --port 5005 --interval 1.0 --mode simulated --sim-pattern spike
```
*Observe `h2` triggering `[ALERT] [CRITICAL]` on Terminal 1 with high CPU and RAM.*

---

## Full SDN Mininet Network Emulation
*(Requires root privileges, Mininet, Open vSwitch, and Ryu)*

### Terminal 1: Launch Ryu Controller
```bash
ryu-manager sdn/ryu_controller.py --verbose
```

### Terminal 2: Launch Mininet Topology
```bash
sudo -E python3 sdn/topology.py --hosts 5 --interval 1.0
```
This automatically:
1. Connects `s1` to the Ryu controller at `127.0.0.1:6633`.
2. Configures HTB QoS queues on switch port `s1-eth1`.
3. Starts `monitor_server.py` on host `h_server` (`10.0.0.100`).
4. Launches `health_agent.py` on hosts `h1` through `h5`.
5. Opens the Mininet interactive CLI.

### Clean up after Mininet
```bash
sudo mn -c
```

---

## Executing Benchmark Experiments & Generating Plots

Run the four evaluation experiments and generate charts:

```bash
# 1. Baseline Latency Experiment (3 runs)
python3 experiments/run_latency_test.py --runs 3

# 2. Congestion Experiment (Priority OFF vs Priority ON)
python3 experiments/run_congestion_test.py --runs 3

# 3. Failure Detection Experiment (5 repetitions per failure mode)
python3 experiments/run_failure_test.py --repetitions 5

# 4. Scalability Experiment (N = 5, 10, 20, 40, 80 nodes)
python3 experiments/run_scalability_test.py --sizes 5 10 20 40 80 --intervals 1.0 0.5

# 5. Generate Figures and Tables
python3 experiments/plot_results.py
```

Generated plots in `results/`:
- `results/latency_cdf.png`
- `results/congestion_comparison.png`
- `results/failure_detection_boxplot.png`
- `results/scalability_trends.png`

---

# 5. 3-Member Team Presentation & Teacher Viva Defense Guide

This guide is designed for our **3-member team** presenting Project No. 11. It directly maps to the 8 slides in [`data/Remote-System-Health-Monitoring.pdf`](file:///run/media/astro/New%20Volume/Sem3/CN/miniproject/data/Remote-System-Health-Monitoring.pdf) (and [`docs/Remote-System-Health-Monitoring.pdf`](file:///run/media/astro/New%20Volume/Sem3/CN/miniproject/docs/Remote-System-Health-Monitoring.pdf)), providing verbatim speaking scripts, seamless handovers, live demo coordination, and viva question allocations.

---

## 5.1 Team Division of Responsibilities & Role Matrix

To ensure a balanced academic presentation where the **Technical Lead (Member 2)** handles the core systems and SDN networking, while **Member 1** and **Member 3** deliver strong foundations and rigorous empirical proof:

| Member & SRN | Role in Project | Assigned Slides | Primary Topics & Technical Focus | Live Demo Responsibility |
|---|---|---|---|---|
| **Member 1**<br>`PES2UG25CS609` | **Architecture & Protocol Lead** | **Slides 1, 2, 3** | • Problem Context: TCP head-of-line blocking vs. naive UDP loss<br>• Protocol Architecture: Compact JSON & MTU $\le 1400$B guard<br>• Agent Design: `psutil` sampling, timer drift avoidance, heartbeat fallback, and IP TOS/DSCP socket marking | Introduces the team, sets up the problem context, and explains agent startup. |
| **Member 2**<br>`PES2UG25CS642`<br>*(Technical Lead)* | **Core Systems & SDN Lead** | **Slides 4, 5** | • Server Select Loop: Non-blocking POSIX I/O multiplexing<br>• Telemetry & Alerts: One-way delay, hysteresis deadband (2%) & cooldown (5s)<br>• SDN OpenFlow 1.3: Flow tables, DSCP 46 matching, and OVS HTB QoS queueing | **Operates the Terminal:** Runs the 60-test pytest suite, launches server/agents, triggers CPU spikes, and demonstrates SDN QoS queues. |
| **Member 3**<br>`PES2UG25CS620` | **Reliability & Evaluation Lead** | **Slides 6, 7, 8** | • Failure Detection: Sequence gaps, silence timeout ($3 \times \text{interval}$), crash vs link cut disambiguation<br>• Empirical Benchmarks: Congestion (56.7% vs 0% loss), Latency CDF (<1ms), Scalability (80 nodes)<br>• Conclusions: Test rigor (60 tests, 87% coverage) & final takeaways | Explains failure detection and interprets experimental benchmark charts during the demo. |

---

## 5.2 Slide-by-Slide 3-Member Presentation Script & Transitions

---

### Slide 1: Remote System Health Monitoring (Title & Motivation)
**Speaker: Member 1 (`PES2UG25CS609`)**

* **Visual on Screen:** Title slide showing project name, subtitle ("A lightweight path from local readings to protected alerts"), and the 3 team SRNs (`PES2UG25CS609`, `PES2UG25CS620`, `PES2UG25CS642`).
* **Key Talking Points:**
  1. Welcome the evaluator and introduce the team.
  2. The fundamental networking dilemma in cluster health monitoring:
     - **TCP** has heavy connection state and suffers from **head-of-line blocking**—one lost packet stalls all subsequent telemetry.
     - **UDP** is stateless and lightweight, but offers **zero delivery guarantees**—under switch congestion, critical health alerts are dropped indiscriminately alongside bulk background traffic.
  3. Our project's objective: combine the microsecond speed of UDP with the intelligent traffic engineering of **OpenFlow 1.3 Software-Defined Networking (SDN)**.
* **Verbatim Script:**
  > *"Good morning, Professor. Today, our team is presenting Project No. 11: **Remote System Health Monitoring using UDP and an OpenFlow 1.3 SDN Controller**.*  
  > *In cloud data centers, hundreds of server nodes must continuously report their vitals—CPU, memory, process counts, and network I/O. Traditionally, network engineers face an uncomfortable tradeoff: TCP provides reliability but incurs heavy connection state and head-of-line blocking. Naive UDP eliminates connection overhead, but when network links become congested, switches drop critical failure alarms just like background traffic.*  
  > *Our system solves this by creating a lightweight telemetry path over UDP, paired with an SDN control plane that guarantees bandwidth and zero packet loss for high-priority alerts across congested bottleneck links."*

---

### Slide 2: How It Works — Lightweight Datagrams & Strict Protocol
**Speaker: Member 1 (`PES2UG25CS609`)**

* **Visual on Screen:** 3-step pipeline (`01 Collect local data`, `02 Keep each report small`, `03 Prioritize alerts`), Packet Rules box (`common/protocol.py`), and CSV evidence sample (`server_reports.csv`).
* **Key Talking Points:**
  1. **3-Step Architecture:** Local agent data collection $\to$ Compact JSON datagram encoding $\to$ Hardware-level switch prioritization via DSCP 46.
  2. **MTU 1400-byte Guard:** Standard Ethernet MTU is 1500 bytes. With 20B IPv4 + 8B UDP headers, maximum payload is 1472B. Capping payloads at 1400 bytes guarantees zero IP packet fragmentation.
  3. **Strict Validation:** Every packet is validated against formal schemas; malformed datagrams are rejected without crashing the daemon.
  4. **Empirical Evidence Logging:** Server persists every decision to `results/server_reports.csv` and `results/server_alerts.csv`.
* **Verbatim Script:**
  > *"Moving to Slide 2: How the system works end-to-end. Our architecture operates as a streamlined three-step pipeline:*  
  > *First, agents continuously collect host metrics. Second, we serialize telemetry into strict, compact JSON datagrams. Crucially, in `common/protocol.py`, we enforce an MTU guard of 1400 bytes. Since standard Ethernet MTU is 1500 bytes, this guard ensures that no telemetry packet will ever undergo IP fragmentation, completely avoiding reassembly overhead and fragment drops.*  
  > *Third, when a threshold violation occurs, the agent tags the packet so the SDN switch can steer it to a protected queue. Furthermore, every packet received by the server is logged into append-only CSV files, providing audit evidence for every single transmission."*

---

### Slide 3: Agent Design · Local Sampling
**Speaker: Member 1 (`PES2UG25CS609`)**

* **Visual on Screen:** Agent design cards (Report fields, Heartbeat fallback, Message wire size), DSCP / TOS Marking code snippet, and `stats_collector.py` simulation modes.
* **Key Talking Points:**
  1. **Low Overhead:** Wire size is only 420 bytes (378B payload), consuming only **3.36 kbps per node** at 1-second intervals.
  2. **Drift-Free Sampling:** Monotonic timer (`time.monotonic()`) eliminates wall-clock drift over hours of execution.
  3. **Fault-Tolerant Heartbeat:** If `psutil` hardware queries fail, the agent falls back to sending a lightweight `HEARTBEAT` datagram, keeping the node marked `ALIVE`.
  4. **IP TOS / DSCP Marking:** Uses `sock.setsockopt(socket.IPPROTO_IP, socket.IP_TOS, 0xB8)` to mark DSCP 46 (Expedited Forwarding).
  5. **Deterministic Simulation Modes:** Supports `spike`, `ramp-up`, and `normal` modes for reproducible testing.
* **Verbatim Script:**
  > *"On Slide 3, we look at agent engineering. Our agent uses `psutil` to sample CPU, memory, active process counts, top memory consumers, and network I/O. Each report has a wire size of only 420 bytes, consuming a negligible 3.36 kbps of bandwidth per agent at 1-second intervals.*  
  > *To ensure rock-solid reliability, the agent uses monotonic clock timing to prevent scheduling drift. If local hardware sampling encounters an exception, the agent falls back to transmitting a lightweight `HEARTBEAT` packet, ensuring the node is never prematurely flagged as offline.*  
  > *Crucially, when metrics exceed critical thresholds, the agent invokes `setsockopt` with IP Type of Service `0xB8`. This writes DSCP 46—Expedited Forwarding—directly into the outer IPv4 header.*  
  > *To explain how our central server processes these datagrams and how our OpenFlow controller enforces Quality of Service, I will now hand over to **Member 2 (`PES2UG25CS642`)**, our Core Systems and SDN Lead."*

---

### 🔄 Transition to Member 2:
> **Member 1 says:** *"I will now hand over to Member 2 (`PES2UG25CS642`), who led the technical implementation of our non-blocking server architecture and the OpenFlow SDN QoS framework."*

---

### Slide 4: Server Decision Loop · Receive, Check, Alert
**Speaker: Member 2 (`PES2UG25CS642` / Technical Lead)**

* **Visual on Screen:** Non-blocking `select` loop diagram, delay calculation with clock jump clamping, append-only CSV evidence, and multi-metric alert thresholds.
* **Key Talking Points:**
  1. **POSIX Select Multiplexing:** Uses a single non-blocking UDP socket and `select.select()` with a 0.5s timeout. This avoids thread-per-client overhead, eliminating OS context switching and scaling effortlessly to hundreds of concurrent nodes.
  2. **Accurate Delay Measurement:** Sub-millisecond latency computed as $(\text{recv\_ts} - \text{sent\_ts}) \times 1000$. Negative values from clock skews are safely clamped to $0.0\text{ ms}$ with diagnostic logging.
  3. **Alert Engine with Hysteresis & Cooldown:**
     - Thresholds: CPU (70% warn / 90% crit), RAM (75% warn / 90% crit), Processes (300 warn / 500 crit), Packet loss (5% warn / 20% crit).
     - **2% Hysteresis Deadband:** Prevents alert flapping at threshold boundaries (e.g., oscillating around 70%).
     - **5.0s Cooldown:** Suppresses duplicate alert storms during sustained degradation.
* **Verbatim Script:**
  > *"Thank you. On Slide 4, we examine the server's non-blocking decision engine.*  
  > *Rather than spawning a separate thread per client—which wastes memory and incurs heavy OS context switching—our server multiplexes all incoming telemetry through a single non-blocking UDP socket using the POSIX `select` system call. This allows a single event loop to handle hundreds of packets per second while utilizing under 5% CPU.*  
  > *When a packet arrives, the server immediately timestamps it and computes one-way transmission delay. In production clusters, clock skew can occasionally produce negative values, so our engine includes bounds checking to clamp any anomaly to 0.0 ms.*  
  > *Incoming vitals pass into our `AlertEngine`. In real-world networks, a metric hovering right at 70% can cause 'alert flapping'—firing and clearing every second. To eliminate this, we implemented a 2% hysteresis deadband: an alert triggers at 70%, but only clears when the metric drops strictly below 68%. Combined with a 5-second cooldown timer, this completely prevents log flooding."*

---

### Slide 5: Quality of Service · Keeping Critical Packets Moving
**Speaker: Member 2 (`PES2UG25CS642` / Technical Lead)**

* **Visual on Screen:** OpenFlow 1.3 match-action architecture table, DSCP 46 packet tagging, and OVS HTB Queue bandwidth reservations (Queue 2: 5M, Queue 1: 3M, Queue 0: 1M on a 10 Mbps bottleneck).
* **Key Talking Points:**
  1. **OpenFlow 1.3 Flow Rules:** The Ryu controller installs proactive OpenFlow 1.3 entries on Open vSwitch:
     - **Priority 100:** Matches `eth_type=0x0800, ip_proto=17, udp_dst=5005, ip_dscp=46` $\to$ Action `OFPActionSetQueue(2)` (High-Priority Critical Queue).
     - **Priority 50:** Matches `eth_type=0x0800, ip_proto=17, udp_dst=5005, ip_dscp=0` $\to$ Action `OFPActionSetQueue(1)` (Normal Telemetry Queue).
     - **Priority 10:** Matches default UDP/bulk traffic $\to$ Action `OFPActionSetQueue(0)` (Best-Effort Queue).
  2. **Linux HTB Queues in Open vSwitch:** Configured using `tc` / `ovs-vsctl` on switch egress port `s1-eth1`:
     - Queue 2 guarantees **5 Mbps minimum** reserved exclusively for critical alerts.
     - Queue 1 guarantees **3 Mbps minimum** for normal health reports.
     - Queue 0 provides **1 Mbps minimum** for background floods (e.g., `iperf`).
  3. **Dynamic Congestion Polling:** A Ryu green thread queries port statistics every 2 seconds via `OFPPortStatsRequest`; if link utilization exceeds 80% (8 Mbps), it logs congestion alerts.
* **Verbatim Script:**
  > *"Moving to Slide 5: Quality of Service and SDN traffic engineering.*  
  > *The core innovation of our project is using OpenFlow 1.3 to enforce deterministic QoS without inspecting application payloads. As Member 1 explained, the agent tags critical packets with DSCP 46. At the switch level, our centralized Ryu SDN controller installs proactive flow rules:*  
  > *Rule Priority 100 matches IPv4 UDP packets on destination port 5005 with `ip_dscp=46`, applying the action `OFPActionSetQueue(2)`. Rule Priority 50 steers normal DSCP 0 reports into Queue 1, while Priority 10 dumps all background bulk traffic into Queue 0.*  
  > *In the underlying data plane, we configure Open vSwitch with Linux Hierarchical Token Bucket (HTB) queues across our 10 Mbps bottleneck link. Queue 2 has a guaranteed 5 Mbps min-rate reserved exclusively for critical alerts. When background traffic saturates the link, Queue 0 packets are dropped by the kernel, while our critical Queue 2 flows through untouched.*  
  > *Now, I will conduct a quick live demonstration of our test suite and running server before Member 3 presents our failure detection and benchmark results."*

---

### 🖥️ Live Demonstration Interlude (Led by Member 2):
1. **Show automated tests:** Run `pytest tests/ -v` (point out: *"60 tests passed with 87% coverage"*).
2. **Launch Server & Agent:** Run `python3 server/monitor_server.py --port 5005` in Terminal 1, and `python3 agent/health_agent.py --id h1 --server 127.0.0.1 --port 5005 --mode real` in Terminal 2. Show live ASCII dashboard refreshing.
3. **Trigger Critical Spike:** Run `python3 agent/health_agent.py --id h2 --server 127.0.0.1 --port 5005 --mode simulated --sim-pattern spike` in Terminal 3. Point out: *"Notice that h2 triggers `[ALERT] [CRITICAL]` in sub-millisecond time with DSCP 46 tagging."*

---

### 🔄 Transition to Member 3:
> **Member 2 says:** *"Now that we've seen the server and SDN architecture running live, I'll hand over to **Member 3 (`PES2UG25CS620`)**, who will explain our failure detection algorithms and present our empirical benchmark findings."*

---

### Slide 6: Failure Detection · When a Node Stops Reporting
**Speaker: Member 3 (`PES2UG25CS620`)**

* **Visual on Screen:** Sequence gap and silence tracking formulas, state transition logic, and Measured Failure Results table (`agent_crash: 1.07s`, `link_failure: 3.30s`, `partial_loss: 3.31s`, `recovery: <0.05s`).
* **Key Talking Points:**
  1. **Sequence Gap Tracking:** Loss is calculated strictly from sequence number deltas: $\text{gap} = seq - last\_seq - 1$. Duplicates and out-of-order packets are isolated and accounted for without corrupting loss metrics.
  2. **Silence Evaluation:** The server evaluates node liveness every 0.5s. If silence exceeds $3.0 \times \text{interval}$ (3 seconds for 1s interval), the node transitions to `DOWN` state and emits `NODE_DOWN`.
  3. **Disambiguating Crashes vs. Link Cuts:**
     - **Agent Crash:** Process terminates abruptly. Upon restart, its sequence number resets to 0 or 1, triggering a `NODE_RESTARTED` state.
     - **Link Cut:** Agent keeps running and incrementing sequence numbers, but the network drops packets. Upon link reconnection, a large sequence gap is detected, correctly reporting packet loss.
  4. **Empirical Time-to-Detect (TTD):**
     - Agent crash detected in **1.07 seconds**.
     - Link cuts and partial loss detected in **3.30 seconds** (matching $3 \times \text{interval}$).
     - Recovery detected in **under 0.05 seconds** on the very first resumed packet.
* **Verbatim Script:**
  > *"Thank you. On Slide 6, we examine how our system reliably detects node and network failures.*  
  > *Since UDP is connectionless, the server cannot rely on TCP FIN or RST flags. Instead, our `NodeRegistry` implements dual-mode sequence tracking and silence monitoring. Loss is calculated by tracking sequence gaps: if packet sequence jumps from 10 to 14, three packets were lost.*  
  > *To handle silence, the server checks timestamps every 500 ms. If no report is received within 3 times the reporting interval—3.0 seconds—the node is declared `DOWN`.*  
  > *Our system cleanly distinguishes an agent crash from a physical link cut: when an agent crashes and restarts, its sequence counter resets to zero, firing a `NODE_RESTARTED` event. During a link cut, the agent keeps counting; when the link recovers, the server observes the sequence gap and computes exact packet loss.*  
  > *Across five empirical benchmark trials, agent crashes were detected in just 1.07 seconds, link cuts in 3.30 seconds, and recovery occurred in under 50 milliseconds upon receiving the first resumed datagram."*

---

### Slide 7: Results · What the Data Tells Us
**Speaker: Member 3 (`PES2UG25CS620`)**

* **Visual on Screen:** Benchmark figures (`congestion_comparison.png`, `latency_distribution.png`), Baseline cards (0.257 ms mean delay), Priority Routing ON cards (0.00% loss, 1.48 ms p95 delay), and Scale cards (5–80 nodes, <0.7 ms delay, <5% CPU).
* **Key Talking Points:**
  1. **Baseline Latency:** In normal conditions, mean one-way telemetry delay is **0.32 ms** and alert latency is **0.26 ms** ($0.43\text{ ms}$ at p95).
  2. **Congestion Stress Test (12 Mbps flood over 10 Mbps bottleneck):**
     - **Priority OFF (Standard UDP):** Suffers **56.67% critical packet loss** and an average p95 latency of **30.75 ms**.
     - **Priority ON (SDN OpenFlow QoS):** Achieves **0.00% critical packet loss** and reduces p95 latency to **1.48 ms**—a **95.2% latency reduction**.
  3. **Scalability Evaluation (5 to 80 Nodes):** Tested at 1.0s and 0.5s intervals (up to 184.2 packets/sec). Zero packet loss, latency stays below 0.7 ms, and server CPU utilization remains $< 5.0\%$.
* **Verbatim Script:**
  > *"On Slide 7, we present the empirical proof from our benchmark experiments.*  
  > *In our baseline experiments, telemetry latency was consistently under 1 millisecond, with a mean delay of 0.32 milliseconds and alert response latency of 0.26 milliseconds.*  
  > *The defining experiment of our project is the Congestion Stress Test. We injected a 12 Mbps UDP traffic flood across our 10 Mbps bottleneck link using iperf.*  
  > *As shown in the left bar chart, without SDN priority, standard UDP collapses: 56.67% of critical health alerts were dropped, and p95 latency jumped to 30.75 milliseconds. But when our OpenFlow QoS rules were active—shown in the right bar chart—critical alert loss was exactly 0.00%, and latency dropped to 1.48 milliseconds—a 95.2% latency improvement!*  
  > *Finally, our scalability tests scaled from 5 to 80 nodes transmitting 184.2 packets per second. The server handled the load with zero dropped packets and under 5% CPU utilization."*

---

### Slide 8: What We Built · What We Learned (Conclusion)
**Speaker: Member 3 (`PES2UG25CS620`)**

* **Visual on Screen:** Summary cards, terminal commands to run, test suite highlights (60 passed, 87% coverage), and key takeaways.
* **Key Talking Points:**
  1. **Core Takeaway:** Proved that pairing lightweight UDP with OpenFlow 1.3 traffic engineering delivers the speed of UDP with the deterministic reliability of enterprise QoS.
  2. **Software Engineering Rigor:** Built with modular layered architecture, comprehensive error guards, and validated by 60 automated unit and integration tests with 87% code coverage.
  3. **Thank the Teacher:** Conclude the presentation and invite questions for viva.
* **Verbatim Script:**
  > *"To conclude on Slide 8: What we built and what we learned.*  
  > *Through this project, our team proved that lightweight UDP datagrams become enterprise-grade when augmented by software-defined networking. Sequence tracking and silence timeouts provide fault visibility without connection overhead, while OpenFlow 1.3 and OVS HTB queues ensure that life-critical telemetry is never dropped during network congestion.*  
  > *Our codebase is verified by 60 automated unit, integration, and robustness tests with 87% test coverage.*  
  > *Thank you, Professor. We are now ready to demonstrate any component or answer your viva questions."*

---

## 5.3 Live Demonstration Coordination Runbook

During the live evaluation, execute this seamless 5-step sequence:

```
+---------------------------------------------------------------------------------------+
|                                LIVE DEMO COORDINATION                                 |
+---------------------------------------------------------------------------------------+
| Step 1: Proof of Rigor       | Member 2 runs `pytest tests/ -v`                       |
|                              | Member 1 explains test suite breadth & 87% coverage    |
+------------------------------+--------------------------------------------------------+
| Step 2: Live Ingestion       | Member 2 launches `monitor_server.py` & agent `h1`     |
|                              | Member 2 explains ASCII table & select multiplexing    |
+------------------------------+--------------------------------------------------------+
| Step 3: Critical Spike Alert | Member 2 launches agent `h2` with `--sim-pattern spike`|
|                              | Member 2 highlights DSCP 46 & sub-ms alert latency     |
+------------------------------+--------------------------------------------------------+
| Step 4: Failure Detection    | Member 2 kills `h1` (`Ctrl+C`); restarts after 4s      |
|                              | Member 3 explains 3s silence timeout & recovery log    |
+------------------------------+--------------------------------------------------------+
| Step 5: Benchmark Graphs     | Member 3 opens `results/congestion_comparison.png`     |
|                              | Member 3 quotes 56.67% vs 0% loss & 95.2% delay cut    |
+---------------------------------------------------------------------------------------+
```

### Exact Commands for Terminal Operator (Member 2):
```bash
# Step 1: Run complete automated test suite
pytest tests/ -v --cov=common --cov=server --cov=agent

# Step 2: Launch Central Monitoring Server in Terminal 1
python3 server/monitor_server.py --port 5005

# Step 3: Launch Normal Agent in Terminal 2
python3 agent/health_agent.py --id h1 --server 127.0.0.1 --port 5005 --interval 1.0 --mode real

# Step 4: Launch Spiking Agent in Terminal 3
python3 agent/health_agent.py --id h2 --server 127.0.0.1 --port 5005 --interval 1.0 --mode simulated --sim-pattern spike

# Step 5: View Congestion Comparison Graph
xdg-open results/congestion_comparison.png
```

---

## 5.4 Team Viva Defense: Assigned Examiner Questions & Expert Answers

Each member should master the questions aligned with their project domain:

### Domain 1: Transport, Protocol & Agent Telemetry (Assigned to Member 1: `PES2UG25CS609`)

#### Q1: Why did you choose UDP instead of TCP or WebSockets for health monitoring?
> **Member 1 Answer:**  
> *"TCP and WebSockets introduce significant connection overhead: SYN/ACK three-way handshakes, persistent socket state on the server, and keepalive traffic. More critically, TCP suffers from **head-of-line blocking**. If an intermediate packet is lost in TCP, the operating system kernel buffers subsequent packets until the missing one is retransmitted, delaying time-critical health alerts.  
> UDP is stateless, connectionless, and has an 8-byte header compared to TCP's 20-byte minimum header. By combining UDP with OpenFlow SDN prioritization, we obtain the low latency of UDP while guaranteeing the delivery of critical alerts at the network switch."*

#### Q2: Why is the packet payload restricted to 1400 bytes?
> **Member 1 Answer:**  
> *"Standard Ethernet frames have a Maximum Transmission Unit (MTU) of 1500 bytes. Subtracting the 20-byte IPv4 header and the 8-byte UDP header leaves an absolute maximum payload of 1472 bytes.  
> If a UDP datagram exceeds 1472 bytes, the IP layer fragments it into multiple IP packets. If even one fragment is lost, the entire datagram is dropped. Limiting our serialized JSON payload to 1400 bytes leaves a 72-byte safety margin for optional IP options or VLAN tags, guaranteeing that our packets are never fragmented."*

#### Q3: How do you prevent timer drift on long-running monitoring agents?
> **Member 1 Answer:**  
> *"Naive monitoring scripts use `time.sleep(interval)`, which causes cumulative timing drift because the code execution time (reading CPU, serializing JSON, network send) adds to the sleep duration.  
> In `health_agent.py`, we use monotonic clock scheduling (`time.monotonic()`). We record a fixed target next-run timestamp (`next_tick = start_time + tick * interval`) and dynamically sleep only for `max(0, next_tick - time.monotonic())`. This guarantees a consistent 1.0 Hz reporting cadence without drift."*

#### Q4: What happens if an agent fails to read hardware metrics via `psutil`?
> **Member 1 Answer:**  
> *"If `psutil` raises an exception—due to permission restrictions or OS kernel call failures—the agent does not crash. In `stats_collector.py`, exceptions are caught gracefully and the agent falls back to generating a lightweight `HEARTBEAT` message with null metrics. This ensures the central server knows the host is still alive and does not trigger a false `NODE_DOWN` alarm."*

---

### Domain 2: Core Server Engine, Hysteresis & OpenFlow SDN QoS (Assigned to Member 2: `PES2UG25CS642` / Technical Lead)

#### Q5: Why use POSIX `select` multiplexing instead of multi-threading or `asyncio`?
> **Member 2 Answer:**  
> *"A thread-per-client or thread-per-packet model incurs substantial OS kernel thread-scheduling overhead, memory consumption for thread stacks (typically 8MB per thread by default), and synchronization locks. In UDP monitoring, datagrams arrive sporadically and handle fast processing.  
> By using POSIX `select.select()` on a single non-blocking UDP socket, a single thread can inspect readiness and drain the receive buffer immediately. Our scalability benchmarks prove this architecture handles 80 nodes transmitting 184 packets per second with under 5% server CPU utilization."*

#### Q6: UDP headers do not have a priority field. How does Open vSwitch know which packet is critical?
> **Member 2 Answer:**  
> *"We classify packets at Layer 3 using the **IPv4 Type of Service (TOS) / DSCP (Differentiated Services Code Point)** header field.  
> When our agent evaluates that a metric crosses a critical threshold, it calls `sock.setsockopt(socket.IPPROTO_IP, socket.IP_TOS, 0xB8)`. DSCP occupies the 6 most significant bits of the TOS byte; binary `10111000` is decimal 184 (`0xB8`), which represents **DSCP 46 (Expedited Forwarding - EF)**.  
> OpenFlow 1.3 natively supports the `ip_dscp` match field. The switch matches `eth_type=0x0800, ip_proto=17, udp_dst=5005, ip_dscp=46` at wire speed without inspecting application payloads, and applies `OFPActionSetQueue(2)`."*

#### Q7: How does OpenFlow `set_queue` translate into physical bandwidth guarantees on Linux?
> **Member 2 Answer:**  
> *"OpenFlow standardizes the `set_queue` action, but the physical queue scheduling is executed by the Linux kernel's **Hierarchical Token Bucket (HTB)** traffic control (`tc`) subsystem.  
> In `sdn/topology.py`, we configure Open vSwitch port `s1-eth1` with three HTB classes:  
> - Queue 2 (Critical) has a minimum guaranteed rate of 5 Mbps and a maximum of 10 Mbps.  
> - Queue 1 (Normal) has a minimum guaranteed rate of 3 Mbps.  
> - Queue 0 (Best-Effort) has a minimum guaranteed rate of 1 Mbps.  
> Under network congestion, HTB guarantees Queue 2 its 5 Mbps token allocation, dropping lower-priority packets in Queue 0 when intermediate ring buffers fill up."*

#### Q8: What is alert hysteresis and cooldown, and why are they necessary?
> **Member 2 Answer:**  
> *"In monitoring systems, **alert flapping** occurs when a fluctuating metric hovers around a static threshold. For example, if CPU oscillates between 69.9% and 70.1% around a 70% threshold, a naive system emits alarms and clears alarms continuously every second.  
> In `server/alert_engine.py`, we implemented a **2% hysteresis deadband**: an alert triggers when CPU $\ge 70\%$, but clears only when CPU drops strictly below $70\% - 2\% = 68\%$. Additionally, our 5.0-second cooldown suppresses duplicate alerts for the same condition, ensuring clear and actionable incident logging."*

#### Q9: How do you measure one-way delay accurately if clocks might not be synchronized?
> **Member 2 Answer:**  
> *"In our Mininet network emulation, all virtual hosts run as lightweight network namespaces on the same underlying Linux kernel, meaning they share the identical physical system clock (`time.time()`). Thus, $\text{recv\_ts} - \text{sent\_ts}$ accurately captures propagation and queueing delay without NTP clock drift.  
> For real-world production networks where NTP clock skews can occur, our server code implements clamping: any calculated negative delay is bounded to $0.0\text{ ms}$ with an anomaly warning."*

---

### Domain 3: Failure Analysis, Empirical Benchmarks & Scalability (Assigned to Member 3: `PES2UG25CS620`)

#### Q10: How do you distinguish between an agent process crash and a network link failure?
> **Member 3 Answer:**  
> *"Both conditions cause packet silence at the server, but their root causes and recovery signatures are distinct:  
> 1. In an **Agent Process Crash**, the agent terminates. When it restarts, its sequence counter resets to 0. Our `NodeRegistry` detects this reset and emits a `NODE_RESTARTED` event.  
> 2. In a **Network Link Failure**, the agent continues running in the background, incrementing sequence numbers. When the link recovers, the server receives a packet with a large sequence jump ($\text{gap} = seq - last\_seq - 1$). The server calculates exact packet loss percentage during the outage and transitions the node back to healthy."*

#### Q11: Why did Priority OFF drop 56.67% of critical traffic, while Priority ON dropped 0%?
> **Member 3 Answer:**  
> *"In our congestion experiment, we configured a 10 Mbps bottleneck link between Open vSwitch and the server, and flooded it with 12 Mbps of background UDP traffic using `iperf`.  
> When Priority was **OFF**, all traffic shared a single FIFO buffer. Because the aggregate traffic (12 Mbps + telemetry) exceeded link capacity, the switch buffer experienced persistent tail-drop, dropping 56.67% of critical alert packets.  
> When Priority was **ON**, OpenFlow steered DSCP 46 packets to Queue 2, which has a 5 Mbps guaranteed rate. The switch buffer dropped background packets from Queue 0 while preserving Queue 2, achieving **0.00% critical packet loss** and reducing p95 latency from 30.75 ms to 1.48 ms."*

#### Q12: How did you benchmark 80 nodes on a single machine without crashing the host?
> **Member 3 Answer:**  
> *"Because our health agent is designed with minimal resource consumption (only 420-byte wire size and low CPU usage) and the central server uses non-blocking POSIX `select` multiplexing on a single thread, running 80 lightweight agent processes consumes under 150 MB of RAM combined.  
> In `experiments/run_scalability_test.py`, we benchmarked $N = 5, 10, 20, 40, \text{and } 80$ nodes, demonstrating linear throughput scaling up to 184.2 packets/sec with 0.0% packet loss and under 5% server CPU utilization."*

#### Q13: How does the server handle duplicate or out-of-order packets?
> **Member 3 Answer:**  
> *"In `server/node_registry.py`, we maintain `last_seq` for each registered node:  
> - If $seq == last\_seq$, the datagram is flagged as a duplicate, logged in a duplicate counter, and discarded.  
> - If $seq < last\_seq$ and $seq > 1$, it is recognized as out-of-order; the `out_of_order` counter increments without corrupting the `lost_packets` counter.  
> - If $seq > last\_seq + 1$, the delta is computed as lost packets: $\text{gap} = seq - last\_seq - 1$."*

---

## 5.5 Key Empirical Metrics Cheat Sheet for Viva

Memorize these exact figures from our evaluation runs to quote with confidence:

| Performance Metric | Measured Value | Academic & Engineering Significance |
|---|---|---|
| **Test Suite Pass Rate** | **60 / 60 Passed (100%)** | Validated across protocol, agent, server, alert engine, and SDN modules |
| **Code Coverage** | **87% Overall Coverage** | Exceeds university requirements across all 8 rubric criteria |
| **Baseline Telemetry Delay** | **0.32 ms mean**, **0.45 ms p95** | Sub-millisecond latency on local link |
| **Baseline Alert Latency** | **0.26 ms mean**, **0.43 ms p95** | Time elapsed from host metric spike to server alert generation |
| **Congestion Critical Loss (No SDN)** | **56.67% ± 10.27%** | Standard UDP drops over half of critical alerts during 12 Mbps flood |
| **Congestion Critical Loss (With SDN)** | **0.00% ± 0.00%** | OpenFlow 1.3 QoS completely insulates critical alerts |
| **Congestion p95 Latency Reduction** | **30.75 ms $\to$ 1.48 ms** | **95.2% latency reduction** achieved under link saturation |
| **Agent Crash Time-to-Detect (TTD)** | **1.07 ± 0.04 seconds** | Rapid identification of process termination |
| **Link Cut Time-to-Detect (TTD)** | **3.30 ± 0.00 seconds** | Matches exact $3.0 \times \text{interval}$ silence threshold |
| **Recovery Time (TTR)** | **< 0.05 seconds** | Immediate state restoration upon receiving first resumed packet |
| **Maximum Scalability Tested** | **80 Nodes (184.2 pkts/sec)** | Handled with **0.0% loss** and $< 5\%$ server CPU utilization |
| **Per-Agent Wire Bandwidth** | **3.36 kbps per agent** | Negligible network overhead at 1-second reporting intervals |

