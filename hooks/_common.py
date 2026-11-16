"""Shared by the hook scripts: find the rstate package and the project root."""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "skills" / "research-state" / "scripts"))


def project_root(payload):
    """The directory holding research/ for this call, or None when there is none."""
    env = os.environ.get("CLAUDE_PROJECT_DIR")
    if env and (Path(env) / "research").is_dir():
        return Path(env)
    cwd = payload.get("cwd") if isinstance(payload, dict) else None
    if isinstance(cwd, str) and cwd and os.path.isdir(cwd):
        from rstate import paths
        return paths.locate(cwd)
    return None
