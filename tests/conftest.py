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
