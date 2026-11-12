"""OpenFlow 1.3 Ryu SDN Controller for monitoring traffic prioritization and QoS."""

# Import csv module for recording flow statistics to disk
import csv
# Import os module for filesystem and environment interaction
import os
# Import sys module for python path modifications
import sys
# Import time module for timestamp tracking
import time
# Import Path class for cross-platform path handling
from pathlib import Path

# Eventlet compatibility patch for modern Python environments
try:
    # Import eventlet.wsgi to inspect attribute availability
    import eventlet.wsgi
    # Check if ALREADY_HANDLED sentinel attribute exists
    if not hasattr(eventlet.wsgi, "ALREADY_HANDLED"):
        # Define missing attribute to avoid runtime AttributeError in older Ryu builds
        eventlet.wsgi.ALREADY_HANDLED = object()
# Catch and ignore import errors if eventlet is missing or patched
except Exception:
    # Pass silently
    pass

# Import Ryu base application class
from ryu.base import app_manager
# Import Ryu OpenFlow event classes
from ryu.controller import ofp_event
# Import event dispatchers and event handler registration decorator
from ryu.controller.handler import CONFIG_DISPATCHER, MAIN_DISPATCHER, set_ev_cls
# Import OpenFlow 1.3 protocol specifications
from ryu.ofproto import ofproto_v1_3
# Import packet parsing libraries for Ethernet, IPv4, UDP, and EtherType constants
from ryu.lib.packet import packet, ethernet, ipv4, udp, ether_types
# Import Ryu hub for cooperative greenlet concurrency
from ryu.lib import hub

# Prepend project root directory to sys.path so common modules can be imported
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
# Import YAML configuration loader
from common.config_loader import load_config


