"""Regression tests for the findings of the whole-branch review."""
import json
import os

import pytest

from conftest import cli, run_hook
from rstate import questions, rules, runs, status
from rstate.guard import decide
from rstate.paths import find_root, matches
from rstate.plans import freeze

RULES = ('---\nenforce: true\nprotected_paths:\n  - "scripts/rq1_*.py"\n  - "out/step*/**"\n'
         'eval_only_paths:\n  - "data/heldout.json"\ntrain_command_patterns:\n  - "train\\\\.py|accelerate launch"\n'
         'protected_processes:\n  - "llama-server"\n---\n')


@pytest.fixture
def guarded(project):
    (project / "research/rules.md").write_text(RULES)
    (project / "scripts").mkdir()
    (project / "scripts/rq1_eval.py").write_text("x\n")
    return project


def bash(root, cmd, cwd=None):
    return decide("Bash", {"command": cmd}, cwd or root, root).action


# 1. Bash shapes the guard used to miss -------------------------------------

@pytest.mark.parametrize("cmd", [
    "echo hi\nrm scripts/rq1_eval.py", "echo start\npkill llama-server",
    "cd scripts && rm rq1_eval.py", "cd scripts; echo x > rq1_eval.py",
    "if [ -f f ]; then rm scripts/rq1_eval.py; fi", "for f in a; do rm scripts/rq1_eval.py; done",
    "{ rm scripts/rq1_eval.py; }", "! rm scripts/rq1_eval.py", "timeout 5 rm scripts/rq1_eval.py",
    "bash -lc 'rm scripts/rq1_eval.py'", 'eval "rm scripts/rq1_eval.py"', "echo `rm scripts/rq1_eval.py`",
    "echo a#b; rm scripts/rq1_eval.py", "echo $(rm scripts/rq1_eval.py)",
    "rm -rf scripts", "rm -rf out", "mv out out_old", "rm -rf research", "mv research research_old",
    "rm scripts/*.py", "cp /tmp/rq1_eval.py scripts/", "mv /tmp/rq1_eval.py scripts/",
    "cp -t scripts /tmp/rq1_eval.py",
    "kill $(pgrep -f llama-server)", "pgrep llama-server | xargs kill",
    "git checkout -- scripts/rq1_eval.py", "git restore scripts/rq1_eval.py", "git rm scripts/rq1_eval.py",
    "git mv scripts/rq1_eval.py x.py", "git clean -fdx",
])
def test_denied_shapes(guarded, cmd):
    assert bash(guarded, cmd) == "deny"


def test_moving_plans_dir_with_a_frozen_plan_is_denied(guarded):
    (guarded / "research/plans").mkdir()
    (guarded / "research/plans/a.md").write_text("x\n")
    freeze(guarded, "a")
    assert bash(guarded, "mv research/plans research/p2") == "deny"


def test_git_checkout_of_rules_asks(guarded):
    assert bash(guarded, "git checkout research/rules.md") == "ask"


# 6. Read-only work the guard used to deny ----------------------------------

@pytest.mark.parametrize("cmd", [
    "grep '>' scripts/rq1_eval.py", 'grep -c ">" scripts/rq1_eval.py',
    'grep -rn "data/heldout.json" train.py scripts/', "git log -- train.py data/heldout.json",
    "python eval.py --data data/heldout.json --ckpt ckpts/pretrain.py",
    "wc -l data/heldout.json && python train.py",
    "cat > n.md <<'EOF'\nresult: a > scripts/rq1_eval.py is wrong; rm scripts/rq1_eval.py\nEOF",
    "rm -rf scripts/tmp", "rm out/tmp_*", "python x.py 2>&1 | tee logs/a.txt", "ls scripts > /dev/null",
    "chmod +x scripts/rq1_eval.py", "kill ²", "git status", "git checkout main",
    "python train.py --data data/train.json  # not data/heldout.json",
])
def test_allowed_shapes(guarded, cmd):
    assert bash(guarded, cmd) == "allow"


