"""Tests for strix.interface.doctor.

The expensive checks (`check_sandbox_image`, `check_tool_registry_parity`) shell out to
`docker`. We don't want to require Docker to be installed/running for unit tests, so
those tests fully mock `subprocess.run`.
"""

from __future__ import annotations

import json
import subprocess
from types import SimpleNamespace
from unittest.mock import patch

from strix.interface import doctor


def _completed(stdout: str = "", stderr: str = "", returncode: int = 0):
    return SimpleNamespace(stdout=stdout, stderr=stderr, returncode=returncode)


def test_check_llm_env_missing_model(monkeypatch):
    monkeypatch.delenv("STRIX_LLM", raising=False)
    for var in doctor._PROVIDER_API_KEY_VARS:
        monkeypatch.delenv(var, raising=False)

    result = doctor.check_llm_env()

    assert result.ok is False
    assert "STRIX_LLM" in result.summary
    assert result.fix and "export STRIX_LLM=" in result.fix


def test_check_llm_env_missing_api_key(monkeypatch):
    monkeypatch.setenv("STRIX_LLM", "anthropic/claude-sonnet-4-5")
    for var in doctor._PROVIDER_API_KEY_VARS:
        monkeypatch.delenv(var, raising=False)

    result = doctor.check_llm_env()

    assert result.ok is False
    assert "no API key" in result.summary
    assert result.fix and "ANTHROPIC_API_KEY" in result.fix


def test_check_llm_env_accepts_provider_specific_key(monkeypatch):
    """Doctor should accept ANTHROPIC_API_KEY (etc.) as a valid LLM key."""
    monkeypatch.setenv("STRIX_LLM", "anthropic/claude-sonnet-4-5")
    for var in doctor._PROVIDER_API_KEY_VARS:
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-xxx")

    result = doctor.check_llm_env()

    assert result.ok is True
    assert "ANTHROPIC_API_KEY" in result.summary


def test_check_llm_env_present(monkeypatch):
    monkeypatch.setenv("STRIX_LLM", "openai/gpt-4")
    monkeypatch.setenv("LLM_API_KEY", "sk-test")

    result = doctor.check_llm_env()

    assert result.ok is True
    assert "openai/gpt-4" in result.summary


def test_check_docker_cli_missing(monkeypatch):
    monkeypatch.setattr(doctor, "_which", lambda _cmd: None)

    result = doctor.check_docker_cli()

    assert result.ok is False
    assert "not on PATH" in result.summary
    assert result.fix is not None


def test_check_docker_cli_present(monkeypatch):
    monkeypatch.setattr(doctor, "_which", lambda _cmd: "/usr/local/bin/docker")

    result = doctor.check_docker_cli()

    assert result.ok is True


def test_check_docker_daemon_unreachable(monkeypatch):
    def fake_run(*_args, **_kwargs):
        return _completed(stderr="Cannot connect to the Docker daemon", returncode=1)

    monkeypatch.setattr(doctor.subprocess, "run", fake_run)

    result = doctor.check_docker_daemon()

    assert result.ok is False
    assert "info` failed" in result.summary
    assert result.detail and "Cannot connect" in result.detail


def test_check_docker_daemon_running(monkeypatch):
    def fake_run(*_args, **_kwargs):
        return _completed(stdout="24.0.7\n", returncode=0)

    monkeypatch.setattr(doctor.subprocess, "run", fake_run)

    result = doctor.check_docker_daemon()

    assert result.ok is True
    assert "24.0.7" in result.summary


def test_check_sandbox_image_missing(monkeypatch):
    def fake_run(*_args, **_kwargs):
        return _completed(stderr="Error: No such image", returncode=1)

    monkeypatch.setattr(doctor.subprocess, "run", fake_run)

    result = doctor.check_sandbox_image()

    assert result.ok is False
    assert "not present" in result.summary
    assert result.fix is not None
    assert "docker pull" in result.fix


