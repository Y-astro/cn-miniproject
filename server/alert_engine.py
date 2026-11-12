"""Alert engine evaluating thresholds, hysteresis, cooldowns, and alert latency."""

# Import time module for timestamp tracking and latency calculations
import time
# Import uuid module for generating unique 8-character hexadecimal alert identifiers
import uuid
# Import typing annotations for static type verification and clean method signatures
from typing import Any, Dict, List, Optional, Tuple
# Import configuration validation routine and custom exception class
from common.config_loader import validate_config, ConfigError


# Class representing an individual threshold breach alert record
class AlertRecord:
    """Represents a generated alert with latency measurement."""

    # Constructor initializing alert metadata, metric values, and timestamps
    def __init__(
        self,
        alert_id: str,
        node_id: str,
        metric: str,
        value: float,
        threshold: float,
        severity: str,
        trigger_ts: float,
        detect_ts: float,
    ):
        # Unique identifier string for this alert incident
        self.alert_id = alert_id
        # Identifier of the node that generated the breaching metric
        self.node_id = node_id
        # Name of the offending metric (e.g., 'cpu_percent', 'mem_percent')
        self.metric = metric
        # Actual numerical value sampled on the reporting agent
        self.value = value
        # Configured threshold boundary that was breached
        self.threshold = threshold
        # Severity rating: "WARNING" or "CRITICAL"
        self.severity = severity
        # Wall-clock timestamp recorded on the agent when metric was sampled
        self.trigger_ts = trigger_ts
        # Wall-clock timestamp recorded on the server when alert was evaluated
        self.detect_ts = detect_ts

    # Computed property calculating end-to-end alert detection latency in milliseconds
    @property
    def alert_latency_ms(self) -> float:
        """End-to-end alert latency in milliseconds."""
        # Calculate time difference between agent trigger and server detection
        return max(0.0, (self.detect_ts - self.trigger_ts) * 1000.0)

    # Method to export alert record as a JSON/CSV serializable dictionary
    def to_dict(self) -> Dict[str, Any]:
        # Return standardized dictionary representation of the alert
        return {
            # Alert UUID
            "alert_id": self.alert_id,
            # Node ID
            "node_id": self.node_id,
            # Metric name
            "metric": self.metric,
            # Observed value
            "value": self.value,
            # Breached threshold
            "threshold": self.threshold,
            # Severity classification
            "severity": self.severity,
            # Metric trigger timestamp
            "trigger_ts": self.trigger_ts,
            # Server detection timestamp
            "detect_ts": self.detect_ts,
            # Alert latency in milliseconds rounded to 2 decimal places
            "alert_latency_ms": round(self.alert_latency_ms, 2),
        }


