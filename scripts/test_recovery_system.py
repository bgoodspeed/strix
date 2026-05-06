#!/usr/bin/env python3
"""
Integration test script for the Strix recovery system.

This script validates the key components of the stuck behavior fixes:
1. Thinking block sanitization
2. Automatic agent recovery
3. Deadlock detection
4. Scan health monitoring
5. Telemetry integration

Run this script to validate the recovery system is working correctly.
"""

import asyncio
import json
import sys
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import Mock, patch

# Add strix to path
sys.path.insert(0, str(Path(__file__).parent.parent))

try:
    from strix.llm.llm import LLM
    from strix.llm.config import LLMConfig
    from strix.agents.base_agent import BaseAgent
    from strix.agents.state import AgentState
    from strix.monitoring.scan_health import ScanHealthMonitor, check_scan_health
    from strix.telemetry.tracer import Tracer
    from strix.tools.agents_graph import agents_graph_actions
except ImportError as e:
    print(f"❌ Import error: {e}")
    print("Make sure you're running this from the strix directory")
    sys.exit(1)


class TestResults:
    """Track test results."""
    def __init__(self):
        self.passed = 0
        self.failed = 0
        self.errors = []

    def test_pass(self, name: str):
        print(f"✅ {name}")
        self.passed += 1

    def test_fail(self, name: str, error: str):
        print(f"❌ {name}: {error}")
        self.failed += 1
        self.errors.append(f"{name}: {error}")

    def summary(self):
        total = self.passed + self.failed
        print(f"\n📊 Test Summary: {self.passed}/{total} passed")
        if self.failed > 0:
            print(f"❌ Failed tests:")
            for error in self.errors:
                print(f"   - {error}")
        return self.failed == 0


def test_thinking_block_sanitization(results: TestResults):
    """Test the thinking block sanitization functionality."""
    try:
        print("\n🧠 Testing Thinking Block Sanitization...")

        # Create LLM instance
        config = LLMConfig(model_name="test/mock-model")
        llm = LLM(config, agent_name="test-agent")
        llm.agent_id = "test_agent_123"

        # Test data with immutable thinking blocks
        messages = [
            {
                "role": "assistant",
                "content": [
                    {
                        "type": "text",
                        "text": "This is normal content"
                    },
                    {
                        "type": "thinking",
                        "content": "This thinking block should be removed",
                        "immutable": True
                    },
                    {
                        "type": "redacted_thinking",
                        "content": "This should also be removed",
                        "immutable": True
                    },
                    {
                        "type": "thinking",
                        "content": "This thinking block should stay",
                        "immutable": False
                    }
                ]
            }
        ]

        # Test sanitization
        sanitized = llm._sanitize_conversation_history(messages)

        # Verify results
        if len(sanitized) != 1:
            results.test_fail("thinking_block_sanitization", "Wrong number of messages")
            return

        content = sanitized[0]["content"]
        if len(content) != 2:  # Should keep text and non-immutable thinking
            results.test_fail("thinking_block_sanitization", f"Expected 2 content blocks, got {len(content)}")
            return

        if content[0]["type"] != "text":
            results.test_fail("thinking_block_sanitization", "First block should be text")
            return

        if content[1]["type"] != "thinking" or content[1]["immutable"] != False:
            results.test_fail("thinking_block_sanitization", "Second block should be non-immutable thinking")
            return

        results.test_pass("thinking_block_sanitization")

    except Exception as e:
        results.test_fail("thinking_block_sanitization", str(e))


async def test_deadlock_detection(results: TestResults):
    """Test deadlock detection in BaseAgent."""
    try:
        print("\n⏰ Testing Deadlock Detection...")

        # Create mock agent
        class MockAgent(BaseAgent):
            agent_name = "TestAgent"

            def __init__(self, state: AgentState):
                self.state = state
                self.non_interactive = False
                self._current_task = None
                self._force_stop = False

        # Create agent with old last_updated time (simulating stuck agent)
        state = AgentState(agent_name="Test Agent", task="Test task")
        old_time = datetime.now(UTC) - timedelta(hours=2)  # 2 hours ago
        state.last_updated = old_time.isoformat()

        agent = MockAgent(state)

        # Mock recovery config to use short timeout for testing
        with patch('strix.agents.base_agent.get_recovery_config') as mock_config:
            mock_config.return_value = {"deadlock_timeout_seconds": 1800}  # 30 minutes

            # Test deadlock detection
            is_deadlocked = await agent._check_deadlock()
            if not is_deadlocked:
                results.test_fail("deadlock_detection", "Should detect deadlock for old timestamp")
                return

        # Test with recent timestamp
        state.last_updated = datetime.now(UTC).isoformat()
        is_deadlocked = await agent._check_deadlock()
        if is_deadlocked:
            results.test_fail("deadlock_detection", "Should not detect deadlock for recent timestamp")
            return

        results.test_pass("deadlock_detection")

    except Exception as e:
        results.test_fail("deadlock_detection", str(e))


