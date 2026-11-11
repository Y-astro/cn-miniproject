# Deliverable 2 (D2) Master Evaluation & Viva Preparation Guide
### Project No. 11: Remote System Health Monitoring (UDP + OpenFlow 1.3 SDN)
**Total D2 Weightage: 25 Marks** *(Total Mini Project: 40 Marks)*  
**Team Members & Evaluation Roles:**
- **Member 1 (`PES2UG25CS642`):** Application Architecture & Challenging Scenarios / Robustness *(Components 1 & 3 — 8 Marks)*
- **Member 2 (`PES2UG25CS609` / Y-astro - Technical Lead):** Dynamic SDN Functionality & Reactive Flow Control *(Component 2 — 6 Marks)*
- **Member 3 (`PES2UG25CS620`):** Performance Evaluation, Baseline Comparison & Live D2 Showcase *(Components 4 & 5 — 11 Marks)*

---

## 1. D2 Rubric Breakdown & Exact Evidence Mapping

| Rubric Component | Marks | Official Rubric Requirement | Where It Is Implemented & What to Show Evaluator |
|---|---|---|---|
| **1. Complete Application Functionality** | **4** | All major project requirements implemented; application supports expected users/clients/flows; functionality works correctly under normal operating conditions. | • `agent/health_agent.py`: Periodic UDP daemon (CPU, RAM, procs, net I/O)<br>• `server/monitor_server.py`: Non-blocking POSIX `select` multiplexing<br>• `server/alert_engine.py`: Dual thresholds (`WARNING`, `CRITICAL`), hysteresis, cooldown<br>• `server/web_dashboard.py`: Live dark-mode Web UI (`http://localhost:8080`)<br>• 65 unit and integration tests passing (`pytest tests/`) |
| **2. Dynamic SDN Functionality** | **6** | SDN controller dynamically responds to network/application conditions through mechanisms such as routing, filtering, prioritization, load balancing, rerouting, monitoring, blocking, or recovery. | • `sdn/ryu_controller.py`: OpenFlow 1.3 PortStats monitor detects bottleneck load<br>• **Dynamic Congestion Throttling:** When TX rate $\ge 8.0\text{ Mbps}$ (80%), controller dynamically injects `OFPFlowMod` (Priority 80, Queue 0, `idle_timeout=15s`) to throttle bulk cross-traffic<br>• **Dynamic Restoration:** When rate drops $< 4.0\text{ Mbps}$, throttle flow is cleanly deleted<br>• **Dynamic Quarantine:** OpenFlow `DROP` rule (Priority 200, `actions=[]`) blocks rogue flooders |
| **3. Challenging Scenario / Robustness** | **4** | At least one meaningful challenging scenario is demonstrated, such as congestion, packet loss, link failure, server overload, unauthorized access, or service failure; system responds appropriately. | • **Scenario 1 (Congestion):** 12 Mbps UDP blast across 10 Mbps link; Priority ON maintains **0.0% loss** and **0.88 ms delay** vs. Priority OFF suffering **56.7% loss**<br>• **Scenario 2 (Crash & Silence):** Agent killed; silence timer (3.0s) triggers `[NODE DOWN]`; on restart, server recovers node in 48 ms<br>• **Scenario 3 (Malformed Attack):** 10,000 corrupt/oversized packets dropped with zero crashes |
| **4. Performance Evaluation & Comparison** | **5** | Appropriate metrics are measured; experiments conducted under multiple conditions; results presented clearly; proposed approach compared with suitable baseline/static approach. | • `results/congestion_comparison.png` & CSV: Priority ON vs. OFF<br>• `results/latency_cdf.png`: One-way delay & alert latency empirical CDF<br>• `results/failure_detection_boxplot.png`: Time-to-Detect (TTD) across failure modes<br>• `results/scalability_trends.png`: Throughput & server CPU from $N = 5$ to $80$ nodes<br>• `results/overhead_summary.csv`: Protocol wire overhead (< 3.5 kbps per agent) |
| **5. Documentation, Final Demo & Viva** | **6** | Complete and well-structured documentation; architecture, implementation, testing and results clearly presented; reproducible final demonstration; students demonstrate individual understanding through viva. | • `docs/report.md`: Complete IEEE-style technical report<br>• `demo.py`: One-click unified evaluation menu (Option 5: D2 Showcase)<br>• Slides deck in `docs/Remote-System-Health-Monitoring.pdf`<br>• All 3 members rehearsed with exact viva scripts below |

---

