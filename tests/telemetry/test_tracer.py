import json
from pathlib import Path
from typing import Any

import pytest

from strix.telemetry import tracer as tracer_module
from strix.telemetry import utils as telemetry_utils
from strix.telemetry.tracer import Tracer, set_global_tracer


def _load_events(events_path: Path) -> list[dict[str, Any]]:
    lines = events_path.read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines if line]


@pytest.fixture(autouse=True)
def _reset_tracer_globals(monkeypatch) -> None:
    monkeypatch.setattr(tracer_module, "_global_tracer", None)
    monkeypatch.setattr(tracer_module, "_OTEL_BOOTSTRAPPED", False)
    telemetry_utils.reset_events_write_locks()
    monkeypatch.delenv("STRIX_TELEMETRY", raising=False)
    monkeypatch.delenv("STRIX_OTEL_TELEMETRY", raising=False)


def test_tracer_local_mode_writes_jsonl_with_correlation(monkeypatch, tmp_path) -> None:
    monkeypatch.chdir(tmp_path)

    tracer = Tracer("local-observability")
    set_global_tracer(tracer)
    tracer.set_scan_config({"targets": ["https://example.com"], "user_instructions": "focus auth"})
    tracer.log_agent_creation("agent-1", "Root Agent", "scan auth")
    tracer.log_chat_message("starting scan", "user", "agent-1")
    execution_id = tracer.log_tool_execution_start(
        "agent-1",
        "send_request",
        {"url": "https://example.com/login"},
    )
    tracer.update_tool_execution(execution_id, "completed", {"status_code": 200, "body": "ok"})

    events_path = tmp_path / "strix_runs" / "local-observability" / "events.jsonl"
    assert events_path.exists()

    events = _load_events(events_path)
    assert any(event["event_type"] == "tool.execution.updated" for event in events)
    assert not any(event["event_type"] == "traffic.intercepted" for event in events)

    for event in events:
        assert event["run_id"] == "local-observability"
        assert event["trace_id"]
        assert event["span_id"]


def test_tracer_redacts_sensitive_payloads(monkeypatch, tmp_path) -> None:
    monkeypatch.chdir(tmp_path)

    tracer = Tracer("redaction-run")
    set_global_tracer(tracer)
    execution_id = tracer.log_tool_execution_start(
        "agent-1",
        "send_request",
        {
            "url": "https://example.com",
            "api_key": "sk-secret-token-value",
            "authorization": "Bearer super-secret-token",
        },
    )
    tracer.update_tool_execution(
        execution_id,
        "error",
        {"error": "request failed with token sk-secret-token-value"},
    )

    events_path = tmp_path / "strix_runs" / "redaction-run" / "events.jsonl"
    events = _load_events(events_path)
    serialized = json.dumps(events)

    assert "sk-secret-token-value" not in serialized
    assert "super-secret-token" not in serialized
    assert "[REDACTED]" in serialized


def test_provider_setup_failure_does_not_mark_bootstrapped(monkeypatch, tmp_path) -> None:
    monkeypatch.chdir(tmp_path)

    def _raise_provider_error(provider: Any) -> None:  # noqa: ARG001
        raise RuntimeError("provider setup failed")

    monkeypatch.setattr(tracer_module.trace, "set_tracer_provider", _raise_provider_error)

    tracer = Tracer("bootstrap-failure")
    set_global_tracer(tracer)

    assert tracer_module._OTEL_BOOTSTRAPPED is False


def test_run_completed_event_emitted_once(monkeypatch, tmp_path) -> None:
    monkeypatch.chdir(tmp_path)

    tracer = Tracer("single-complete")
    set_global_tracer(tracer)
    tracer.save_run_data(mark_complete=True)
    tracer.save_run_data(mark_complete=True)

    events_path = tmp_path / "strix_runs" / "single-complete" / "events.jsonl"
    events = _load_events(events_path)
    run_completed = [event for event in events if event["event_type"] == "run.completed"]
    assert len(run_completed) == 1


def test_events_with_agent_id_include_agent_name(monkeypatch, tmp_path) -> None:
    monkeypatch.chdir(tmp_path)

    tracer = Tracer("agent-name-enrichment")
    set_global_tracer(tracer)
    tracer.log_agent_creation("agent-1", "Root Agent", "scan auth")
    tracer.log_chat_message("hello", "assistant", "agent-1")

    events_path = tmp_path / "strix_runs" / "agent-name-enrichment" / "events.jsonl"
    events = _load_events(events_path)
    chat_event = next(event for event in events if event["event_type"] == "chat.message")

    assert chat_event["actor"]["agent_id"] == "agent-1"
    assert chat_event["actor"]["agent_name"] == "Root Agent"


