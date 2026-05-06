import threading
from datetime import UTC, datetime
from typing import Any, Literal

from strix.tools.registry import register_tool


_agent_graph: dict[str, Any] = {
    "nodes": {},
    "edges": [],
}

_root_agent_id: str | None = None

_agent_messages: dict[str, list[dict[str, Any]]] = {}

_running_agents: dict[str, threading.Thread] = {}

_agent_instances: dict[str, Any] = {}

_agent_states: dict[str, Any] = {}


def _run_agent_in_thread(
    agent: Any,
    state: Any,
    inherited_messages: list[dict[str, Any]],
    briefing: str | None = None,
) -> dict[str, Any]:
    try:
        if inherited_messages:
            state.add_message("user", "<inherited_context_from_parent>")
            for msg in inherited_messages:
                # Sanitize inherited content to remove immutable thinking blocks
                content = msg["content"]
                if isinstance(content, list):
                    # Filter out immutable thinking blocks
                    sanitized_content = []
                    for block in content:
                        if isinstance(block, dict):
                            block_type = block.get('type')
                            is_immutable = block.get('immutable', False)
                            # Skip immutable thinking/redacted blocks
                            if block_type in ['thinking', 'redacted_thinking'] and is_immutable:
                                continue
                            # Deep copy to avoid shared references
                            import copy
                            sanitized_content.append(copy.deepcopy(block))
                        else:
                            sanitized_content.append(block)
                    content = sanitized_content
                state.add_message(msg["role"], content)
            state.add_message("user", "</inherited_context_from_parent>")

        if briefing:
            state.add_message("user", f"<parent_briefing>\n{briefing}\n</parent_briefing>")

        parent_info = _agent_graph["nodes"].get(state.parent_id, {})
        parent_name = parent_info.get("name", "Unknown Parent")

        if inherited_messages:
            context_status = (
                "inherited conversation context from your parent for background understanding"
            )
        elif briefing:
            context_status = (
                "received a structured briefing from your parent (see <parent_briefing>)"
            )
        else:
            context_status = "started with a fresh context"

        task_xml = f"""<agent_delegation>
    <identity>
        ⚠️ You are NOT your parent agent. You are a NEW, SEPARATE sub-agent (not root).

        Your Info: {state.agent_name} ({state.agent_id})
        Parent Info: {parent_name} ({state.parent_id})
    </identity>

    <your_task>{state.task}</your_task>

    <instructions>
        - You have {context_status}
        - Inherited context is for BACKGROUND ONLY - don't continue parent's work
        - Maintain strict self-identity: never speak as or for your parent
        - Do not merge your conversation with the parent's;
        - Do not claim parent's actions or messages as your own
        - Focus EXCLUSIVELY on your delegated task above
        - Work independently with your own approach
        - Use agent_finish when complete to report back to parent
        - You are a SPECIALIST for this specific task
        - You share the same container as other agents but have your own tool server instance
        - All agents share /workspace directory and proxy history for better collaboration
        - You can see files created by other agents and proxy traffic from previous work
        - Build upon previous work but focus on your specific delegated task
    </instructions>
</agent_delegation>"""

        state.add_message("user", task_xml)

        _agent_states[state.agent_id] = state

        _agent_graph["nodes"][state.agent_id]["state"] = state.model_dump()

        import asyncio

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            result = loop.run_until_complete(agent.agent_loop(state.task))
        finally:
            loop.close()

    except Exception as e:
        _agent_graph["nodes"][state.agent_id]["status"] = "error"
        _agent_graph["nodes"][state.agent_id]["finished_at"] = datetime.now(UTC).isoformat()
        _agent_graph["nodes"][state.agent_id]["result"] = {"error": str(e)}
        _running_agents.pop(state.agent_id, None)
        _agent_instances.pop(state.agent_id, None)
        raise
    else:
        if state.stop_requested:
            _agent_graph["nodes"][state.agent_id]["status"] = "stopped"
        else:
            _agent_graph["nodes"][state.agent_id]["status"] = "completed"
        _agent_graph["nodes"][state.agent_id]["finished_at"] = datetime.now(UTC).isoformat()
        _agent_graph["nodes"][state.agent_id]["result"] = result
        _running_agents.pop(state.agent_id, None)
        _agent_instances.pop(state.agent_id, None)

        return {"result": result}


