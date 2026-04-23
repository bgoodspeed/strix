"""Tests for disk-based deliverables: write_deliverable, read_deliverable, list_deliverables."""

from __future__ import annotations

from pathlib import Path

import pytest

from strix.tools.deliverables import deliverables_actions


@pytest.fixture(autouse=True)
def _isolated_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point the deliverables root at an isolated tmp dir for each test."""
    root = tmp_path / "deliverables"
    monkeypatch.setattr(deliverables_actions, "DELIVERABLES_ROOT", root)
    return root


def test_write_creates_file_and_parent_dirs() -> None:
    result = deliverables_actions.write_deliverable(
        path="findings/xss/001.md", content="# XSS-001\nhello"
    )
    assert result["success"] is True
    written = Path(result["path"])
    assert written.exists()
    assert written.read_text() == "# XSS-001\nhello"
    assert result["bytes_written"] == len(b"# XSS-001\nhello")


def test_write_overwrites_existing_file() -> None:
    deliverables_actions.write_deliverable(path="recon/map.md", content="v1")
    result = deliverables_actions.write_deliverable(path="recon/map.md", content="v2")
    assert result["success"] is True
    assert Path(result["path"]).read_text() == "v2"


def test_write_rejects_leading_slash() -> None:
    """Absolute-style paths must be rejected to keep writes inside the root."""
    result = deliverables_actions.write_deliverable(path="/etc/passwd", content="x")
    assert result["success"] is False
    assert "Invalid" in result["error"]


def test_write_rejects_path_traversal() -> None:
    result = deliverables_actions.write_deliverable(path="../escape.md", content="x")
    assert result["success"] is False
    assert "Invalid" in result["error"]


def test_write_rejects_empty_path() -> None:
    result = deliverables_actions.write_deliverable(path="", content="x")
    assert result["success"] is False


def test_read_returns_content() -> None:
    deliverables_actions.write_deliverable(path="pocs/xss-search.md", content="poc body")
    result = deliverables_actions.read_deliverable(path="pocs/xss-search.md")
    assert result["success"] is True
    assert result["content"] == "poc body"


def test_read_missing_returns_error() -> None:
    result = deliverables_actions.read_deliverable(path="nope.md")
    assert result["success"] is False
    assert "not found" in result["error"].lower()


def test_read_rejects_path_traversal() -> None:
    result = deliverables_actions.read_deliverable(path="../../etc/passwd")
    assert result["success"] is False


def test_list_empty_when_root_missing() -> None:
    # Root hasn't been created yet.
    result = deliverables_actions.list_deliverables()
    assert result["success"] is True
    assert result["total_count"] == 0


def test_list_returns_all_with_previews() -> None:
    deliverables_actions.write_deliverable(
        path="recon/attack_surface.md",
        content="# Attack surface for example.com\n- www\n- api\n",
    )
    deliverables_actions.write_deliverable(
        path="findings/xss/001.md",
        content="# XSS-001: reflected in /search\ndetails...",
    )
    deliverables_actions.write_deliverable(
        path="findings/xss/002.md",
        content="# XSS-002: stored in /comments\ndetails...",
    )

    result = deliverables_actions.list_deliverables()
    assert result["success"] is True
    assert result["total_count"] == 3
    # Entries sorted by relative path.
    paths = [d["path"] for d in result["deliverables"]]
    assert paths == [
        "findings/xss/001.md",
        "findings/xss/002.md",
        "recon/attack_surface.md",
    ]
    # Preview should show the first-line heading stripped of leading '#'.
    xss_001 = next(d for d in result["deliverables"] if d["path"] == "findings/xss/001.md")
    assert xss_001["preview"].startswith("XSS-001")
    assert xss_001["size_bytes"] > 0


def test_list_filters_by_kind_prefix() -> None:
    deliverables_actions.write_deliverable(path="recon/map.md", content="# recon")
    deliverables_actions.write_deliverable(path="findings/xss/001.md", content="# xss 001")
    deliverables_actions.write_deliverable(path="findings/auth/001.md", content="# auth 001")

    scoped = deliverables_actions.list_deliverables(kind="findings/xss")
    assert scoped["success"] is True
    assert [d["path"] for d in scoped["deliverables"]] == ["findings/xss/001.md"]


def test_list_rejects_kind_with_traversal() -> None:
    result = deliverables_actions.list_deliverables(kind="../etc")
    assert result["success"] is False


def test_list_scoped_to_missing_dir_returns_empty() -> None:
    # Root exists but the kind subdir does not.
    deliverables_actions.write_deliverable(path="recon/map.md", content="x")
    result = deliverables_actions.list_deliverables(kind="findings/xss")
    assert result["success"] is True
    assert result["total_count"] == 0


def test_write_then_read_round_trip_with_unicode() -> None:
    payload = "# Report — impact: cookie exfil ✓\n<script>alert('ö')</script>"
    deliverables_actions.write_deliverable(path="reports/xss-001.md", content=payload)
    result = deliverables_actions.read_deliverable(path="reports/xss-001.md")
    assert result["success"] is True
    assert result["content"] == payload
