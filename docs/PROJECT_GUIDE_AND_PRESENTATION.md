# Remote System Health Monitoring (UDP + SDN)
## Complete Technical Reference & Academic Presentation Guide

**Project No. 11 — Computer Networks & Software-Defined Networking**  
**Student Name:** Y-astro  
**Repository:** [https://github.com/Y-astro/cn-miniproject.git](https://github.com/Y-astro/cn-miniproject.git)  

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
5. [Teacher Presentation & Viva Defense Guide](#5-teacher-presentation--viva-defense-guide)
   - [5.1 The 30-Second Elevator Pitch](#51-the-30-second-elevator-pitch)
   - [5.2 5-Minute Structured Presentation Script](#52-5-minute-structured-presentation-script)
   - [5.3 Live Demonstration Runbook](#53-live-demonstration-runbook)
   - [5.4 Anticipated Viva/Examiner Questions & Expert Answers](#54-anticipated-vivaexaminer-questions--expert-answers)
   - [5.5 Key Numbers & Experimental Proof to Quote](#55-key-numbers--experimental-proof-to-quote)

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

# 5. Teacher Presentation & Viva Defense Guide

Use this section to prepare your project demonstration and answer questions from your professor or external examiner.

## 5.1 The 30-Second Elevator Pitch
> *"Good morning, Professor. My project is a **Distributed Remote System Health Monitoring application built with UDP and an OpenFlow 1.3 SDN controller**.*  
> *Traditional TCP monitoring suffers from head-of-line blocking and connection overhead, while raw UDP drops critical alerts when network links become congested. To solve this, my system marks critical telemetry packets using **DSCP 46 Expedited Forwarding**. A centralized **Ryu SDN controller** programs OpenFlow flow rules and OVS HTB queues to guarantee bandwidth for critical alerts. Under a 12 Mbps traffic flood across a 10 Mbps bottleneck, my system achieved **0.0% critical packet loss** and cut delay by **95.2%**, demonstrating how software-defined networking provides deterministic QoS for vital telemetry."*

---

## 5.2 5-Minute Structured Presentation Script

### Slide / Step 1: Motivation & Problem
- Cloud clusters need continuous health reporting (CPU, RAM, process count, network I/O).
- **The dilemma:** TCP is reliable but slow and prone to head-of-line blocking; UDP is fast and connectionless but drops packets when switches are congested.
- **Our Goal:** Deliver the speed of UDP while using **SDN OpenFlow 1.3** to physically guarantee delivery of high-priority alerts.

### Slide / Step 2: System Architecture
- **Agents:** Deployed on nodes, sampling `psutil` metrics and setting IP TOS socket options (`0xB8` for DSCP 46 EF).
- **Server:** Non-blocking I/O (`select`) server handling sequence tracking, packet loss calculations, hysteresis-based alert evaluation, and CSV logging.
- **SDN Controller:** Ryu controller managing Open vSwitch with 3 HTB QoS queues (Queue 2 for Critical, Queue 1 for Normal, Queue 0 for Best Effort).

### Slide / Step 3: Key Engineering Details
- **Sequence Tracking:** Detects loss from sequence number gaps, ignores duplicates, and gracefully handles agent restarts.
- **Hysteresis & Cooldown:** Eliminates alert flapping by requiring metrics to drop 2% below threshold before clearing.
- **MTU Safety:** JSON datagrams kept $\le 1400$ bytes to prevent IP packet fragmentation.

### Slide / Step 4: Experimental Results & Graphs
- **Baseline Latency:** One-way delay of $0.32\text{ ms}$, alert latency of $0.26\text{ ms}$.
- **Congestion Test:** Under bottleneck saturation, Priority OFF lost **56.67%** of critical packets; Priority ON achieved **0.0% loss** and reduced p95 latency from **30.75 ms to 1.48 ms**.
- **Scalability:** Successfully tested up to **80 nodes** ($184.2\text{ packets/s}$) with **0.0% loss** and $< 5\%$ server CPU utilization.

### Slide / Step 5: Conclusion
- Proved that SDN traffic engineering turns UDP into an enterprise-grade telemetry transport.
- Code is covered by 60 automated tests with 87% test coverage.

---

## 5.3 Live Demonstration Runbook

If your teacher asks for a live demo, follow these exact steps:

### Demo Step 1: Show the Automated Test Suite (Proof of Rigor)
Run in Terminal 1:
```bash
pytest tests/ -v
```
**Say to the teacher:**  
*"Professor, before running live traffic, here is our test suite. We have 60 automated unit and integration tests verifying protocol encoding, boundary thresholds, sequence gap loss detection, server socket resilience, and SDN failure scenarios, achieving 87% code coverage."*

### Demo Step 2: Live Server & Agent Communication
1. Open **Terminal 1**:
   ```bash
   python3 server/monitor_server.py --port 5005
   ```
2. Open **Terminal 2**:
   ```bash
   python3 agent/health_agent.py --id h1 --server 127.0.0.1 --port 5005 --interval 1.0 --mode real
   ```
3. Show Terminal 1: Point to the live dashboard updating every 2 seconds with `h1`'s real CPU and RAM.

### Demo Step 3: Trigger a Real-Time Alert
In **Terminal 3**, launch a spiking agent:
```bash
python3 agent/health_agent.py --id h2 --server 127.0.0.1 --port 5005 --interval 1.0 --mode simulated --sim-pattern spike
```
**Point to the screen and say:**  
*"Notice that when node `h2` generates a CPU spike above 90%, it marks the packet as CRITICAL. The server detects this in under 1 millisecond and logs a `[ALERT] [CRITICAL]` event with measured alert latency."*

### Demo Step 4: Demonstrate Failure Detection
Press `Ctrl+C` on `h1` in Terminal 2.  
Watch Terminal 1 for 3 seconds.  
**Point to the screen and say:**  
*"Because `h1` went silent for more than $3 \times \text{interval}$ (3 seconds), the server automatically flagged `[NODE FAILURE] Node 'h1' is DOWN!`. When I restart `h1`, it will immediately report `[NODE RECOVERY]`."*

### Demo Step 5: Show the Generated Graphs
Open the generated images in `results/`:
```bash
# View the congestion comparison chart
xdg-open results/congestion_comparison.png
```
**Point to the bar chart and explain:**  
*"Here is our empirical proof: without SDN prioritization (red bar on left), 56.7% of critical alerts are lost during network congestion. With our OpenFlow QoS rules enabled (red bar on right), critical packet loss drops to exactly 0.0%."*

---

## 5.4 Anticipated Viva/Examiner Questions & Expert Answers

### Q1: Why did you choose UDP instead of TCP for health monitoring?
> **Answer:**  
> *"TCP has connection overhead (SYN/ACK handshakes), per-connection socket memory on the server, and most importantly, **head-of-line blocking**. If one packet is lost in TCP, the receiver buffers subsequent packets until the missing one is retransmitted, delaying urgent alerts.  
> UDP is stateless and connectionless, delivering telemetry immediately. By pairing UDP with an SDN controller that prioritizes packets at the switch hardware level, we achieve the timeliness of UDP without suffering packet loss for critical alerts."*

---

### Q2: UDP headers don't have a priority field. How does the SDN switch know which packet is critical?
> **Answer:**  
> *"We utilize the **IPv4 Type of Service (TOS) / DSCP (Differentiated Services Code Point)** header field.  
> When our agent detects a critical threshold violation, it calls `setsockopt(IPPROTO_IP, IP_TOS, 0xB8)` on the UDP socket. This writes **DSCP 46 (Expedited Forwarding)** into the IP header.  
> The Ryu OpenFlow controller proactively installs an OpenFlow 1.3 rule matching `ip_dscp=46` and `udp_dst=5005`, and applies the action `set_queue(2)`, steering the packet into the high-priority queue."*

---

### Q3: What is the difference between an Agent Crash and a Link Failure in your project?
> **Answer:**  
> *"Both result in packet silence at the server, but their root cause and recovery mechanisms differ:  
> 1. In an **Agent Crash**, the process terminates abruptly (tested via `--fail-after`). When it recovers, its sequence number resets to 0, which our `NodeRegistry` detects as a `NODE_RESTARTED` event.  
> 2. In a **Link Failure**, the agent continues running and incrementing its sequence number, but packets are dropped by the network (simulated via Mininet `configLinkStatus down` or socket drops). When the link recovers, the server detects sequence gaps and computes packet loss percentage."*

---

### Q4: What is hysteresis in your alert engine and why is it necessary?
> **Answer:**  
> *"Hysteresis prevents **alert flapping**. If CPU utilization fluctuates between 69.9% and 70.1% around a 70% threshold, a naive system would fire and clear alerts every second.  
> With our 2% hysteresis deadband, an alert triggers at $\ge 70\%$, but only clears when CPU drops strictly below $70\% - 2\% = 68\%$. This stabilizes monitoring state."*

---

### Q5: How does OpenFlow QoS queueing work in Open vSwitch?
> **Answer:**  
> *"OpenFlow standardizes the `set_queue` action. The physical queue scheduling is implemented by the Linux kernel using **Hierarchical Token Bucket (HTB)** traffic control (`tc`).  
> In our topology script, we configure OVS on the switch egress port with 3 queues: Queue 0 has a 1 Mbps rate for background traffic, Queue 1 has 3 Mbps for normal health traffic, and Queue 2 has a guaranteed 5 Mbps min-rate for critical alerts. The switch enforces these rate limits and queue priorities at wire speed."*

---

### Q6: How do you measure one-way delay accurately if clocks might not be synchronized?
> **Answer:**  
> *"In our Mininet network emulation, all simulated virtual hosts run as network namespaces on the same physical Linux kernel, meaning they share the exact same system clock (`time.time()`). Therefore, `recv_ts - sent_ts` gives an exact one-way propagation and queueing delay without NTP skew. In our server code, we also include bounds checking to clamp any negative values caused by potential clock adjustments."*

---

### Q7: Why did you limit the packet payload to 1400 bytes?
> **Answer:**  
> *"The standard Maximum Transmission Unit (MTU) for Ethernet is 1500 bytes. Subtracting 20 bytes for the IPv4 header and 8 bytes for the UDP header leaves 1472 bytes of maximum payload. Limiting our JSON payload to 1400 bytes guarantees that no packet will ever be fragmented by IP, preventing fragmentation overhead and packet reassembly loss."*

---

## 5.5 Key Numbers & Experimental Proof to Quote

Memorize these exact figures from your evaluation to quote during your presentation:

1. **Test Suite:** **60 tests passed**, **87% overall code coverage**.
2. **Baseline One-Way Delay:** **0.32 ms mean**, **0.45 ms p95**.
3. **Baseline Alert Latency:** **0.26 ms mean**, **0.43 ms p95**.
4. **Congestion Impact on Critical Telemetry:**
   - **Priority OFF:** **56.67% packet loss**, **30.75 ms p95 delay**.
   - **Priority ON:** **0.00% packet loss**, **1.48 ms p95 delay** (*95.2% latency reduction*).
5. **Failure Detection Time:** **1.07 seconds** for agent crash, **3.30 seconds** for link cuts ($3 \times \text{interval}$).
6. **Scalability:** Benchmarked up to **80 nodes** ($184.2\text{ packets/sec}$) with **0.0% loss** and $< 5\%$ CPU utilization.
7. **Bandwidth Overhead:** Only **3.36 kbps per agent** at 1-second intervals.