@register_tool(sandbox_execution=False)
def view_agent_graph(agent_state: Any) -> dict[str, Any]:
    try:
        structure_lines = ["=== AGENT GRAPH STRUCTURE ==="]

        def _build_tree(agent_id: str, depth: int = 0) -> None:
            node = _agent_graph["nodes"][agent_id]
            indent = "  " * depth

            you_indicator = " ← This is you" if agent_id == agent_state.agent_id else ""

            structure_lines.append(f"{indent}* {node['name']} ({agent_id}){you_indicator}")
            structure_lines.append(f"{indent}  Task: {node['task']}")
            structure_lines.append(f"{indent}  Status: {node['status']}")

            children = [
                edge["to"]
                for edge in _agent_graph["edges"]
                if edge["from"] == agent_id and edge["type"] == "delegation"
            ]

            if children:
                structure_lines.append(f"{indent}   Children:")
                for child_id in children:
                    _build_tree(child_id, depth + 2)

        root_agent_id = _root_agent_id
        if not root_agent_id and _agent_graph["nodes"]:
            for agent_id, node in _agent_graph["nodes"].items():
                if node.get("parent_id") is None:
                    root_agent_id = agent_id
                    break
            if not root_agent_id:
                root_agent_id = next(iter(_agent_graph["nodes"].keys()))

        if root_agent_id and root_agent_id in _agent_graph["nodes"]:
            _build_tree(root_agent_id)
        else:
            structure_lines.append("No agents in the graph yet")

        graph_structure = "\n".join(structure_lines)

        total_nodes = len(_agent_graph["nodes"])
        running_count = sum(
            1 for node in _agent_graph["nodes"].values() if node["status"] == "running"
        )
        waiting_count = sum(
            1 for node in _agent_graph["nodes"].values() if node["status"] == "waiting"
        )
        stopping_count = sum(
            1 for node in _agent_graph["nodes"].values() if node["status"] == "stopping"
        )
        completed_count = sum(
            1 for node in _agent_graph["nodes"].values() if node["status"] == "completed"
        )
        stopped_count = sum(
            1 for node in _agent_graph["nodes"].values() if node["status"] == "stopped"
        )
        failed_count = sum(
            1 for node in _agent_graph["nodes"].values() if node["status"] in ["failed", "error"]
        )

    except Exception as e:  # noqa: BLE001
        return {
            "error": f"Failed to view agent graph: {e}",
            "graph_structure": "Error retrieving graph structure",
        }
    else:
        return {
            "graph_structure": graph_structure,
            "summary": {
                "total_agents": total_nodes,
                "running": running_count,
                "waiting": waiting_count,
                "stopping": stopping_count,
                "completed": completed_count,
                "stopped": stopped_count,
                "failed": failed_count,
            },
        }


_ROLE_SKILL_MAP: dict[str, str] = {
    "vuln-injection": "sql_injection",
    "vuln-xss": "xss",
    "vuln-auth": "authentication_jwt",
    "vuln-authz": "broken_function_level_authorization",
    "vuln-ssrf": "ssrf",
    "exploit-injection": "sql_injection",
    "exploit-xss": "xss",
    "exploit-auth": "authentication_jwt",
    "exploit-authz": "broken_function_level_authorization",
    "exploit-ssrf": "ssrf",
}

_VALID_ROLES: set[str] = {
    "pre-recon",
    "recon",
    "vuln-injection",
    "vuln-xss",
    "vuln-auth",
    "vuln-authz",
    "vuln-ssrf",
    "exploit-injection",
    "exploit-xss",
    "exploit-auth",
    "exploit-authz",
    "exploit-ssrf",
    "report",
}


