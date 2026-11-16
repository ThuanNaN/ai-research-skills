import pytest

from rstate.questions import load, upsert


def test_question_upsert_roundtrip(project):
    upsert(project, "RQ1", title="Does X hold?")
    upsert(project, "RQ2", title="Why?", status="running", next_step="run seed 2")
    upsert(project, "RQ1", status="closed", verdict="inconclusive", evidence=["reports/rq1.md"])
    upsert(project, "RQ1", evidence=["reports/rq1.md", "r20261116-001"])
    q1, q2 = load(project)
    assert q1 == {"id": "RQ1", "title": "Does X hold?", "status": "closed", "verdict": "inconclusive",
                  "evidence": ["reports/rq1.md", "r20261116-001"], "next": "—"}
    assert (q2["status"], q2["next"]) == ("running", "run seed 2")


def test_question_validation(project):
    with pytest.raises(ValueError):
        upsert(project, "RQ9", status="open")  # new without title
    with pytest.raises(ValueError):
        upsert(project, "RQ1", title="t", status="done")


def test_other_text_in_file_is_kept(project):
    upsert(project, "RQ1", title="Does X hold?")
    path = project / "research/questions.md"
    path.write_text(path.read_text() + "\nFree-form note the owner wrote.\n")
    upsert(project, "RQ2", title="Why?")
    upsert(project, "RQ1", status="running")
    text = path.read_text()
    assert "Free-form note the owner wrote." in text
    assert [q["id"] for q in load(project)] == ["RQ1", "RQ2"]