async def test_scan_health_monitoring(results: TestResults):
    """Test scan health monitoring functionality."""
    try:
        print("\n🏥 Testing Scan Health Monitoring...")

        # Create test scan data
        current_time = datetime.now(UTC)
        old_time = current_time - timedelta(hours=1)

        sample_scan_data = {
            "agents": [
                {
                    "id": "agent_001",
                    "name": "Completed Agent",
                    "status": "completed",
                    "created_at": old_time.isoformat(),
                    "finished_at": (old_time + timedelta(minutes=30)).isoformat(),
                    "retry_count": 0
                },
                {
                    "id": "agent_002",
                    "name": "Stuck Agent",
                    "status": "running",
                    "created_at": old_time.isoformat(),  # Running for 1 hour
                    "finished_at": None,
                    "retry_count": 0
                },
                {
                    "id": "agent_003",
                    "name": "Failed Agent",
                    "status": "failed",
                    "created_at": old_time.isoformat(),
                    "finished_at": (old_time + timedelta(minutes=10)).isoformat(),
                    "retry_count": 2
                }
            ],
            "summary": {
                "total_agents": 3,
                "running": 1,
                "completed": 1,
                "failed": 1,
                "recovery_attempts": 2
            },
            "scan_start_time": old_time.isoformat(),
            "last_activity": current_time.isoformat()
        }

        # Test health monitoring
        monitor = ScanHealthMonitor({
            "stuck_agent_minutes": 30,
            "failure_rate_percent": 30,  # Lower threshold to trigger warning
            "enable_alerts": False  # Disable alerts for testing
        })

        health_report = await monitor.monitor_scan_health(sample_scan_data)

        # Verify report structure
        required_keys = ["overall_status", "issues", "metrics", "alerts", "timestamp"]
        for key in required_keys:
            if key not in health_report:
                results.test_fail("scan_health_monitoring", f"Missing key: {key}")
                return

        # Should detect stuck agent (running for 1 hour > 30 min threshold)
        stuck_issues = [i for i in health_report["issues"] if i["type"] == "stuck_agent"]
        if len(stuck_issues) != 1:
            results.test_fail("scan_health_monitoring", f"Expected 1 stuck agent, found {len(stuck_issues)}")
            return

        # Should detect high failure rate (33% > 30% threshold)
        failure_issues = [i for i in health_report["issues"] if i["type"] == "high_failure_rate"]
        if len(failure_issues) != 1:
            results.test_fail("scan_health_monitoring", f"Expected 1 failure rate issue, found {len(failure_issues)}")
            return

        # Overall status should be warning due to issues
        if health_report["overall_status"] == "healthy":
            results.test_fail("scan_health_monitoring", "Status should not be healthy with issues present")
            return

        results.test_pass("scan_health_monitoring")

    except Exception as e:
        results.test_fail("scan_health_monitoring", str(e))


