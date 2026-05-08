"""
Scan health monitoring for Strix - monitors agent states and scan progress
for stuck agents, high failure rates, and overall scan health.
"""

import json
import logging
from datetime import UTC, datetime, timedelta
from typing import Any, Dict, List, Optional
from pathlib import Path

logger = logging.getLogger(__name__)


class ScanHealthMonitor:
    """Monitor scan health including stuck agents, failure rates, and progress."""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """Initialize scan health monitor with configuration.

        Args:
            config: Optional configuration dict. If None, uses default config.
        """
        self.config = config or self._get_default_config()
        self._last_check_time: Optional[datetime] = None

    def _get_default_config(self) -> Dict[str, Any]:
        """Get default monitoring configuration from Strix config."""
        try:
            from strix.config.config import Config

            def get_int(value: str, default: int) -> int:
                try:
                    return int(value)
                except (ValueError, TypeError):
                    return default

            def get_float(value: str, default: float) -> float:
                try:
                    return float(value)
                except (ValueError, TypeError):
                    return default

            def get_bool(value: str) -> bool:
                return value.lower() in ('true', '1', 'yes', 'on')

            alert_channels = Config.get("strix_recovery_alert_channels") or "log,file"
            channels = [c.strip() for c in alert_channels.split(",") if c.strip()]
            channels = [c for c in channels if c in ("log", "file")] or ["log", "file"]

            return {
                "stuck_agent_minutes": get_int(Config.get("strix_recovery_stuck_agent_minutes") or "30", 30),
                "failure_rate_percent": get_float(Config.get("strix_recovery_failure_rate_percent") or "50", 50.0),
                "scan_progress_stall_minutes": get_int(Config.get("strix_recovery_scan_progress_stall_minutes") or "60", 60),
                "check_interval_minutes": 5,
                "enable_alerts": True,
                "alert_channels": channels,
            }

        except ImportError:
            return {
                "stuck_agent_minutes": 30,
                "failure_rate_percent": 50,
                "scan_progress_stall_minutes": 60,
                "check_interval_minutes": 5,
                "enable_alerts": True,
                "alert_channels": ["log", "file"],
            }

    async def monitor_scan_health(self, scan_data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Monitor overall scan health and return status report.

        Args:
            scan_data: Optional scan data. If None, attempts to get from agents graph.

        Returns:
            Dict containing health status and any issues found.
        """
        try:
            current_time = datetime.now(UTC)
            self._last_check_time = current_time

            # Get scan data from various sources
            if scan_data is None:
                scan_data = await self._get_scan_data()

            health_report = {
                "timestamp": current_time.isoformat(),
                "overall_status": "healthy",
                "issues": [],
                "metrics": {},
                "alerts": []
            }

            # Check for stuck agents
            stuck_issues = await self._check_stuck_agents(scan_data)
            if stuck_issues:
                health_report["issues"].extend(stuck_issues)
                if len(stuck_issues) > 0:
                    health_report["overall_status"] = "warning"

            # Check failure rates
            failure_issues = await self._check_failure_rates(scan_data)
            if failure_issues:
                health_report["issues"].extend(failure_issues)
                if any(issue["severity"] == "critical" for issue in failure_issues):
                    health_report["overall_status"] = "critical"

            # Check scan progress stalls
            progress_issues = await self._check_scan_progress(scan_data)
            if progress_issues:
                health_report["issues"].extend(progress_issues)

            # Update overall status based on issues
            if any(issue["severity"] == "critical" for issue in health_report["issues"]):
                health_report["overall_status"] = "critical"
            elif health_report["issues"]:
                health_report["overall_status"] = "warning"

            # Generate metrics
            health_report["metrics"] = await self._generate_metrics(scan_data)

            # Generate alerts if issues found
            if health_report["issues"]:
                alerts = await self._generate_alerts(health_report["issues"])
                health_report["alerts"] = alerts

                if self.config.get("enable_alerts", True):
                    await self._send_alerts(alerts)

            # Log health check to telemetry
            try:
                from strix.telemetry.tracer import get_global_tracer
                tracer = get_global_tracer()
                if tracer:
                    stuck_count = len([i for i in health_report["issues"] if i["type"] == "stuck_agent"])
                    failed_count = health_report["metrics"].get("failed_agents", 0)

                    tracer.track_scan_health_check(
                        overall_status=health_report["overall_status"],
                        issues_found=len(health_report["issues"]),
                        stuck_agents=stuck_count,
                        failed_agents=failed_count,
                        metrics=health_report["metrics"]
                    )
            except (ImportError, AttributeError):
                pass

            return health_report

        except Exception as e:
            logger.error(f"Error monitoring scan health: {e}")
            return {
                "timestamp": datetime.now(UTC).isoformat(),
                "overall_status": "error",
                "error": str(e),
                "issues": [],
                "metrics": {},
                "alerts": []
            }

    async def _get_scan_data(self) -> Dict[str, Any]:
        """Get current scan data from agents graph."""
        try:
            from strix.tools.agents_graph.agents_graph_actions import (
                _agent_graph,
                _running_agents,
                _agent_instances,
                _recovery_attempts
            )

            # Collect agent data
            agents = []
            for agent_id, agent_node in _agent_graph.get("nodes", {}).items():
                agents.append({
                    "id": agent_id,
                    "name": agent_node.get("name", "Unknown"),
                    "status": agent_node.get("status", "unknown"),
                    "task": agent_node.get("task", ""),
                    "parent_id": agent_node.get("parent_id"),
                    "created_at": agent_node.get("created_at"),
                    "finished_at": agent_node.get("finished_at"),
                    "result": agent_node.get("result"),
                    "is_running": agent_id in _running_agents,
                    "retry_count": _recovery_attempts.get(agent_id, 0)
                })

            # Calculate summary statistics
            total_agents = len(agents)
            running_agents = [a for a in agents if a["status"] == "running"]
            completed_agents = [a for a in agents if a["status"] in ["completed", "finished"]]
            failed_agents = [a for a in agents if a["status"] in ["error", "failed"]]
            stuck_agents = [a for a in agents if a["status"] == "deadlocked"]

            return {
                "agents": agents,
                "summary": {
                    "total_agents": total_agents,
                    "running": len(running_agents),
                    "completed": len(completed_agents),
                    "failed": len(failed_agents),
                    "stuck": len(stuck_agents),
                    "recovery_attempts": sum(_recovery_attempts.values())
                },
                "scan_start_time": self._get_scan_start_time(agents),
                "last_activity": self._get_last_activity_time(agents)
            }

        except Exception as e:
            logger.warning(f"Error getting scan data: {e}")
            return {
                "agents": [],
                "summary": {
                    "total_agents": 0,
                    "running": 0,
                    "completed": 0,
                    "failed": 0,
                    "stuck": 0,
                    "recovery_attempts": 0
                },
                "scan_start_time": None,
                "last_activity": None
            }

    async def _check_stuck_agents(self, scan_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Check for agents that appear to be stuck."""
        issues = []
        current_time = datetime.now(UTC)
        stuck_threshold = timedelta(minutes=self.config["stuck_agent_minutes"])

        for agent in scan_data.get("agents", []):
            if agent["status"] != "running":
                continue

            # Check last activity time
            created_at = agent.get("created_at")
            if not created_at:
                continue

            try:
                created_time = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
                time_since_creation = current_time - created_time

                if time_since_creation > stuck_threshold:
                    issues.append({
                        "type": "stuck_agent",
                        "severity": "warning",
                        "agent_id": agent["id"],
                        "agent_name": agent["name"],
                        "task": agent["task"],
                        "stuck_duration_minutes": time_since_creation.total_seconds() / 60,
                        "message": f"Agent '{agent['name']}' has been running for {time_since_creation.total_seconds() / 60:.1f} minutes without completion",
                        "suggested_action": "Consider manual intervention or agent restart"
                    })

            except (ValueError, TypeError) as e:
                logger.warning(f"Error parsing created_at for agent {agent['id']}: {e}")

        return issues

    async def _check_failure_rates(self, scan_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Check for high failure rates."""
        issues = []
        summary = scan_data.get("summary", {})
        total_agents = summary.get("total_agents", 0)
        failed_agents = summary.get("failed", 0)

        if total_agents == 0:
            return issues

        failure_rate = (failed_agents / total_agents) * 100
        threshold = self.config["failure_rate_percent"]

        if failure_rate > threshold:
            severity = "critical" if failure_rate > threshold * 1.5 else "warning"
            issues.append({
                "type": "high_failure_rate",
                "severity": severity,
                "failure_rate_percent": failure_rate,
                "failed_agents": failed_agents,
                "total_agents": total_agents,
                "threshold_percent": threshold,
                "message": f"High failure rate detected: {failure_rate:.1f}% ({failed_agents}/{total_agents} agents failed)",
                "suggested_action": "Review failed agents and check for systematic issues"
            })

        return issues

    async def _check_scan_progress(self, scan_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Check for stalled scan progress."""
        issues = []
        current_time = datetime.now(UTC)

        last_activity = scan_data.get("last_activity")
        if not last_activity:
            return issues

        try:
            last_activity_time = datetime.fromisoformat(last_activity.replace('Z', '+00:00'))
            stall_threshold = timedelta(minutes=self.config["scan_progress_stall_minutes"])
            time_since_activity = current_time - last_activity_time

            if time_since_activity > stall_threshold:
                issues.append({
                    "type": "scan_progress_stall",
                    "severity": "warning",
                    "stall_duration_minutes": time_since_activity.total_seconds() / 60,
                    "last_activity": last_activity,
                    "message": f"Scan progress appears stalled: no activity for {time_since_activity.total_seconds() / 60:.1f} minutes",
                    "suggested_action": "Check if scan is complete or if manual intervention is needed"
                })

        except (ValueError, TypeError) as e:
            logger.warning(f"Error parsing last_activity time: {e}")

        return issues

    async def _generate_metrics(self, scan_data: Dict[str, Any]) -> Dict[str, Any]:
        """Generate health metrics from scan data."""
        summary = scan_data.get("summary", {})
        agents = scan_data.get("agents", [])

        # Calculate additional metrics
        total_agents = summary.get("total_agents", 0)
        running = summary.get("running", 0)
        completed = summary.get("completed", 0)
        failed = summary.get("failed", 0)

        completion_rate = (completed / total_agents * 100) if total_agents > 0 else 0
        failure_rate = (failed / total_agents * 100) if total_agents > 0 else 0

        # Calculate scan duration
        scan_duration = None
        scan_start = scan_data.get("scan_start_time")
        if scan_start:
            try:
                start_time = datetime.fromisoformat(scan_start.replace('Z', '+00:00'))
                scan_duration = (datetime.now(UTC) - start_time).total_seconds()
            except (ValueError, TypeError):
                pass

        # Agent retry statistics
        retry_counts = [a.get("retry_count", 0) for a in agents]
        avg_retries = sum(retry_counts) / len(retry_counts) if retry_counts else 0

        return {
            "total_agents": total_agents,
            "running_agents": running,
            "completed_agents": completed,
            "failed_agents": failed,
            "completion_rate_percent": round(completion_rate, 2),
            "failure_rate_percent": round(failure_rate, 2),
            "scan_duration_seconds": scan_duration,
            "recovery_attempts": summary.get("recovery_attempts", 0),
            "average_retries_per_agent": round(avg_retries, 2),
            "health_check_time": datetime.now(UTC).isoformat()
        }

    async def _generate_alerts(self, issues: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Generate alerts from identified issues."""
        alerts = []

        for issue in issues:
            alert = {
                "id": f"alert_{datetime.now(UTC).strftime('%Y%m%d_%H%M%S')}_{issue['type']}",
                "type": issue["type"],
                "severity": issue["severity"],
                "title": self._get_alert_title(issue),
                "message": issue["message"],
                "suggested_action": issue.get("suggested_action", "Manual review required"),
                "timestamp": datetime.now(UTC).isoformat(),
                "data": issue
            }
            alerts.append(alert)

        return alerts

    def _get_alert_title(self, issue: Dict[str, Any]) -> str:
        """Generate alert title based on issue type."""
        issue_type = issue["type"]
        severity = issue["severity"].upper()

        if issue_type == "stuck_agent":
            return f"{severity}: Agent Stuck"
        elif issue_type == "high_failure_rate":
            return f"{severity}: High Failure Rate"
        elif issue_type == "scan_progress_stall":
            return f"{severity}: Scan Progress Stalled"
        else:
            return f"{severity}: Scan Health Issue"

    async def _send_alerts(self, alerts: List[Dict[str, Any]]) -> None:
        """Send alerts through configured channels (local-only: log + file)."""
        enabled_channels = self.config.get("alert_channels", [])

        for alert in alerts:
            for channel in enabled_channels:
                try:
                    if channel == "log":
                        await self._send_log_alert(alert)
                    elif channel == "file":
                        await self._send_file_alert(alert)
                    else:
                        logger.warning(
                            f"Alert channel '{channel}' is not supported in this build "
                            "(only 'log' and 'file' are available)."
                        )

                except Exception as e:
                    logger.error(f"Failed to send alert via {channel}: {e}")

    async def _send_log_alert(self, alert: Dict[str, Any]) -> None:
        """Send alert to logger."""
        severity = alert["severity"]
        title = alert["title"]
        message = alert["message"]

        if severity == "critical":
            logger.critical(f"SCAN ALERT - {title}: {message}")
        elif severity == "warning":
            logger.warning(f"SCAN ALERT - {title}: {message}")
        else:
            logger.info(f"SCAN ALERT - {title}: {message}")

    async def _send_file_alert(self, alert: Dict[str, Any]) -> None:
        """Send alert to file."""
        try:
            alert_file = Path("scan_alerts.log")
            timestamp = alert["timestamp"]
            title = alert["title"]
            message = alert["message"]

            with alert_file.open("a") as f:
                f.write(f"{timestamp} [{alert['severity'].upper()}] {title}: {message}\n")

        except Exception as e:
            logger.error(f"Failed to write alert to file: {e}")

    def _get_scan_start_time(self, agents: List[Dict[str, Any]]) -> Optional[str]:
        """Get the earliest agent creation time as scan start."""
        if not agents:
            return None

        created_times = []
        for agent in agents:
            created_at = agent.get("created_at")
            if created_at:
                try:
                    created_times.append(datetime.fromisoformat(created_at.replace('Z', '+00:00')))
                except (ValueError, TypeError):
                    continue

        if created_times:
            return min(created_times).isoformat()
        return None

    def _get_last_activity_time(self, agents: List[Dict[str, Any]]) -> Optional[str]:
        """Get the most recent activity time across all agents."""
        if not agents:
            return None

        latest_time = None

        for agent in agents:
            # Check created_at and finished_at times
            for time_field in ["created_at", "finished_at"]:
                time_str = agent.get(time_field)
                if not time_str:
                    continue

                try:
                    time_obj = datetime.fromisoformat(time_str.replace('Z', '+00:00'))
                    if latest_time is None or time_obj > latest_time:
                        latest_time = time_obj
                except (ValueError, TypeError):
                    continue

        return latest_time.isoformat() if latest_time else None


# Convenience function for quick health checks
async def check_scan_health(config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Perform a quick scan health check.

    Args:
        config: Optional monitoring configuration

    Returns:
        Health report dictionary
    """
    monitor = ScanHealthMonitor(config)
    return await monitor.monitor_scan_health()