# Class responsible for evaluating incoming metrics against defined operational thresholds
class AlertEngine:
    """Evaluates metrics against warning and critical thresholds with cooldown and hysteresis."""

    # Constructor validating configuration and initializing hysteresis tracking state
    def __init__(self, config: Dict[str, Any]):
        # Validate configuration dictionary schema and threshold invariants
        validate_config(config)
        # Store configuration dictionary
        self.config = config
        # Cache threshold rules dictionary: {metric: {warning: float, critical: float}}
        self.thresholds = config.get("thresholds", {})
        # Extract alert behavior settings section
        alert_cfg = config.get("alerts", {})
        # Minimum cooldown duration in seconds before re-firing the same alert severity
        self.cooldown_seconds = float(alert_cfg.get("cooldown_seconds", 5.0))
        # Hysteresis band percentage to prevent rapid flapping around threshold boundaries
        self.hysteresis_percent = float(alert_cfg.get("hysteresis_percent", 2.0))

        # Dictionary tracking current active severity per (node_id, metric): {(node_id, metric): severity}
        self._active_states: Dict[Tuple[str, str], str] = {}
        # Dictionary tracking last alert fire timestamp per (node_id, metric, severity)
        self._last_alert_ts: Dict[Tuple[str, str, str], float] = {}
        # Chronological in-memory log of all generated AlertRecord instances
        self.alert_history: List[AlertRecord] = []

    # Method evaluating an individual metric value against warning and critical thresholds
    def evaluate_metric(
        self,
        node_id: str,
        metric: str,
        value: float,
        trigger_ts: float,
        now: Optional[float] = None,
    ) -> Optional[AlertRecord]:
        """Evaluates a single metric value against thresholds with hysteresis and cooldown."""
        # Use provided evaluation timestamp or sample current system clock
        current_time = now if now is not None else time.time()
        # Retrieve threshold configuration for this metric
        m_cfg = self.thresholds.get(metric)
        # If no thresholds are configured for this metric, do not alert
        if not m_cfg:
            # Return None
            return None

        # Extract warning threshold value as a float
        warn_th = float(m_cfg["warning"])
        # Extract critical threshold value as a float
        crit_th = float(m_cfg["critical"])

        # Construct composite lookup key for current node and metric
        state_key = (node_id, metric)
        # Look up any existing active alert state for this metric
        current_state = self._active_states.get(state_key)

        # Initialize target severity variable to None
        target_severity = None
        # Initialize threshold boundary value that was breached
        threshold_hit = 0.0

        # Check if metric breaches the critical threshold
        if value >= crit_th:
            # Set target severity to CRITICAL
            target_severity = "CRITICAL"
            # Record critical threshold value
            threshold_hit = crit_th
        # Check if metric breaches the warning threshold
        elif value >= warn_th:
            # Set target severity to WARNING
            target_severity = "WARNING"
            # Record warning threshold value
            threshold_hit = warn_th
        # Metric is below standard thresholds: apply hysteresis deadband logic
        else:
            # Handle recovery from active CRITICAL state
            if current_state == "CRITICAL":
                # Metric must drop below (critical - hysteresis) to exit CRITICAL state
                clear_crit = crit_th - self.hysteresis_percent
                # Check if metric has dropped below critical clearing boundary
                if value < clear_crit:
                    # Check if value is still high enough to warrant WARNING severity
                    if value >= warn_th:
                        # Downgrade severity to WARNING
                        target_severity = "WARNING"
                        # Record warning threshold
                        threshold_hit = warn_th
                    # Otherwise check if it clears warning state as well
                    else:
                        # Metric must drop below (warning - hysteresis) to completely clear
                        clear_warn = warn_th - self.hysteresis_percent
                        # If value has dropped below clear_warn boundary, clear alert completely
                        if value < clear_warn:
                            # Remove active state entry from tracking dictionary
                            self._active_states.pop(state_key, None)
                            # Return None (alert resolved)
                            return None
                        # Otherwise value is trapped in warning deadband: remain in WARNING
                        else:
                            # Maintain WARNING state
                            target_severity = "WARNING"
                            # Record warning threshold
                            threshold_hit = warn_th
                # Value has not dropped below clear_crit: maintain CRITICAL state
                else:
                    # Maintain CRITICAL state
                    target_severity = "CRITICAL"
                    # Record critical threshold
                    threshold_hit = crit_th
            # Handle recovery from active WARNING state
            elif current_state == "WARNING":
                # Compute warning clearance boundary
                clear_warn = warn_th - self.hysteresis_percent
                # Check if value has dropped below warning clearing boundary
                if value < clear_warn:
                    # Completely clear active warning state
                    self._active_states.pop(state_key, None)
                    # Return None (alert resolved)
                    return None
                # Value is in warning hysteresis deadband: maintain WARNING state
                else:
                    # Maintain WARNING state
                    target_severity = "WARNING"
                    # Record warning threshold
                    threshold_hit = warn_th
            # Metric is normal and was not previously in alert state
            else:
                # Return None (no alert needed)
                return None

        # If no target severity was determined, exit
        if target_severity is None:
            # Return None
            return None

        # Flag determining whether an alert record should be created and emitted
        fire_alert = False
        # Key for checking rate-limiting cooldown: (node_id, metric, severity)
        cooldown_key = (node_id, metric, target_severity)
        # Retrieve the timestamp when this alert severity was last fired
        last_fired = self._last_alert_ts.get(cooldown_key, 0.0)

        # Immediate escalation/transition: state changed (e.g. None -> WARNING, WARNING -> CRITICAL)
        if current_state != target_severity:
            # Fire alert immediately without waiting for cooldown
            fire_alert = True
        # If state remains the same, only re-fire if cooldown period has elapsed
        elif (current_time - last_fired) >= self.cooldown_seconds:
            # Fire repeat alert
            fire_alert = True

        # Process alert emission if triggered
        if fire_alert:
            # Update tracked active state for this node and metric
            self._active_states[state_key] = target_severity
            # Update last firing timestamp for cooldown tracking
            self._last_alert_ts[cooldown_key] = current_time

            # Instantiate new AlertRecord object with unique ID and latency measurement
            record = AlertRecord(
                # Generate compact 8-character unique hexadecimal ID
                alert_id=str(uuid.uuid4())[:8],
                # Node identifier
                node_id=node_id,
                # Metric name
                metric=metric,
                # Observed metric value
                value=float(value),
                # Breached threshold boundary
                threshold=threshold_hit,
                # Severity classification
                severity=target_severity,
                # Telemetry trigger timestamp
                trigger_ts=trigger_ts,
                # Alert detection timestamp
                detect_ts=current_time,
            )
            # Append new alert record to in-memory history log
            self.alert_history.append(record)
            # Return newly generated alert record
            return record

        # Return None if alert was suppressed by cooldown
        return None

    # Method to evaluate all metrics contained within a complete health report
    def evaluate_report(
        self,
        node_id: str,
        metrics: Dict[str, Any],
        trigger_ts: float,
        packet_loss_percent: float = 0.0,
        now: Optional[float] = None,
    ) -> List[AlertRecord]:
        """Evaluates all metrics in a report and returns any triggered alerts."""
        # Initialize list to hold any triggered alerts
        alerts: List[AlertRecord] = []
        # Sample or use provided evaluation timestamp
        current_time = now if now is not None else time.time()

        # Check CPU utilization metric if present in report
        if "cpu_percent" in metrics:
            # Evaluate CPU percentage against CPU thresholds
            a = self.evaluate_metric(node_id, "cpu_percent", metrics["cpu_percent"], trigger_ts, current_time)
            # If an alert was generated, add it to the list
            if a:
                # Append alert
                alerts.append(a)

        # Check memory utilization metric if present in report
        if "mem_percent" in metrics:
            # Evaluate memory percentage against RAM thresholds
            a = self.evaluate_metric(node_id, "mem_percent", metrics["mem_percent"], trigger_ts, current_time)
            # If an alert was generated, add it to the list
            if a:
                # Append alert
                alerts.append(a)

        # Check active process count metric if present in report
        if "process_count" in metrics:
            # Evaluate process count against process thresholds
            a = self.evaluate_metric(node_id, "process_count", metrics["process_count"], trigger_ts, current_time)
            # If an alert was generated, add it to the list
            if a:
                # Append alert
                alerts.append(a)

        # Check packet loss percentage if loss has been observed
        if packet_loss_percent > 0:
            # Evaluate packet loss against packet loss thresholds
            a = self.evaluate_metric(node_id, "packet_loss_percent", packet_loss_percent, trigger_ts, current_time)
            # If an alert was generated, add it to the list
            if a:
                # Append alert
                alerts.append(a)

        # Return list of all triggered alert records
        return alerts
