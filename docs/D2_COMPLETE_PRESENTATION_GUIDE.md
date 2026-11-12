# D2 COMPLETE PRESENTATION GUIDE
## Remote System Health Monitoring using UDP + Ryu SDN + Mininet

**Use:** Full presentation outline, slide content, exact speaker script, demo checklist, results interpretation, tough viva answers and last-minute revision. This is a **text/Markdown guide**, not an HTML file or slide deck.

**Suggested format:** 18 slides, roughly 15–18 minutes plus demonstration and questions. Adjust to your allotted time.

**Sources:** The [official SDN–Socket Programming rubric](SDN-Socket%20Programming-Guidelines_Rubrics.pdf); actual Python/configuration/tests; checked-in CSV results; Git history. **Existing Markdown guides were deliberately not used as sources.** For the D1→D2 comparison, the pre-D2 repository state was checked at `8378cc85ac27` and compared with D2 commit `4a15ef25cb41` and current `main` (through `e933325c9a6e`).

> **Core argument:** D1 gave us a functioning multi-agent UDP monitoring system with proactive OpenFlow QoS and a Mininet topology. **D2 introduced reactive Ryu congestion response, install/remove dynamic FlowMods, explicit host quarantine/unquarantine, controller-specific tests and an integrated D2 showcase.** A later dashboard update added interactive ON/OFF and throttle *simulation* controls. The software-proxy results and dashboard simulation must not be misrepresented as measured live OVS outcomes.

---

# 1. Exact D1 vs D2 development comparison

| Topic | Already in D1 | New / strengthened for D2 |
|---|---|---|
| Monitoring | UDP agent/server, JSON protocol, CPU/RAM/process metrics, simulated patterns, node registration and failure, threshold alerts | Used as foundation for D2 challenging demos; the basic monitoring stack is **not** a new D2 feature |
| SDN | Ryu OpenFlow 1.3, proactive priority-100/50/10 flows, DSCP marking, OVS QoS queues | **Reactive controller:** port-byte-rate calculation, priority-80 congestion FlowMod added/removed, priority-200 quarantine DROP rule |
| Mininet | Star topology, `s1`, h1–hN plus `h_server`, 10 Mbps shared link, queue configuration | Still the full-network integration path; topology itself predated D2 |
| Benchmarks | Local latency, congestion-model, failure, scalability scripts existed | D2 emphasizes OFF/ON comparison, challenging scenarios, results interpretation and a consolidated showcase—not a claim every script was newly created |
| Tests | Agent, protocol, UDP server, registry, alert, integration, robustness tests | `tests/test_sdn_controller.py` added for reactive FlowMods, port-stats trigger, quarantine and proactive classification, using **mocked datapaths** |
| Demo | Interactive `demo.py` and a live dashboard | `run_d2_showcase()` added; later dashboard gained ON/OFF, throttle-state controls and a simulation-mode reset |
| Web QoS toggle (latest main) | Dashboard showing node health | **Current code toggles server-side synthetic drop/delay**, not live Ryu/OVS flow programming |

### Rubric-based priority

The official [guidelines and rubric](SDN-Socket%20Programming-Guidelines_Rubrics.pdf) award:

- **D1 / 15 marks:** architecture 2; low-level sockets 4; Mininet+SDN 4; socket–SDN integration 3; initial testing/demo 2.
- **D2 / 25 marks:** full functionality 4; **dynamic SDN 6**; challenging scenario/robustness 4; performance comparison 5; documentation/final demo/viva 6.

**Present D2 as moving from static SDN policy to a reactive network-control loop.** Do not spend half the D2 talk re-explaining D1.

---

# 2. COMPLETE SLIDE-BY-SLIDE PRESENTATION

Each slide includes **what to display** and **what to say**. The speaker scripts are designed to sound natural, rather than like a README being read aloud.

## Slide 1 — Title: From remote monitoring to dynamic SDN

**Display:**
- *Remote System Health Monitoring using UDP and Software-Defined Networking*
- *Deliverable 2 — Dynamic SDN, robustness and performance evaluation*
- Project team/section details as appropriate

**Say:**
"Good morning. Today we present Deliverable 2 of our Computer Networks mini-project: Remote System Health Monitoring using UDP and SDN. Our application receives periodic health reports from multiple nodes, tracks failures and raises alerts. The major D2 improvement is that our Ryu controller can react to current network congestion and install or remove OpenFlow rules, instead of relying only on static priorities. We'll show the architecture, explain what changed since D1, analyze the recorded experiments and demonstrate the system."

