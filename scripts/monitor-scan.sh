#!/bin/bash

# Monitor Strix scan health and alert on stuck agents
# Usage: ./monitor-scan.sh [run_directory] [check_interval_seconds]
#
# Example: ./monitor-scan.sh strix_runs/grow-441e-75040-beta-clio-dev_1695 300

set -e

# Configuration
RUN_DIR="${1:-strix_runs/grow-441e-75040-beta-clio-dev_1695}"
CHECK_INTERVAL="${2:-300}"  # 5 minutes default
STUCK_THRESHOLD_MINUTES=30
ALERT_FILE="scan_alerts.log"

# Colors for output
RED='\033[0;31m'
YELLOW='\033[1;33m'
GREEN='\033[0;32m'
NC='\033[0m' # No Color

echo "🔍 Starting Strix scan monitor..."
echo "📁 Monitoring: $RUN_DIR"
echo "⏱️  Check interval: ${CHECK_INTERVAL}s"
echo "⚠️  Stuck threshold: ${STUCK_THRESHOLD_MINUTES} minutes"
echo "📝 Alerts logged to: $ALERT_FILE"
echo ""

# Function to check scan health
check_scan_health() {
    local status_file="$RUN_DIR/scan_status.json"

    if [[ ! -f "$status_file" ]]; then
        echo "❌ Status file not found: $status_file"
        return 1
    fi

    python3 << EOF
import json
import sys
from datetime import datetime, timezone

try:
    with open('$status_file') as f:
        status = json.load(f)
except Exception as e:
    print(f"❌ Error reading status file: {e}")
    sys.exit(1)

print(f"=== Scan Health Check at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ===")
# Count actual failures including llm_failed
actual_failed = status['summary']['failed']
llm_failed_count = len([a for a in status['agents'] if a['status'] == 'llm_failed'])
total_failed = actual_failed + llm_failed_count

print(f"📊 Summary:")
print(f"   Total agents: {status['summary']['total_agents']}")
print(f"   Running: {status['summary']['running']}")
print(f"   Completed: {status['summary']['completed']}")
print(f"   Failed: {total_failed} (reported: {status['summary']['failed']}, llm_failed: {llm_failed_count})")
print(f"   Findings: {status['summary']['total_findings']}")

# Calculate elapsed time
elapsed_hours = status['elapsed_seconds'] / 3600
print(f"   Elapsed: {elapsed_hours:.1f} hours")

# Check for stuck agents
now = datetime.now(timezone.utc)
stuck_agents = []
all_running = []

for agent in status['agents']:
    if agent['status'] == 'running':
        all_running.append(agent)
        try:
            # Handle both with and without 'Z' suffix
            updated_str = agent['updated_at']
            if updated_str.endswith('+00:00'):
                updated = datetime.fromisoformat(updated_str)
            elif updated_str.endswith('Z'):
                updated = datetime.fromisoformat(updated_str.replace('Z', '+00:00'))
            else:
                updated = datetime.fromisoformat(updated_str + '+00:00')

            minutes_since_update = (now - updated).total_seconds() / 60

            if minutes_since_update > $STUCK_THRESHOLD_MINUTES:
                stuck_agents.append({
                    'name': agent['name'],
                    'id': agent['id'],
                    'minutes_stuck': minutes_since_update,
                    'tool_count': agent.get('tool_count', 0)
                })
        except Exception as e:
            print(f"⚠️  Error parsing timestamp for {agent['name']}: {e}")

print(f"\\n🏃 Running agents:")
if not all_running:
    print("   None")
else:
    for agent in all_running:
        status_emoji = "🟢"
        updated_str = agent['updated_at']
        try:
            if updated_str.endswith('+00:00'):
                updated = datetime.fromisoformat(updated_str)
            elif updated_str.endswith('Z'):
                updated = datetime.fromisoformat(updated_str.replace('Z', '+00:00'))
            else:
                updated = datetime.fromisoformat(updated_str + '+00:00')
            minutes_ago = (now - updated).total_seconds() / 60
            if minutes_ago > $STUCK_THRESHOLD_MINUTES:
                status_emoji = "🔴"
            elif minutes_ago > 15:
                status_emoji = "🟡"
        except:
            status_emoji = "❓"

        print(f"   {status_emoji} {agent['name']} (tools: {agent.get('tool_count', 0)})")

if stuck_agents:
    print(f"\\n⚠️  STUCK AGENTS DETECTED:")
    for agent in stuck_agents:
        print(f"   🔴 {agent['name']} - stuck for {agent['minutes_stuck']:.1f} minutes")

    # Log alert
    alert_msg = f"{datetime.now().isoformat()}: STUCK_AGENTS detected: {len(stuck_agents)} agents stuck >{$STUCK_THRESHOLD_MINUTES}min"
    with open('$ALERT_FILE', 'a') as f:
        f.write(alert_msg + "\\n")
        for agent in stuck_agents:
            f.write(f"  - {agent['name']} ({agent['id']}): {agent['minutes_stuck']:.1f}min\\n")

    # Exit with error code to indicate stuck agents
    sys.exit(2)
else:
    print(f"\\n✅ No stuck agents detected")

# Check for thinking block errors
thinking_errors = []
if llm_failed_count > 0:
    # Read events.jsonl to check for thinking block errors
    import os
    events_file = os.path.join('$RUN_DIR', 'events.jsonl')
    if os.path.exists(events_file):
        with open(events_file) as f:
            for line in f:
                try:
                    event = json.loads(line.strip())
                    if ('thinking' in event.get('payload', {}).get('args', {}).get('details', '') or
                        'redacted_thinking' in event.get('payload', {}).get('args', {}).get('details', '')):
                        if 'cannot be modified' in event.get('payload', {}).get('args', {}).get('details', ''):
                            agent_name = event.get('actor', {}).get('agent_name', 'Unknown')
                            if agent_name not in [e['agent'] for e in thinking_errors]:
                                thinking_errors.append({'agent': agent_name})
                except:
                    pass

if thinking_errors:
    print(f"\\n🧠 THINKING BLOCK ERRORS DETECTED:")
    for error in thinking_errors:
        print(f"   🔴 {error['agent']} - cannot modify thinking blocks")

    alert_msg = f"{datetime.now().isoformat()}: THINKING_BLOCK_ERRORS: {len(thinking_errors)} agents failing on thinking block modification"
    with open('$ALERT_FILE', 'a') as f:
        f.write(alert_msg + "\\n")
        for error in thinking_errors:
            f.write(f"  - {error['agent']}: thinking block modification error\\n")

# Check failure rate using actual failed count
if status['summary']['total_agents'] > 0:
    failure_rate = total_failed / status['summary']['total_agents']
    if failure_rate > 0.5:
        print(f"\\n⚠️  HIGH FAILURE RATE: {failure_rate:.1%}")
        alert_msg = f"{datetime.now().isoformat()}: HIGH_FAILURE_RATE: {failure_rate:.1%}"
        with open('$ALERT_FILE', 'a') as f:
            f.write(alert_msg + "\\n")
        sys.exit(3)

print("")
EOF
}

