# Strix Stuck Behavior Triage Guide

This guide provides a systematic approach to diagnosing, monitoring, and recovering from stuck Strix scans. Use this when scans appear to have plateaued or agents have stopped making progress.

## 🚨 Quick Assessment (2 minutes)

Start here when you suspect a scan is stuck:

### Step 1: Check Current Status
```bash
# Get real-time scan overview
./scripts/extract-vulnerabilities.py strix_runs/your-scan-dir

# Check agent health
./scripts/recover-failed-agents.py strix_runs/your-scan-dir
```

**🚩 Red Flags:**
- Agents with status `llm_failed`
- Running agents with no activity >30 minutes  
- High failure rate (>50% of agents failed)
- Zero progress in last hour

### Step 2: Immediate Actions

**If agents are stuck:**
```bash
# Start monitoring (runs in background)
./scripts/monitor-scan.sh strix_runs/your-scan-dir 300 &

# Get recovery suggestions
./scripts/recover-failed-agents.py strix_runs/your-scan-dir --auto-recover
```

**If vulnerabilities found:**
```bash
# Extract current findings immediately (in case scan needs restart)
./scripts/extract-vulnerabilities.py strix_runs/your-scan-dir --format detailed --output findings-backup.txt
```

---

## 🔍 Deep Diagnosis (10 minutes)

When quick assessment shows problems, use these tools for detailed analysis:

### Tool 1: Scan Health Monitor
**Purpose:** Real-time monitoring and alerting  
**Script:** `./scripts/monitor-scan.sh`

```bash
# Continuous monitoring with 5-minute intervals
./scripts/monitor-scan.sh strix_runs/your-scan-dir 300

# Quick health check (single run)
./scripts/monitor-scan.sh strix_runs/your-scan-dir 60 | head -50
```

**What to look for:**
- 🔴 Stuck agents (red traffic lights in output)
- ⚠️ Alert messages in `scan_alerts.log`
- 📊 Progress stagnation (same running count for >1 hour)

### Tool 2: Failed Agent Analyzer  
**Purpose:** Root cause analysis of failures  
**Script:** `./scripts/recover-failed-agents.py`

```bash
# Full analysis with detailed error information
./scripts/recover-failed-agents.py strix_runs/your-scan-dir --verbose

# Get specific recovery instructions
./scripts/recover-failed-agents.py strix_runs/your-scan-dir --auto-recover
```

**Common failure patterns:**
- 🧠 **Thinking Block Errors:** `"thinking blocks cannot be modified"`
- 🔗 **Network Issues:** Connection timeouts, DNS failures
- 🔑 **Authentication Problems:** Invalid API keys, expired tokens
- ⏰ **Timeout Failures:** Long-running operations exceeded limits

### Tool 3: Vulnerability Extractor
**Purpose:** Preserve findings before potential restart  
**Script:** `./scripts/extract-vulnerabilities.py`

```bash
# Summary view (good for quick overview)
./scripts/extract-vulnerabilities.py strix_runs/your-scan-dir --format summary

# Detailed report (full findings with PoCs)
./scripts/extract-vulnerabilities.py strix_runs/your-scan-dir --format detailed

# JSON export (for integration with other tools)
./scripts/extract-vulnerabilities.py strix_runs/your-scan-dir --format json --output findings.json

# CSV export (for spreadsheet analysis)  
./scripts/extract-vulnerabilities.py strix_runs/your-scan-dir --format csv --output findings.csv
```

---

## 🛠️ Recovery Procedures

Choose the appropriate recovery method based on your diagnosis:

### Recovery Method 1: Automatic Retry (Thinking Block Errors)

**When to use:** Multiple agents failed with "thinking block modification" errors

**Steps:**
1. **Message the root agent** in the Strix UI:
   ```
   Please retry the failed agents with fresh context. 
   The following agents encountered LLM API errors and need to be restarted:
   - API Recon Agent  
   - IDOR Discovery Agent
   - SQL Injection Agent
   - Auth Testing Agent
   ```

2. **Monitor recovery:**
   ```bash
   # Watch for new agent creation
   ./scripts/monitor-scan.sh strix_runs/your-scan-dir 120
   ```

3. **Verify new agents are working:**
   ```bash
   # Check that new agents are making tool calls
   ./scripts/recover-failed-agents.py strix_runs/your-scan-dir
   ```

**Expected outcome:** Root agent creates new replacement agents with clean conversation history

### Recovery Method 2: Manual Intervention (Network/Auth Issues)

**When to use:** Agents failed due to connectivity, authentication, or configuration issues

**Steps:**
1. **Identify root cause:**
   ```bash
   ./scripts/recover-failed-agents.py strix_runs/your-scan-dir --verbose
   ```

2. **Fix underlying issue:**
   - Check network connectivity: `curl -I https://target-site.com`
   - Verify credentials: Check API keys, test authentication manually
   - Review proxy settings: Ensure corporate firewall not blocking

3. **Manual restart specific test types:**
   ```bash
   # Restart the scan with same target (may resume automatically)
   strix -t https://your-target.com
   ```

### Recovery Method 3: Clean Restart (Severe Issues)

**When to use:** Multiple failure types, scan completely stalled, or critical bugs discovered

**Steps:**
1. **Preserve current findings:**
   ```bash
   # Backup all current findings
   ./scripts/extract-vulnerabilities.py strix_runs/your-scan-dir --format json --output backup-findings-$(date +%Y%m%d-%H%M).json
   
   # Create summary report
   ./scripts/extract-vulnerabilities.py strix_runs/your-scan-dir --format detailed --output backup-report-$(date +%Y%m%d-%H%M).txt
   ```

