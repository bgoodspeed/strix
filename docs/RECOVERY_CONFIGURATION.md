# Strix Recovery System Configuration

This document describes all configuration options for the Strix recovery system that addresses stuck behavior issues.

## Configuration Overview

The recovery system can be configured through environment variables or the Strix CLI config file (`~/.strix/cli-config.json`). All configuration options have sensible defaults but can be customized for your specific deployment needs.

## Configuration Options

### Automatic Recovery Settings

#### `STRIX_RECOVERY_ENABLE_AUTO_RECOVERY`
- **Default:** `true`
- **Values:** `true`, `false`, `1`, `0`, `yes`, `no`
- **Description:** Enable or disable automatic agent recovery. When disabled, failed agents will not be automatically restarted.

#### `STRIX_RECOVERY_MAX_RETRIES`
- **Default:** `3`
- **Type:** Integer
- **Description:** Maximum number of recovery attempts per agent before giving up.

#### `STRIX_RECOVERY_RETRY_DELAY_SECONDS`
- **Default:** `300` (5 minutes)
- **Type:** Integer
- **Description:** Time to wait between recovery attempts in seconds.

### Deadlock Detection

#### `STRIX_RECOVERY_DEADLOCK_TIMEOUT_SECONDS`
- **Default:** `1800` (30 minutes)
- **Type:** Integer
- **Description:** Time threshold for detecting deadlocked agents. Agents with no activity for this duration are considered deadlocked.

### Health Monitoring Thresholds

#### `STRIX_RECOVERY_STUCK_AGENT_MINUTES`
- **Default:** `30`
- **Type:** Integer
- **Description:** Number of minutes after which a running agent is considered "stuck" for health monitoring purposes.

#### `STRIX_RECOVERY_FAILURE_RATE_PERCENT`
- **Default:** `50`
- **Type:** Float
- **Description:** Failure rate percentage threshold for triggering high failure rate alerts.

#### `STRIX_RECOVERY_SCAN_PROGRESS_STALL_MINUTES`
- **Default:** `60`
- **Type:** Integer
- **Description:** Number of minutes of no scan activity before considering the scan stalled.

### Alerting Configuration

#### `STRIX_RECOVERY_ALERT_CHANNELS`
- **Default:** `log,file`
- **Type:** Comma-separated string
- **Values:** `log`, `file`, `webhook`, `slack`, `email`
- **Description:** Channels to use for sending alerts about recovery events and health issues.

#### `STRIX_RECOVERY_WEBHOOK_URL`
- **Default:** `None`
- **Type:** URL string
- **Description:** Webhook URL for sending HTTP POST alerts. Required if `webhook` is included in alert channels.

#### `STRIX_RECOVERY_SLACK_WEBHOOK_URL`
- **Default:** `None`
- **Type:** URL string
- **Description:** Slack webhook URL for sending Slack notifications. Required if `slack` is included in alert channels.

## Configuration Methods

### Method 1: Environment Variables

Set environment variables directly:

```bash
export STRIX_RECOVERY_MAX_RETRIES=5
export STRIX_RECOVERY_DEADLOCK_TIMEOUT_SECONDS=2700
export STRIX_RECOVERY_ALERT_CHANNELS="log,file,slack"
export STRIX_RECOVERY_SLACK_WEBHOOK_URL="https://hooks.slack.com/services/YOUR/SLACK/WEBHOOK"
```

### Method 2: Strix CLI Config

Use the Strix CLI to manage configuration:

```bash
# Set individual options (planned feature)
strix config set recovery.max_retries 5
strix config set recovery.alert_channels "log,file,webhook"
strix config set recovery.webhook_url "https://your-webhook.example.com/alerts"

# View current configuration
strix config get recovery
```

### Method 3: Direct Config File Edit

Edit `~/.strix/cli-config.json` directly:

```json
{
  "env": {
    "STRIX_RECOVERY_MAX_RETRIES": "5",
    "STRIX_RECOVERY_DEADLOCK_TIMEOUT_SECONDS": "2700",
    "STRIX_RECOVERY_ALERT_CHANNELS": "log,file,slack",
    "STRIX_RECOVERY_SLACK_WEBHOOK_URL": "https://hooks.slack.com/services/YOUR/SLACK/WEBHOOK",
    "STRIX_RECOVERY_ENABLE_AUTO_RECOVERY": "true"
  }
}
```

### Method 4: Programmatic Configuration

Update configuration programmatically using the recovery API:

```python
from strix.tools.agents_graph.agents_graph_actions import update_recovery_config

result = update_recovery_config({
    "max_retries": 5,
    "deadlock_timeout_seconds": 2700,
    "alert_thresholds": {
        "stuck_agent_minutes": 45,
        "failure_rate_percent": 60
    }
})

if result["success"]:
    print("Configuration updated successfully")
else:
    print(f"Error: {result['error']}")
```

## Configuration Profiles

### Development Profile
```bash
export STRIX_RECOVERY_DEADLOCK_TIMEOUT_SECONDS=900  # 15 minutes
export STRIX_RECOVERY_STUCK_AGENT_MINUTES=15
export STRIX_RECOVERY_MAX_RETRIES=2
export STRIX_RECOVERY_ALERT_CHANNELS="log"
```

