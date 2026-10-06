"""Mininet topology script for Remote Health Monitoring evaluation.

Configures a star topology with:
- 1 Central OpenFlow OVS switch (s1)
- 1 Central Monitoring Server (h_server: 10.0.0.100) with a 10 Mbps bottleneck link
- N Monitored Agent Hosts (h1 ... hN: 10.0.0.1 ... 10.0.0.N)
- Remote Ryu OpenFlow 1.3 Controller (127.0.0.1:6633)
- OVS HTB QoS queues on switch-to-server port for priority enforcement
"""

import argparse
import os
import shutil
import signal
import subprocess
import sys
import time
from typing import Dict, List, Optional

# Ensure project root is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from common.config_loader import load_config
from common.logger import setup_logger

logger = setup_logger("mininet_topology")


def check_dependencies() -> Dict[str, bool]:
    """Verifies that all required system binaries are present."""
    tools = {
        "mn": shutil.which("mn") is not None,
        "ovs-vsctl": shutil.which("ovs-vsctl") is not None,
        "iperf": (shutil.which("iperf") is not None or shutil.which("iperf3") is not None),
        "ryu-manager": (shutil.which("ryu-manager") is not None or os.path.exists(".venv/bin/ryu-manager")),
    }
    return tools


def check_environment_or_warn() -> bool:
    """Checks root privileges and required dependencies."""
    is_root = (os.geteuid() == 0)
    deps = check_dependencies()

    if not is_root:
        logger.warning(
            "Mininet requires root privileges! Please run with: sudo -E python3 sdn/topology.py"
        )

    missing = [tool for tool, present in deps.items() if not present]
    if missing:
        logger.warning(
            f"Missing required tools for full SDN emulation: {', '.join(missing)}.\n"
            f"On Ubuntu/Debian: sudo apt update && sudo apt install -y mininet openvswitch-switch iperf\n"
            f"On Arch/CachyOS:  pacman/AUR mininet, openvswitch, iperf"
        )

    return is_root and not missing


def configure_ovs_qos(switch_name: str, port_name: str, bottleneck_mbps: float = 10.0) -> bool:
    """Configures Linux HTB QoS queues on the switch egress port using ovs-vsctl.

    Queue 0: Best effort (max rate = bottleneck, min rate = 1 Mbps)
    Queue 1: Normal monitoring (min rate = 3 Mbps)
    Queue 2: Critical monitoring (min rate = 5 Mbps guaranteed)
    """
    rate_bps = int(bottleneck_mbps * 1_000_000)
    q0_min = int(rate_bps * 0.1)
    q1_min = int(rate_bps * 0.3)
    q2_min = int(rate_bps * 0.5)

    cmds = [
        f"ovs-vsctl -- --all destroy QoS -- --all destroy Queue",
        (
            f"ovs-vsctl -- set Port {port_name} qos=@newqos -- "
            f"--id=@newqos create QoS type=linux-htb other-config:max-rate={rate_bps} "
            f"queues=0=@q0,1=@q1,2=@q2 -- "
            f"--id=@q0 create Queue other-config:min-rate={q0_min} other-config:max-rate={rate_bps} -- "
            f"--id=@q1 create Queue other-config:min-rate={q1_min} other-config:max-rate={rate_bps} -- "
            f"--id=@q2 create Queue other-config:min-rate={q2_min} other-config:max-rate={rate_bps}"
        ),
    ]

    for cmd in cmds:
        res = subprocess.run(cmd, shell=True, capture_output=True, text=True)
        if res.returncode != 0:
            logger.warning(f"OVS QoS setup warning for command '{cmd}': {res.stderr.strip()}")
            return False

    logger.info(
        f"Configured OVS QoS queues on {port_name}: Q0={q0_min/1e6:.1f}M, "
        f"Q1={q1_min/1e6:.1f}M, Q2={q2_min/1e6:.1f}M (Max {bottleneck_mbps} Mbps)"
    )
    return True


