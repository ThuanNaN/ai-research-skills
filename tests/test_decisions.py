from rstate.decisions import append, recent


def test_decision_format_and_append_only(project):
    append(project, "Comparison point is checkpoint 20k", "100k takes too long", date="2026-11-03")
    first = (project / "research/decisions.md").read_text()
    assert "## 2026-11-03 — Comparison point is checkpoint 20k\nWhy: 100k takes too long\nSupersedes: —\n" in first
    append(project, "Use 40k instead", "20k was noisy",
           supersedes="2026-11-03 — Comparison point is checkpoint 20k", date="2026-11-09")
    assert (project / "research/decisions.md").read_text().startswith(first)
    assert recent(project, 1) == ["2026-11-09 — Use 40k instead"]
    assert recent(project) == ["2026-11-09 — Use 40k instead", "2026-11-03 — Comparison point is checkpoint 20k"]


def test_recent_without_file(project):
    assert recent(project) == []