def _prepare_skill_list(
    skills: str | None, role: str | None
) -> tuple[list[str], dict[str, Any] | None]:
    """Validate role, build effective skill list. Returns (skills, error_response_or_None)."""
    skill_list: list[str] = []
    if skills:
        skill_list = [s.strip() for s in skills.split(",") if s.strip()]

    if role and role not in _VALID_ROLES:
        return skill_list, {
            "success": False,
            "error": f"Invalid role: {role!r}. Valid roles: {', '.join(sorted(_VALID_ROLES))}.",
            "agent_id": None,
        }

    if role and role in _ROLE_SKILL_MAP:
        from strix.skills import get_all_skill_names

        auto_skill = _ROLE_SKILL_MAP[role]
        if auto_skill in get_all_skill_names() and auto_skill not in skill_list:
            skill_list.insert(0, auto_skill)

    if len(skill_list) > 5:
        return skill_list, {
            "success": False,
            "error": "Cannot specify more than 5 skills for an agent (use comma-separated format)",
            "agent_id": None,
        }

    if skill_list:
        from strix.skills import get_all_skill_names, validate_skill_names

        validation = validate_skill_names(skill_list)
        if validation["invalid"]:
            available_skills = list(get_all_skill_names())
            return skill_list, {
                "success": False,
                "error": (
                    f"Invalid skills: {validation['invalid']}. "
                    f"Available skills: {', '.join(available_skills)}"
                ),
                "agent_id": None,
            }

    return skill_list, None


@register_tool(sandbox_execution=False)
def create_agent(
    agent_state: Any,
    task: str,
    name: str,
    inherit_context: bool = False,
    skills: str | None = None,
    briefing: str | None = None,
    role: str | None = None,
) -> dict[str, Any]:
    try:
        parent_id = agent_state.agent_id

        skill_list, error = _prepare_skill_list(skills, role)
        if error is not None:
            return error

        from strix.agents import StrixAgent
        from strix.agents.state import AgentState
        from strix.llm.config import LLMConfig

        state = AgentState(task=task, agent_name=name, parent_id=parent_id, max_iterations=300)

        parent_agent = _agent_instances.get(parent_id)

        timeout = None
        scan_mode = "deep"
        if parent_agent and hasattr(parent_agent, "llm_config"):
            if hasattr(parent_agent.llm_config, "timeout"):
                timeout = parent_agent.llm_config.timeout
            if hasattr(parent_agent.llm_config, "scan_mode"):
                scan_mode = parent_agent.llm_config.scan_mode

        llm_config = LLMConfig(skills=skill_list, timeout=timeout, scan_mode=scan_mode, role=role)
        # WORKAROUND: Disable thinking blocks for subagents until conversation corruption bug is fully resolved
        llm_config.enable_thinking = False

        agent_config = {
            "llm_config": llm_config,
            "state": state,
        }
        if parent_agent and hasattr(parent_agent, "non_interactive"):
            agent_config["non_interactive"] = parent_agent.non_interactive

        agent = StrixAgent(agent_config)

        inherited_messages: list[dict[str, Any]] = []
        if inherit_context:
            inherited_messages = agent_state.get_conversation_history()

        _agent_instances[state.agent_id] = agent

        thread = threading.Thread(
            target=_run_agent_in_thread,
            args=(agent, state, inherited_messages, briefing),
            daemon=True,
            name=f"Agent-{name}-{state.agent_id}",
        )
        thread.start()
        _running_agents[state.agent_id] = thread

    except Exception as e:  # noqa: BLE001
        return {"success": False, "error": f"Failed to create agent: {e}", "agent_id": None}
    else:
        return {
            "success": True,
            "agent_id": state.agent_id,
            "message": f"Agent '{name}' created and started asynchronously",
            "agent_info": {
                "id": state.agent_id,
                "name": name,
                "status": "running",
                "parent_id": parent_id,
                "role": role,
            },
        }


