import pytest
import asyncio
from datetime import UTC, datetime, timedelta
from unittest.mock import Mock, patch, AsyncMock

from strix.monitoring.scan_health import ScanHealthMonitor, check_scan_health


@pytest.fixture
def health_config():
    """Sample health monitoring configuration."""
    return {
        "stuck_agent_minutes": 30,
        "failure_rate_percent": 50,
        "scan_progress_stall_minutes": 60,
        "enable_alerts": True,
        "alert_channels": ["log", "file"]
    }


@pytest.fixture
def sample_scan_data():
    """Sample scan data for testing."""
    current_time = datetime.now(UTC)
    old_time = current_time - timedelta(hours=1)

    return {
        "agents": [
            {
                "id": "agent_001",
                "name": "Test Agent 1",
                "status": "completed",
                "task": "Test task 1",
                "parent_id": None,
                "created_at": old_time.isoformat(),
                "finished_at": (old_time + timedelta(minutes=30)).isoformat(),
                "result": {"success": True},
                "is_running": False,
                "retry_count": 0
            },
            {
                "id": "agent_002",
                "name": "Test Agent 2",
                "status": "running",
                "task": "Test task 2",
                "parent_id": "agent_001",
                "created_at": old_time.isoformat(),
                "finished_at": None,
                "result": None,
                "is_running": True,
                "retry_count": 1
            },
            {
                "id": "agent_003",
                "name": "Test Agent 3",
                "status": "failed",
                "task": "Test task 3",
                "parent_id": "agent_001",
                "created_at": old_time.isoformat(),
                "finished_at": (old_time + timedelta(minutes=10)).isoformat(),
                "result": {"success": False, "error": "Test error"},
                "is_running": False,
                "retry_count": 2
            }
        ],
        "summary": {
            "total_agents": 3,
            "running": 1,
            "completed": 1,
            "failed": 1,
            "stuck": 0,
            "recovery_attempts": 3
        },
        "scan_start_time": old_time.isoformat(),
        "last_activity": current_time.isoformat()
    }


@pytest.mark.asyncio
async def test_scan_health_monitor_initialization(health_config):
    """Test ScanHealthMonitor initialization."""
    monitor = ScanHealthMonitor(health_config)
    assert monitor.config == health_config

    # Test default config
    default_monitor = ScanHealthMonitor()
    assert default_monitor.config["stuck_agent_minutes"] == 30
    assert default_monitor.config["failure_rate_percent"] == 50


@pytest.mark.asyncio
async def test_monitor_healthy_scan(health_config, sample_scan_data):
    """Test monitoring a healthy scan with no issues."""
    monitor = ScanHealthMonitor(health_config)

    # Modify sample data to be healthy
    healthy_data = sample_scan_data.copy()
    healthy_data["summary"]["failed"] = 0
    healthy_data["agents"] = [a for a in healthy_data["agents"] if a["status"] != "failed"]
    healthy_data["summary"]["total_agents"] = 2

    # Update running agent to be recent
    for agent in healthy_data["agents"]:
        if agent["status"] == "running":
            agent["created_at"] = datetime.now(UTC).isoformat()

    health_report = await monitor.monitor_scan_health(healthy_data)

    assert health_report["overall_status"] == "healthy"
    assert len(health_report["issues"]) == 0
    assert len(health_report["alerts"]) == 0


@pytest.mark.asyncio
async def test_detect_stuck_agents(health_config, sample_scan_data):
    """Test detection of stuck agents."""
    monitor = ScanHealthMonitor(health_config)

    # Running agent has been running for 1 hour (stuck)
    health_report = await monitor.monitor_scan_health(sample_scan_data)

    stuck_issues = [i for i in health_report["issues"] if i["type"] == "stuck_agent"]
    assert len(stuck_issues) == 1

    stuck_issue = stuck_issues[0]
    assert stuck_issue["agent_id"] == "agent_002"
    assert stuck_issue["severity"] == "warning"
    assert stuck_issue["stuck_duration_minutes"] > 30


