"""Mininet topology script for Remote Health Monitoring evaluation.

Configures a star topology with:
- 1 Central OpenFlow OVS switch (s1)
- 1 Central Monitoring Server (h_server: 10.0.0.100) with a 10 Mbps bottleneck link
- N Monitored Agent Hosts (h1 ... hN: 10.0.0.1 ... 10.0.0.N)
- Remote Ryu OpenFlow 1.3 Controller (127.0.0.1:6633)
- OVS HTB QoS queues on switch-to-server port for priority enforcement
"""

# Import argparse for CLI argument parsing
import argparse
# Import os module for checking root UID and filesystem paths
import os
# Import shutil for locating system binaries on PATH (e.g., ovs-vsctl, iperf)
import shutil
# Import signal module for handling process termination
import signal
# Import subprocess module for running shell commands (ovs-vsctl, mn -c)
import subprocess
# Import sys module for Python interpreter path and standard streams
import sys
# Import time module for delay pauses and timestamps
import time
# Import typing annotations for static type safety
from typing import Dict, List, Optional

# Prepend project root directory to sys.path so project modules can be imported
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

# Import configuration loader function
from common.config_loader import load_config
# Import structured logger setup function
from common.logger import setup_logger

# Instantiate dedicated logger for Mininet topology orchestration
logger = setup_logger("mininet_topology")


# Function to inspect system PATH and determine which required SDN binaries are installed
def check_dependencies() -> Dict[str, bool]:
    """Verifies that all required system binaries are present."""
    # Check for presence of required binaries
    tools = {
        # Check if mininet CLI binary exists
        "mn": shutil.which("mn") is not None,
        # Check if Open vSwitch control utility exists
        "ovs-vsctl": shutil.which("ovs-vsctl") is not None,
        # Check if iperf or iperf3 network performance tool exists
        "iperf": (shutil.which("iperf") is not None or shutil.which("iperf3") is not None),
        # Check if Ryu SDN manager executable exists
        "ryu-manager": (shutil.which("ryu-manager") is not None or os.path.exists(".venv/bin/ryu-manager")),
    }
    # Return dictionary of tool availability flags
    return tools


# Function to verify whether execution environment meets root and dependency prerequisites
def check_environment_or_warn() -> bool:
    """Checks root privileges and required dependencies."""
    # Mininet requires root (UID 0) to manipulate network namespaces and kernel interfaces
    is_root = (os.geteuid() == 0)
    # Check tool availability
    deps = check_dependencies()

    # If not running as root, print informative warning
    if not is_root:
        # Emit warning
        logger.warning(
            "Mininet requires root privileges! Please run with: sudo -E python3 sdn/topology.py"
        )

    # Filter out any tools that are missing from the system
    missing = [tool for tool, present in deps.items() if not present]
    # If any tools are missing, warn the user with OS installation instructions
    if missing:
        # Emit installation guidance warning
        logger.warning(
            f"Missing required tools for full SDN emulation: {', '.join(missing)}.\n"
            f"On Ubuntu/Debian: sudo apt update && sudo apt install -y mininet openvswitch-switch iperf\n"
            f"On Arch/CachyOS:  pacman/AUR mininet, openvswitch, iperf"
        )

    # Return True only if running as root and all dependencies are satisfied
    return is_root and not missing