## 2. 5-Minute Timed Presentation Script (Member-by-Member)

---

### Step 1: Complete Application Architecture & Robustness Scenarios (8 Marks)
**Speaker: Member 1 (`PES2UG25CS642`)** — *Duration: 1.5 Minutes*

* **Slides to Show:** Slides 2 & 4 in `docs/Remote-System-Health-Monitoring.pdf`
* **What to Say:**
  > *"Good morning, Professors. We are presenting Deliverable 2 for Project No. 11: Remote System Health Monitoring over UDP with OpenFlow 1.3 SDN Prioritization and Dynamic Flow Control.*  
  >  
  > *For Deliverable 2, our application is fully operational end-to-end:*  
  > *1. **Low-Level Socket Agents (`agent/health_agent.py`):** Each server node runs an autonomous daemon collecting real CPU, RAM, active process counts, and network I/O via `psutil`. Telemetry is packed into compact JSON datagrams strictly capped at 1400 bytes to prevent IP fragmentation over 1500-byte MTUs.*  
  > *2. **Non-Blocking Central Server (`server/monitor_server.py`):** Using POSIX `select.select()` on a single UDP socket, the server multiplexes hundreds of concurrent reports per second with under 5% CPU overhead. It tracks monotonic sequence numbers, packet loss gaps, and one-way network latency.*  
  > *3. **Dual-Level Alert Engine (`server/alert_engine.py`):** Alerts trigger under `WARNING` and `CRITICAL` conditions. To prevent alarm flapping and false alerts in volatile server environments, we implemented a 5-second cooldown window and a 2% hysteresis deadband.*  
  >  
  > *We also subjected our system to three extreme robustness scenarios:*  
  > *• **Link Failure & Process Crash:** When a node stops transmitting, dynamic silence detection ($3 \times \text{interval} = 3.0\text{s}$) flags the node as `[DOWN]`. Upon node restart, sequence gap reconciliation detects recovery in under 50 milliseconds.*  
  > *• **Malformed & Burst Overload:** The server safely discarded bursts of 10,000 malformed, oversized, and corrupted packets without a single crash or memory leak.*  
  >  
  > *Now, I hand over to **Member 2 (`PES2UG25CS609`)**, our Technical Lead, to explain our Dynamic SDN Controller and reactive OpenFlow mitigation."*

---

### Step 2: Dynamic SDN Functionality & Reactive Flow Control (6 Marks)
**Speaker: Member 2 (`PES2UG25CS609` / Technical Lead)** — *Duration: 1.5 Minutes*

* **Code Files to Show:** `sdn/ryu_controller.py` lines 160–250 and lines 340–370.
* **What to Point to & Say:**
  > *"Thank you. Looking at `sdn/ryu_controller.py`: Deliverable 2 requires the SDN controller to **dynamically respond to real-time network and application conditions**, rather than relying solely on static rules.*  
  >  
  > *Here is how our controller achieves dynamic programmability:*  
  > *1. **Periodic Port & Flow Telemetry Polling:**  
  > Every 2.0 seconds, our Ryu OpenFlow 1.3 controller issues `OFPPortStatsRequest` and `OFPFlowStatsRequest` messages to monitor throughput across all switch ports.*  
  >  
  > *2. **Dynamic Congestion Reaction (`install_dynamic_throttle`):**  
  > When port statistics reveal that the switch-to-server bottleneck link (10 Mbps) exceeds 80% capacity ($\ge 8.0\text{ Mbps}$), the controller dynamically issues an OpenFlow `OFPFlowMod` entry:*  
  > *• It matches background UDP cross-traffic with **Priority 80** (elevated above normal traffic, but below critical telemetry).*  
  > *• It sets an `idle_timeout` of 15 seconds, and enqueues cross-traffic into Queue 0 (strict rate-limited best effort).*  
  > *• This immediately stops buffer starvation, guaranteeing the remaining link capacity for Queue 2 (critical health alerts).*  
  >  
  > *3. **Dynamic Restoration (`remove_dynamic_throttle`):**  
  > When port utilization drops below 4.0 Mbps, the controller dynamically sends an `OFPFC_DELETE_STRICT` message to decommission the throttle rule, restoring standard fair sharing.*  
  >  
  > *4. **Reactive Host Quarantine (`quarantine_host`):**  
  > If a rogue or compromised node floods invalid UDP traffic, the controller dynamically injects a top-priority OpenFlow rule (**Priority 200**) with an empty action list (`actions=[]`), dropping the attacking traffic directly in switch hardware at wire speed.*  
  >  
  > *Now, **Member 3 (`PES2UG25CS620`)** will present our empirical benchmark results and run the live Deliverable 2 demonstration."*

