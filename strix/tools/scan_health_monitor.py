"""Scan health monitoring tools for Strix agents."""

from typing import Any, Dict, Optional
from strix.tools.registry import register_tool


@register_tool(sandbox_execution=False)
async def monitor_scan_health(agent_state: Any, config: Optional[str] = None) -> Dict[str, Any]:
    """Monitor scan health and report status.

    This tool monitors the health of all agents in the current scan,
    detecting stuck agents, high failure rates, and progress stalls.

    Args:
        agent_state: Current agent state (automatically provided)
        config: Optional JSON configuration string for monitoring parameters

    Returns:
        Dict containing health status, issues found, metrics, and alerts
    """
    try:
        from strix.monitoring.scan_health import ScanHealthMonitor
        import json

        # Parse config if provided
        monitor_config = None
        if config:
            try:
                monitor_config = json.loads(config)
            except json.JSONDecodeError as e:
                return {
                    "success": False,
                    "error": f"Invalid JSON config: {e}",
                    "health_report": None
                }

        # Create monitor and run health check
        monitor = ScanHealthMonitor(monitor_config)
        health_report = await monitor.monitor_scan_health()

        return {
            "success": True,
            "health_report": health_report,
            "summary": {
                "overall_status": health_report["overall_status"],
                "issues_found": len(health_report["issues"]),
                "critical_issues": len([i for i in health_report["issues"] if i["severity"] == "critical"]),
                "warning_issues": len([i for i in health_report["issues"] if i["severity"] == "warning"]),
                "alerts_generated": len(health_report["alerts"]),
                "check_timestamp": health_report["timestamp"]
            }
        }

    except Exception as e:
        return {
            "success": False,
            "error": f"Failed to monitor scan health: {e}",
            "health_report": None
        }


@register_tool(sandbox_execution=False)
async def get_scan_health_summary(agent_state: Any) -> Dict[str, Any]:
    """Get a quick summary of scan health status.

    Returns:
        Dict with simplified health status and key metrics
    """
    try:
        from strix.monitoring.scan_health import check_scan_health

        health_report = await check_scan_health()

        # Extract key information for quick summary
        issues = health_report.get("issues", [])
        metrics = health_report.get("metrics", {})

        summary = {
            "overall_status": health_report.get("overall_status", "unknown"),
            "timestamp": health_report.get("timestamp"),
            "agent_counts": {
                "total": metrics.get("total_agents", 0),
                "running": metrics.get("running_agents", 0),
                "completed": metrics.get("completed_agents", 0),
                "failed": metrics.get("failed_agents", 0)
            },
            "health_indicators": {
                "completion_rate_percent": metrics.get("completion_rate_percent", 0),
                "failure_rate_percent": metrics.get("failure_rate_percent", 0),
                "recovery_attempts": metrics.get("recovery_attempts", 0)
            },
            "current_issues": {
                "total": len(issues),
                "critical": len([i for i in issues if i["severity"] == "critical"]),
                "warnings": len([i for i in issues if i["severity"] == "warning"]),
                "stuck_agents": len([i for i in issues if i["type"] == "stuck_agent"]),
                "high_failure_rate": any(i["type"] == "high_failure_rate" for i in issues)
            }
        }

        # Add scan duration if available
        scan_duration = metrics.get("scan_duration_seconds")
        if scan_duration:
            summary["scan_duration_minutes"] = round(scan_duration / 60, 1)

        return {
            "success": True,
            "summary": summary,
            "recommendations": _get_health_recommendations(health_report)
        }

    except Exception as e:
        return {
            "success": False,
            "error": f"Failed to get scan health summary: {e}",
            "summary": None
        }


@register_tool(sandbox_execution=False)
async def alert_on_scan_issues(
    agent_state: Any,
    alert_channels: str = "log,file",
    severity_threshold: str = "warning"
) -> Dict[str, Any]:
    """Check scan health and send alerts if issues are found.

    Args:
        agent_state: Current agent state
        alert_channels: Comma-separated list of alert channels (log, file, webhook, slack)
        severity_threshold: Minimum severity to alert on (info, warning, critical)

    Returns:
        Dict with alert status and actions taken
    """
    try:
        from strix.monitoring.scan_health import ScanHealthMonitor

        # Parse parameters
        channels = [c.strip() for c in alert_channels.split(",")]
        threshold = severity_threshold.lower()

        config = {
            "alert_channels": channels,
            "enable_alerts": True
        }

        # Run health check with alerting enabled
        monitor = ScanHealthMonitor(config)
        health_report = await monitor.monitor_scan_health()

        # Filter issues by severity threshold
        severity_levels = {"info": 1, "warning": 2, "critical": 3}
        min_level = severity_levels.get(threshold, 2)

        relevant_issues = [
            issue for issue in health_report.get("issues", [])
            if severity_levels.get(issue["severity"], 1) >= min_level
        ]

        return {
            "success": True,
            "alerts_sent": len(health_report.get("alerts", [])),
            "issues_found": len(relevant_issues),
            "overall_status": health_report["overall_status"],
            "alert_channels_used": channels,
            "severity_threshold": threshold,
            "timestamp": health_report["timestamp"]
        }

    except Exception as e:
        return {
            "success": False,
            "error": f"Failed to send scan alerts: {e}",
            "alerts_sent": 0
        }


def _get_health_recommendations(health_report: Dict[str, Any]) -> list[str]:
    """Generate recommendations based on health report."""
    recommendations = []
    issues = health_report.get("issues", [])
    overall_status = health_report.get("overall_status", "unknown")

    if overall_status == "healthy":
        recommendations.append("✅ Scan is healthy - no immediate action required")
        return recommendations

    # Analyze issues and provide specific recommendations
    stuck_agents = [i for i in issues if i["type"] == "stuck_agent"]
    if stuck_agents:
        recommendations.append(
            f"🔄 {len(stuck_agents)} agents appear stuck - consider using check_and_recover_agents tool"
        )

    failure_issues = [i for i in issues if i["type"] == "high_failure_rate"]
    if failure_issues:
        recommendations.append(
            "📊 High failure rate detected - review failed agents and check for systematic issues"
        )

    progress_issues = [i for i in issues if i["type"] == "scan_progress_stall"]
    if progress_issues:
        recommendations.append(
            "⏱️ Scan progress stalled - verify if scan is complete or manual intervention needed"
        )

    # Add general recommendations
    if overall_status == "critical":
        recommendations.append(
            "🚨 Critical issues detected - immediate intervention recommended"
        )

    return recommendations