import pytest
import threading
from datetime import UTC, datetime
from unittest.mock import Mock, patch, MagicMock

from strix.tools.agents_graph.agents_graph_actions import (
    _monitor_and_recover_failed_agents,
    _respawn_failed_agent,
    check_and_recover_agents,
    get_recovery_config,
    update_recovery_config,
    _agent_graph,
    _running_agents,
    _agent_instances,
    _agent_states,
    _recovery_attempts,
    _RECOVERY_CONFIG
)


@pytest.fixture(autouse=True)
def reset_agent_graph():
    """Reset agent graph state before each test."""
    global _agent_graph, _running_agents, _agent_instances, _agent_states, _recovery_attempts

    # Store original state
    original_graph = _agent_graph.copy()
    original_running = _running_agents.copy()
    original_instances = _agent_instances.copy()
    original_states = _agent_states.copy()
    original_attempts = _recovery_attempts.copy()

    # Clear for test
    _agent_graph.clear()
    _agent_graph.update({"nodes": {}, "edges": []})
    _running_agents.clear()
    _agent_instances.clear()
    _agent_states.clear()
    _recovery_attempts.clear()

    yield

    # Restore original state
    _agent_graph.clear()
    _agent_graph.update(original_graph)
    _running_agents.clear()
    _running_agents.update(original_running)
    _agent_instances.clear()
    _agent_instances.update(original_instances)
    _agent_states.clear()
    _agent_states.update(original_states)
    _recovery_attempts.clear()
    _recovery_attempts.update(original_attempts)


def test_get_recovery_config():
    """Test getting recovery configuration."""
    config = get_recovery_config()

    assert isinstance(config, dict)
    assert "retry_delay_seconds" in config
    assert "max_retries" in config
    assert "deadlock_timeout_seconds" in config
    assert "enable_auto_recovery" in config
    assert "alert_thresholds" in config


def test_update_recovery_config():
    """Test updating recovery configuration."""
    original_config = get_recovery_config()

    # Test valid update
    updates = {"max_retries": 5, "retry_delay_seconds": 600}
    result = update_recovery_config(updates)

    assert result["success"] is True
    assert result["updated_config"]["max_retries"] == 5
    assert result["updated_config"]["retry_delay_seconds"] == 600

    # Test invalid key
    invalid_updates = {"invalid_key": 123}
    result = update_recovery_config(invalid_updates)

    assert result["success"] is False
    assert "invalid_key" in result["error"]

    # Restore original config
    update_recovery_config(original_config)


def test_monitor_and_recover_failed_agents_disabled():
    """Test monitoring when auto-recovery is disabled."""
    with patch.object(_RECOVERY_CONFIG, '__getitem__', side_effect=lambda key: False if key == "enable_auto_recovery" else _RECOVERY_CONFIG.get(key)):
        result = _monitor_and_recover_failed_agents()

        assert result["recovery_enabled"] is False
        assert "disabled" in result["message"]


def test_monitor_and_recover_failed_agents_no_agents():
    """Test monitoring with no agents in graph."""
    result = _monitor_and_recover_failed_agents()

    assert result["agents_checked"] == 0
    assert result["failed_agents_found"] == 0
    assert result["recovery_attempts"] == 0


def test_monitor_and_recover_failed_agents_with_failed_agent():
    """Test monitoring and recovery of a failed agent."""
    # Setup failed agent
    agent_id = "test_agent_123"
    parent_id = "parent_agent_456"

    _agent_graph["nodes"][agent_id] = {
        "name": "Test Agent",
        "status": "error",
        "task": "Test task",
        "parent_id": parent_id,
        "started_at": datetime.now(UTC).isoformat(),
        "role": "test-role"
    }

    _agent_graph["nodes"][parent_id] = {
        "name": "Parent Agent",
        "status": "running",
        "task": "Parent task",
        "parent_id": None
    }

    # Mock parent agent state
    mock_parent_state = Mock()
    mock_parent_state.agent_id = parent_id
    _agent_states[parent_id] = mock_parent_state

    # Mock the create_agent function to avoid complex dependencies
    with patch('strix.tools.agents_graph.agents_graph_actions.create_agent') as mock_create:
        mock_create.return_value = {
            "success": True,
            "agent_id": "new_agent_789",
            "message": "Recovery agent created"
        }

        # Mock telemetry to avoid import issues
        with patch('strix.tools.agents_graph.agents_graph_actions.get_global_tracer'):
            result = _monitor_and_recover_failed_agents()

    assert result["agents_checked"] == 2
    assert result["failed_agents_found"] == 1
    assert result["recovery_attempts"] == 1
    assert result["successful_recoveries"] == 1

    # Check that retry count was incremented
    assert _recovery_attempts[agent_id] == 1

    # Check that failed agent was marked as replaced
    assert _agent_graph["nodes"][agent_id]["status"] == "replaced"


