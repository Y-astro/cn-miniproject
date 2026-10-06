"""Interactive Demo and Evaluation Launcher for Project No. 11.

Provides a unified menu-driven interface to:
1. Run the complete automated test suite (60 tests, coverage report)
2. Launch a live multi-agent monitoring session with live console updates
3. Demonstrate node failure detection and automatic recovery
4. Launch the Central Server with Real-Time Web Dashboard (http://localhost:8080)
5. Execute benchmark experiments and generate publication-quality figures
6. Display a summary of all experimental findings
"""

import os
import sys

# Auto-detect and switch to .venv python if running in external/system python
_venv_py = os.path.abspath(os.path.join(os.path.dirname(__file__), ".venv", "bin", "python"))
if os.path.exists(_venv_py) and os.path.realpath(sys.executable) != os.path.realpath(_venv_py):
    os.execv(_venv_py, [_venv_py] + sys.argv)

import subprocess
import threading
import time

CYAN = "\033[96m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
RED = "\033[91m"
BOLD = "\033[1m"
RESET = "\033[0m"


def print_banner():
    print(f"\n{CYAN}{BOLD}" + "=" * 80 + f"{RESET}")
    print(f"{CYAN}{BOLD}   REMOTE SYSTEM HEALTH MONITORING (UDP + OPENFLOW 1.3 SDN) — PROJECT #11{RESET}")
    print(f"{CYAN}   Interactive Demonstration, Test Runner & Evaluation Console{RESET}")
    print(f"{CYAN}{BOLD}" + "=" * 80 + f"{RESET}\n")


def menu():
    print(f"{BOLD}Select an action to demonstrate:{RESET}")
    print(f"  {GREEN}[1]{RESET} Run Automated Test Suite (60 Tests, 87% Code Coverage)")
    print(f"  {GREEN}[2]{RESET} Start Live Localhost Monitoring Demo (Server + Normal Host + Spiking Host)")
    print(f"  {GREEN}[3]{RESET} Run Failure Detection & Recovery Demo (Crash, Silence & Resume)")
    print(f"  {GREEN}[4]{RESET} Launch Central Server with Live Web Dashboard ({CYAN}http://localhost:8080{RESET})")
    print(f"  {GREEN}[5]{RESET} Run Benchmark Experiments & Regenerate All Evaluation Plots")
    print(f"  {GREEN}[6]{RESET} View Experimental Benchmark Summary (Real Measurement Data)")
    print(f"  {YELLOW}[7]{RESET} Open Project Architecture & Teacher Presentation Guide")
    print(f"  {RED}[0]{RESET} Exit\n")


def run_tests():
    print(f"\n{CYAN}>>> Executing pytest suite across all modules with coverage...{RESET}\n")
    cmd = [
        sys.executable, "-m", "pytest", "tests/", "-v",
        "--cov=common", "--cov=server", "--cov=agent", "--cov-report=term-missing"
    ]
    subprocess.run(cmd)


def run_live_demo():
    print(f"\n{CYAN}>>> Starting Live Monitoring Session for 15 seconds...{RESET}")
    print(f"{YELLOW}Launching Monitor Server on UDP port 5005 with console dashboard...{RESET}")

    from server.monitor_server import MonitorServer
    from agent.health_agent import HealthAgent

    server = MonitorServer(host="127.0.0.1", port=5005, dashboard_interval=2.0)
    s_thread = threading.Thread(target=server.run, daemon=True)
    s_thread.start()
    time.sleep(0.3)

    print(f"{GREEN}Starting Agent 1 (h1) in real metrics mode (interval=1.0s)...{RESET}")
    agent1 = HealthAgent(node_id="h1", server_ip="127.0.0.1", server_port=5005, interval=1.0, mode="real")
    a1_thread = threading.Thread(target=agent1.run, daemon=True)
    a1_thread.start()

    time.sleep(1.0)
    print(f"{RED}Starting Agent 2 (h2) in simulated SPIKE mode (triggers CRITICAL alerts every 3 ticks)...{RESET}")
    agent2 = HealthAgent(node_id="h2", server_ip="127.0.0.1", server_port=5005, interval=1.0, mode="simulated", sim_pattern="spike", spike_interval=3)
    a2_thread = threading.Thread(target=agent2.run, daemon=True)
    a2_thread.start()

    try:
        time.sleep(12.0)
    except KeyboardInterrupt:
        pass

    print(f"\n{YELLOW}Stopping agents and server...{RESET}")
    agent1.stop()
    agent2.stop()
    server.stop()
    s_thread.join(timeout=1.0)
    print(f"{GREEN}Live session completed cleanly.{RESET}\n")


def run_failure_demo():
    print(f"\n{CYAN}>>> Demonstrating Failure Detection (Crash & Silence Detection)...{RESET}")
    from server.monitor_server import MonitorServer
    from agent.health_agent import HealthAgent

    port = 5555
    server = MonitorServer(host="127.0.0.1", port=port, dashboard_interval=1.5)
    s_thread = threading.Thread(target=server.run, daemon=True)
    s_thread.start()
    time.sleep(0.2)

    print(f"{GREEN}Launching Agent (h_crash) with --fail-after 3 (interval=0.5s)...{RESET}")
    agent = HealthAgent(node_id="h_crash", server_ip="127.0.0.1", server_port=port, interval=0.5, fail_after=3)
    a_thread = threading.Thread(target=agent.run, daemon=True)
    a_thread.start()
    a_thread.join(timeout=3.0)

    print(f"{RED}Agent process has crashed! Waiting for silence timeout (3 x interval = 1.5s)...{RESET}")
    time.sleep(2.5)

    node = server.registry.get_node("h_crash")
    if node and node.status == "DOWN":
        print(f"{RED}{BOLD}[CONFIRMED] Server detected node 'h_crash' is DOWN!{RESET}")

    print(f"\n{GREEN}Restarting agent 'h_crash'...{RESET}")
    agent2 = HealthAgent(node_id="h_crash", server_ip="127.0.0.1", server_port=port, interval=0.5, fail_after=3)
    a2_thread = threading.Thread(target=agent2.run, daemon=True)
    a2_thread.start()
    time.sleep(1.5)

    if node and node.status == "UP":
        print(f"{GREEN}{BOLD}[CONFIRMED] Server detected node 'h_crash' has RECOVERED and is UP!{RESET}")

    agent2.stop()
    server.stop()
    s_thread.join(timeout=0.5)
    print(f"{GREEN}Failure detection demo finished.{RESET}\n")


