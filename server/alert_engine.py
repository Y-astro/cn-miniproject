"""Alert engine evaluating thresholds, hysteresis, cooldowns, and alert latency."""

import time
import uuid
from typing import Any, Dict, List, Optional, Tuple
from common.config_loader import validate_config, ConfigError


class AlertRecord:
    """Represents a generated alert with latency measurement."""

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
        self.alert_id = alert_id
        self.node_id = node_id
        self.metric = metric
        self.value = value
        self.threshold = threshold
        self.severity = severity  # "WARNING" or "CRITICAL"
        self.trigger_ts = trigger_ts
        self.detect_ts = detect_ts

    @property
    def alert_latency_ms(self) -> float:
        """End-to-end alert latency in milliseconds."""
        return max(0.0, (self.detect_ts - self.trigger_ts) * 1000.0)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "alert_id": self.alert_id,
            "node_id": self.node_id,
            "metric": self.metric,
            "value": self.value,
            "threshold": self.threshold,
            "severity": self.severity,
            "trigger_ts": self.trigger_ts,
            "detect_ts": self.detect_ts,
            "alert_latency_ms": round(self.alert_latency_ms, 2),
        }


class AlertEngine:
    """Evaluates metrics against warning and critical thresholds with cooldown and hysteresis."""

    def __init__(self, config: Dict[str, Any]):
        validate_config(config)
        self.config = config
        self.thresholds = config.get("thresholds", {})
        alert_cfg = config.get("alerts", {})
        self.cooldown_seconds = float(alert_cfg.get("cooldown_seconds", 5.0))
        self.hysteresis_percent = float(alert_cfg.get("hysteresis_percent", 2.0))

        # Track active alert state per (node_id, metric) -> current severity ("WARNING", "CRITICAL")
        self._active_states: Dict[Tuple[str, str], str] = {}
        # Track last alert firing timestamp per (node_id, metric, severity) -> timestamp
        self._last_alert_ts: Dict[Tuple[str, str, str], float] = {}
        # History of generated alerts
        self.alert_history: List[AlertRecord] = []

    def evaluate_metric(
        self,
        node_id: str,
        metric: str,
        value: float,
        trigger_ts: float,
        now: Optional[float] = None,
    ) -> Optional[AlertRecord]:
        """Evaluates a single metric value against thresholds with hysteresis and cooldown."""
        current_time = now if now is not None else time.time()
        m_cfg = self.thresholds.get(metric)
        if not m_cfg:
            return None

        warn_th = float(m_cfg["warning"])
        crit_th = float(m_cfg["critical"])

        state_key = (node_id, metric)
        current_state = self._active_states.get(state_key)

        # Determine target severity
        target_severity = None
        threshold_hit = 0.0

        if value >= crit_th:
            target_severity = "CRITICAL"
            threshold_hit = crit_th
        elif value >= warn_th:
            target_severity = "WARNING"
            threshold_hit = warn_th
        else:
            # Check hysteresis for clearing
            if current_state == "CRITICAL":
                clear_crit = crit_th - self.hysteresis_percent
                if value < clear_crit:
                    if value >= warn_th:
                        target_severity = "WARNING"
                        threshold_hit = warn_th
                    else:
                        clear_warn = warn_th - self.hysteresis_percent
                        if value < clear_warn:
                            self._active_states.pop(state_key, None)
                            return None
                        else:
                            # Remain in warning
                            target_severity = "WARNING"
                            threshold_hit = warn_th
                else:
                    target_severity = "CRITICAL"
                    threshold_hit = crit_th
            elif current_state == "WARNING":
                clear_warn = warn_th - self.hysteresis_percent
                if value < clear_warn:
                    self._active_states.pop(state_key, None)
                    return None
                else:
                    # In hysteresis deadband, keep current state
                    target_severity = "WARNING"
                    threshold_hit = warn_th
            else:
                return None

        if target_severity is None:
            return None

        # Check state transition or cooldown expiration
        fire_alert = False
        cooldown_key = (node_id, metric, target_severity)
        last_fired = self._last_alert_ts.get(cooldown_key, 0.0)

        if current_state != target_severity:
            # State changed (e.g. None -> WARNING, WARNING -> CRITICAL)
            fire_alert = True
        elif (current_time - last_fired) >= self.cooldown_seconds:
            # Cooldown elapsed for active severity
            fire_alert = True

        if fire_alert:
            self._active_states[state_key] = target_severity
            self._last_alert_ts[cooldown_key] = current_time

            record = AlertRecord(
                alert_id=str(uuid.uuid4())[:8],
                node_id=node_id,
                metric=metric,
                value=float(value),
                threshold=threshold_hit,
                severity=target_severity,
                trigger_ts=trigger_ts,
                detect_ts=current_time,
            )
            self.alert_history.append(record)
            return record

        return None

    def evaluate_report(
        self,
        node_id: str,
        metrics: Dict[str, Any],
        trigger_ts: float,
        packet_loss_percent: float = 0.0,
        now: Optional[float] = None,
    ) -> List[AlertRecord]:
        """Evaluates all metrics in a report and returns any triggered alerts."""
        alerts: List[AlertRecord] = []
        current_time = now if now is not None else time.time()

        # Check CPU
        if "cpu_percent" in metrics:
            a = self.evaluate_metric(node_id, "cpu_percent", metrics["cpu_percent"], trigger_ts, current_time)
            if a:
                alerts.append(a)

        # Check Memory
        if "mem_percent" in metrics:
            a = self.evaluate_metric(node_id, "mem_percent", metrics["mem_percent"], trigger_ts, current_time)
            if a:
                alerts.append(a)

        # Check Process Count
        if "process_count" in metrics:
            a = self.evaluate_metric(node_id, "process_count", metrics["process_count"], trigger_ts, current_time)
            if a:
                alerts.append(a)

        # Check Packet Loss %
        if packet_loss_percent > 0:
            a = self.evaluate_metric(node_id, "packet_loss_percent", packet_loss_percent, trigger_ts, current_time)
            if a:
                alerts.append(a)

        return alerts