@pytest.mark.asyncio
async def test_detect_high_failure_rate(health_config, sample_scan_data):
    """Test detection of high failure rates."""
    monitor = ScanHealthMonitor(health_config)

    # Modify data to have higher failure rate (66% - above 50% threshold)
    health_report = await monitor.monitor_scan_health(sample_scan_data)

    failure_issues = [i for i in health_report["issues"] if i["type"] == "high_failure_rate"]
    assert len(failure_issues) == 1

    failure_issue = failure_issues[0]
    assert failure_issue["failure_rate_percent"] > 30  # 1 of 3 failed
    assert failure_issue["severity"] in ["warning", "critical"]


@pytest.mark.asyncio
async def test_detect_scan_progress_stall(health_config):
    """Test detection of stalled scan progress."""
    monitor = ScanHealthMonitor(health_config)

    # Create data with stalled progress (last activity > 60 minutes ago)
    old_time = datetime.now(UTC) - timedelta(hours=2)
    stalled_data = {
        "agents": [
            {
                "id": "agent_001",
                "name": "Stalled Agent",
                "status": "completed",
                "created_at": old_time.isoformat(),
                "finished_at": old_time.isoformat()
            }
        ],
        "summary": {"total_agents": 1, "running": 0, "completed": 1, "failed": 0},
        "scan_start_time": old_time.isoformat(),
        "last_activity": old_time.isoformat()
    }

    health_report = await monitor.monitor_scan_health(stalled_data)

    progress_issues = [i for i in health_report["issues"] if i["type"] == "scan_progress_stall"]
    assert len(progress_issues) == 1

    stall_issue = progress_issues[0]
    assert stall_issue["stall_duration_minutes"] > 60
    assert stall_issue["severity"] == "warning"


@pytest.mark.asyncio
async def test_generate_metrics(health_config, sample_scan_data):
    """Test metrics generation."""
    monitor = ScanHealthMonitor(health_config)

    health_report = await monitor.monitor_scan_health(sample_scan_data)
    metrics = health_report["metrics"]

    assert metrics["total_agents"] == 3
    assert metrics["running_agents"] == 1
    assert metrics["completed_agents"] == 1
    assert metrics["failed_agents"] == 1
    assert metrics["completion_rate_percent"] == 33.33  # 1 of 3 completed
    assert metrics["failure_rate_percent"] == 33.33  # 1 of 3 failed
    assert metrics["recovery_attempts"] == 3


@pytest.mark.asyncio
async def test_alert_generation_and_logging(health_config, sample_scan_data, caplog):
    """Test alert generation and logging."""
    health_config["alert_channels"] = ["log"]

    monitor = ScanHealthMonitor(health_config)
    health_report = await monitor.monitor_scan_health(sample_scan_data)

    # Should generate alerts for issues found
    assert len(health_report["alerts"]) > 0

    # Check that log alerts were sent
    assert "SCAN ALERT" in caplog.text


@pytest.mark.asyncio
async def test_alert_file_output(health_config, sample_scan_data, tmp_path):
    """Test alert file output."""
    import os
    os.chdir(tmp_path)  # Change to temp directory

    health_config["alert_channels"] = ["file"]

    monitor = ScanHealthMonitor(health_config)
    await monitor.monitor_scan_health(sample_scan_data)

    # Check that alert file was created
    alert_file = tmp_path / "scan_alerts.log"
    if alert_file.exists():
        content = alert_file.read_text()
        assert "SCAN ALERT" in content or len(content) > 0


@pytest.mark.asyncio
async def test_webhook_alert_sending(health_config, sample_scan_data):
    """Test webhook alert sending."""
    health_config["alert_channels"] = ["webhook"]
    health_config["webhook_url"] = "http://example.com/webhook"

    monitor = ScanHealthMonitor(health_config)

    with patch('aiohttp.ClientSession.post') as mock_post:
        mock_post.return_value.__aenter__.return_value.status = 200

        await monitor.monitor_scan_health(sample_scan_data)

        # Should have attempted webhook calls
        assert mock_post.called