### Production Profile
```bash
export STRIX_RECOVERY_DEADLOCK_TIMEOUT_SECONDS=1800  # 30 minutes
export STRIX_RECOVERY_STUCK_AGENT_MINUTES=30
export STRIX_RECOVERY_MAX_RETRIES=3
export STRIX_RECOVERY_ALERT_CHANNELS="log,file,slack"
export STRIX_RECOVERY_SLACK_WEBHOOK_URL="https://hooks.slack.com/services/YOUR/PROD/WEBHOOK"
```

### High-Volume Profile
```bash
export STRIX_RECOVERY_DEADLOCK_TIMEOUT_SECONDS=3600  # 1 hour
export STRIX_RECOVERY_STUCK_AGENT_MINUTES=60
export STRIX_RECOVERY_MAX_RETRIES=5
export STRIX_RECOVERY_FAILURE_RATE_PERCENT=70
export STRIX_RECOVERY_ALERT_CHANNELS="log,file,webhook"
```

## Alert Channel Configuration

### Log Alerts
- **Requirements:** None (always available)
- **Output:** Standard Python logging
- **Configuration:** Enabled by including `log` in `STRIX_RECOVERY_ALERT_CHANNELS`

### File Alerts
- **Requirements:** Write permissions to current directory
- **Output:** `scan_alerts.log` file
- **Configuration:** Enabled by including `file` in `STRIX_RECOVERY_ALERT_CHANNELS`

### Webhook Alerts
- **Requirements:** `STRIX_RECOVERY_WEBHOOK_URL` must be set
- **Format:** JSON POST with alert data
- **Configuration:** Set webhook URL and include `webhook` in alert channels

Example webhook payload:
```json
{
  "alert": {
    "id": "alert_20240315_143022_stuck_agent",
    "type": "stuck_agent",
    "severity": "warning",
    "title": "WARNING: Agent Stuck",
    "message": "Agent 'Test Agent' has been running for 45.2 minutes without completion"
  },
  "scan_info": {
    "timestamp": "2024-03-15T14:30:22.123456Z",
    "alert_type": "stuck_agent",
    "severity": "warning"
  }
}
```

### Slack Alerts
- **Requirements:** `STRIX_RECOVERY_SLACK_WEBHOOK_URL` must be set
- **Format:** Slack-formatted blocks
- **Configuration:** Set Slack webhook URL and include `slack` in alert channels

## Monitoring Configuration

You can monitor the effectiveness of your configuration through telemetry events:

```python
from strix.telemetry.tracer import get_global_tracer

tracer = get_global_tracer()
if tracer:
    # Recovery events are automatically tracked
    # Check telemetry data for:
    # - agent.recovery.attempted
    # - agent.deadlock.detected
    # - scan.health.checked
    pass
```

## Troubleshooting Configuration

### Validate Current Configuration

```python
from strix.tools.agents_graph.agents_graph_actions import get_recovery_config

config = get_recovery_config()
print("Current recovery configuration:")
for key, value in config.items():
    print(f"  {key}: {value}")
```

### Test Configuration Changes

```python
from strix.tools.agents_graph.agents_graph_actions import update_recovery_config

# Test with temporary changes
result = update_recovery_config({
    "max_retries": 1,  # Lower for testing
    "deadlock_timeout_seconds": 300  # 5 minutes for testing
})

if result["success"]:
    print("Test configuration applied")
    # Run your tests...
    
    # Restore original settings
    update_recovery_config({
        "max_retries": 3,
        "deadlock_timeout_seconds": 1800
    })
```

### Common Configuration Issues

1. **Alerts not working:** Check that alert channels are correctly specified and webhook URLs are valid
2. **Too many recovery attempts:** Reduce `max_retries` or increase `retry_delay_seconds`
3. **Deadlocks not detected:** Reduce `deadlock_timeout_seconds` for more sensitive detection
4. **False positive stuck alerts:** Increase `stuck_agent_minutes` threshold

## Configuration Validation

The system validates configuration values and provides helpful error messages:

```bash
# Invalid configuration will be rejected
export STRIX_RECOVERY_MAX_RETRIES="not_a_number"
# Will fall back to default value (3)

export STRIX_RECOVERY_ALERT_CHANNELS="invalid_channel"
# Will log warning and use default channels
```

## Performance Considerations

- **Deadlock Detection:** Runs every 10 agent iterations (configurable frequency)
- **Health Monitoring:** Configurable check intervals (default: 5 minutes)
- **Recovery Delays:** Balance between quick recovery and system stability
- **Alert Throttling:** Alerts are generated per issue but not spammed

## Security Considerations

- **Webhook URLs:** Ensure webhook endpoints are secure and authenticated
- **Configuration Files:** Config files are created with restricted permissions (0600)
- **Sensitive Data:** Webhook URLs may contain sensitive tokens - protect accordingly

## Future Configuration Options

Planned configuration enhancements:

- Email alert configuration
- Custom recovery strategies per agent type
- Advanced scheduling for health checks
- Integration with external monitoring systems
- Configuration validation and schema enforcement