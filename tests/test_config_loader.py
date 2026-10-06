"""Unit tests for config loader and validation."""

import pytest
import yaml
from common.config_loader import load_config, validate_config, ConfigError


def test_load_valid_config(tmp_path):
    cfg_file = tmp_path / "valid_config.yaml"
    cfg_data = {
        "server": {"port": 5005, "failure_timeout_multiplier": 3.0},
        "agent": {"default_interval": 1.0},
        "thresholds": {
            "cpu_percent": {"warning": 70.0, "critical": 90.0},
            "mem_percent": {"warning": 75.0, "critical": 90.0},
            "process_count": {"warning": 300, "critical": 500},
            "packet_loss_percent": {"warning": 5.0, "critical": 20.0},
            "silence_multiplier": 3.0,
        },
    }
    cfg_file.write_text(yaml.dump(cfg_data))
    loaded = load_config(str(cfg_file))
    assert loaded["server"]["port"] == 5005


def test_missing_config_file():
    with pytest.raises(ConfigError, match="Configuration file not found"):
        load_config("non_existent_file.yaml")


def test_invalid_yaml(tmp_path):
    bad_yaml = tmp_path / "bad.yaml"
    bad_yaml.write_text("server: [invalid yaml {")
    with pytest.raises(ConfigError, match="Failed to parse YAML"):
        load_config(str(bad_yaml))


def test_warning_greater_or_equal_critical():
    bad_cfg = {
        "server": {"port": 5005},
        "agent": {"default_interval": 1.0},
        "thresholds": {
            "cpu_percent": {"warning": 90.0, "critical": 70.0},  # Warning > Critical
            "mem_percent": {"warning": 75.0, "critical": 90.0},
            "process_count": {"warning": 300, "critical": 500},
            "packet_loss_percent": {"warning": 5.0, "critical": 20.0},
        },
    }
    with pytest.raises(ConfigError, match="strictly less than critical"):
        validate_config(bad_cfg)


def test_negative_threshold():
    bad_cfg = {
        "server": {"port": 5005},
        "agent": {"default_interval": 1.0},
        "thresholds": {
            "cpu_percent": {"warning": -10.0, "critical": 90.0},
            "mem_percent": {"warning": 75.0, "critical": 90.0},
            "process_count": {"warning": 300, "critical": 500},
            "packet_loss_percent": {"warning": 5.0, "critical": 20.0},
        },
    }
    with pytest.raises(ConfigError, match="cannot be negative"):
        validate_config(bad_cfg)


def test_invalid_interval():
    bad_cfg = {
        "server": {"port": 5005},
        "agent": {"default_interval": -1.0},
        "thresholds": {
            "cpu_percent": {"warning": 70.0, "critical": 90.0},
            "mem_percent": {"warning": 75.0, "critical": 90.0},
            "process_count": {"warning": 300, "critical": 500},
            "packet_loss_percent": {"warning": 5.0, "critical": 20.0},
        },
    }
    with pytest.raises(ConfigError, match="Invalid agent default_interval"):
        validate_config(bad_cfg)
