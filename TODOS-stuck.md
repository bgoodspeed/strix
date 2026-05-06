# TODOS: Fix Strix Stuck Behavior

Based on analysis of the "stuck" behavior where agents fail and don't automatically retry. Root cause: Anthropic API thinking block modification errors + no automatic recovery mechanisms.

## 🚨 Immediate Actions (Current Scan)

### Monitor Current Scan Health
- [ ] Set up monitoring script (see `scripts/monitor-scan.sh`) 
- [ ] Verify current running agents are making progress
- [ ] Check if any agents have been stuck >30 minutes
- [ ] Document any new stuck patterns observed

### Recovery Testing
- [ ] Test manual agent recovery by messaging root agent
- [ ] Verify new agents (API Recon, IDOR) are working properly
- [ ] Document time to recovery after manual intervention

## 🔧 Code Fixes (High Priority)

### 1. Fix Thinking Block API Errors
**File: `strix/llm/llm.py`**
- [ ] Add `_sanitize_conversation_history()` method before LLM API calls
- [ ] Filter out `thinking` and `redacted_thinking` blocks that can't be modified
- [ ] Test with conversation history that previously failed
- [ ] Add unit tests for conversation sanitization

```python
def _sanitize_conversation_history(self, messages):
    """Remove or preserve thinking blocks to avoid API errors"""
    for message in messages:
        if isinstance(message.get('content'), list):
            # Filter out thinking blocks that can't be modified
            message['content'] = [
                block for block in message['content'] 
                if block.get('type') not in ['thinking', 'redacted_thinking']
                or block.get('immutable') is not True
            ]
    return messages
```

### 2. Add Automatic Agent Recovery
**File: `strix/tools/agents_graph/agents_graph_actions.py`**
- [ ] Implement `_monitor_and_recover_failed_agents()` periodic check
- [ ] Add `_respawn_failed_agent()` function 
- [ ] Integrate into root agent main loop (check every 5 minutes)
- [ ] Add configuration for retry delay and max retry attempts
- [ ] Log recovery attempts to telemetry

```python
def _monitor_and_recover_failed_agents():
    """Periodically check for failed agents and attempt recovery"""
    # Implementation in code section
    pass

def _respawn_failed_agent(agent_id: str, fresh_context: bool = False):
    """Create new agent to replace failed one"""
    # Implementation in code section  
    pass
```

### 3. Add Deadlock Detection
**File: `strix/agents/base_agent.py`**
- [ ] Add `last_activity_time` tracking to agent state
- [ ] Implement `_check_deadlock()` method with configurable timeout
- [ ] Add `_handle_deadlock()` recovery mechanism
- [ ] Integrate deadlock checks into agent main loop
- [ ] Add deadlock events to telemetry

```python
async def _check_deadlock(self):
    """Detect if agent has been stuck too long"""
    # Implementation in code section
    pass
```

## 📊 Enhanced Monitoring & Alerting

### 4. Scan Health Monitoring
**New file: `strix/monitoring/scan_health.py`**
- [ ] Implement `monitor_scan_health()` function
- [ ] Add stuck agent detection (>30 min no activity)
- [ ] Add high failure rate alerts (>50% failed)
- [ ] Add scan progress stall detection
- [ ] Integrate with existing telemetry system

### 5. Multi-Channel Alerting
**Extend existing telemetry**
- [ ] Add structured alert events to tracer
- [ ] Implement webhook notifications for critical alerts
- [ ] Add Slack integration (if webhook available)
- [ ] Add email alerts for long-running stuck scans
- [ ] Configure alert thresholds via config

```python
def send_alert(alert_type: str, data: dict):
    """Send alert via multiple channels"""
    # Implementation in code section
    pass
```

## 🧪 Testing & Validation

### 6. Reproduction Testing
- [ ] Create test scenario that triggers thinking block error
- [ ] Verify fix prevents the API error
- [ ] Test automatic recovery of failed agents
- [ ] Test deadlock detection with artificially stuck agent
- [ ] Load test with multiple concurrent failing agents

### 7. Integration Testing  
- [ ] Test full scan with recovery mechanisms enabled
- [ ] Verify alerts fire correctly for stuck scenarios
- [ ] Test manual intervention still works after automatic recovery
- [ ] Ensure no regressions in normal scan behavior
- [ ] Test with different LLM models/providers

## 📈 Performance & Reliability

### 8. Configuration & Tuning
- [ ] Add config options for retry delays and timeouts
- [ ] Add config for deadlock detection sensitivity  
- [ ] Add config for alert thresholds
- [ ] Add config to disable auto-recovery (debugging mode)
- [ ] Document all new configuration options

```yaml
# Add to config
strix_agent_recovery:
  retry_delay_seconds: 300
  max_retries: 3
  deadlock_timeout_seconds: 1800
  enable_auto_recovery: true
  alert_thresholds:
    stuck_agent_minutes: 30
    failure_rate_percent: 50
```

### 9. Telemetry Enhancements
- [ ] Add recovery attempt events
- [ ] Add deadlock detection events  
- [ ] Add thinking block sanitization events
- [ ] Add scan health check events
- [ ] Enhance existing telemetry to track recovery success rates

## 🔍 Long-term Improvements

### 10. Architecture Enhancements
- [ ] Consider timeout-based agent orchestration vs passive monitoring
- [ ] Evaluate agent-to-agent communication mechanisms
- [ ] Consider circuit breaker patterns for failing agents
- [ ] Evaluate queue-based agent task distribution
- [ ] Consider agent health checks / heartbeat mechanisms

### 11. User Experience
- [ ] Add UI indicators for stuck/recovered agents
- [ ] Add manual "retry failed agents" button in UI
- [ ] Add scan health dashboard
- [ ] Add progress estimates accounting for retries
- [ ] Add notification when manual intervention needed

## 🚀 Deployment & Rollout

### 12. Gradual Rollout
- [ ] Deploy fixes in development environment first
- [ ] Test with controlled scans before production
- [ ] Add feature flags for new recovery mechanisms
- [ ] Monitor impact on scan performance and reliability
- [ ] Document new behaviors for users

### 13. Documentation
- [ ] Update troubleshooting docs with new recovery info
- [ ] Document new config options
- [ ] Add runbook for investigating stuck scans
- [ ] Update architecture docs with monitoring flows
- [ ] Create user guide for new alerting features

---

## Priority Order

1. **Immediate**: Set up monitoring script, verify current scan
2. **Week 1**: Fix thinking block errors (#1)
3. **Week 1**: Add basic automatic recovery (#2) 
4. **Week 2**: Add deadlock detection (#3)
5. **Week 2**: Enhanced alerting (#4-5)
6. **Week 3**: Testing & validation (#6-7)
7. **Week 4**: Performance tuning & rollout (#8-9, #12-13)
8. **Future**: Architecture improvements (#10-11)

## Success Metrics

- [ ] Zero scans stuck >30 minutes without automatic recovery
- [ ] <10% manual intervention rate for stuck scans
- [ ] <5 minute recovery time for failed agents
- [ ] >95% agent success rate after thinking block fixes
- [ ] Alerts fire within 5 minutes of stuck detection