def test_monitor_detects_stuck_agent():
    """Test that monitoring detects and recovers stuck agents."""
    agent_id = "stuck_agent_123"
    parent_id = "parent_agent_456"

    # Set agent start time to over 30 minutes ago (past deadlock timeout)
    stuck_start_time = datetime.now(UTC).replace(minute=0, second=0, microsecond=0)
    stuck_start_time = stuck_start_time.replace(hour=stuck_start_time.hour - 1)  # 1 hour ago

    _agent_graph["nodes"][agent_id] = {
        "name": "Stuck Agent",
        "status": "running",
        "task": "Test task",
        "parent_id": parent_id,
        "started_at": stuck_start_time.isoformat(),
        "role": "test-role"
    }

    _agent_graph["nodes"][parent_id] = {
        "name": "Parent Agent",
        "status": "running",
        "task": "Parent task",
        "parent_id": None
    }

    mock_parent_state = Mock()
    mock_parent_state.agent_id = parent_id
    _agent_states[parent_id] = mock_parent_state

    with patch('strix.tools.agents_graph.agents_graph_actions.create_agent') as mock_create:
        mock_create.return_value = {
            "success": True,
            "agent_id": "recovery_agent_789",
            "message": "Recovery agent created"
        }

        with patch('strix.tools.agents_graph.agents_graph_actions.get_global_tracer'):
            result = _monitor_and_recover_failed_agents()

    assert result["failed_agents_found"] == 1
    assert result["recovery_attempts"] == 1
    assert result["successful_recoveries"] == 1


def test_respawn_failed_agent_success():
    """Test successful agent respawn."""
    agent_id = "failed_agent_123"
    parent_id = "parent_agent_456"

    _agent_graph["nodes"][agent_id] = {
        "name": "Failed Agent",
        "status": "error",
        "task": "Test task",
        "parent_id": parent_id,
        "role": "test-role",
        "result": {"error": "Test failure"}
    }

    _agent_graph["nodes"][parent_id] = {
        "name": "Parent Agent",
        "status": "running",
        "task": "Parent task"
    }

    mock_parent_state = Mock()
    mock_parent_state.agent_id = parent_id
    _agent_states[parent_id] = mock_parent_state

    with patch('strix.tools.agents_graph.agents_graph_actions.create_agent') as mock_create:
        mock_create.return_value = {
            "success": True,
            "agent_id": "recovery_agent_789",
            "message": "Recovery agent created"
        }

        with patch('strix.tools.agents_graph.agents_graph_actions.stop_agent'):
            result = _respawn_failed_agent(agent_id)

    assert result["success"] is True
    assert result["new_agent_id"] == "recovery_agent_789"
    assert result["old_agent_id"] == agent_id
    assert result["retry_count"] == 1
    assert result["briefing_provided"] is True

    # Check that retry count was tracked
    assert _recovery_attempts[agent_id] == 1

    # Check that old agent was marked as replaced
    assert _agent_graph["nodes"][agent_id]["status"] == "replaced"
    assert _agent_graph["nodes"][agent_id]["result"]["auto_recovered"] is True


def test_respawn_failed_agent_max_retries_exceeded():
    """Test that respawn fails when max retries exceeded."""
    agent_id = "failed_agent_123"

    # Set retry count to exceed maximum
    _recovery_attempts[agent_id] = 5  # Higher than default max_retries (3)

    _agent_graph["nodes"][agent_id] = {
        "name": "Failed Agent",
        "status": "error",
        "task": "Test task",
        "parent_id": "parent_123"
    }

    result = _respawn_failed_agent(agent_id)

    assert result["success"] is False
    assert "Max retries" in result["error"]
    assert result["retry_count"] == 5


