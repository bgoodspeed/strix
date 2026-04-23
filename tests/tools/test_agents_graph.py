"""Tests for agents_graph subagent dispatch — briefing, role plumbing, default history behavior."""

from __future__ import annotations

import threading
from typing import Any, ClassVar

import pytest

from strix.agents.state import AgentState
from strix.tools.agents_graph import agents_graph_actions


class _StubAgent:
    """Stand-in for StrixAgent that captures the config it was built with and never runs."""

    instances: ClassVar[list[_StubAgent]] = []

    def __init__(self, config: dict[str, Any]) -> None:
        self.config = config
        self.llm_config = config.get("llm_config")
        self.state = config.get("state")
        self.non_interactive = config.get("non_interactive", True)
        _StubAgent.instances.append(self)

    async def agent_loop(self, _task: str) -> dict[str, Any]:
        return {"status": "stub"}


@pytest.fixture(autouse=True)
def _reset_graph_state(monkeypatch: pytest.MonkeyPatch) -> None:
    """Reset module-level dicts and stub StrixAgent + threading so create_agent is testable."""
    _StubAgent.instances = []

    # LLMConfig requires a model to be configured; use a dummy litellm-compatible name.
    monkeypatch.setenv("STRIX_LLM", "openai/gpt-4o-mini")

    monkeypatch.setattr(agents_graph_actions, "_agent_graph", {"nodes": {}, "edges": []})
    monkeypatch.setattr(agents_graph_actions, "_agent_messages", {})
    monkeypatch.setattr(agents_graph_actions, "_running_agents", {})
    monkeypatch.setattr(agents_graph_actions, "_agent_instances", {})
    monkeypatch.setattr(agents_graph_actions, "_agent_states", {})

    # Route the deferred `from strix.agents import StrixAgent` import inside create_agent
    # to our stub by injecting it into the already-imported module namespace.
    import strix.agents as strix_agents_module

    monkeypatch.setattr(strix_agents_module, "StrixAgent", _StubAgent, raising=True)

    # Prevent the created agent from actually running: replace Thread with one that never starts.
    class _NoopThread:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            self.args = args
            self.kwargs = kwargs
            self.started = False

        def start(self) -> None:
            self.started = True

    monkeypatch.setattr(threading, "Thread", _NoopThread)


def _make_parent_state(history: list[dict[str, Any]] | None = None) -> AgentState:
    state = AgentState(agent_name="Parent", task="parent task")
    for msg in history or []:
        state.add_message(msg["role"], msg["content"])
    return state


def _get_child_thread_args(parent_state: AgentState) -> tuple[Any, ...]:
    """Pull the args that _run_agent_in_thread would have been invoked with.

    threading.Thread is called with args=(...) as a kwarg in create_agent, so
    read from kwargs, not positional args on the stub.
    """
    running = agents_graph_actions._running_agents
    assert running, "expected a child thread to have been registered"
    child_id = next(iter(running))
    thread = running[child_id]
    return thread.kwargs["args"]  # type: ignore[no-any-return]


def test_create_agent_defaults_to_no_history_inheritance() -> None:
    parent = _make_parent_state(
        [
            {"role": "user", "content": "find XSS"},
            {"role": "assistant", "content": "on it"},
        ]
    )

    result = agents_graph_actions.create_agent(
        agent_state=parent, task="scope the login form", name="XSS Scout"
    )

    assert result["success"] is True
    _, _, inherited, _ = _get_child_thread_args(parent)
    assert inherited == [], "default behavior must NOT inherit parent conversation history"


def test_create_agent_inherit_context_true_preserves_history() -> None:
    parent = _make_parent_state(
        [
            {"role": "user", "content": "find XSS"},
            {"role": "assistant", "content": "on it"},
        ]
    )

    result = agents_graph_actions.create_agent(
        agent_state=parent,
        task="scope the login form",
        name="XSS Scout",
        inherit_context=True,
    )

    assert result["success"] is True
    _, _, inherited, _ = _get_child_thread_args(parent)
    assert len(inherited) == 2
    assert inherited[0]["content"] == "find XSS"


