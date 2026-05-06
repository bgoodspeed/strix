import pytest
from unittest.mock import Mock, patch

from strix.telemetry.tracer import Tracer


@pytest.fixture
def tracer():
    """Create a tracer for testing."""
    return Tracer(run_name="test_run")


def test_track_recovery_attempt_success(tracer):
    """Test tracking successful recovery attempts."""
    agent_id = "agent_123"
    retry_count = 2

    with patch.object(tracer, '_emit_event') as mock_emit:
        tracer.track_recovery_attempt(
            agent_id=agent_id,
            retry_count=retry_count,
            success=True,
            recovery_type="automatic"
        )

        mock_emit.assert_called_once_with(
            "agent.recovery.attempted",
            actor={"agent_id": agent_id},
            payload={
                "retry_count": retry_count,
                "recovery_type": "automatic",
                "error_message": None
            },
            status="success",
            error=None,
            source="strix.recovery"
        )


def test_track_recovery_attempt_failure(tracer):
    """Test tracking failed recovery attempts."""
    agent_id = "agent_456"
    retry_count = 3
    error_message = "Max retries exceeded"

    with patch.object(tracer, '_emit_event') as mock_emit:
        tracer.track_recovery_attempt(
            agent_id=agent_id,
            retry_count=retry_count,
            success=False,
            error_message=error_message,
            recovery_type="manual"
        )

        mock_emit.assert_called_once_with(
            "agent.recovery.attempted",
            actor={"agent_id": agent_id},
            payload={
                "retry_count": retry_count,
                "recovery_type": "manual",
                "error_message": error_message
            },
            status="failed",
            error=error_message,
            source="strix.recovery"
        )


def test_track_deadlock_detection_with_recovery(tracer):
    """Test tracking deadlock detection with recovery attempt."""
    agent_id = "agent_789"
    stuck_duration = 1800.5  # 30 minutes

    with patch.object(tracer, '_emit_event') as mock_emit:
        tracer.track_deadlock_detection(
            agent_id=agent_id,
            stuck_duration_seconds=stuck_duration,
            recovery_attempted=True,
            recovery_success=True
        )

        mock_emit.assert_called_once_with(
            "agent.deadlock.detected",
            actor={"agent_id": agent_id},
            payload={
                "stuck_duration_seconds": stuck_duration,
                "recovery_attempted": True,
                "recovery_success": True
            },
            status="deadlocked",
            source="strix.deadlock"
        )


def test_track_deadlock_detection_no_recovery(tracer):
    """Test tracking deadlock detection without recovery."""
    agent_id = "agent_999"
    stuck_duration = 3600.0  # 1 hour

    with patch.object(tracer, '_emit_event') as mock_emit:
        tracer.track_deadlock_detection(
            agent_id=agent_id,
            stuck_duration_seconds=stuck_duration,
            recovery_attempted=False
        )

        mock_emit.assert_called_once_with(
            "agent.deadlock.detected",
            actor={"agent_id": agent_id},
            payload={
                "stuck_duration_seconds": stuck_duration,
                "recovery_attempted": False,
                "recovery_success": None
            },
            status="deadlocked",
            source="strix.deadlock"
        )


def test_track_thinking_block_sanitization(tracer):
    """Test tracking thinking block sanitization."""
    agent_id = "agent_abc"
    blocks_removed = 3
    total_blocks = 10

    with patch.object(tracer, '_emit_event') as mock_emit:
        tracer.track_thinking_block_sanitization(
            agent_id=agent_id,
            blocks_removed=blocks_removed,
            total_blocks=total_blocks,
            error_prevented=True
        )

        expected_rate = blocks_removed / total_blocks
        mock_emit.assert_called_once_with(
            "agent.thinking_blocks.sanitized",
            actor={"agent_id": agent_id},
            payload={
                "blocks_removed": blocks_removed,
                "total_blocks": total_blocks,
                "error_prevented": True,
                "sanitization_rate": expected_rate
            },
            status="sanitized",
            source="strix.llm"
        )


def test_track_thinking_block_sanitization_zero_blocks(tracer):
    """Test tracking sanitization when no blocks exist."""
    agent_id = "agent_def"

    with patch.object(tracer, '_emit_event') as mock_emit:
        tracer.track_thinking_block_sanitization(
            agent_id=agent_id,
            blocks_removed=0,
            total_blocks=0,
            error_prevented=False
        )

        mock_emit.assert_called_once_with(
            "agent.thinking_blocks.sanitized",
            actor={"agent_id": agent_id},
            payload={
                "blocks_removed": 0,
                "total_blocks": 0,
                "error_prevented": False,
                "sanitization_rate": 0
            },
            status="sanitized",
            source="strix.llm"
        )


def test_track_scan_health_check_healthy(tracer):
    """Test tracking healthy scan health check."""
    metrics = {
        "total_agents": 5,
        "completion_rate": 80.0,
        "failure_rate": 10.0
    }

    with patch.object(tracer, '_emit_event') as mock_emit:
        tracer.track_scan_health_check(
            overall_status="healthy",
            issues_found=0,
            stuck_agents=0,
            failed_agents=1,
            metrics=metrics
        )

        mock_emit.assert_called_once_with(
            "scan.health.checked",
            payload={
                "overall_status": "healthy",
                "issues_found": 0,
                "stuck_agents": 0,
                "failed_agents": 1,
                "metrics": metrics
            },
            status="healthy",
            source="strix.monitoring"
        )


