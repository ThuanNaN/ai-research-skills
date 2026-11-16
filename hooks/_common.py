"""Shared by the hook scripts: find the rstate package and the project root."""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "skills" / "research-state" / "scripts"))


def project_root(payload):
    """The directory holding research/, or None when this project has none."""
    candidates = []
    if os.environ.get("CLAUDE_PROJECT_DIR"):
        candidates.append(Path(os.environ["CLAUDE_PROJECT_DIR"]))
    cwd = payload.get("cwd") if isinstance(payload, dict) else None
    if cwd:
        start = Path(cwd)
        candidates.extend([start, *start.parents])
    for candidate in candidates:
        if (candidate / "research").is_dir():
            return candidate
    return None
