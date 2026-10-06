"""Configuration loader with schema and threshold validation."""

import os
from pathlib import Path
from typing import Any, Dict
import yaml


class ConfigError(ValueError):
    """Raised when configuration file is missing, malformed, or invalid."""
    pass


def load_config(config_path: str = "config.yaml") -> Dict[str, Any]:
    """Loads and validates a YAML configuration file.

    Args:
        config_path: Path to the YAML configuration file.

    Returns:
        Dict[str, Any]: Validated configuration dictionary.

    Raises:
        ConfigError: If file is not found, unparseable, or contains invalid values.
    """
    path = Path(config_path)
    if not path.is_file():
        raise ConfigError(f"Configuration file not found: {config_path}")

    try:
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except yaml.YAMLError as exc:
        raise ConfigError(f"Failed to parse YAML configuration: {exc}") from exc
    except Exception as exc:
        raise ConfigError(f"Error reading configuration file: {exc}") from exc

    if not isinstance(data, dict):
        raise ConfigError(f"Configuration root must be a mapping/dict, got {type(data).__name__}")

    validate_config(data)
    return data


def validate_config(cfg: Dict[str, Any]) -> None:
    """Validates configuration parameters and threshold invariants."""
    # Validate server section
    server = cfg.get("server")
    if not isinstance(server, dict):
        raise ConfigError("Missing or invalid 'server' configuration section")

    port = server.get("port")
    if not isinstance(port, int) or not (1 <= port <= 65535):
        raise ConfigError(f"Invalid server port: {port}")

    timeout_mult = server.get("failure_timeout_multiplier", 3.0)
    if not isinstance(timeout_mult, (int, float)) or timeout_mult <= 0:
        raise ConfigError(f"Invalid failure_timeout_multiplier: {timeout_mult}")

    # Validate agent section
    agent = cfg.get("agent", {})
    if not isinstance(agent, dict):
        raise ConfigError("Invalid 'agent' configuration section")

    interval = agent.get("default_interval", 1.0)
    if not isinstance(interval, (int, float)) or interval <= 0:
        raise ConfigError(f"Invalid agent default_interval: {interval}")

    # Validate thresholds
    thresholds = cfg.get("thresholds")
    if not isinstance(thresholds, dict):
        raise ConfigError("Missing or invalid 'thresholds' configuration section")

    for metric in ["cpu_percent", "mem_percent", "process_count", "packet_loss_percent"]:
        if metric not in thresholds or not isinstance(thresholds[metric], dict):
            raise ConfigError(f"Missing threshold definition for metric '{metric}'")
        m_cfg = thresholds[metric]
        warn = m_cfg.get("warning")
        crit = m_cfg.get("critical")

        if not isinstance(warn, (int, float)) or not isinstance(crit, (int, float)):
            raise ConfigError(f"Thresholds for '{metric}' must be numeric (warn={warn}, crit={crit})")

        if warn < 0 or crit < 0:
            raise ConfigError(f"Thresholds for '{metric}' cannot be negative (warn={warn}, crit={crit})")

        if warn >= crit:
            raise ConfigError(
                f"Warning threshold must be strictly less than critical for '{metric}' "
                f"(warn={warn} >= crit={crit})"
            )

    # Validate silence multiplier
    silence = thresholds.get("silence_multiplier", 3.0)
    if not isinstance(silence, (int, float)) or silence <= 0:
        raise ConfigError(f"Invalid silence_multiplier: {silence}")