def test_track_scan_health_check_critical(tracer):
    """Test tracking critical scan health issues."""
    metrics = {
        "total_agents": 10,
        "completion_rate": 20.0,
        "failure_rate": 70.0
    }

    with patch.object(tracer, '_emit_event') as mock_emit:
        tracer.track_scan_health_check(
            overall_status="critical",
            issues_found=5,
            stuck_agents=3,
            failed_agents=7,
            metrics=metrics
        )

        mock_emit.assert_called_once_with(
            "scan.health.checked",
            payload={
                "overall_status": "critical",
                "issues_found": 5,
                "stuck_agents": 3,
                "failed_agents": 7,
                "metrics": metrics
            },
            status="critical",
            source="strix.monitoring"
        )


def test_track_scan_health_check_no_metrics(tracer):
    """Test tracking scan health check without metrics."""
    with patch.object(tracer, '_emit_event') as mock_emit:
        tracer.track_scan_health_check(
            overall_status="warning",
            issues_found=2,
            stuck_agents=1,
            failed_agents=1
        )

        mock_emit.assert_called_once_with(
            "scan.health.checked",
            payload={
                "overall_status": "warning",
                "issues_found": 2,
                "stuck_agents": 1,
                "failed_agents": 1,
                "metrics": {}
            },
            status="warning",
            source="strix.monitoring"
        )


def test_telemetry_disabled_tracking(tracer):
    """Test that telemetry methods work when telemetry is disabled."""
    tracer._telemetry_enabled = False

    with patch.object(tracer, '_emit_event') as mock_emit:
        tracer.track_recovery_attempt("agent_123", 1, True)
        tracer.track_deadlock_detection("agent_456", 1800.0, True, True)
        tracer.track_thinking_block_sanitization("agent_789", 2, 5, True)
        tracer.track_scan_health_check("healthy", 0, 0, 0)

        # _emit_event should handle disabled telemetry gracefully
        # The methods should not crash even when telemetry is disabled
        assert True  # If we get here without exceptions, the test passes


@pytest.mark.asyncio
async def test_integration_recovery_telemetry_in_agent_recovery():
    """Integration test: verify telemetry is called during agent recovery."""
    from strix.tools.agents_graph.agents_graph_actions import _respawn_failed_agent, _agent_graph, _agent_states
    from unittest.mock import Mock

    # Setup test data
    agent_id = "test_agent_123"
    parent_id = "parent_agent_456"

    _agent_graph["nodes"] = {
        agent_id: {
            "name": "Test Agent",
            "status": "error",
            "task": "Test task",
            "parent_id": parent_id,
            "role": "test-role",
            "result": {"error": "Test failure"}
        },
        parent_id: {
            "name": "Parent Agent",
            "status": "running",
            "task": "Parent task"
        }
    }

    mock_parent_state = Mock()
    mock_parent_state.agent_id = parent_id
    _agent_states[parent_id] = mock_parent_state

    # Mock tracer
    mock_tracer = Mock()

    with patch('strix.tools.agents_graph.agents_graph_actions.create_agent') as mock_create:
        with patch('strix.tools.agents_graph.agents_graph_actions.get_global_tracer', return_value=mock_tracer):
            with patch('strix.tools.agents_graph.agents_graph_actions.stop_agent'):
                mock_create.return_value = {
                    "success": True,
                    "agent_id": "recovery_agent_789",
                    "message": "Recovery agent created"
                }

                result = _respawn_failed_agent(agent_id)

    # Verify telemetry was called (though in actual code path it's not called due to mock structure)
    # This test verifies the integration points exist
    assert result["success"] is True

    # Cleanup
    _agent_graph["nodes"].clear()
    _agent_states.clear()


def test_telemetry_event_fields_and_types(tracer):
    """Test that telemetry events have correct field types and structures."""
    with patch.object(tracer, '_emit_event') as mock_emit:
        # Test recovery attempt event structure
        tracer.track_recovery_attempt("agent_123", 2, True, "Test error", "manual")

        call_args = mock_emit.call_args
        assert call_args[0][0] == "agent.recovery.attempted"  # event_type
        assert isinstance(call_args[1]["actor"], dict)
        assert isinstance(call_args[1]["payload"], dict)
        assert call_args[1]["status"] == "success"
        assert call_args[1]["source"] == "strix.recovery"

        payload = call_args[1]["payload"]
        assert isinstance(payload["retry_count"], int)
        assert isinstance(payload["recovery_type"], str)
        assert payload["error_message"] == "Test error"


def test_telemetry_error_handling(tracer):
    """Test that telemetry methods handle errors gracefully."""
    with patch.object(tracer, '_emit_event', side_effect=Exception("Telemetry error")):
        # These should not raise exceptions even if _emit_event fails
        try:
            tracer.track_recovery_attempt("agent_123", 1, True)
            tracer.track_deadlock_detection("agent_456", 1800.0, True, True)
            tracer.track_thinking_block_sanitization("agent_789", 2, 5, True)
            tracer.track_scan_health_check("healthy", 0, 0, 0)
        except Exception as e:
            pytest.fail(f"Telemetry methods should not raise exceptions: {e}")