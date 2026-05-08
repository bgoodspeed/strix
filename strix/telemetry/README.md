### Overview

This local fork of Strix has had its non-local telemetry stripped out:

- **PostHog** usage telemetry: removed entirely.
- **OpenTelemetry remote export** (Traceloop / OTLP-HTTP): removed entirely.
- **Scan-health webhook / Slack alerts**: removed entirely.

OpenTelemetry spans are still produced — but they are written to a local
`events.jsonl` file inside the run directory via a `JsonlSpanExporter`.
Nothing is sent off-host.

### How to Opt Out

```bash
export STRIX_TELEMETRY=0
```

Disables local OpenTelemetry span emission as well (only a thin set of
manually-emitted JSONL events will still be written).
