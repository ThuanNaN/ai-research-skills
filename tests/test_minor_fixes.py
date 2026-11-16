"""Regressions for the minor findings deferred from the whole-branch review."""
import json
import os
import socket
import subprocess
import sys
from datetime import datetime, timedelta, timezone

import pytest

from conftest import cli, run_hook
from rstate import decisions, guard, plans, rules, runs, status

NOW = datetime(2026, 11, 16, 12, 0, tzinfo=timezone.utc)


def _rules(project, front):
    (project / "research/rules.md").write_text(f"---\n{front}\n---\n")


# --- rules.md that cannot be read -------------------------------------------

def test_rules_md_as_directory_is_a_rules_error(project):
    (project / "research/rules.md").mkdir()
    with pytest.raises(rules.RulesError):
        rules.load(project)


def test_guard_answers_instead_of_crashing_when_rules_md_is_a_directory(project):
    (project / "research/rules.md").mkdir()
    d = guard.decide("Bash", {"command": "ls"}, project, project)
    assert d.action == "deny" and "rules.md" in d.reason
    assert "rules.md" in status.session_context(project, now=NOW)


# --- front matter forms ------------------------------------------------------

def test_front_matter_accepts_empty_list_and_other_quote_styles():
    r = rules.parse(
        "---\nprotected_paths: []\n"
        "eval_only_paths:\n  - data/human_eval   # held out\n  - 'it''s here'\n"
        "train_command_patterns:\n  - train\\.py\n"
        'protected_processes: ["trainer", "eval_server"]\n---\n')
    assert r.protected_paths == []
    assert r.eval_only_paths == ["data/human_eval", "it's here"]
    assert r.train_command_patterns == ["train\\.py"]
    assert r.protected_processes == ["trainer", "eval_server"]


@pytest.mark.parametrize("front", ["protected_paths:\n  - 'open", "protected_paths: [1]", "protected_paths: [\"a\""])
def test_front_matter_still_rejects_broken_items(front):
    with pytest.raises(rules.RulesError):
        rules.parse(f"---\n{front}\n---\n")


# --- dirty flag in a monorepo subdirectory ----------------------------------

def test_git_dirty_ignores_research_when_project_is_a_subdirectory(project_no_research):
    repo = project_no_research
    sub = repo / "proj"
    (sub / "research").mkdir(parents=True)
    (sub / "code.py").write_text("x = 1\n")
    git = ["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@example.com"]
    subprocess.run([*git, "add", "proj/code.py"], check=True)
    subprocess.run([*git, "commit", "-q", "-m", "init"], check=True)
    (sub / "research/runs.jsonl").write_text("")
    assert runs.git_info(sub)[1] is False
    (sub / "code.py").write_text("x = 2\n")
    assert runs.git_info(sub)[1] is True


# --- plan hash scope ---------------------------------------------------------

def test_heading_that_only_starts_with_amendment_stays_in_the_hash(project):
    folder = project / "research/plans"
    folder.mkdir()
    p = folder / "rq1.md"
    p.write_text("# Plan\n\n## Amendment policy\n\nNo changes after freeze.\n")
    plans.freeze(project, "rq1", date="2026-11-16")
    p.write_text(p.read_text().replace("No changes", "Any changes"))
    assert plans.state(p) == "tampered"


def test_real_amendment_still_leaves_plan_frozen(project):
    folder = project / "research/plans"
    folder.mkdir()
    (folder / "rq1.md").write_text("# Plan\n\n## Amendment policy\n\nNone.\n")
    plans.freeze(project, "rq1", date="2026-11-16")
    plans.amend(project, "rq1", "extra seed", date="2026-11-17")
    assert plans.state(folder / "rq1.md") == "frozen"


# --- stale and dead detection -----------------------------------------------

def _write_runs(project, *records):
    (project / "research/runs.jsonl").write_text("".join(json.dumps(r) + "\n" for r in records))


def _running(project):
    return "\n".join(dict(status.sections(project, now=NOW)).get("Running", []))


def test_timestamp_with_offset_is_understood(project):
    _write_runs(project, {"run_id": "r1", "ts": "2026-11-16T18:30:00+07:00", "event": "started", "host": "elsewhere"})
    text = _running(project)
    assert "updated 30m ago" in text and "STALE" not in text


def test_stale_flag_states_the_age(project):
    _write_runs(project, {"run_id": "r1", "ts": "2026-11-14T12:00:00Z", "event": "started", "host": "elsewhere"})
    assert "STALE — no update for 48h" in _running(project)


