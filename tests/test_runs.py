import re
import socket

import pytest

from rstate.runs import append_event, git_info, load


def test_started_autofills_and_merges(project):
    a = append_event(project, "started", cmd="python train.py", seed=7, rq="RQ1", pid=123)
    assert re.fullmatch(r"r\d{8}-001", a["run_id"])
    assert a["host"] == socket.gethostname() and a["git_dirty"] is False
    append_event(project, "finished", run_id=a["run_id"], metrics={"sr": 0.34})
    runs, bad = load(project)
    r = runs[a["run_id"]]
    assert (r["status"], r["cmd"], r["seed"], r["metrics"], bad) == ("finished", "python train.py", 7, {"sr": 0.34}, 0)


def test_run_ids_count_up_within_a_day(project):
    a = append_event(project, "started", cmd="a")
    b = append_event(project, "planned", cmd="b")
    assert int(b["run_id"][-3:]) == int(a["run_id"][-3:]) + 1


def test_dirty_ignores_research_dir(project):
    (project / "research/decisions.md").write_text("x")
    assert git_info(project)[1] is False
    (project / "train.py").write_text("x")
    assert git_info(project)[1] is True


def test_explicit_remote_fields_win(project):
    a = append_event(project, "started", host="gpu-box", git_commit="abc123", cwd="/remote/repo")
    assert (a["host"], a["git_commit"], a["cwd"]) == ("gpu-box", "abc123", "/remote/repo")


def test_not_a_git_repo(tmp_path):
    (tmp_path / "research").mkdir()
    a = append_event(tmp_path, "started", cmd="x")
    assert a["git_commit"] is None and a["git_dirty"] is None


def test_corrupt_lines_are_skipped_and_counted(project):
    a = append_event(project, "started", cmd="x")
    with open(project / "research/runs.jsonl", "a") as f:
        f.write('{"run_id": "r1", "ev\n\nnot json\n')
    runs, bad = load(project)
    assert list(runs) == [a["run_id"]] and bad == 2


def test_append_only_and_validation(project):
    a = append_event(project, "started", cmd="x")
    before = (project / "research/runs.jsonl").read_text()
    append_event(project, "note", run_id=a["run_id"], note="eta 2h")
    assert (project / "research/runs.jsonl").read_text().startswith(before)
    with pytest.raises(ValueError):
        append_event(project, "exploded", run_id=a["run_id"])
    with pytest.raises(ValueError):
        append_event(project, "finished", run_id="nope")
    assert load(project)[0][a["run_id"]]["status"] == "started"  # note does not change status


def test_remote_run_is_not_filled_from_local_repo(project):
    a = append_event(project, "started", host="gpu-box", cmd="x")
    assert a["git_commit"] is None and a["git_dirty"] is None and a["cwd"] is None
