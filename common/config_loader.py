"""Configuration loader and validator for YAML configuration files."""

# Import os for operating system path manipulations and environment variable access
import os
# Import sys to inspect and update the Python module search path (sys.path)
import sys
# Import Path class from pathlib for clean, cross-platform filesystem operations
from pathlib import Path
# Import typing helpers for static type safety and documentation
from typing import Any, Dict

# Attempt to import PyYAML library to read YAML files
try:
    # Standard PyYAML module import
    import yaml
# If PyYAML is installed inside the virtualenv and not global environment, catch ImportError
except ImportError:
    # Import glob to locate Python site-packages dynamically within the project directory
    import glob
    # Locate all virtualenv site-packages paths inside .venv
    _v_paths = glob.glob(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".venv", "lib", "python*", "site-packages")))
    # Iterate through discovered virtual environment directory paths
    for _p in _v_paths:
        # Check if the virtualenv path is already present in sys.path
        if _p not in sys.path:
            # Prepend virtual environment site-packages to sys.path so modules can be resolved
            sys.path.insert(0, _p)
    # Retry importing yaml now that sys.path includes the local virtual environment
    import yaml


# Custom exception class indicating invalid or missing configuration parameters
class ConfigError(ValueError):
    """Raised when configuration file is missing, malformed, or invalid."""
    # Pass through standard ValueError behavior
    pass


# Function to load and validate a YAML configuration file from disk
def load_config(config_path: str = "config.yaml") -> Dict[str, Any]:
    """Loads and validates a YAML configuration file.

    Args:
        config_path: Path to the YAML configuration file.

    Returns:
        Dict[str, Any]: Validated configuration dictionary.

    Raises:
        ConfigError: If file is not found, unparseable, or contains invalid values.
    """
    # Convert string file path into a pathlib Path object
    path = Path(config_path)
    # Check if the file actually exists on the filesystem and is a regular file
    if not path.is_file():
        # Raise error if configuration file is not found
        raise ConfigError(f"Configuration file not found: {config_path}")

    # Safely open and parse the configuration file
    try:
        # Open the file with UTF-8 encoding
        with open(path, "r", encoding="utf-8") as f:
            # Safely parse YAML without allowing arbitrary code execution (safe_load)
            data = yaml.safe_load(f)
    # Catch any syntax errors within the YAML document
    except yaml.YAMLError as exc:
        # Raise ConfigError with parsing details
        raise ConfigError(f"Failed to parse YAML configuration: {exc}") from exc
    # Catch OS, I/O, or permission errors
    except Exception as exc:
        # Raise ConfigError on generic read failure
        raise ConfigError(f"Error reading configuration file: {exc}") from exc

    # Ensure the top-level YAML data structure is a dictionary/mapping
    if not isinstance(data, dict):
        # Raise error if root is a list, scalar, or null
        raise ConfigError(f"Configuration root must be a mapping/dict, got {type(data).__name__}")

    # Validate all mandatory configuration sections and parameters
    validate_config(data)
    # Return the validated configuration dictionary
    return data


# Function to validate configuration schema, types, and mathematical invariants
def validate_config(cfg: Dict[str, Any]) -> None:
    """Validates configuration parameters and threshold invariants."""
    # Extract the 'server' configuration section
    server = cfg.get("server")
    # Verify the server section exists and is a dictionary
    if not isinstance(server, dict):
        # Raise error if server section is missing
        raise ConfigError("Missing or invalid 'server' configuration section")

    # Extract the listening port number
    port = server.get("port")
    # Port must be an integer between 1 and 65535 (standard TCP/UDP port range)
    if not isinstance(port, int) or not (1 <= port <= 65535):
        # Raise error if port is out of range or not an integer
        raise ConfigError(f"Invalid server port: {port}")

    # Extract failure timeout multiplier (default: 3.0 times report interval)
    timeout_mult = server.get("failure_timeout_multiplier", 3.0)
    # Ensure multiplier is a positive number
    if not isinstance(timeout_mult, (int, float)) or timeout_mult <= 0:
        # Raise error if multiplier is non-positive or invalid type
        raise ConfigError(f"Invalid failure_timeout_multiplier: {timeout_mult}")

    # Extract the 'agent' configuration section (defaults to empty dict if omitted)
    agent = cfg.get("agent", {})
    # Verify agent section is a dictionary
    if not isinstance(agent, dict):
        # Raise error if agent section is not a dictionary
        raise ConfigError("Invalid 'agent' configuration section")

    # Extract the default report interval in seconds
    interval = agent.get("default_interval", 1.0)
    # Verify interval is a positive number
    if not isinstance(interval, (int, float)) or interval <= 0:
        # Raise error if interval is <= 0 or not a number
        raise ConfigError(f"Invalid agent default_interval: {interval}")

    # Extract the 'thresholds' configuration section
    thresholds = cfg.get("thresholds")
    # Verify thresholds section exists and is a dictionary
    if not isinstance(thresholds, dict):
        # Raise error if thresholds section is missing
        raise ConfigError("Missing or invalid 'thresholds' configuration section")

    # Iterate through all required system metrics to ensure alert rules are defined
    for metric in ["cpu_percent", "mem_percent", "process_count", "packet_loss_percent"]:
        # Verify each metric has an explicit dictionary configuration
        if metric not in thresholds or not isinstance(thresholds[metric], dict):
            # Raise error if metric threshold configuration is absent
            raise ConfigError(f"Missing threshold definition for metric '{metric}'")
        # Get threshold configuration dictionary for this specific metric
        m_cfg = thresholds[metric]
        # Retrieve warning threshold value
        warn = m_cfg.get("warning")
        # Retrieve critical threshold value
        crit = m_cfg.get("critical")

        # Both warning and critical thresholds must be numeric
        if not isinstance(warn, (int, float)) or not isinstance(crit, (int, float)):
            # Raise error if either threshold is missing or non-numeric
            raise ConfigError(f"Thresholds for '{metric}' must be numeric (warn={warn}, crit={crit})")

        # Thresholds cannot be negative
        if warn < 0 or crit < 0:
            # Raise error if negative values were supplied
            raise ConfigError(f"Thresholds for '{metric}' cannot be negative (warn={warn}, crit={crit})")

        # Invariant: Warning threshold must be strictly lower than Critical threshold
        if warn >= crit:
            # Raise error if warning threshold is equal to or greater than critical threshold
            raise ConfigError(
                f"Warning threshold must be strictly less than critical for '{metric}' "
                f"(warn={warn} >= crit={crit})"
            )

    # Extract silence multiplier for missing heartbeat detection
    silence = thresholds.get("silence_multiplier", 3.0)
    # Ensure silence multiplier is a positive number
    if not isinstance(silence, (int, float)) or silence <= 0:
        # Raise error if silence multiplier is non-positive
        raise ConfigError(f"Invalid silence_multiplier: {silence}")
