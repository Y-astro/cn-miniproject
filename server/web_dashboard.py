"""Real-Time Web Dashboard for Remote System Health Monitoring.

Runs a lightweight HTTP server on port 8080 serving a live dark-mode
telemetry interface with node status cards, gauge bars, alerts feed,
and SDN QoS queue metrics.
"""

# Import http.server module to provide built-in HTTP server primitives
import http.server
# Import json module to serialize REST API status responses
import json
# Import os module for filesystem and environment interaction
import os
# Import socketserver module to handle TCP server connections
import socketserver
# Import sys module for system paths and standard streams
import sys
# Import threading module to run web server concurrently in a daemon thread
import threading
# Import time module for timestamp formatting
import time
# Import typing annotations for static type safety
from typing import Any, Dict, Optional

# Prepend project root directory to sys.path so modules can be imported cleanly
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

# Import structured logging factory
from common.logger import setup_logger
# Import MonitorServer type for type annotation
from server.monitor_server import MonitorServer

# Instantiate logger for the web dashboard service
logger = setup_logger("web_dashboard")

# Self-contained HTML/CSS/JavaScript single-page application dashboard
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
        .alert-critical { background-color: rgba(248, 81, 73, 0.15); border: 1px solid var(--accent-red); color: #ff7b72; }
        .alert-warning { background-color: rgba(210, 153, 34, 0.15); border: 1px solid var(--accent-yellow); color: #e3b341; }
    </style>
</head>
<body>
    <div class="header">
        <div>
            <h1>Remote System Health Monitor</h1>
            <p style="font-size: 13px; color: #8b949e; margin-top: 4px;">Real-Time OpenFlow SDN Telemetry & Failure Detection Engine</p>
        </div>
        <div class="badges">
            <div class="badge">Valid Packets: <strong id="valid-packets">0</strong></div>
            <div class="badge">Dropped Packets: <strong id="dropped-packets">0</strong></div>
            <div class="badge green">● Server Live</div>
        </div>
    </div>

    <div class="grid" id="nodes-grid">
        <p style="color: #8b949e; font-size: 14px;">Waiting for telemetry reports from agents...</p>
    </div>

    <div class="alerts-section">
        <h2>Active Alerts Feed (Recent 5 Incidents)</h2>
        <div id="alerts-container">
            <p style="color: #8b949e; font-size: 13px;">No active alerts. All nodes within thresholds.</p>
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
                if (!res.ok) return;
                const data = await res.json();

                document.getElementById('valid-packets').innerText = data.valid_packet_count;
                document.getElementById('dropped-packets').innerText = data.bad_packet_count;

                const grid = document.getElementById('nodes-grid');
                grid.innerHTML = '';

                const nodeIds = Object.keys(data.nodes).sort();
                if (nodeIds.length === 0) {
                    grid.innerHTML = '<p style="color: #8b949e; font-size: 14px;">Waiting for telemetry reports from agents...</p>';
                    return;
                }

                for (const nodeId of nodeIds) {
                    const n = data.nodes[nodeId];
                    const m = n.metrics || {};
                    const cpu = m.cpu_percent !== undefined ? m.cpu_percent : 0;
                    const mem = m.mem_percent !== undefined ? m.mem_percent : 0;
                    const procs = m.process_count !== undefined ? m.process_count : 0;

                    const card = document.createElement('div');
                    card.className = `card ${n.status === 'DOWN' ? 'down' : ''}`;
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


# Custom HTTP request handler serving the static dashboard and JSON REST status endpoints
class DashboardHTTPHandler(http.server.BaseHTTPRequestHandler):
    """Serves the dashboard HTML and the /api/status endpoint."""

    # Class-level reference to the running MonitorServer instance
    server_instance: Optional[MonitorServer] = None

    # Handle incoming HTTP GET requests
    def do_GET(self):
        # Serve main dashboard HTML interface on root or index.html
        if self.path in ("/", "/index.html"):
            # Send HTTP 200 OK status code
            self.send_response(200)
            # Set response MIME content type to HTML with UTF-8 character set
            self.send_header("Content-Type", "text/html; charset=utf-8")
            # Finalize HTTP headers
            self.end_headers()
            # Write raw HTML bytes to HTTP response stream
            self.wfile.write(DASHBOARD_HTML.encode("utf-8"))
        # Serve JSON REST API endpoint containing instantaneous server status
        elif self.path == "/api/status":
            # Send HTTP 200 OK status code
            self.send_response(200)
            # Set response MIME content type to JSON
            self.send_header("Content-Type", "application/json")
            # Allow Cross-Origin Resource Sharing (CORS) for external web apps
            self.send_header("Access-Control-Allow-Origin", "*")
            # Finalize HTTP headers
            self.end_headers()

            # Initialize default empty status dictionary
            status_payload = {"valid_packet_count": 0, "bad_packet_count": 0, "nodes": {}, "active_alerts": []}
            # If reference to MonitorServer exists, extract live metrics
            if self.server_instance:
                # Reference server instance
                s = self.server_instance
                # Total count of valid processed packets
                status_payload["valid_packet_count"] = s.valid_packet_count
                # Total count of malformed or corrupted packets dropped
                status_payload["bad_packet_count"] = s.bad_packet_count

                # Iterate through all registered nodes in NodeRegistry
                for node_id, node in s.registry.nodes.items():
                    # Extract node state dictionary
                    status_payload["nodes"][node_id] = {
                        # Node status ('UP' or 'DOWN')
                        "status": node.status,
                        # Last observed packet sequence number
                        "last_seq": node.last_seq,
                        # Total packets received from this node
                        "total_received": node.total_received,
                        # Packet loss percentage
                        "loss_percent": node.loss_percent,
                        # Moving average delay in milliseconds
                        "avg_delay_ms": node.avg_delay_ms,
                        # Last received telemetry metrics dictionary
                        "metrics": node.last_metrics,
                    }

                # If alert engine is active, export the 5 most recent alerts
                if s.alert_engine:
                    # Slice last 5 alert records from history
                    status_payload["active_alerts"] = [
                        # Convert AlertRecord object to serializable dictionary
                        a.to_dict() for a in s.alert_engine.alert_history[-5:]
                    ]

            # Serialize status dictionary to JSON bytes and write to HTTP socket
            self.wfile.write(json.dumps(status_payload).encode("utf-8"))
        # All other paths return 404 Not Found
        else:
            # Send HTTP 404 Not Found status code
            self.send_response(404)
            # Finalize headers
            self.end_headers()

    # Override standard logging method to suppress spammy HTTP GET request logs in console
    def log_message(self, format, *args):
        # Do nothing to keep terminal output clean and focused on monitor server events
        pass


# Factory function to launch the web dashboard server inside a background daemon thread
def run_web_dashboard(monitor_server: MonitorServer, http_port: int = 8080):
    """Starts the HTTP dashboard server in a background thread."""
    # Store monitor server instance in handler class
    DashboardHTTPHandler.server_instance = monitor_server
    # Attempt binding TCP socket and starting server
    try:
        # Create TCP server bound to all interfaces on specified port
        httpd = socketserver.TCPServer(("0.0.0.0", http_port), DashboardHTTPHandler)
        # Allow address reuse so port is freed immediately on restart
        httpd.allow_reuse_address = True
        # Log successful web server startup with access URL
        logger.info(f"Real-Time Web Dashboard accessible at: http://localhost:{http_port}")
        # Create daemon background thread to run HTTP server serve_forever loop
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        # Start thread
        thread.start()
        # Return server instance
        return httpd
    # Catch socket binding errors (e.g. port 8080 in use)
    except OSError as exc:
        # Log warning without interrupting core UDP server
        logger.warning(f"Could not bind Web Dashboard on port {http_port}: {exc}")
        # Return None
        return None