---

### Step 3: Performance Evaluation, Comparison & Live D2 Showcase (11 Marks)
**Speaker: Member 3 (`PES2UG25CS620`)** — *Duration: 2.0 Minutes*

* **Graphs to Show:** `results/congestion_comparison.png` and `results/scalability_trends.png`
* **What to Say:**
  > *"Thank you. We conducted four extensive benchmark experiments under real and simulated network impairments:*  
  >  
  > *1. **Congestion Mitigation Comparison (Priority OFF vs. Priority ON):**  
  > Looking at `results/congestion_comparison.png`: we flooded the 10 Mbps bottleneck link with a 12 Mbps UDP blast.*  
  > *• **In the baseline (Priority OFF / Best-Effort FIFO):** Critical health alerts suffered a catastrophic **56.7% packet loss** with a mean delay of **30.05 ms**.*  
  > *• **With our SDN Prioritization (Priority ON):** Critical health alerts achieved **0.0% packet loss** with mean delay dropping to **0.93 ms**—over a 30-fold latency improvement under heavy link saturation!*  
  >  
  > *2. **Scalability ($N = 5$ to $80$ Nodes):**  
  > Across 80 simultaneous agent nodes streaming 184 packets per second, the server maintained **0.0% packet loss**, mean delay remained under **0.5 ms**, and server CPU utilization stayed below **5.0%**.*  
  >  
  > *Now, let me run our unified Deliverable 2 demonstration."*

---

## 3. How to Execute the Live Demo During Viva

### Method A: The 1-Click Interactive Demo (Recommended)
Open a terminal and run:
```bash
cd "/run/media/astro/New Volume/Sem3/CN/miniproject"
python3 demo.py
```
- **Press `5`:** Executes the **Deliverable 2 Showcase**!  
  *(Runs Scenario 1 Congestion comparison, Scenario 2 Dynamic SDN Throttling, and Scenario 3 Host Quarantine in 10 seconds with clear color-coded outputs!)*
- **Press `1`:** Runs the **65 automated tests** proving 100% test pass rate.
- **Press `4`:** Launches the **Real-Time Web Dashboard** at `http://localhost:8080`.

---

### Method B: Separate Multi-Terminal Live Demo (If Teachers Ask)

#### Terminal 1: Launch Central Server with Live Dashboard
```bash
cd "/run/media/astro/New Volume/Sem3/CN/miniproject"
python3 server/monitor_server.py --port 5005 --web-port 8080
```
*Point to terminal:* "Server is listening on UDP port 5005 with non-blocking POSIX `select` multiplexing."  
*Open browser:* Navigate to `http://localhost:8080` to show real-time telemetry cards.

#### Terminal 2: Launch Normal Production Agent (h1)
```bash
cd "/run/media/astro/New Volume/Sem3/CN/miniproject"
python3 agent/health_agent.py --id h1 --server 127.0.0.1 --port 5005 --mode real
```
*Point to Terminal 1 & Dashboard:* "Node `h1` registered, streaming real host CPU/RAM every 1.0s with sub-millisecond network delay."

#### Terminal 3: Trigger Critical Alert Spike (h2)
```bash
cd "/run/media/astro/New Volume/Sem3/CN/miniproject"
python3 agent/health_agent.py --id h2 --server 127.0.0.1 --port 5005 --mode simulated --sim-pattern spike --spike-interval 3
```
*Point to Terminal 1:*  
`[ALERT] [CRITICAL] Node 'h2' cpu_percent=95.0 (threshold=90.0) Latency=0.21ms`  
"Notice the agent set DSCP 46 on the socket, and the server registered the alert in **0.21 milliseconds**!"

---

## 4. Viva Voce Master Cheat Sheet (20 Essential Questions)

### Category A: Socket Programming & Networking
1. **Q: Why did you choose UDP instead of TCP for health monitoring?**  
   *A (Member 1):* "TCP uses cumulative acknowledgments and sliding-window retransmissions. If a single telemetry packet is lost during network congestion, TCP halts all subsequent packets due to head-of-line blocking. UDP delivers datagrams instantaneously without connection overhead; when combined with SDN QoS, critical packets receive guaranteed bandwidth without TCP delay."
