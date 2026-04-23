"""Tests for role-scoped system prompt rendering in StrixAgent."""

from __future__ import annotations

import pytest
from jinja2 import Environment, FileSystemLoader, TemplateNotFound, select_autoescape

from strix.utils.resource_paths import get_strix_resource_path


# First-wave role prompts that must exist and render without the monolith's escalation language.
# Roles kept silent on GO-SUPER-HARD / 2000+ steps framing:
_QUIET_ROLES = ("recon", "pre-recon", "report")
# Roles where the escalation framing is still apt (discovery / exploit phases):
_ESCALATING_ROLES = ("vuln", "exploit")

_ESCALATION_SUBSTRINGS = ("GO SUPER HARD", "2000+ steps")


@pytest.fixture
def jinja_env() -> Environment:
    prompt_dir = get_strix_resource_path("agents", "StrixAgent")
    skills_dir = get_strix_resource_path("skills")
    env = Environment(
        loader=FileSystemLoader([str(prompt_dir), str(skills_dir)]),
        autoescape=select_autoescape(enabled_extensions=(), default_for_string=False),
    )
    # Stub the globals the templates expect.
    env.globals["get_tools_prompt"] = lambda: "<tools_placeholder/>"
    env.globals["get_skill"] = lambda _name: ""
    return env


def _render(env: Environment, template_name: str) -> str:
    template = env.get_template(template_name)
    return template.render(loaded_skill_names=[])


@pytest.mark.parametrize("role", [*_QUIET_ROLES, *_ESCALATING_ROLES])
def test_role_prompt_renders_non_empty(jinja_env: Environment, role: str) -> None:
    content = _render(jinja_env, f"system_prompt_{role}.jinja")
    assert content.strip(), f"role prompt for {role!r} must not be empty"
    # Must include identity + communication fragments.
    assert "You are Strix" in content
    assert "<communication_rules>" in content


@pytest.mark.parametrize("role", _QUIET_ROLES)
def test_quiet_roles_lack_escalation_language(jinja_env: Environment, role: str) -> None:
    content = _render(jinja_env, f"system_prompt_{role}.jinja")
    for needle in _ESCALATION_SUBSTRINGS:
        assert (
            needle not in content
        ), f"{role!r} prompt should NOT contain escalation language {needle!r}"


@pytest.mark.parametrize("role", _ESCALATING_ROLES)
def test_escalating_roles_retain_escalation_language(jinja_env: Environment, role: str) -> None:
    """vuln and exploit agents are the ones intended to push hard; keep the framing there."""
    content = _render(jinja_env, f"system_prompt_{role}.jinja")
    # Don't pin on every substring — just confirm at least one escalation phrase survived.
    assert any(
        needle in content for needle in _ESCALATION_SUBSTRINGS
    ), f"{role!r} prompt unexpectedly dropped all escalation framing"


def test_monolith_still_renders(jinja_env: Environment) -> None:
    content = _render(jinja_env, "system_prompt.jinja")
    assert "You are Strix" in content
    assert (
        "STRUCTURED HANDOFFS" in content
    ), "monolith should teach the orchestrator about the new briefing/role pattern"


def test_template_selection_prefers_exact_then_phase_then_monolith() -> None:
    """Simulate LLM._select_prompt_template logic against the real template dir."""
    from strix.llm.llm import LLM

    prompt_dir = get_strix_resource_path("agents", "StrixAgent")
    skills_dir = get_strix_resource_path("skills")
    env = Environment(
        loader=FileSystemLoader([str(prompt_dir), str(skills_dir)]),
        autoescape=select_autoescape(enabled_extensions=(), default_for_string=False),
    )
    env.globals["get_tools_prompt"] = lambda: ""
    env.globals["get_skill"] = lambda _name: ""

    def _select(role: str | None) -> str:
        llm = LLM.__new__(LLM)
        llm.config = _ConfigWithRole(role)  # type: ignore[attr-defined]
        template = llm._select_prompt_template(env)
        return template.name  # type: ignore[no-any-return]

    # Exact match: recon
    assert _select("recon") == "system_prompt_recon.jinja"
    # Phase-level fallback: vuln-xss has no dedicated file (yet), falls back to
    # system_prompt_vuln.jinja
    assert _select("vuln-xss") == "system_prompt_vuln.jinja"
    # Exploit-class fallback: exploit-ssrf → system_prompt_exploit.jinja
    assert _select("exploit-ssrf") == "system_prompt_exploit.jinja"
    # Unknown role → monolith
    assert _select("definitely-not-a-role") == "system_prompt.jinja"
    # No role → monolith
    assert _select(None) == "system_prompt.jinja"


class _ConfigWithRole:
    """Minimal stand-in for LLMConfig in the select-template test (avoid touching env vars)."""

    def __init__(self, role: str | None) -> None:
        self.role = role


def test_all_first_wave_templates_exist(jinja_env: Environment) -> None:
    """Guard against someone deleting a role file without updating the plumbing."""
    for role in (*_QUIET_ROLES, *_ESCALATING_ROLES):
        try:
            jinja_env.get_template(f"system_prompt_{role}.jinja")
        except TemplateNotFound:  # pragma: no cover - failure path
            pytest.fail(f"missing first-wave role template for {role!r}")


def test_shared_fragments_exist(jinja_env: Environment) -> None:
    for fragment in (
        "_shared/_identity.jinja",
        "_shared/_communication.jinja",
        "_shared/_authorization.jinja",
        "_shared/_tool_format.jinja",
        "_shared/_environment_full.jinja",
        "_shared/_environment_recon.jinja",
        "_shared/_environment_reporting.jinja",
        "_shared/_vuln_focus.jinja",
        "_shared/_skills.jinja",
    ):
        try:
            jinja_env.get_template(fragment)
        except TemplateNotFound:  # pragma: no cover
            pytest.fail(f"missing shared fragment {fragment!r}")
