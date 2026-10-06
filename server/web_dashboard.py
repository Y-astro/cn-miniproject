"""Real-Time Web Dashboard for Remote System Health Monitoring.

Runs a lightweight HTTP server on port 8080 serving a live dark-mode
telemetry interface with node status cards, gauge bars, alerts feed,
and SDN QoS queue metrics.
"""

import http.server
import json
import os
import socketserver
import sys
import threading
import time
from typing import Any, Dict, Optional

# Ensure project root is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from common.logger import setup_logger
from server.monitor_server import MonitorServer

logger = setup_logger("web_dashboard")

DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>SDN Health Monitor | Live Dashboard</title>
    <style>
        :root {
            --bg-primary: #0d1117;
            --bg-secondary: #161b22;
            --bg-card: #21262d;
            --text-primary: #c9d1d9;
            --text-bright: #f0f6fc;
            --accent-blue: #58a6ff;
            --accent-green: #3fb950;
            --accent-yellow: #d29922;
            --accent-red: #f85149;
            --border-color: #30363d;
        }
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
            background-color: var(--bg-primary);
            color: var(--text-primary);
            padding: 24px;
        }
        .header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            border-bottom: 1px solid var(--border-color);
            padding-bottom: 16px;
            margin-bottom: 24px;
        }
        .header h1 { font-size: 22px; color: var(--text-bright); }
        .header .badges { display: flex; gap: 10px; }
        .badge {
            background-color: var(--bg-secondary);
            border: 1px solid var(--border-color);
            border-radius: 6px;
            padding: 6px 12px;
            font-size: 13px;
        }
        .badge strong { color: var(--text-bright); }
        .badge.green { border-color: var(--accent-green); color: var(--accent-green); }
        .grid {
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
            gap: 18px;
            margin-bottom: 24px;
        }
        .card {
            background-color: var(--bg-card);
            border: 1px solid var(--border-color);
            border-radius: 8px;
            padding: 16px;
            transition: transform 0.15s ease, border-color 0.15s ease;
        }
        .card:hover { border-color: var(--accent-blue); transform: translateY(-2px); }
        .card.down { border-color: var(--accent-red); opacity: 0.75; }
        .card-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 12px;
            border-bottom: 1px solid var(--border-color);
            padding-bottom: 8px;
        }
        .card-header h3 { font-size: 16px; color: var(--text-bright); }
        .status-tag {
            font-size: 11px;
            font-weight: 700;
            padding: 2px 8px;
            border-radius: 12px;
            text-transform: uppercase;
        }
        .status-up { background-color: rgba(63, 185, 80, 0.2); color: var(--accent-green); border: 1px solid var(--accent-green); }
        .status-down { background-color: rgba(248, 81, 73, 0.2); color: var(--accent-red); border: 1px solid var(--accent-red); }
        .metric-row { margin-bottom: 10px; }
        .metric-header { display: flex; justify-content: space-between; font-size: 12px; margin-bottom: 4px; }
        .progress-bar-bg {
            background-color: var(--bg-secondary);
            border-radius: 4px;
            height: 8px;
            width: 100%;
            overflow: hidden;
        }
        .progress-bar-fill {
            height: 100%;
            transition: width 0.3s ease, background-color 0.3s ease;
        }
        .stats-footer {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 8px;
            font-size: 11px;
            margin-top: 12px;
            padding-top: 8px;
            border-top: 1px solid var(--border-color);
            color: #8b949e;
        }
        .stats-footer span strong { color: var(--text-bright); }
        .alerts-section {
            background-color: var(--bg-secondary);
            border: 1px solid var(--border-color);
            border-radius: 8px;
            padding: 16px;
        }
        .alerts-section h2 { font-size: 16px; margin-bottom: 12px; color: var(--text-bright); }
        .alert-item {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 8px 12px;
            margin-bottom: 8px;
            border-radius: 6px;
            font-size: 13px;
        }
        .alert-critical { background-color: rgba(248, 81, 73, 0.15); border-left: 4px solid var(--accent-red); color: #ff7b72; }
        .alert-warning { background-color: rgba(210, 153, 34, 0.15); border-left: 4px solid var(--accent-yellow); color: #e3b341; }
        .sdn-banner {
            background: linear-gradient(90deg, #1f2937, #111827);
            border: 1px solid #374151;
            border-radius: 8px;
            padding: 12px 18px;
            margin-bottom: 20px;
            display: flex;
            justify-content: space-between;
            align-items: center;
            font-size: 13px;
        }
        .sdn-tag {
            background-color: #3b82f6;
            color: #ffffff;
            font-weight: bold;
            padding: 3px 8px;
            border-radius: 4px;
            font-size: 11px;
        }
    </style>
</head>
<body>
    <div class="header">
        <div>
            <h1>Remote System Health Monitor</h1>
            <p style="font-size: 13px; color: #8b949e; margin-top: 4px;">
                UDP Telemetry &bull; OpenFlow 1.3 SDN Prioritization &bull; Port 5005
            </p>
        </div>
        <div class="badges">
            <div class="badge green">Status: <strong id="system-status">ACTIVE</strong></div>
            <div class="badge">Valid Packets: <strong id="total-packets">0</strong></div>
            <div class="badge">Dropped: <strong id="dropped-packets">0</strong></div>
            <div class="badge">Active Nodes: <strong id="node-count">0</strong></div>
        </div>
    </div>

    <div class="sdn-banner">
        <div>
            <span class="sdn-tag">OPENFLOW 1.3 QoS</span>
            <span style="margin-left: 10px;">Queue 2 (EF / DSCP 46 Critical): <strong>5 Mbps Guaranteed</strong></span>
            <span style="margin-left: 15px; color: #8b949e;">&bull; Queue 1 (Normal): <strong>3 Mbps</strong></span>
            <span style="margin-left: 15px; color: #8b949e;">&bull; Queue 0 (Best-Effort): <strong>1 Mbps</strong></span>
        </div>
        <div style="color: #38bdf8; font-size: 12px;">Bottleneck Link: 10 Mbps</div>
    </div>

    <div class="grid" id="nodes-grid">
        <!-- Node cards dynamically inserted here -->
    </div>

    <div class="alerts-section">
        <h2>Live Active Alerts & Failure Events</h2>
        <div id="alerts-container">
            <p style="color: #8b949e; font-size: 13px;">No active critical alerts.</p>
        </div>
    </div>

    <script>
        function getBarColor(pct) {
            if (pct >= 90) return 'var(--accent-red)';
            if (pct >= 70) return 'var(--accent-yellow)';
            return 'var(--accent-green)';
        }

        async function updateDashboard() {
            try {
                const res = await fetch('/api/status');
                const data = await res.json();

                document.getElementById('total-packets').textContent = data.valid_packet_count;
                document.getElementById('dropped-packets').textContent = data.bad_packet_count;
                document.getElementById('node-count').textContent = Object.keys(data.nodes).length;

                const grid = document.getElementById('nodes-grid');
                grid.innerHTML = '';

                for (const [nodeId, n] of Object.entries(data.nodes)) {
                    const card = document.createElement('div');
                    card.className = `card ${n.status.toLowerCase()}`;

                    const cpu = n.metrics.cpu_percent || 0;
                    const mem = n.metrics.mem_percent || 0;
                    const procs = n.metrics.process_count || 0;

                    card.innerHTML = `
                        <div class="card-header">
                            <h3>${nodeId}</h3>
                            <span class="status-tag status-${n.status.toLowerCase()}">${n.status}</span>
                        </div>
                        <div class="metric-row">
                            <div class="metric-header">
                                <span>CPU Usage</span>
                                <strong>${cpu}%</strong>
                            </div>
                            <div class="progress-bar-bg">
                                <div class="progress-bar-fill" style="width: ${cpu}%; background-color: ${getBarColor(cpu)};"></div>
                            </div>
                        </div>
                        <div class="metric-row">
                            <div class="metric-header">
                                <span>Memory Usage</span>
                                <strong>${mem}%</strong>
                            </div>
                            <div class="progress-bar-bg">
                                <div class="progress-bar-fill" style="width: ${mem}%; background-color: ${getBarColor(mem)};"></div>
                            </div>
                        </div>
                        <div class="stats-footer">
                            <span>Procs: <strong>${procs}</strong></span>
                            <span>Loss: <strong>${n.loss_percent}%</strong></span>
                            <span>Avg Delay: <strong>${n.avg_delay_ms} ms</strong></span>
                            <span>Seq: <strong>${n.last_seq !== null ? n.last_seq : '-'}</strong></span>
                        </div>
                    `;
                    grid.appendChild(card);
                }

                const alertsBox = document.getElementById('alerts-container');
                if (data.active_alerts && data.active_alerts.length > 0) {
                    alertsBox.innerHTML = '';
                    data.active_alerts.forEach(a => {
                        const div = document.createElement('div');
                        div.className = `alert-item alert-${a.severity.toLowerCase()}`;
                        div.innerHTML = `
                            <span><strong>[${a.severity}]</strong> Node <strong>${a.node_id}</strong>: ${a.metric} = <strong>${a.value}</strong> (Threshold: ${a.threshold})</span>
                            <span style="font-size: 11px; opacity: 0.85;">Latency: ${a.alert_latency_ms} ms</span>
                        `;
                        alertsBox.appendChild(div);
                    });
                } else {
                    alertsBox.innerHTML = '<p style="color: #8b949e; font-size: 13px;">All nodes within normal operational thresholds.</p>';
                }
            } catch (err) {
                console.error("Dashboard update error:", err);
            }
        }

        setInterval(updateDashboard, 1000);
        updateDashboard();
    </script>
</body>
</html>
"""


class DashboardHTTPHandler(http.server.BaseHTTPRequestHandler):
    """Serves the dashboard HTML and the /api/status endpoint."""

    server_instance: Optional[MonitorServer] = None

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(DASHBOARD_HTML.encode("utf-8"))
        elif self.path == "/api/status":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()

            status_payload = {"valid_packet_count": 0, "bad_packet_count": 0, "nodes": {}, "active_alerts": []}
            if self.server_instance:
                s = self.server_instance
                status_payload["valid_packet_count"] = s.valid_packet_count
                status_payload["bad_packet_count"] = s.bad_packet_count

                for node_id, node in s.registry.nodes.items():
                    status_payload["nodes"][node_id] = {
                        "status": node.status,
                        "last_seq": node.last_seq,
                        "total_received": node.total_received,
                        "loss_percent": node.loss_percent,
                        "avg_delay_ms": node.avg_delay_ms,
                        "metrics": node.last_metrics,
                    }

                if s.alert_engine:
                    status_payload["active_alerts"] = [
                        a.to_dict() for a in s.alert_engine.alert_history[-5:]
                    ]

            self.wfile.write(json.dumps(status_payload).encode("utf-8"))
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        # Suppress noisy HTTP request logging in terminal
        pass


def run_web_dashboard(monitor_server: MonitorServer, http_port: int = 8080):
    """Starts the HTTP dashboard server in a background thread."""
    DashboardHTTPHandler.server_instance = monitor_server
    try:
        httpd = socketserver.TCPServer(("0.0.0.0", http_port), DashboardHTTPHandler)
        httpd.allow_reuse_address = True
        logger.info(f"Real-Time Web Dashboard accessible at: http://localhost:{http_port}")
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        return httpd
    except OSError as exc:
        logger.warning(f"Could not bind Web Dashboard on port {http_port}: {exc}")
        return None