def test_run_metadata_is_only_on_run_lifecycle_events(monkeypatch, tmp_path) -> None:
    monkeypatch.chdir(tmp_path)

    tracer = Tracer("metadata-scope")
    set_global_tracer(tracer)
    tracer.log_chat_message("hello", "assistant", "agent-1")
    tracer.save_run_data(mark_complete=True)

    events_path = tmp_path / "strix_runs" / "metadata-scope" / "events.jsonl"
    events = _load_events(events_path)

    run_started = next(event for event in events if event["event_type"] == "run.started")
    run_completed = next(event for event in events if event["event_type"] == "run.completed")
    chat_event = next(event for event in events if event["event_type"] == "chat.message")

    assert "run_metadata" in run_started
    assert "run_metadata" in run_completed
    assert "run_metadata" not in chat_event


def test_set_run_name_resets_cached_paths(monkeypatch, tmp_path) -> None:
    monkeypatch.chdir(tmp_path)

    tracer = Tracer()
    set_global_tracer(tracer)
    old_events_path = tracer.events_file_path

    tracer.set_run_name("renamed-run")
    tracer.log_chat_message("hello", "assistant", "agent-1")

    new_events_path = tracer.events_file_path
    assert new_events_path != old_events_path
    assert new_events_path == tmp_path / "strix_runs" / "renamed-run" / "events.jsonl"

    events = _load_events(new_events_path)
    assert any(event["event_type"] == "run.started" for event in events)
    assert any(event["event_type"] == "chat.message" for event in events)


def test_set_run_name_resets_run_completed_flag(monkeypatch, tmp_path) -> None:
    monkeypatch.chdir(tmp_path)

    tracer = Tracer()
    set_global_tracer(tracer)

    tracer.save_run_data(mark_complete=True)
    tracer.set_run_name("renamed-complete")
    tracer.save_run_data(mark_complete=True)

    events_path = tmp_path / "strix_runs" / "renamed-complete" / "events.jsonl"
    events = _load_events(events_path)
    run_completed = [event for event in events if event["event_type"] == "run.completed"]

    assert any(event["event_type"] == "run.started" for event in events)
    assert len(run_completed) == 1


def test_events_write_locks_are_scoped_by_events_file(monkeypatch, tmp_path) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("STRIX_TELEMETRY", "0")

    tracer_one = Tracer("lock-run-a")
    tracer_two = Tracer("lock-run-b")

    lock_a_from_one = tracer_one._get_events_write_lock(tracer_one.events_file_path)
    lock_a_from_two = tracer_two._get_events_write_lock(tracer_one.events_file_path)
    lock_b = tracer_two._get_events_write_lock(tracer_two.events_file_path)

    assert lock_a_from_one is lock_a_from_two
    assert lock_a_from_one is not lock_b


def test_tracer_skips_jsonl_when_telemetry_disabled(monkeypatch, tmp_path) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("STRIX_TELEMETRY", "0")

    tracer = Tracer("telemetry-disabled")
    set_global_tracer(tracer)
    tracer.log_chat_message("hello", "assistant", "agent-1")
    tracer.save_run_data(mark_complete=True)

    events_path = tmp_path / "strix_runs" / "telemetry-disabled" / "events.jsonl"
    assert not events_path.exists()


def test_tracer_otel_flag_overrides_global_telemetry(monkeypatch, tmp_path) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("STRIX_TELEMETRY", "0")
    monkeypatch.setenv("STRIX_OTEL_TELEMETRY", "1")

    tracer = Tracer("otel-enabled")
    set_global_tracer(tracer)
    tracer.log_chat_message("hello", "assistant", "agent-1")
    tracer.save_run_data(mark_complete=True)

    events_path = tmp_path / "strix_runs" / "otel-enabled" / "events.jsonl"
    assert events_path.exists()


# ------------------------------------------------------------------
# Interim disk logging tests
# ------------------------------------------------------------------


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    lines = path.read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines if line.strip()]


def test_tool_log_written_on_tool_completion(monkeypatch, tmp_path) -> None:
    monkeypatch.chdir(tmp_path)

    tracer = Tracer("tool-log-run")
    set_global_tracer(tracer)
    tracer.log_agent_creation("agent-1", "Root Agent", "scan auth")

    eid = tracer.log_tool_execution_start(
        "agent-1", "send_request", {"url": "https://example.com/login", "method": "POST"}
    )
    tracer.update_tool_execution(eid, "completed", {"status_code": 200})

    log_dir = tmp_path / "strix_runs" / "tool-log-run" / "agents" / "agent-1_Root_Agent"
    log_file = log_dir / "tool_log.jsonl"
    assert log_file.exists()

    records = _load_jsonl(log_file)
    assert len(records) == 1
    assert records[0]["tool_name"] == "send_request"
    assert records[0]["args"]["url"] == "https://example.com/login"
    assert records[0]["status"] == "completed"
    assert records[0]["result"] == {"status_code": 200}
    assert records[0]["timestamp"]
    assert records[0]["started_at"]
    assert records[0]["completed_at"]


