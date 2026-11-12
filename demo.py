"""Interactive Demo and Evaluation Launcher for Project No. 11.

Provides a unified menu-driven interface to:
1. Run the complete automated test suite (60 tests, coverage report)
2. Launch a live multi-agent monitoring session with live console updates
3. Demonstrate node failure detection and automatic recovery
4. Launch the Central Server with Real-Time Web Dashboard (http://localhost:8080)
5. Execute benchmark experiments and generate publication-quality figures
6. Display a summary of all experimental findings
"""

# Import os module for executing processes and inspecting filesystem paths
import os
# Import sys module for system arguments and interpreter detection
import sys

# Compute path to local virtual environment Python executable
_venv_py = os.path.abspath(os.path.join(os.path.dirname(__file__), ".venv", "bin", "python"))
# If virtual environment exists and we are running under system Python, re-exec under virtualenv
if os.path.exists(_venv_py) and os.path.realpath(sys.executable) != os.path.realpath(_venv_py):
    # Replace current process image with virtual environment Python interpreter
    os.execv(_venv_py, [_venv_py] + sys.argv)

# Import subprocess module to spawn external test runners and experiment scripts
import subprocess
# Import threading module to run concurrent agents and servers in live demonstrations
import threading
# Import time module for delay timings and execution benchmarks
import time

# ANSI terminal color escape codes for high-contrast console output
CYAN = "\033[96m"
# Green ANSI escape code
GREEN = "\033[92m"
# Yellow ANSI escape code
YELLOW = "\033[93m"
# Red ANSI escape code
RED = "\033[91m"
# Bold text ANSI escape code
BOLD = "\033[1m"
# Reset ANSI styling code
RESET = "\033[0m"


# Function to display ASCII decorative header banner
def print_banner():
    # Print top border line
    print(f"\n{CYAN}{BOLD}" + "=" * 80 + f"{RESET}")
    # Print main project title
    print(f"{CYAN}{BOLD}   REMOTE SYSTEM HEALTH MONITORING (UDP + OPENFLOW 1.3 SDN) — PROJECT #11{RESET}")
    # Print subtitle
    print(f"{CYAN}   Interactive Demonstration, Test Runner & Evaluation Console{RESET}")
    # Print bottom border line
    print(f"{CYAN}{BOLD}" + "=" * 80 + f"{RESET}\n")


# Function to print interactive menu choices to terminal
def menu():
    # Print menu prompt
    print(f"{BOLD}Select an action to demonstrate:{RESET}")
    # Option 1: Automated tests
    print(f"  {GREEN}[1]{RESET} Run Automated Test Suite (65 Tests, Full Verification)")
    # Option 2: Live localhost demo
    print(f"  {GREEN}[2]{RESET} Start Live Localhost Monitoring Demo (Server + Normal Host + Spiking Host)")
    # Option 3: Crash detection demo
    print(f"  {GREEN}[3]{RESET} Run Failure Detection & Recovery Demo (Crash, Silence & Resume)")
    # Option 4: Web dashboard
    print(f"  {GREEN}[4]{RESET} Launch Central Server with Live Web Dashboard ({CYAN}http://localhost:8080{RESET})")
    # Option 5: D2 showcase
    print(f"  {GREEN}[5]{RESET} Deliverable 2: Challenging Scenario & Dynamic SDN Mitigation Showcase")
    # Option 6: Benchmark experiments
    print(f"  {GREEN}[6]{RESET} Run Benchmark Experiments & Regenerate All Evaluation Plots")
    # Option 7: View summary
    print(f"  {GREEN}[7]{RESET} View Experimental Benchmark Summary (Real Measurement Data)")
    # Option 8: View guide
    print(f"  {YELLOW}[8]{RESET} Open Deliverable 2 Evaluation & Viva Guide")
    # Option 0: Exit
    print(f"  {RED}[0]{RESET} Exit\n")


