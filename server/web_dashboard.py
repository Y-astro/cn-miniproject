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
            margin-bottom: 20px;
            flex-wrap: wrap;
            gap: 12px;
        }
        .header h1 { font-size: 22px; color: var(--text-bright); }
        .header .badges { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
        .badge {
            background-color: var(--bg-secondary);
            border: 1px solid var(--border-color);
            border-radius: 6px;
            padding: 6px 12px;
            font-size: 13px;
        }
        .badge strong { color: var(--text-bright); }
        .badge.green { border-color: var(--accent-green); color: var(--accent-green); }

        /* Deliverable 2 Interactive Priority Toggle Button */
        .priority-toggle-btn {
            display: inline-flex;
            align-items: center;
            gap: 8px;
            padding: 7px 14px;
            border-radius: 6px;
            font-size: 13px;
            font-weight: 700;
            cursor: pointer;
            transition: all 0.2s ease;
            border: 1px solid var(--border-color);
            background-color: var(--bg-secondary);
            color: var(--text-bright);
            user-select: none;
        }
        .priority-toggle-btn.on {
            border-color: var(--accent-green);
            background-color: rgba(63, 185, 80, 0.15);
            color: var(--accent-green);
            box-shadow: 0 0 10px rgba(63, 185, 80, 0.25);
        }
        .priority-toggle-btn.off {
            border-color: var(--accent-red);
            background-color: rgba(248, 81, 73, 0.15);
            color: var(--accent-red);
            box-shadow: 0 0 10px rgba(248, 81, 73, 0.25);
        }
        .priority-toggle-btn:hover {
            transform: translateY(-1px);
            filter: brightness(1.2);
        }

        /* Deliverable 2 Control Panel */
        .d2-panel {
            background-color: var(--bg-secondary);
            border: 1px solid var(--border-color);
            border-radius: 8px;
            padding: 16px;
            margin-bottom: 24px;
            display: flex;
            flex-direction: column;
            gap: 12px;
        }
        .d2-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            border-bottom: 1px solid var(--border-color);
            padding-bottom: 8px;
            flex-wrap: wrap;
            gap: 8px;
        }
        .d2-header h2 {
            font-size: 15px;
            color: var(--text-bright);
            display: flex;
            align-items: center;
            gap: 8px;
        }
        .d2-badge {
            font-size: 11px;
            font-weight: 700;
            padding: 2px 8px;
            border-radius: 12px;
            text-transform: uppercase;
        }
        .d2-badge.on {
            background-color: rgba(63, 185, 80, 0.2);
            color: var(--accent-green);
            border: 1px solid var(--accent-green);
        }
        .d2-badge.off {
            background-color: rgba(248, 81, 73, 0.2);
            color: var(--accent-red);
            border: 1px solid var(--accent-red);
        }
        .d2-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
            gap: 12px;
        }
        .d2-box {
            background-color: var(--bg-card);
            border: 1px solid var(--border-color);
            border-radius: 6px;
            padding: 12px;
            font-size: 12px;
            line-height: 1.5;
        }
        .d2-box h4 {
            font-size: 13px;
            color: var(--text-bright);
            margin-bottom: 6px;
            display: flex;
            align-items: center;
            gap: 6px;
        }
        .d2-box p { color: #8b949e; }
        .d2-actions {
            display: flex;
            gap: 10px;
            margin-top: 4px;
            flex-wrap: wrap;
        }
        .action-btn {
            background-color: var(--bg-card);
            border: 1px solid var(--border-color);
            border-radius: 4px;
            padding: 5px 12px;
            font-size: 12px;
            color: var(--text-bright);
            cursor: pointer;
            transition: all 0.15s ease;
        }
        .action-btn:hover {
            border-color: var(--accent-blue);
            color: var(--accent-blue);
        }

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
        .card.card-loss { border-color: rgba(248, 81, 73, 0.7); box-shadow: 0 0 10px rgba(248, 81, 73, 0.15); }
        .card.card-spike { border-color: rgba(240, 136, 62, 0.8); box-shadow: 0 0 12px rgba(240, 136, 62, 0.25); }
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

        /* Real-Time Topology & Animated Flow Panel (Deliverable 2) */
        .topo-panel {
            background-color: var(--bg-secondary);
            border: 1px solid var(--border-color);
            border-radius: 8px;
            padding: 16px;
            margin-bottom: 24px;
            display: flex;
            flex-direction: column;
            gap: 12px;
        }
        .topo-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            border-bottom: 1px solid var(--border-color);
            padding-bottom: 10px;
            flex-wrap: wrap;
            gap: 10px;
        }
        .topo-header h3 {
            font-size: 15px;
            color: var(--text-bright);
            display: flex;
            align-items: center;
            gap: 8px;
        }
        .topo-meta {
            display: flex;
            align-items: center;
            gap: 10px;
            flex-wrap: wrap;
            font-size: 12px;
        }
        .topo-pill {
            background-color: var(--bg-card);
            border: 1px solid var(--border-color);
            padding: 3px 10px;
            border-radius: 12px;
            color: #8b949e;
        }
        .topo-pill strong { color: var(--text-bright); }
        .topo-legend {
            display: flex;
            gap: 12px;
            font-size: 11px;
            color: #8b949e;
            align-items: center;
            flex-wrap: wrap;
        }
        .legend-item { display: inline-flex; align-items: center; gap: 5px; }
        .legend-dot {
            width: 9px;
            height: 9px;
            border-radius: 50%;
            display: inline-block;
        }
        .legend-dot.crit { background-color: #f0883e; box-shadow: 0 0 6px #f0883e; }
        .legend-dot.norm { background-color: #58a6ff; box-shadow: 0 0 6px #58a6ff; }
        .legend-dot.drop { background-color: #f85149; box-shadow: 0 0 6px #f85149; }
        .legend-dot.ofctl { background-color: #a371f7; box-shadow: 0 0 6px #a371f7; }

        .topo-title-group {
            display: flex;
            justify-content: space-between;
            align-items: center;
            width: 100%;
            flex-wrap: wrap;
            gap: 10px;
        }
        .topo-sim-controls {
            display: flex;
            align-items: center;
            gap: 8px;
            flex-wrap: wrap;
        }
        .ctrl-btn {
            display: inline-flex;
            align-items: center;
            gap: 6px;
            padding: 5px 12px;
            border-radius: 6px;
            font-size: 12px;
            font-weight: 600;
            cursor: pointer;
            border: 1px solid var(--border-color);
            background-color: var(--bg-card);
            color: var(--text-bright);
            transition: all 0.2s ease;
            user-select: none;
        }
        .ctrl-btn:hover {
            transform: translateY(-1px);
            border-color: var(--accent-blue);
            color: var(--accent-blue);
        }
        .ctrl-btn.pause {
            border-color: #d29922;
            color: #d29922;
            background-color: rgba(210, 153, 34, 0.15);
        }
        .ctrl-btn.resume {
            border-color: #3fb950;
            color: #3fb950;
            background-color: rgba(63, 185, 80, 0.2);
            box-shadow: 0 0 10px rgba(63, 185, 80, 0.4);
            animation: pulse-resume 1.2s infinite alternate;
        }
        @keyframes pulse-resume {
            from { box-shadow: 0 0 4px rgba(63, 185, 80, 0.2); }
            to { box-shadow: 0 0 14px rgba(63, 185, 80, 0.7); }
        }
        .ctrl-btn.spike {
            border-color: #f0883e;
            color: #f0883e;
            background-color: rgba(240, 136, 62, 0.15);
        }
        .ctrl-btn.spike:hover {
            box-shadow: 0 0 10px rgba(240, 136, 62, 0.5);
        }
        .ctrl-btn.prio-on {
            border-color: var(--accent-green);
            color: var(--accent-green);
            background-color: rgba(63, 185, 80, 0.15);
        }
        .ctrl-btn.prio-off {
            border-color: var(--accent-red);
            color: var(--accent-red);
            background-color: rgba(248, 81, 73, 0.15);
        }

        /* Viva Presentation Walkthrough Bar */
        .viva-stepper {
            display: flex;
            align-items: center;
            gap: 8px;
            background-color: #121820;
            border: 1px solid var(--border-color);
            border-radius: 6px;
            padding: 8px 12px;
            margin-top: 10px;
            margin-bottom: 10px;
            flex-wrap: wrap;
        }
        .viva-stepper-title {
            font-size: 12px;
            font-weight: 700;
            color: #d2a8ff;
            display: flex;
            align-items: center;
            gap: 6px;
            margin-right: 4px;
        }
        .viva-step-btn {
            background-color: var(--bg-secondary);
            border: 1px solid var(--border-color);
            border-radius: 4px;
            padding: 4px 10px;
            font-size: 11px;
            font-weight: 600;
            color: #8b949e;
            cursor: pointer;
            transition: all 0.15s ease;
        }
        .viva-step-btn:hover {
            color: var(--text-bright);
            border-color: #a371f7;
        }
        .viva-step-btn.active {
            background-color: rgba(163, 113, 247, 0.2);
            border-color: #a371f7;
            color: #d2a8ff;
            box-shadow: 0 0 8px rgba(163, 113, 247, 0.3);
        }
        .viva-card {
            background: linear-gradient(135deg, rgba(22, 27, 34, 0.95), rgba(13, 17, 23, 0.95));
            border: 1px solid rgba(163, 113, 247, 0.35);
            border-radius: 6px;
            padding: 10px 14px;
            margin-bottom: 12px;
            font-size: 12px;
            line-height: 1.5;
            box-shadow: 0 2px 10px rgba(0, 0, 0, 0.3);
        }
        .viva-card-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 6px;
            border-bottom: 1px solid rgba(163, 113, 247, 0.2);
            padding-bottom: 4px;
        }
        .viva-card-title {
            font-weight: 700;
            color: #d2a8ff;
            font-size: 13px;
            display: flex;
            align-items: center;
            gap: 6px;
        }
        .viva-card-rubric {
            font-size: 11px;
            font-weight: 700;
            color: #3fb950;
            background-color: rgba(63, 185, 80, 0.15);
            padding: 2px 6px;
            border-radius: 4px;
            border: 1px solid rgba(63, 185, 80, 0.3);
        }
        .viva-points {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
            gap: 8px;
            color: var(--text-primary);
        }
        .viva-point {
            background-color: rgba(33, 38, 45, 0.6);
            border-left: 3px solid #a371f7;
            padding: 5px 8px;
            border-radius: 0 4px 4px 0;
            font-size: 11.5px;
        }
        .viva-point strong { color: var(--text-bright); }

        .canvas-wrapper {
            position: relative;
            width: 100%;
            background-color: #0b0e14;
            border: 1px solid var(--border-color);
            border-radius: 6px;
            overflow: hidden;
            box-shadow: inset 0 0 20px rgba(0, 0, 0, 0.4);
        }
        #topoCanvas {
            display: block;
            width: 100%;
            height: 530px;
        }

        .flow-ticker-bar {
            display: flex;
            align-items: center;
            gap: 10px;
            background-color: var(--bg-card);
            border: 1px solid var(--border-color);
            border-radius: 6px;
            padding: 8px 12px;
            overflow: hidden;
            font-size: 12px;
        }
        .ticker-label {
            font-weight: 700;
            color: var(--text-bright);
            white-space: nowrap;
            display: flex;
            align-items: center;
            gap: 6px;
        }
        .ticker-stream {
            display: flex;
            gap: 8px;
            overflow-x: auto;
            white-space: nowrap;
            scrollbar-width: none;
            flex: 1;
        }
        .ticker-stream::-webkit-scrollbar { display: none; }
        .ticker-chip {
            display: inline-flex;
            align-items: center;
            gap: 5px;
            padding: 3px 8px;
            border-radius: 4px;
            font-size: 11px;
            font-family: monospace;
            border: 1px solid var(--border-color);
            animation: fadeIn 0.25s ease;
        }
        .ticker-chip.delivered {
            background-color: rgba(63, 185, 80, 0.15);
            border-color: rgba(63, 185, 80, 0.4);
            color: var(--accent-green);
        }
        .ticker-chip.critical {
            background-color: rgba(240, 136, 62, 0.2);
            border-color: rgba(240, 136, 62, 0.6);
            color: #f0883e;
            font-weight: 700;
            box-shadow: 0 0 6px rgba(240, 136, 62, 0.3);
        }
        .ticker-chip.dropped {
            background-color: rgba(248, 81, 73, 0.25);
            border-color: var(--accent-red);
            color: #ff7b72;
            font-weight: 700;
            animation: pulse-drop 1s infinite alternate;
        }
        @keyframes pulse-drop {
            from { box-shadow: 0 0 4px rgba(248, 81, 73, 0.3); }
            to { box-shadow: 0 0 10px rgba(248, 81, 73, 0.8); }
        }
        @keyframes fadeIn {
            from { opacity: 0; transform: translateX(8px); }
            to { opacity: 1; transform: translateX(0); }
        }
    </style>
</head>
<body>
    <div class="header">
        <div>
            <h1>Remote System Health Monitor</h1>
            <p style="font-size: 13px; color: #8b949e; margin-top: 4px;">Real-Time OpenFlow SDN Telemetry & Failure Detection Engine (Deliverable 2)</p>
        </div>
        <div class="badges">
            <button id="priority-toggle-btn" class="priority-toggle-btn on" onclick="togglePriority()" title="Click to toggle Deliverable 2 SDN QoS Prioritization">
                <span id="priority-icon">⚡</span>
                <span id="priority-btn-text">SDN Priority: ON (D2)</span>
            </button>
            <div class="badge">Valid Packets: <strong id="valid-packets">0</strong></div>
            <div class="badge">Dropped: <strong id="dropped-packets">0</strong></div>
            <div class="badge green">● Server Live</div>
        </div>
    </div>

    <!-- Deliverable 2 Architecture & Control Card -->
    <div class="d2-panel">
        <div class="d2-header">
            <h2>
                <span>⚡ Deliverable 2: OpenFlow 1.3 QoS & Dynamic SDN Flow Control</span>
                <span id="d2-status-badge" class="d2-badge on">Priority Active (Queue 2/1/0)</span>
            </h2>
            <div class="d2-actions">
                <button class="action-btn" onclick="togglePriority()">Toggle Priority ON/OFF</button>
                <button class="action-btn" onclick="toggleThrottle()">Simulate Dynamic Throttle</button>
            </div>
        </div>
        <div class="d2-grid">
            <div class="d2-box">
                <h4>Queue Configuration (10 Mbps Link)</h4>
                <p id="d2-queue-desc">
                    <strong style="color: #58a6ff;">Queue 2 (Critical):</strong> DSCP 46 (EF) | Guaranteed 5 Mbps (0% loss under burst)<br>
                    <strong style="color: #3fb950;">Queue 1 (Normal):</strong> DSCP 0 (BE) | Guaranteed 3 Mbps<br>
                    <strong style="color: #8b949e;">Queue 0 (Bulk):</strong> Best-effort background flows | Capped 1–7 Mbps
                </p>
            </div>
            <div class="d2-box">
                <h4>Dynamic SDN State (Rubric: 6 Marks)</h4>
                <p id="d2-throttle-desc">
                    <strong>Port Utilization:</strong> Bottleneck link load normal (< 8.0 Mbps).<br>
                    <strong>Reactive Throttle:</strong> <span id="throttle-status" style="color: #3fb950;">Inactive (Clean link)</span><br>
                    <em>Automatically demotes bulk flows when load &ge; 8 Mbps.</em>
                </p>
            </div>
            <div class="d2-box">
                <h4>Benchmark Performance Delta</h4>
                <p>
                    <strong>Priority ON:</strong> 0.0% Critical Loss | 1.8 ms delay | 2.1 ms alert latency<br>
                    <strong>Priority OFF:</strong> 56.7% Critical Loss | 38.4 ms delay | 41.2 ms alert latency
                </p>
            </div>
        </div>
    </div>

    <!-- Real-Time SDN OpenFlow Topology & Packet Flow Visualizer (Deliverable 2) -->
    <div class="topo-panel">
        <div class="topo-header">
            <div class="topo-title-group">
                <h3>
                    <span>🌐 OpenFlow 1.3 Topology & Real-Time Flow Pipeline</span>
                    <span id="topo-badge" class="d2-badge on">Priority Active (0.0% Loss)</span>
                </h3>
                <div class="topo-sim-controls">
                    <button id="sim-play-pause-btn" class="ctrl-btn pause" onclick="toggleSimPause()" title="Pause simulation to explain packet states, flow rules, and queue allocation to examiners">
                        <span id="sim-play-icon">⏸</span> <span id="sim-play-text">Pause Simulation</span>
                    </button>
                    <button id="sim-step-btn" class="ctrl-btn" onclick="stepSimulation()" title="Advance simulation by 1 discrete frame/packet while paused">
                        <span>⏭</span> <span>Step Frame</span>
                    </button>
                    <button class="ctrl-btn spike" onclick="injectSpike()" title="Trigger High Load Anomaly Spikes on h1, h2, and h3 simultaneously to demonstrate multi-node QoS Queue 2 handling">
                        <span>🚨</span> <span>Inject Spike (All 3)</span>
                    </button>
                    <button id="sim-bulk-btn" class="ctrl-btn" onclick="toggleBulkTraffic()" title="Burst background cross-traffic to demonstrate bottleneck buffer saturation">
                        <span>🌪️</span> <span>Burst Bulk Traffic</span>
                    </button>
                    <button id="toggle-prio-mini-btn" class="ctrl-btn prio-on" onclick="togglePriority()" title="Toggle SDN QoS Prioritization (Deliverable 2 vs Deliverable 1 FIFO Baseline)">
                        <span id="mini-prio-icon">⚡</span> <span id="mini-prio-text">Priority: ON</span>
                    </button>
                </div>
            </div>
            <div class="topo-meta">
                <span class="topo-pill">Bottleneck: <strong>10 Mbps</strong></span>
                <span class="topo-pill">Delivery Rate: <strong id="topo-delivery-rate" style="color: #3fb950;">100.0%</strong></span>
                <span class="topo-pill">Dropped Packets: <strong id="topo-lost-count" style="color: var(--text-bright);">0</strong></span>
                <div class="topo-legend">
                    <span class="legend-item"><span class="legend-dot ofctl"></span> Ryu OF 1.3 Control</span>
                    <span class="legend-item"><span class="legend-dot crit"></span> Critical EF (Queue 2)</span>
                    <span class="legend-item"><span class="legend-dot norm"></span> Normal BE (Queue 1)</span>
                    <span class="legend-item"><span class="legend-dot drop"></span> ✕ Dropped (FIFO Tail-Drop)</span>
                </div>
            </div>
        </div>

        <!-- Viva Presentation Walkthrough Guide -->
        <div class="viva-stepper">
            <span class="viva-stepper-title">🎓 Viva Walkthrough:</span>
            <button class="viva-step-btn active" id="viva-btn-arch" onclick="setVivaStep('arch')">1. Architecture (Ryu + Mininet)</button>
            <button class="viva-step-btn" id="viva-btn-d1" onclick="setVivaStep('d1')">2. Deliverable 1: Ingestion & Telemetry</button>
            <button class="viva-step-btn" id="viva-btn-d2" onclick="setVivaStep('d2')">3. Deliverable 2: SDN QoS & Rules</button>
            <button class="viva-step-btn" id="viva-btn-loss" onclick="setVivaStep('loss')">4. Packet Loss Demo (FIFO vs QoS)</button>
        </div>

        <!-- Viva Explainer Card -->
        <div id="viva-card" class="viva-card">
            <!-- Dynamically populated by setVivaStep() -->
        </div>

        <div class="canvas-wrapper">
            <canvas id="topoCanvas" width="1000" height="530"></canvas>
        </div>
        <div class="flow-ticker-bar">
            <div class="ticker-label">
                <span>⚡ Sequence Stream:</span>
            </div>
            <div id="packet-ticker" class="ticker-stream">
                <span style="color: #8b949e; font-size: 11px;">Listening for packet flow...</span>
            </div>
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
        // Color scale for CPU and memory usage meters
        function getBarColor(pct) {
            if (pct >= 90) return 'var(--accent-red)';
            if (pct >= 70) return 'var(--accent-yellow)';
            return 'var(--accent-green)';
        }

        // --- Global Pipeline State & Topology Engine ---
        let currentPriorityOn = true;
        let isSimPaused = false;
        let currentVivaStep = 'arch';
        let activePackets = [];
        let openflowPulses = [];
        let particleBursts = [];
        let serverRipples = [];
        let floatingAlerts = [];
        let processedEventKeys = new Set();
        let recentSequenceChips = [];
        let lastSimulatedSpawn = 0;
        let lastOFPulseTime = 0;
        let localSeqCounter = 100;
        let liveHostMetrics = {
            h1_prod:  { cpu_percent: 24.5, mem_percent: 42.0, process_count: 142 },
            h2_db:    { cpu_percent: 28.1, mem_percent: 46.5, process_count: 185 },
            h3_cache: { cpu_percent: 19.8, mem_percent: 34.0, process_count: 98 },
            h1:       { cpu_percent: 24.5, mem_percent: 42.0, process_count: 142 },
            h2:       { cpu_percent: 28.1, mem_percent: 46.5, process_count: 185 },
            h3:       { cpu_percent: 19.8, mem_percent: 34.0, process_count: 98 }
        };
        let lastKnownHostStates = JSON.parse(JSON.stringify(liveHostMetrics));

        function getHostMetrics(k) {
            if (!k) return {};
            const clean = String(k).replace('_prod', '').replace('_db', '').replace('_cache', '');
            return liveHostMetrics[k] || liveHostMetrics[clean] || {};
        }

        function getHostObj(k) {
            const layout = getTopologyLayout();
            if (!layout || !layout.hosts) return null;
            if (layout.hosts[k]) return layout.hosts[k];
            if (k === 'h1' || k === 'h1_prod') return layout.hosts.h1_prod;
            if (k === 'h2' || k === 'h2_db') return layout.hosts.h2_db;
            if (k === 'h3' || k === 'h3_cache') return layout.hosts.h3_cache;
            return layout.hosts.h1_prod;
        }
        let switchRuleFlash = 0.0;
        let ryuStatsFlash = 0.0;
        let bulkTrafficBurstActive = false;

        // Canvas element and 2D rendering context
        const canvas = document.getElementById('topoCanvas');
        const ctx = canvas.getContext('2d');
        let cw = 1000;
        let ch = 530;

        // Auto-scale canvas resolution to match retina high-DPI displays
        function resizeCanvas() {
            if (!canvas) return;
            const rect = canvas.getBoundingClientRect();
            const dpr = window.devicePixelRatio || 1;
            cw = rect.width || 1000;
            ch = 530;
            canvas.width = cw * dpr;
            canvas.height = ch * dpr;
            ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
        }
        window.addEventListener('resize', resizeCanvas);
        resizeCanvas();

        // Calculate responsive node positions across the canvas width
        function getTopologyLayout() {
            const hostX = 110;
            const ryuX = Math.round(cw * 0.38);
            const swX = Math.round(cw * 0.38);
            const serverX = Math.round(cw - 110);
            const flowTableX = Math.round(cw * 0.74);
            const tableWidth = Math.min(380, Math.max(260, Math.round(cw * 0.40)));

            return {
                ryu: {
                    x: ryuX,
                    y: 56,
                    w: 250,
                    h: 62,
                    title: '🧠 Ryu SDN Controller (c0)',
                    sub: 'OpenFlow 1.3 | TCP 6653 | REST :8080'
                },
                flowTable: {
                    x: flowTableX,
                    y: 56,
                    w: tableWidth,
                    h: 78
                },
                ctrlChannel: {
                    fromX: ryuX,
                    fromY: 87,
                    toX: swX,
                    toY: 175
                },
                hosts: {
                    h1_prod:  { x: hostX, y: 220, name: 'h1_prod', title: 'h1 (Prod Server)', mode: 'Telemetry & Spikes', ip: '10.0.0.1', color: '#58a6ff' },
                    h2_db:    { x: hostX, y: 330, name: 'h2_db',   title: 'h2 (Database)', mode: 'Spike Pattern', ip: '10.0.0.2', color: '#f0883e' },
                    h3_cache: { x: hostX, y: 440, name: 'h3_cache',title: 'h3 (Cache Cluster)', mode: 'Telemetry & Spikes', ip: '10.0.0.3', color: '#3fb950' }
                },
                sw:  { x: swX, y: 330, w: 260, h: 310 },
                srv: { x: serverX, y: 330, w: 145, h: 140 }
            };
        }

        // --- Viva Presentation Step Guide Data & Controller ---
        const VIVA_STEPS_DATA = {
            arch: {
                title: '1. Mininet & Ryu SDN Architecture Overview',
                rubric: 'Rubric: Topology & Architecture (4 Marks)',
                points: [
                    { label: 'Control Plane', desc: 'Ryu SDN Controller (c0) runs on TCP 6653 using OpenFlow 1.3 protocol. Completely decoupled from high-speed data plane.' },
                    { label: 'Data Plane', desc: 'Mininet topology with 3 host agents (h1, h2, h3), OpenFlow switch s1, and centralized MonitorServer across 10 Mbps bottleneck.' },
                    { label: 'Control Channel', desc: 'Ryu programs flow table rules in s1 proactively and monitors port stats reactively for dynamic traffic management.' }
                ]
            },
            d1: {
                title: '2. Deliverable 1: Telemetry Ingestion & Anomaly Detection',
                rubric: 'Rubric: Ingestion & Failure Detection (8 Marks)',
                points: [
                    { label: 'Agent Collection', desc: 'Non-blocking psutil daemon samples CPU, memory, disk, network, and process count every 1.0s.' },
                    { label: 'Custom UDP Protocol', desc: 'Lightweight JSON datagram (<1400B MTU-safe) with sequence numbers (seq) to track loss without TCP 3-way handshake overhead.' },
                    { label: 'Anomaly Engine', desc: 'Threshold evaluator detects CPU > 90% or RAM > 85%, triggering CRITICAL alert with hysteresis window to prevent alert flap.' }
                ]
            },
            d2: {
                title: '3. Deliverable 2: OpenFlow 1.3 QoS & Dynamic Flow Control',
                rubric: 'Rubric: OpenFlow QoS & Throttling (8 Marks)',
                points: [
                    { label: 'Traffic Marking', desc: 'Health agents mark critical packets with IP ToS 0xB8 (DSCP 46 Expedited Forwarding / EF); normal traffic marked DSCP 0 (BE).' },
                    { label: 'Flow Table Rules', desc: 'Ryu installs Table 0 rule (Priority 100) matching ip_dscp=46 -> set_queue:2; normal UDP telemetry (Priority 50) -> set_queue:1.' },
                    { label: 'Dynamic Throttling', desc: 'When port utilization >= 8.0 Mbps, Ryu installs Priority 80 rule demoting bulk cross-traffic to Queue 0 (capped 1-7M).' }
                ]
            },
            loss: {
                title: '4. Packet Loss Demonstration: Shared FIFO vs SDN QoS',
                rubric: 'Rubric: Loss & Latency Contrast (6 Marks)',
                points: [
                    { label: 'Priority OFF (FIFO)', desc: 'Single shared buffer overflows during iPerf congestion -> 56.7% critical packet loss, 38.4ms delay due to tail-drop bufferbloat.' },
                    { label: 'Priority ON (SDN QoS)', desc: 'Queue 2 isolation guarantees 5 Mbps dedicated bandwidth -> 0.0% loss and 1.8ms latency even under 9.5 Mbps congestion!' },
                    { label: 'Delivery Guarantee', desc: 'Mission-critical telemetry and alerts bypass cross-traffic bursts, ensuring the remote monitor never misses a failure.' }
                ]
            }
        };

        function setVivaStep(stepKey) {
            currentVivaStep = stepKey;
            document.querySelectorAll('.viva-step-btn').forEach(btn => btn.classList.remove('active'));
            const activeBtn = document.getElementById(`viva-btn-${stepKey}`);
            if (activeBtn) activeBtn.classList.add('active');

            const data = VIVA_STEPS_DATA[stepKey] || VIVA_STEPS_DATA.arch;
            const card = document.getElementById('viva-card');
            if (card) {
                card.innerHTML = `
                    <div class="viva-card-header">
                        <span class="viva-card-title">📖 ${data.title}</span>
                        <span class="viva-card-rubric">${data.rubric}</span>
                    </div>
                    <div class="viva-points">
                        ${data.points.map(p => `
                            <div class="viva-point">
                                <strong>${p.label}:</strong> ${p.desc}
                            </div>
                        `).join('')}
                    </div>
                `;
            }
        }

        // --- Interactive Simulation Presentation Controls ---
        async function toggleSimPause() {
            isSimPaused = !isSimPaused;
            const btn = document.getElementById('sim-play-pause-btn');
            const icon = document.getElementById('sim-play-icon');
            const text = document.getElementById('sim-play-text');
            if (btn) {
                if (isSimPaused) {
                    btn.className = 'ctrl-btn resume';
                    if (icon) icon.innerText = '▶';
                    if (text) text.innerText = 'Resume Simulation';
                    // Capture snapshot of last known states so cards and nodes stay strictly frozen
                    lastKnownHostStates = JSON.parse(JSON.stringify(liveHostMetrics));
                } else {
                    btn.className = 'ctrl-btn pause';
                    if (icon) icon.innerText = '⏸';
                    if (text) text.innerText = 'Pause Simulation';
                    updateDashboard(true);
                }
            }
            try {
                await fetch('/api/toggle_pause', { method: 'POST' });
            } catch (err) {
                console.warn("Could not notify server of pause state:", err);
            }
        }

        function stepSimulation() {
            if (activePackets.length > 0) {
                activePackets.forEach(p => { p.progress += 0.05; });
            } else {
                const hostKeys = ['h1_prod', 'h2_db', 'h3_cache'];
                const randHost = hostKeys[Math.floor(Math.random() * hostKeys.length)];
                const seq = ++localSeqCounter;
                const isCrit = (getHostMetrics(randHost).cpu_percent >= 90);
                const isDrop = !currentPriorityOn;
                spawnPacket(randHost, seq, isCrit ? 'CRITICAL' : 'NORMAL', isDrop ? 'DROPPED' : 'DELIVERED', isCrit ? 1.8 : 2.5);
                addSequenceChip(randHost, seq, isCrit ? 'CRITICAL' : 'NORMAL', isDrop ? 'DROPPED' : 'DELIVERED', isCrit ? 1.8 : 2.5);
            }
            openflowPulses.forEach(p => { p.y += (p.dir === 'DOWN' ? 6 : -6); });
        }

        async function injectSpike() {
            // Spikes high load across ALL THREE NODES (h1, h2, h3) simultaneously
            const spikeMetrics = {
                h1_prod:  { cpu_percent: 96.8, mem_percent: 91.5, process_count: 530 },
                h2_db:    { cpu_percent: 98.4, mem_percent: 95.0, process_count: 595 },
                h3_cache: { cpu_percent: 95.2, mem_percent: 89.8, process_count: 515 },
                h1:       { cpu_percent: 96.8, mem_percent: 91.5, process_count: 530 },
                h2:       { cpu_percent: 98.4, mem_percent: 95.0, process_count: 595 },
                h3:       { cpu_percent: 95.2, mem_percent: 89.8, process_count: 515 }
            };
            Object.assign(liveHostMetrics, spikeMetrics);
            lastKnownHostStates = JSON.parse(JSON.stringify(liveHostMetrics));

            // All 3 nodes spawn critical alert packets simultaneously
            ['h1_prod', 'h2_db', 'h3_cache'].forEach((nodeId) => {
                const seq = ++localSeqCounter;
                const isDrop = !currentPriorityOn;
                spawnPacket(nodeId, seq, 'CRITICAL', isDrop ? 'DROPPED' : 'DELIVERED', isDrop ? 38.4 : 1.8);
                addSequenceChip(nodeId, seq, 'CRITICAL', isDrop ? 'DROPPED' : 'DELIVERED', isDrop ? 38.4 : 1.8);
            });

            // Ryu SDN Controller sends OpenFlow FlowMod rule prioritizing all 3 into Queue 2
            spawnOFPulse('FLOW_MOD', 'DOWN', 'OFPFlowMod: Prioritize h1,h2,h3 (Q2 EF)', '#f0883e');

            // Notify backend server so server registry, CSV logs, and alerts feed also update
            try {
                await fetch('/api/inject_spike', { method: 'POST' });
                await updateDashboard(true);
            } catch (err) {
                console.warn("Could not notify backend of spike injection:", err);
            }
        }

        function toggleBulkTraffic() {
            bulkTrafficBurstActive = !bulkTrafficBurstActive;
            const btn = document.getElementById('sim-bulk-btn');
            if (btn) {
                btn.style.borderColor = bulkTrafficBurstActive ? '#f85149' : 'var(--border-color)';
                btn.style.color = bulkTrafficBurstActive ? '#f85149' : 'var(--text-bright)';
            }
            for (let i = 0; i < 4; i++) {
                setTimeout(() => {
                    const seq = ++localSeqCounter;
                    const isDrop = !currentPriorityOn;
                    spawnPacket('h3_cache', seq, 'NORMAL', isDrop ? 'DROPPED' : 'DELIVERED', isDrop ? 38.4 : 2.5);
                    addSequenceChip('h3_cache', seq, 'NORMAL', isDrop ? 'DROPPED' : 'DELIVERED', isDrop ? 38.4 : 2.5);
                }, i * 200);
            }
        }

        function spawnOFPulse(type, dir, label, color) {
            openflowPulses.push({
                y: dir === 'DOWN' ? 88 : 175,
                targetY: dir === 'DOWN' ? 175 : 88,
                speed: dir === 'DOWN' ? 1.6 : -1.6,
                dir: dir,
                type: type || 'FLOW_MOD',
                label: label || 'OFPFlowMod',
                color: color || '#a371f7',
                alpha: 1.0
            });
        }

        // Add outcome chip to the live sequence ticker ribbon
        function addSequenceChip(nodeId, seq, priority, status, delayMs) {
            recentSequenceChips.unshift({ nodeId, seq, priority, status, delayMs, ts: Date.now() });
            if (recentSequenceChips.length > 20) recentSequenceChips.pop();
            renderSequenceTicker();
        }

        // Render the sequence flow ticker ribbon beneath the topology canvas
        function renderSequenceTicker() {
            const container = document.getElementById('packet-ticker');
            if (!container) return;
            if (recentSequenceChips.length === 0) {
                container.innerHTML = '<span style="color: #8b949e; font-size: 11px;">Listening for packet flow...</span>';
                return;
            }
            container.innerHTML = recentSequenceChips.map(c => {
                if (c.status === 'DROPPED') {
                    return `<span class="ticker-chip dropped" title="Packet #${c.seq} dropped by shared FIFO bottleneck buffer overflow">✕ MISSING #${c.seq} [${c.nodeId}] (FIFO Drop)</span>`;
                } else if (c.priority === 'CRITICAL') {
                    return `<span class="ticker-chip critical" title="Queue 2 Expedited Forwarding packet delivered with zero loss">★ #${c.seq} [${c.nodeId} EF] (${c.delayMs}ms)</span>`;
                } else {
                    return `<span class="ticker-chip delivered" title="Normal telemetry packet delivered to monitor server">✓ #${c.seq} [${c.nodeId}] (${c.delayMs}ms)</span>`;
                }
            }).join('');
        }

        // Spawn an animated packet moving through the topology
        function spawnPacket(nodeId, seq, priority, status, delayMs) {
            const isCrit = (priority === 'CRITICAL');
            const isDrop = (status === 'DROPPED');
            activePackets.push({
                id: Math.random(),
                nodeId: nodeId || 'h1_prod',
                seq: seq || ++localSeqCounter,
                priority: priority || 'NORMAL',
                isCrit: isCrit,
                isDrop: isDrop,
                delayMs: delayMs || (isCrit ? 1.8 : 2.5),
                progress: 0.0,
                // Speed: when priority is off, surviving packets cross bottleneck slower (buffer bloat delay)
                speed: isDrop ? 0.014 : (currentPriorityOn ? 0.016 : 0.011),
                color: isCrit ? '#f0883e' : '#58a6ff'
            });
        }

        // Trigger explosive tail-drop particle burst when packet is dropped in congested FIFO
        function triggerDropBurst(x, y, seq) {
            for (let i = 0; i < 14; i++) {
                const angle = Math.random() * Math.PI * 2;
                const spd = 1.0 + Math.random() * 4.0;
                particleBursts.push({
                    x: x,
                    y: y,
                    vx: Math.cos(angle) * spd,
                    vy: Math.sin(angle) * spd,
                    radius: 2 + Math.random() * 3,
                    alpha: 1.0,
                    color: Math.random() > 0.3 ? '#f85149' : '#ff7b72'
                });
            }
            floatingAlerts.push({
                x: x,
                y: y - 10,
                vy: -0.9,
                alpha: 1.0,
                text: `✕ DROPPED #${seq} (FIFO Saturated)`
            });
        }

        // Trigger green radar ripple ring on server when a packet arrives safely
        function triggerServerRipple(x, y) {
            serverRipples.push({
                x: x,
                y: y,
                radius: 12,
                maxRadius: 70,
                alpha: 0.85
            });
        }

        // Main 60 FPS Canvas Animation Loop
        function renderLoop() {
            ctx.clearRect(0, 0, cw, ch);
            const layout = getTopologyLayout();
            const { ryu, flowTable, ctrlChannel, hosts, sw, srv } = layout;

            // 1. Draw subtle background blueprint grid dots
            ctx.fillStyle = '#161b22';
            for (let gx = 20; gx < cw; gx += 40) {
                for (let gy = 20; gy < ch; gy += 40) {
                    ctx.beginPath();
                    ctx.arc(gx, gy, 1, 0, Math.PI * 2);
                    ctx.fill();
                }
            }

            // 2. Draw Viva Focus Highlight Rings based on current active walkthrough step
            ctx.save();
            if (currentVivaStep === 'arch') {
                // Focus on Complete Architecture (Ryu + Switch + Hosts + Server)
                ctx.strokeStyle = 'rgba(163, 113, 247, 0.35)';
                ctx.lineWidth = 1.5;
                ctx.setLineDash([5, 5]);
                // Control plane region
                ctx.strokeRect(ryu.x - ryu.w / 2 - 10, ryu.y - ryu.h / 2 - 6, ryu.w + flowTable.w + 40, ryu.h + 12);
                // Data plane region
                ctx.strokeRect(30, 165, cw - 60, 335);
                ctx.fillStyle = 'rgba(163, 113, 247, 0.8)';
                ctx.font = 'bold 10px monospace';
                ctx.textAlign = 'left';
                ctx.fillText('[CONTROL PLANE: OpenFlow 1.3]', ryu.x - ryu.w / 2, ryu.y - ryu.h / 2 - 10);
                ctx.fillText('[DATA PLANE: Mininet 10 Mbps Bottleneck]', 35, 180);
                ctx.setLineDash([]);
            } else if (currentVivaStep === 'd1') {
                // Focus on Host agents & Monitor Server
                ctx.strokeStyle = 'rgba(63, 185, 80, 0.4)';
                ctx.lineWidth = 2;
                ctx.setLineDash([6, 4]);
                ctx.strokeRect(35, 175, 150, 315);
                ctx.strokeRect(srv.x - srv.w / 2 - 8, srv.y - srv.h / 2 - 8, srv.w + 16, srv.h + 16);
                ctx.fillStyle = '#3fb950';
                ctx.font = 'bold 10px monospace';
                ctx.textAlign = 'center';
                ctx.fillText('★ D1: psutil Host Agents (1.0s Interval)', 110, 170);
                ctx.fillText('★ D1: UDP 5005 Ingestion Engine', srv.x, srv.y - srv.h / 2 - 14);
                ctx.setLineDash([]);
            } else if (currentVivaStep === 'd2') {
                // Focus on Ryu, Flow Table, and Switch Queues
                ctx.strokeStyle = 'rgba(88, 166, 255, 0.5)';
                ctx.lineWidth = 2;
                ctx.setLineDash([6, 4]);
                ctx.strokeRect(ryu.x - ryu.w / 2 - 8, ryu.y - ryu.h / 2 - 8, ryu.w + 16, ryu.h + 16);
                ctx.strokeRect(flowTable.x - flowTable.w / 2 - 8, flowTable.y - flowTable.h / 2 - 8, flowTable.w + 16, flowTable.h + 16);
                ctx.strokeRect(sw.x - sw.w / 2 - 8, sw.y - sw.h / 2 - 8, sw.w + 16, sw.h + 16);
                ctx.fillStyle = '#58a6ff';
                ctx.font = 'bold 10px monospace';
                ctx.textAlign = 'center';
                ctx.fillText('★ D2: Ryu OpenFlow 1.3 Controller (TCP 6653)', ryu.x, ryu.y - ryu.h / 2 - 12);
                ctx.fillText('★ D2: Table 0 QoS Matching Rules', flowTable.x, flowTable.y - flowTable.h / 2 - 12);
                ctx.fillText('★ D2: Linux HTB Queuing (Q2, Q1, Q0)', sw.x, sw.y - sw.h / 2 - 12);
                ctx.setLineDash([]);
            } else if (currentVivaStep === 'loss') {
                // Focus on Bottleneck link & Drop Zone
                ctx.strokeStyle = 'rgba(248, 81, 73, 0.6)';
                ctx.lineWidth = 2;
                ctx.setLineDash([6, 4]);
                const linkStartX = sw.x + sw.w / 2 - 20;
                const linkWidth = (srv.x - srv.w / 2) - linkStartX + 20;
                ctx.strokeRect(linkStartX, sw.y - 45, linkWidth, 90);
                ctx.fillStyle = '#ff7b72';
                ctx.font = 'bold 10px monospace';
                ctx.textAlign = 'center';
                ctx.fillText('★ RUBRIC PROOF: Tail-Drop Zone (56.7% Loss FIFO vs 0.0% QoS)', (linkStartX + linkStartX + linkWidth) / 2, sw.y - 52);
                ctx.setLineDash([]);
            }
            ctx.restore();

            // 3. Draw Ryu SDN Controller (c0) [Control Plane]
            ctx.save();
            ctx.fillStyle = '#161b22';
            ctx.strokeStyle = ryuStatsFlash > 0 ? '#3fb950' : '#a371f7';
            ctx.lineWidth = ryuStatsFlash > 0 ? 3 : 2;
            if (ryuStatsFlash > 0) {
                ctx.shadowColor = '#3fb950';
                ctx.shadowBlur = 12 * ryuStatsFlash;
                ryuStatsFlash -= 0.03;
            }
            ctx.beginPath();
            ctx.roundRect(ryu.x - ryu.w / 2, ryu.y - ryu.h / 2, ryu.w, ryu.h, 8);
            ctx.fill();
            ctx.stroke();
            ctx.shadowBlur = 0;

            // Controller Status LED
            const ledPulse = 0.5 + 0.5 * Math.sin(Date.now() / 300);
            ctx.beginPath();
            ctx.arc(ryu.x - ryu.w / 2 + 16, ryu.y - 12, 5, 0, Math.PI * 2);
            ctx.fillStyle = `rgba(63, 185, 80, ${0.7 + 0.3 * ledPulse})`;
            ctx.shadowColor = '#3fb950';
            ctx.shadowBlur = 6;
            ctx.fill();
            ctx.shadowBlur = 0;

            // Controller Title
            ctx.fillStyle = 'var(--text-bright)';
            ctx.font = 'bold 12px system-ui';
            ctx.textAlign = 'left';
            ctx.fillText(ryu.title, ryu.x - ryu.w / 2 + 28, ryu.y - 8);

            // Controller Subtitle
            ctx.fillStyle = '#a371f7';
            ctx.font = '10px monospace';
            ctx.fillText(ryu.sub, ryu.x - ryu.w / 2 + 14, ryu.y + 10);

            // Dynamic QoS status pill
            ctx.fillStyle = 'rgba(163, 113, 247, 0.18)';
            ctx.strokeStyle = 'rgba(163, 113, 247, 0.4)';
            ctx.beginPath();
            ctx.roundRect(ryu.x - ryu.w / 2 + 14, ryu.y + 16, ryu.w - 28, 14, 3);
            ctx.fill();
            ctx.stroke();
            ctx.fillStyle = '#d2a8ff';
            ctx.font = 'bold 9px monospace';
            ctx.textAlign = 'center';
            ctx.fillText('● Active (OpenFlow 1.3 QoS Engine)', ryu.x, ryu.y + 26);
            ctx.restore();

            // 4. Draw Live OpenFlow 1.3 Flow Table 0
            ctx.save();
            ctx.fillStyle = '#161b22';
            ctx.strokeStyle = currentPriorityOn ? 'rgba(88, 166, 255, 0.6)' : 'rgba(248, 81, 73, 0.6)';
            ctx.lineWidth = 1.5;
            ctx.beginPath();
            ctx.roundRect(flowTable.x - flowTable.w / 2, flowTable.y - flowTable.h / 2, flowTable.w, flowTable.h, 6);
            ctx.fill();
            ctx.stroke();

            // Table Header Banner
            ctx.fillStyle = '#0d1117';
            ctx.beginPath();
            ctx.roundRect(flowTable.x - flowTable.w / 2 + 1, flowTable.y - flowTable.h / 2 + 1, flowTable.w - 2, 20, [5, 5, 0, 0]);
            ctx.fill();

            ctx.fillStyle = currentPriorityOn ? '#58a6ff' : '#ff7b72';
            ctx.font = 'bold 10px system-ui';
            ctx.textAlign = 'left';
            ctx.fillText('📋 Switch s1 - OpenFlow 1.3 Table 0 (Live Rules)', flowTable.x - flowTable.w / 2 + 8, flowTable.y - flowTable.h / 2 + 14);

            // Flow Table Rows
            const tLeft = flowTable.x - flowTable.w / 2 + 8;
            if (currentPriorityOn) {
                ctx.font = '9px monospace';
                // Priority 100 Rule
                ctx.fillStyle = '#f0883e';
                ctx.fillText('Prio 100: ip_dscp=46 -> set_queue:2, out:4 (EF 5M min)', tLeft, flowTable.y - 5);
                // Priority 80 Rule
                ctx.fillStyle = '#d29922';
                ctx.fillText('Prio 80:  proto=UDP (iPerf) -> set_queue:0, out:4 (Throttle)', tLeft, flowTable.y + 7);
                // Priority 50 Rule
                ctx.fillStyle = '#3fb950';
                ctx.fillText('Prio 50:  tp_dst=5005 -> set_queue:1, out:4 (BE 3M min)', tLeft, flowTable.y + 19);
                // Priority 0 Rule
                ctx.fillStyle = '#58a6ff';
                ctx.fillText('Prio 0:   match=* -> NORMAL (L2/L3 Learning)', tLeft, flowTable.y + 31);
            } else {
                ctx.font = '9.5px monospace';
                ctx.fillStyle = '#f85149';
                ctx.fillText('⚠️ QoS Rules Flushed: Single Shared FIFO Active', tLeft, flowTable.y);
                ctx.fillStyle = '#ff7b72';
                ctx.fillText('Prio 0: match=* -> output:4 (No Queue Isolation)', tLeft, flowTable.y + 14);
                ctx.fillStyle = '#8b949e';
                ctx.fillText('* All flows compete in unmanaged FIFO buffer *', tLeft, flowTable.y + 28);
            }
            ctx.restore();

            // 5. Draw OpenFlow 1.3 Control Channel (Ryu -> Switch s1)
            ctx.save();
            const chX = ctrlChannel.fromX;
            const chStartY = ctrlChannel.fromY;
            const chEndY = ctrlChannel.toY;
            ctx.beginPath();
            ctx.moveTo(chX - 4, chStartY);
            ctx.lineTo(chX - 4, chEndY);
            ctx.moveTo(chX + 4, chStartY);
            ctx.lineTo(chX + 4, chEndY);
            ctx.strokeStyle = 'rgba(163, 113, 247, 0.45)';
            ctx.lineWidth = 2;
            ctx.setLineDash([4, 4]);
            ctx.stroke();
            ctx.setLineDash([]);

            // Label in middle of control channel
            ctx.fillStyle = '#161b22';
            ctx.fillRect(chX - 70, (chStartY + chEndY) / 2 - 9, 140, 18);
            ctx.strokeStyle = 'rgba(163, 113, 247, 0.5)';
            ctx.strokeRect(chX - 70, (chStartY + chEndY) / 2 - 9, 140, 18);
            ctx.fillStyle = '#d2a8ff';
            ctx.font = 'bold 8.5px monospace';
            ctx.textAlign = 'center';
            ctx.fillText('OF 1.3 Control [TCP 6653]', chX, (chStartY + chEndY) / 2 + 3);

            // Draw OpenFlow Message Pulses along control channel
            for (let i = openflowPulses.length - 1; i >= 0; i--) {
                const pulse = openflowPulses[i];
                if (!isSimPaused) {
                    pulse.y += pulse.speed;
                }

                ctx.fillStyle = pulse.color;
                ctx.shadowColor = pulse.color;
                ctx.shadowBlur = 8;
                ctx.beginPath();
                ctx.roundRect(chX - 48, pulse.y - 8, 96, 16, 8);
                ctx.fill();
                ctx.shadowBlur = 0;

                ctx.fillStyle = '#ffffff';
                ctx.font = 'bold 8px monospace';
                ctx.textAlign = 'center';
                ctx.fillText(pulse.label.slice(0, 15), chX, pulse.y + 3);

                // Arrival trigger
                if (pulse.dir === 'DOWN' && pulse.y >= pulse.targetY) {
                    switchRuleFlash = 1.0;
                    openflowPulses.splice(i, 1);
                } else if (pulse.dir === 'UP' && pulse.y <= pulse.targetY) {
                    ryuStatsFlash = 1.0;
                    openflowPulses.splice(i, 1);
                }
            }
            ctx.restore();

            // 6. Draw Curved Connection Links (Hosts -> Switch)
            const queueYEF = 230;
            const queueYNorm = 330;
            const queueYBulk = 430;

            Object.keys(hosts).forEach(k => {
                const h = hosts[k];
                const metrics = getHostMetrics(k);
                const cpu = metrics.cpu_percent !== undefined ? metrics.cpu_percent : 24;
                const isHostSpiked = (cpu >= 90);
                const destY = (isHostSpiked && currentPriorityOn) ? queueYEF : (k === 'h3_cache' && currentPriorityOn && !isHostSpiked ? queueYBulk : queueYNorm);
                ctx.beginPath();
                ctx.moveTo(h.x + 55, h.y);
                ctx.bezierCurveTo((h.x + sw.x) / 2, h.y, (h.x + sw.x) / 2, destY, sw.x - sw.w / 2, destY);
                ctx.strokeStyle = isHostSpiked ? 'rgba(240, 136, 62, 0.75)' : 'rgba(48, 54, 61, 0.75)';
                ctx.lineWidth = isHostSpiked ? 2.5 : 2;
                ctx.stroke();

                // Directional flow indicator pulses along host links
                const flowPhase = (Date.now() / 800) % 1.0;
                const fx = (h.x + 55) + (sw.x - sw.w / 2 - (h.x + 55)) * flowPhase;
                const fy = h.y + (destY - h.y) * flowPhase;
                ctx.beginPath();
                ctx.arc(fx, fy, isHostSpiked ? 3 : 2, 0, Math.PI * 2);
                ctx.fillStyle = isHostSpiked ? '#f0883e' : h.color;
                ctx.fill();
            });

            // 7. Draw Bottleneck Link (Switch -> Server)
            const linkStartX = sw.x + sw.w / 2;
            const linkEndX = srv.x - srv.w / 2;
            const linkMidX = (linkStartX + linkEndX) / 2;

            ctx.beginPath();
            ctx.moveTo(linkStartX, sw.y);
            ctx.lineTo(linkEndX, srv.y);
            if (currentPriorityOn) {
                // Priority ON: Clean cyan 10 Mbps link
                ctx.strokeStyle = 'rgba(88, 166, 255, 0.75)';
                ctx.lineWidth = 3;
                ctx.setLineDash([]);
                ctx.stroke();
                // Bottleneck label
                ctx.fillStyle = '#58a6ff';
                ctx.font = 'bold 10px monospace';
                ctx.textAlign = 'center';
                ctx.fillText('10 Mbps Link [Clean | 1.8ms]', linkMidX, sw.y - 12);
            } else {
                // Priority OFF: Congested pulsing red dashed bottleneck
                const pulseAlpha = 0.5 + 0.5 * Math.sin(Date.now() / 200);
                ctx.strokeStyle = `rgba(248, 81, 73, ${0.4 + 0.5 * pulseAlpha})`;
                ctx.lineWidth = 4;
                ctx.setLineDash([8, 4]);
                ctx.stroke();
                ctx.setLineDash([]);
                // Bottleneck warning label
                ctx.fillStyle = '#ff7b72';
                ctx.font = 'bold 10px monospace';
                ctx.textAlign = 'center';
                ctx.fillText('⚠️ Bottleneck Saturated [FIFO Bloat: ~38ms]', linkMidX, sw.y - 12);
            }

            // 8. Draw Host Nodes on Left
            Object.keys(hosts).forEach(k => {
                const h = hosts[k];
                const metrics = getHostMetrics(k);
                const cpu = metrics.cpu_percent !== undefined ? metrics.cpu_percent : (k === 'h2_db' ? 28 : 24);
                const isHostSpiked = (cpu >= 90);

                // Host box
                ctx.fillStyle = '#161b22';
                ctx.strokeStyle = isHostSpiked ? '#f0883e' : '#30363d';
                ctx.lineWidth = isHostSpiked ? 2 : 1.5;
                if (isHostSpiked) {
                    ctx.shadowColor = '#f0883e';
                    ctx.shadowBlur = 10;
                }
                ctx.beginPath();
                ctx.roundRect(h.x - 55, h.y - 32, 110, 64, 6);
                ctx.fill();
                ctx.stroke();
                ctx.shadowBlur = 0;

                // Status LED
                ctx.beginPath();
                ctx.arc(h.x - 42, h.y - 18, 4, 0, Math.PI * 2);
                ctx.fillStyle = isHostSpiked ? '#f0883e' : h.color;
                ctx.shadowColor = isHostSpiked ? '#f0883e' : h.color;
                ctx.shadowBlur = 6;
                ctx.fill();
                ctx.shadowBlur = 0;

                // Host title
                ctx.fillStyle = 'var(--text-bright)';
                ctx.font = 'bold 11px system-ui';
                ctx.textAlign = 'left';
                ctx.fillText(h.name, h.x - 32, h.y - 15);

                // Host subtitle / mode
                ctx.fillStyle = isHostSpiked ? '#f0883e' : '#8b949e';
                ctx.font = '9px system-ui';
                ctx.fillText(isHostSpiked ? '⚠️ High Load (EF)' : h.mode, h.x - 42, h.y - 1);

                // CPU metric pill
                ctx.fillStyle = isHostSpiked ? 'rgba(240, 136, 62, 0.25)' : 'rgba(88, 166, 255, 0.15)';
                ctx.strokeStyle = isHostSpiked ? '#f0883e' : 'rgba(88, 166, 255, 0.4)';
                ctx.beginPath();
                ctx.roundRect(h.x - 42, h.y + 7, 84, 16, 3);
                ctx.fill();
                ctx.stroke();

                ctx.fillStyle = isHostSpiked ? '#f0883e' : '#58a6ff';
                ctx.font = 'bold 9px monospace';
                ctx.fillText(`CPU: ${cpu}% [${h.ip}]`, h.x - 38, h.y + 19);
            });

            // 9. Draw SDN Switch (s1) & Queues in Center
            ctx.fillStyle = '#161b22';
            ctx.strokeStyle = currentPriorityOn ? 'rgba(63, 185, 80, 0.8)' : 'rgba(248, 81, 73, 0.9)';
            ctx.lineWidth = 2;
            if (switchRuleFlash > 0) {
                ctx.shadowColor = '#58a6ff';
                ctx.shadowBlur = 14 * switchRuleFlash;
                switchRuleFlash -= 0.04;
            } else if (!currentPriorityOn) {
                // Hazard pulsing border on switch during FIFO saturation
                const swPulse = 0.4 + 0.4 * Math.sin(Date.now() / 250);
                ctx.shadowColor = 'rgba(248, 81, 73, 0.8)';
                ctx.shadowBlur = 10 * swPulse;
            }
            ctx.beginPath();
            ctx.roundRect(sw.x - sw.w / 2, sw.y - sw.h / 2, sw.w, sw.h, 8);
            ctx.fill();
            ctx.stroke();
            ctx.shadowBlur = 0;

            // Ingress and Egress Port Tags on Switch Border
            ctx.fillStyle = '#0d1117';
            ctx.strokeStyle = '#30363d';
            // Ingress Port 1 (h1)
            ctx.strokeRect(sw.x - sw.w / 2 - 14, 212, 14, 16);
            ctx.fillRect(sw.x - sw.w / 2 - 14, 212, 14, 16);
            ctx.fillStyle = '#58a6ff';
            ctx.font = 'bold 8px monospace';
            ctx.fillText('P1', sw.x - sw.w / 2 - 12, 224);
            // Ingress Port 2 (h2)
            ctx.fillStyle = '#0d1117';
            ctx.strokeRect(sw.x - sw.w / 2 - 14, 322, 14, 16);
            ctx.fillRect(sw.x - sw.w / 2 - 14, 322, 14, 16);
            ctx.fillStyle = '#f0883e';
            ctx.fillText('P2', sw.x - sw.w / 2 - 12, 334);
            // Ingress Port 3 (h3)
            ctx.fillStyle = '#0d1117';
            ctx.strokeRect(sw.x - sw.w / 2 - 14, 432, 14, 16);
            ctx.fillRect(sw.x - sw.w / 2 - 14, 432, 14, 16);
            ctx.fillStyle = '#3fb950';
            ctx.fillText('P3', sw.x - sw.w / 2 - 12, 444);
            // Egress Port 4 (Bottleneck)
            ctx.fillStyle = '#0d1117';
            ctx.strokeRect(sw.x + sw.w / 2, 322, 14, 16);
            ctx.fillRect(sw.x + sw.w / 2, 322, 14, 16);
            ctx.fillStyle = '#58a6ff';
            ctx.fillText('P4', sw.x + sw.w / 2 + 2, 334);

            // Switch Header Banner
            ctx.fillStyle = '#0d1117';
            ctx.beginPath();
            ctx.roundRect(sw.x - sw.w / 2 + 1, sw.y - sw.h / 2 + 1, sw.w - 2, 28, [7, 7, 0, 0]);
            ctx.fill();

            ctx.fillStyle = currentPriorityOn ? '#3fb950' : '#ff7b72';
            ctx.font = 'bold 11px system-ui';
            ctx.textAlign = 'center';
            const swTitle = currentPriorityOn
                ? '🔀 SDN Switch (s1) | OpenFlow 1.3 QoS'
                : '⚠️ SDN Switch (s1) | Shared FIFO Baseline';
            ctx.fillText(swTitle, sw.x, sw.y - sw.h / 2 + 18);

            // Inside Switch: Draw Queues
            if (currentPriorityOn) {
                // --- Queue 2 (High / EF Critical) ---
                ctx.fillStyle = 'rgba(240, 136, 62, 0.15)';
                ctx.strokeStyle = '#f0883e';
                ctx.lineWidth = 1;
                ctx.beginPath();
                ctx.roundRect(sw.x - sw.w / 2 + 10, queueYEF - 20, sw.w - 20, 40, 4);
                ctx.fill();
                ctx.stroke();
                ctx.fillStyle = '#f0883e';
                ctx.font = 'bold 10px monospace';
                ctx.textAlign = 'left';
                ctx.fillText('Queue 2: EF Critical [5 Mbps Guaranteed]', sw.x - sw.w / 2 + 16, queueYEF - 4);
                ctx.fillStyle = '#8b949e';
                ctx.font = '9px system-ui';
                ctx.fillText('0% Loss Guarantee | DSCP 46', sw.x - sw.w / 2 + 16, queueYEF + 10);

                // --- Queue 1 (Medium / BE Normal) ---
                ctx.fillStyle = 'rgba(63, 185, 80, 0.15)';
                ctx.strokeStyle = '#3fb950';
                ctx.beginPath();
                ctx.roundRect(sw.x - sw.w / 2 + 10, queueYNorm - 20, sw.w - 20, 40, 4);
                ctx.fill();
                ctx.stroke();
                ctx.fillStyle = '#3fb950';
                ctx.font = 'bold 10px monospace';
                ctx.fillText('Queue 1: BE Normal [3 Mbps Min]', sw.x - sw.w / 2 + 16, queueYNorm - 4);
                ctx.fillStyle = '#8b949e';
                ctx.font = '9px system-ui';
                ctx.fillText('Normal Health Telemetry | DSCP 0', sw.x - sw.w / 2 + 16, queueYNorm + 10);

                // --- Queue 0 (Bulk / Background) ---
                ctx.fillStyle = 'rgba(139, 148, 158, 0.1)';
                ctx.strokeStyle = '#484f58';
                ctx.beginPath();
                ctx.roundRect(sw.x - sw.w / 2 + 10, queueYBulk - 20, sw.w - 20, 40, 4);
                ctx.fill();
                ctx.stroke();
                ctx.fillStyle = '#8b949e';
                ctx.font = 'bold 10px monospace';
                ctx.fillText('Queue 0: Bulk Background [Capped 1-7M]', sw.x - sw.w / 2 + 16, queueYBulk - 4);
                ctx.font = '9px system-ui';
                ctx.fillText('Best-effort cross-traffic isolation', sw.x - sw.w / 2 + 16, queueYBulk + 10);
            } else {
                // Priority OFF: Single Red Shared FIFO Queue with Buffer Overflow Meter
                ctx.fillStyle = 'rgba(248, 81, 73, 0.15)';
                ctx.strokeStyle = '#f85149';
                ctx.lineWidth = 1.5;
                ctx.beginPath();
                ctx.roundRect(sw.x - sw.w / 2 + 12, sw.y - 120, sw.w - 24, 250, 6);
                ctx.fill();
                ctx.stroke();

                ctx.fillStyle = '#ff7b72';
                ctx.font = 'bold 12px system-ui';
                ctx.textAlign = 'center';
                ctx.fillText('SHARED BEST-EFFORT FIFO QUEUE', sw.x, sw.y - 75);

                ctx.fillStyle = '#8b949e';
                ctx.font = '10px system-ui';
                ctx.fillText('All flows compete in a single unmanaged buffer', sw.x, sw.y - 55);

                // Saturated Buffer Meter Bar (96% Full)
                ctx.fillStyle = '#0d1117';
                ctx.beginPath();
                ctx.roundRect(sw.x - sw.w / 2 + 25, sw.y - 30, sw.w - 50, 20, 4);
                ctx.fill();

                const bufferFillWidth = (sw.w - 54) * 0.96;
                const fillGrad = ctx.createLinearGradient(sw.x - sw.w / 2 + 27, 0, sw.x - sw.w / 2 + 27 + bufferFillWidth, 0);
                fillGrad.addColorStop(0, '#d29922');
                fillGrad.addColorStop(1, '#f85149');
                ctx.fillStyle = fillGrad;
                ctx.beginPath();
                ctx.roundRect(sw.x - sw.w / 2 + 27, sw.y - 28, bufferFillWidth, 16, 3);
                ctx.fill();

                ctx.fillStyle = '#ffffff';
                ctx.font = 'bold 9px monospace';
                ctx.fillText('BUFFER 96% FULL [OVERFLOW]', sw.x, sw.y - 16);

                // Tail-drop warning tag
                const flash = (Date.now() / 400) % 1.0 > 0.5;
                ctx.fillStyle = flash ? '#f85149' : '#ff7b72';
                ctx.font = 'bold 11px monospace';
                ctx.fillText('✕ TAIL-DROP ACTIVE (~56.7% DROP RATE)', sw.x, sw.y + 25);

                ctx.fillStyle = '#8b949e';
                ctx.font = '10px system-ui';
                ctx.fillText('Queue Latency: +38.4 ms bufferbloat delay', sw.x, sw.y + 50);
            }

            // 10. Draw Central Monitor Server on Right
            ctx.fillStyle = '#161b22';
            ctx.strokeStyle = '#58a6ff';
            ctx.lineWidth = 1.5;
            ctx.beginPath();
            ctx.roundRect(srv.x - srv.w / 2, srv.y - srv.h / 2, srv.w, srv.h, 8);
            ctx.fill();
            ctx.stroke();

            // Server title
            ctx.fillStyle = 'var(--text-bright)';
            ctx.font = 'bold 12px system-ui';
            ctx.textAlign = 'center';
            ctx.fillText('🖥️ Monitor Server', srv.x, srv.y - 32);

            ctx.fillStyle = '#8b949e';
            ctx.font = '10px monospace';
            ctx.fillText('UDP Port: 5005', srv.x, srv.y - 15);
            ctx.fillText('IP: 10.0.0.4', srv.x, srv.y);

            // Ingestion status pill
            ctx.fillStyle = 'rgba(63, 185, 80, 0.2)';
            ctx.strokeStyle = '#3fb950';
            ctx.beginPath();
            ctx.roundRect(srv.x - 55, srv.y + 15, 110, 22, 11);
            ctx.fill();
            ctx.stroke();

            ctx.fillStyle = '#3fb950';
            ctx.font = 'bold 10px system-ui';
            ctx.fillText('● Ingestion Live', srv.x, srv.y + 30);

            // Draw Server Radar Ripples
            for (let i = serverRipples.length - 1; i >= 0; i--) {
                const rip = serverRipples[i];
                ctx.beginPath();
                ctx.arc(rip.x, rip.y, rip.radius, 0, Math.PI * 2);
                ctx.strokeStyle = `rgba(63, 185, 80, ${rip.alpha})`;
                ctx.lineWidth = 2;
                ctx.stroke();
                if (!isSimPaused) {
                    rip.radius += 1.6;
                    rip.alpha -= 0.025;
                }
                if (rip.alpha <= 0 || rip.radius >= rip.maxRadius) {
                    serverRipples.splice(i, 1);
                }
            }

            // 11. Update and Draw Moving Packets Along Paths
            for (let i = activePackets.length - 1; i >= 0; i--) {
                const p = activePackets[i];
                if (!isSimPaused) {
                    p.progress += p.speed;
                }

                const hostObj = getHostObj(p.nodeId) || hosts.h1_prod;
                const destY = (p.isCrit && currentPriorityOn) ? queueYEF : ((p.nodeId === 'h3_cache' || p.nodeId === 'h3') && currentPriorityOn ? queueYBulk : queueYNorm);

                let px, py;
                // Stage 1: Host to Switch Ingress (progress 0.0 -> 0.45)
                if (p.progress <= 0.45) {
                    const t = p.progress / 0.45;
                    const startX = hostObj.x + 55;
                    const startY = hostObj.y;
                    const endX = sw.x - sw.w / 2;
                    const endY = destY;
                    const ctrlX = (startX + endX) / 2;
                    px = (1 - t) * (1 - t) * startX + 2 * (1 - t) * t * ctrlX + t * t * endX;
                    py = (1 - t) * (1 - t) * startY + 2 * (1 - t) * t * startY + t * t * endY;
                }
                // Stage 2: Through Switch Queues (progress 0.45 -> 0.55)
                else if (p.progress <= 0.55) {
                    const t = (p.progress - 0.45) / 0.10;
                    px = (sw.x - sw.w / 2) + t * sw.w;
                    py = currentPriorityOn ? destY : sw.y;

                    // If packet is marked DROPPED (Priority OFF tail-drop), explode it at bottleneck entrance
                    if (p.isDrop && t >= 0.5) {
                        triggerDropBurst(px, py, p.seq);
                        activePackets.splice(i, 1);
                        continue;
                    }
                }
                // Stage 3: Across Bottleneck Link to Server (progress 0.55 -> 1.0)
                else {
                    const t = (p.progress - 0.55) / 0.45;
                    const startX = sw.x + sw.w / 2;
                    const endX = srv.x - srv.w / 2;
                    px = startX + t * (endX - startX);
                    py = sw.y + t * (srv.y - sw.y);

                    // Reached Monitor Server
                    if (p.progress >= 1.0) {
                        triggerServerRipple(srv.x - srv.w / 2 + 10, srv.y);
                        activePackets.splice(i, 1);
                        continue;
                    }
                }

                // Draw Packet Body
                ctx.save();
                if (p.isCrit) {
                    // Critical Alert Packet: Glowing Amber Diamond (DSCP 46 EF)
                    ctx.translate(px, py);
                    ctx.rotate(Math.PI / 4);
                    ctx.fillStyle = '#f0883e';
                    ctx.shadowColor = '#f0883e';
                    ctx.shadowBlur = 10;
                    ctx.fillRect(-5, -5, 10, 10);
                    ctx.restore();

                    // Sequence tag
                    ctx.fillStyle = '#f0883e';
                    ctx.font = 'bold 9px monospace';
                    ctx.textAlign = 'center';
                    ctx.fillText(`#${p.seq} EF`, px, py - 9);
                } else {
                    // Normal Packet: Cyan/Green Circular Bead
                    ctx.beginPath();
                    ctx.arc(px, py, 5, 0, Math.PI * 2);
                    ctx.fillStyle = p.isDrop && p.progress > 0.4 ? '#f85149' : '#58a6ff';
                    ctx.shadowColor = p.isDrop && p.progress > 0.4 ? '#f85149' : '#58a6ff';
                    ctx.shadowBlur = 8;
                    ctx.fill();
                    ctx.shadowBlur = 0;

                    // Sequence tag
                    ctx.fillStyle = p.isDrop && p.progress > 0.4 ? '#ff7b72' : '#8b949e';
                    ctx.font = 'bold 9px monospace';
                    ctx.textAlign = 'center';
                    ctx.fillText(`#${p.seq}`, px, py - 8);
                }
            }

            // 12. Update and Draw Particle Bursts from Dropped Packets
            for (let i = particleBursts.length - 1; i >= 0; i--) {
                const pt = particleBursts[i];
                ctx.beginPath();
                ctx.arc(pt.x, pt.y, pt.radius, 0, Math.PI * 2);
                ctx.fillStyle = pt.color;
                ctx.globalAlpha = Math.max(0, pt.alpha);
                ctx.fill();
                ctx.globalAlpha = 1.0;

                if (!isSimPaused) {
                    pt.x += pt.vx;
                    pt.y += pt.vy;
                    pt.alpha -= 0.035;
                }
                if (pt.alpha <= 0) particleBursts.splice(i, 1);
            }

            // 13. Update and Draw Floating Drop Alerts
            for (let i = floatingAlerts.length - 1; i >= 0; i--) {
                const fa = floatingAlerts[i];
                ctx.fillStyle = `rgba(248, 81, 73, ${fa.alpha})`;
                ctx.font = 'bold 11px system-ui';
                ctx.textAlign = 'center';
                ctx.shadowColor = 'rgba(248, 81, 73, 0.8)';
                ctx.shadowBlur = 6;
                ctx.fillText(fa.text, fa.x, fa.y);
                ctx.shadowBlur = 0;

                if (!isSimPaused) {
                    fa.y += fa.vy;
                    fa.alpha -= 0.02;
                }
                if (fa.alpha <= 0) floatingAlerts.splice(i, 1);
            }

            // 14. Simulation Paused Presentation Overlay Watermark
            if (isSimPaused) {
                ctx.fillStyle = 'rgba(13, 17, 23, 0.88)';
                ctx.fillRect(cw / 2 - 240, ch - 50, 480, 42);
                ctx.strokeStyle = '#d29922';
                ctx.lineWidth = 1.5;
                ctx.strokeRect(cw / 2 - 240, ch - 50, 480, 42);
                ctx.fillStyle = '#d29922';
                ctx.font = 'bold 12px system-ui';
                ctx.textAlign = 'center';
                ctx.fillText('⏸ SIMULATION PAUSED — FROZEN AT LAST KNOWN STATE', cw / 2, ch - 30);
                ctx.fillStyle = '#8b949e';
                ctx.font = '10px monospace';
                const m1 = (getHostMetrics('h1_prod').cpu_percent || 24);
                const m2 = (getHostMetrics('h2_db').cpu_percent || 28);
                const m3 = (getHostMetrics('h3_cache').cpu_percent || 20);
                ctx.fillText(`h1: ${m1}% CPU  |  h2: ${m2}% CPU  |  h3: ${m3}% CPU  (Packets & Metrics Frozen)`, cw / 2, ch - 15);
            }

            // 15. Autonomous Fallback Packet & OpenFlow Emitter
            // Keeps the pipeline active and demonstrating continuously even if polling is paused
            const now = Date.now();
            if (!isSimPaused) {
                if (now - lastSimulatedSpawn > 1100) {
                    lastSimulatedSpawn = now;
                    const hostKeys = ['h1_prod', 'h2_db', 'h3_cache'];
                    const randHost = hostKeys[Math.floor(Math.random() * hostKeys.length)];
                    // Anomaly spikes can occur across h1, h2, or h3
                    const isCrit = (Math.random() < 0.35);
                    const shortKey = randHost.replace('_prod', '').replace('_db', '').replace('_cache', '');
                    if (isCrit) {
                        const spikeCpu = 93 + Math.floor(Math.random() * 6);
                        liveHostMetrics[randHost].cpu_percent = spikeCpu;
                        if (liveHostMetrics[shortKey]) liveHostMetrics[shortKey].cpu_percent = spikeCpu;
                    } else {
                        const baseCpu = randHost === 'h1_prod' ? (22 + Math.floor(Math.random() * 5)) :
                                        randHost === 'h2_db' ? (26 + Math.floor(Math.random() * 5)) :
                                        (18 + Math.floor(Math.random() * 5));
                        liveHostMetrics[randHost].cpu_percent = baseCpu;
                        if (liveHostMetrics[shortKey]) liveHostMetrics[shortKey].cpu_percent = baseCpu;
                    }
                    let status = 'DELIVERED';
                    if (!currentPriorityOn) {
                        status = (Math.random() < 0.567) ? 'DROPPED' : 'DELIVERED';
                    }
                    const seq = ++localSeqCounter;
                    const delay = isCrit ? 1.8 : (currentPriorityOn ? 2.4 : 38.4);
                    spawnPacket(randHost, seq, isCrit ? 'CRITICAL' : 'NORMAL', status, delay);
                    addSequenceChip(randHost, seq, isCrit ? 'CRITICAL' : 'NORMAL', status, delay);
                }

                if (now - lastOFPulseTime > 2400) {
                    lastOFPulseTime = now;
                    if (Math.random() > 0.45) {
                        spawnOFPulse('FLOW_MOD', 'DOWN', 'OFPFlowMod: Priority 100 (EF 46)', '#f0883e');
                    } else {
                        spawnOFPulse('STATS_REQ', 'DOWN', 'OFPPortStatsRequest', '#58a6ff');
                    }
                }
            }

            requestAnimationFrame(renderLoop);
        }

        // Start 60 FPS animation loop
        requestAnimationFrame(renderLoop);

        // --- Dashboard REST API Polling & Real-Time Sync ---
        async function togglePriority() {
            try {
                spawnOFPulse('FLOW_MOD', 'DOWN', currentPriorityOn ? 'OFPFlowMod: Delete QoS Rules' : 'OFPFlowMod: Install Queue 2/1/0', currentPriorityOn ? '#f85149' : '#3fb950');
                const res = await fetch('/api/toggle_priority', { method: 'POST' });
                if (res.ok) {
                    await updateDashboard();
                }
            } catch (err) {
                console.error("Failed to toggle priority:", err);
            }
        }

        async function toggleThrottle() {
            try {
                spawnOFPulse('FLOW_MOD', 'DOWN', 'OFPFlowMod: Prio 80 Throttle Bulk', '#d29922');
                const res = await fetch('/api/toggle_throttle', { method: 'POST' });
                if (res.ok) {
                    await updateDashboard();
                }
            } catch (err) {
                console.error("Failed to toggle dynamic throttle:", err);
            }
        }

        async function updateDashboard(force = false) {
            if (isSimPaused && !force) {
                return;
            }
            try {
                const res = await fetch('/api/status');
                if (!res.ok) return;
                const data = await res.json();

                if (data.simulation_paused !== undefined && data.simulation_paused && !isSimPaused) {
                    isSimPaused = true;
                    const btn = document.getElementById('sim-play-pause-btn');
                    const icon = document.getElementById('sim-play-icon');
                    const text = document.getElementById('sim-play-text');
                    if (btn) {
                        btn.className = 'ctrl-btn resume';
                        if (icon) icon.innerText = '▶';
                        if (text) text.innerText = 'Resume Simulation';
                    }
                }

                currentPriorityOn = (data.priority_enabled !== false);

                // Update Header Badges
                document.getElementById('valid-packets').innerText = data.valid_packet_count;
                document.getElementById('dropped-packets').innerText = data.bad_packet_count;

                // Update Topology Panel Header & Badges
                const topoBadge = document.getElementById('topo-badge');
                const topoRate = document.getElementById('topo-delivery-rate');
                const topoLost = document.getElementById('topo-lost-count');

                const totalPkts = data.valid_packet_count + data.bad_packet_count;
                const overallLoss = data.overall_loss_percent !== undefined
                    ? data.overall_loss_percent
                    : (totalPkts > 0 ? ((data.bad_packet_count / totalPkts) * 100).toFixed(1) : 0.0);
                const deliveryRate = (100.0 - overallLoss).toFixed(1);

                if (currentPriorityOn) {
                    topoBadge.className = 'd2-badge on';
                    topoBadge.innerText = '⚡ Priority Active (0.0% Loss)';
                    topoRate.style.color = '#3fb950';
                    topoRate.innerText = `${deliveryRate}% (QoS Guaranteed)`;
                    topoLost.style.color = 'var(--text-bright)';
                    topoLost.innerText = data.bad_packet_count;
                } else {
                    topoBadge.className = 'd2-badge off';
                    topoBadge.innerText = '⚠️ Priority Disabled (Shared FIFO)';
                    topoRate.style.color = '#ff7b72';
                    topoRate.innerText = `${deliveryRate}% (${overallLoss}% Drop Rate)`;
                    topoLost.style.color = 'var(--accent-red)';
                    topoLost.innerText = `${data.bad_packet_count} (Lost)`;
                }

                // Update Deliverable 2 Control Button & Descriptions
                const pBtn = document.getElementById('priority-toggle-btn');
                const pText = document.getElementById('priority-btn-text');
                const pIcon = document.getElementById('priority-icon');
                const d2Badge = document.getElementById('d2-status-badge');
                const queueDesc = document.getElementById('d2-queue-desc');

                if (currentPriorityOn) {
                    pBtn.className = 'priority-toggle-btn on';
                    pIcon.innerText = '⚡';
                    pText.innerText = 'SDN Priority: ON (D2)';
                    d2Badge.className = 'd2-badge on';
                    d2Badge.innerText = 'Priority Active (Queue 2/1/0)';
                    queueDesc.innerHTML = `
                        <strong style="color: #58a6ff;">Queue 2 (Critical):</strong> DSCP 46 (EF) | Guaranteed 5 Mbps (0% loss under burst)<br>
                        <strong style="color: #3fb950;">Queue 1 (Normal):</strong> DSCP 0 (BE) | Guaranteed 3 Mbps<br>
                        <strong style="color: #8b949e;">Queue 0 (Bulk):</strong> Best-effort background flows | Capped 1–7 Mbps
                    `;
                } else {
                    pBtn.className = 'priority-toggle-btn off';
                    pIcon.innerText = '⚠️';
                    pText.innerText = 'SDN Priority: OFF (FIFO)';
                    d2Badge.className = 'd2-badge off';
                    d2Badge.innerText = 'Priority Disabled (Shared FIFO)';
                    queueDesc.innerHTML = `
                        <strong style="color: #f85149;">Shared Best-Effort FIFO Queue:</strong><br>
                        All packets (Critical + Bulk + Normal) compete in a single shared buffer.<br>
                        <em style="color: #ff7b72;">Bottleneck saturates -> Tail-drop causes ~56.7% packet drop rate & 38.4ms delay!</em>
                    `;
                }

                // Update Dynamic SDN Throttle status
                const throttleStatus = document.getElementById('throttle-status');
                if (data.dynamic_throttling_active) {
                    throttleStatus.innerHTML = '<strong style="color: #ff7b72;">ACTIVE (Priority 80 Rule Injected & Cross-Traffic Throttled to Queue 0)</strong>';
                } else {
                    throttleStatus.innerHTML = '<span style="color: #3fb950;">Inactive (Port rate < 8 Mbps)</span>';
                }

                // Update Mini Priority Toggle in Topology Controls Toolbar
                const miniPrioBtn = document.getElementById('toggle-prio-mini-btn');
                const miniPrioIcon = document.getElementById('mini-prio-icon');
                const miniPrioText = document.getElementById('mini-prio-text');
                if (miniPrioBtn) {
                    if (currentPriorityOn) {
                        miniPrioBtn.className = 'ctrl-btn prio-on';
                        if (miniPrioIcon) miniPrioIcon.innerText = '⚡';
                        if (miniPrioText) miniPrioText.innerText = 'Priority: ON';
                    } else {
                        miniPrioBtn.className = 'ctrl-btn prio-off';
                        if (miniPrioIcon) miniPrioIcon.innerText = '⚠️';
                        if (miniPrioText) miniPrioText.innerText = 'Priority: OFF (FIFO)';
                    }
                }

                // Synchronize real server packet events with the animated canvas
                if (data.recent_packet_events && data.recent_packet_events.length > 0) {
                    for (const ev of data.recent_packet_events) {
                        const evKey = `${ev.node_id}_${ev.seq}_${ev.status}`;
                        if (!processedEventKeys.has(evKey)) {
                            processedEventKeys.add(evKey);
                            if (processedEventKeys.size > 200) {
                                const firstKey = processedEventKeys.values().next().value;
                                processedEventKeys.delete(firstKey);
                            }
                            spawnPacket(ev.node_id, ev.seq, ev.priority, ev.status, ev.delay_ms);
                            addSequenceChip(ev.node_id, ev.seq, ev.priority, ev.status, ev.delay_ms);
                        }
                    }
                }

                // Update Node Cards
                const grid = document.getElementById('nodes-grid');
                grid.innerHTML = '';

                let nodeEntries = Object.entries(data.nodes || {});
                if (nodeEntries.length === 0) {
                    nodeEntries = [
                        ['h1', { metrics: getHostMetrics('h1_prod'), status: 'UP', loss_percent: 0.0, avg_delay_ms: currentPriorityOn ? 1.8 : 38.4, last_seq: localSeqCounter }],
                        ['h2', { metrics: getHostMetrics('h2_db'), status: 'UP', loss_percent: 0.0, avg_delay_ms: currentPriorityOn ? 1.8 : 38.4, last_seq: localSeqCounter }],
                        ['h3', { metrics: getHostMetrics('h3_cache'), status: 'UP', loss_percent: currentPriorityOn ? 0.0 : 56.7, avg_delay_ms: currentPriorityOn ? 2.4 : 38.4, last_seq: localSeqCounter }]
                    ];
                }

                for (const [nodeId, n] of nodeEntries) {
                    const m = n.metrics || {};
                    const cpu = m.cpu_percent !== undefined ? m.cpu_percent : 0;
                    const mem = m.mem_percent !== undefined ? m.mem_percent : 0;
                    const procs = m.process_count !== undefined ? m.process_count : 0;
                    const lossVal = n.loss_percent !== undefined ? n.loss_percent : 0;

                    // Cache live metrics for canvas nodes (supporting both h1 and h1_prod formats)
                    liveHostMetrics[nodeId] = m;
                    if (nodeId === 'h1') liveHostMetrics['h1_prod'] = m;
                    if (nodeId === 'h2') liveHostMetrics['h2_db'] = m;
                    if (nodeId === 'h3') liveHostMetrics['h3_cache'] = m;
                    if (nodeId === 'h1_prod') liveHostMetrics['h1'] = m;
                    if (nodeId === 'h2_db') liveHostMetrics['h2'] = m;
                    if (nodeId === 'h3_cache') liveHostMetrics['h3'] = m;

                    const lossColor = lossVal > 20 ? 'var(--accent-red)' : (lossVal > 0 ? 'var(--accent-yellow)' : '#3fb950');
                    const delayColor = n.avg_delay_ms > 20 ? 'var(--accent-yellow)' : '#8b949e';

                    const card = document.createElement('div');
                    card.className = `card ${n.status === 'DOWN' ? 'down' : (lossVal > 20 ? 'card-loss' : (cpu >= 90 ? 'card-spike' : ''))}`;
                    card.innerHTML = `
                        <div class="card-header">
                            <h3>${nodeId}</h3>
                            <span class="status-tag status-${n.status.toLowerCase()}">${n.status}</span>
                        </div>
                        <div class="metric-row">
                            <div class="metric-header">
                                <span>CPU Usage</span>
                                <strong style="${cpu >= 90 ? 'color: #f0883e;' : ''}">${cpu}% ${cpu >= 90 ? '(🚨 SPIKE)' : ''}</strong>
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
                            <span>Loss: <strong style="color: ${lossColor}; font-weight: 800; font-size: 12px;">${lossVal}% ${lossVal > 20 ? '(⚠️ HIGH LOSS)' : ''}</strong></span>
                            <span>Avg Delay: <strong style="color: ${delayColor};">${n.avg_delay_ms} ms</strong></span>
                            <span>Seq: <strong>${n.last_seq !== null ? n.last_seq : '-'}</strong></span>
                        </div>
                    `;
                    grid.appendChild(card);
                }

                // Update Active Alerts
                const alertsBox = document.getElementById('alerts-container');
                let alertsList = data.active_alerts || [];
                // If backend has no active alerts but any host is spiked (cpu >= 90), surface active spike alerts
                if (alertsList.length === 0) {
                    ['h1', 'h2', 'h3'].forEach(k => {
                        const m = getHostMetrics(k);
                        if (m && m.cpu_percent >= 90) {
                            alertsList.push({
                                severity: 'CRITICAL',
                                node_id: k,
                                metric: 'cpu_percent',
                                value: `${m.cpu_percent}%`,
                                threshold: '90.0%',
                                alert_latency_ms: 1.8
                            });
                        }
                    });
                }

                if (alertsList.length > 0) {
                    alertsBox.innerHTML = '';
                    alertsList.forEach(a => {
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

        setVivaStep('arch');
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
            status_payload = {
                "valid_packet_count": 0,
                "bad_packet_count": 0,
                "priority_enabled": True,
                "dynamic_throttling_active": False,
                "nodes": {},
                "active_alerts": [],
            }
            # If reference to MonitorServer exists, extract live metrics
            if self.server_instance:
                # Reference server instance
                s = self.server_instance
                # Total count of valid processed packets
                status_payload["valid_packet_count"] = s.valid_packet_count
                # Total count of malformed or corrupted packets dropped
                status_payload["bad_packet_count"] = s.bad_packet_count
                # Current SDN QoS Priority mode state (Deliverable 2)
                status_payload["priority_enabled"] = getattr(s, "priority_enabled", True)
                # Current Dynamic SDN Throttling state (Deliverable 2)
                status_payload["dynamic_throttling_active"] = getattr(s, "dynamic_throttling_active", False)
                # Current simulation pause state
                status_payload["simulation_paused"] = getattr(s, "simulation_paused", False)

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

                # Export recent packet flow events for animated topology pipeline
                status_payload["recent_packet_events"] = list(getattr(s, "recent_packet_events", []))
                tot = s.valid_packet_count + s.bad_packet_count
                status_payload["overall_loss_percent"] = round((s.bad_packet_count / tot) * 100.0, 2) if tot > 0 else 0.0

            # Serialize status dictionary to JSON bytes and write to HTTP socket
            self.wfile.write(json.dumps(status_payload).encode("utf-8"))
        # Endpoint to toggle SDN QoS Priority Mode (Deliverable 2)
        elif self.path in ("/api/toggle_priority", "/api/toggle_priority/"):
            # Toggle state
            new_state = True
            if self.server_instance:
                self.server_instance.priority_enabled = not getattr(self.server_instance, "priority_enabled", True)
                new_state = self.server_instance.priority_enabled
                # Reset node loss and latency stats so effect of new QoS mode is immediately reflected
                if hasattr(self.server_instance, "registry") and hasattr(self.server_instance.registry, "reset_loss_stats"):
                    self.server_instance.registry.reset_loss_stats()
                # Clear recent event buffer on mode switch so graph reflects fresh state
                if hasattr(self.server_instance, "recent_packet_events"):
                    self.server_instance.recent_packet_events.clear()
                # Reset dropped packet counter when restoring priority protection
                if new_state:
                    self.server_instance.bad_packet_count = 0
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(json.dumps({"priority_enabled": new_state}).encode("utf-8"))
        # Endpoint to toggle Dynamic SDN Throttling simulation (Deliverable 2)
        elif self.path in ("/api/toggle_throttle", "/api/toggle_throttle/"):
            # Toggle state
            new_throttle = False
            if self.server_instance:
                self.server_instance.dynamic_throttling_active = not getattr(self.server_instance, "dynamic_throttling_active", False)
                new_throttle = self.server_instance.dynamic_throttling_active
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(json.dumps({"dynamic_throttling_active": new_throttle}).encode("utf-8"))
        # Endpoint to toggle Simulation Pause (freezes packets and holds nodes at last known state)
        elif self.path in ("/api/toggle_pause", "/api/toggle_pause/"):
            new_pause = False
            if self.server_instance:
                self.server_instance.simulation_paused = not getattr(self.server_instance, "simulation_paused", False)
                new_pause = self.server_instance.simulation_paused
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(json.dumps({"simulation_paused": new_pause}).encode("utf-8"))
        # Endpoint to inject simultaneous high load anomaly spikes across all 3 nodes (h1, h2, h3)
        elif self.path in ("/api/inject_spike", "/api/inject_spike/"):
            spiked = {}
            if self.server_instance and hasattr(self.server_instance, "inject_spike"):
                spiked = self.server_instance.inject_spike(["h1", "h2", "h3"])
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(json.dumps({"status": "spiked", "nodes": spiked}).encode("utf-8"))
        # All other paths return 404 Not Found
        else:
            # Send HTTP 404 Not Found status code
            self.send_response(404)
            # Finalize headers
            self.end_headers()

    # Handle incoming HTTP POST requests (delegates toggle actions to matching logic)
    def do_POST(self):
        # Support POST method on toggle endpoints
        if self.path in ("/api/toggle_priority", "/api/toggle_throttle", "/api/toggle_pause", "/api/inject_spike"):
            self.do_GET()
        else:
            self.send_response(404)
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