def test_tool_log_appends_multiple_executions(monkeypatch, tmp_path) -> None:
    monkeypatch.chdir(tmp_path)

    tracer = Tracer("multi-tool-run")
    set_global_tracer(tracer)
    tracer.log_agent_creation("agent-1", "Scanner", "scan target")

    for i in range(3):
        eid = tracer.log_tool_execution_start(
            "agent-1", f"tool_{i}", {"arg": f"val_{i}"}
        )
        tracer.update_tool_execution(eid, "completed", {"ok": True})

    log_file = (
        tmp_path / "strix_runs" / "multi-tool-run" / "agents" / "agent-1_Scanner" / "tool_log.jsonl"
    )
    records = _load_jsonl(log_file)
    assert len(records) == 3
    assert [r["tool_name"] for r in records] == ["tool_0", "tool_1", "tool_2"]


def test_tool_log_records_error_status(monkeypatch, tmp_path) -> None:
    monkeypatch.chdir(tmp_path)

    tracer = Tracer("error-tool-run")
    set_global_tracer(tracer)
    tracer.log_agent_creation("agent-1", "Agent", "task")

    eid = tracer.log_tool_execution_start("agent-1", "failing_tool", {"x": 1})
    tracer.update_tool_execution(eid, "error", "connection refused")

    log_file = (
        tmp_path / "strix_runs" / "error-tool-run" / "agents" / "agent-1_Agent" / "tool_log.jsonl"
    )
    records = _load_jsonl(log_file)
    assert len(records) == 1
    assert records[0]["status"] == "error"
    assert records[0]["result"] == "connection refused"


def test_tool_log_truncates_large_values(monkeypatch, tmp_path) -> None:
    monkeypatch.chdir(tmp_path)

    tracer = Tracer("truncate-run")
    set_global_tracer(tracer)
    tracer.log_agent_creation("agent-1", "Agent", "task")

    big_output = "x" * 5000
    eid = tracer.log_tool_execution_start("agent-1", "big_tool", {"code": big_output})
    tracer.update_tool_execution(eid, "completed", {"output": big_output})

    log_file = (
        tmp_path / "strix_runs" / "truncate-run" / "agents" / "agent-1_Agent" / "tool_log.jsonl"
    )
    records = _load_jsonl(log_file)
    assert len(records) == 1
    assert len(records[0]["args"]["code"]) < 5000
    assert "truncated" in records[0]["args"]["code"]
    assert len(records[0]["result"]["output"]) < 5000
    assert "truncated" in records[0]["result"]["output"]


def test_tool_log_per_agent_isolation(monkeypatch, tmp_path) -> None:
    monkeypatch.chdir(tmp_path)

    tracer = Tracer("isolation-run")
    set_global_tracer(tracer)
    tracer.log_agent_creation("agent-a", "Alpha", "task a")
    tracer.log_agent_creation("agent-b", "Beta", "task b")

    eid_a = tracer.log_tool_execution_start("agent-a", "tool_alpha", {})
    tracer.update_tool_execution(eid_a, "completed", {"from": "alpha"})

    eid_b = tracer.log_tool_execution_start("agent-b", "tool_beta", {})
    tracer.update_tool_execution(eid_b, "completed", {"from": "beta"})

    agents_dir = tmp_path / "strix_runs" / "isolation-run" / "agents"
    log_a = agents_dir / "agent-a_Alpha" / "tool_log.jsonl"
    log_b = agents_dir / "agent-b_Beta" / "tool_log.jsonl"

    assert log_a.exists()
    assert log_b.exists()

    records_a = _load_jsonl(log_a)
    records_b = _load_jsonl(log_b)
    assert len(records_a) == 1
    assert records_a[0]["tool_name"] == "tool_alpha"
    assert len(records_b) == 1
    assert records_b[0]["tool_name"] == "tool_beta"