def test_create_agent_passes_briefing_through_to_thread() -> None:
    parent = _make_parent_state()

    result = agents_graph_actions.create_agent(
        agent_state=parent,
        task="t",
        name="child",
        briefing="Target: /login; prior: none; artifact: /workspace/findings/xss/001.md",
    )

    assert result["success"] is True
    _, _, inherited, briefing = _get_child_thread_args(parent)
    assert inherited == []
    assert briefing is not None
    assert "001.md" in briefing


def test_create_agent_role_plumbs_to_llm_config() -> None:
    parent = _make_parent_state()

    result = agents_graph_actions.create_agent(
        agent_state=parent, task="t", name="Recon", role="recon"
    )

    assert result["success"] is True
    assert result["agent_info"]["role"] == "recon"
    assert _StubAgent.instances, "StrixAgent should have been constructed"
    assert _StubAgent.instances[-1].llm_config.role == "recon"


def test_create_agent_typed_role_auto_adds_skill() -> None:
    parent = _make_parent_state()

    result = agents_graph_actions.create_agent(
        agent_state=parent, task="t", name="XSS Hunter", role="vuln-xss"
    )

    assert result["success"] is True
    skills = _StubAgent.instances[-1].llm_config.skills
    assert "xss" in skills, f"vuln-xss role should auto-add 'xss' skill; got {skills!r}"


def test_create_agent_typed_role_does_not_duplicate_explicit_skill() -> None:
    parent = _make_parent_state()

    result = agents_graph_actions.create_agent(
        agent_state=parent,
        task="t",
        name="XSS Hunter",
        role="vuln-xss",
        skills="xss",
    )

    assert result["success"] is True
    skills = _StubAgent.instances[-1].llm_config.skills
    assert skills.count("xss") == 1


def test_create_agent_rejects_unknown_role() -> None:
    parent = _make_parent_state()

    result = agents_graph_actions.create_agent(
        agent_state=parent, task="t", name="bogus", role="made-up"
    )

    assert result["success"] is False
    assert "Invalid role" in result["error"]


def test_run_agent_in_thread_injects_briefing_as_single_message() -> None:
    """_run_agent_in_thread should wrap briefing as one <parent_briefing> message,
    not unroll it the way inherited_messages would."""
    child_state = AgentState(agent_name="child", parent_id="parent_123", task="t")
    # Register a dummy parent node so parent_name lookup succeeds.
    agents_graph_actions._agent_graph["nodes"]["parent_123"] = {
        "name": "Parent",
        "status": "running",
    }
    # Register child node so the function's status/finished_at writes don't KeyError.
    agents_graph_actions._agent_graph["nodes"][child_state.agent_id] = {
        "name": "child",
        "status": "running",
    }

    class _NoopAgent:
        async def agent_loop(self, _task: str) -> dict[str, Any]:
            return {"ok": True}

    agents_graph_actions._run_agent_in_thread(
        _NoopAgent(),
        child_state,
        inherited_messages=[],
        briefing="Briefing body",
    )

    briefing_messages = [
        m for m in child_state.messages if str(m.get("content", "")).startswith("<parent_briefing>")
    ]
    assert len(briefing_messages) == 1
    assert "Briefing body" in briefing_messages[0]["content"]
    # And no inherited_context wrapper should have been injected.
    assert not any(
        "<inherited_context_from_parent>" in str(m.get("content", "")) for m in child_state.messages
    )


def test_role_skill_map_covers_all_typed_roles() -> None:
    """Every vuln-* and exploit-* role in the validator set should have a skill mapping."""
    typed_roles = {
        r for r in agents_graph_actions._VALID_ROLES if r.startswith(("vuln-", "exploit-"))
    }
    assert typed_roles <= set(
        agents_graph_actions._ROLE_SKILL_MAP
    ), "every typed role should map to a skill"
