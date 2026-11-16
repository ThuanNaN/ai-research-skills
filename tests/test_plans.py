import pytest

from rstate.plans import amend, freeze, is_frozen, list_plans, state


def test_freeze_amend_and_tamper(project):
    p = project / "research/plans/rq2.md"
    p.parent.mkdir(parents=True)
    p.write_text("# RQ2 plan\n\nDecision rule: interval above 0 → supported.\n")
    assert state(p) == "draft"
    digest = freeze(project, "rq2", date="2026-11-16")
    assert p.read_text().splitlines()[0] == f"Frozen: 2026-11-16 (sha256 {digest})"
    assert state(p) == "frozen" and is_frozen(p)
    amend(project, "rq2", "Found near-duplicates in test; adding exploratory analysis.", date="2026-11-18")
    assert "## Amendment 2026-11-18" in p.read_text() and state(p) == "frozen"
    amend(project, "rq2", "Second amendment.", date="2026-11-19")
    assert state(p) == "frozen"
    p.write_text(p.read_text().replace("above 0", "above -1"))
    assert state(p) == "tampered" and is_frozen(p)
    assert list_plans(project) == [("rq2", "tampered")]


def test_freeze_errors(project):
    (project / "research/plans").mkdir()
    with pytest.raises(FileNotFoundError):
        freeze(project, "nope")
    (project / "research/plans/a.md").write_text("x\n")
    freeze(project, "a")
    with pytest.raises(ValueError):
        freeze(project, "a")
    (project / "research/plans/b.md").write_text("x\n")
    with pytest.raises(ValueError):
        amend(project, "b", "t")


def test_no_plans_dir(project):
    assert list_plans(project) == []
