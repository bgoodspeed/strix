import pytest
import os
from unittest.mock import patch, Mock

from strix.tools.agents_graph.agents_graph_actions import (
    get_recovery_config,
    update_recovery_config,
    _get_recovery_config
)


@pytest.fixture
def clean_env():
    """Ensure clean environment for config tests."""
    recovery_vars = [
        "STRIX_RECOVERY_RETRY_DELAY_SECONDS",
        "STRIX_RECOVERY_MAX_RETRIES",
        "STRIX_RECOVERY_DEADLOCK_TIMEOUT_SECONDS",
        "STRIX_RECOVERY_ENABLE_AUTO_RECOVERY",
        "STRIX_RECOVERY_STUCK_AGENT_MINUTES",
        "STRIX_RECOVERY_FAILURE_RATE_PERCENT",
        "STRIX_RECOVERY_SCAN_PROGRESS_STALL_MINUTES",
        "STRIX_RECOVERY_ALERT_CHANNELS",
        "STRIX_RECOVERY_WEBHOOK_URL",
        "STRIX_RECOVERY_SLACK_WEBHOOK_URL"
    ]

    # Save original values
    original_values = {}
    for var in recovery_vars:
        original_values[var] = os.environ.get(var)
        if var in os.environ:
            del os.environ[var]

    yield

    # Restore original values
    for var, value in original_values.items():
        if value is not None:
            os.environ[var] = value
        elif var in os.environ:
            del os.environ[var]


def test_get_recovery_config_defaults(clean_env):
    """Test getting recovery config with default values."""
    with patch('strix.tools.agents_graph.agents_graph_actions.Config') as mock_config:
        mock_config.get.return_value = None

        config = _get_recovery_config()

        # Check default values
        assert config["retry_delay_seconds"] == 300
        assert config["max_retries"] == 3
        assert config["deadlock_timeout_seconds"] == 1800
        assert config["enable_auto_recovery"] is True
        assert config["alert_thresholds"]["stuck_agent_minutes"] == 30
        assert config["alert_thresholds"]["failure_rate_percent"] == 50.0


def test_get_recovery_config_from_env(clean_env):
    """Test getting recovery config from environment variables."""
    # Set test environment variables
    os.environ["STRIX_RECOVERY_MAX_RETRIES"] = "5"
    os.environ["STRIX_RECOVERY_DEADLOCK_TIMEOUT_SECONDS"] = "2700"
    os.environ["STRIX_RECOVERY_ENABLE_AUTO_RECOVERY"] = "false"
    os.environ["STRIX_RECOVERY_STUCK_AGENT_MINUTES"] = "45"
    os.environ["STRIX_RECOVERY_FAILURE_RATE_PERCENT"] = "75.5"

    with patch('strix.tools.agents_graph.agents_graph_actions.Config') as mock_config:
        def mock_get(key):
            return os.environ.get(key.upper())

        mock_config.get.side_effect = mock_get

        config = _get_recovery_config()

        # Check environment values are used
        assert config["max_retries"] == 5
        assert config["deadlock_timeout_seconds"] == 2700
        assert config["enable_auto_recovery"] is False
        assert config["alert_thresholds"]["stuck_agent_minutes"] == 45
        assert config["alert_thresholds"]["failure_rate_percent"] == 75.5


def test_get_recovery_config_invalid_values(clean_env):
    """Test that invalid config values fall back to defaults."""
    with patch('strix.tools.agents_graph.agents_graph_actions.Config') as mock_config:
        def mock_get(key):
            # Return invalid values
            if key == "strix_recovery_max_retries":
                return "not_a_number"
            elif key == "strix_recovery_enable_auto_recovery":
                return "invalid_bool"
            elif key == "strix_recovery_failure_rate_percent":
                return "not_a_float"
            return None

        mock_config.get.side_effect = mock_get

        config = _get_recovery_config()

        # Should fall back to defaults
        assert config["max_retries"] == 3
        assert config["enable_auto_recovery"] is True  # Invalid bool becomes False, but None becomes True
        assert config["alert_thresholds"]["failure_rate_percent"] == 50.0


def test_get_recovery_config_boolean_parsing():
    """Test boolean parsing for enable_auto_recovery."""
    test_cases = [
        ("true", True),
        ("True", True),
        ("TRUE", True),
        ("1", True),
        ("yes", True),
        ("on", True),
        ("false", False),
        ("False", False),
        ("FALSE", False),
        ("0", False),
        ("no", False),
        ("off", False),
        ("", True),  # Empty string should default to True
        (None, True)  # None should default to True
    ]

    for test_value, expected in test_cases:
        with patch('strix.tools.agents_graph.agents_graph_actions.Config') as mock_config:
            def mock_get(key):
                if key == "strix_recovery_enable_auto_recovery":
                    return test_value
                return None

            mock_config.get.side_effect = mock_get

            config = _get_recovery_config()
            assert config["enable_auto_recovery"] == expected, f"Value '{test_value}' should parse to {expected}"


