from conftest import cli
from rstate import questions, rules, runs


def test_init_is_idempotent_and_ignores_status(project_no_research):
    root = project_no_research
    cli(root, "init")
    (root / "research/rules.md").write_text("mine")
    cli(root, "init")
    assert (root / "research/rules.md").read_text() == "mine"
    assert (root / ".gitignore").read_text().count("research/STATUS.md") == 1
    assert (root / "research/plans").is_dir() and (root / "research/STATUS.md").exists()
    assert (root / "research/decisions.md").exists() and (root / "research/questions.md").exists()


def test_init_appends_to_existing_gitignore(project_no_research):
    root = project_no_research
    (root / ".gitignore").write_text("*.pt")
    cli(root, "init")
    assert (root / ".gitignore").read_text().splitlines() == ["*.pt", "research/STATUS.md"]


def test_template_rules_parse(project_no_research):
    cli(project_no_research, "init")
    r = rules.load(project_no_research)
    assert r.enforce is True and r.protected_paths == [] and r.stale_after_hours == 24
    assert "approval" in r.prose


def test_run_lifecycle_from_subdir(project):
    (project / "src").mkdir()
    rid = cli(project, "run", "start", "--cmd", "python train.py", "--seed", "3", "--rq", "RQ1",
              cwd=project / "src").stdout.strip()
    cli(project, "run", "finish", "--id", rid, "--metric", "sr=0.34", "--metric", "tag=best")
    r = runs.load(project)[0][rid]
    assert r["status"] == "finished" and r["metrics"] == {"sr": 0.34, "tag": "best"} and r["seed"] == 3
    assert rid in (project / "research/STATUS.md").read_text()


def test_decide_rq_freeze_amend(project):
    cli(project, "decide", "--title", "Use 20k checkpoint", "--why", "100k is too slow")
    cli(project, "rq", "RQ1", "--title", "Does X hold?", "--status", "running", "--evidence", "a.md", "--evidence", "b.md")
    (project / "research/plans").mkdir()
    (project / "research/plans/rq1.md").write_text("rule\n")
    cli(project, "freeze", "rq1")
    cli(project, "amend", "rq1", "--text", "added exploratory analysis")
    assert "Use 20k checkpoint" in (project / "research/decisions.md").read_text()
    assert questions.load(project)[0]["evidence"] == ["a.md", "b.md"]
    assert "## Amendment" in (project / "research/plans/rq1.md").read_text()
    status = cli(project, "status").stdout
    assert "rq1 — frozen" in status and "RQ1 (running)" in status


def test_errors_are_one_line(project):
    p = cli(project, "rq", "RQ1", "--status", "done", "--title", "t", check=False)
    assert p.returncode == 1 and "Traceback" not in p.stderr and len(p.stderr.strip().splitlines()) == 1
    q = cli(project, "freeze", "missing", check=False)
    assert q.returncode == 1 and "Traceback" not in q.stderr


def test_commands_need_an_initialised_project(project_no_research):
    p = cli(project_no_research, "decide", "--title", "t", "--why", "w", check=False)
    assert p.returncode == 1 and "init" in p.stderr
    assert not (project_no_research / "research").exists()