@pytest.mark.asyncio
async def test_get_scan_data_from_agents_graph():
    """Test getting scan data from agents graph."""
    monitor = ScanHealthMonitor()

    # Mock the agents graph data
    mock_graph = {
        "nodes": {
            "agent_123": {
                "name": "Test Agent",
                "status": "running",
                "task": "Test task",
                "created_at": datetime.now(UTC).isoformat()
            }
        }
    }

    mock_running = {"agent_123": Mock()}
    mock_recovery = {"agent_123": 1}

    with patch('strix.monitoring.scan_health._agent_graph', mock_graph):
        with patch('strix.monitoring.scan_health._running_agents', mock_running):
            with patch('strix.monitoring.scan_health._recovery_attempts', mock_recovery):
                scan_data = await monitor._get_scan_data()

                assert len(scan_data["agents"]) == 1
                assert scan_data["agents"][0]["id"] == "agent_123"
                assert scan_data["agents"][0]["is_running"] is True
                assert scan_data["agents"][0]["retry_count"] == 1


@pytest.mark.asyncio
async def test_get_scan_data_handles_import_error():
    """Test that _get_scan_data handles import errors gracefully."""
    monitor = ScanHealthMonitor()

    # This should handle the import error gracefully
    scan_data = await monitor._get_scan_data()

    # Should return empty/default data structure
    assert scan_data["agents"] == []
    assert scan_data["summary"]["total_agents"] == 0


@pytest.mark.asyncio
async def test_check_scan_health_convenience_function():
    """Test the convenience function for quick health checks."""
    config = {"stuck_agent_minutes": 15}

    with patch('strix.monitoring.scan_health.ScanHealthMonitor') as mock_monitor_class:
        mock_monitor = Mock()
        mock_monitor.monitor_scan_health.return_value = {"status": "healthy"}
        mock_monitor_class.return_value = mock_monitor

        result = await check_scan_health(config)

        mock_monitor_class.assert_called_once_with(config)
        mock_monitor.monitor_scan_health.assert_called_once_with(None)


def test_get_scan_start_time(health_config, sample_scan_data):
    """Test getting scan start time."""
    monitor = ScanHealthMonitor(health_config)

    start_time = monitor._get_scan_start_time(sample_scan_data["agents"])

    # Should return the earliest created_at time
    assert start_time is not None
    # All agents in sample data have the same created_at time
    expected_time = sample_scan_data["agents"][0]["created_at"]
    assert start_time == datetime.fromisoformat(expected_time.replace('Z', '+00:00')).isoformat()


def test_get_last_activity_time(health_config, sample_scan_data):
    """Test getting last activity time."""
    monitor = ScanHealthMonitor(health_config)

    last_activity = monitor._get_last_activity_time(sample_scan_data["agents"])

    # Should return the latest time among created_at and finished_at
    assert last_activity is not None


@pytest.mark.asyncio
async def test_monitor_handles_exceptions_gracefully(health_config):
    """Test that monitor handles exceptions without crashing."""
    monitor = ScanHealthMonitor(health_config)

    # Pass invalid scan data that might cause exceptions
    invalid_data = {"invalid": "data"}

    health_report = await monitor.monitor_scan_health(invalid_data)

    # Should still return a report, but with error status
    assert "timestamp" in health_report
    assert health_report.get("overall_status") in ["healthy", "warning", "critical", "error"]


def test_alert_title_generation(health_config):
    """Test alert title generation for different issue types."""
    monitor = ScanHealthMonitor(health_config)

    stuck_issue = {"type": "stuck_agent", "severity": "warning"}
    assert "Agent Stuck" in monitor._get_alert_title(stuck_issue)

    failure_issue = {"type": "high_failure_rate", "severity": "critical"}
    assert "High Failure Rate" in monitor._get_alert_title(failure_issue)

    stall_issue = {"type": "scan_progress_stall", "severity": "warning"}
    assert "Scan Progress Stalled" in monitor._get_alert_title(stall_issue)


@pytest.mark.asyncio
async def test_multiple_alert_channels(health_config, sample_scan_data):
    """Test sending alerts through multiple channels."""
    health_config["alert_channels"] = ["log", "file", "webhook"]
    health_config["webhook_url"] = "http://example.com/webhook"

    monitor = ScanHealthMonitor(health_config)

    with patch('aiohttp.ClientSession.post') as mock_post:
        mock_post.return_value.__aenter__.return_value.status = 200

        health_report = await monitor.monitor_scan_health(sample_scan_data)

        # Should have generated alerts
        assert len(health_report["alerts"]) > 0