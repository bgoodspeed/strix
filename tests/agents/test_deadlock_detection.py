import pytest
import asyncio
from datetime import UTC, datetime, timedelta
from unittest.mock import Mock, patch, AsyncMock

from strix.agents.base_agent import BaseAgent
from strix.agents.state import AgentState
from strix.llm.config import LLMConfig


class MockBaseAgent(BaseAgent):
    """Mock BaseAgent for testing that doesn't require complex initialization."""
    agent_name = "TestAgent"

    def __init__(self, state: AgentState, llm_config: LLMConfig | None = None):
        # Minimal initialization for testing
        self.state = state
        self.llm_config = llm_config or LLMConfig(model_name="test-model")
        self.non_interactive = False
        self._current_task = None
        self._force_stop = False


@pytest.fixture
def agent_state():
    """Create a mock agent state for testing."""
    state = AgentState(
        agent_name="Test Agent",
        task="Test task",
        parent_id="parent_123"
    )
    return state


@pytest.fixture
def mock_agent(agent_state):
    """Create a mock agent for testing."""
    return MockBaseAgent(agent_state)


@pytest.mark.asyncio
async def test_check_deadlock_no_deadlock(mock_agent):
    """Test that check_deadlock returns False when agent is active."""
    # Set recent activity
    mock_agent.state.last_updated = datetime.now(UTC).isoformat()

    with patch('strix.agents.base_agent.get_recovery_config') as mock_config:
        mock_config.return_value = {"deadlock_timeout_seconds": 1800}

        result = await mock_agent._check_deadlock()
        assert result is False


@pytest.mark.asyncio
async def test_check_deadlock_detects_deadlock(mock_agent):
    """Test that check_deadlock detects agents stuck for too long."""
    # Set old activity (2 hours ago)
    old_time = datetime.now(UTC) - timedelta(hours=2)
    mock_agent.state.last_updated = old_time.isoformat()

    with patch('strix.agents.base_agent.get_recovery_config') as mock_config:
        mock_config.return_value = {"deadlock_timeout_seconds": 1800}  # 30 minutes

        result = await mock_agent._check_deadlock()
        assert result is True


@pytest.mark.asyncio
async def test_check_deadlock_handles_invalid_timestamp(mock_agent):
    """Test that check_deadlock handles invalid timestamps gracefully."""
    mock_agent.state.last_updated = "invalid_timestamp"

    with patch('strix.agents.base_agent.get_recovery_config') as mock_config:
        mock_config.return_value = {"deadlock_timeout_seconds": 1800}

        result = await mock_agent._check_deadlock()
        assert result is False  # Should not crash, should return False


@pytest.mark.asyncio
async def test_check_deadlock_no_last_updated(mock_agent):
    """Test check_deadlock when last_updated is None."""
    mock_agent.state.last_updated = None

    result = await mock_agent._check_deadlock()
    assert result is False


@pytest.mark.asyncio
async def test_handle_deadlock_non_interactive_recovery(mock_agent):
    """Test deadlock handling for non-interactive agents."""
    mock_agent.non_interactive = True

    # Mock the tracer
    mock_tracer = Mock()
    mock_tracer.log_tool_execution_start.return_value = "exec_123"

    result = await mock_agent._handle_deadlock(mock_tracer)

    # Should attempt self-recovery
    assert result is True

    # Should add recovery message
    messages = mock_agent.state.messages
    assert len(messages) > 0
    assert "SYSTEM RECOVERY" in messages[-1]["content"]

    # Should log to telemetry
    mock_tracer.log_tool_execution_start.assert_called_once()
    mock_tracer.update_tool_execution.assert_called_once()
    mock_tracer.update_agent_status.assert_called_with(mock_agent.state.agent_id, "deadlocked")


@pytest.mark.asyncio
async def test_handle_deadlock_root_agent_recovery(mock_agent):
    """Test deadlock handling for root agents (no parent)."""
    mock_agent.state.parent_id = None  # Root agent

    result = await mock_agent._handle_deadlock()

    # Should attempt self-recovery
    assert result is True

    # Should add recovery message
    messages = mock_agent.state.messages
    assert len(messages) > 0
    assert "SYSTEM RECOVERY" in messages[-1]["content"]


