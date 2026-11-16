import pytest

from rstate.guard import decide
from rstate.plans import freeze

RULES = ('---\nenforce: true\nprotected_paths:\n  - "scripts/rq1_*.py"\n  - "out/step*/**"\n'
         'eval_only_paths:\n  - "data/heldout.json"\ntrain_command_patterns:\n  - "train\\\\.py|accelerate launch"\n'
         'protected_processes:\n  - "llama-server"\n---\n')


@pytest.fixture
def guarded(project):
    (project / "research/rules.md").write_text(RULES)
    (project / "scripts").mkdir()
    return project


def bash(root, cmd, cwd=None):
    return decide("Bash", {"command": cmd}, cwd or root, root).action


@pytest.mark.parametrize("cmd", [
    "echo x > scripts/rq1_eval.py", "echo x >>out/step3/a/b.csv", "rm -rf out/step3", "mv scripts/rq1_eval.py old.py",
    "cp new.py scripts/rq1_eval.py", "sed -i 's/a/b/' ./scripts/../scripts/rq1_eval.py",
    "python x.py | tee out/step2/log.txt", "sudo rm out/step3/a", "cd . && rm out/step3/a; ls",
    "python x.py 2>out/step3/err.log", "dd if=/dev/zero of=out/step3/blob", "truncate -s 0 scripts/rq1_eval.py",
    "python train.py --eval data/heldout.json", "accelerate launch t.py --data ./data/heldout.json",
    "pkill -f llama-server", "killall llama-server", "echo x >> research/runs.jsonl", "rm research/decisions.md",
    "echo x > research/STATUS.md",
])
def test_bash_denied(guarded, cmd):
    assert bash(guarded, cmd) == "deny"


@pytest.mark.parametrize("cmd", [
    "cat scripts/rq1_eval.py", "cp scripts/rq1_eval.py scripts/copy_of_rq1_eval.py", "python scripts/rq1_eval.py",
    "python eval.py --data data/heldout.json", "python train.py --data data/train.json", "ls out/step3",
    "pkill -f my_train", "echo 'unbalanced", "grep llama-server ps.txt", "python x.py > logs/new.txt",
    "python skills/research-state/scripts/research_state.py decide --title t --why w",
])
def test_bash_allowed(guarded, cmd):
    assert bash(guarded, cmd) == "allow"


def test_copy_into_rules_asks(guarded):
    assert bash(guarded, "cp /tmp/x research/rules.md") == "ask"


def test_cwd_in_subdirectory(guarded):
    assert bash(guarded, "rm rq1_eval.py", cwd=guarded / "scripts") == "deny"


def test_symlink_to_protected(guarded):
    (guarded / "scripts/rq1_a.py").write_text("")
    (guarded / "alias.py").symlink_to(guarded / "scripts/rq1_a.py")
    assert decide("Edit", {"file_path": str(guarded / "alias.py")}, guarded, guarded).action == "deny"


def test_write_edit_rules(guarded):
    def d(rel):
        return decide("Write", {"file_path": str(guarded / rel), "content": ""}, guarded, guarded)
    assert d("scripts/rq1_eval.py").action == "deny" and "scripts/rq1_*.py" in d("scripts/rq1_eval.py").reason
    assert d("scripts/other.py").action == "allow"
    assert d("research/rules.md").action == "ask"
    assert d("research/STATUS.md").action == d("research/runs.jsonl").action == d("research/decisions.md").action == "deny"
    assert d("research/questions.md").action == "deny"
    assert "research/rules.md" in d("scripts/rq1_eval.py").reason
    assert "research_state.py" in d("research/runs.jsonl").reason


def test_notebook_edit_is_guarded(guarded):
    d = decide("NotebookEdit", {"notebook_path": str(guarded / "out/step1/a.ipynb")}, guarded, guarded)
    assert d.action == "deny"


def test_frozen_plan_is_immutable(guarded):
    p = guarded / "research/plans/a.md"
    p.parent.mkdir()
    p.write_text("x\n")

    def edit():
        return decide("Edit", {"file_path": str(p), "old_string": "x", "new_string": "y"}, guarded, guarded).action
    assert edit() == "allow"
    freeze(guarded, "a")
    assert edit() == "deny"
    assert bash(guarded, "echo y >> research/plans/a.md") == "deny"


def test_kill_by_pid_of_protected_process(guarded, monkeypatch):
    import rstate.guard as guard
    monkeypatch.setattr(guard, "_cmdline", lambda pid: "/usr/bin/llama-server --port 8080" if pid == 4242 else "python train.py")
    assert bash(guarded, "kill -9 4242") == "deny"
    assert bash(guarded, "kill 999") == "allow"


def test_malformed_rules_fail_closed_but_fixable(guarded):
    (guarded / "research/rules.md").write_text("---\nbogus: 1\n---\n")
    assert bash(guarded, "ls") == "deny"
    assert decide("Edit", {"file_path": str(guarded / "research/rules.md")}, guarded, guarded).action == "ask"


def test_disabled_or_absent(guarded, tmp_path_factory):
    (guarded / "research/rules.md").write_text("---\nenforce: false\n---\n")
    assert bash(guarded, "rm -rf out/step3") == "allow"
    other = tmp_path_factory.mktemp("plain")
    assert decide("Bash", {"command": "rm -rf /"}, other, other).action == "allow"  # no research/ → not our business


def test_other_tools_are_ignored(guarded):
    assert decide("Read", {"file_path": str(guarded / "scripts/rq1_eval.py")}, guarded, guarded).action == "allow"


def test_copy_onto_a_name_matching_the_pattern_is_denied(guarded):
    # The destination itself matches scripts/rq1_*.py, so it is protected too.
    assert bash(guarded, "cp scripts/rq1_eval.py scripts/rq1_eval_v2.py") == "deny"


@pytest.mark.parametrize("cmd", ["bash -c 'rm -rf out/step3'", 'ssh gpu-box "pkill -f llama-server"'])
def test_wrapped_commands_are_inspected(guarded, cmd):
    assert bash(guarded, cmd) == "deny"
