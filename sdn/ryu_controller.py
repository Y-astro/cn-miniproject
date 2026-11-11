"""OpenFlow 1.3 Ryu SDN Controller for monitoring traffic prioritization and QoS."""

import csv
import os
import sys
import time
from pathlib import Path

# Eventlet compatibility patch for modern Python environments
try:
    import eventlet.wsgi
    if not hasattr(eventlet.wsgi, "ALREADY_HANDLED"):
        eventlet.wsgi.ALREADY_HANDLED = object()
except Exception:
    pass

from ryu.base import app_manager
from ryu.controller import ofp_event
from ryu.controller.handler import CONFIG_DISPATCHER, MAIN_DISPATCHER, set_ev_cls
from ryu.ofproto import ofproto_v1_3
from ryu.lib.packet import packet, ethernet, ipv4, udp, ether_types
from ryu.lib import hub

# Ensure project root is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from common.config_loader import load_config


class HealthMonitorSDNController(app_manager.RyuApp):
    """Ryu SDN application that prioritizes critical health monitoring traffic."""

    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]

    def __init__(self, *args, **kwargs):
        super(HealthMonitorSDNController, self).__init__(*args, **kwargs)
        self.mac_to_port = {}
        self.datapaths = {}

        # Load configuration
        self.config = {}
        try:
            self.config = load_config("config.yaml")
        except Exception:
            pass

        sdn_cfg = self.config.get("sdn", {})
        self.priority_enabled = sdn_cfg.get("priority_enabled", True)
        self.server_ip = sdn_cfg.get("server_ip", "10.0.0.100")
        self.mon_port = sdn_cfg.get("udp_port", 5005)
        self.dscp_critical = sdn_cfg.get("dscp_critical", 46)
        self.stats_poll_interval = sdn_cfg.get("stats_poll_interval", 2.0)
        self.flow_stats_file = sdn_cfg.get("flow_stats_file", "results/sdn_flow_stats.csv")

        # Stats tracking
        self.port_stats_history = {}
        self.throttled_ports = set()
        self.quarantined_hosts = set()
        self._init_stats_csv()

        # Start background polling thread
        self.monitor_thread = hub.spawn(self._stats_monitor_loop)
        self.logger.info(
            f"HealthMonitorSDNController initialized. Priority mode: "
            f"{'ENABLED' if self.priority_enabled else 'DISABLED'}"
        )

    def _init_stats_csv(self):
        """Initializes CSV file for SDN flow statistics."""
        p = Path(self.flow_stats_file)
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow([
                "timestamp", "dpid", "priority_level", "match", "packet_count", "byte_count", "duration_sec"
            ])

    @set_ev_cls(ofp_event.EventOFPSwitchFeatures, CONFIG_DISPATCHER)
    def switch_features_handler(self, ev):
        """Handles switch connection and installs proactive OpenFlow rules."""
        datapath = ev.msg.datapath
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser
        self.datapaths[datapath.id] = datapath
        self.logger.info(f"Switch connected: dpid={datapath.id}")

        # 1. Default table-miss flow rule (send unhandled packets to controller)
        match = parser.OFPMatch()
        actions = [parser.OFPActionOutput(ofproto.OFPP_CONTROLLER, ofproto.OFPCML_NO_BUFFER)]
        self.add_flow(datapath, priority=0, match=match, actions=actions)

        # 2. Proactive rules if priority is enabled
        if self.priority_enabled:
            self._install_proactive_qos_rules(datapath)
        else:
            self.logger.info("SDN traffic prioritization is DISABLED via configuration.")

    def _install_proactive_qos_rules(self, datapath):
        """Installs proactive rules classifying UDP monitoring traffic by DSCP."""
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser

        # Critical Monitoring Traffic: UDP dst 5005 with DSCP 46 (EF)
        # Higher priority (priority=100), Enqueue to high-priority Queue 2
        match_crit = parser.OFPMatch(
            eth_type=ether_types.ETH_TYPE_IP,
            ip_proto=17,  # UDP
            udp_dst=self.mon_port,
            ip_dscp=self.dscp_critical,
        )
        actions_crit = [
            parser.OFPActionSetQueue(queue_id=2),
            parser.OFPActionOutput(ofproto.OFPP_NORMAL),
        ]
        self.add_flow(datapath, priority=100, match=match_crit, actions=actions_crit)

        # Normal Monitoring Traffic: UDP dst 5005 with normal DSCP (0)
        # Medium priority (priority=50), Enqueue to Queue 1
        match_norm = parser.OFPMatch(
            eth_type=ether_types.ETH_TYPE_IP,
            ip_proto=17,
            udp_dst=self.mon_port,
            ip_dscp=0,
        )
        actions_norm = [
            parser.OFPActionSetQueue(queue_id=1),
            parser.OFPActionOutput(ofproto.OFPP_NORMAL),
        ]
        self.add_flow(datapath, priority=50, match=match_norm, actions=actions_norm)

        # Background Best-Effort Traffic (iperf or other bulk packets)
        # Low priority (priority=10), Enqueue to Queue 0
        match_best_effort = parser.OFPMatch(
            eth_type=ether_types.ETH_TYPE_IP,
            ip_proto=17,
        )
        actions_best_effort = [
            parser.OFPActionSetQueue(queue_id=0),
            parser.OFPActionOutput(ofproto.OFPP_NORMAL),
        ]
        self.add_flow(datapath, priority=10, match=match_best_effort, actions=actions_best_effort)

        self.logger.info("Installed proactive QoS rules: Queue 2 (Critical), Queue 1 (Normal), Queue 0 (Best-Effort)")

    def add_flow(self, datapath, priority, match, actions, buffer_id=None, idle_timeout=0, hard_timeout=0):
        """Installs a flow entry into the OpenFlow table with optional timeouts."""
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser

        inst = [parser.OFPInstructionActions(ofproto.OFPIT_APPLY_ACTIONS, actions)]
        if buffer_id:
            mod = parser.OFPFlowMod(
                datapath=datapath, buffer_id=buffer_id, priority=priority,
                match=match, instructions=inst,
                idle_timeout=idle_timeout, hard_timeout=hard_timeout,
            )
        else:
            mod = parser.OFPFlowMod(
                datapath=datapath, priority=priority, match=match, instructions=inst,
                idle_timeout=idle_timeout, hard_timeout=hard_timeout,
            )
        datapath.send_msg(mod)

    def install_dynamic_throttle(self, datapath, port_no: int, idle_timeout: int = 15):
        """Dynamically installs an OpenFlow flow rule to throttle/demote non-monitoring bulk traffic.

        Triggered dynamically when port utilization exceeds 80% (8 Mbps) on the 10 Mbps bottleneck link.
        Demotes best-effort UDP traffic to Queue 0 and prioritizes monitoring queues.
        """
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser

        # Intercept bulk UDP cross-traffic (priority 80 > normal 10, but < critical monitoring 100)
        match = parser.OFPMatch(
            eth_type=ether_types.ETH_TYPE_IP,
            ip_proto=17,
        )
        actions = [
            parser.OFPActionSetQueue(queue_id=0),
            parser.OFPActionOutput(ofproto.OFPP_NORMAL),
        ]
        self.add_flow(
            datapath,
            priority=80,
            match=match,
            actions=actions,
            idle_timeout=idle_timeout,
        )
        self.logger.info(
            f"[DYNAMIC SDN ACTION] Switch {datapath.id} Port {port_no}: Installed dynamic QoS throttle rule "
            f"(Priority=80, Queue=0, idle_timeout={idle_timeout}s) to protect monitoring queues!"
        )

    def remove_dynamic_throttle(self, datapath, port_no: int):
        """Removes the dynamic throttle rule once congestion subsides."""
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser
        match = parser.OFPMatch(
            eth_type=ether_types.ETH_TYPE_IP,
            ip_proto=17,
        )
        mod = parser.OFPFlowMod(
            datapath=datapath,
            command=ofproto.OFPFC_DELETE_STRICT,
            priority=80,
            match=match,
            out_port=ofproto.OFPP_ANY,
            out_group=ofproto.OFPG_ANY,
        )
        datapath.send_msg(mod)
        self.logger.info(
            f"[DYNAMIC SDN RESTORATION] Switch {datapath.id} Port {port_no}: Congestion resolved. "
            f"Removed dynamic throttle rule."
        )

    def quarantine_host(self, datapath, host_ip: str, reason: str = "unauthorized_flood", idle_timeout: int = 30):
        """Dynamically installs an OpenFlow DROP rule to isolate a rogue or attacking host."""
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser

        match = parser.OFPMatch(
            eth_type=ether_types.ETH_TYPE_IP,
            ipv4_src=host_ip,
        )
        # Empty actions list drops all matching frames in hardware
        self.add_flow(
            datapath,
            priority=200,
            match=match,
            actions=[],
            idle_timeout=idle_timeout,
        )
        self.quarantined_hosts.add(host_ip)
        self.logger.warning(
            f"[DYNAMIC SDN SECURITY] Dynamically quarantined host {host_ip} ({reason}). "
            f"Installed OpenFlow DROP rule (Priority=200, idle_timeout={idle_timeout}s)."
        )

    def unquarantine_host(self, datapath, host_ip: str):
        """Removes the dynamic quarantine DROP rule for a host."""
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser
        match = parser.OFPMatch(
            eth_type=ether_types.ETH_TYPE_IP,
            ipv4_src=host_ip,
        )
        mod = parser.OFPFlowMod(
            datapath=datapath,
            command=ofproto.OFPFC_DELETE_STRICT,
            priority=200,
            match=match,
            out_port=ofproto.OFPP_ANY,
            out_group=ofproto.OFPG_ANY,
        )
        datapath.send_msg(mod)
        self.quarantined_hosts.discard(host_ip)
        self.logger.info(f"[DYNAMIC SDN SECURITY] Unquarantined host {host_ip}. Restored network connectivity.")

    @set_ev_cls(ofp_event.EventOFPPacketIn, MAIN_DISPATCHER)
    def packet_in_handler(self, ev):
        """Handles packet-in events for baseline L2 learning switch behavior."""
        msg = ev.msg
        datapath = msg.datapath
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser
        in_port = msg.match["in_port"]

        pkt = packet.Packet(msg.data)
        eth = pkt.get_protocols(ethernet.ethernet)[0]

        if eth.eth_type == ether_types.ETH_TYPE_LLDP:
            return

        dst = eth.dst
        src = eth.src
        dpid = datapath.id
        self.mac_to_port.setdefault(dpid, {})
        self.mac_to_port[dpid][src] = in_port

        if dst in self.mac_to_port[dpid]:
            out_port = self.mac_to_port[dpid][dst]
        else:
            out_port = ofproto.OFPP_FLOOD

        actions = [parser.OFPActionOutput(out_port)]

        # Install flow to avoid packet-in next time for standard non-monitoring flows
        if out_port != ofproto.OFPP_FLOOD:
            match = parser.OFPMatch(in_port=in_port, eth_dst=dst, eth_src=src)
            if msg.buffer_id != ofproto.OFP_NO_BUFFER:
                self.add_flow(datapath, 1, match, actions, msg.buffer_id)
                return
            else:
                self.add_flow(datapath, 1, match, actions)

        data = None
        if msg.buffer_id == ofproto.OFP_NO_BUFFER:
            data = msg.data

        out = parser.OFPPacketOut(
            datapath=datapath, buffer_id=msg.buffer_id, in_port=in_port,
            actions=actions, data=data
        )
        datapath.send_msg(out)

    def _stats_monitor_loop(self):
        """Periodically requests port and flow statistics from connected switches."""
        while True:
            for dp in list(self.datapaths.values()):
                self._request_stats(dp)
            hub.sleep(self.stats_poll_interval)

    def _request_stats(self, datapath):
        parser = datapath.ofproto_parser
        # Request flow stats
        req = parser.OFPFlowStatsRequest(datapath)
        datapath.send_msg(req)
        # Request port stats
        port_req = parser.OFPPortStatsRequest(datapath, 0, datapath.ofproto.OFPP_ANY)
        datapath.send_msg(port_req)

    @set_ev_cls(ofp_event.EventOFPFlowStatsReply, MAIN_DISPATCHER)
    def flow_stats_reply_handler(self, ev):
        """Logs flow stats to CSV and checks link load."""
        body = ev.msg.body
        dpid = ev.msg.datapath.id
        now = time.time()

        with open(self.flow_stats_file, "a", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            for stat in body:
                if stat.priority > 0:
                    writer.writerow([
                        round(now, 2),
                        dpid,
                        stat.priority,
                        str(stat.match),
                        stat.packet_count,
                        stat.byte_count,
                        stat.duration_sec,
                    ])

    @set_ev_cls(ofp_event.EventOFPPortStatsReply, MAIN_DISPATCHER)
    def port_stats_reply_handler(self, ev):
        """Monitors port utilization and dynamically mitigates bottleneck link congestion."""
        body = ev.msg.body
        datapath = ev.msg.datapath
        dpid = datapath.id
        for stat in body:
            port_no = stat.port_no
            if port_no > 100:  # Skip local or virtual ports
                continue
            prev = self.port_stats_history.get((dpid, port_no))
            now = time.time()
            if prev:
                prev_bytes, prev_ts = prev
                delta_sec = now - prev_ts
                if delta_sec > 0:
                    rate_bps = ((stat.tx_bytes - prev_bytes) * 8.0) / delta_sec
                    # If bottleneck link (10 Mbps) exceeds 80% (8 Mbps) -> Dynamic SDN Congestion Mitigation
                    if rate_bps >= 8_000_000:
                        self.logger.warning(
                            f"[SDN CONGESTION ALERT] Port {port_no} on switch {dpid} TX rate "
                            f"{rate_bps / 1_000_000:.2f} Mbps >= 80% capacity!"
                        )
                        if (dpid, port_no) not in self.throttled_ports:
                            self.install_dynamic_throttle(datapath, port_no)
                            self.throttled_ports.add((dpid, port_no))
                    elif rate_bps < 4_000_000 and (dpid, port_no) in self.throttled_ports:
                        self.remove_dynamic_throttle(datapath, port_no)
                        self.throttled_ports.remove((dpid, port_no))
            self.port_stats_history[(dpid, port_no)] = (stat.tx_bytes, now)