@register_tool(sandbox_execution=False)
def send_message_to_agent(
    agent_state: Any,
    target_agent_id: str,
    message: str,
    message_type: Literal["query", "instruction", "information"] = "information",
    priority: Literal["low", "normal", "high", "urgent"] = "normal",
) -> dict[str, Any]:
    try:
        if target_agent_id not in _agent_graph["nodes"]:
            return {
                "success": False,
                "error": f"Target agent '{target_agent_id}' not found in graph",
                "message_id": None,
            }

        sender_id = agent_state.agent_id

        from uuid import uuid4

        message_id = f"msg_{uuid4().hex[:8]}"
        message_data = {
            "id": message_id,
            "from": sender_id,
            "to": target_agent_id,
            "content": message,
            "message_type": message_type,
            "priority": priority,
            "timestamp": datetime.now(UTC).isoformat(),
            "delivered": False,
            "read": False,
        }

        if target_agent_id not in _agent_messages:
            _agent_messages[target_agent_id] = []

        _agent_messages[target_agent_id].append(message_data)

        _agent_graph["edges"].append(
            {
                "from": sender_id,
                "to": target_agent_id,
                "type": "message",
                "message_id": message_id,
                "message_type": message_type,
                "priority": priority,
                "created_at": datetime.now(UTC).isoformat(),
            }
        )

        message_data["delivered"] = True

        target_name = _agent_graph["nodes"][target_agent_id]["name"]
        sender_name = _agent_graph["nodes"][sender_id]["name"]

        return {
            "success": True,
            "message_id": message_id,
            "message": f"Message sent from '{sender_name}' to '{target_name}'",
            "delivery_status": "delivered",
            "target_agent": {
                "id": target_agent_id,
                "name": target_name,
                "status": _agent_graph["nodes"][target_agent_id]["status"],
            },
        }

    except Exception as e:  # noqa: BLE001
        return {"success": False, "error": f"Failed to send message: {e}", "message_id": None}


@register_tool(sandbox_execution=False)
def agent_finish(
    agent_state: Any,
    result_summary: str,
    findings: list[str] | None = None,
    success: bool = True,
    report_to_parent: bool = True,
    final_recommendations: list[str] | None = None,
) -> dict[str, Any]:
    try:
        if not hasattr(agent_state, "parent_id") or agent_state.parent_id is None:
            return {
                "agent_completed": False,
                "error": (
                    "This tool can only be used by subagents. "
                    "Root/main agents must use finish_scan instead."
                ),
                "parent_notified": False,
            }

        agent_id = agent_state.agent_id

        if agent_id not in _agent_graph["nodes"]:
            return {"agent_completed": False, "error": "Current agent not found in graph"}

        agent_node = _agent_graph["nodes"][agent_id]

        agent_node["status"] = "finished" if success else "failed"
        agent_node["finished_at"] = datetime.now(UTC).isoformat()
        agent_node["result"] = {
            "summary": result_summary,
            "findings": findings or [],
            "success": success,
            "recommendations": final_recommendations or [],
        }

        parent_notified = False

        if report_to_parent and agent_node["parent_id"]:
            parent_id = agent_node["parent_id"]

            if parent_id in _agent_graph["nodes"]:
                findings_xml = "\n".join(
                    f"        <finding>{finding}</finding>" for finding in (findings or [])
                )
                recommendations_xml = "\n".join(
                    f"        <recommendation>{rec}</recommendation>"
                    for rec in (final_recommendations or [])
                )

                report_message = f"""<agent_completion_report>
    <agent_info>
        <agent_name>{agent_node["name"]}</agent_name>
        <agent_id>{agent_id}</agent_id>
        <task>{agent_node["task"]}</task>
        <status>{"SUCCESS" if success else "FAILED"}</status>
        <completion_time>{agent_node["finished_at"]}</completion_time>
    </agent_info>
    <results>
        <summary>{result_summary}</summary>
        <findings>
{findings_xml}
        </findings>
        <recommendations>
{recommendations_xml}
        </recommendations>
    </results>
</agent_completion_report>"""

                if parent_id not in _agent_messages:
                    _agent_messages[parent_id] = []

                from uuid import uuid4

                _agent_messages[parent_id].append(
                    {
                        "id": f"report_{uuid4().hex[:8]}",
                        "from": agent_id,
                        "to": parent_id,
                        "content": report_message,
                        "message_type": "information",
                        "priority": "high",
                        "timestamp": datetime.now(UTC).isoformat(),
                        "delivered": True,
                        "read": False,
                    }
                )

                parent_notified = True

        _running_agents.pop(agent_id, None)

        return {
            "agent_completed": True,
            "parent_notified": parent_notified,
            "completion_summary": {
                "agent_id": agent_id,
                "agent_name": agent_node["name"],
                "task": agent_node["task"],
                "success": success,
                "findings_count": len(findings or []),
                "has_recommendations": bool(final_recommendations),
                "finished_at": agent_node["finished_at"],
            },
        }

    except Exception as e:  # noqa: BLE001
        return {
            "agent_completed": False,
            "error": f"Failed to complete agent: {e}",
            "parent_notified": False,
        }