@pytest.mark.asyncio
async def test_handle_deadlock_sub_agent_notify_parent(mock_agent):
    """Test deadlock handling for sub-agents notifies parent."""
    mock_agent.state.parent_id = "parent_agent_123"

    # Mock the _enter_waiting_state method
    with patch.object(mock_agent, '_enter_waiting_state', new_callable=AsyncMock) as mock_wait:
        # Mock the send_user_message_to_agent function
        with patch('strix.agents.base_agent.send_user_message_to_agent') as mock_send:
            result = await mock_agent._handle_deadlock()

    # Should stop execution and wait for intervention
    assert result is False

    # Should notify parent
    mock_send.assert_called_once()
    call_args = mock_send.call_args
    assert call_args[0][0] == "parent_agent_123"  # parent_id
    assert "DEADLOCK ALERT" in call_args[0][1]  # message

    # Should enter waiting state
    mock_wait.assert_called_once()


@pytest.mark.asyncio
async def test_handle_deadlock_with_telemetry_error(mock_agent):
    """Test deadlock handling continues even if telemetry fails."""
    mock_agent.non_interactive = True

    # Mock tracer that raises exception
    mock_tracer = Mock()
    mock_tracer.log_tool_execution_start.side_effect = Exception("Telemetry error")

    # Should not raise exception despite telemetry error
    result = await mock_agent._handle_deadlock(mock_tracer)

    # Should still attempt recovery
    assert result is True


def test_should_check_deadlock(mock_agent):
    """Test deadlock checking frequency logic."""
    # Should check on iteration 0, 10, 20, etc.
    mock_agent.state.iteration = 0
    assert mock_agent._should_check_deadlock() is True

    mock_agent.state.iteration = 10
    assert mock_agent._should_check_deadlock() is True

    mock_agent.state.iteration = 25
    assert mock_agent._should_check_deadlock() is False

    mock_agent.state.iteration = 50
    assert mock_agent._should_check_deadlock() is True


@pytest.mark.asyncio
async def test_deadlock_integration_in_agent_loop(mock_agent):
    """Test that deadlock detection integrates properly with main agent loop."""
    # Set up deadlocked state
    old_time = datetime.now(UTC) - timedelta(hours=2)
    mock_agent.state.last_updated = old_time.isoformat()
    mock_agent.state.iteration = 10  # Will trigger deadlock check

    # Mock dependencies
    with patch('strix.agents.base_agent.get_recovery_config') as mock_config:
        mock_config.return_value = {"deadlock_timeout_seconds": 1800}

        with patch.object(mock_agent, '_handle_deadlock', new_callable=AsyncMock) as mock_handle:
            mock_handle.return_value = True  # Recovery successful

            # Test the deadlock check logic that would be in agent loop
            if mock_agent._should_check_deadlock():
                deadlock_detected = await mock_agent._check_deadlock()
                if deadlock_detected:
                    deadlock_handled = await mock_agent._handle_deadlock()

            # Verify deadlock was detected and handled
            assert deadlock_detected is True
            mock_handle.assert_called_once()


@pytest.mark.asyncio
async def test_deadlock_recovery_adjusts_iteration_counter(mock_agent):
    """Test that deadlock recovery adjusts iteration counter."""
    mock_agent.non_interactive = True
    mock_agent.state.iteration = 50  # High iteration count

    result = await mock_agent._handle_deadlock()

    assert result is True
    # Should have reduced iteration count to give room for recovery
    assert mock_agent.state.iteration < 50
    assert mock_agent.state.iteration >= 10


@pytest.mark.asyncio
async def test_deadlock_adds_error_to_state(mock_agent):
    """Test that deadlock detection adds error to agent state."""
    initial_error_count = len(mock_agent.state.errors)

    await mock_agent._handle_deadlock()

    # Should have added error
    assert len(mock_agent.state.errors) > initial_error_count
    assert any("Deadlock detected" in error for error in mock_agent.state.errors)


@pytest.mark.asyncio
async def test_deadlock_updates_last_updated_time(mock_agent):
    """Test that deadlock recovery updates last_updated timestamp."""
    mock_agent.non_interactive = True
    old_time = mock_agent.state.last_updated

    await mock_agent._handle_deadlock()

    # Should have updated timestamp
    assert mock_agent.state.last_updated != old_time

    # New timestamp should be recent
    new_time = datetime.fromisoformat(mock_agent.state.last_updated.replace('Z', '+00:00'))
    time_diff = (datetime.now(UTC) - new_time).total_seconds()
    assert time_diff < 5  # Should be within 5 seconds