# Ryu SDN Controller application implementing OpenFlow 1.3 QoS prioritization and dynamic control
class HealthMonitorSDNController(app_manager.RyuApp):
    """Ryu SDN application that prioritizes critical health monitoring traffic."""

    # Explicitly enforce OpenFlow 1.3 protocol version negotiation with switches
    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]

    # Application constructor initializing MAC learning tables, configuration, and timers
    def __init__(self, *args, **kwargs):
        # Call parent RyuApp initializer
        super(HealthMonitorSDNController, self).__init__(*args, **kwargs)
        # MAC-to-port forwarding table for L2 learning switch logic: {dpid: {mac: port}}
        self.mac_to_port = {}
        # Active connected OpenFlow switches dictionary: {dpid: datapath}
        self.datapaths = {}

        # Initialize configuration dictionary
        self.config = {}
        # Attempt loading configuration from config.yaml
        try:
            # Load YAML configuration
            self.config = load_config("config.yaml")
        # Suppress exceptions and proceed with defaults if config file is missing
        except Exception:
            # Pass silently
            pass

        # Extract SDN section from configuration
        sdn_cfg = self.config.get("sdn", {})
        # Boolean flag indicating whether QoS prioritization rules should be installed
        self.priority_enabled = sdn_cfg.get("priority_enabled", True)
        # Central monitoring server IP address
        self.server_ip = sdn_cfg.get("server_ip", "10.0.0.100")
        # Health telemetry UDP destination port (5005)
        self.mon_port = sdn_cfg.get("udp_port", 5005)
        # DSCP value designating critical traffic (46 = Expedited Forwarding)
        self.dscp_critical = sdn_cfg.get("dscp_critical", 46)
        # Periodic interval in seconds for polling switch port and flow statistics
        self.stats_poll_interval = sdn_cfg.get("stats_poll_interval", 2.0)
        # Destination CSV file path for flow telemetry logs
        self.flow_stats_file = sdn_cfg.get("flow_stats_file", "results/sdn_flow_stats.csv")

        # Historical port byte counters for rate calculations: {(dpid, port): (bytes, timestamp)}
        self.port_stats_history = {}
        # Set tracking currently throttled ports to prevent redundant flow rule insertions
        self.throttled_ports = set()
        # Set tracking quarantined host IPs isolated with drop rules
        self.quarantined_hosts = set()
        # Create CSV file with column headers for flow stats
        self._init_stats_csv()

        # Spawn cooperative background greenlet thread to periodically poll switch stats
        self.monitor_thread = hub.spawn(self._stats_monitor_loop)
        # Log controller startup and priority mode status
        self.logger.info(
            f"HealthMonitorSDNController initialized. Priority mode: "
            f"{'ENABLED' if self.priority_enabled else 'DISABLED'}"
        )

    # Private method to prepare CSV file for logging flow statistics
    def _init_stats_csv(self):
        """Initializes CSV file for SDN flow statistics."""
        # Convert path string to Path object
        p = Path(self.flow_stats_file)
        # Ensure parent directory exists
        p.parent.mkdir(parents=True, exist_ok=True)
        # Open CSV file in write mode
        with open(p, "w", newline="", encoding="utf-8") as f:
            # Create CSV writer
            writer = csv.writer(f)
            # Write column headers
            writer.writerow([
                "timestamp", "dpid", "priority_level", "match", "packet_count", "byte_count", "duration_sec"
            ])

    # Event handler triggered when a new OpenFlow switch completes initial handshake
    @set_ev_cls(ofp_event.EventOFPSwitchFeatures, CONFIG_DISPATCHER)
    def switch_features_handler(self, ev):
        """Handles switch connection and installs proactive OpenFlow rules."""
        # Extract datapath object representing the connected OpenFlow switch
        datapath = ev.msg.datapath
        # Extract protocol constants module for OpenFlow 1.3
        ofproto = datapath.ofproto
        # Extract message parser module for OpenFlow 1.3
        parser = datapath.ofproto_parser
        # Register connected switch in active datapaths dictionary
        self.datapaths[datapath.id] = datapath
        # Log successful switch attachment with DPID
        self.logger.info(f"Switch connected: dpid={datapath.id}")

        # 1. Install default table-miss rule (Priority 0): send all unhandled packets to controller
        match = parser.OFPMatch()
        # Action sends packet to controller without buffering on switch
        actions = [parser.OFPActionOutput(ofproto.OFPP_CONTROLLER, ofproto.OFPCML_NO_BUFFER)]
        # Install table-miss flow rule
        self.add_flow(datapath, priority=0, match=match, actions=actions)

        # 2. Proactively install QoS queue classification rules if priority is enabled
        if self.priority_enabled:
            # Install proactive QoS classification rules
            self._install_proactive_qos_rules(datapath)
        # Otherwise log that prioritization is disabled
        else:
            # Log disabled state
            self.logger.info("SDN traffic prioritization is DISABLED via configuration.")

    # Private method to inject proactive QoS classification rules into the OpenFlow switch
    def _install_proactive_qos_rules(self, datapath):
        """Installs proactive rules classifying UDP monitoring traffic by DSCP."""
        # Extract protocol constants
        ofproto = datapath.ofproto
        # Extract protocol parser
        parser = datapath.ofproto_parser

        # Critical Monitoring Traffic: Match UDP packets to port 5005 with DSCP 46 (EF)
        # Priority 100 ensures this rule matches before normal or best-effort rules
        match_crit = parser.OFPMatch(
            # Match IPv4 packets
            eth_type=ether_types.ETH_TYPE_IP,
            # Match UDP protocol number 17
            ip_proto=17,
            # Match destination UDP port 5005
            udp_dst=self.mon_port,
            # Match DSCP 46 (Expedited Forwarding)
            ip_dscp=self.dscp_critical,
        )
        # Action: Enqueue packet into high-priority Queue 2 (guaranteed 5 Mbps, ceil 10 Mbps)
        actions_crit = [
            # Assign packet to hardware/kernel egress Queue 2
            parser.OFPActionSetQueue(queue_id=2),
            # Forward packet using normal L2/L3 pipeline
            parser.OFPActionOutput(ofproto.OFPP_NORMAL),
        ]
        # Install flow rule with priority 100
        self.add_flow(datapath, priority=100, match=match_crit, actions=actions_crit)

        # Normal Monitoring Traffic: Match UDP packets to port 5005 with DSCP 0
        # Priority 50 ensures normal health packets match after critical but before background traffic
        match_norm = parser.OFPMatch(
            # Match IPv4 packets
            eth_type=ether_types.ETH_TYPE_IP,
            # Match UDP protocol 17
            ip_proto=17,
            # Match destination UDP port 5005
            udp_dst=self.mon_port,
            # Match standard Best-Effort DSCP 0
            ip_dscp=0,
        )
        # Action: Enqueue packet into medium-priority Queue 1 (guaranteed 3 Mbps, ceil 10 Mbps)
        actions_norm = [
            # Assign packet to egress Queue 1
            parser.OFPActionSetQueue(queue_id=1),
            # Forward packet using normal pipeline
            parser.OFPActionOutput(ofproto.OFPP_NORMAL),
        ]
        # Install flow rule with priority 50
        self.add_flow(datapath, priority=50, match=match_norm, actions=actions_norm)

        # Background Best-Effort Traffic: Match all other UDP traffic (e.g. bulk iperf flows)
        # Priority 10 ensures this rule serves as a catch-all for non-monitoring UDP packets
        match_best_effort = parser.OFPMatch(
            # Match IPv4 packets
            eth_type=ether_types.ETH_TYPE_IP,
            # Match UDP protocol 17
            ip_proto=17,
        )
        # Action: Enqueue packet into lowest-priority Queue 0 (guaranteed 1 Mbps, ceil 7 Mbps)
        actions_best_effort = [
            # Assign packet to egress Queue 0
            parser.OFPActionSetQueue(queue_id=0),
            # Forward packet using normal pipeline
            parser.OFPActionOutput(ofproto.OFPP_NORMAL),
        ]
        # Install flow rule with priority 10
        self.add_flow(datapath, priority=10, match=match_best_effort, actions=actions_best_effort)

        # Log completion of proactive QoS rule installation
        self.logger.info("Installed proactive QoS rules: Queue 2 (Critical), Queue 1 (Normal), Queue 0 (Best-Effort)")

    # Helper method to construct and transmit an OFPFlowMod message to an OpenFlow switch
    def add_flow(self, datapath, priority, match, actions, buffer_id=None, idle_timeout=0, hard_timeout=0):
        """Installs a flow entry into the OpenFlow table with optional timeouts."""
        # Extract protocol constants
        ofproto = datapath.ofproto
        # Extract protocol parser
        parser = datapath.ofproto_parser

        # Encapsulate action list inside an OpenFlow Apply-Actions instruction
        inst = [parser.OFPInstructionActions(ofproto.OFPIT_APPLY_ACTIONS, actions)]
        # If switch buffered packet, include buffer_id in flow mod
        if buffer_id:
            # Construct OFPFlowMod with buffer reference
            mod = parser.OFPFlowMod(
                datapath=datapath, buffer_id=buffer_id, priority=priority,
                match=match, instructions=inst,
                idle_timeout=idle_timeout, hard_timeout=hard_timeout,
            )
        # Otherwise construct standard OFPFlowMod without buffer
        else:
            # Construct OFPFlowMod
            mod = parser.OFPFlowMod(
                datapath=datapath, priority=priority, match=match, instructions=inst,
                idle_timeout=idle_timeout, hard_timeout=hard_timeout,
            )
        # Transmit flow modification message to switch
        datapath.send_msg(mod)

    # Dynamic SDN method to throttle/demote cross-traffic when port utilization exceeds 80%
    def install_dynamic_throttle(self, datapath, port_no: int, idle_timeout: int = 15):
        """Dynamically installs an OpenFlow flow rule to throttle/demote non-monitoring bulk traffic.

        Triggered dynamically when port utilization exceeds 80% (8 Mbps) on the 10 Mbps bottleneck link.
        Demotes best-effort UDP traffic to Queue 0 and prioritizes monitoring queues.
        """
        # Extract protocol constants
        ofproto = datapath.ofproto
        # Extract protocol parser
        parser = datapath.ofproto_parser

        # Intercept bulk UDP cross-traffic with priority 80 (higher than normal 10, below critical 100)
        match = parser.OFPMatch(
            # Match IPv4 packets
            eth_type=ether_types.ETH_TYPE_IP,
            # Match UDP packets
            ip_proto=17,
        )
        # Demote matching traffic into Queue 0 to prevent packet loss in monitoring queues
        actions = [
            # Assign to Queue 0
            parser.OFPActionSetQueue(queue_id=0),
            # Forward packet normally
            parser.OFPActionOutput(ofproto.OFPP_NORMAL),
        ]
        # Install flow rule with idle_timeout for automatic expiration once burst stops
        self.add_flow(
            datapath,
            priority=80,
            match=match,
            actions=actions,
            idle_timeout=idle_timeout,
        )
        # Log dynamic SDN throttling action
        self.logger.info(
            f"[DYNAMIC SDN ACTION] Switch {datapath.id} Port {port_no}: Installed dynamic QoS throttle rule "
            f"(Priority=80, Queue=0, idle_timeout={idle_timeout}s) to protect monitoring queues!"
        )

    # Dynamic SDN method to delete throttling rule once bottleneck port utilization subsides
    def remove_dynamic_throttle(self, datapath, port_no: int):
        """Removes the dynamic throttle rule once congestion subsides."""
        # Extract protocol constants
        ofproto = datapath.ofproto
        # Extract protocol parser
        parser = datapath.ofproto_parser
        # Match UDP flows that were throttled
        match = parser.OFPMatch(
            # Match IPv4 packets
            eth_type=ether_types.ETH_TYPE_IP,
            # Match UDP packets
            ip_proto=17,
        )
        # Construct strict delete flow mod to remove Priority 80 rule
        mod = parser.OFPFlowMod(
            datapath=datapath,
            command=ofproto.OFPFC_DELETE_STRICT,
            priority=80,
            match=match,
            out_port=ofproto.OFPP_ANY,
            out_group=ofproto.OFPG_ANY,
        )
        # Send deletion message to switch
        datapath.send_msg(mod)
        # Log restoration of normal flow rules
        self.logger.info(
            f"[DYNAMIC SDN RESTORATION] Switch {datapath.id} Port {port_no}: Congestion resolved. "
            f"Removed dynamic throttle rule."
        )

    # Dynamic SDN security method to quarantine a rogue host by injecting a drop rule
    def quarantine_host(self, datapath, host_ip: str, reason: str = "unauthorized_flood", idle_timeout: int = 30):
        """Dynamically installs an OpenFlow DROP rule to isolate a rogue or attacking host."""
        # Extract protocol constants
        ofproto = datapath.ofproto
        # Extract protocol parser
        parser = datapath.ofproto_parser

        # Match all traffic originating from the rogue host's source IP address
        match = parser.OFPMatch(
            # Match IPv4 packets
            eth_type=ether_types.ETH_TYPE_IP,
            # Match rogue source IP address
            ipv4_src=host_ip,
        )
        # Empty action list drops all matching packets in switch hardware/datapath
        self.add_flow(
            datapath,
            priority=200,
            match=match,
            actions=[],
            idle_timeout=idle_timeout,
        )
        # Track quarantined host in memory
        self.quarantined_hosts.add(host_ip)
        # Log quarantine action
        self.logger.warning(
            f"[DYNAMIC SDN SECURITY] Dynamically quarantined host {host_ip} ({reason}). "
            f"Installed OpenFlow DROP rule (Priority=200, idle_timeout={idle_timeout}s)."
        )

    # Dynamic SDN method to remove quarantine DROP rule and restore host connectivity
    def unquarantine_host(self, datapath, host_ip: str):
        """Removes the dynamic quarantine DROP rule for a host."""
        # Extract protocol constants
        ofproto = datapath.ofproto
        # Extract protocol parser
        parser = datapath.ofproto_parser
        # Match packets from previously quarantined host
        match = parser.OFPMatch(
            # Match IPv4 packets
            eth_type=ether_types.ETH_TYPE_IP,
            # Match host IP
            ipv4_src=host_ip,
        )
        # Construct strict delete command for Priority 200 rule
        mod = parser.OFPFlowMod(
            datapath=datapath,
            command=ofproto.OFPFC_DELETE_STRICT,
            priority=200,
            match=match,
            out_port=ofproto.OFPP_ANY,
            out_group=ofproto.OFPG_ANY,
        )
        # Send delete command to switch
        datapath.send_msg(mod)
        # Remove host from quarantined set
        self.quarantined_hosts.discard(host_ip)
        # Log restoration of host connectivity
        self.logger.info(f"[DYNAMIC SDN SECURITY] Unquarantined host {host_ip}. Restored network connectivity.")

    # Event handler for packet-in messages: implements L2 MAC learning and forwarding
    @set_ev_cls(ofp_event.EventOFPPacketIn, MAIN_DISPATCHER)
    def packet_in_handler(self, ev):
        """Handles packet-in events for baseline L2 learning switch behavior."""
        # Extract packet-in message
        msg = ev.msg
        # Extract switch datapath
        datapath = msg.datapath
        # Extract protocol constants
        ofproto = datapath.ofproto
        # Extract protocol parser
        parser = datapath.ofproto_parser
        # Extract ingress switch port number
        in_port = msg.match["in_port"]

        # Parse raw packet bytes
        pkt = packet.Packet(msg.data)
        # Extract Ethernet frame header
        eth = pkt.get_protocols(ethernet.ethernet)[0]

        # Ignore Link Layer Discovery Protocol (LLDP) packets
        if eth.eth_type == ether_types.ETH_TYPE_LLDP:
            # Drop LLDP
            return

        # Extract destination MAC address
        dst = eth.dst
        # Extract source MAC address
        src = eth.src
        # Extract switch DPID
        dpid = datapath.id
        # Ensure MAC learning table exists for this switch
        self.mac_to_port.setdefault(dpid, {})
        # Learn mapping between source MAC and ingress port
        self.mac_to_port[dpid][src] = in_port

        # Look up destination port if previously learned
        if dst in self.mac_to_port[dpid]:
            # Forward directly to learned output port
            out_port = self.mac_to_port[dpid][dst]
        # Otherwise flood packet to all ports
        else:
            # Set output action to flood
            out_port = ofproto.OFPP_FLOOD

        # Define output action
        actions = [parser.OFPActionOutput(out_port)]

        # If destination port is known, install flow rule to avoid future packet-in overhead
        if out_port != ofproto.OFPP_FLOOD:
            # Match on ingress port, source MAC, and destination MAC
            match = parser.OFPMatch(in_port=in_port, eth_dst=dst, eth_src=src)
            # If packet was buffered on switch, include buffer_id
            if msg.buffer_id != ofproto.OFP_NO_BUFFER:
                # Add flow entry referencing buffer
                self.add_flow(datapath, 1, match, actions, msg.buffer_id)
                # Return immediately as switch will output buffered packet
                return
            # Otherwise install flow entry without buffer
            else:
                # Add flow entry
                self.add_flow(datapath, 1, match, actions)

        # Handle raw payload data if packet was not buffered on switch
        data = None
        # Check if buffer is empty
        if msg.buffer_id == ofproto.OFP_NO_BUFFER:
            # Provide raw packet bytes
            data = msg.data

        # Construct Packet-Out message to send current packet out the designated port
        out = parser.OFPPacketOut(
            datapath=datapath, buffer_id=msg.buffer_id, in_port=in_port,
            actions=actions, data=data
        )
        # Transmit Packet-Out message
        datapath.send_msg(out)

    # Periodic background loop polling switch port and flow statistics
    def _stats_monitor_loop(self):
        """Periodically requests port and flow statistics from connected switches."""
        # Run loop continuously while application is active
        while True:
            # Iterate through all active switch datapaths
            for dp in list(self.datapaths.values()):
                # Send statistics request messages to switch
                self._request_stats(dp)
            # Yield execution and sleep cooperatively for poll interval duration
            hub.sleep(self.stats_poll_interval)

    # Helper method to transmit flow and port stats request messages to switch
    def _request_stats(self, datapath):
        # Extract protocol parser
        parser = datapath.ofproto_parser
        # Construct flow stats request message
        req = parser.OFPFlowStatsRequest(datapath)
        # Transmit flow stats request to switch
        datapath.send_msg(req)
        # Construct port stats request message for all ports (OFPP_ANY)
        port_req = parser.OFPPortStatsRequest(datapath, 0, datapath.ofproto.OFPP_ANY)
        # Transmit port stats request to switch
        datapath.send_msg(port_req)

    # Event handler for flow statistics replies from switches
    @set_ev_cls(ofp_event.EventOFPFlowStatsReply, MAIN_DISPATCHER)
    def flow_stats_reply_handler(self, ev):
        """Logs flow stats to CSV and checks link load."""
        # Extract list of flow statistics entries
        body = ev.msg.body
        # Extract switch DPID
        dpid = ev.msg.datapath.id
        # Record current timestamp
        now = time.time()

        # Open flow statistics CSV log file in append mode
        with open(self.flow_stats_file, "a", newline="", encoding="utf-8") as f:
            # Create CSV writer
            writer = csv.writer(f)
            # Iterate through all flow statistics entries reported by switch
            for stat in body:
                # Log non-default rules (priority > 0)
                if stat.priority > 0:
                    # Append flow stats row to CSV
                    writer.writerow([
                        round(now, 2),
                        dpid,
                        stat.priority,
                        str(stat.match),
                        stat.packet_count,
                        stat.byte_count,
                        stat.duration_sec,
                    ])

    # Event handler for port statistics replies: monitors utilization and triggers dynamic throttling
    @set_ev_cls(ofp_event.EventOFPPortStatsReply, MAIN_DISPATCHER)
    def port_stats_reply_handler(self, ev):
        """Monitors port utilization and dynamically mitigates bottleneck link congestion."""
        # Extract port statistics list
        body = ev.msg.body
        # Extract switch datapath
        datapath = ev.msg.datapath
        # Extract switch DPID
        dpid = datapath.id
        # Iterate through port statistics records
        for stat in body:
            # Extract port number
            port_no = stat.port_no
            # Ignore virtual or internal local switch ports (> 100)
            if port_no > 100:
                # Skip
                continue
            # Look up previous transmission stats for this port
            prev = self.port_stats_history.get((dpid, port_no))
            # Record current timestamp
            now = time.time()
            # If previous stats exist, calculate transmission throughput rate
            if prev:
                # Unpack previous transmitted byte count and timestamp
                prev_bytes, prev_ts = prev
                # Calculate elapsed time in seconds
                delta_sec = now - prev_ts
                # Ensure elapsed time is positive
                if delta_sec > 0:
                    # Calculate transmission bitrate in bits per second: (bytes * 8) / seconds
                    rate_bps = ((stat.tx_bytes - prev_bytes) * 8.0) / delta_sec
                    # If bottleneck link (10 Mbps) exceeds 80% capacity (8 Mbps), trigger dynamic throttling
                    if rate_bps >= 8_000_000:
                        # Log congestion warning
                        self.logger.warning(
                            f"[SDN CONGESTION ALERT] Port {port_no} on switch {dpid} TX rate "
                            f"{rate_bps / 1_000_000:.2f} Mbps >= 80% capacity!"
                        )
                        # Check if port has not already been throttled
                        if (dpid, port_no) not in self.throttled_ports:
                            # Install dynamic throttle rule demoting cross-traffic to Queue 0
                            self.install_dynamic_throttle(datapath, port_no)
                            # Record port in throttled set
                            self.throttled_ports.add((dpid, port_no))
                    # If port load drops below 40% (4 Mbps) and port is currently throttled, restore normal rules
                    elif rate_bps < 4_000_000 and (dpid, port_no) in self.throttled_ports:
                        # Delete dynamic throttle rule
                        self.remove_dynamic_throttle(datapath, port_no)
                        # Remove port from throttled set
                        self.throttled_ports.remove((dpid, port_no))
            # Update history cache with current byte count and timestamp
            self.port_stats_history[(dpid, port_no)] = (stat.tx_bytes, now)