2. **Document learned information:**
   ```bash
   # Note any working credentials, successful endpoints, etc.
   echo "Working credentials: demo@clio.com / testtest" >> restart-notes.txt
   echo "Successful endpoints discovered: /api/v1/contacts, /api/v1/user" >> restart-notes.txt
   ```

3. **Start fresh scan:**
   ```bash
   # Use same target and credentials but fresh run
   strix -t https://your-target.com --instruction "Use demo@clio.com / testtest credentials. Previous scan found XSS and stack trace disclosure issues."
   ```

---

## 📊 Monitoring Best Practices

### Continuous Monitoring Setup

**For active scans:**
```bash
# Terminal 1: Main monitoring (leave running)
./scripts/monitor-scan.sh strix_runs/your-scan-dir 300

# Terminal 2: Periodic health checks  
watch -n 600 './scripts/recover-failed-agents.py strix_runs/your-scan-dir'

# Terminal 3: Findings backup (every hour)
while true; do 
  ./scripts/extract-vulnerabilities.py strix_runs/your-scan-dir --format json --output "backup-$(date +%Y%m%d-%H%M).json"
  sleep 3600
done
```

### Alert Configuration

**Set up webhook alerts:**
```bash
# Export webhook URL for Slack/Teams/Discord
export STRIX_ALERT_WEBHOOK="https://hooks.slack.com/your-webhook-url"

# Run monitor with webhook notifications
./scripts/monitor-scan.sh strix_runs/your-scan-dir 300
```

**Desktop notifications** (macOS/Linux):
- Monitor script automatically shows desktop notifications for stuck agents
- Ensures you're alerted even when not watching terminal

### Progress Tracking

**Key metrics to track:**
- **Agent completion rate:** Should increase steadily
- **Finding discovery rate:** New vulnerabilities should be found periodically  
- **Tool execution rate:** Active agents should make tool calls regularly
- **Error patterns:** Look for recurring failure types

```bash
# Track metrics over time
echo "$(date): $(./scripts/extract-vulnerabilities.py strix_runs/your-scan-dir --quiet --format json | jq '.scan_summary.total_vulnerabilities')" >> progress.log
```

---

## 🔧 Prevention (Implementing Fixes)

Once your current scan is complete, implement these fixes to prevent future stuck behavior:

### Priority 1: Critical Fixes
- [ ] **Implement conversation sanitization** (fixes thinking block errors)
- [ ] **Add automatic agent retry logic** (eliminates manual intervention)  
- [ ] **Deploy health monitoring** (detects stuck agents automatically)

### Priority 2: Enhanced Monitoring
- [ ] **Set up alerting system** (get notified of issues immediately)
- [ ] **Add deadlock detection** (prevents agents from hanging indefinitely)
- [ ] **Implement progress tracking** (measure scan advancement)

### Implementation Guide
Follow the detailed checklist in `TODOS-stuck.md` for step-by-step implementation instructions.

---

## 📞 Escalation Path

### When to escalate:
- 🔴 **Immediate escalation:** Security critical findings (SQL injection, RCE, auth bypass)
- 🟡 **Same-day escalation:** High-severity findings affecting production systems  
- 🟢 **Routine reporting:** Medium/Low findings during regular security review cycles

### Escalation checklist:
1. **Extract findings:** Use vulnerability extractor for complete report
2. **Document impact:** Include business impact assessment  
3. **Provide remediation:** Include specific fix recommendations from detailed reports
4. **Set timeline:** Coordinate fix timeline based on severity

```bash
# Generate executive summary
./scripts/extract-vulnerabilities.py strix_runs/your-scan-dir --format summary > executive-summary.txt

# Generate technical report  
./scripts/extract-vulnerabilities.py strix_runs/your-scan-dir --format detailed > technical-report.txt

# Generate data for tracking
./scripts/extract-vulnerabilities.py strix_runs/your-scan-dir --format csv > findings-tracker.csv
```

---

## 🧰 Tool Reference

| Tool | Purpose | Usage | Output |
|------|---------|-------|--------|
| `monitor-scan.sh` | Real-time health monitoring | `./scripts/monitor-scan.sh DIR [INTERVAL]` | Live status, alerts |
| `recover-failed-agents.py` | Failure analysis & recovery | `./scripts/recover-failed-agents.py DIR [--auto-recover]` | Error details, recovery steps |
| `extract-vulnerabilities.py` | Findings extraction | `./scripts/extract-vulnerabilities.py DIR [--format FORMAT]` | Vuln reports in multiple formats |

**Format Options for Vulnerability Extractor:**
- `summary`: Executive overview with counts by severity
- `detailed`: Full technical reports with PoCs and remediation  
- `json`: Machine-readable format for integration
- `csv`: Spreadsheet-compatible for tracking and analysis

**Exit Codes:**
- `0`: Success, no issues
- `1`: Error running tool  
- `2`: Stuck agents detected (monitor-scan.sh)
- `3`: High failure rate detected (monitor-scan.sh)

## 📚 Additional Resources

- **Implementation Guide:** `TODOS-stuck.md` - Complete fix checklist
- **Log Files:** `scan_alerts.log` - Historical alerts and events
- **Original Analysis:** See investigation of your current scan in this conversation

---

*💡 **Pro Tip:** Run the monitoring script in a separate terminal window during all scans. The few seconds of setup saves hours of troubleshooting later.*


 # Full content (default behavior)
  python3 scripts/extract-vulnerabilities.py strix_runs/your-scan --format detailed

  # Truncate long sections only when requested
  python3 scripts/extract-vulnerabilities.py strix_runs/your-scan --format detailed --truncate