def test_update_recovery_config_success():
    """Test successful recovery config update."""
    with patch('strix.tools.agents_graph.agents_graph_actions.Config') as mock_config:
        mock_config.load.return_value = {"env": {}}
        mock_config.save.return_value = True

        updates = {
            "max_retries": 5,
            "retry_delay_seconds": 600,
            "enable_auto_recovery": False
        }

        result = update_recovery_config(updates)

        assert result["success"] is True
        assert "Recovery configuration updated" in result["message"]

        # Verify save was called
        mock_config.save.assert_called_once()

        # Check that the correct environment variables were set
        save_call_args = mock_config.save.call_args[0][0]
        env_vars = save_call_args["env"]

        assert env_vars["STRIX_RECOVERY_MAX_RETRIES"] == "5"
        assert env_vars["STRIX_RECOVERY_RETRY_DELAY_SECONDS"] == "600"
        assert env_vars["STRIX_RECOVERY_ENABLE_AUTO_RECOVERY"] == "False"


def test_update_recovery_config_nested_alert_thresholds():
    """Test updating nested alert_thresholds configuration."""
    with patch('strix.tools.agents_graph.agents_graph_actions.Config') as mock_config:
        mock_config.load.return_value = {"env": {}}
        mock_config.save.return_value = True

        updates = {
            "alert_thresholds": {
                "stuck_agent_minutes": 45,
                "failure_rate_percent": 75.5
            }
        }

        result = update_recovery_config(updates)

        assert result["success"] is True

        # Check that nested values were flattened
        save_call_args = mock_config.save.call_args[0][0]
        env_vars = save_call_args["env"]

        assert env_vars["STRIX_RECOVERY_STUCK_AGENT_MINUTES"] == "45"
        assert env_vars["STRIX_RECOVERY_FAILURE_RATE_PERCENT"] == "75.5"


def test_update_recovery_config_invalid_keys():
    """Test that invalid configuration keys are rejected."""
    result = update_recovery_config({
        "invalid_key": "value",
        "another_invalid": 123
    })

    assert result["success"] is False
    assert "Invalid configuration keys" in result["error"]
    assert "invalid_key" in result["error"]
    assert "another_invalid" in result["error"]


def test_update_recovery_config_save_failure():
    """Test handling of config save failure."""
    with patch('strix.tools.agents_graph.agents_graph_actions.Config') as mock_config:
        mock_config.load.return_value = {"env": {}}
        mock_config.save.return_value = False  # Simulate save failure

        result = update_recovery_config({"max_retries": 5})

        assert result["success"] is False
        assert "Failed to save configuration" in result["error"]


def test_update_recovery_config_preserves_existing():
    """Test that updating config preserves existing environment variables."""
    existing_env = {
        "OTHER_VAR": "keep_this",
        "STRIX_RECOVERY_MAX_RETRIES": "3"  # Will be overridden
    }

    with patch('strix.tools.agents_graph.agents_graph_actions.Config') as mock_config:
        mock_config.load.return_value = {"env": existing_env}
        mock_config.save.return_value = True

        result = update_recovery_config({"max_retries": 7})

        assert result["success"] is True

        # Check that existing variables are preserved and new ones added
        save_call_args = mock_config.save.call_args[0][0]
        env_vars = save_call_args["env"]

        assert env_vars["OTHER_VAR"] == "keep_this"  # Preserved
        assert env_vars["STRIX_RECOVERY_MAX_RETRIES"] == "7"  # Updated


def test_get_recovery_config_public_interface():
    """Test the public get_recovery_config function."""
    with patch('strix.tools.agents_graph.agents_graph_actions._get_recovery_config') as mock_get:
        expected_config = {"test": "config"}
        mock_get.return_value = expected_config

        result = get_recovery_config()

        assert result == expected_config
        mock_get.assert_called_once()


def test_config_exception_handling():
    """Test that configuration functions handle exceptions gracefully."""
    with patch('strix.tools.agents_graph.agents_graph_actions.Config') as mock_config:
        mock_config.get.side_effect = Exception("Config error")

        # Should not raise exception, should use defaults
        config = _get_recovery_config()

        # Should still return valid config with defaults
        assert isinstance(config, dict)
        assert "max_retries" in config
        assert "enable_auto_recovery" in config


def test_update_config_exception_handling():
    """Test that config update handles exceptions gracefully."""
    with patch('strix.tools.agents_graph.agents_graph_actions.Config') as mock_config:
        mock_config.load.side_effect = Exception("Load error")

        result = update_recovery_config({"max_retries": 5})

        assert result["success"] is False
        assert "Failed to update recovery configuration" in result["error"]


@pytest.mark.integration
def test_config_integration_with_monitoring():
    """Integration test: verify monitoring uses updated config."""
    from strix.monitoring.scan_health import ScanHealthMonitor

    # Test that monitoring picks up config changes
    with patch('strix.monitoring.scan_health.Config') as mock_config:
        def mock_get(key):
            if key == "strix_recovery_stuck_agent_minutes":
                return "45"  # Custom value
            elif key == "strix_recovery_failure_rate_percent":
                return "75.5"  # Custom value
            return None

        mock_config.get.side_effect = mock_get

        monitor = ScanHealthMonitor()

        assert monitor.config["stuck_agent_minutes"] == 45
        assert monitor.config["failure_rate_percent"] == 75.5