from strix.config.config import Config


def test_telemetry_vars_are_tracked() -> None:
    tracked = Config.tracked_vars()

    assert "STRIX_TELEMETRY" in tracked
    assert "STRIX_OTEL_TELEMETRY" in tracked


def test_remote_telemetry_vars_are_not_tracked() -> None:
    """Traceloop / posthog / webhook config has been removed — must not reappear."""
    tracked = Config.tracked_vars()

    for removed in (
        "TRACELOOP_BASE_URL",
        "TRACELOOP_API_KEY",
        "TRACELOOP_HEADERS",
        "STRIX_POSTHOG_TELEMETRY",
        "STRIX_RECOVERY_WEBHOOK_URL",
        "STRIX_RECOVERY_SLACK_WEBHOOK_URL",
    ):
        assert removed not in tracked, f"{removed} should have been removed"