2. **Q: How does the server handle multiple agents without spawning a thread per client?**  
   *A (Member 1):* "We use POSIX `select.select([self.sock], [], [], 0.1)` on a single non-blocking UDP socket. Each iteration reads pending datagrams in a fast loop (`recvfrom`). This avoids thread stack memory allocations (8MB per thread) and eliminates OS context-switching overhead."
3. **Q: What is the 1400-byte MTU guard in your protocol?**  
   *A (Member 1):* "Standard Ethernet MTU is 1500 bytes. Subtracting the 20-byte IPv4 header and the 8-byte UDP header leaves an absolute maximum payload of 1472 bytes. By strictly asserting `len(payload) <= 1400`, we guarantee that no health datagram will ever undergo IP fragmentation at intermediate routers."
4. **Q: How do you prevent timer drift in periodic reporting?**  
   *A (Member 1):* "Instead of naive `time.sleep(interval)` which drifts due to execution time, we use `time.monotonic()` scheduling: `next_tick += interval; sleep_duration = next_tick - time.monotonic()`. This maintains an exact, stable reporting frequency."

---

### Category B: SDN, OpenFlow & Dynamic Control
5. **Q: Exactly where does the socket application interface with OpenFlow?**  
   *A (Member 2):* "In `agent/health_agent.py`, when metrics exceed a critical threshold, the socket calls `sock.setsockopt(socket.IPPROTO_IP, socket.IP_TOS, 0xB8)`. DSCP occupies the 6 upper bits of the TOS byte ($46 \ll 2 = 184 = \text{0xB8}$). The switch inspects the Layer 3 IP header and matches `ip_dscp=46` at line rate."
6. **Q: What is the difference between static and dynamic SDN functionality in your project?**  
   *A (Member 2):* "Static SDN installs fixed proactive flow entries upon switch connection (Queue 2 for DSCP 46, Queue 1 for normal). Dynamic SDN actively monitors port bandwidth counters via `OFPPortStatsRequest`; when link utilization exceeds 80% ($\ge 8\text{ Mbps}$), the controller dynamically issues an `OFPFlowMod` to throttle bulk cross-traffic with an `idle_timeout=15s`, and removes it when congestion subsides."
7. **Q: How does the switch enforce QoS prioritization on the wire?**  
   *A (Member 2):* "We configure Linux Hierarchical Token Bucket (HTB) queues on Open vSwitch using `ovs-vsctl`. Queue 2 has a guaranteed minimum bandwidth of 5 Mbps, Queue 1 has 3 Mbps, and Queue 0 (best-effort) has 1 Mbps. The OpenFlow action `OFPActionSetQueue(2)` directs packets into Queue 2."
8. **Q: How does the controller isolate a rogue host?**  
   *A (Member 2):* "The controller invokes `quarantine_host(datapath, host_ip)`, which installs an OpenFlow flow entry with Priority 200 matching `ipv4_src=host_ip` and an empty action list (`actions=[]`). OpenFlow semantics dictate that a rule with no actions drops matching packets immediately in switch hardware."

---

### Category C: Failure Detection, Alerting & Evaluation
9. **Q: What are hysteresis and cooldown in your alert engine?**  
   *A (Member 3):* "Cooldown (5.0s) prevents alert spamming when a metric remains continuously high. Hysteresis (2.0%) creates a deadband to prevent rapid alarm flapping: for example, if the critical threshold is 90%, the alert fires at 90% but will only clear when the value drops below 88%."
10. **Q: How does the server detect when a node crashes or a link cuts?**  
    *A (Member 3):* "The `NodeRegistry` tracks the timestamp of the last received packet. In `check_liveness()`, if `now - last_seen_ts > 3.0 * interval`, the node is flagged as `[NODE DOWN]` and a silence alarm is logged. When packets resume, the status changes to `[UP]`."
11. **Q: What did your congestion experiment prove?**  
    *A (Member 3):* "When saturating the 10 Mbps link with a 12 Mbps UDP blast: without priority (Priority OFF), critical alerts suffered a 56.7% drop rate and 30 ms delay. With priority (Priority ON), critical alerts experienced **0.0% loss** and mean latency of **0.93 ms**, proving SDN QoS completely insulates critical monitoring telemetry."
12. **Q: How did you verify scalability up to 80 nodes?**  
    *A (Member 3):* "We ran `experiments/run_scalability_test.py` across $N = 5, 10, 20, 40, 80$ nodes. At 80 nodes streaming 184 packets/sec, zero packets were lost, mean delay remained 0.47 ms, and server CPU usage stayed under 5.0%, proving high concurrency."
