import pytest

from rstate.rules import RulesError, load


def test_load_rules(project):
    (project / "research/rules.md").write_text(
        '---\nenforce: true\nstale_after_hours: 12\n'
        'protected_paths:   # no writes\n  - "scripts/rq1_*.py"\n'
        'train_command_patterns:\n  - "train\\\\.py|accelerate launch"\n---\n- Copy before editing.\n')
    r = load(project)
    assert r.enforce and r.stale_after_hours == 12
    assert r.protected_paths == ["scripts/rq1_*.py"]
    assert r.train_command_patterns == [r"train\.py|accelerate launch"]
    assert r.eval_only_paths == [] and r.prose.strip() == "- Copy before editing."


def test_missing_rules_file_disables_enforcement(project):
    assert load(project).enforce is False


@pytest.mark.parametrize("fm", ["enforce: maybe", "protected_paths:\n  - unquoted", "bogus_key: true", "enforce: true"])  # last: no closing ---
def test_malformed_front_matter_raises(project, fm):
    closing = "" if fm == "enforce: true" else "\n---\n"
    (project / "research/rules.md").write_text("---\n" + fm + closing)
    with pytest.raises(RulesError):
        load(project)


def test_invalid_training_regex_is_a_rules_error(project):
    (project / "research/rules.md").write_text('---\ntrain_command_patterns:\n  - "train(\\\\.py"\n---\n')
    with pytest.raises(RulesError):
        load(project)
