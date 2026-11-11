"""Unit tests for OpenFlow 1.3 Ryu SDN Controller and Dynamic QoS/Mitigation features."""

import os
import sys
import time
from unittest.mock import MagicMock, patch
import pytest

from ryu.ofproto import ofproto_v1_3, ofproto_v1_3_parser
from sdn.ryu_controller import HealthMonitorSDNController


@pytest.fixture
def mock_controller():
    """Initializes HealthMonitorSDNController with background thread mocked."""
    with patch("ryu.lib.hub.spawn"):
        controller = HealthMonitorSDNController()
        return controller


@pytest.fixture
def mock_datapath():
    """Builds a mock OpenFlow 1.3 datapath."""
    dp = MagicMock()
    dp.id = 1
    dp.ofproto = ofproto_v1_3
    dp.ofproto_parser = ofproto_v1_3_parser
    dp.send_msg = MagicMock()
    return dp


def test_controller_initialization(mock_controller):
    """Verifies default controller attributes and state sets."""
    assert mock_controller.priority_enabled is True
    assert mock_controller.mon_port == 5005
    assert mock_controller.dscp_critical == 46
    assert isinstance(mock_controller.throttled_ports, set)
    assert isinstance(mock_controller.quarantined_hosts, set)


def test_install_proactive_qos_rules(mock_controller, mock_datapath):
    """Verifies that proactive QoS rules install queue 2 (critical), queue 1 (normal), queue 0 (bulk)."""
    mock_controller._install_proactive_qos_rules(mock_datapath)
    # Check that 3 FlowMod messages were sent to the datapath
    assert mock_datapath.send_msg.call_count == 3

    flow_mods = [call[0][0] for call in mock_datapath.send_msg.call_args_list]
    priorities = [fm.priority for fm in flow_mods]
    assert 100 in priorities  # Critical DSCP 46
    assert 50 in priorities   # Normal DSCP 0
    assert 10 in priorities   # Best-effort bulk


def test_install_and_remove_dynamic_throttle(mock_controller, mock_datapath):
    """Verifies dynamic OpenFlow throttle rule installation on congestion and subsequent deletion."""
    mock_controller.install_dynamic_throttle(mock_datapath, port_no=1, idle_timeout=15)
    assert mock_datapath.send_msg.called

    flow_mod = mock_datapath.send_msg.call_args[0][0]
    assert flow_mod.priority == 80
    assert flow_mod.idle_timeout == 15

    # Test removing dynamic throttle
    mock_datapath.send_msg.reset_mock()
    mock_controller.remove_dynamic_throttle(mock_datapath, port_no=1)
    assert mock_datapath.send_msg.called
    del_mod = mock_datapath.send_msg.call_args[0][0]
    assert del_mod.command == ofproto_v1_3.OFPFC_DELETE_STRICT
    assert del_mod.priority == 80


def test_dynamic_host_quarantine(mock_controller, mock_datapath):
    """Verifies reactive host isolation via OpenFlow DROP flow rule."""
    rogue_ip = "10.0.0.99"
    mock_controller.quarantine_host(mock_datapath, host_ip=rogue_ip, reason="dos_burst", idle_timeout=30)

    assert rogue_ip in mock_controller.quarantined_hosts
    assert mock_datapath.send_msg.called
    flow_mod = mock_datapath.send_msg.call_args[0][0]
    assert flow_mod.priority == 200
    assert flow_mod.idle_timeout == 30

    # Unquarantine host
    mock_datapath.send_msg.reset_mock()
    mock_controller.unquarantine_host(mock_datapath, host_ip=rogue_ip)
    assert rogue_ip not in mock_controller.quarantined_hosts
    del_mod = mock_datapath.send_msg.call_args[0][0]
    assert del_mod.command == ofproto_v1_3.OFPFC_DELETE_STRICT
    assert del_mod.priority == 200


def test_port_stats_dynamic_congestion_trigger(mock_controller, mock_datapath):
    """Verifies port stats handler detects rate >= 8 Mbps and triggers dynamic throttling."""
    ev = MagicMock()
    ev.msg.datapath = mock_datapath
    stat = MagicMock()
    stat.port_no = 1

    # First stat sample: baseline
    stat.tx_bytes = 10_000_000
    ev.msg.body = [stat]
    mock_controller.port_stats_history[(1, 1)] = (10_000_000, time.time() - 1.0)

    # Second stat sample: +1.5 MB in 1 second = 12 Mbps (exceeds 8.0 Mbps bottleneck threshold)
    stat.tx_bytes = 11_500_000
    mock_controller.port_stats_reply_handler(ev)

    assert (1, 1) in mock_controller.throttled_ports
    assert mock_datapath.send_msg.called

    # Third stat sample: rate drops to 1 Mbps (< 4.0 Mbps threshold)
    stat.tx_bytes = 11_625_000
    mock_controller.port_stats_history[(1, 1)] = (11_500_000, time.time() - 1.0)
    mock_datapath.send_msg.reset_mock()
    mock_controller.port_stats_reply_handler(ev)

    assert (1, 1) not in mock_controller.throttled_ports
    assert mock_datapath.send_msg.called