def stop_agent(agent_id: str) -> dict[str, Any]:
    try:
        if agent_id not in _agent_graph["nodes"]:
            return {
                "success": False,
                "error": f"Agent '{agent_id}' not found in graph",
                "agent_id": agent_id,
            }

        agent_node = _agent_graph["nodes"][agent_id]

        if agent_node["status"] in ["completed", "error", "failed", "stopped"]:
            return {
                "success": True,
                "message": f"Agent '{agent_node['name']}' was already stopped",
                "agent_id": agent_id,
                "previous_status": agent_node["status"],
            }

        if agent_id in _agent_states:
            agent_state = _agent_states[agent_id]
            agent_state.request_stop()

        if agent_id in _agent_instances:
            agent_instance = _agent_instances[agent_id]
            if hasattr(agent_instance, "state"):
                agent_instance.state.request_stop()
            if hasattr(agent_instance, "cancel_current_execution"):
                agent_instance.cancel_current_execution()

        agent_node["status"] = "stopping"

        try:
            from strix.telemetry.tracer import get_global_tracer

            tracer = get_global_tracer()
            if tracer:
                tracer.update_agent_status(agent_id, "stopping")
        except (ImportError, AttributeError):
            pass

        agent_node["result"] = {
            "summary": "Agent stop requested by user",
            "success": False,
            "stopped_by_user": True,
        }

        return {
            "success": True,
            "message": f"Stop request sent to agent '{agent_node['name']}'",
            "agent_id": agent_id,
            "agent_name": agent_node["name"],
            "note": "Agent will stop gracefully after current iteration",
        }

    except Exception as e:  # noqa: BLE001
        return {
            "success": False,
            "error": f"Failed to stop agent: {e}",
            "agent_id": agent_id,
        }


def send_user_message_to_agent(agent_id: str, message: str) -> dict[str, Any]:
    try:
        if agent_id not in _agent_graph["nodes"]:
            return {
                "success": False,
                "error": f"Agent '{agent_id}' not found in graph",
                "agent_id": agent_id,
            }

        agent_node = _agent_graph["nodes"][agent_id]

        if agent_id not in _agent_messages:
            _agent_messages[agent_id] = []

        from uuid import uuid4

        message_data = {
            "id": f"user_msg_{uuid4().hex[:8]}",
            "from": "user",
            "to": agent_id,
            "content": message,
            "message_type": "instruction",
            "priority": "high",
            "timestamp": datetime.now(UTC).isoformat(),
            "delivered": True,
            "read": False,
        }

        _agent_messages[agent_id].append(message_data)

        return {
            "success": True,
            "message": f"Message sent to agent '{agent_node['name']}'",
            "agent_id": agent_id,
            "agent_name": agent_node["name"],
        }

    except Exception as e:  # noqa: BLE001
        return {
            "success": False,
            "error": f"Failed to send message to agent: {e}",
            "agent_id": agent_id,
        }


@register_tool(sandbox_execution=False)
def wait_for_message(
    agent_state: Any,
    reason: str = "Waiting for messages from other agents",
) -> dict[str, Any]:
    try:
        agent_id = agent_state.agent_id
        agent_name = agent_state.agent_name

        agent_state.enter_waiting_state()

        if agent_id in _agent_graph["nodes"]:
            _agent_graph["nodes"][agent_id]["status"] = "waiting"
            _agent_graph["nodes"][agent_id]["waiting_reason"] = reason

        try:
            from strix.telemetry.tracer import get_global_tracer

            tracer = get_global_tracer()
            if tracer:
                tracer.update_agent_status(agent_id, "waiting")
        except (ImportError, AttributeError):
            pass

    except Exception as e:  # noqa: BLE001
        return {"success": False, "error": f"Failed to enter waiting state: {e}", "status": "error"}
    else:
        return {
            "success": True,
            "status": "waiting",
            "message": f"Agent '{agent_name}' is now waiting for messages",
            "reason": reason,
            "agent_info": {
                "id": agent_id,
                "name": agent_name,
                "status": "waiting",
            },
            "resume_conditions": [
                "Message from another agent",
                "Message from user",
                "Direct communication",
                "Waiting timeout reached",
            ],
        }