def test_respawn_failed_agent_no_parent():
    """Test that respawn fails for agents without parent (root agents)."""
    agent_id = "root_agent_123"

    _agent_graph["nodes"][agent_id] = {
        "name": "Root Agent",
        "status": "error",
        "task": "Root task",
        "parent_id": None  # No parent
    }

    result = _respawn_failed_agent(agent_id)

    assert result["success"] is False
    assert "cannot recover root agents" in result["error"]


def test_respawn_failed_agent_not_found():
    """Test respawn failure when agent not found."""
    result = _respawn_failed_agent("nonexistent_agent")

    assert result["success"] is False
    assert "not found in graph" in result["error"]


def test_check_and_recover_agents_tool():
    """Test the manual recovery tool."""
    mock_agent_state = Mock()

    # Setup a failed agent scenario
    agent_id = "failed_agent_123"
    parent_id = "parent_agent_456"

    _agent_graph["nodes"][agent_id] = {
        "name": "Failed Agent",
        "status": "error",
        "task": "Test task",
        "parent_id": parent_id
    }

    _agent_graph["nodes"][parent_id] = {
        "name": "Parent Agent",
        "status": "running",
        "task": "Parent task"
    }

    mock_parent_state = Mock()
    mock_parent_state.agent_id = parent_id
    _agent_states[parent_id] = mock_parent_state

    with patch('strix.tools.agents_graph.agents_graph_actions.create_agent') as mock_create:
        mock_create.return_value = {
            "success": True,
            "agent_id": "recovery_agent_789"
        }

        with patch('strix.tools.agents_graph.agents_graph_actions.get_global_tracer'):
            result = check_and_recover_agents(mock_agent_state)

    assert result["success"] is True
    assert "Checked 2 agents" in result["message"]
    assert "Found 1 failed" in result["message"]
    assert "Attempted 1 recoveries" in result["message"]
    assert "Successfully recovered 1 agents" in result["message"]
    assert result["details"] is not None
    assert result["recovery_config"] is not None


def test_respawn_with_fresh_context():
    """Test respawn with fresh context option."""
    agent_id = "failed_agent_123"
    parent_id = "parent_agent_456"

    _agent_graph["nodes"][agent_id] = {
        "name": "Failed Agent",
        "status": "error",
        "task": "Test task",
        "parent_id": parent_id
    }

    _agent_graph["nodes"][parent_id] = {
        "name": "Parent Agent",
        "status": "running"
    }

    mock_parent_state = Mock()
    _agent_states[parent_id] = mock_parent_state

    with patch('strix.tools.agents_graph.agents_graph_actions.create_agent') as mock_create:
        mock_create.return_value = {"success": True, "agent_id": "new_agent"}

        result = _respawn_failed_agent(agent_id, fresh_context=True)

        # Check that create_agent was called with inherit_context=False
        mock_create.assert_called_once()
        call_args = mock_create.call_args
        assert call_args.kwargs["inherit_context"] is False


def test_recovery_attempts_tracking():
    """Test that recovery attempts are properly tracked."""
    agent_id = "test_agent"

    assert _recovery_attempts.get(agent_id, 0) == 0

    # Setup minimal agent and parent
    _agent_graph["nodes"][agent_id] = {
        "parent_id": "parent_123",
        "name": "Test",
        "status": "error",
        "task": "test"
    }
    _agent_graph["nodes"]["parent_123"] = {"name": "Parent"}
    _agent_states["parent_123"] = Mock(agent_id="parent_123")

    with patch('strix.tools.agents_graph.agents_graph_actions.create_agent') as mock_create:
        mock_create.return_value = {"success": True, "agent_id": "new_agent"}

        # First attempt
        _respawn_failed_agent(agent_id)
        assert _recovery_attempts[agent_id] == 1

        # Second attempt
        _respawn_failed_agent(agent_id)
        assert _recovery_attempts[agent_id] == 2


def test_monitor_handles_exceptions_gracefully():
    """Test that monitoring handles exceptions without crashing."""
    # Setup malformed agent data that might cause exceptions
    _agent_graph["nodes"]["malformed_agent"] = {
        "status": "error",
        "started_at": "invalid_date_format"  # This should cause parsing errors
    }

    result = _monitor_and_recover_failed_agents()

    # Should still return a result, but with errors logged
    assert "check_time" in result
    assert "agents_checked" in result
    # Errors should be captured, not raised
    assert isinstance(result.get("errors", []), list)