def run_mininet_topology(
    num_hosts: int = 5,
    interval: float = 1.0,
    bottleneck_bw: float = 10.0,
    agent_mode: str = "simulated",
    run_duration: Optional[float] = None,
    server_ip: str = "10.0.0.100",
    server_port: int = 5005,
    controller_ip: str = "127.0.0.1",
    controller_port: int = 6633,
):
    """Initializes and runs the full Mininet topology."""
    from mininet.net import Mininet
    from mininet.node import RemoteController, OVSSwitch
    from mininet.link import TCLink
    from mininet.cli import CLI

    logger.info(f"Starting Mininet topology: {num_hosts} hosts, server={server_ip}:{server_port}")

    net = Mininet(controller=None, switch=OVSSwitch, link=TCLink, autoSetMacs=True)

    try:
        # Add remote SDN controller
        logger.info(f"Connecting to Ryu controller at {controller_ip}:{controller_port}")
        c0 = net.addController(
            "c0",
            controller=RemoteController,
            ip=controller_ip,
            port=controller_port,
        )

        # Add single central switch with OpenFlow 1.3
        s1 = net.addSwitch("s1", protocols="OpenFlow13")

        # Add central monitoring server
        server_host = net.addHost("h_server", ip=f"{server_ip}/24")
        # Add bottleneck link to switch (10 Mbps)
        server_link = net.addLink(server_host, s1, bw=bottleneck_bw, delay="2ms")

        # Add agent hosts (10.0.0.1 ... 10.0.0.N)
        agents = []
        for i in range(1, num_hosts + 1):
            ip_addr = f"10.0.0.{i}"
            h = net.addHost(f"h{i}", ip=f"{ip_addr}/24")
            net.addLink(h, s1, bw=100, delay="1ms")
            agents.append(h)

        logger.info("Building network and starting switches...")
        net.build()
        c0.start()
        s1.start([c0])

        # Configure OVS QoS on the switch port connected to server
        # Typically s1-eth1 is connected to h_server
        server_port_name = "s1-eth1"
        configure_ovs_qos("s1", server_port_name, bottleneck_mbps=bottleneck_bw)

        # Start server process
        py_bin = sys.executable
        server_cmd = f"{py_bin} server/monitor_server.py --host {server_ip} --port {server_port} &"
        logger.info(f"Launching monitor server on {server_host.name}: {server_cmd}")
        server_host.cmd(server_cmd)
        time.sleep(1.0)

        # Start agent processes
        for i, h in enumerate(agents, start=1):
            pattern = "spike" if (i == 2) else "normal"
            agent_cmd = (
                f"{py_bin} agent/health_agent.py --id {h.name} --server {server_ip} "
                f"--port {server_port} --interval {interval} --mode {agent_mode} "
                f"--sim-pattern {pattern} &"
            )
            logger.info(f"Starting agent on {h.name}: {agent_cmd}")
            h.cmd(agent_cmd)

        if run_duration:
            logger.info(f"Running topology for {run_duration} seconds...")
            time.sleep(run_duration)
        else:
            logger.info("Starting Mininet CLI. Type 'exit' to stop.")
            CLI(net)

    finally:
        logger.info("Cleaning up Mininet...")
        net.stop()
        subprocess.run(["mn", "-c"], capture_output=True)
        logger.info("Mininet cleanup complete.")


def parse_args():
    parser = argparse.ArgumentParser(description="Mininet Topology for Health Monitoring")
    parser.add_argument("--hosts", type=int, default=5, help="Number of agent hosts")
    parser.add_argument("--interval", type=float, default=1.0, help="Agent reporting interval (s)")
    parser.add_argument("--bw", type=float, default=10.0, help="Bottleneck link bandwidth (Mbps)")
    parser.add_argument("--mode", choices=["real", "simulated"], default="simulated", help="Stats collector mode")
    parser.add_argument("--duration", type=float, default=None, help="Run duration in seconds before auto-exit")
    parser.add_argument("--controller", default="127.0.0.1", help="Ryu controller IP")
    parser.add_argument("--port", type=int, default=6633, help="Ryu controller port")
    return parser.parse_args()


def main():
    args = parse_args()

    ready = check_environment_or_warn()
    if not ready:
        logger.info(
            "To run the live Mininet SDN topology, please install mininet, openvswitch-switch, and iperf, "
            "then run this script with root privileges:\n"
            "  sudo -E python3 sdn/topology.py --hosts 5 --interval 1\n"
        )
        sys.exit(1)

    run_mininet_topology(
        num_hosts=args.hosts,
        interval=args.interval,
        bottleneck_bw=args.bw,
        agent_mode=args.mode,
        run_duration=args.duration,
        controller_ip=args.controller,
        controller_port=args.port,
    )


if __name__ == "__main__":
    main()
