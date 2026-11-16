import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
SCRIPTS = REPO / "skills" / "research-state" / "scripts"
sys.path.insert(0, str(SCRIPTS))


def _git_init(path):
    subprocess.run(["git", "init", "-q", str(path)], check=True)


@pytest.fixture(autouse=True)
def _repo_cwd(monkeypatch):
    monkeypatch.chdir(REPO)


@pytest.fixture
def project(tmp_path):
    _git_init(tmp_path)
    (tmp_path / "research").mkdir()
    return tmp_path


@pytest.fixture
def project_no_research(tmp_path):
    _git_init(tmp_path)
    return tmp_path


def cli(root, *args, cwd=None, check=True):
    """Run the research_state CLI inside a project directory."""
    proc = subprocess.run(
        [sys.executable, str(SCRIPTS / "research_state.py"), *args],
        cwd=str(cwd or root), capture_output=True, text=True)
    if check and proc.returncode != 0:
        raise AssertionError(f"cli {args} failed: {proc.stderr}")
    return proc


def run_hook(script, payload, project_dir):
    """Run a hook script with a JSON payload on stdin."""
    data = payload if isinstance(payload, str) else json.dumps(payload)
    env = {**os.environ, "CLAUDE_PROJECT_DIR": str(project_dir)}
    return subprocess.run(
        [sys.executable, str(REPO / "hooks" / script)],
        input=data, capture_output=True, text=True, env=env, cwd=str(project_dir))