# Function to configure Linux Hierarchical Token Bucket (HTB) queues on an Open vSwitch egress port
def configure_ovs_qos(switch_name: str, port_name: str, bottleneck_mbps: float = 10.0) -> bool:
    """Configures Linux HTB QoS queues on the switch egress port using ovs-vsctl.

    Queue 0: Best effort (max rate = bottleneck, min rate = 1 Mbps)
    Queue 1: Normal monitoring (min rate = 3 Mbps)
    Queue 2: Critical monitoring (min rate = 5 Mbps guaranteed)
    """
    # Convert bottleneck link capacity from Mbps to bits per second
    rate_bps = int(bottleneck_mbps * 1_000_000)
    # Guaranteed minimum rate for Queue 0 (10% of bottleneck link = 1 Mbps)
    q0_min = int(rate_bps * 0.1)
    # Guaranteed minimum rate for Queue 1 (30% of bottleneck link = 3 Mbps)
    q1_min = int(rate_bps * 0.3)
    # Guaranteed minimum rate for Queue 2 (50% of bottleneck link = 5 Mbps)
    q2_min = int(rate_bps * 0.5)

    # Sequence of ovs-vsctl commands to clear existing QoS and configure new HTB queues
    cmds = [
        # Destroy any existing stale QoS and Queue records on Open vSwitch
        f"ovs-vsctl -- --all destroy QoS -- --all destroy Queue",
        # Create HTB QoS discipline and link Queues 0, 1, and 2 to the port
        (
            f"ovs-vsctl -- set Port {port_name} qos=@newqos -- "
            f"--id=@newqos create QoS type=linux-htb other-config:max-rate={rate_bps} "
            f"queues=0=@q0,1=@q1,2=@q2 -- "
            f"--id=@q0 create Queue other-config:min-rate={q0_min} other-config:max-rate={rate_bps} -- "
            f"--id=@q1 create Queue other-config:min-rate={q1_min} other-config:max-rate={rate_bps} -- "
            f"--id=@q2 create Queue other-config:min-rate={q2_min} other-config:max-rate={rate_bps}"
        ),
    ]

    # Execute each ovs-vsctl command sequentially via subprocess
    for cmd in cmds:
        # Run command synchronously with captured stdout/stderr
        res = subprocess.run(cmd, shell=True, capture_output=True, text=True)
        # Check if command failed
        if res.returncode != 0:
            # Log warning about OVS QoS configuration failure
            logger.warning(f"OVS QoS setup warning for command '{cmd}': {res.stderr.strip()}")
            # Return False on failure
            return False

    # Log successful configuration of Linux HTB queues on switch port
    logger.info(
        f"Configured OVS QoS queues on {port_name}: Q0={q0_min/1e6:.1f}M, "
        f"Q1={q1_min/1e6:.1f}M, Q2={q2_min/1e6:.1f}M (Max {bottleneck_mbps} Mbps)"
    )
    # Return True on success
    return True


# Function to instantiate, start, and run the simulated network environment using Mininet
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
    # Import Mininet core classes locally inside function
    from mininet.net import Mininet
    # Import node types: RemoteController for Ryu, OVSSwitch for Open vSwitch
    from mininet.node import RemoteController, OVSSwitch
    # Import Traffic Control link to enforce bandwidth limits and propagation delay
    from mininet.link import TCLink
    # Import Mininet interactive command-line interface
    from mininet.cli import CLI

    # Log topology startup parameters
    logger.info(f"Starting Mininet topology: {num_hosts} hosts, server={server_ip}:{server_port}")

    # Create Mininet instance without default controller, using OVS switch and TC links
    net = Mininet(controller=None, switch=OVSSwitch, link=TCLink, autoSetMacs=True)

    # Wrap network execution in try/finally to guarantee clean network teardown
    try:
        # Log controller connection details
        logger.info(f"Connecting to Ryu controller at {controller_ip}:{controller_port}")
        # Add external Ryu SDN controller instance
        c0 = net.addController(
            "c0",
            controller=RemoteController,
            ip=controller_ip,
            port=controller_port,
        )

        # Add single central Open vSwitch switch configured for OpenFlow 1.3 protocol
        s1 = net.addSwitch("s1", protocols="OpenFlow13")

        # Add central monitoring server host with static IP (10.0.0.100/24)
        server_host = net.addHost("h_server", ip=f"{server_ip}/24")
        # Connect server to switch with a 10 Mbps bottleneck link and 2ms delay
        server_link = net.addLink(server_host, s1, bw=bottleneck_bw, delay="2ms")

        # Create list to store agent host objects
        agents = []
        # Instantiate each agent host node (h1 ... hN)
        for i in range(1, num_hosts + 1):
            # Compute IP address for this host
            ip_addr = f"10.0.0.{i}"
            # Add host node to Mininet network
            h = net.addHost(f"h{i}", ip=f"{ip_addr}/24")
            # Connect agent to switch with 100 Mbps link and 1ms delay
            net.addLink(h, s1, bw=100, delay="1ms")
            # Append host object to agents list
            agents.append(h)

        # Log build step
        logger.info("Building network and starting switches...")
        # Build network topologies and configure virtual ethernet interfaces
        net.build()
        # Start remote controller communication
        c0.start()
        # Start switch connected to controller
        s1.start([c0])

        # Name of switch port connected to server (first link created is s1-eth1)
        server_port_name = "s1-eth1"
        # Configure Linux HTB queues on switch-to-server bottleneck link
        configure_ovs_qos("s1", server_port_name, bottleneck_mbps=bottleneck_bw)

        # Retrieve current Python interpreter binary path
        py_bin = sys.executable
        # Command line string to launch monitor server inside h_server network namespace
        server_cmd = f"{py_bin} server/monitor_server.py --host {server_ip} --port {server_port} &"
        # Log server command
        logger.info(f"Launching monitor server on {server_host.name}: {server_cmd}")
        # Execute server launch command inside h_server namespace
        server_host.cmd(server_cmd)
        # Sleep 1.0 second to allow server UDP socket to bind
        time.sleep(1.0)

        # Iterate through agent hosts and start HealthAgent process on each
        for i, h in enumerate(agents, start=1):
            # Node 2 is configured with 'spike' anomaly pattern to test alert generation
            pattern = "spike" if (i == 2) else "normal"
            # Command line string to launch health agent inside host namespace
            agent_cmd = (
                f"{py_bin} agent/health_agent.py --id {h.name} --server {server_ip} "
                f"--port {server_port} --interval {interval} --mode {agent_mode} "
                f"--sim-pattern {pattern} &"
            )
            # Log agent launch command
            logger.info(f"Starting agent on {h.name}: {agent_cmd}")
            # Execute agent launch command inside host namespace
            h.cmd(agent_cmd)

        # If run duration was specified, sleep for that duration then exit
        if run_duration:
            # Log duration
            logger.info(f"Running topology for {run_duration} seconds...")
            # Sleep duration
            time.sleep(run_duration)
        # Otherwise hand control over to interactive Mininet CLI
        else:
            # Log CLI prompt instruction
            logger.info("Starting Mininet CLI. Type 'exit' to stop.")
            # Launch interactive Mininet CLI
            CLI(net)

    # Teardown block to cleanly dismantle virtual network interfaces
    finally:
        # Log cleanup
        logger.info("Cleaning up Mininet...")
        # Stop Mininet network
        net.stop()
        # Clean up stale virtual interfaces using mn -c
        subprocess.run(["mn", "-c"], capture_output=True)
        # Log completion
        logger.info("Mininet cleanup complete.")