def test_dead_pid_is_flagged_without_proc_and_with_a_qualified_hostname(project, monkeypatch):
    child = subprocess.Popen([sys.executable, "-c", "pass"])
    child.wait()
    monkeypatch.setattr(socket, "gethostname", lambda: "GPU1.lab.example.org")
    monkeypatch.setattr(os.path, "isdir", lambda p: False if str(p) == "/proc" else os.path.exists(p))
    _write_runs(project, {"run_id": "r1", "ts": "2026-11-16T11:00:00Z", "event": "started",
                          "host": "gpu1", "pid": child.pid})
    assert "PROCESS NOT FOUND" in _running(project)


def test_live_pid_is_not_flagged(project):
    _write_runs(project, {"run_id": "r1", "ts": "2026-11-16T11:00:00Z", "event": "started",
                          "host": socket.gethostname(), "pid": os.getpid()})
    assert "PROCESS NOT FOUND" not in _running(project)


def test_old_planned_run_is_flagged(project):
    _write_runs(project, {"run_id": "r1", "ts": "2026-11-10T12:00:00Z", "event": "planned", "cmd": "python train.py"},
                {"run_id": "r2", "ts": "2026-11-16T11:00:00Z", "event": "planned", "cmd": "python eval.py"})
    lines = dict(status.sections(project, now=NOW))["Awaiting your approval"]
    assert "STALE" in lines[0] and "STALE" not in lines[1]


# --- STATUS.md ---------------------------------------------------------------

def test_long_metric_values_are_cut(project):
    _write_runs(project, {"run_id": "r1", "ts": "2026-11-16T11:00:00Z", "event": "finished",
                          "metrics": {"note": "x" * 500, "acc": 0.5}})
    line = dict(status.sections(project, now=NOW))["Recently finished"][0]
    assert len(line) < 250 and "acc=0.5" in line


def test_status_md_summarises_the_rules(project):
    _rules(project, 'protected_paths:\n  - "out/**"')
    text = status.build(project, now=NOW)
    assert "## Rules" in text and "1 protected path pattern" in text
    assert text.count("## Rules") == 1 and "## Rules" not in status.session_context(project, now=NOW)


# --- session context size ----------------------------------------------------

def test_session_start_output_does_not_escape_non_ascii(project):
    (project / "research/rules.md").write_text("Không dùng dữ liệu đánh giá để huấn luyện.\n" * 100)
    proc = run_hook("session_start.py", {"cwd": str(project), "source": "startup"}, project)
    raw = proc.stdout
    assert "\\u" not in raw and "Không dùng" in raw
    assert len(raw) <= 10000
    assert "Không" in json.loads(raw)["hookSpecificOutput"]["additionalContext"]


# --- kill by pid -------------------------------------------------------------

def test_kill_pid_of_a_viewer_that_mentions_the_name_is_allowed(project, monkeypatch):
    _rules(project, 'protected_processes:\n  - "train.py"')
    monkeypatch.setattr(guard, "_cmdline", lambda pid: "tail -f logs/train.py.log")
    assert guard.decide("Bash", {"command": "kill 4242"}, project, project).action == "allow"
    monkeypatch.setattr(guard, "_cmdline", lambda pid: "/usr/bin/vim train.py")
    assert guard.decide("Bash", {"command": "kill 4242"}, project, project).action == "allow"


def test_kill_pid_of_the_protected_process_is_still_denied(project, monkeypatch):
    _rules(project, 'protected_processes:\n  - "train.py"')
    monkeypatch.setattr(guard, "_cmdline", lambda pid: "python train.py --seed 1")
    assert guard.decide("Bash", {"command": "kill 4242"}, project, project).action == "deny"


# --- CLI ---------------------------------------------------------------------

def test_nan_metric_is_written_as_valid_json(project):
    rid = cli(project, "run", "start", "--cmd", "python train.py").stdout.strip()
    cli(project, "run", "finish", "--id", rid, "--metric", "loss=nan", "--metric", "best=inf")
    for line in (project / "research/runs.jsonl").read_text().splitlines():
        rec = json.loads(line, parse_constant=lambda c: pytest.fail(f"bare {c} in runs.jsonl"))
    assert rec["metrics"] == {"loss": "nan", "best": "inf"}


def test_init_from_a_subdirectory_says_where_it_went(project_no_research):
    sub = project_no_research / "pkg"
    sub.mkdir()
    out = cli(project_no_research, "init", cwd=sub)
    assert (project_no_research / "research").is_dir() and not (sub / "research").exists()
    assert "--root" in out.stdout + out.stderr


def test_decisions_append_takes_the_lock(project, monkeypatch):
    import fcntl
    calls = []
    real = fcntl.flock
    monkeypatch.setattr(fcntl, "flock", lambda f, op: (calls.append(op), real(f, op))[1])
    decisions.append(project, "Use seed 3", "variance", date="2026-11-16")
    decisions.append(project, "Use seed 5", "more variance", date="2026-11-16")
    text = (project / "research/decisions.md").read_text()
    assert fcntl.LOCK_EX in calls and text.count("# Decisions") == 1 and text.count("## 2026-11-16") == 2