**Transition:** "First, let's see the problem this solves."

## Slide 2 — Why this problem matters

**Display:**
1. Machines can be overloaded or silently fail.
2. The monitoring server needs fresh, timely telemetry.
3. Congested networks can drop/delay critical reports.
4. Our design combines application awareness with programmable forwarding.

**Say:**
"In a distributed network, a server can lose visibility for two reasons: the monitored machine may fail, or the network carrying its reports may be congested. We therefore built agents that periodically collect CPU, memory, process count and network statistics and send them via UDP. The central monitor detects overload and missing reports. With SDN, we also classify important monitoring traffic into a higher-priority network queue so it has a better chance of getting through during congestion."

**Know:** UDP is chosen for small, frequent, independent reports; it does **not** guarantee delivery.

## Slide 3 — System architecture and data flow

**Display the flow:**

~~~text
Agent h1 / h2 / ... / hN (StatsCollector + HealthAgent)
       │  JSON UDP datagrams + seq + sent_ts + IP DSCP
       ▼
   Open vSwitch s1  ◄──── OpenFlow 1.3 ──── Ryu controller
       │                 flows, queues, stats
       │ 10 Mbps server-side bottleneck
       ▼
h_server: MonitorServer / UDP 5005
       ├─ NodeRegistry: UP/DOWN, seq gaps, delays
       ├─ AlertEngine: warning/critical, cooldown
       ├─ results/*.csv
       └─ optional web dashboard / HTTP 8080
~~~

**Say:**
"The agent is the UDP client and the monitoring server is the UDP receiver. Each agent creates a versioned JSON report with its node ID, sequence and timestamp. Mininet provides multiple virtual hosts connected through OVS, with a bottleneck on the monitoring server's link. Ryu is the SDN controller; it communicates with OVS using OpenFlow. On the server, reports update the node registry, trigger alerts and appear in CSV logs and the dashboard. The monitoring data path and the controller path are separate."

**Source:** [`sdn/topology.py`](../sdn/topology.py), [`server/monitor_server.py`](../server/monitor_server.py).

## Slide 4 — What D1 already achieved

**Display:**
- Low-level UDP: `socket(AF_INET, SOCK_DGRAM)`, `sendto()`, `recvfrom()`
- Version 1 JSON protocol, validation, up to 1400-byte encoded payloads
- Multi-node registry: sequence tracking, loss estimate, failure/recovery
- Health warning and critical alerts
- Mininet topology, DSCP marking and proactive OpenFlow queue rules
- Baseline experiment scripts and dashboard

**Say:**
"Our first deliverable established a working end-to-end socket application and programmable-network foundation. We were already collecting and receiving UDP health reports and detecting missing or problematic nodes. We had a Mininet star topology and a Ryu controller that installed proactive queue-selection rules. This is the base architecture. Our D2 goal was not to recreate the sender or server; it was to add **dynamic network behavior** and show stronger robustness and performance evaluation."

**Key defense:** D1 included proactive QoS; D2's new code is reactive control.

## Slide 5 — Exactly what we added in D2

**Display:**
1. **Congestion feedback loop:** OpenFlow port statistics → calculate transmit rate
2. **Dynamic throttling:** install/remove a priority-80 UDP queue rule
3. **Host isolation:** install/remove source-IP DROP rule (priority 200)
4. **New controller unit tests** and `demo.py` D2 showcase
5. **Interactive D2 dashboard controls** added in later commits (modeled, not live Ryu switches)

**Say:**
"The most significant D2 addition is in `sdn/ryu_controller.py`. We extended the port statistics handler to compare current transmitted-byte rates with congestion thresholds. It can then send FlowMod messages to temporarily change flow classification and later remove them. We also added quarantine and unquarantine methods to isolate a selected IPv4 source. These additions were covered with dedicated controller tests. Later, we added dashboard controls for illustrating priority ON and OFF. We'll explicitly distinguish the simulation from real OpenFlow behavior."

**Source:** [`sdn/ryu_controller.py`](../sdn/ryu_controller.py); [`tests/test_sdn_controller.py`](../tests/test_sdn_controller.py).

## Slide 6 — D1 static OpenFlow QoS

**Display this rule table:**

| Rule priority | Match | Action |
|---:|---|---|
| 100 | IPv4 + UDP dst 5005 + DSCP 46 | `SetQueue(2)`, NORMAL output |
| 50 | IPv4 + UDP dst 5005 + DSCP 0 | `SetQueue(1)`, NORMAL output |
| 10 | General IPv4 + UDP | `SetQueue(0)`, NORMAL output |
| 1 | Learned L2 flow | Output learned port |
| 0 | Table miss | Send to controller |

**Say:**
"In D1, the switch connection event installed a table-miss flow and proactive QoS rules. A health agent marks important packets by setting the IP TOS byte to 0xB8, which represents DSCP 46. OVS matches that field and port 5005, then selects queue 2. Normal telemetry matches queue 1; background UDP goes to queue 0. These are installed when the switch connects, so the policy is proactive rather than a reaction to a measured congestion event."

**Know:** DSCP 46 shifted left by 2 = 184 decimal = `0xB8`. OpenFlow *flow priority* and QoS *queue number* are different concepts.

## Slide 7 — D2: the reactive congestion algorithm (**important**)

**Display:**
- Ryu polls port/flow counters every **2 seconds** by default.
- `rate_bps = (tx_bytes_now - tx_bytes_before) * 8 / delta_seconds`
- **≥ 8 Mbps:** install dynamic throttle
- **< 4 Mbps:** remove dynamic throttle
- Hysteresis band avoids constant switching.
- These are hard-coded thresholds in the controller's current method.

**Say:**
"This slide contains the core 6-mark D2 contribution. Instead of just setting QoS rules once, Ryu periodically requests OpenFlow port counters. The `port_stats_reply_handler` compares current and previous transmitted bytes over elapsed time and calculates bit rate. On our assumed 10 Mbps bottleneck, a rate of at least 8 Mbps triggers the dynamic action. Once traffic falls below 4 Mbps, the controller removes the temporary rule. This creates an observe–decide–act loop."

**Example:** 1,200,000 additional bytes in one second → 9,600,000 bits/s → **9.6 Mbps** → trigger.

**Source:** [`port_stats_reply_handler()`](../sdn/ryu_controller.py).

## Slide 8 — D2: what the dynamic FlowMod actually does

**Display:**
- `install_dynamic_throttle()` creates an IPv4/UDP match
- OpenFlow **priority 80** (above normal 50, below critical 100)
- Actions `SetQueue(0)` + `Output(OFPP_NORMAL)`
- Default flow idle timeout: **15 s**
- `remove_dynamic_throttle()` sends `OFPFC_DELETE_STRICT` to restore policy

**Say:**
"When the congestion decision fires, the controller constructs and sends an OpenFlow FlowMod. The match is IPv4 UDP and the action assigns queue 0, the best-effort queue. The critical-monitoring rule has priority 100, so it continues to win against the new priority-80 rule. When port load drops below the lower threshold, we remove the temporary flow with a strict delete."

**Important technical honesty:** Priority 80 currently matches **all IPv4 UDP**, not only bulk traffic. It overrides the normal-monitoring priority-50 rule too. In a refined version, we'd narrow the match to background sources or ports. Also, flow idle timeout and the controller's cached `throttled_ports` state can become out of sync.

**Source:** [`install_dynamic_throttle()` / `remove_dynamic_throttle()`](../sdn/ryu_controller.py).

## Slide 9 — D2: quarantine and unquarantine

**Display:**
- `quarantine_host(datapath, host_ip)`
- Match: Ethernet IPv4 + `ipv4_src=host_ip`
- **Priority 200** DROP: empty action list
- Default 30-second idle timeout
- `unquarantine_host()` performs strict flow deletion

**Say:**
"A second dynamic SDN capability is isolation of an identified host. The controller can install a high-priority DROP rule matching the host's source IP, so OVS discards matching packets before they reach the monitoring server. It can later remove that rule. The D2 demonstration invokes these methods and the unit tests verify flow construction."

**Do not overclaim:** There is no automatic malicious-host classification wired to the main controller loop. Quarantine is **callable**; the showcase's sample rogue host uses a **mock datapath** rather than isolating a real connected Mininet host.

## Slide 10 — New D2 interactive dashboard: what it does (and doesn't)

**Display:**
- New button: **SDN Priority ON / OFF**
- New button: **Simulate Dynamic Throttle**
- `POST /api/toggle_priority` and `POST /api/toggle_throttle`
- Live node metrics still come from the UDP monitor
- **Dashboard mode ≠ actual Ryu switch configuration**

**Say:**
"We extended the web dashboard with a D2 control panel to illustrate the effects of prioritization. The priority button changes a state on the central monitor. In OFF mode, the server intentionally models an overloaded FIFO bottleneck by dropping reports with a 56.7 percent probability and assigning apparent 34–43 millisecond delay to surviving reports. This makes the effect visible interactively. However, the dashboard does not communicate that button state to Ryu, and the throttle button only changes a dashboard status flag."

**Code-accurate details:**
- `MonitorServer.priority_enabled` toggles; the default OFF emulation flag is enabled if not configured otherwise.
- When OFF, `process_datagram()` drops valid datagrams when `random.random() < 0.567` and changes `recv_ts` for survivors.
- Synthetic drops increment `bad_packet_count`, even though that counter also tracks malformed messages.
- Switching modes resets registry loss and delay statistics; switching back ON resets `bad_packet_count`.
- The dashboard's printed performance figures (e.g. 38.4/1.8 ms) are **fixed text**, **not** readings of the saved CSV or live queue counters.

**Presentation wording:** "This is an application-side illustrative simulation. Real switch rules live in `ryu_controller.py` and must be inspected in OVS."

## Slide 11 — Challenging scenarios: robustness and failures

**Display:**
- **Overload:** normal/spike/ramp-up/constant-high metric patterns
- **Failure:** stop sender; no datagrams; node becomes DOWN
- **Recovery:** reports resume; status returns UP
- **Bad input:** invalid JSON/metrics rejected without stopping server
- **Network loss:** sequence gaps estimated and reported

**Say:**
"We also address the D2 requirement for challenging scenarios. An agent can simulate CPU and memory spikes. The server checks thresholds and generates warnings or critical alerts. If a node becomes silent for more than its allowed interval, the registry marks it DOWN. When a valid report resumes, the server marks it recovered. We also validate incoming JSON so malformed packets are dropped without crashing the monitoring service."

**Numbers:** Default report interval 1 second, silence multiplier 3; CPU thresholds 70/90%, memory 75/90%, processes 300/500; alert cooldown 5 seconds; hysteresis 2.

**Nuance:** Agent packet priority becomes `CRITICAL` at a **warning** threshold. The server computes the distinct WARNING/CRITICAL alert severity using both thresholds.

## Slide 12 — Experiment design and why the baseline is fair

**Display:**
- Software model: `CongestedBottleneckProxy` on localhost
- OFF = single FIFO buffer
- ON = high priority for JSON reports labeled CRITICAL; other packets use lower queue
- Background aims for **12 Mbps**, modeled link capacity **10 Mbps**
- Compare class loss, mean/p95 delay and alert latency

**Say:**
"Our congestion experiment uses the same application reporting behavior while changing the queue discipline. Priority OFF shares one FIFO. Priority ON separates critical reports into a high-priority queue. We inject a background stream aiming for 12 Mbps, above the 10 Mbps modeled bottleneck. We then calculate per-class losses, delay and alert latency and save the comparison. We use p95 alongside mean because a small number of very late packets can matter in monitoring."

**Methodology label:** This is **a Python software queue model**, not a live Ryu/Mininet queue benchmark. The proxy reads **JSON priority**, not IP DSCP. The controller's FlowMod logic is tested separately with mocks. Say this without waiting for the examiner to catch it.

**Source:** [`run_congestion_test.py`](../experiments/run_congestion_test.py).

## Slide 13 — Most important D2 comparison results

**Display the exact values from [`results/congestion_results.csv`](../results/congestion_results.csv):**

| Metric | Priority OFF | Priority ON |
|---|---:|---:|
| **Critical loss** | **56.67%** | **0.00%** |
| Normal loss | 56.96% | 59.94% |
| **Critical mean delay** | **30.05 ms** | **0.93 ms** |
| Critical p95 delay | 30.75 ms | 1.48 ms |
| Normal mean delay | 27.03 ms | 27.30 ms |
| **Alert mean latency** | **29.98 ms** | **5.48 ms** |
| **Alert p95 latency** | **30.51 ms** | **30.44 ms** |

**Say:**
"The stored software-model trials show a major improvement to the traffic class we wanted to protect. Critical loss decreases from about 56.7 percent to zero *in these trials*, and mean critical delay drops from 30.05 to 0.93 milliseconds—about a 96.9 percent decrease. There is a tradeoff: normal loss remains high and increases slightly. Importantly, the alert **mean** latency improves while its **p95** changes very little. We do not claim every latency metric improved uniformly or that these are already measured OpenFlow queue results."

**Explain:** Zero measured modeled loss is not a guarantee of UDP reliability. The performance CSV is not the dashboard's hard-coded comparison text.

## Slide 14 — Other experiments: latency, failure and scale

**Display:**
- Baseline localhost delay: **0.318 ms mean**, **0.447 ms p95**
- Crash scenario: typical recorded TTD about **1.05 s**, TTR about **0.05 s**
- Silent/link-like scenario: TTD about **3.30 s**, recovery about **0.02 s**
- 80 local agents, 0.5-s interval: **184.2 received packets/s**, recorded estimated loss **0%**
- Example wire size: HEALTH **420 bytes**, HEARTBEAT **148 bytes** (with assumed 42-byte Ethernet/IPv4/UDP headers)

**Say:**
"Beyond congestion, our evaluation includes baseline delay, failure detection/recovery and scaling agent count. The local results show the registry transitions and that a threaded localhost sender/receiver setup can handle the studied loads. We also quantify packet size overhead. These results should be read with the test environment in mind: the scalability run uses simulated local agents rather than dozens of independent computers."

**Caveats to know:** The 'link failure' and 'partial loss' scripts model silence/packet resumption rather than actually invoking a Mininet link-down. Baseline one-way delay depends on clock alignment if tested across machines. Scalability's CPU sample is machine-wide `psutil.cpu_percent()`, not a dedicated monitor-process CPU meter. Some scripts have hard-coded fallback values if expected observations are missing; do not mistake fallback data for measurements.

**Source:** [latency CSV](../results/latency_results_summary.csv), [failure CSV](../results/failure_results.csv), [scalability CSV](../results/scalability_results.csv).

## Slide 15 — Testing and validation

**Display:**
- Protocol: valid/invalid JSON, maximum datagram size, field/range checks
- Monitoring: sequence gaps, duplicates, out of order, silence and recovery
- Alerts: threshold boundaries, cooldown, hysteresis
- Server: malformed bursts, multiple senders, port binding, shutdown
- **D2 controller tests:** reactive rule add/remove, port-stat trigger, quarantine

**Say:**
"We verify the application at several levels. Protocol tests check that malformed datagrams and incorrect values are rejected. Registry and alert tests cover expected state transitions. UDP integration tests simulate multiple senders. The controller-specific D2 tests check that our controller attempts the correct OpenFlow actions when mocked port statistics cross thresholds. This provides code-level evidence; a real Mininet demonstration adds the separate question of whether the switch accepted the rules and forwarded traffic accordingly."

**Show:** [`tests/test_sdn_controller.py`](../tests/test_sdn_controller.py). Run tests if possible; don't state a current pass count without a current run.

## Slide 16 — Live demonstration plan

**Display:**
1. Start central UDP server and live dashboard.
2. Start normal and spiking agents.
3. Show node metrics, alerts, status and sequence numbers.
4. Stop/restart an agent: show DOWN then RECOVERED.
5. Use new dashboard ON/OFF **simulation** controls.
6. Show D2 showcase; if the lab permits, show **real Mininet/OVS** flow table too.

**Say:**
"Our live demonstration has two clearly labeled parts. First we show the real UDP monitoring application, node-status changes and alerts. Second we show D2 simulation controls and the congestion-model comparison. When Ryu and Mininet are available, we inspect actual OVS queue configuration and FlowMods separately. We do not present an application-only toggle as proof that the physical switch changed rules."

**Source:** [`demo.py`](../demo.py).

## Slide 17 — Limitations, engineering choices and future work

**Display:**
- Compare OFF/ON on **live OVS** using queue/flow counters
- Make priority-80 match selective; don't inadvertently demote normal monitoring
- Wire dashboard controls to an authenticated Ryu API, not just server emulation
- Automate suspicious-host detection before calling quarantine
- Synchronize clocks and measure process-specific CPU; remove fallback benchmark samples
- Keep controller cached state consistent with expiring OpenFlow rules

**Say:**
"The project demonstrates the architecture and the dynamic-control logic, but we know where the model and implementation need strengthening. Our current congestion benchmark is software-based. Our interactive priority button doesn't change OVS rules. Our priority-80 rule matches normal UDP telemetry as well as bulk traffic. These are concrete opportunities for an improved live Mininet evaluation and safer, more precise control-plane integration."

## Slide 18 — Conclusion: D1 established; D2 reacted

**Display:**
- **D1:** working telemetry, alerts, Mininet/OVS and proactive queue classification
- **D2:** stats-driven controller, dynamic FlowMods, quarantine functions, specific tests and challenging-scenario evaluation
- **Takeaway:** Real-time health reporting + programmable network policy

**Say:**
"To conclude, D1 made the monitoring system work. D2 moved the network controller beyond fixed classification by adding a feedback-driven congestion action and explicit host-isolation operations. We demonstrated these mechanisms through code/tests and controlled models, and we have identified the live-switch verification needed to validate the same improvements in Mininet. Thank you—we're ready for your questions."

---

# 3. OPERATOR-READY DEMONSTRATION SCRIPT

## A. Safe local demonstration (works without Mininet)

From the repository root, with Python dependencies installed:

**Terminal 1 — server and dashboard**
~~~bash
python server/monitor_server.py --host 127.0.0.1 --port 5005 \
  --web-port 8080 --dashboard-interval 2
~~~

**Terminal 2 — normal agent**
~~~bash
python agent/health_agent.py --id h1 --server 127.0.0.1 \
  --port 5005 --interval 1 --mode simulated --sim-pattern normal
~~~

**Terminal 3 — spiking agent**
~~~bash
python agent/health_agent.py --id h2 --server 127.0.0.1 \
  --port 5005 --interval 1 --mode simulated --sim-pattern spike
~~~

Open `http://localhost:8080`. Show the two nodes, CPU and RAM, last sequence, report counters and alerts. Stop h2 and leave enough time for the 3×interval silence check; the node becomes DOWN. Restart the same h2 ID and it becomes UP again.

**Quick menu alternative:** `python demo.py`. Choose **4** for dashboard with sample agents, **3** for failure demo, **5** for the D2 showcase, **6** for experiments (which can overwrite result CSVs/plots).

### Exact safe language for the new buttons

"Clicking Priority OFF changes the monitor's **simulation mode**: it adds synthetic loss and delay to show how a congested, unprotected queue could affect reports. Clicking Simulate Dynamic Throttle changes the displayed status. Neither of these clicks sends an OpenFlow rule to the actual Ryu controller. Our real controller code and Mininet verification path are separate."

## B. Genuine Ryu/Mininet demonstration (Linux/root + dependencies required)

Have Ryu, Mininet, Open vSwitch, iperf and compatible Python packages installed.

**Terminal 1 — controller**
~~~bash
ryu-manager sdn/ryu_controller.py --ofp-tcp-listen-port 6633
~~~

**Terminal 2 — network (adapt Python path/permissions to your environment)**
~~~bash
sudo -E .venv/bin/python sdn/topology.py \
  --hosts 5 --interval 1 --bw 10 --mode simulated
~~~

**Mininet CLI**
~~~text
nodes
net
h1 ping -c 2 10.0.0.100
sh ovs-ofctl -O OpenFlow13 dump-flows s1
sh ovs-vsctl list qos
sh ovs-vsctl list queue
~~~

Describe the switch, controller connection, static queue rules and actual counters. A dynamic priority-80 flow appears **only if the real port-statistics condition triggers**; its existence must be inspected rather than assumed. The code currently assumes the server-facing egress port is `s1-eth1`, so check that port mapping in the live lab.

**Safety:** `configure_ovs_qos()` uses an OVS-wide delete of QoS/Queue records. Run this only in an isolated lab OVS setup. Mininet commands need root and the right Python environment.

## C. What `demo.py` option 5 actually proves

`run_d2_showcase()`:
1. Runs priority OFF and ON with a **localhost `CongestedBottleneckProxy`** (software FIFO vs high-priority queue).
2. Creates a **MagicMock Ryu datapath** with a synthetic 9.6 Mbps port-stats event to exercise the dynamic handler.
3. Calls quarantine for a sample source IP on that mocked datapath.
4. Shows outputs and confirms the handler logic, but does **not** deploy this showcase on a real OVS switch.

**If asked:** "It verifies logic and illustrates the expected benefit. Live SDN data-plane proof needs the separate Mininet path."

## D. Demo fallback

- **No Mininet:** show working local UDP, test suite, controller code and labeled proxy results.
- **No Ryu import:** check Ryu/eventlet/Python compatibility; show controller test source rather than claiming execution.
- **Dashboard busy:** close old process or choose another `--web-port`.
- **No overload:** start a `spike` agent.
- **Results don't match dashboard panel:** cite the saved CSV; dashboard numbers are fixed illustrative text.
- **No priority-80 rule in live OVS:** say the actual utilization trigger has not been observed, rather than fabricating a success.

---

# 4. EXAMINER QUESTIONS AND STRONG SHORT ANSWERS

**1. What's specifically new in D2?**  
Reactive SDN port-stat handling with conditional FlowMods, throttle removal, host quarantine/unquarantine, new controller tests, a D2 showcase and later illustrative dashboard controls. The basic agent/server and static SDN were already present in D1.

**2. Why is the SDN controller "dynamic"?**  
It periodically measures switch port transmit rate and adds/removes rules in response; this is different from fixed rules at switch connection.

**3. Which Ryu event do you use?**  
`EventOFPPortStatsReply` handled by `port_stats_reply_handler`.

**4. What triggers a new rule?**  
TX rate ≥8 Mbps, calculated as eight times the change in transmitted bytes divided by elapsed seconds.

**5. Why also use a 4 Mbps clearing threshold?**  
To reduce repeated state changes near the activation threshold.

**6. What does the priority-80 flow match?**  
All IPv4 UDP, not only bulk. It overrides priority-50 normal monitoring but not priority-100 critical monitoring.

**7. What is the role of the 15-second idle timeout?**  
Allows the temporary rule to expire if no matching packets arrive. Controller state may then need synchronization.

**8. What does a FlowMod do?**  
Programs the switch with a match, priority and action or deletes a matching entry.

**9. How does DSCP work here?**  
Critical agent messages use `IP_TOS=0xB8`, giving DSCP 46. Ryu's priority-100 match selects Q2 for UDP dst 5005.

**10. Is the JSON "CRITICAL" field itself visible to the switch?**  
No. OVS matches packet headers; the agent converts application priority to the IP DSCP field.

**11. Does CRITICAL packet priority mean CRITICAL server alert?**  
Not necessarily. Agent raises packet priority at warning thresholds; the alert engine separately determines WARNING/CRITICAL severity.

**12. What do queues 0, 1 and 2 represent?**  
Best effort, normal monitoring and critical monitoring, with configured minimum rates of 1, 3 and 5 Mbps on the 10 Mbps egress link.

**13. Why is host quarantine priority 200?**  
To outrank the other relevant forwarding/classification rules; its empty action list drops matching source-IP traffic.

**14. Is quarantine automatic?**  
No. The method is present and tested, but the main controller does not independently classify and quarantine attackers.

**15. Does dashboard Priority OFF reconfigure Ryu?**  
No. It changes server-side demonstration state and synthesizes drops/delays.

**16. Why does `bad_packet_count` rise in OFF mode?**  
The software OFF-mode emulation increments that counter for intentionally dropped, otherwise-valid datagrams. It isn't solely a count of invalid JSON in that mode.

**17. What are you measuring in congestion results?**  
Packet loss estimates and observed delays for critical/normal traffic in the **software proxy**, comparing shared FIFO with class-aware queue service.

**18. What is the strongest numeric finding?**  
Critical loss 56.67% → 0.00% and critical mean delay 30.05 → 0.93 ms in the recorded model trials.

**19. Did alert p95 latency improve by the same amount?**  
No. It is about 30.51 → 30.44 ms, almost unchanged. We report mean and p95 separately.

**20. Can you claim zero packet loss for live OVS?**  
Not from this CSV. It is a software-model outcome for particular runs; live queue counters and matched Mininet trials would be needed.

**21. How is UDP loss estimated?**  
From gaps in per-node sequence numbers; this can be imperfect with reordering/restarts.

**22. How does node failure detection work?**  
If no valid message arrives for more than the node's reporting interval × the silence multiplier, node state becomes DOWN.

**23. How does recovery work?**  
A valid packet arriving from the DOWN node changes it to UP and emits a recovery event.

**24. What is hysteresis in alerting?**  
It requires a metric to fall below a lower clearing threshold before an alert is cleared, reducing rapid flapping.

**25. Why use UDP, not TCP?**  
Each periodic reading is small and freshness matters. UDP avoids transport retransmission/ordered-stream constraints, while sequence tracking and liveness add application observability.

**26. What is the difference between Mininet and a simulator?**  
Mininet emulates real Linux network stacks and virtual links/switches. Our congestion benchmark separately uses an application-layer Python proxy model.

**27. What does `tests/test_sdn_controller.py` verify?**  
Mocked OpenFlow rule construction and event handling, including reactive throttle and quarantine. It does not prove switch installation or live QoS improvement.

**28. What is the most important rubric category in D2?**  
Dynamic SDN functionality (6 of 25 D2 marks); show the live stats→decision→FlowMod path and distinguish its proof level.

**29. What would you improve first?**  
Measure ON/OFF in actual Mininet/OVS, refine the broad priority-80 match, connect dashboard to a proper controller API, and automate carefully justified quarantine triggers.

**30. How would you make the results more scientifically convincing?**  
Use repeated comparable real-network trials, capture offered load and queue/flow counters, avoid synthetic data fallbacks, measure tail delay and confidence/spread, and document environment/settings.

---

# 5. FIVE CRITICAL PITFALLS (NEVER SAY THESE IN VIVA)

1. **"We implemented all UDP, Mininet and the static QoS for D2."** No: they existed in the D1 version. Explain exactly what was new.
2. **"The dashboard button installs an OpenFlow rule."** It does not; it toggles a server-side simulation variable.
3. **"Our critical traffic has zero loss in every real network."** Zero critical loss is from the stored software-proxy trials under specified settings.
4. **"The dynamic rule only drops/throttles background traffic."** Its current match is all IPv4 UDP, so normal monitoring can be demoted. It classifies into Q0, not a rate-meter DROP action.
5. **"Mock tests prove our OVS network performance."** They validate controller behavior; switch installation and performance require live Mininet evidence.

---

# 6. OPTIONAL TEAM HANDOFF FOR THREE PRESENTERS

- **Presenter 1: Slides 1–5.** Problem, architecture, D1 recap, precise new D2 features. Handoff: "Now we explain the SDN control logic itself."
- **Presenter 2: Slides 6–10.** Proactive vs reactive OpenFlow, stats formula, FlowMods, quarantine, dashboard distinction. Handoff: "Next is how we evaluated and demonstrated the behavior."
- **Presenter 3: Slides 11–18.** Robustness, results, tests, live demonstration, limitations and conclusion.

Everyone should still be able to explain the full packet path and answer why the dashboard and proxy are not live switch measurements.

---

# 7. FINAL 90-SECOND REVISION CARD

### One sentence
**"D1 made health monitoring and static prioritization work; D2 made the SDN controller respond to switch conditions with dynamic FlowMods and explicit isolation rules."**

### Must-know values
- UDP **5005**, Ryu **6633**, dashboard HTTP **8080**
- Agent urgent marking **DSCP 46 = IP_TOS 0xB8**
- Mininet server **10.0.0.100**, agents **10.0.0.1...N**, switch **s1**
- Bottleneck **10 Mbps**, queue minima Q0 **1 Mbps**, Q1 **3 Mbps**, Q2 **5 Mbps**
- Static rules **100 → Q2**, **50 → Q1**, **10 → Q0**
- D2 **80 → Q0** on all IPv4 UDP during congestion; **200 → DROP** chosen source IP
- Congestion trigger **8 Mbps**, clear **below 4 Mbps**
- Failure check **3 × interval**, alert cooldown **5 s**
- Software comparison: critical loss **56.67% vs 0%**, mean delay **30.05 vs 0.93 ms**

### What evidence to show for full live SDN credit
`ovs-ofctl -O OpenFlow13 dump-flows s1`, actual OVS queue configuration/counters, Ryu port-stat logs, and matched measured ON/OFF trials—not only the browser controls or `MagicMock` tests.

### Last closing line
"Deliverable 2 shifts our network from **static classification** toward **feedback-based programmable control**. We can explain the implementation and its test evidence while distinguishing simulations from measurements of a real OpenFlow datapath."

---

# 8. SOURCE NAVIGATION

- [Official grading rubric](SDN-Socket%20Programming-Guidelines_Rubrics.pdf)
- [Agent](../agent/health_agent.py) and [statistics collector](../agent/stats_collector.py)
- [JSON protocol](../common/protocol.py)
- [Monitoring server](../server/monitor_server.py), [node registry](../server/node_registry.py), [alert engine](../server/alert_engine.py)
- [Ryu controller](../sdn/ryu_controller.py) and [Mininet topology](../sdn/topology.py)
- [Dashboard](../server/web_dashboard.py), [demo launcher](../demo.py)
- [Congestion model](../experiments/run_congestion_test.py), [failure test](../experiments/run_failure_test.py), [latency test](../experiments/run_latency_test.py), [scalability test](../experiments/run_scalability_test.py)
- [Controller tests](../tests/test_sdn_controller.py)
- [Congestion results](../results/congestion_results.csv), [baseline latency](../results/latency_results_summary.csv), [failure results](../results/failure_results.csv), [scalability results](../results/scalability_results.csv)

**Accuracy note:** This guide was prepared by reading source, official rubric, commit history and stored results. It does not claim that Python tests or a live Mininet/OVS trial were freshly executed during guide preparation.
