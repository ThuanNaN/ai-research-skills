from datetime import datetime, timedelta, timezone

from rstate import decisions, plans
from rstate.questions import upsert
from rstate.runs import append_event
from rstate.status import build, session_context, write

NOW = datetime(2026, 11, 16, 12, 0, tzinfo=timezone.utc)


def section(text, title):
    return text.split(f"## {title}")[1].split("\n## ")[0]


def test_status_sections(project):
    a = append_event(project, "started", cmd="python train.py --seed 1", rq="RQ1", host="gpu-box",
                     now=NOW - timedelta(hours=30))
    b = append_event(project, "started", cmd="python eval.py", host="gpu-box", now=NOW - timedelta(hours=1))
    append_event(project, "finished", run_id=b["run_id"], metrics={"sr": 0.34}, now=NOW)
    append_event(project, "planned", cmd="python train.py --seed 2", now=NOW)
    upsert(project, "RQ1", title="Does X hold?", status="awaiting-approval")
    upsert(project, "RQ2", title="Why?", next_step="run seed 2")
    decisions.append(project, "Use 20k checkpoint", "time", date="2026-11-03")
    text = build(project, now=NOW)
    running = section(text, "Running")
    assert a["run_id"] in running and "STALE" in running and b["run_id"] not in running
    waiting = section(text, "Awaiting your approval")
    assert "RQ1" in waiting and "--seed 2" in waiting
    assert "run seed 2" in text and "Use 20k checkpoint" in text and "0.34" in text


def test_fresh_run_is_not_stale(project):
    append_event(project, "started", cmd="x", host="gpu-box", now=NOW - timedelta(hours=2))
    assert "STALE" not in build(project, now=NOW)


def test_dead_local_pid_flagged(project):
    append_event(project, "started", cmd="x", pid=2**22 + 12345, now=NOW)  # above pid_max
    assert "PROCESS NOT FOUND" in build(project, now=NOW)


def test_warnings_never_crash(project):
    (project / "research/runs.jsonl").write_text("garbage\n")
    (project / "research/rules.md").write_text("---\nbogus: 1\n---\n")
    text = build(project, now=NOW)
    assert "1 unreadable line" in text and "rules.md cannot be parsed" in text


def test_tampered_plan_is_reported(project):
    p = project / "research/plans/a.md"
    p.parent.mkdir()
    p.write_text("rule one\n")
    plans.freeze(project, "a")
    p.write_text(p.read_text().replace("one", "two"))
    assert "TAMPERED" in section(build(project, now=NOW), "Plans")


def test_empty_project(project):
    assert build(project, now=NOW).startswith("# Research status")


def test_write_creates_status_file(project):
    assert write(project, now=NOW).read_text().startswith("# Research status")


def test_context_keeps_rules_under_limit(project):
    (project / "research/rules.md").write_text('---\nenforce: true\n---\n- Never train on the held-out set.\n')
    for i in range(200):
        upsert(project, f"RQ{i}", title="q" * 80, next_step="n" * 80)
    append_event(project, "started", cmd="python train.py", now=NOW)
    ctx = session_context(project, now=NOW)
    assert len(ctx) <= 9000
    assert "Never train on the held-out set." in ctx and "python train.py" in ctx
    assert ctx.rstrip().endswith("Full state: research/STATUS.md, research/rules.md")