# Agent recovery configuration - loaded from main Strix config
def _get_recovery_config() -> dict[str, Any]:
    """Get recovery configuration from Strix config with fallback defaults."""
    from strix.config.config import Config

    def get_bool(value: str) -> bool:
        return value.lower() in ('true', '1', 'yes', 'on')

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

    return {
        "retry_delay_seconds": get_int(Config.get("strix_recovery_retry_delay_seconds") or "300", 300),
        "max_retries": get_int(Config.get("strix_recovery_max_retries") or "3", 3),
        "deadlock_timeout_seconds": get_int(Config.get("strix_recovery_deadlock_timeout_seconds") or "1800", 1800),
        "enable_auto_recovery": get_bool(Config.get("strix_recovery_enable_auto_recovery") or "true"),
        "alert_thresholds": {
            "stuck_agent_minutes": get_int(Config.get("strix_recovery_stuck_agent_minutes") or "30", 30),
            "failure_rate_percent": get_float(Config.get("strix_recovery_failure_rate_percent") or "50", 50.0)
        }
    }

# Track recovery attempts
_recovery_attempts: dict[str, int] = {}
_last_recovery_check: datetime | None = None


def _monitor_and_recover_failed_agents() -> dict[str, Any]:
    """Periodically check for failed agents and attempt recovery.

    This function should be called periodically (e.g., every 5 minutes)
    from the root agent main loop to automatically recover failed agents.

    Returns:
        dict: Summary of recovery actions taken
    """
    global _last_recovery_check

    config = _get_recovery_config()
    if not config["enable_auto_recovery"]:
        return {"recovery_enabled": False, "message": "Auto-recovery is disabled"}

    current_time = datetime.now(UTC)
    _last_recovery_check = current_time

    recovery_actions = {
        "check_time": current_time.isoformat(),
        "agents_checked": 0,
        "failed_agents_found": 0,
        "recovery_attempts": 0,
        "successful_recoveries": 0,
        "skipped_max_retries": 0,
        "errors": []
    }

    try:
        for agent_id, agent_node in _agent_graph["nodes"].items():
            recovery_actions["agents_checked"] += 1

            # Check for failed agents
            status = agent_node.get("status")
            if status in ["error", "failed"]:
                recovery_actions["failed_agents_found"] += 1

                # Check if we should attempt recovery
                retry_count = _recovery_attempts.get(agent_id, 0)
                if retry_count >= config["max_retries"]:
                    recovery_actions["skipped_max_retries"] += 1
                    continue

                try:
                    result = _respawn_failed_agent(agent_id)
                    recovery_actions["recovery_attempts"] += 1

                    if result.get("success", False):
                        recovery_actions["successful_recoveries"] += 1

                        # Log recovery attempt to telemetry
                        try:
                            from strix.telemetry.tracer import get_global_tracer
                            tracer = get_global_tracer()
                            if tracer:
                                tracer.track_recovery_attempt(agent_id, retry_count + 1, True, recovery_type="automatic")
                        except (ImportError, AttributeError):
                            pass

                    else:
                        recovery_actions["errors"].append(f"Failed to recover agent {agent_id}: {result.get('error', 'Unknown error')}")

                except Exception as e:
                    recovery_actions["errors"].append(f"Exception recovering agent {agent_id}: {str(e)}")

            # Check for stuck agents (no activity for too long)
            elif status == "running":
                started_at = agent_node.get("started_at")
                if started_at:
                    try:
                        start_time = datetime.fromisoformat(started_at.replace('Z', '+00:00'))
                        minutes_running = (current_time - start_time).total_seconds() / 60

                        if minutes_running > config["deadlock_timeout_seconds"] / 60:
                            # Agent appears stuck - treat as failed
                            recovery_actions["failed_agents_found"] += 1

                            try:
                                result = _respawn_failed_agent(agent_id, fresh_context=True)
                                recovery_actions["recovery_attempts"] += 1

                                if result.get("success", False):
                                    recovery_actions["successful_recoveries"] += 1
                                else:
                                    recovery_actions["errors"].append(f"Failed to recover stuck agent {agent_id}: {result.get('error', 'Unknown error')}")
                            except Exception as e:
                                recovery_actions["errors"].append(f"Exception recovering stuck agent {agent_id}: {str(e)}")

                    except (ValueError, TypeError) as e:
                        recovery_actions["errors"].append(f"Error parsing start time for agent {agent_id}: {str(e)}")

        return recovery_actions

    except Exception as e:
        recovery_actions["errors"].append(f"Critical error in monitoring: {str(e)}")
        return recovery_actions