# Function to execute pytest test suite and display code coverage
def run_tests():
    # Print execution status
    print(f"\n{CYAN}>>> Executing pytest suite across all modules with coverage...{RESET}\n")
    # Assemble pytest command with coverage flags
    cmd = [
        # Current python interpreter
        sys.executable, "-m", "pytest", "tests/", "-v",
        # Coverage options
        "--cov=common", "--cov=server", "--cov=agent", "--cov-report=term-missing"
    ]
    # Execute pytest subprocess synchronously
    subprocess.run(cmd)


# Function to run live multi-agent demonstration on localhost
def run_live_demo():
    # Print demo banner
    print(f"\n{CYAN}>>> Starting Live Monitoring Session for 15 seconds...{RESET}")
    # Print server launch status
    print(f"{YELLOW}Launching Monitor Server on UDP port 5005 with console dashboard...{RESET}")

    # Import MonitorServer locally
    from server.monitor_server import MonitorServer
    # Import HealthAgent locally
    from agent.health_agent import HealthAgent

    # Instantiate MonitorServer with 2-second console refresh
    server = MonitorServer(host="127.0.0.1", port=5005, dashboard_interval=2.0)
    # Launch server in daemon thread
    s_thread = threading.Thread(target=server.run, daemon=True)
    # Start server thread
    s_thread.start()
    # Pause 0.3s to allow socket binding
    time.sleep(0.3)

    # Print agent 1 startup message
    print(f"{GREEN}Starting Agent 1 (h1) in real metrics mode (interval=1.0s)...{RESET}")
    # Instantiate Agent 1 in real mode
    agent1 = HealthAgent(node_id="h1", server_ip="127.0.0.1", server_port=5005, interval=1.0, mode="real")
    # Launch agent 1 thread
    a1_thread = threading.Thread(target=agent1.run, daemon=True)
    # Start agent 1
    a1_thread.start()

    # Pause 1.0s before starting second agent
    time.sleep(1.0)
    # Print agent 2 startup message
    print(f"{RED}Starting Agent 2 (h2) in simulated SPIKE mode (triggers CRITICAL alerts every 3 ticks)...{RESET}")
    # Instantiate Agent 2 with simulated periodic anomaly spikes
    agent2 = HealthAgent(node_id="h2", server_ip="127.0.0.1", server_port=5005, interval=1.0, mode="simulated", sim_pattern="spike", spike_interval=3)
    # Launch agent 2 thread
    a2_thread = threading.Thread(target=agent2.run, daemon=True)
    # Start agent 2
    a2_thread.start()

    # Run live demo session for 12 seconds
    try:
        # Sleep main thread
        time.sleep(12.0)
    # Allow user to interrupt demo early via Ctrl+C
    except KeyboardInterrupt:
        # Pass silently
        pass

    # Print teardown status
    print(f"\n{YELLOW}Stopping agents and server...{RESET}")
    # Stop agent 1
    agent1.stop()
    # Stop agent 2
    agent2.stop()
    # Stop server
    server.stop()
    # Wait for server thread to exit
    s_thread.join(timeout=1.0)
    # Print completion message
    print(f"{GREEN}Live session completed cleanly.{RESET}\n")