# Function to send notification (if configured)
send_notification() {
    local message="$1"
    local severity="$2"  # info, warning, error

    # Log to file
    echo "$(date -u +"%Y-%m-%dT%H:%M:%SZ") [$severity] $message" >> "$ALERT_FILE"

    # Optional: Send webhook notification
    if [[ -n "${STRIX_ALERT_WEBHOOK:-}" ]]; then
        curl -s -X POST "$STRIX_ALERT_WEBHOOK" \
            -H "Content-Type: application/json" \
            -d "{\"text\":\"Strix Alert [$severity]: $message\", \"run_dir\":\"$RUN_DIR\"}" \
            || echo "⚠️  Failed to send webhook notification"
    fi

    # Optional: macOS desktop notification
    if command -v osascript >/dev/null 2>&1; then
        osascript -e "display notification \"$message\" with title \"Strix Scan Alert\" sound name \"default\""
    fi
}

# Trap to handle script termination
trap 'echo "🛑 Monitoring stopped"; exit 0' INT TERM

# Main monitoring loop
echo "🚀 Monitoring started. Press Ctrl+C to stop."
echo ""

iteration=0
while true; do
    iteration=$((iteration + 1))

    # Check scan health
    if check_scan_health; then
        health_status=$?
        case $health_status in
            2)
                echo -e "${RED}🚨 STUCK AGENTS DETECTED!${NC}"
                send_notification "Stuck agents detected in scan" "error"
                ;;
            3)
                echo -e "${YELLOW}⚠️  High failure rate detected${NC}"
                send_notification "High failure rate detected in scan" "warning"
                ;;
            *)
                if (( iteration % 4 == 0 )); then  # Every 4th check (20 min default)
                    echo -e "${GREEN}✅ Scan healthy${NC}"
                fi
                ;;
        esac
    else
        echo -e "${RED}❌ Failed to check scan health${NC}"
        send_notification "Failed to check scan health" "error"
    fi

    # Check if scan is complete
    if [[ -f "$RUN_DIR/scan_status.json" ]]; then
        scan_completed=$(python3 -c "import json; f=open('$RUN_DIR/scan_status.json'); print(json.load(f)['scan_completed']); f.close()")
        if [[ "$scan_completed" == "True" ]]; then
            echo "🎉 Scan completed successfully!"
            send_notification "Scan completed successfully" "info"
            break
        fi
    fi

    echo "⏳ Sleeping for ${CHECK_INTERVAL}s... (iteration $iteration)"
    sleep "$CHECK_INTERVAL"
done

echo "✅ Monitoring completed"