def _respawn_failed_agent(agent_id: str, fresh_context: bool = False) -> dict[str, Any]:
    """Create new agent to replace failed one.

    Args:
        agent_id: ID of the failed agent to replace
        fresh_context: If True, start with fresh context instead of inheriting

    Returns:
        dict: Result of the respawn attempt
    """
    try:
        if agent_id not in _agent_graph["nodes"]:
            return {
                "success": False,
                "error": f"Agent {agent_id} not found in graph",
                "new_agent_id": None
            }

        failed_agent = _agent_graph["nodes"][agent_id]

        # Increment retry count
        _recovery_attempts[agent_id] = _recovery_attempts.get(agent_id, 0) + 1
        retry_count = _recovery_attempts[agent_id]

        config = _get_recovery_config()
        if retry_count > config["max_retries"]:
            return {
                "success": False,
                "error": f"Max retries ({config['max_retries']}) exceeded for agent {agent_id}",
                "new_agent_id": None,
                "retry_count": retry_count
            }

        # Stop the failed agent if still running
        if agent_id in _running_agents:
            try:
                stop_agent(agent_id)
            except Exception as e:
                # Continue with recovery even if stop fails
                pass

        # Mark the old agent as recovered
        failed_agent["status"] = "replaced"
        failed_agent["finished_at"] = datetime.now(UTC).isoformat()
        failed_agent["result"] = {
            "summary": f"Agent failed and was automatically recovered (attempt {retry_count})",
            "success": False,
            "auto_recovered": True,
            "retry_count": retry_count
        }

        # Get parent agent for context
        parent_id = failed_agent.get("parent_id")
        if not parent_id:
            return {
                "success": False,
                "error": f"No parent found for failed agent {agent_id} - cannot recover root agents",
                "new_agent_id": None
            }

        # Prepare new agent parameters
        task = failed_agent.get("task", "Continue the work of the failed agent")
        name = f"{failed_agent.get('name', 'Unknown')}-recovery-{retry_count}"
        role = failed_agent.get("role")

        # Create briefing about the failure
        briefing = f"""RECOVERY BRIEFING:
You are a recovery agent replacing a failed agent.

Failed Agent Info:
- Original Agent: {failed_agent.get('name', 'Unknown')} ({agent_id})
- Original Task: {task}
- Failure Reason: {failed_agent.get('result', {}).get('error', 'Unknown error')}
- Retry Attempt: {retry_count}/{_RECOVERY_CONFIG['max_retries']}

Instructions:
1. Continue the work where the failed agent left off
2. Be aware that this is a recovery scenario - some context may be lost
3. Focus on completing the original task successfully
4. Report any persistent issues that might indicate systemic problems
"""

        # Find parent agent state for creating new agent
        parent_state = _agent_states.get(parent_id)
        if not parent_state:
            return {
                "success": False,
                "error": f"Parent agent state not found for {parent_id}",
                "new_agent_id": None
            }

        # Create replacement agent
        inherit_context = not fresh_context  # Inherit context unless specifically requested not to
        skills = None  # Will inherit from role if specified

        result = create_agent(
            agent_state=parent_state,
            task=task,
            name=name,
            inherit_context=inherit_context,
            skills=skills,
            briefing=briefing,
            role=role
        )

        if result.get("success", False):
            new_agent_id = result.get("agent_id")

            # Update the new agent's metadata to indicate it's a recovery
            if new_agent_id and new_agent_id in _agent_graph["nodes"]:
                new_node = _agent_graph["nodes"][new_agent_id]
                new_node["is_recovery"] = True
                new_node["replaces_agent_id"] = agent_id
                new_node["recovery_attempt"] = retry_count

            return {
                "success": True,
                "message": f"Successfully spawned recovery agent {name}",
                "new_agent_id": new_agent_id,
                "old_agent_id": agent_id,
                "retry_count": retry_count,
                "briefing_provided": True
            }
        else:
            return {
                "success": False,
                "error": f"Failed to create recovery agent: {result.get('error', 'Unknown error')}",
                "new_agent_id": None,
                "retry_count": retry_count
            }

    except Exception as e:
        return {
            "success": False,
            "error": f"Exception during agent recovery: {str(e)}",
            "new_agent_id": None,
            "retry_count": _recovery_attempts.get(agent_id, 0)
        }