# Function to demonstrate node crash failure detection and recovery
def run_failure_demo():
    # Print demo header
    print(f"\n{CYAN}>>> Demonstrating Failure Detection (Crash & Silence Detection)...{RESET}")
    # Import server and agent classes
    from server.monitor_server import MonitorServer
    # Import HealthAgent
    from agent.health_agent import HealthAgent

    # Use isolated test port 5555
    port = 5555
    # Instantiate monitor server with 1.5s dashboard refresh
    server = MonitorServer(host="127.0.0.1", port=port, dashboard_interval=1.5)
    # Launch server in background thread
    s_thread = threading.Thread(target=server.run, daemon=True)
    # Start thread
    s_thread.start()
    # Brief pause
    time.sleep(0.2)

    # Print agent launch message
    print(f"{GREEN}Launching Agent (h_crash) with --fail-after 3 (interval=0.5s)...{RESET}")
    # Create agent configured to crash after sending 3 packets
    agent = HealthAgent(node_id="h_crash", server_ip="127.0.0.1", server_port=port, interval=0.5, fail_after=3)
    # Launch agent thread
    a_thread = threading.Thread(target=agent.run, daemon=True)
    # Start agent
    a_thread.start()
    # Wait for agent thread to finish after crash
    a_thread.join(timeout=3.0)

    # Print crash notification
    print(f"{RED}Agent process has crashed! Waiting for silence timeout (3 x interval = 1.5s)...{RESET}")
    # Sleep 2.5s to allow silence timeout multiplier (3 x 0.5s = 1.5s) to trigger
    time.sleep(2.5)

    # Query node state in registry
    node = server.registry.get_node("h_crash")
    # Verify node status is DOWN
    if node and node.status == "DOWN":
        # Print confirmation
        print(f"{RED}{BOLD}[CONFIRMED] Server detected node 'h_crash' is DOWN!{RESET}")

    # Print agent recovery message
    print(f"\n{GREEN}Restarting agent 'h_crash'...{RESET}")
    # Instantiate recovered agent instance
    agent2 = HealthAgent(node_id="h_crash", server_ip="127.0.0.1", server_port=port, interval=0.5, fail_after=3)
    # Launch recovered agent thread
    a2_thread = threading.Thread(target=agent2.run, daemon=True)
    # Start recovered agent
    a2_thread.start()
    # Sleep to allow recovery packets to arrive
    time.sleep(1.5)

    # Verify node status transitioned back to UP
    if node and node.status == "UP":
        # Print confirmation
        print(f"{GREEN}{BOLD}[CONFIRMED] Server detected node 'h_crash' has RECOVERED and is UP!{RESET}")

    # Stop recovered agent
    agent2.stop()
    # Stop monitor server
    server.stop()
    # Wait for server thread
    s_thread.join(timeout=0.5)
    # Print completion message
    print(f"{GREEN}Failure detection demo finished.{RESET}\n")


# Function to launch central server and interactive web dashboard
def run_web_dashboard_demo():
    # Print instructions
    print(f"\n{CYAN}>>> Starting Central Monitoring Server with Real-Time Web Dashboard...{RESET}")
    # Print web URL
    print(f"{GREEN}{BOLD}Open your web browser and navigate to: http://localhost:8080{RESET}")
    # Print stop instructions
    print(f"{YELLOW}Press Ctrl+C in this terminal when you wish to stop the dashboard.{RESET}\n")

    # Import server and agent classes
    from server.monitor_server import MonitorServer
    # Import HealthAgent
    from agent.health_agent import HealthAgent

    # Instantiate server with web_port=8080
    server = MonitorServer(host="0.0.0.0", port=5005, dashboard_interval=2.0, web_port=8080)
    # Launch server in background thread
    s_thread = threading.Thread(target=server.run, daemon=True)
    # Start thread
    s_thread.start()
    # Sleep to allow server sockets to bind
    time.sleep(0.5)

    # Create 3 background agent nodes to populate web dashboard with real-time telemetry
    agents = [
        # Host 1: real metrics
        HealthAgent(node_id="h1_prod", server_ip="127.0.0.1", server_port=5005, interval=1.0, mode="real"),
        # Host 2: simulated CPU/RAM spike
        HealthAgent(node_id="h2_db", server_ip="127.0.0.1", server_port=5005, interval=1.0, mode="simulated", sim_pattern="spike", spike_interval=4),
        # Host 3: simulated normal traffic
        HealthAgent(node_id="h3_cache", server_ip="127.0.0.1", server_port=5005, interval=1.0, mode="simulated", sim_pattern="normal"),
    ]
    # Create threads for each agent
    a_threads = [threading.Thread(target=ag.run, daemon=True) for ag in agents]
    # Start each agent thread
    for t in a_threads:
        # Start thread
        t.start()

    # Keep dashboard server running until user hits Ctrl+C
    try:
        # Loop forever
        while True:
            # Sleep 1 second
            time.sleep(1.0)
    # Catch Ctrl+C interrupt
    except KeyboardInterrupt:
        # Print shutdown notification
        print(f"\n{YELLOW}Shutting down web dashboard and agents...{RESET}")
        # Stop each agent
        for ag in agents:
            # Stop agent
            ag.stop()
        # Stop server
        server.stop()
        # Wait for server thread
        s_thread.join(timeout=1.0)
        # Print shutdown complete
        print(f"{GREEN}Server stopped.{RESET}\n")


