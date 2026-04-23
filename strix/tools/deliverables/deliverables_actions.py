"""Disk-based deliverables for cross-agent handoffs.

Agents write structured artifacts under /workspace/.strix/deliverables/<relative path>
instead of stuffing findings into the conversation. Downstream agents read them on demand.
This mirrors Shannon's .shannon/deliverables/ convention.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from strix.tools.registry import register_tool


DELIVERABLES_ROOT = Path("/workspace/.strix/deliverables")
_PREVIEW_CHARS = 160
_MAX_LIST_ENTRIES = 500


def _resolve_relative_path(relative_path: str) -> Path | None:
    """Normalize and validate a caller-supplied path; return None if it escapes the root."""
    if not relative_path or not relative_path.strip():
        return None
    cleaned = relative_path.strip()
    if cleaned.startswith(("/", "\\")):
        return None
    candidate = Path(cleaned)
    if candidate.is_absolute() or any(part == ".." for part in candidate.parts):
        return None
    return DELIVERABLES_ROOT / candidate


def _extract_preview(content: str) -> str:
    stripped = content.strip()
    if not stripped:
        return ""
    first_line = stripped.splitlines()[0].lstrip("# ").strip()
    if len(first_line) > _PREVIEW_CHARS:
        return first_line[: _PREVIEW_CHARS - 1] + "…"
    return first_line


@register_tool
def write_deliverable(path: str, content: str) -> dict[str, Any]:
    """Write a deliverable artifact under the shared deliverables root.

    `path` is interpreted relative to /workspace/.strix/deliverables/ — e.g. pass
    "recon/attack_surface.md" or "findings/xss/001.md". Overwrites any existing file
    at that path (use read + write to append).
    """
    full = _resolve_relative_path(path)
    if full is None:
        return {
            "success": False,
            "error": (
                "Invalid deliverable path. Use a relative path such as "
                "'recon/attack_surface.md' (no leading / or .. segments)."
            ),
            "path": None,
        }
    if content is None:
        return {"success": False, "error": "content is required", "path": None}
    try:
        full.parent.mkdir(parents=True, exist_ok=True)
        full.write_text(content, encoding="utf-8")
    except OSError as e:
        return {"success": False, "error": f"Failed to write deliverable: {e}", "path": None}
    return {
        "success": True,
        "path": str(full),
        "bytes_written": len(content.encode("utf-8")),
    }


@register_tool
def read_deliverable(path: str) -> dict[str, Any]:
    """Read a deliverable artifact. `path` is relative to the deliverables root."""
    full = _resolve_relative_path(path)
    if full is None:
        return {"success": False, "error": "Invalid deliverable path.", "content": None}
    if not full.exists():
        return {
            "success": False,
            "error": f"Deliverable not found at {full}",
            "content": None,
        }
    if not full.is_file():
        return {"success": False, "error": f"Not a file: {full}", "content": None}
    try:
        content = full.read_text(encoding="utf-8")
    except OSError as e:
        return {"success": False, "error": f"Failed to read deliverable: {e}", "content": None}
    return {"success": True, "path": str(full), "content": content}


@register_tool
def list_deliverables(kind: str | None = None) -> dict[str, Any]:
    """List deliverables under the shared root, optionally filtered by a kind prefix.

    `kind` is a path prefix — e.g. "findings", "findings/xss", "recon". Returns
    each matching file with its relative path, size in bytes, and a short preview
    (first line, stripped of leading '#'s).
    """
    search_root = DELIVERABLES_ROOT
    if kind:
        scoped = _resolve_relative_path(kind)
        if scoped is None:
            return {
                "success": False,
                "error": "Invalid kind filter (no leading / or .. segments).",
                "deliverables": [],
                "total_count": 0,
            }
        if not scoped.exists():
            return {
                "success": True,
                "deliverables": [],
                "total_count": 0,
                "root": str(DELIVERABLES_ROOT),
            }
        # If caller passed a full relative path by accident, use it as-is (list covers one file).
        search_root = scoped

    if not DELIVERABLES_ROOT.exists():
        return {"success": True, "deliverables": [], "total_count": 0}

    entries: list[dict[str, Any]] = []
    try:
        iterable = search_root.rglob("*") if search_root.is_dir() else [search_root]
        for item in iterable:
            if not item.is_file():
                continue
            try:
                text = item.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                text = ""
            rel = item.relative_to(DELIVERABLES_ROOT)
            entries.append(
                {
                    "path": str(rel),
                    "absolute_path": str(item),
                    "size_bytes": item.stat().st_size,
                    "preview": _extract_preview(text),
                }
            )
            if len(entries) >= _MAX_LIST_ENTRIES:
                break
    except OSError as e:
        return {
            "success": False,
            "error": f"Failed to walk deliverables: {e}",
            "deliverables": [],
            "total_count": 0,
        }

    entries.sort(key=lambda e: e["path"])
    return {
        "success": True,
        "deliverables": entries,
        "total_count": len(entries),
        "root": str(DELIVERABLES_ROOT),
    }