@register_tool(sandbox_execution=False)
def check_and_recover_agents(agent_state: Any) -> dict[str, Any]:
    """Manual trigger for agent monitoring and recovery.

    This tool can be called by the root agent or administrators to manually
    trigger the agent recovery process.
    """
    try:
        result = _monitor_and_recover_failed_agents()

        # Format for user-friendly output
        summary = []
        if result["agents_checked"] > 0:
            summary.append(f"Checked {result['agents_checked']} agents")

        if result["failed_agents_found"] > 0:
            summary.append(f"Found {result['failed_agents_found']} failed/stuck agents")

        if result["recovery_attempts"] > 0:
            summary.append(f"Attempted {result['recovery_attempts']} recoveries")

        if result["successful_recoveries"] > 0:
            summary.append(f"Successfully recovered {result['successful_recoveries']} agents")

        if result["skipped_max_retries"] > 0:
            summary.append(f"Skipped {result['skipped_max_retries']} agents (max retries exceeded)")

        if result["errors"]:
            summary.append(f"Encountered {len(result['errors'])} errors")

        message = "; ".join(summary) if summary else "No recovery actions needed"

        return {
            "success": True,
            "message": message,
            "details": result,
            "recovery_config": _RECOVERY_CONFIG
        }

    except Exception as e:
        return {
            "success": False,
            "error": f"Failed to run recovery check: {str(e)}",
            "details": None
        }


def get_recovery_config() -> dict[str, Any]:
    """Get current recovery configuration."""
    return _get_recovery_config()


def update_recovery_config(config_updates: dict[str, Any]) -> dict[str, Any]:
    """Update recovery configuration through Strix config system.

    Args:
        config_updates: Dictionary of configuration values to update

    Returns:
        dict: Success status and updated configuration
    """
    try:
        from strix.config.config import Config

        # Map user-friendly keys to Strix config keys
        key_mapping = {
            "retry_delay_seconds": "strix_recovery_retry_delay_seconds",
            "max_retries": "strix_recovery_max_retries",
            "deadlock_timeout_seconds": "strix_recovery_deadlock_timeout_seconds",
            "enable_auto_recovery": "strix_recovery_enable_auto_recovery",
            "stuck_agent_minutes": "strix_recovery_stuck_agent_minutes",
            "failure_rate_percent": "strix_recovery_failure_rate_percent",
            "scan_progress_stall_minutes": "strix_recovery_scan_progress_stall_minutes",
            "alert_channels": "strix_recovery_alert_channels",
            "webhook_url": "strix_recovery_webhook_url",
            "slack_webhook_url": "strix_recovery_slack_webhook_url"
        }

        # Handle nested alert_thresholds
        flat_updates = {}
        for key, value in config_updates.items():
            if key == "alert_thresholds" and isinstance(value, dict):
                for sub_key, sub_value in value.items():
                    if sub_key in key_mapping:
                        flat_updates[sub_key] = sub_value
                    else:
                        flat_updates[f"alert_thresholds.{sub_key}"] = sub_value
            else:
                flat_updates[key] = value

        # Validate and convert keys
        env_updates = {}
        invalid_keys = []

        for key, value in flat_updates.items():
            if key in key_mapping:
                env_key = key_mapping[key].upper()
                env_updates[env_key] = str(value)
            else:
                invalid_keys.append(key)

        if invalid_keys:
            return {
                "success": False,
                "error": f"Invalid configuration keys: {invalid_keys}",
                "valid_keys": list(key_mapping.keys())
            }

        # Load current config and update
        current_config = Config.load()
        env_vars = current_config.get("env", {})
        env_vars.update(env_updates)

        # Save updated config
        updated_config = {"env": env_vars}
        success = Config.save(updated_config)

        if not success:
            return {
                "success": False,
                "error": "Failed to save configuration to file"
            }

        return {
            "success": True,
            "message": "Recovery configuration updated in Strix config",
            "updated_config": _get_recovery_config()
        }

    except Exception as e:
        return {
            "success": False,
            "error": f"Failed to update recovery configuration: {str(e)}"
        }