def test_cd_elsewhere_is_followed(guarded, tmp_path_factory):
    other = tmp_path_factory.mktemp("elsewhere")
    assert bash(guarded, f"cd {other} && rm scripts/rq1_eval.py") == "allow"


def test_rules_file_asks_even_when_a_pattern_covers_it(project):
    (project / "research/rules.md").write_text('---\nprotected_paths:\n  - "**/*.md"\n---\n')
    d = decide("Edit", {"file_path": str(project / "research/rules.md")}, project, project)
    assert d.action == "ask"


def test_hooks_json_covers_multiedit():
    cfg = json.load(open("hooks/hooks.json"))["hooks"]
    assert "MultiEdit" in cfg["PreToolUse"][0]["matcher"].split("|")


# 2. Front matter that does not start on line 1 -----------------------------

@pytest.mark.parametrize("prefix", ["﻿", "\n", "\n\n  \n"])
def test_bom_or_blank_lines_before_front_matter(project, prefix):
    (project / "research/rules.md").write_text(prefix + '---\nprotected_paths:\n  - "a.py"\n---\nprose\n')
    assert rules.load(project).protected_paths == ["a.py"]


@pytest.mark.parametrize("text", ['protected_paths:\n  - "a.py"\n---\n', 'Some intro\n---\nenforce: true\n---\n'])
def test_front_matter_without_opening_is_an_error(project, text):
    (project / "research/rules.md").write_text(text)
    with pytest.raises(rules.RulesError):
        rules.load(project)


def test_plain_prose_rules_are_fine(project):
    (project / "research/rules.md").write_text("# Rules\n\n- Be careful.\n")
    assert rules.load(project).prose.startswith("# Rules")


# 3. An unrelated research/ above the project -------------------------------

def test_unrelated_ancestor_research_dir_is_ignored(tmp_path):
    import subprocess
    (tmp_path / "research").mkdir()  # e.g. ~/research, nothing to do with us
    proj = tmp_path / "work/proj"
    proj.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(proj)], check=True)
    assert find_root(proj) == proj
    cli(proj, "init")
    assert (proj / "research/rules.md").exists() and not (tmp_path / "research/rules.md").exists()
    assert not (tmp_path / ".gitignore").exists()


def test_hooks_ignore_unrelated_ancestor_research_dir(tmp_path):
    import subprocess
    (tmp_path / "research").mkdir()
    proj = tmp_path / "work/proj"
    proj.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(proj)], check=True)
    env_dir = tmp_path / "nowhere"
    env_dir.mkdir()
    out = run_hook("session_start.py", {"source": "startup", "cwd": str(proj)}, env_dir)
    assert out.stdout == "" and not (tmp_path / "research/STATUS.md").exists()


def test_no_git_repo_only_looks_at_start_dir(tmp_path):
    (tmp_path / "research").mkdir()
    (tmp_path / "sub").mkdir()
    assert find_root(tmp_path / "sub") == tmp_path / "sub"
    assert find_root(tmp_path) == tmp_path


# 4. questions.md keeps what the user wrote ---------------------------------

def test_upsert_keeps_user_text_in_place(project):
    path = project / "research/questions.md"
    path.write_text(
        "# Research questions\n\n"
        "## RQ1 — First\n"
        "Context I wrote before the fields.\n"
        "- Status: open\n- Verdict: —\n- Evidence: —\n- Next: real next\n"
        "Notes:\n- Next: a bullet I wrote\n- Verdict: just a remark\n\n"
        "## RQ2 - hyphen heading\n- Status: awaiting-approval\n")
    questions.upsert(project, "RQ1", status="running")
    text = path.read_text()
    assert text.index("Context I wrote before the fields.") < text.index("- Status: running")
    assert "- Next: real next" in text and "- Next: a bullet I wrote" in text and "- Verdict: just a remark" in text
    q1, q2 = questions.load(project)
    assert (q1["status"], q1["next"], q1["verdict"]) == ("running", "real next", "—")
    assert (q2["id"], q2["status"]) == ("RQ2", "awaiting-approval")
    questions.upsert(project, "RQ2", status="closed")
    assert questions.load(project)[1]["status"] == "closed"


