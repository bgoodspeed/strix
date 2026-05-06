#!/usr/bin/env python3

"""
Strix Failed Agent Recovery Script

This script analyzes failed agents in a Strix run and provides options for recovery.
It can identify the root cause of failures and suggest appropriate actions.

Usage:
    python3 recover-failed-agents.py [run_directory] [--auto-recover]

Examples:
    python3 recover-failed-agents.py strix_runs/grow-441e-75040-beta-clio-dev_1695
    python3 recover-failed-agents.py strix_runs/my-scan --auto-recover
"""

import json
import sys
import argparse
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Any, Optional


def load_scan_status(run_dir: Path) -> Dict[str, Any]:
    """Load scan status from the run directory."""
    status_file = run_dir / "scan_status.json"
    if not status_file.exists():
        raise FileNotFoundError(f"Status file not found: {status_file}")

    with open(status_file) as f:
        return json.load(f)


def load_events_log(run_dir: Path) -> List[Dict[str, Any]]:
    """Load events from the JSONL events log."""
    events_file = run_dir / "events.jsonl"
    if not events_file.exists():
        return []

    events = []
    with open(events_file) as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    events.append(json.loads(line))
                except json.JSONDecodeError as e:
                    print(f"Warning: Failed to parse event line: {e}")
    return events