def run_web_dashboard_demo():
    print(f"\n{CYAN}>>> Starting Central Monitoring Server with Real-Time Web Dashboard...{RESET}")
    print(f"{GREEN}{BOLD}Open your web browser and navigate to: http://localhost:8080{RESET}")
    print(f"{YELLOW}Press Ctrl+C in this terminal when you wish to stop the dashboard.{RESET}\n")

    from server.monitor_server import MonitorServer
    from agent.health_agent import HealthAgent

    server = MonitorServer(host="0.0.0.0", port=5005, dashboard_interval=2.0, web_port=8080)
    s_thread = threading.Thread(target=server.run, daemon=True)
    s_thread.start()
    time.sleep(0.5)

    # Launch background agents to populate the web dashboard
    agents = [
        HealthAgent(node_id="h1_prod", server_ip="127.0.0.1", server_port=5005, interval=1.0, mode="real"),
        HealthAgent(node_id="h2_db", server_ip="127.0.0.1", server_port=5005, interval=1.0, mode="simulated", sim_pattern="spike", spike_interval=4),
        HealthAgent(node_id="h3_cache", server_ip="127.0.0.1", server_port=5005, interval=1.0, mode="simulated", sim_pattern="normal"),
    ]
    a_threads = [threading.Thread(target=ag.run, daemon=True) for ag in agents]
    for t in a_threads:
        t.start()

    try:
        while True:
            time.sleep(1.0)
    except KeyboardInterrupt:
        print(f"\n{YELLOW}Shutting down web dashboard and agents...{RESET}")
        for ag in agents:
            ag.stop()
        server.stop()
        s_thread.join(timeout=1.0)
        print(f"{GREEN}Server stopped.{RESET}\n")


def run_experiments():
    print(f"\n{CYAN}>>> Running full experimental suite (Latency, Congestion, Failure, Scalability)...{RESET}\n")
    scripts = [
        ["experiments/run_latency_test.py", "--runs", "3"],
        ["experiments/run_congestion_test.py", "--runs", "3"],
        ["experiments/run_failure_test.py", "--repetitions", "5"],
        ["experiments/run_scalability_test.py", "--sizes", "5", "10", "20", "40", "80", "--intervals", "1.0", "0.5", "--duration", "3.0"],
        ["experiments/plot_results.py"],
    ]
    for s in scripts:
        print(f"{YELLOW}Executing {s[0]}...{RESET}")
        subprocess.run([sys.executable] + s)
    print(f"\n{GREEN}{BOLD}All benchmarks completed! Plots saved to results/{RESET}\n")


def view_summary():
    print(f"\n{CYAN}{BOLD}=== EMPIRICAL BENCHMARK SUMMARY ==={RESET}")
    files = [
        ("results/congestion_results.csv", "SDN QoS Congestion Test (Priority OFF vs ON)"),
        ("results/latency_results_summary.csv", "Baseline Latency & Alert Delay (ms)"),
        ("results/failure_results.csv", "Failure Detection Latency (TTD & TTR)"),
        ("results/overhead_summary.csv", "Protocol Wire Overhead & Bandwidth"),
        ("results/scalability_results.csv", "Scalability Trends (N=5 to 80 Nodes)"),
    ]
    for fname, title in files:
        if os.path.exists(fname):
            print(f"\n{YELLOW}{BOLD}--- {title} [{fname}] ---{RESET}")
            with open(fname, "r", encoding="utf-8") as f:
                lines = f.readlines()
                for line in lines[:8]:
                    print("  " + line.strip())
                if len(lines) > 8:
                    print(f"  ... ({len(lines) - 8} more rows)")
    print()


def view_guide():
    guide_path = "docs/PROJECT_GUIDE_AND_PRESENTATION.md"
    if os.path.exists(guide_path):
        print(f"\n{GREEN}Guide is located at: {guide_path}{RESET}")
        print(f"{YELLOW}View it in your favorite Markdown reader or VS Code!{RESET}\n")


def main():
    print_banner()
    while True:
        menu()
        try:
            choice = input(f"{BOLD}Enter choice [0-7]: {RESET}").strip()
        except (KeyboardInterrupt, EOFError):
            print("\nExiting.")
            break

        if choice == "1":
            run_tests()
        elif choice == "2":
            run_live_demo()
        elif choice == "3":
            run_failure_demo()
        elif choice == "4":
            run_web_dashboard_demo()
        elif choice == "5":
            run_experiments()
        elif choice == "6":
            view_summary()
        elif choice == "7":
            view_guide()
        elif choice == "0":
            print(f"{GREEN}Exiting. Good luck with your presentation!{RESET}\n")
            break
        else:
            print(f"{RED}Invalid option. Please enter 0 through 7.{RESET}\n")


if __name__ == "__main__":
    main()