def test_parallel_upserts_keep_every_question(project):
    import subprocess, sys
    from conftest import SCRIPTS
    procs = [subprocess.Popen([sys.executable, str(SCRIPTS / "research_state.py"), "rq", f"RQ{i}", "--title", "t"],
                              cwd=str(project)) for i in range(10)]
    assert all(p.wait() == 0 for p in procs)
    assert len(questions.load(project)) == 10


# 5. Absolute pattern through a symlinked directory -------------------------

def test_absolute_pattern_through_symlink(tmp_path):
    real = tmp_path / "disk"
    (real / "outputs/step1").mkdir(parents=True)
    link = tmp_path / "data"
    link.symlink_to(real)
    pattern = f"{link}/outputs/step*/**"
    assert matches(os.path.realpath(link / "outputs/step1/ckpt"), pattern, tmp_path)


# 7. Odd data in runs.jsonl -------------------------------------------------

def test_non_string_timestamp_is_an_unreadable_line(project):
    runs.append_event(project, "started", cmd="x")
    with open(project / "research/runs.jsonl", "a") as f:
        f.write('{"run_id": "r1", "ts": 5, "event": "finished"}\n')
    loaded, bad = runs.load(project)
    assert "r1" not in loaded and bad == 1
    assert "1 unreadable line" in status.build(project)
    assert cli(project, "status").returncode == 0


def test_rules_reach_the_session_even_if_status_breaks(project, monkeypatch):
    (project / "research/rules.md").write_text("---\nenforce: true\n---\n- Keep the held-out set out of training.\n")
    monkeypatch.setattr(status, "sections", lambda *a, **k: (_ for _ in ()).throw(TypeError("boom")))
    ctx = status.session_context(project)
    assert "Keep the held-out set out of training." in ctx and "boom" in ctx


def test_session_start_still_injects_when_status_cannot_be_written(project):
    (project / "research/rules.md").write_text("---\nenforce: true\n---\n- Rule one.\n")
    (project / "research/STATUS.md").mkdir()  # cannot be written as a file
    out = run_hook("session_start.py", {"source": "startup", "cwd": str(project)}, project)
    assert "Rule one." in json.loads(out.stdout)["hookSpecificOutput"]["additionalContext"]


@pytest.mark.parametrize("cmd", [
    "", "   ", "\n\n", "echo 'unbalanced", 'echo "unbalanced', "rm a\x00b", "cat <<EOF\nnever closed", "<<", ">", "2>&1",
    "a=$(b) c | d && e || f; g &", "rm -- -weird", "cp", "mv a", "git", "git checkout", "sed -i", "dd of=",
    "kill", "kill -9", "cd", "cd -", "bash -c", "eval", "timeout", "xargs", "sudo -u", "\\", "((1+1))", "x=(a b)",
    "echo ${a[@]} > /dev/null", "rm " + "a/" * 2000 + "b", "🙂 > 🙂.txt",
])
def test_odd_commands_never_raise(guarded, cmd):
    assert bash(guarded, cmd) in ("allow", "deny", "ask")


def test_odd_file_paths_never_raise(guarded):
    for path in ["", "a\x00b", "/", "~", "relative/x.py", "x" * 5000]:
        assert decide("Write", {"file_path": path}, guarded, guarded).action in ("allow", "deny", "ask")
    assert decide("Edit", {"file_path": 5}, guarded, guarded).action in ("allow", "deny", "ask")
    assert decide("Bash", {"command": None}, guarded, guarded).action == "allow"
    assert decide("Bash", "not a dict", guarded, guarded).action == "allow"