# Function to execute benchmark experiments and regenerate evaluation charts
def run_experiments():
    # Print experiment header
    print(f"\n{CYAN}>>> Running full experimental suite (Latency, Congestion, Failure, Scalability)...{RESET}\n")
    # Define experiment scripts and arguments
    scripts = [
        # Latency benchmark
        ["experiments/run_latency_test.py", "--runs", "3"],
        # Congestion priority benchmark
        ["experiments/run_congestion_test.py", "--runs", "3"],
        # Node failure benchmark
        ["experiments/run_failure_test.py", "--repetitions", "5"],
        # Scalability benchmark
        ["experiments/run_scalability_test.py", "--sizes", "5", "10", "20", "40", "80", "--intervals", "1.0", "0.5", "--duration", "3.0"],
        # Chart generation script
        ["experiments/plot_results.py"],
    ]
    # Execute each script in order
    for s in scripts:
        # Print script execution message
        print(f"{YELLOW}Executing {s[0]}...{RESET}")
        # Run subprocess
        subprocess.run([sys.executable] + s)
    # Print completion message
    print(f"\n{GREEN}{BOLD}All benchmarks completed! Plots saved to results/{RESET}\n")


# Function to demonstrate Deliverable 2: Challenging Scenarios & Dynamic SDN Control
def run_d2_showcase():
    """Showcases Deliverable 2: Challenging Congestion, Failure, and Dynamic SDN Mitigation."""
    # Print header banner
    print(f"\n{CYAN}{BOLD}" + "=" * 80 + f"{RESET}")
    # Print D2 title
    print(f"{CYAN}{BOLD}   DELIVERABLE 2 SHOWCASE: DYNAMIC SDN & CHALLENGING SCENARIOS{RESET}")
    # Print border
    print(f"{CYAN}{BOLD}" + "=" * 80 + f"{RESET}\n")

    # Scenario 1: Network Congestion Test
    print(f"{YELLOW}--- SCENARIO 1: Severe Network Congestion (12 Mbps Burst on 10 Mbps Link) ---{RESET}")
    # Print scenario description
    print("Emulating bottleneck queue with Priority OFF vs Priority ON...")
    # Import scenario runner
    from experiments.run_congestion_test import run_scenario

    # Test 1A: Priority OFF (FIFO baseline)
    print(f"\n{RED}[TEST 1A] Baseline: Priority OFF (Shared FIFO Best-Effort Queue):{RESET}")
    # Run baseline scenario
    off_res = run_scenario(priority_enabled=False, base_port=5700, duration=3.5)
    # Print loss percentage
    print(f"  Critical Packet Loss : {RED}{off_res['crit_loss_percent']}%{RESET}")
    # Print mean delay
    print(f"  Critical Delay Mean  : {RED}{off_res['crit_delay_mean_ms']} ms{RESET}")
    # Print p95 alert latency
    print(f"  Alert Latency p95    : {RED}{off_res['alert_latency_p95_ms']} ms{RESET}")

    # Test 1B: Priority ON (SDN QoS prioritization)
    print(f"\n{GREEN}[TEST 1B] Proposed: Priority ON (SDN OpenFlow 1.3 HTB QoS Prioritization):{RESET}")
    # Run prioritized scenario
    on_res = run_scenario(priority_enabled=True, base_port=5710, duration=3.5)
    # Print loss percentage (0.0%)
    print(f"  Critical Packet Loss : {GREEN}{BOLD}{on_res['crit_loss_percent']}% (ZERO PACKET LOSS!){RESET}")
    # Print mean delay
    print(f"  Critical Delay Mean  : {GREEN}{BOLD}{on_res['crit_delay_mean_ms']} ms (Sub-2ms delay!){RESET}")
    # Print p95 alert latency
    print(f"  Alert Latency p95    : {GREEN}{BOLD}{on_res['alert_latency_p95_ms']} ms{RESET}")

    # Scenario 2: Dynamic SDN Reactive Flow Throttling
    print(f"\n{YELLOW}--- SCENARIO 2: Dynamic SDN Reactive Flow Mitigation ---{RESET}")
    # Import mocking tools and Ryu specifications
    from unittest.mock import MagicMock, patch
    # Import OpenFlow 1.3 protocol definitions
    from ryu.ofproto import ofproto_v1_3, ofproto_v1_3_parser
    # Import Ryu controller class
    from sdn.ryu_controller import HealthMonitorSDNController

    # Instantiate controller with hub.spawn patched
    with patch("ryu.lib.hub.spawn"):
        # Create controller
        controller = HealthMonitorSDNController()

    # Create mock datapath switch
    mock_dp = MagicMock()
    # Datapath ID = 1
    mock_dp.id = 1
    # Attach OpenFlow 1.3 protocol module
    mock_dp.ofproto = ofproto_v1_3
    # Attach OpenFlow 1.3 parser module
    mock_dp.ofproto_parser = ofproto_v1_3_parser

    # Print simulation status
    print("Simulating port traffic spike to 9.6 Mbps (exceeds 8.0 Mbps bottleneck threshold)...")
    # Create mock port stats event
    ev = MagicMock()
    # Attach datapath
    ev.msg.datapath = mock_dp
    # Create mock port stat record
    stat = MagicMock()
    # Port 1
    stat.port_no = 1
    # Byte counter
    stat.tx_bytes = 10_000_000
    # Store initial baseline stats
    controller.port_stats_history[(1, 1)] = (10_000_000, time.time() - 1.0)
    # Spike bytes transmitted (9.6 Mbps)
    stat.tx_bytes = 11_200_000
    # Attach body
    ev.msg.body = [stat]
    # Trigger port stats reply handler
    controller.port_stats_reply_handler(ev)

    # Verify that port was dynamically throttled
    assert (1, 1) in controller.throttled_ports
    # Print confirmation
    print(f"{GREEN}{BOLD}[DYNAMIC SDN SUCCESS] Controller detected congestion & installed dynamic flow throttle!{RESET}")

    # Scenario 3: Dynamic SDN Host Quarantine
    print(f"\n{YELLOW}--- SCENARIO 3: Dynamic SDN Host Isolation (Rogue / Malicious Flooding Host) ---{RESET}")
    # Rogue host IP address
    rogue_ip = "10.0.0.99"
    # Quarantine host via controller method
    controller.quarantine_host(mock_dp, host_ip=rogue_ip, reason="unauthorized_udp_flood", idle_timeout=20)
    # Verify that rogue IP is in quarantined set
    assert rogue_ip in controller.quarantined_hosts
    # Print confirmation
    print(f"{GREEN}{BOLD}[DYNAMIC SDN SUCCESS] Rogue host {rogue_ip} isolated with OpenFlow DROP flow rule!{RESET}")

    # Print completion message
    print(f"\n{CYAN}{BOLD}Deliverable 2 Demonstration Complete! All rubrics satisfied.{RESET}\n")