def test_check_sandbox_image_present(monkeypatch):
    def fake_run(*_args, **_kwargs):
        return _completed(stdout="[{}]", returncode=0)

    monkeypatch.setattr(doctor.subprocess, "run", fake_run)

    result = doctor.check_sandbox_image()

    assert result.ok is True


def test_check_tool_registry_parity_drift(monkeypatch):
    """Host has list_deliverables but sandbox image doesn't — must surface clearly."""
    monkeypatch.setattr(
        doctor,
        "_host_sandbox_tool_names",
        lambda: ["python_action", "list_deliverables", "terminal_execute"],
    )

    def fake_run(args, *_a, **_kw):
        # Only the tool-list dump uses `docker run --rm`; image inspect uses `inspect`.
        if "run" in args:
            return _completed(stdout=json.dumps(["python_action", "terminal_execute"]) + "\n")
        return _completed(stdout="[{}]", returncode=0)

    monkeypatch.setattr(doctor.subprocess, "run", fake_run)

    result = doctor.check_tool_registry_parity()

    assert result.ok is False
    assert "list_deliverables" in result.summary
    assert "missing" in result.summary
    assert result.fix is not None
    assert "docker build" in result.fix


def test_check_tool_registry_parity_aligned(monkeypatch):
    monkeypatch.setattr(
        doctor,
        "_host_sandbox_tool_names",
        lambda: ["python_action", "terminal_execute"],
    )

    def fake_run(args, *_a, **_kw):
        if "run" in args:
            return _completed(stdout=json.dumps(["python_action", "terminal_execute"]) + "\n")
        return _completed(stdout="[{}]", returncode=0)

    monkeypatch.setattr(doctor.subprocess, "run", fake_run)

    result = doctor.check_tool_registry_parity()

    assert result.ok is True


def test_host_sandbox_tool_names_excludes_orchestration_tools(monkeypatch):
    """Tools registered with sandbox_execution=False must NOT appear in the parity diff."""
    fake_tools = [
        {"name": "python_action", "sandbox_execution": True},
        {"name": "create_agent", "sandbox_execution": False},
        {"name": "finish_scan", "sandbox_execution": False},
        {"name": "terminal_execute", "sandbox_execution": True},
    ]
    monkeypatch.setattr("strix.tools.tools", fake_tools)

    names = doctor._host_sandbox_tool_names()

    assert names == ["python_action", "terminal_execute"]
    assert "create_agent" not in names
    assert "finish_scan" not in names


def test_check_tool_registry_parity_introspection_failure(monkeypatch):
    """When the sandbox image can't even respond, surface the docker error, not a diff."""
    monkeypatch.setattr(doctor, "_host_sandbox_tool_names", lambda: ["python_action"])

    def fake_run(args, *_a, **_kw):
        if "run" in args:
            return _completed(stderr="image not found", returncode=125)
        return _completed(stdout="[{}]", returncode=0)

    monkeypatch.setattr(doctor.subprocess, "run", fake_run)

    result = doctor.check_tool_registry_parity()

    assert result.ok is False
    assert "could not introspect" in result.summary


def test_run_aggregates_failures_and_returns_nonzero(monkeypatch):
    """A failing check should make `run()` return 1; a clean run should return 0."""
    monkeypatch.delenv("STRIX_LLM", raising=False)
    for var in doctor._PROVIDER_API_KEY_VARS:
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr(doctor, "_which", lambda _c: None)

    rc = doctor.run()

    assert rc == 1


def test_run_skips_image_checks_when_docker_missing(monkeypatch, capsys):
    monkeypatch.setenv("STRIX_LLM", "openai/gpt-4")
    monkeypatch.setenv("LLM_API_KEY", "sk-test")
    monkeypatch.setattr(doctor, "_which", lambda _c: None)

    rc = doctor.run()
    out = capsys.readouterr().out

    assert rc == 1
    assert "Docker CLI" in out
    assert "skipped" in out