# Function to configure CLI arguments for Mininet topology script
def parse_args():
    # Instantiate argument parser
    parser = argparse.ArgumentParser(description="Mininet Topology for Health Monitoring")
    # Number of simulated agent hosts (default 5)
    parser.add_argument("--hosts", type=int, default=5, help="Number of agent hosts")
    # Reporting interval in seconds (default 1.0)
    parser.add_argument("--interval", type=float, default=1.0, help="Agent reporting interval (s)")
    # Bottleneck link bandwidth in Mbps (default 10.0)
    parser.add_argument("--bw", type=float, default=10.0, help="Bottleneck link bandwidth (Mbps)")
    # Stats collection mode ('simulated' or 'real')
    parser.add_argument("--mode", choices=["real", "simulated"], default="simulated", help="Stats collector mode")
    # Optional execution duration in seconds
    parser.add_argument("--duration", type=float, default=None, help="Run duration in seconds before auto-exit")
    # Remote Ryu controller IP address
    parser.add_argument("--controller", default="127.0.0.1", help="Ryu controller IP")
    # Remote Ryu controller OpenFlow port
    parser.add_argument("--port", type=int, default=6633, help="Ryu controller port")
    # Parse and return CLI arguments
    return parser.parse_args()


# Main execution entrypoint for Mininet topology script
def main():
    # Parse CLI flags
    args = parse_args()

    # Verify root privileges and required dependencies
    ready = check_environment_or_warn()
    # If environment is not ready, print instructions and exit
    if not ready:
        # Log instructions
        logger.info(
            "To run the live Mininet SDN topology, please install mininet, openvswitch-switch, and iperf, "
            "then run this script with root privileges:\n"
            "  sudo -E python3 sdn/topology.py --hosts 5 --interval 1\n"
        )
        # Exit with error status 1
        sys.exit(1)

    # Launch Mininet topology
    run_mininet_topology(
        num_hosts=args.hosts,
        interval=args.interval,
        bottleneck_bw=args.bw,
        agent_mode=args.mode,
        run_duration=args.duration,
        controller_ip=args.controller,
        controller_port=args.port,
    )


# Standard Python script entrypoint idiom
if __name__ == "__main__":
    # Execute main
    main()
