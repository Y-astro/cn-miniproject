# Viva Defense & Quick-Reference Cheat Sheet
### Project No. 11: Remote System Health Monitoring (UDP + SDN)

Keep this cheat sheet handy during your project evaluation and viva.

---

## 1. Project At A Glance (30-Second Summary)
- **Problem:** TCP health monitoring has connection overhead and head-of-line blocking under loss; naive UDP drops packets blindly under congestion.
- **Solution:** Telemetry over **UDP** where critical packets are tagged with **DSCP 46 (Expedited Forwarding)**. A **Ryu OpenFlow 1.3 controller** installs proactive flow entries on **Open vSwitch (OVS)** to steer DSCP 46 packets into a high-priority **Linux HTB QoS queue (5 Mbps guaranteed)** across a 10 Mbps bottleneck link.
- **Impact:** Eliminates packet loss for critical alerts under congestion (**0.0% loss vs. 56.7% loss** without SDN) and cuts 95th percentile delay by **95.2%**.

---

## 2. Technical Specifications & Constants

| Parameter | Value | Location in Code | Why this value? |
|---|---|---|---|
| **Protocol** | UDP (IPv4) | `common/protocol.py` | Minimal header (8B), zero handshake, no head-of-line blocking |
| **Server Port** | `5005` | `config.yaml` | Standard unprivileged UDP port |
| **Max Payload Size** | `1400 bytes` | `common/protocol.py` | Fits within 1500B Ethernet MTU (prevents IP fragmentation) |
| **DSCP Critical (EF)** | `46` (`0xB8` / 184 in TOS) | `agent/health_agent.py` | RFC 2474 Expedited Forwarding ($46 \ll 2 = 184 = 0\text{xB8}$) |
| **DSCP Normal (BE)** | `0` (`0x00` in TOS) | `agent/health_agent.py` | Best Effort (default class) |
| **OpenFlow Version** | OpenFlow 1.3 | `sdn/ryu_controller.py` | Supports `set_queue`, multi-table pipelines, flow meters |
| **Bottleneck Link** | `10 Mbps` | `sdn/topology.py` | Emulates physical edge/uplink bandwidth constraint |
| **OVS Queue 2 (Crit)** | `5 Mbps min` guaranteed | `sdn/topology.py` | Physical bandwidth isolation for high-priority telemetry |
| **OVS Queue 1 (Norm)** | `3 Mbps min` guaranteed | `sdn/topology.py` | Guaranteed throughput for normal health reports |
| **OVS Queue 0 (Bulk)** | `1 Mbps min` | `sdn/topology.py` | Best-effort queue for background flood (iperf) |
| **Silence Timeout** | $3.0 \times \text{interval}$ | `server/node_registry.py` | Prevents premature node failure declarations on single-packet jitter |
| **Alert Cooldown** | `5.0 seconds` | `server/alert_engine.py` | Suppresses duplicate log storms during sustained issues |
| **Alert Hysteresis** | `2.0%` | `server/alert_engine.py` | Prevents alert flapping at boundary conditions |

---

## 3. Key Numbers from Real Benchmark Runs

| Benchmark Metric | Measured Result | Significance to Mention to Teacher |
|---|---|---|
| **Automated Tests** | **60 Passed**, **87% Coverage** | Extensive verification across all 8 project expectations |
| **Baseline Delay** | **0.32 ms mean**, **0.45 ms p95** | Sub-millisecond latency on local network |
| **Baseline Alert Latency** | **0.26 ms mean**, **0.43 ms p95** | End-to-end time from host symptom to server alarm |
| **Congestion Critical Loss (No SDN)**| **56.67% ± 10.27%** | Standard UDP collapses under 12 Mbps background flood |
| **Congestion Critical Loss (With SDN)**| **0.00% ± 0.00%** | SDN QoS completely insulates critical alerts |
| **Congestion Delay (p95 Critical)** | Reduced from **30.75 ms to 1.48 ms** | 95.2% latency reduction under heavy link saturation |
| **Crash Time-to-Detect (TTD)** | **1.07 ± 0.04 seconds** | Fast identification of process termination |
| **Link Cut Time-to-Detect (TTD)** | **3.30 ± 0.00 seconds** | Accurate $3 \times \text{interval}$ silence detection |
| **Recovery Time (TTR)** | **0.02 - 0.04 seconds** | Immediate restoration on first resumed packet |
| **Scalability (80 Nodes)** | **184.2 pkts/sec**, **0.0% loss** | Server CPU remained $< 5\%$ using `select` multiplexing |
| **Telemetry Wire Overhead** | **3.36 kbps per agent** | Negligible network overhead |

---

## 4. Rapid-Fire Viva Answers (Say exactly this)

### 1. "How does the OpenFlow switch inspect packet priority if UDP has no priority header?"
> *"We set the **DSCP (Differentiated Services Code Point)** in the outer IPv4 header using the `IP_TOS` socket option (`0xB8` for DSCP 46 Expedited Forwarding). OpenFlow 1.3 switch flow tables natively match on the `ip_dscp` field and apply the `set_queue` action to route packets into pre-configured OVS HTB queues."*

### 2. "Why use non-blocking `select` in the server instead of multiple threads?"
> *"A thread-per-client model incurs substantial operating system context-switching overhead and memory footprint as the cluster grows. Using `select` on a single non-blocking UDP socket enables a single thread to multiplex hundreds of concurrent telemetry streams with $< 5\%$ CPU utilization."*

### 3. "What happens if packets arrive out of order?"
> *"Our `NodeRegistry` compares the packet's sequence number against `last_seq`. If $seq < last\_seq$, it increments an `out_of_order` counter without decrementing or corrupting the `lost_packets` counter. If the sequence drops back to 0 or 1, it recognizes an agent restart event and resets sequence tracking."*

### 4. "How is congestion generated during your tests?"
> *"In Mininet, we saturate the 10 Mbps bottleneck link using an `iperf` UDP flood at 12 Mbps. In our automated test proxy, we emulate queue buffer overflow with tail-drop packet loss for Queue 0, proving that Queue 2 packets bypass the congestion."*

---

## 5. Quick Commands to Run During the Demo

```bash
# 1. Run full test suite:
pytest tests/ -v

# 2. Start the interactive demo console:
python3 demo.py

# 3. Start live web visualizer (browser on http://localhost:8080):
python3 server/monitor_server.py --port 5005 --web-port 8080

# 4. Clean up Mininet (if run with sudo):
sudo mn -c
```
