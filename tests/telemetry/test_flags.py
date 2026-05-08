from strix.telemetry.flags import is_otel_enabled


def test_otel_falls_back_to_strix_telemetry(monkeypatch) -> None:
    monkeypatch.delenv("STRIX_OTEL_TELEMETRY", raising=False)
    monkeypatch.setenv("STRIX_TELEMETRY", "0")

    assert is_otel_enabled() is False


def test_otel_flag_overrides_global_telemetry(monkeypatch) -> None:
    monkeypatch.setenv("STRIX_TELEMETRY", "0")
    monkeypatch.setenv("STRIX_OTEL_TELEMETRY", "1")

    assert is_otel_enabled() is True