def test_agent_recovery_logic(results: TestResults):
    """Test agent recovery logic."""
    try:
        print("\n🔄 Testing Agent Recovery Logic...")

        # Mock the agent graph data structures
        test_agent_id = "test_agent_123"
        parent_id = "parent_agent_456"

        # Setup mock data
        agents_graph_actions._agent_graph["nodes"] = {
            test_agent_id: {
                "name": "Failed Agent",
                "status": "error",
                "task": "Test task",
                "parent_id": parent_id,
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
        agents_graph_actions._agent_states[parent_id] = mock_parent_state

        # Test monitoring function
        with patch('strix.tools.agents_graph.agents_graph_actions.create_agent') as mock_create:
            mock_create.return_value = {
                "success": True,
                "agent_id": "recovery_agent_789",
                "message": "Recovery agent created"
            }

            recovery_result = agents_graph_actions._monitor_and_recover_failed_agents()

            # Verify recovery was attempted
            if recovery_result["agents_checked"] == 0:
                results.test_fail("agent_recovery_logic", "No agents were checked")
                return

            if recovery_result["failed_agents_found"] == 0:
                results.test_fail("agent_recovery_logic", "Failed agent was not detected")
                return

        # Cleanup
        agents_graph_actions._agent_graph["nodes"].clear()
        agents_graph_actions._agent_states.clear()
        agents_graph_actions._recovery_attempts.clear()

        results.test_pass("agent_recovery_logic")

    except Exception as e:
        results.test_fail("agent_recovery_logic", str(e))


def test_telemetry_integration(results: TestResults):
    """Test telemetry integration for recovery events."""
    try:
        print("\n📊 Testing Telemetry Integration...")

        # Create tracer
        tracer = Tracer(run_name="test_recovery_telemetry")

        # Mock _emit_event to capture calls
        emitted_events = []
        original_emit = tracer._emit_event

        def mock_emit_event(*args, **kwargs):
            emitted_events.append((args, kwargs))
            # Don't actually emit to avoid file system operations

        tracer._emit_event = mock_emit_event

        # Test recovery attempt tracking
        tracer.track_recovery_attempt("agent_123", 2, True, recovery_type="automatic")

        # Test deadlock detection tracking
        tracer.track_deadlock_detection("agent_456", 1800.0, True, True)

        # Test thinking block sanitization tracking
        tracer.track_thinking_block_sanitization("agent_789", 3, 10, True)

        # Test scan health check tracking
        tracer.track_scan_health_check("warning", 2, 1, 1, {"total_agents": 5})

        # Verify events were captured
        if len(emitted_events) != 4:
            results.test_fail("telemetry_integration", f"Expected 4 events, got {len(emitted_events)}")
            return

        # Verify event types
        event_types = [args[0] for args, kwargs in emitted_events]
        expected_types = [
            "agent.recovery.attempted",
            "agent.deadlock.detected",
            "agent.thinking_blocks.sanitized",
            "scan.health.checked"
        ]

        for expected_type in expected_types:
            if expected_type not in event_types:
                results.test_fail("telemetry_integration", f"Missing event type: {expected_type}")
                return

        results.test_pass("telemetry_integration")

    except Exception as e:
        results.test_fail("telemetry_integration", str(e))


def test_configuration_validation(results: TestResults):
    """Test configuration options for recovery system."""
    try:
        print("\n⚙️ Testing Configuration Validation...")

        # Test recovery config
        config = agents_graph_actions.get_recovery_config()
        required_keys = [
            "retry_delay_seconds",
            "max_retries",
            "deadlock_timeout_seconds",
            "enable_auto_recovery"
        ]

        for key in required_keys:
            if key not in config:
                results.test_fail("configuration_validation", f"Missing config key: {key}")
                return

        # Test config updates
        original_max_retries = config["max_retries"]
        update_result = agents_graph_actions.update_recovery_config({"max_retries": 5})

        if not update_result["success"]:
            results.test_fail("configuration_validation", "Failed to update config")
            return

        updated_config = agents_graph_actions.get_recovery_config()
        if updated_config["max_retries"] != 5:
            results.test_fail("configuration_validation", "Config update not applied")
            return

        # Restore original config
        agents_graph_actions.update_recovery_config({"max_retries": original_max_retries})

        results.test_pass("configuration_validation")

    except Exception as e:
        results.test_fail("configuration_validation", str(e))


async def main():
    """Run all tests."""
    print("🚀 Starting Strix Recovery System Integration Tests\n")

    results = TestResults()

    # Run tests
    test_thinking_block_sanitization(results)
    await test_deadlock_detection(results)
    await test_scan_health_monitoring(results)
    test_agent_recovery_logic(results)
    test_telemetry_integration(results)
    test_configuration_validation(results)

    # Print summary
    success = results.summary()

    if success:
        print(f"\n🎉 All tests passed! The recovery system is working correctly.")
        return 0
    else:
        print(f"\n💥 Some tests failed. Please review the errors above.")
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)