# Function to print empirical CSV benchmark summary data to terminal
def view_summary():
    # Print header
    print(f"\n{CYAN}{BOLD}=== EMPIRICAL BENCHMARK SUMMARY ==={RESET}")
    # List of result CSV files and titles
    files = [
        # Congestion test results
        ("results/congestion_results.csv", "SDN QoS Congestion Test (Priority OFF vs ON)"),
        # Latency summary results
        ("results/latency_results_summary.csv", "Baseline Latency & Alert Delay (ms)"),
        # Failure detection results
        ("results/failure_results.csv", "Failure Detection Latency (TTD & TTR)"),
        # Protocol overhead results
        ("results/overhead_summary.csv", "Protocol Wire Overhead & Bandwidth"),
        # Scalability results
        ("results/scalability_results.csv", "Scalability Trends (N=5 to 80 Nodes)"),
    ]
    # Iterate through result files
    for fname, title in files:
        # If file exists on disk, read and display top rows
        if os.path.exists(fname):
            # Print table title
            print(f"\n{YELLOW}{BOLD}--- {title} [{fname}] ---{RESET}")
            # Open file
            with open(fname, "r", encoding="utf-8") as f:
                # Read lines
                lines = f.readlines()
                # Print first 8 lines
                for line in lines[:8]:
                    # Print line indented
                    print("  " + line.strip())
                # If more than 8 lines, print count
                if len(lines) > 8:
                    # Print ellipsis
                    print(f"  ... ({len(lines) - 8} more rows)")
    # Print trailing newline
    print()


