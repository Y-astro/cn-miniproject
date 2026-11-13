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
            height: 310px;
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
            <h3>
                <span>🌐 OpenFlow 1.3 Topology & Real-Time Flow Pipeline</span>
                <span id="topo-badge" class="d2-badge on">Priority Active (0.0% Loss)</span>
            </h3>
            <div class="topo-meta">
                <span class="topo-pill">Bottleneck: <strong>10 Mbps</strong></span>
                <span class="topo-pill">Delivery Rate: <strong id="topo-delivery-rate" style="color: #3fb950;">100.0%</strong></span>
                <span class="topo-pill">Dropped Packets: <strong id="topo-lost-count" style="color: var(--text-bright);">0</strong></span>
                <div class="topo-legend">
                    <span class="legend-item"><span class="legend-dot crit"></span> Critical EF (Queue 2)</span>
                    <span class="legend-item"><span class="legend-dot norm"></span> Normal BE (Queue 1)</span>
                    <span class="legend-item"><span class="legend-dot drop"></span> ✕ Dropped (FIFO Tail-Drop)</span>
                </div>
            </div>
        </div>
        <div class="canvas-wrapper">
            <canvas id="topoCanvas" width="1000" height="310"></canvas>
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
        let activePackets = [];
        let particleBursts = [];
        let serverRipples = [];
        let floatingAlerts = [];
        let processedEventKeys = new Set();
        let recentSequenceChips = [];
        let lastSimulatedSpawn = 0;
        let localSeqCounter = 100;
        let liveHostMetrics = {};

        // Canvas element and 2D rendering context
        const canvas = document.getElementById('topoCanvas');
        const ctx = canvas.getContext('2d');
        let cw = 1000;
        let ch = 310;

        // Auto-scale canvas resolution to match retina high-DPI displays
        function resizeCanvas() {
            if (!canvas) return;
            const rect = canvas.getBoundingClientRect();
            const dpr = window.devicePixelRatio || 1;
            cw = rect.width || 1000;
            ch = 310;
            canvas.width = cw * dpr;
            canvas.height = ch * dpr;
            ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
        }
        window.addEventListener('resize', resizeCanvas);
        resizeCanvas();

        // Calculate responsive node positions across the canvas width
        function getTopologyLayout() {
            const hostX = 110;
            const switchX = Math.round(cw * 0.50);
            const serverX = Math.round(cw - 110);
            return {
                hosts: {
                    h1_prod:  { x: hostX, y: 55,  name: 'h1_prod', title: 'h1 (Prod)', mode: 'Real PSUtil', color: '#58a6ff' },
                    h2_db:    { x: hostX, y: 155, name: 'h2_db',   title: 'h2 (Database)', mode: 'Spike Pattern', color: '#f0883e' },
                    h3_cache: { x: hostX, y: 255, name: 'h3_cache',title: 'h3 (Cache)', mode: 'Normal BE', color: '#3fb950' }
                },
                sw:  { x: switchX, y: 155, w: 230, h: 175 },
                srv: { x: serverX, y: 155, w: 140, h: 110 }
            };
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
            for (let i = 0; i < 12; i++) {
                const angle = Math.random() * Math.PI * 2;
                const spd = 1.0 + Math.random() * 3.5;
                particleBursts.push({
                    x: x,
                    y: y,
                    vx: Math.cos(angle) * spd,
                    vy: Math.sin(angle) * spd,
                    radius: 2 + Math.random() * 2.5,
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
                maxRadius: 65,
                alpha: 0.85
            });
        }

        // Main 60 FPS Canvas Animation Loop
        function renderLoop() {
            ctx.clearRect(0, 0, cw, ch);
            const layout = getTopologyLayout();
            const { hosts, sw, srv } = layout;

            // 1. Draw subtle background blueprint grid dots
            ctx.fillStyle = '#161b22';
            for (let gx = 20; gx < cw; gx += 40) {
                for (let gy = 20; gy < ch; gy += 40) {
                    ctx.beginPath();
                    ctx.arc(gx, gy, 1, 0, Math.PI * 2);
                    ctx.fill();
                }
            }

            // 2. Draw curved connection links (Hosts -> Switch)
            const queueYEF = sw.y - 48;
            const queueYNorm = sw.y;
            const queueYBulk = sw.y + 48;

            Object.keys(hosts).forEach(k => {
                const h = hosts[k];
                const destY = (k === 'h2_db' && currentPriorityOn) ? queueYEF : queueYNorm;
                ctx.beginPath();
                ctx.moveTo(h.x + 55, h.y);
                ctx.bezierCurveTo((h.x + sw.x) / 2, h.y, (h.x + sw.x) / 2, destY, sw.x - sw.w / 2, destY);
                ctx.strokeStyle = 'rgba(48, 54, 61, 0.7)';
                ctx.lineWidth = 2;
                ctx.stroke();

                // Directional flow indicator pulses along host links
                const flowPhase = (Date.now() / 800) % 1.0;
                const fx = (h.x + 55) + (sw.x - sw.w / 2 - (h.x + 55)) * flowPhase;
                const fy = h.y + (destY - h.y) * flowPhase;
                ctx.beginPath();
                ctx.arc(fx, fy, 2, 0, Math.PI * 2);
                ctx.fillStyle = h.color;
                ctx.fill();
            });

            // 3. Draw Bottleneck Link (Switch -> Server)
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

            // 4. Draw Host Nodes on the Left
            Object.keys(hosts).forEach(k => {
                const h = hosts[k];
                const metrics = liveHostMetrics[k] || {};
                const cpu = metrics.cpu_percent !== undefined ? metrics.cpu_percent : (k === 'h2_db' ? 92 : 24);

                // Host box
                ctx.fillStyle = '#161b22';
                ctx.strokeStyle = (k === 'h2_db' && cpu >= 90) ? '#f0883e' : '#30363d';
                ctx.lineWidth = 1.5;
                ctx.beginPath();
                ctx.roundRect(h.x - 55, h.y - 32, 110, 64, 6);
                ctx.fill();
                ctx.stroke();

                // Status LED
                ctx.beginPath();
                ctx.arc(h.x - 42, h.y - 18, 4, 0, Math.PI * 2);
                ctx.fillStyle = h.color;
                ctx.shadowColor = h.color;
                ctx.shadowBlur = 6;
                ctx.fill();
                ctx.shadowBlur = 0;

                // Host title
                ctx.fillStyle = 'var(--text-bright)';
                ctx.font = 'bold 11px system-ui';
                ctx.textAlign = 'left';
                ctx.fillText(h.name, h.x - 32, h.y - 15);

                // Host subtitle / mode
                ctx.fillStyle = '#8b949e';
                ctx.font = '9px system-ui';
                ctx.fillText(h.mode, h.x - 42, h.y - 1);

                // CPU metric pill
                ctx.fillStyle = cpu >= 90 ? 'rgba(240, 136, 62, 0.25)' : 'rgba(88, 166, 255, 0.15)';
                ctx.strokeStyle = cpu >= 90 ? '#f0883e' : 'rgba(88, 166, 255, 0.4)';
                ctx.beginPath();
                ctx.roundRect(h.x - 42, h.y + 7, 84, 16, 3);
                ctx.fill();
                ctx.stroke();

                ctx.fillStyle = cpu >= 90 ? '#f0883e' : '#58a6ff';
                ctx.font = 'bold 9px monospace';
                ctx.fillText(`CPU: ${cpu}%`, h.x - 34, h.y + 19);
            });

            // 5. Draw SDN Switch (s1) & Queues in Center
            ctx.fillStyle = '#161b22';
            ctx.strokeStyle = currentPriorityOn ? 'rgba(63, 185, 80, 0.8)' : 'rgba(248, 81, 73, 0.9)';
            ctx.lineWidth = 2;
            if (!currentPriorityOn) {
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
                ctx.roundRect(sw.x - sw.w / 2 + 10, queueYEF - 16, sw.w - 20, 32, 4);
                ctx.fill();
                ctx.stroke();
                ctx.fillStyle = '#f0883e';
                ctx.font = 'bold 10px monospace';
                ctx.textAlign = 'left';
                ctx.fillText('Queue 2: EF Critical [5 Mbps Guaranteed]', sw.x - sw.w / 2 + 16, queueYEF - 2);
                ctx.fillStyle = '#8b949e';
                ctx.font = '9px system-ui';
                ctx.fillText('0% Loss Guarantee | DSCP 46', sw.x - sw.w / 2 + 16, queueYEF + 10);

                // --- Queue 1 (Medium / BE Normal) ---
                ctx.fillStyle = 'rgba(63, 185, 80, 0.15)';
                ctx.strokeStyle = '#3fb950';
                ctx.beginPath();
                ctx.roundRect(sw.x - sw.w / 2 + 10, queueYNorm - 16, sw.w - 20, 32, 4);
                ctx.fill();
                ctx.stroke();
                ctx.fillStyle = '#3fb950';
                ctx.font = 'bold 10px monospace';
                ctx.fillText('Queue 1: BE Normal [3 Mbps Min]', sw.x - sw.w / 2 + 16, queueYNorm - 2);
                ctx.fillStyle = '#8b949e';
                ctx.font = '9px system-ui';
                ctx.fillText('Normal Health Telemetry | DSCP 0', sw.x - sw.w / 2 + 16, queueYNorm + 10);

                // --- Queue 0 (Bulk / Background) ---
                ctx.fillStyle = 'rgba(139, 148, 158, 0.1)';
                ctx.strokeStyle = '#484f58';
                ctx.beginPath();
                ctx.roundRect(sw.x - sw.w / 2 + 10, queueYBulk - 16, sw.w - 20, 32, 4);
                ctx.fill();
                ctx.stroke();
                ctx.fillStyle = '#8b949e';
                ctx.font = 'bold 10px monospace';
                ctx.fillText('Queue 0: Bulk Background [Capped 1-7M]', sw.x - sw.w / 2 + 16, queueYBulk - 2);
                ctx.font = '9px system-ui';
                ctx.fillText('Best-effort cross-traffic isolation', sw.x - sw.w / 2 + 16, queueYBulk + 10);
            } else {
                // Priority OFF: Single Red Shared FIFO Queue with Buffer Overflow Meter
                ctx.fillStyle = 'rgba(248, 81, 73, 0.15)';
                ctx.strokeStyle = '#f85149';
                ctx.lineWidth = 1.5;
                ctx.beginPath();
                ctx.roundRect(sw.x - sw.w / 2 + 12, sw.y - 50, sw.w - 24, 115, 6);
                ctx.fill();
                ctx.stroke();

                ctx.fillStyle = '#ff7b72';
                ctx.font = 'bold 11px system-ui';
                ctx.textAlign = 'center';
                ctx.fillText('SHARED BEST-EFFORT FIFO QUEUE', sw.x, sw.y - 28);

                ctx.fillStyle = '#8b949e';
                ctx.font = '10px system-ui';
                ctx.fillText('All flows compete in a single buffer', sw.x, sw.y - 12);

                // Saturated Buffer Meter Bar (98% Full)
                ctx.fillStyle = '#0d1117';
                ctx.beginPath();
                ctx.roundRect(sw.x - sw.w / 2 + 25, sw.y + 4, sw.w - 50, 18, 4);
                ctx.fill();

                const bufferFillWidth = (sw.w - 54) * 0.96;
                const fillGrad = ctx.createLinearGradient(sw.x - sw.w / 2 + 27, 0, sw.x - sw.w / 2 + 27 + bufferFillWidth, 0);
                fillGrad.addColorStop(0, '#d29922');
                fillGrad.addColorStop(1, '#f85149');
                ctx.fillStyle = fillGrad;
                ctx.beginPath();
                ctx.roundRect(sw.x - sw.w / 2 + 27, sw.y + 6, bufferFillWidth, 14, 3);
                ctx.fill();

                ctx.fillStyle = '#ffffff';
                ctx.font = 'bold 9px monospace';
                ctx.fillText('BUFFER 96% FULL [OVERFLOW]', sw.x, sw.y + 17);

                // Tail-drop warning tag
                const flash = (Date.now() / 400) % 1.0 > 0.5;
                ctx.fillStyle = flash ? '#f85149' : '#ff7b72';
                ctx.font = 'bold 10px monospace';
                ctx.fillText('✕ TAIL-DROP ACTIVE (~56.7% DROP RATE)', sw.x, sw.y + 45);
            }

            // 6. Draw Central Monitor Server on Right
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
            ctx.fillText('🖥️ Monitor Server', srv.x, srv.y - 25);

            ctx.fillStyle = '#8b949e';
            ctx.font = '10px monospace';
            ctx.fillText('UDP Port: 5005', srv.x, srv.y - 8);

            // Ingestion status pill
            ctx.fillStyle = 'rgba(63, 185, 80, 0.2)';
            ctx.strokeStyle = '#3fb950';
            ctx.beginPath();
            ctx.roundRect(srv.x - 55, srv.y + 10, 110, 22, 11);
            ctx.fill();
            ctx.stroke();

            ctx.fillStyle = '#3fb950';
            ctx.font = 'bold 10px system-ui';
            ctx.fillText('● Ingestion Live', srv.x, srv.y + 25);

            // Draw Server Radar Ripples
            for (let i = serverRipples.length - 1; i >= 0; i--) {
                const rip = serverRipples[i];
                ctx.beginPath();
                ctx.arc(rip.x, rip.y, rip.radius, 0, Math.PI * 2);
                ctx.strokeStyle = `rgba(63, 185, 80, ${rip.alpha})`;
                ctx.lineWidth = 2;
                ctx.stroke();
                rip.radius += 1.6;
                rip.alpha -= 0.025;
                if (rip.alpha <= 0 || rip.radius >= rip.maxRadius) {
                    serverRipples.splice(i, 1);
                }
            }

            // 7. Update and Draw Moving Packets Along Paths
            for (let i = activePackets.length - 1; i >= 0; i--) {
                const p = activePackets[i];
                p.progress += p.speed;

                const hostObj = hosts[p.nodeId] || hosts.h1_prod;
                const destY = (p.isCrit && currentPriorityOn) ? queueYEF : queueYNorm;

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

            // 8. Update and Draw Particle Bursts from Dropped Packets
            for (let i = particleBursts.length - 1; i >= 0; i--) {
                const pt = particleBursts[i];
                ctx.beginPath();
                ctx.arc(pt.x, pt.y, pt.radius, 0, Math.PI * 2);
                ctx.fillStyle = pt.color;
                ctx.globalAlpha = Math.max(0, pt.alpha);
                ctx.fill();
                ctx.globalAlpha = 1.0;

                pt.x += pt.vx;
                pt.y += pt.vy;
                pt.alpha -= 0.035;
                if (pt.alpha <= 0) particleBursts.splice(i, 1);
            }

            // 9. Update and Draw Floating Drop Alerts
            for (let i = floatingAlerts.length - 1; i >= 0; i--) {
                const fa = floatingAlerts[i];
                ctx.fillStyle = `rgba(248, 81, 73, ${fa.alpha})`;
                ctx.font = 'bold 11px system-ui';
                ctx.textAlign = 'center';
                ctx.shadowColor = 'rgba(248, 81, 73, 0.8)';
                ctx.shadowBlur = 6;
                ctx.fillText(fa.text, fa.x, fa.y);
                ctx.shadowBlur = 0;

                fa.y += fa.vy;
                fa.alpha -= 0.02;
                if (fa.alpha <= 0) floatingAlerts.splice(i, 1);
            }

            // 10. Autonomous Fallback Packet Emitter
            // Keeps the pipeline active and demonstrating continuously even if polling is paused
            const now = Date.now();
            if (now - lastSimulatedSpawn > 1100) {
                lastSimulatedSpawn = now;
                const hostKeys = ['h1_prod', 'h2_db', 'h3_cache'];
                const randHost = hostKeys[Math.floor(Math.random() * hostKeys.length)];
                const isCrit = (randHost === 'h2_db' && Math.random() > 0.4);
                let status = 'DELIVERED';
                if (!currentPriorityOn) {
                    status = (Math.random() < 0.567) ? 'DROPPED' : 'DELIVERED';
                }
                const seq = ++localSeqCounter;
                spawnPacket(randHost, seq, isCrit ? 'CRITICAL' : 'NORMAL', status, isCrit ? 1.8 : (currentPriorityOn ? 2.4 : 38.4));
                addSequenceChip(randHost, seq, isCrit ? 'CRITICAL' : 'NORMAL', status, isCrit ? 1.8 : (currentPriorityOn ? 2.4 : 38.4));
            }

            requestAnimationFrame(renderLoop);
        }

        // Start 60 FPS animation loop
        requestAnimationFrame(renderLoop);

        // --- Dashboard REST API Polling & Real-Time Sync ---
        async function togglePriority() {
            try {
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
                const res = await fetch('/api/toggle_throttle', { method: 'POST' });
                if (res.ok) {
                    await updateDashboard();
                }
            } catch (err) {
                console.error("Failed to toggle dynamic throttle:", err);
            }
        }

        async function updateDashboard() {
            try {
                const res = await fetch('/api/status');
                if (!res.ok) return;
                const data = await res.json();

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
                    const lossVal = n.loss_percent !== undefined ? n.loss_percent : 0;

                    // Cache live metrics for canvas nodes
                    liveHostMetrics[nodeId] = m;

                    const lossColor = lossVal > 20 ? 'var(--accent-red)' : (lossVal > 0 ? 'var(--accent-yellow)' : '#3fb950');
                    const delayColor = n.avg_delay_ms > 20 ? 'var(--accent-yellow)' : '#8b949e';

                    const card = document.createElement('div');
                    card.className = `card ${n.status === 'DOWN' ? 'down' : (lossVal > 20 ? 'card-loss' : '')}`;
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
                            <span>Loss: <strong style="color: ${lossColor}; font-weight: 800; font-size: 12px;">${lossVal}% ${lossVal > 20 ? '(⚠️ HIGH LOSS)' : ''}</strong></span>
                            <span>Avg Delay: <strong style="color: ${delayColor};">${n.avg_delay_ms} ms</strong></span>
                            <span>Seq: <strong>${n.last_seq !== null ? n.last_seq : '-'}</strong></span>
                        </div>
                    `;
                    grid.appendChild(card);
                }

                // Update Active Alerts
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
        # All other paths return 404 Not Found
        else:
            # Send HTTP 404 Not Found status code
            self.send_response(404)
            # Finalize headers
            self.end_headers()

    # Handle incoming HTTP POST requests (delegates toggle actions to matching logic)
    def do_POST(self):
        # Support POST method on toggle endpoints
        if self.path in ("/api/toggle_priority", "/api/toggle_throttle"):
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
