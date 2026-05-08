"""`strix doctor` — pre-flight sanity checks.

Each check returns a CheckResult with a one-line summary and, when failing,
a copy-pasteable shell command that fixes the problem. The command exits
non-zero if any check fails.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess  # nosec B404
from dataclasses import dataclass
from typing import Callable

from rich.console import Console

from strix.config import Config


@dataclass
class CheckResult:
    name: str
    ok: bool
    summary: str
    fix: str | None = None
    detail: str | None = None


def _which(cmd: str) -> str | None:
    return shutil.which(cmd)


_PROVIDER_API_KEY_VARS = (
    "LLM_API_KEY",
    "ANTHROPIC_API_KEY",
    "OPENAI_API_KEY",
    "AZURE_API_KEY",
    "GEMINI_API_KEY",
    "GOOGLE_API_KEY",
    "GROQ_API_KEY",
    "MISTRAL_API_KEY",
    "TOGETHER_API_KEY",
    "DEEPSEEK_API_KEY",
)


def check_llm_env() -> CheckResult:
    model = Config.get("strix_llm")
    if not model:
        return CheckResult(
            name="LLM environment",
            ok=False,
            summary="STRIX_LLM not set",
            fix="export STRIX_LLM='anthropic/claude-sonnet-4-5'  # or your provider/model",
        )

    found_key = next((var for var in _PROVIDER_API_KEY_VARS if os.getenv(var)), None)
    if not found_key:
        return CheckResult(
            name="LLM environment",
            ok=False,
            summary=(
                f"STRIX_LLM={model} but no API key in env "
                f"(checked: {', '.join(_PROVIDER_API_KEY_VARS)})"
            ),
            fix=(
                "export LLM_API_KEY='sk-...'   # generic strix alias\n"
                "# or set the provider-specific var litellm expects, e.g.\n"
                "# export ANTHROPIC_API_KEY='sk-ant-...'  /  export OPENAI_API_KEY='sk-...'"
            ),
        )

    return CheckResult(
        name="LLM environment",
        ok=True,
        summary=f"STRIX_LLM={model}, {found_key} set",
    )


def check_docker_cli() -> CheckResult:
    if _which("docker") is None:
        return CheckResult(
            name="Docker CLI",
            ok=False,
            summary="`docker` not on PATH",
            fix="# Install Docker Desktop (https://docs.docker.com/get-docker/) or colima.",
        )
    return CheckResult(name="Docker CLI", ok=True, summary="docker CLI present")


def check_docker_daemon() -> CheckResult:
    try:
        result = subprocess.run(  # nosec B603 B607
            ["docker", "info", "--format", "{{.ServerVersion}}"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as e:
        return CheckResult(
            name="Docker daemon",
            ok=False,
            summary=f"could not reach Docker: {type(e).__name__}",
            fix="# Start Docker Desktop, or run: colima start",
        )

    if result.returncode != 0:
        return CheckResult(
            name="Docker daemon",
            ok=False,
            summary="`docker info` failed",
            fix="# Start Docker Desktop, or run: colima start",
            detail=result.stderr.strip() or result.stdout.strip(),
        )
    return CheckResult(
        name="Docker daemon",
        ok=True,
        summary=f"server version {result.stdout.strip()}",
    )


def _strix_image() -> str:
    return Config.get("strix_image") or "ghcr.io/usestrix/strix-sandbox:0.1.12"


def check_sandbox_image() -> CheckResult:
    image = _strix_image()
    try:
        result = subprocess.run(  # nosec B603 B607
            ["docker", "image", "inspect", image],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as e:
        return CheckResult(
            name="Sandbox image",
            ok=False,
            summary=f"could not query Docker for `{image}`: {type(e).__name__}",
            fix=f"docker pull {image}",
        )

    if result.returncode != 0:
        return CheckResult(
            name="Sandbox image",
            ok=False,
            summary=f"image `{image}` not present locally",
            fix=(
                f"docker pull {image}\n"
                "# Or, if you've patched containers/Dockerfile:\n"
                "docker build -t strix-sandbox:local -f containers/Dockerfile . && "
                "export STRIX_IMAGE=strix-sandbox:local"
            ),
        )

    return CheckResult(
        name="Sandbox image",
        ok=True,
        summary=f"`{image}` present locally",
    )


def _host_tool_names() -> list[str]:
    """Tool names registered in this (host) Python process."""
    from strix.tools import get_tool_names

    return sorted(get_tool_names())


def _host_sandbox_tool_names() -> list[str]:
    """Subset of host-registered tools that would be proxied to the sandbox.

    Tools registered with `sandbox_execution=False` (orchestration tools like
    create_agent, todo/notes management, finish_scan, etc.) run host-side and
    are *expected* to be missing from the sandbox image — they shouldn't appear
    in the parity diff.
    """
    from strix.tools import tools  # noqa: PLC0415

    return sorted(
        str(entry["name"])
        for entry in tools
        if entry.get("sandbox_execution", True)
    )


def _sandbox_tool_names(image: str) -> tuple[list[str] | None, str | None]:
    """Run a one-shot container against the sandbox image to dump its tool names.

    Returns (names, error) — exactly one is non-None.
    """
    script = (
        "import os; os.environ['STRIX_SANDBOX_MODE']='true'; "
        "import json; "
        "from strix.tools import get_tool_names; "
        "print(json.dumps(sorted(get_tool_names())))"
    )
    try:
        result = subprocess.run(  # nosec B603 B607
            [
                "docker",
                "run",
                "--rm",
                "--entrypoint",
                "python",
                image,
                "-c",
                script,
            ],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as e:
        return None, f"{type(e).__name__}: {e}"

    if result.returncode != 0:
        stderr = result.stderr.strip() or result.stdout.strip()
        return None, stderr or f"docker run exited {result.returncode}"

    last_line = result.stdout.strip().splitlines()[-1] if result.stdout.strip() else ""
    try:
        parsed = json.loads(last_line)
    except json.JSONDecodeError as e:
        return None, f"could not parse tool list: {e}"
    if not isinstance(parsed, list):
        return None, f"unexpected tool list shape: {type(parsed).__name__}"
    return [str(item) for item in parsed], None


def check_tool_registry_parity() -> CheckResult:
    """Diff sandbox-bound host tools against what the sandbox image actually carries.

    We compare only the tools the host *would* proxy to the sandbox; orchestration
    tools (sandbox_execution=False) live exclusively on the host and shouldn't
    flag this check.
    """
    image = _strix_image()
    host = _host_sandbox_tool_names()
    sandbox, err = _sandbox_tool_names(image)

    if err is not None:
        return CheckResult(
            name="Tool registry parity",
            ok=False,
            summary=f"could not introspect sandbox image: {err}",
            fix=(
                f"docker pull {image}\n"
                "# If the image exists but introspection fails, the image is too old "
                "to support `strix doctor`."
            ),
        )

    sandbox_set = set(sandbox or [])
    host_only = [t for t in host if t not in sandbox_set]

    if host_only:
        return CheckResult(
            name="Tool registry parity",
            ok=False,
            summary=(
                f"{len(host_only)} sandbox-bound tool(s) missing from "
                f"`{image}`: {', '.join(host_only)}"
            ),
            fix=(
                "# Rebuild the sandbox image so it carries the missing tools:\n"
                "docker build -t strix-sandbox:local -f containers/Dockerfile .\n"
                "export STRIX_IMAGE=strix-sandbox:local"
            ),
            detail=(
                f"sandbox-bound host tools: {len(host)}; sandbox tools: {len(sandbox or [])}"
            ),
        )

    return CheckResult(
        name="Tool registry parity",
        ok=True,
        summary=(
            f"{len(host)} sandbox-bound tools all present in `{image}` "
            f"(sandbox image carries {len(sandbox_set)} total)"
        ),
    )


CHECKS: list[Callable[[], CheckResult]] = [
    check_llm_env,
    check_docker_cli,
    check_docker_daemon,
    check_sandbox_image,
    check_tool_registry_parity,
]


def run() -> int:
    """Run all checks; print results; return shell exit code."""
    console = Console()
    console.print("[bold]strix doctor[/bold] — pre-flight checks\n")

    results: list[CheckResult] = []
    skip_remaining = False

    for check in CHECKS:
        if skip_remaining and check.__name__ in (
            "check_sandbox_image",
            "check_tool_registry_parity",
        ):
            results.append(
                CheckResult(
                    name=check.__name__.replace("check_", "").replace("_", " ").title(),
                    ok=False,
                    summary="skipped (Docker not available)",
                )
            )
            continue
        result = check()
        results.append(result)
        if (
            check.__name__ in ("check_docker_cli", "check_docker_daemon")
            and not result.ok
        ):
            skip_remaining = True

    failed = 0
    for r in results:
        marker = "[green]✓[/green]" if r.ok else "[red]✗[/red]"
        console.print(f"  {marker} [bold]{r.name}[/bold] — {r.summary}")
        if r.detail:
            console.print(f"      [dim]{r.detail}[/dim]")
        if not r.ok:
            failed += 1
            if r.fix:
                console.print("      [yellow]fix:[/yellow]")
                for line in r.fix.splitlines():
                    console.print(f"        [cyan]{line}[/cyan]")

    console.print()
    if failed:
        console.print(
            f"[red]{failed} check(s) failed.[/red] Run the suggested fix(es) above."
        )
        return 1

    console.print("[green]All checks passed.[/green]")
    return 0


def main() -> None:
    raise SystemExit(run())