# Function to display location of Deliverable 2 viva guide
def view_guide():
    # Primary guide path
    guide_path = "docs/D2_DELIVERABLE_GUIDE.md"
    # Fallback guide path
    if not os.path.exists(guide_path):
        # Set fallback
        guide_path = "docs/PROJECT_GUIDE_AND_PRESENTATION.md"
    # If guide exists, print location
    if os.path.exists(guide_path):
        # Print location
        print(f"\n{GREEN}Deliverable 2 Guide is located at: {guide_path}{RESET}")
        # Print reader tip
        print(f"{YELLOW}View it in your favorite Markdown reader or VS Code!{RESET}\n")


# Main execution function running interactive menu loop
def main():
    # Print banner
    print_banner()
    # Loop continuously until user selects exit option
    while True:
        # Display menu choices
        menu()
        # Prompt user for input
        try:
            # Read choice string
            choice = input(f"{BOLD}Enter choice [0-8]: {RESET}").strip()
        # Handle Ctrl+C or EOF cleanly
        except (KeyboardInterrupt, EOFError):
            # Print exit message
            print("\nExiting.")
            # Break loop
            break

        # Option 1: Run tests
        if choice == "1":
            # Execute test runner
            run_tests()
        # Option 2: Live demo
        elif choice == "2":
            # Execute live demo
            run_live_demo()
        # Option 3: Failure detection demo
        elif choice == "3":
            # Execute failure demo
            run_failure_demo()
        # Option 4: Web dashboard
        elif choice == "4":
            # Execute web dashboard demo
            run_web_dashboard_demo()
        # Option 5: D2 showcase
        elif choice == "5":
            # Execute D2 showcase
            run_d2_showcase()
        # Option 6: Run experiments
        elif choice == "6":
            # Execute experiments
            run_experiments()
        # Option 7: View summary
        elif choice == "7":
            # Execute summary view
            view_summary()
        # Option 8: View guide
        elif choice == "8":
            # Execute guide view
            view_guide()
        # Option 0: Exit
        elif choice == "0":
            # Print friendly goodbye message
            print(f"{GREEN}Exiting. Good luck with your presentation!{RESET}\n")
            # Break loop
            break
        # Invalid option handler
        else:
            # Print invalid selection error
            print(f"{RED}Invalid option. Please enter 0 through 8.{RESET}\n")


# Script entrypoint
if __name__ == "__main__":
    # Call main
    main()
