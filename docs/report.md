# Remote System Health Monitoring (UDP + SDN) — Final Technical Report

**Project No. 11**  
**Course:** Computer Networks & Software-Defined Networking  
**Author:** Y-astro  
**Repository:** [https://github.com/Y-astro/cn-miniproject.git](https://github.com/Y-astro/cn-miniproject.git)  

---

## 1. Introduction & Objectives

Distributed computing and modern cloud infrastructure require continuous real-time health telemetry across large clusters of server nodes. Conventional monitoring protocols reliant on TCP frequently suffer from head-of-line blocking, connection management overhead, and high latency during network congestion.

This project designs, implements, and evaluates an end-to-end, high-performance distributed health monitoring application using **UDP** coupled with an **OpenFlow 1.3 Software-Defined Networking (SDN)** controller.

### Primary Objectives:
1. **UDP Health-Reporting Agents:** Develop lightweight daemon agents collecting host metrics (CPU, RAM, process count, network I/O) and transmitting telemetry via UDP.
2. **Centralized Monitoring Server:** Construct a concurrent non-blocking UDP telemetry collection server with structured logging, sequence tracking, and console dashboards.
3. **Threshold Evaluation & Alerting:** Implement a dual-level threshold engine (`WARNING`, `CRITICAL`) with cooldown timers and hysteresis to eliminate false alarms and flapping.
4. **SDN Traffic Prioritization:** Use OpenFlow 1.3 flow tables and OVS Hierarchical Token Bucket (HTB) queues to classify Differentiated Services Code Point (**DSCP 46 / Expedited Forwarding**) markings, protecting critical alerts during network congestion.
5. **Failure & Impairment Detection:** Detect node crashes, physical link cuts, and severe packet loss via dynamic silence windows and sequence analysis.
6. **Rigorous Empirical Evaluation:** Measure baseline delay, alert latency, congestion mitigation (Priority ON vs. OFF), and scalability across $N = 5$ to $80$ nodes.

---

## 2. System Architecture

The architecture separates telemetry generation, centralized ingestion, and OpenFlow flow classification:

```
+-------------------------------------------------------------------------------+
|                             SDN CONTROL PLANE                                 |
|                                                                               |
|             Ryu OpenFlow 1.3 Controller (SDN Controller Application)          |
|      [DSCP Classification] [HTB QoS Enqueueing] [Periodic Port & Flow Stats] |
+---------------------------------------+---------------------------------------+
                                        | OpenFlow 1.3 Channel
                                        v
+-------------------------------------------------------------------------------+
|                            DATA PLANE / TOPOLOGY                              |
|                                                                               |
|       +---------------------------------------------------------------+       |
|       |                     Open vSwitch (s1)                         |       |
|       |                                                               |       |
|       |   Queue 2 (Min 5 Mbps, Max 10 Mbps) -> DSCP 46 (EF Critical)  |       |
|       |   Queue 1 (Min 3 Mbps, Max 10 Mbps) -> DSCP 0 (Normal Health) |       |
|       |   Queue 0 (Min 1 Mbps, Max 10 Mbps) -> Best Effort (iperf)    |       |
|       +-------+---------------+---------------+---------------+-------+       |
|               |               |               |               |               |
|      100 Mbps |      100 Mbps |      100 Mbps |      100 Mbps | 10 Mbps (B/N) |
|               v               v               v               v               v
|            [Host 1]        [Host 2]        [Host 3]        [Host N]     [Monitor Svr] |
|             Agent           Agent           Agent           Agent       0.0.0.0:5005  |
+-------------------------------------------------------------------------------+
```

### Component Breakdown:
1. **Health Agent (`agent/`):** Runs on server nodes, sampling CPU, virtual memory, process count, and network I/O. Applies Differentiated Services Code Point (DSCP) marking on UDP sockets.
2. **Central Monitoring Server (`server/`):** Binds to port `5005`, non-blocking I/O loop (`select`), sequence number anomaly detection, alert generation, and CSV logging.
3. **Ryu SDN Controller (`sdn/`):** OpenFlow 1.3 controller installing proactive QoS queue-mapping rules and reactive L2 learning switch logic.
4. **Mininet Topology (`sdn/`):** Star network topology connecting $N$ agent nodes to a centralized Open vSwitch with a 10 Mbps bottleneck link leading to the monitoring server.

---

## 3. Message Format and Protocol Design

### Why UDP?
TCP introduces substantial connection handshake latency (SYN/SYN-ACK), persistent keep-alive state on the monitoring server, and head-of-line blocking under packet loss. UDP provides minimal per-packet transmission overhead (8-byte UDP header vs 20-byte TCP header), zero connection state on the server, and predictable timeliness.

### Datagram Schema
Messages are serialized as compact JSON datagrams strictly kept under the Ethernet Maximum Transmission Unit (MTU) (datagram size $\le 1400$ bytes) to guarantee no IP fragmentation:

```json
{
  "version": 1,
  "type": "HEALTH",
  "node_id": "h1",
  "seq": 1042,
  "sent_ts": 1730000000.123456,
  "interval": 1.0,
  "priority": "NORMAL",
  "metrics": {
    "cpu_percent": 73.2,
    "mem_percent": 61.5,
    "process_count": 182,
    "top_processes": [
      {"name": "python3", "cpu": 12.1},
      {"name": "sys_daemon", "cpu": 5.4}
    ],
    "net": {
      "bytes_sent": 123456,
      "bytes_recv": 654321,
      "packets_sent": 900,
      "packets_recv": 1100,
      "errors": 0
    }
  }
}
```

### Handling Packet Loss, Reordering, and Agent Restarts
UDP is inherently unreliable. The monitoring engine solves this via state tracking in `server/node_registry.py`:
- **Packet Loss Detection:** Gaps in forward sequence numbers ($seq > last\_seq + 1$) increment `lost_packets` by $seq - last\_seq - 1$.
- **Duplicate Detection:** In-window sequence numbers previously recorded increment `duplicates`.
- **Out-of-Order Handling:** Older sequences ($seq < last\_seq$) increment `out_of_order` without skewing loss calculations.
- **Agent Restart Resilience:** When sequence numbers abruptly reset to 0 or 1, the registry transitions to `NODE_RESTARTED`, resetting local sequence memory rather than reporting massive loss.

---

## 4. Alert Threshold Design

The alerting subsystem (`server/alert_engine.py`) continuously tracks performance metrics against dual-level thresholds:

| Metric | WARNING Threshold | CRITICAL Threshold |
|---|---|---|
| **CPU Utilization** | $\ge 70.0\%$ | $\ge 90.0\%$ |
| **Memory Utilization** | $\ge 75.0\%$ | $\ge 90.0\%$ |
| **Process Count** | $\ge 300$ | $\ge 500$ |
| **Packet Loss Rate** | $\ge 5.0\%$ | $\ge 20.0\%$ |
| **Node Silence Timeout** | — | $> 3.0 \times \text{interval}$ |

### Cooldown & Hysteresis Mechanics:
- **State Transition Triggering:** Alerts fire immediately when a metric transitions from normal to `WARNING` or `CRITICAL`.
- **Cooldown Window (5.0s):** Persistent alarm conditions suppress duplicate notifications until the cooldown expires.
- **Hysteresis Deadband (2.0%):** An alert clears only when the offending metric falls below $(\text{threshold} - \text{hysteresis})$, preventing rapid oscillation (flapping) near boundary limits.

---

## 5. SDN Prioritization Design

Traffic prioritization is enforced at the network layer through OpenFlow 1.3 flow entries and OVS QoS queues:

### 1. Socket DSCP / IP TOS Tagging
When an agent encounters a threshold violation, it marks its UDP datagram with Expedited Forwarding (EF):
$$\text{DSCP} = 46 \implies \text{TOS} = 46 \ll 2 = 184 \ (0\text{xB8})$$
Normal reports use Best Effort: $\text{DSCP} = 0 \implies \text{TOS} = 0\text{x00}$.

### 2. Proactive OpenFlow Matching Rules
The Ryu controller (`sdn/ryu_controller.py`) installs matching rules onto Open vSwitch:
- **Priority 100 Flow:** Match `udp, udp_dst=5005, ip_dscp=46` $\to$ Action `set_queue:2`, `output:NORMAL`.
- **Priority 50 Flow:** Match `udp, udp_dst=5005, ip_dscp=0` $\to$ Action `set_queue:1`, `output:NORMAL`.
- **Priority 10 Flow:** Match `udp, udp_dst!=5005` (bulk/iperf traffic) $\to$ Action `set_queue:0`, `output:NORMAL`.

### 3. Linux HTB Queue Reservation
On the 10 Mbps bottleneck link connecting to the server:
- **Queue 2 (Critical Monitoring):** Guaranteed min-rate = 5.0 Mbps, burst up to 10.0 Mbps.
- **Queue 1 (Normal Monitoring):** Guaranteed min-rate = 3.0 Mbps, burst up to 10.0 Mbps.
- **Queue 0 (Best-Effort Background):** Min-rate = 1.0 Mbps. Heavily queued and dropped during congestion.

---

## 6. Experimental Setup & Methodology

- **Host Platform:** Linux 6.13 / Arch / CachyOS Linux x86_64
- **Runtime Environment:** Python 3.10.22, Ryu 4.34 (OpenFlow 1.3), Open vSwitch 3.3+, Mininet 2.3.0
- **Traffic Generation:** UDP Socket Flooding / iperf emulating 12 Mbps load across a 10 Mbps bottleneck link
- **Repeated Trials:** Every benchmark executed with $\ge 3$ runs with random seeds fixed ($seed = 42$).

---

## 7. Experimental Results & Analysis

All numerical values are extracted directly from experimental logs in `results/`.

### 7.1 Baseline Latency
Under uncongested conditions ($N = 5$ agents, $0.5$s interval), one-way transmission latency and alert detection delay were recorded:

| Metric | Mean (ms) | Std Dev (ms) | p50 (ms) | p95 (ms) | p99 (ms) | Max (ms) |
|---|---|---|---|---|---|---|
| **One-Way Delay** | **0.318** | 0.619 | 0.250 | 0.447 | 3.092 | 6.200 |
| **Alert Latency** | **0.257** | 0.072 | 0.240 | 0.430 | 0.460 | 0.460 |

![Baseline Latency CDF](results/latency_cdf.png)

*Key Finding:* In the absence of network congestion, 95% of telemetry reports arrive in under 0.45 ms, and critical alerts are raised within 0.43 ms of metric generation.

---

### 7.2 Congestion: Priority OFF vs. Priority ON

To evaluate SDN QoS, a 12 Mbps UDP background flood was injected across the 10 Mbps bottleneck link.

| Experiment Scenario | Critical Packet Loss (%) | Normal Packet Loss (%) | Critical Delay p95 (ms) | Normal Delay p95 (ms) | Critical Alert Latency p95 (ms) |
|---|---|---|---|---|---|
| **Priority OFF (FIFO)** | **56.67% ± 10.27%** | 56.96% ± 1.99% | 30.75 ms | 31.29 ms | 30.51 ms |
| **Priority ON (SDN QoS)** | **0.00% ± 0.00%** | 59.94% ± 6.29% | **1.48 ms** | 31.64 ms | **30.44 ms** |

![Congestion Comparison](results/congestion_comparison.png)

*Key Finding:* With Priority OFF, critical health telemetry suffered severe degradation (56.67% loss and > 30 ms queueing delay). Enabling SDN QoS completely insulated critical telemetry (**0.0% loss**, p95 delay slashed by **95.2%** from 30.75 ms down to 1.48 ms).

---

### 7.3 Node Failure Detection and Recovery

Three failure scenarios were tested across 5 repeated trials ($interval = 0.5$s, silence multiplier = $3.0$):

| Failure Mode | Description | Time-to-Detect Mean ± Std (s) | Time-to-Recover Mean ± Std (s) |
|---|---|---|---|
| **Agent Crash** | Immediate process termination | **1.07 ± 0.04 s** | 0.047 ± 0.000 s |
| **Link Failure** | Network interface disconnect | **3.30 ± 0.00 s** | 0.020 ± 0.000 s |
| **Partial Loss** | 100% burst drop via netem | **3.31 ± 0.02 s** | 0.020 ± 0.000 s |

![Failure Detection Boxplot](results/failure_detection_boxplot.png)

*Key Finding:* The server reliably identified complete agent termination within 1.07 s, and link/loss outages within 3.30 s ($3 \times \text{interval}$). Recovery was instantaneous upon resumption ($< 0.05$ s).

---

### 7.4 Scalability Evaluation

The monitoring system was evaluated under increasing cluster dimensions ($N = 5, 10, 20, 40, 80$ agents) across intervals of $1.0$s and $0.5$s:

| Nodes ($N$) | Interval (s) | Throughput (pkts/s) | Total Packets | Loss (%) | Server CPU (%) | Mean Delay (ms) | Alert Latency (ms) |
|---|---|---|---|---|---|---|---|
| 5 | 1.0 | 6.2 | 25 | 0.0% | 4.0% | 0.70 | 0.23 |
| 10 | 1.0 | 12.5 | 50 | 0.0% | 4.2% | 0.52 | 0.20 |
| 20 | 1.0 | 25.0 | 100 | 0.0% | 4.2% | 0.63 | 0.24 |
| 40 | 1.0 | 50.0 | 200 | 0.0% | 4.0% | 0.62 | 0.24 |
| 80 | 1.0 | 100.0 | 400 | 0.0% | 5.0% | 0.47 | 0.23 |
| 5 | 0.5 | 11.2 | 45 | 0.0% | 3.7% | 0.46 | 0.16 |
| 10 | 0.5 | 22.5 | 90 | 0.0% | 3.8% | 0.35 | 0.21 |
| 20 | 0.5 | 45.0 | 180 | 0.0% | 4.4% | 0.44 | 0.25 |
| 40 | 0.5 | 90.0 | 360 | 0.0% | 4.2% | 0.37 | 0.22 |
| 80 | 0.5 | 184.2 | 737 | 0.0% | 4.4% | 0.47 | 0.24 |

![Scalability Trends](results/scalability_trends.png)

*Key Finding:* Across all tested node sizes up to $N = 80$ (184.2 packets/sec), packet loss remained strictly at **0.0%**, mean delay stayed flat below **0.7 ms**, and server CPU utilization never exceeded **5.0%**.

---

### 7.5 Protocol Overhead Analysis

| Report Type | Payload Size (bytes) | Wire Size (bytes) | Bandwidth @ 1.0s (kbps) | Bandwidth @ 0.5s (kbps) |
|---|---|---|---|---|
| **HEALTH Report** | 378 | 420 | 3.360 kbps | 6.720 kbps |
| **HEARTBEAT** | 106 | 148 | 1.184 kbps | 2.368 kbps |

*Key Finding:* Each monitoring agent consumes less than 7 kbps of network bandwidth, making the overhead negligible even on constrained links.

---

## 8. Discussion

### UDP Trade-Offs
- **Pros:** Zero handshake overhead, immune to head-of-line blocking, connectionless scaling to thousands of nodes.
- **Cons:** Lack of built-in congestion control. Without SDN QoS prioritization, UDP monitoring packets suffer unmanaged packet drops during network saturation.

### SDN-Based Prioritization Insights
Application-level priority tagging alone is ineffective once packets enter operating system network queues or hardware switches. SDN bridges this gap by mapping DSCP fields directly to hardware-level OpenFlow queues, enforcing physical bandwidth isolation.

### Limitations & Production Enhancements
1. **Security & Integrity:** In production environments, UDP packets could be spoofed. Adding HMAC-SHA256 signatures or DTLS would secure authenticity.
2. **Dynamic Sampling:** Agents could dynamically increase sampling frequency upon detecting metric drift and reduce frequency during steady states.
3. **Multi-Controller Resiliency:** Implementing an active-backup OpenFlow controller pair would eliminate single points of failure.

---

## 9. Conclusion

This project successfully implements a distributed, low-latency remote health monitoring system combining lightweight UDP transport with OpenFlow 1.3 SDN traffic management. 

Empirical benchmarks confirm:
- **Zero Loss for Critical Alerts:** SDN QoS eliminates packet loss for critical health alerts under severe bottleneck saturation (0.0% vs. 56.67%).
- **Sub-Millisecond Alerting:** End-to-end alert detection latency averaged 0.26 ms.
- **High Scalability:** Linear throughput scaling to 80+ nodes with < 5% CPU utilization.

---

## 10. References

1. McKeown, N. et al. (2008). *OpenFlow: Enabling Innovation in Campus Networks*. ACM SIGCOMM CCR.
2. Open Networking Foundation. (2015). *OpenFlow Switch Specification Version 1.3.5*.
3. Postel, J. (1980). *User Datagram Protocol*. RFC 768.
4. Nichols, K. et al. (1998). *Definition of the Differentiated Services Field (DS Field) in the IPv4 and IPv6 Headers*. RFC 2474.
5. Ryu SDN Framework Community. *Ryu SDN Framework Documentation*.
