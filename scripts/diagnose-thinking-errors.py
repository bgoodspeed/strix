#!/usr/bin/env python3
"""
Diagnose thinking block modification errors in Strix agent runs.
Usage: ./diagnose-thinking-errors.py <run_directory>
"""

import json
import sys
import os
from pathlib import Path

def analyze_thinking_errors(run_dir):
    """Analyze failed agents for thinking block errors."""
    run_path = Path(run_dir)
    events_file = run_path / "events.jsonl"

    if not events_file.exists():
        print(f"❌ Events file not found: {events_file}")
        return

    print(f"🔍 Analyzing thinking block errors in: {run_dir}")
    print("=" * 60)

    thinking_errors = []

    # Parse events for thinking block errors
    with open(events_file) as f:
        for line_num, line in enumerate(f, 1):
            try:
                event = json.loads(line.strip())

                # Look for thinking block errors
                details = event.get('payload', {}).get('args', {}).get('details', '')
                if ('thinking' in details and 'cannot be modified' in details):
                    agent_name = event.get('actor', {}).get('agent_name', 'Unknown')
                    agent_id = event.get('actor', {}).get('agent_id', 'Unknown')

                    # Extract message position from error
                    message_pos = None
                    if 'messages.' in details:
                        try:
                            start = details.find('messages.') + len('messages.')
                            end = details.find(':', start)
                            if end > start:
                                message_pos = details[start:end]
                        except:
                            pass

                    thinking_errors.append({
                        'agent_name': agent_name,
                        'agent_id': agent_id,
                        'message_position': message_pos,
                        'full_details': details,
                        'timestamp': event.get('timestamp'),
                        'line_num': line_num
                    })

            except json.JSONDecodeError as e:
                print(f"⚠️  Malformed JSON on line {line_num}: {e}")
                continue

    # Report findings
    print(f"📊 Found {len(thinking_errors)} thinking block errors")
    print()

    for i, error in enumerate(thinking_errors, 1):
        print(f"Error #{i}:")
        print(f"  Agent: {error['agent_name']} ({error['agent_id']})")
        print(f"  Time: {error['timestamp']}")
        print(f"  Message Position: {error['message_position']}")
        print(f"  Events Line: {error['line_num']}")

        # Look for agent directory
        agent_dir = None
        agents_dir = run_path / "agents"
        if agents_dir.exists():
            for d in agents_dir.iterdir():
                if d.is_dir() and error['agent_id'] in d.name:
                    agent_dir = d
                    break

        if agent_dir:
            print(f"  Agent Dir: {agent_dir.name}")

            # Check tool log
            tool_log = agent_dir / "tool_log.jsonl"
            if tool_log.exists():
                print(f"  Tool Log: {tool_log} ({tool_log.stat().st_size} bytes)")

                # Show last few tool calls before failure
                with open(tool_log) as f:
                    tool_calls = [json.loads(line) for line in f if line.strip()]

                print(f"  Last 3 tool calls:")
                for call in tool_calls[-3:]:
                    print(f"    - {call.get('tool_name', 'unknown')} ({call.get('status', 'unknown')})")

        print("  Error Details:")
        print(f"    {error['full_details'][:200]}...")
        print()

    # Recommendations
    print("🔧 RECOMMENDATIONS:")
    print()

    if thinking_errors:
        print("1. IMMEDIATE: This is a bug in Strix's conversation handling")
        print("   - Strix is modifying assistant messages containing thinking blocks")
        print("   - Claude API doesn't allow modification of thinking/redacted_thinking blocks")
        print()

        print("2. WORKAROUND OPTIONS:")
        print("   a) Restart failed agents without thinking mode")
        print("   b) Clear conversation history before retry")
        print("   c) Use models without thinking blocks for subagents")
        print()

        print("3. ROOT CAUSE:")
        print("   - Check Strix's message reconstruction logic")
        print("   - Likely in conversation state management when making subsequent LLM calls")
        print("   - May be related to tool result integration with thinking blocks")
        print()

        print("4. AFFECTED AGENTS:")
        for error in thinking_errors:
            print(f"   - {error['agent_name']} (message {error['message_position']})")
    else:
        print("✅ No thinking block errors detected")

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: ./diagnose-thinking-errors.py <run_directory>")
        sys.exit(1)

    run_dir = sys.argv[1]
    if not os.path.exists(run_dir):
        print(f"❌ Run directory not found: {run_dir}")
        sys.exit(1)

    analyze_thinking_errors(run_dir)