def test_scan_progress_written_on_agent_creation(monkeypatch, tmp_path) -> None:
    monkeypatch.chdir(tmp_path)

    tracer = Tracer("progress-agent-create")
    set_global_tracer(tracer)
    tracer.log_agent_creation("agent-1", "Root Agent", "scan target")

    run_dir = tmp_path / "strix_runs" / "progress-agent-create"
    md_path = run_dir / "scan_progress.md"
    json_path = run_dir / "scan_status.json"

    assert md_path.exists()
    assert json_path.exists()

    md_content = md_path.read_text(encoding="utf-8")
    assert "# Scan Progress" in md_content
    assert "Root Agent" in md_content
    assert "running" in md_content

    status = json.loads(json_path.read_text(encoding="utf-8"))
    assert status["summary"]["total_agents"] == 1
    assert status["summary"]["running"] == 1
    assert status["agents"][0]["name"] == "Root Agent"


def test_scan_progress_updated_on_agent_completion(monkeypatch, tmp_path) -> None:
    monkeypatch.chdir(tmp_path)

    tracer = Tracer("progress-agent-complete")
    set_global_tracer(tracer)
    tracer.log_agent_creation("agent-1", "Root Agent", "scan target")
    tracer.update_agent_status("agent-1", "completed")

    json_path = tmp_path / "strix_runs" / "progress-agent-complete" / "scan_status.json"
    status = json.loads(json_path.read_text(encoding="utf-8"))
    assert status["summary"]["completed"] == 1
    assert status["summary"]["running"] == 0
    assert status["agents"][0]["status"] == "completed"


def test_scan_progress_not_updated_on_non_terminal_status(monkeypatch, tmp_path) -> None:
    monkeypatch.chdir(tmp_path)

    tracer = Tracer("progress-running-status")
    set_global_tracer(tracer)
    tracer.log_agent_creation("agent-1", "Root Agent", "scan target")

    md_path = tmp_path / "strix_runs" / "progress-running-status" / "scan_progress.md"
    mtime_after_create = md_path.stat().st_mtime_ns

    tracer.update_agent_status("agent-1", "running")

    mtime_after_running = md_path.stat().st_mtime_ns
    assert mtime_after_running == mtime_after_create


def test_scan_progress_includes_vulnerability_findings(monkeypatch, tmp_path) -> None:
    monkeypatch.chdir(tmp_path)

    tracer = Tracer("progress-vulns")
    set_global_tracer(tracer)
    tracer.log_agent_creation("agent-1", "Auth Tester", "test auth")

    tracer.add_vulnerability_report(
        title="SQL Injection in Login",
        severity="high",
        description="SQLi found",
        impact="auth bypass",
        target="https://example.com",
        technical_analysis="unsanitized input",
        poc_description="submit quote",
        poc_script_code="curl ...",
        remediation_steps="use parameterized queries",
    )

    run_dir = tmp_path / "strix_runs" / "progress-vulns"
    md_content = (run_dir / "scan_progress.md").read_text(encoding="utf-8")
    assert "SQL Injection in Login" in md_content
    assert "[HIGH]" in md_content
    assert "vuln-0001" in md_content

    status = json.loads((run_dir / "scan_status.json").read_text(encoding="utf-8"))
    assert status["summary"]["total_findings"] == 1
    assert status["findings"][0]["title"] == "SQL Injection in Login"
    assert status["findings"][0]["severity"] == "high"


def test_scan_progress_agent_tree_with_children(monkeypatch, tmp_path) -> None:
    monkeypatch.chdir(tmp_path)

    tracer = Tracer("progress-tree")
    set_global_tracer(tracer)
    tracer.log_agent_creation("root", "Root Agent", "coordinate scan")
    tracer.log_agent_creation("child-1", "Auth Specialist", "test auth", parent_id="root")
    tracer.log_agent_creation("child-2", "XSS Specialist", "test xss", parent_id="root")

    run_dir = tmp_path / "strix_runs" / "progress-tree"
    md_content = (run_dir / "scan_progress.md").read_text(encoding="utf-8")

    assert "Root Agent" in md_content
    assert "Auth Specialist" in md_content
    assert "XSS Specialist" in md_content

    status = json.loads((run_dir / "scan_status.json").read_text(encoding="utf-8"))
    assert status["summary"]["total_agents"] == 3
    assert status["agents"][1]["parent_id"] == "root"
    assert status["agents"][2]["parent_id"] == "root"


