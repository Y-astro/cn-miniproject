"""System metrics collection supporting real psutil queries and scripted simulations."""

# Import random module for generating synthetic variance when needed
import random
# Import time module to record timestamps and elapsed collection intervals
import time
# Import typing annotations for static type safety and documentation
from typing import Any, Dict, List, Optional
# Import psutil library to query underlying Linux host CPU, memory, process, and network I/O
import psutil


# Class responsible for sampling host system metrics or generating controlled test telemetry
class StatsCollector:
    """Collects system performance metrics using psutil or deterministic simulations."""

    # Constructor initializing collection mode, simulation scenario, and spike timing
    def __init__(self, mode: str = "real", sim_pattern: str = "normal", spike_interval: int = 5):
        """Initializes the stats collector.

        Args:
            mode: 'real' to query host OS via psutil, or 'simulated'.
            sim_pattern: Simulation pattern: 'normal', 'spike', 'ramp-up', 'constant-high'.
            spike_interval: In 'spike' pattern, trigger spike every N ticks.
        """
        # Operating mode: 'real' uses OS kernel counters via psutil; 'simulated' generates test patterns
        self.mode = mode
        # Pattern mode for simulations ('normal', 'spike', 'ramp-up', 'constant-high')
        self.sim_pattern = sim_pattern
        # Interval in ticks between periodic anomaly spikes for testing alert triggers
        self.spike_interval = spike_interval
        # Monotonically increasing tick counter for each sample collected
        self._tick = 0
        # Step counter for ramp-up simulation scenario
        self._ramp_step = 0
        # Historical network I/O counter placeholder for delta calculations
        self._prev_net_io = None

    # Public method to gather system metrics based on current mode
    def collect(self) -> Dict[str, Any]:
        """Collects metrics according to configured mode.

        Returns:
            Dict[str, Any] containing cpu_percent, mem_percent, process_count,
            top_processes, and net stats.
        """
        # Increment internal sample tick counter
        self._tick += 1
        # Route to simulation generator if mode is set to 'simulated'
        if self.mode == "simulated":
            # Return synthetic metric dictionary
            return self._collect_simulated()
        # Otherwise query the live operating system
        return self._collect_real()

    # Private method to sample live OS hardware and process metrics using psutil
    def _collect_real(self) -> Dict[str, Any]:
        """Collects real system statistics using psutil with fallback on errors."""
        # Wrap OS queries in try/except block to ensure agent resilience
        try:
            # Query instantaneous overall system CPU utilization (interval=None provides non-blocking reading)
            cpu_percent = float(psutil.cpu_percent(interval=None))
            # Query virtual memory subsystem stats (RAM usage)
            mem = psutil.virtual_memory()
            # Extract percentage of physical memory currently utilized
            mem_percent = float(mem.percent)

            # Initialize container for top processes sorted by CPU consumption
            top_processes: List[Dict[str, Any]] = []
            # Initialize running process counter
            process_count = 0
            # Wrap process iteration in try block to handle rapid process creation/termination
            try:
                # Temporary list to hold process metadata
                p_list = []
                # Iterate through all running OS processes requesting process name and CPU usage
                for p in psutil.process_iter(attrs=["name", "cpu_percent"]):
                    # Increment total active process count
                    process_count += 1
                    # Handle processes that may exit or restrict access during iteration
                    try:
                        # Extract process info dictionary
                        info = p.info
                        # Retrieve process name or default to 'unknown'
                        name = info.get("name") or "unknown"
                        # Retrieve CPU percentage attributed to this process
                        c_pct = float(info.get("cpu_percent") or 0.0)
                        # Append process record truncated to 30 characters
                        p_list.append({"name": str(name)[:30], "cpu": round(c_pct, 1)})
                    # Catch transient process lifecycle exceptions cleanly
                    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                        # Skip terminated, zombie, or privileged processes
                        continue
                # Sort processes in descending order of CPU utilization
                p_list.sort(key=lambda x: x["cpu"], reverse=True)
                # Select the top 3 highest CPU-consuming processes
                top_processes = p_list[:3]
            # Handle generic process iteration errors
            except Exception:
                # Ensure process count is at least 1 (the current agent process itself)
                process_count = max(process_count, 1)

            # Initialize default network interface statistics dictionary
            net_stats = {"bytes_sent": 0, "bytes_recv": 0, "packets_sent": 0, "packets_recv": 0, "errors": 0}
            # Attempt to read cumulative network I/O counters from kernel
            try:
                # Query global network interface counters
                io = psutil.net_io_counters()
                # If valid counters were returned, populate net_stats
                if io:
                    # Map psutil counters to standardized protocol dictionary
                    net_stats = {
                        # Cumulative total bytes transmitted by host
                        "bytes_sent": int(io.bytes_sent),
                        # Cumulative total bytes received by host
                        "bytes_recv": int(io.bytes_recv),
                        # Cumulative total packets transmitted
                        "packets_sent": int(io.packets_sent),
                        # Cumulative total packets received
                        "packets_recv": int(io.packets_recv),
                        # Cumulative total network errors (sum of packet drops and transmission errors)
                        "errors": int(io.errin + io.errout + io.dropin + io.dropout),
                    }
            # Catch network stats query failure without crashing
            except Exception:
                # Retain zeroed default counters on network read error
                pass

            # Return validated dictionary clamped within valid physical ranges
            return {
                # Clamp CPU percentage between 0.0% and 100.0%, rounded to 1 decimal place
                "cpu_percent": round(max(0.0, min(100.0, cpu_percent)), 1),
                # Clamp RAM percentage between 0.0% and 100.0%, rounded to 1 decimal place
                "mem_percent": round(max(0.0, min(100.0, mem_percent)), 1),
                # Total active system process count as an integer
                "process_count": int(process_count),
                # Top 3 processes by CPU consumption
                "top_processes": top_processes,
                # Network I/O statistics dictionary
                "net": net_stats,
            }

        # Fallback error handler if psutil encounters a fatal system-level failure
        except Exception as exc:
            # Return safe fallback structure with error diagnostics
            return {
                # Safe zero value for CPU
                "cpu_percent": 0.0,
                # Safe zero value for memory
                "mem_percent": 0.0,
                # Safe zero value for processes
                "process_count": 0,
                # Empty list for top processes
                "top_processes": [],
                # Zeroed network counters
                "net": {"bytes_sent": 0, "bytes_recv": 0, "packets_sent": 0, "packets_recv": 0, "errors": 0},
                # Detailed error message string for debugging
                "collector_error": str(exc),
            }

    # Private method to generate synthetic deterministic metrics for test scenarios
    def _collect_simulated(self) -> Dict[str, Any]:
        """Generates deterministic simulated statistics."""
        # Read the active simulation pattern name
        pattern = self.sim_pattern

        # Scenario: Periodic anomaly spikes to trigger threshold alerts
        if pattern == "spike":
            # Check if current tick is on the spike interval boundary
            if self._tick % self.spike_interval == 0:
                # Spike CPU to 95.0% (triggers CRITICAL threshold)
                cpu = 95.0
                # Spike RAM to 92.0% (triggers CRITICAL threshold)
                mem = 92.0
                # Spike process count to 550 (triggers CRITICAL threshold)
                procs = 550
            # Otherwise generate healthy baseline metrics
            else:
                # Modest baseline CPU around 25-29%
                cpu = 25.0 + (self._tick % 5)
                # Modest baseline RAM around 35-39%
                mem = 35.0 + (self._tick % 5)
                # Normal process count around 120-129
                procs = 120 + (self._tick % 10)

        # Scenario: Progressive linear resource escalation
        elif pattern == "ramp-up":
            # Increment ramp step counter
            self._ramp_step += 1
            # Step CPU upward by 10% each tick, capped at 100%
            cpu = min(100.0, 10.0 + self._ramp_step * 10.0)
            # Step RAM upward by 8% each tick, capped at 100%
            mem = min(100.0, 20.0 + self._ramp_step * 8.0)
            # Step process count upward by 45 each tick
            procs = 100 + self._ramp_step * 45

        # Scenario: Sustained overload condition
        elif pattern == "constant-high":
            # Sustained high CPU above critical threshold
            cpu = 95.5
            # Sustained high RAM above critical threshold
            mem = 94.0
            # Sustained high process count
            procs = 520

        # Scenario: Normal steady-state operation with small realistic oscillations
        else:
            # Steady baseline CPU oscillating between 20% and 35%
            cpu = 20.0 + (self._tick % 10) * 1.5
            # Steady baseline RAM oscillating between 30% and 40%
            mem = 30.0 + (self._tick % 8) * 1.2
            # Steady process count between 110 and 125
            procs = 110 + (self._tick % 15)

        # Calculate simulated cumulative network counters proportional to tick count
        bytes_sent = self._tick * 1024
        # Simulated bytes received counter
        bytes_recv = self._tick * 2048
        # Simulated packets transmitted counter
        packets_sent = self._tick * 10
        # Simulated packets received counter
        packets_recv = self._tick * 20

        # Assemble and return completed simulated metric dictionary
        return {
            # Clamped CPU percentage
            "cpu_percent": round(max(0.0, min(100.0, float(cpu))), 1),
            # Clamped RAM percentage
            "mem_percent": round(max(0.0, min(100.0, float(mem))), 1),
            # Integer process count
            "process_count": int(procs),
            # Simulated top processes with proportional CPU breakdown
            "top_processes": [
                # Primary worker process consuming 60% of CPU load
                {"name": "worker_proc", "cpu": round(cpu * 0.6, 1)},
                # Background system daemon consuming 20% of CPU load
                {"name": "sys_daemon", "cpu": round(cpu * 0.2, 1)},
            ],
            # Simulated network interface counters
            "net": {
                # Bytes sent
                "bytes_sent": bytes_sent,
                # Bytes received
                "bytes_recv": bytes_recv,
                # Packets sent
                "packets_sent": packets_sent,
                # Packets received
                "packets_recv": packets_recv,
                # Zero network errors in simulated clean network
                "errors": 0,
            },
        }
