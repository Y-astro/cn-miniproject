"""System metrics collection supporting real psutil queries and scripted simulations."""

import random
import time
from typing import Any, Dict, List, Optional
import psutil


class StatsCollector:
    """Collects system performance metrics using psutil or deterministic simulations."""

    def __init__(self, mode: str = "real", sim_pattern: str = "normal", spike_interval: int = 5):
        """Initializes the stats collector.

        Args:
            mode: 'real' to query host OS via psutil, or 'simulated'.
            sim_pattern: Simulation pattern: 'normal', 'spike', 'ramp-up', 'constant-high'.
            spike_interval: In 'spike' pattern, trigger spike every N ticks.
        """
        self.mode = mode
        self.sim_pattern = sim_pattern
        self.spike_interval = spike_interval
        self._tick = 0
        self._ramp_step = 0
        self._prev_net_io = None

    def collect(self) -> Dict[str, Any]:
        """Collects metrics according to configured mode.

        Returns:
            Dict[str, Any] containing cpu_percent, mem_percent, process_count,
            top_processes, and net stats.
        """
        self._tick += 1
        if self.mode == "simulated":
            return self._collect_simulated()
        return self._collect_real()

    def _collect_real(self) -> Dict[str, Any]:
        """Collects real system statistics using psutil with fallback on errors."""
        try:
            cpu_percent = float(psutil.cpu_percent(interval=None))
            mem = psutil.virtual_memory()
            mem_percent = float(mem.percent)

            # Top processes by CPU
            top_processes: List[Dict[str, Any]] = []
            process_count = 0
            try:
                p_list = []
                for p in psutil.process_iter(attrs=["name", "cpu_percent"]):
                    process_count += 1
                    try:
                        info = p.info
                        name = info.get("name") or "unknown"
                        c_pct = float(info.get("cpu_percent") or 0.0)
                        p_list.append({"name": str(name)[:30], "cpu": round(c_pct, 1)})
                    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                        continue
                p_list.sort(key=lambda x: x["cpu"], reverse=True)
                top_processes = p_list[:3]
            except Exception:
                process_count = max(process_count, 1)

            # Network I/O
            net_stats = {"bytes_sent": 0, "bytes_recv": 0, "packets_sent": 0, "packets_recv": 0, "errors": 0}
            try:
                io = psutil.net_io_counters()
                if io:
                    net_stats = {
                        "bytes_sent": int(io.bytes_sent),
                        "bytes_recv": int(io.bytes_recv),
                        "packets_sent": int(io.packets_sent),
                        "packets_recv": int(io.packets_recv),
                        "errors": int(io.errin + io.errout + io.dropin + io.dropout),
                    }
            except Exception:
                pass

            return {
                "cpu_percent": round(max(0.0, min(100.0, cpu_percent)), 1),
                "mem_percent": round(max(0.0, min(100.0, mem_percent)), 1),
                "process_count": int(process_count),
                "top_processes": top_processes,
                "net": net_stats,
            }

        except Exception as exc:
            # Fallback safe response if psutil completely fails
            return {
                "cpu_percent": 0.0,
                "mem_percent": 0.0,
                "process_count": 0,
                "top_processes": [],
                "net": {"bytes_sent": 0, "bytes_recv": 0, "packets_sent": 0, "packets_recv": 0, "errors": 0},
                "collector_error": str(exc),
            }

    def _collect_simulated(self) -> Dict[str, Any]:
        """Generates deterministic simulated statistics."""
        pattern = self.sim_pattern

        if pattern == "spike":
            if self._tick % self.spike_interval == 0:
                cpu = 95.0
                mem = 92.0
                procs = 550
            else:
                cpu = 25.0 + (self._tick % 5)
                mem = 35.0 + (self._tick % 5)
                procs = 120 + (self._tick % 10)

        elif pattern == "ramp-up":
            self._ramp_step += 1
            cpu = min(100.0, 10.0 + self._ramp_step * 10.0)
            mem = min(100.0, 20.0 + self._ramp_step * 8.0)
            procs = 100 + self._ramp_step * 45

        elif pattern == "constant-high":
            cpu = 95.5
            mem = 94.0
            procs = 520

        else:  # 'normal'
            cpu = 20.0 + (self._tick % 10) * 1.5
            mem = 30.0 + (self._tick % 8) * 1.2
            procs = 110 + (self._tick % 15)

        bytes_sent = self._tick * 1024
        bytes_recv = self._tick * 2048
        packets_sent = self._tick * 10
        packets_recv = self._tick * 20

        return {
            "cpu_percent": round(max(0.0, min(100.0, float(cpu))), 1),
            "mem_percent": round(max(0.0, min(100.0, float(mem))), 1),
            "process_count": int(procs),
            "top_processes": [
                {"name": "worker_proc", "cpu": round(cpu * 0.6, 1)},
                {"name": "sys_daemon", "cpu": round(cpu * 0.2, 1)},
            ],
            "net": {
                "bytes_sent": bytes_sent,
                "bytes_recv": bytes_recv,
                "packets_sent": packets_sent,
                "packets_recv": packets_recv,
                "errors": 0,
            },
        }