def test_scan_progress_tool_counts_exclude_internal_tools(monkeypatch, tmp_path) -> None:
    monkeypatch.chdir(tmp_path)

    tracer = Tracer("progress-tool-counts")
    set_global_tracer(tracer)
    tracer.log_agent_creation("agent-1", "Agent", "task")

    eid1 = tracer.log_tool_execution_start("agent-1", "scan_start_info", {})
    tracer.update_tool_execution(eid1, "completed", {})

    eid2 = tracer.log_tool_execution_start("agent-1", "send_request", {"url": "http://x"})
    tracer.update_tool_execution(eid2, "completed", {"ok": True})

    eid3 = tracer.log_tool_execution_start("agent-1", "execute_python", {"code": "1+1"})
    tracer.update_tool_execution(eid3, "completed", {"output": "2"})

    tracer.update_agent_status("agent-1", "completed")

    status = json.loads(
        (tmp_path / "strix_runs" / "progress-tool-counts" / "scan_status.json")
        .read_text(encoding="utf-8")
    )
    assert status["agents"][0]["tool_count"] == 2


def test_scan_progress_vulns_attributed_to_agent(monkeypatch, tmp_path) -> None:
    monkeypatch.chdir(tmp_path)

    tracer = Tracer("progress-vuln-attr")
    set_global_tracer(tracer)
    tracer.log_agent_creation("agent-1", "Auth Tester", "test auth")

    eid = tracer.log_tool_execution_start(
        "agent-1", "create_vulnerability_report", {"title": "SQLi"}
    )
    tracer.add_vulnerability_report(
        title="SQLi",
        severity="high",
        description="d",
        impact="i",
        target="t",
        technical_analysis="ta",
        poc_description="pd",
        poc_script_code="pc",
        remediation_steps="rs",
    )
    tracer.update_tool_execution(
        eid, "completed", {"success": True, "report_id": "vuln-0001"}
    )

    status = json.loads(
        (tmp_path / "strix_runs" / "progress-vuln-attr" / "scan_status.json")
        .read_text(encoding="utf-8")
    )
    agent = status["agents"][0]
    assert agent["finding_count"] == 1
    assert agent["findings"][0]["id"] == "vuln-0001"
    assert agent["findings"][0]["title"] == "SQLi"

    md_content = (
        tmp_path / "strix_runs" / "progress-vuln-attr" / "scan_progress.md"
    ).read_text(encoding="utf-8")
    assert "**Findings:** 1" in md_content


def test_scan_status_json_scan_completed_flag(monkeypatch, tmp_path) -> None:
    monkeypatch.chdir(tmp_path)

    tracer = Tracer("progress-completed-flag")
    set_global_tracer(tracer)
    tracer.log_agent_creation("agent-1", "Root", "task")

    status_path = tmp_path / "strix_runs" / "progress-completed-flag" / "scan_status.json"
    status = json.loads(status_path.read_text(encoding="utf-8"))
    assert status["scan_completed"] is False

    tracer.update_scan_final_fields(
        executive_summary="done",
        methodology="tested",
        technical_analysis="analyzed",
        recommendations="fix",
    )

    tracer.cleanup()

    status = json.loads(status_path.read_text(encoding="utf-8"))
    assert status["scan_completed"] is True


def test_scan_progress_written_on_cleanup(monkeypatch, tmp_path) -> None:
    monkeypatch.chdir(tmp_path)

    tracer = Tracer("progress-cleanup")
    set_global_tracer(tracer)
    tracer.log_agent_creation("agent-1", "Agent", "task")

    md_path = tmp_path / "strix_runs" / "progress-cleanup" / "scan_progress.md"
    md_path.unlink()

    tracer.cleanup()

    assert md_path.exists()
    md_content = md_path.read_text(encoding="utf-8")
    assert "Agent" in md_content


def test_safe_dir_name_sanitizes_special_characters() -> None:
    assert Tracer._safe_dir_name("Auth Specialist") == "Auth_Specialist"
    assert Tracer._safe_dir_name("test/slash\\back") == "testslashback"
    assert Tracer._safe_dir_name("multi   space") == "multi_space"
    assert Tracer._safe_dir_name("") == "agent"
    assert Tracer._safe_dir_name("!!!") == "agent"
    long_name = "a" * 100
    assert len(Tracer._safe_dir_name(long_name)) == 60


def test_truncate_value_handles_nested_structures() -> None:
    big = "x" * 3000
    result = Tracer._truncate_value({"key": big}, max_len=100)
    assert len(result["key"]) < 3000
    assert "truncated" in result["key"]

    big_list = list(range(50))
    result = Tracer._truncate_value(big_list)
    assert len(result) == 21
    assert "50 items total" in result[-1]

    assert Tracer._truncate_value(42) == 42
    assert Tracer._truncate_value(None) is None
    assert Tracer._truncate_value("short") == "short"


def test_format_elapsed() -> None:
    assert Tracer._format_elapsed(0) == "0s"
    assert Tracer._format_elapsed(45) == "45s"
    assert Tracer._format_elapsed(90) == "1m 30s"
    assert Tracer._format_elapsed(3661) == "1h 1m 1s"