def analyze_failure_patterns(events: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    """Analyze failure patterns from events log."""
    failures = {
        'llm_failed': [],
        'tool_failed': [],
        'timeout': [],
        'unknown': []
    }

    for event in events:
        if event.get('event_type') == 'agent.status.updated' and event.get('status') == 'llm_failed':
            failures['llm_failed'].append(event)
        elif 'error' in event.get('event_type', '') and event.get('status') == 'failed':
            if 'timeout' in str(event.get('error', '')).lower():
                failures['timeout'].append(event)
            elif 'tool' in event.get('event_type', ''):
                failures['tool_failed'].append(event)
            else:
                failures['unknown'].append(event)

    return failures


def get_failure_details(events: List[Dict[str, Any]], agent_id: str) -> Optional[Dict[str, Any]]:
    """Get detailed failure information for a specific agent."""
    for event in reversed(events):  # Most recent first
        if (event.get('actor', {}).get('agent_id') == agent_id and
            'error' in event.get('payload', {}).get('result', {})):
            return event.get('payload', {}).get('result', {})
        elif (event.get('actor', {}).get('agent_id') == agent_id and
              event.get('event_type') == 'tool.execution.updated' and
              'error' in event.get('payload', {})):
            return event.get('payload', {})
    return None


def identify_thinking_block_errors(events: List[Dict[str, Any]]) -> List[str]:
    """Identify agents that failed due to thinking block errors."""
    thinking_block_agents = []

    for event in events:
        if (event.get('event_type') == 'tool.execution.updated' and
            'thinking' in str(event.get('payload', {})).lower() and
            'cannot be modified' in str(event.get('payload', {}))):
            agent_id = event.get('actor', {}).get('agent_id')
            if agent_id and agent_id not in thinking_block_agents:
                thinking_block_agents.append(agent_id)

    return thinking_block_agents


def format_duration(seconds: float) -> str:
    """Format duration in human-readable format."""
    if seconds < 60:
        return f"{seconds:.1f}s"
    elif seconds < 3600:
        return f"{seconds/60:.1f}m"
    else:
        return f"{seconds/3600:.1f}h"


def print_scan_summary(status: Dict[str, Any]) -> None:
    """Print overall scan summary."""
    print("📊 SCAN SUMMARY")
    print("=" * 50)

    summary = status['summary']
    elapsed = status['elapsed_seconds']

    print(f"📁 Run ID: {status.get('run_id', 'Unknown')}")
    print(f"⏱️  Elapsed: {format_duration(elapsed)}")
    print(f"📈 Progress: {summary['completed']}/{summary['total_agents']} agents completed")
    print(f"🏃 Currently running: {summary['running']}")
    print(f"❌ Failed: {summary['failed']}")
    print(f"🔍 Findings: {summary['total_findings']}")
    print(f"✅ Completed: {'Yes' if status['scan_completed'] else 'No'}")
    print()


def print_failed_agents(status: Dict[str, Any], events: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Print details of failed agents and return list of failed agents."""
    failed_agents = [agent for agent in status['agents'] if 'failed' in agent['status']]

    if not failed_agents:
        print("✅ No failed agents found!")
        return []

    print("❌ FAILED AGENTS")
    print("=" * 50)

    thinking_block_agents = identify_thinking_block_errors(events)

    for agent in failed_agents:
        print(f"🔴 {agent['name']} ({agent['id']})")
        print(f"   Status: {agent['status']}")
        print(f"   Task: {agent['task'][:100]}..." if len(agent['task']) > 100 else f"   Task: {agent['task']}")
        print(f"   Tool calls made: {agent['tool_count']}")
        print(f"   Created: {agent['created_at']}")
        print(f"   Last update: {agent['updated_at']}")

        # Check if it's a thinking block error
        if agent['id'] in thinking_block_agents:
            print("   🧠 Root cause: Thinking block modification error")
            print("   💡 Solution: Needs fresh conversation context")

        # Get detailed error if available
        failure_details = get_failure_details(events, agent['id'])
        if failure_details:
            error_msg = str(failure_details.get('details', failure_details.get('error', '')))
            if error_msg:
                # Truncate long error messages
                if len(error_msg) > 200:
                    error_msg = error_msg[:200] + "..."
                print(f"   🔍 Error: {error_msg}")

        print()

    return failed_agents


def print_recovery_options(failed_agents: List[Dict[str, Any]], thinking_block_agents: List[str]) -> None:
    """Print recovery options based on failure analysis."""
    if not failed_agents:
        return

    print("🔧 RECOVERY OPTIONS")
    print("=" * 50)

    thinking_block_count = len([a for a in failed_agents if a['id'] in thinking_block_agents])
    other_failures_count = len(failed_agents) - thinking_block_count

    if thinking_block_count > 0:
        print(f"🧠 {thinking_block_count} agent(s) failed due to thinking block errors:")
        print("   These agents tried to modify immutable thinking blocks in conversation history.")
        print("   💡 Solution: Message the root agent to create new replacement agents")
        print("      Example: 'Please retry the failed API and IDOR agents with fresh context'")
        print()

    if other_failures_count > 0:
        print(f"⚠️  {other_failures_count} agent(s) failed due to other reasons:")
        print("   Check the detailed error messages above for specific issues.")
        print("   💡 Solutions:")
        print("      - Check network connectivity")
        print("      - Verify API credentials")
        print("      - Review tool execution errors")
        print("      - Consider manual retry if error is transient")
        print()

    print("🤖 AUTOMATED RECOVERY:")
    print("   Run with --auto-recover flag to attempt automated recovery")
    print("   Note: This will message the root agent to retry failed tasks")
    print()


def attempt_auto_recovery(run_dir: Path, failed_agents: List[Dict[str, Any]]) -> None:
    """Attempt automated recovery of failed agents."""
    print("🤖 ATTEMPTING AUTOMATED RECOVERY")
    print("=" * 50)

    if not failed_agents:
        print("✅ No failed agents to recover")
        return

    # This would integrate with Strix's agent messaging system
    # For now, we'll provide instructions for manual recovery

    failed_names = [agent['name'] for agent in failed_agents]
    recovery_message = f"""
Please retry the following failed agents with fresh context:

{', '.join(failed_names)}

The agents failed due to LLM API errors and need to be restarted with clean conversation history.
"""

    print("📝 Recovery message to send to root agent:")
    print("-" * 40)
    print(recovery_message.strip())
    print("-" * 40)
    print()

    print("💡 To send this message:")
    print("   1. Open the Strix UI")
    print("   2. Navigate to the root agent chat")
    print("   3. Send the message above")
    print("   4. Monitor for new replacement agents")
    print()


def check_agent_health(status: Dict[str, Any]) -> None:
    """Check health of currently running agents."""
    running_agents = [agent for agent in status['agents'] if agent['status'] == 'running']

    if not running_agents:
        print("ℹ️  No currently running agents")
        return

    print("🏃 RUNNING AGENTS HEALTH")
    print("=" * 50)

    now = datetime.now(timezone.utc)

    for agent in running_agents:
        try:
            updated_str = agent['updated_at']
            if updated_str.endswith('+00:00'):
                updated = datetime.fromisoformat(updated_str)
            elif updated_str.endswith('Z'):
                updated = datetime.fromisoformat(updated_str.replace('Z', '+00:00'))
            else:
                updated = datetime.fromisoformat(updated_str + '+00:00')

            minutes_since_update = (now - updated).total_seconds() / 60

            # Health indicators
            health_emoji = "🟢"  # Healthy
            if minutes_since_update > 30:
                health_emoji = "🔴"  # Stuck
            elif minutes_since_update > 15:
                health_emoji = "🟡"  # Warning

            print(f"{health_emoji} {agent['name']}")
            print(f"   Last activity: {minutes_since_update:.1f} minutes ago")
            print(f"   Tool calls: {agent['tool_count']}")

            if minutes_since_update > 30:
                print("   ⚠️  Agent may be stuck - consider manual intervention")

            print()

        except Exception as e:
            print(f"❓ {agent['name']} - Error checking status: {e}")

    print()


def main():
    parser = argparse.ArgumentParser(description="Analyze and recover failed Strix agents")
    parser.add_argument("run_dir", help="Path to the Strix run directory")
    parser.add_argument("--auto-recover", action="store_true",
                       help="Attempt automated recovery of failed agents")
    parser.add_argument("--verbose", "-v", action="store_true",
                       help="Show detailed analysis")

    args = parser.parse_args()

    run_dir = Path(args.run_dir)
    if not run_dir.exists():
        print(f"❌ Run directory does not exist: {run_dir}")
        sys.exit(1)

    try:
        # Load data
        print("📖 Loading scan data...")
        status = load_scan_status(run_dir)
        events = load_events_log(run_dir)

        print(f"✅ Loaded {len(events)} events")
        print()

        # Analysis
        print_scan_summary(status)
        check_agent_health(status)
        failed_agents = print_failed_agents(status, events)

        if failed_agents:
            thinking_block_agents = identify_thinking_block_errors(events)
            print_recovery_options(failed_agents, thinking_block_agents)

            if args.auto_recover:
                attempt_auto_recovery(run_dir, failed_agents)

        if args.verbose and events:
            print("🔍 FAILURE PATTERN ANALYSIS")
            print("=" * 50)
            failure_patterns = analyze_failure_patterns(events)
            for pattern, occurrences in failure_patterns.items():
                if occurrences:
                    print(f"{pattern}: {len(occurrences)} occurrences")

        # Summary and next steps
        print("🎯 NEXT STEPS")
        print("=" * 50)
        if status['scan_completed']:
            print("✅ Scan is complete - review findings")
        elif failed_agents and not status['summary']['running']:
            print("⚠️  Scan has stalled due to failed agents - recovery needed")
        elif status['summary']['running'] > 0:
            print("🏃 Scan is still running - monitor progress")
            print("💡 Run this script again later to check for new issues")
        else:
            print("❓ Scan status unclear - manual investigation needed")

    except Exception as e:
        print(f"❌ Error analyzing scan: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()