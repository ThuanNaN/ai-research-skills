import json

from conftest import run_hook


def test_session_start_injects_and_writes_status(project):
    (project / "research/rules.md").write_text('---\nenforce: true\n---\n- Never train on the held-out set.\n')
    out = run_hook("session_start.py", {"hook_event_name": "SessionStart", "source": "compact", "cwd": str(project)}, project)
    h = json.loads(out.stdout)["hookSpecificOutput"]
    assert h["hookEventName"] == "SessionStart"
    ctx = h["additionalContext"]
    assert "Never train on the held-out set." in ctx and len(ctx) <= 9000
    assert (project / "research/STATUS.md").exists()


def test_hooks_silent_without_research_dir(tmp_path):
    for script, payload in [("session_start.py", {"source": "startup"}),
                            ("pre_tool_use.py", {"tool_name": "Bash", "tool_input": {"command": "rm -rf x"}})]:
        out = run_hook(script, {**payload, "cwd": str(tmp_path)}, tmp_path)
        assert out.returncode == 0 and out.stdout == "" and out.stderr == ""


def test_session_start_survives_garbage(project):
    (project / "research/runs.jsonl").write_bytes(b"\xff\xfe garbage")
    out = run_hook("session_start.py", {"source": "startup", "cwd": str(project)}, project)
    assert out.returncode == 0 and "additionalContext" in out.stdout


def test_session_start_reports_instead_of_crashing(project):
    (project / "research/questions.md").mkdir()  # a directory where a file should be
    out = run_hook("session_start.py", {"source": "startup", "cwd": str(project)}, project)
    assert out.returncode == 0
    ctx = json.loads(out.stdout)["hookSpecificOutput"]["additionalContext"]
    assert "status could not be built" in ctx and "Standing rules" in ctx


def test_pre_tool_use_outputs(project):
    (project / "research/rules.md").write_text('---\nenforce: true\nprotected_paths:\n  - "out/**"\n---\n')
    deny = run_hook("pre_tool_use.py", {"tool_name": "Bash", "tool_input": {"command": "rm out/a"}, "cwd": str(project)}, project)
    h = json.loads(deny.stdout)["hookSpecificOutput"]
    assert (h["hookEventName"], h["permissionDecision"]) == ("PreToolUse", "deny") and "out/**" in h["permissionDecisionReason"]
    ok = run_hook("pre_tool_use.py", {"tool_name": "Bash", "tool_input": {"command": "ls"}, "cwd": str(project)}, project)
    assert ok.returncode == 0 and ok.stdout == ""
    ask = run_hook("pre_tool_use.py", {"tool_name": "Edit", "tool_input": {"file_path": str(project / "research/rules.md")},
                                       "cwd": str(project)}, project)
    assert json.loads(ask.stdout)["hookSpecificOutput"]["permissionDecision"] == "ask"
    bad = run_hook("pre_tool_use.py", "not json", project)
    assert bad.returncode == 2 and bad.stderr


def test_pre_tool_use_uses_the_calls_cwd(project):
    (project / "research/rules.md").write_text('---\nenforce: true\nprotected_paths:\n  - "out/**"\n---\n')
    (project / "out").mkdir()
    deny = run_hook("pre_tool_use.py", {"tool_name": "Bash", "tool_input": {"command": "rm a"}, "cwd": str(project / "out")}, project)
    assert json.loads(deny.stdout)["hookSpecificOutput"]["permissionDecision"] == "deny"


def test_hooks_json_is_valid():
    cfg = json.load(open("hooks/hooks.json"))["hooks"]
    assert cfg["PreToolUse"][0]["hooks"][0]["onFailure"] == "block"
    assert set(cfg["SessionStart"][0]["matcher"].split("|")) == {"startup", "resume", "clear", "compact"}
    assert set(cfg["PreToolUse"][0]["matcher"].split("|")) == {"Write", "Edit", "MultiEdit", "NotebookEdit", "Bash"}
