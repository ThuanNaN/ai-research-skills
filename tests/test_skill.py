def test_skill_front_matter_and_size():
    text = open("skills/research-state/SKILL.md").read()
    fm = text.split("---")[1]
    assert "name: research-state" in fm and "description:" in fm
    assert len(text.splitlines()) <= 120  # progressive disclosure
    for cmd in ["init", "status", "decide", "rq ", "run start", "run finish", "freeze", "amend"]:
        assert cmd in text
    assert "references/file-formats.md" in text


def test_reference_and_readme_exist():
    ref = open("skills/research-state/references/file-formats.md").read()
    for name in ["rules.md", "decisions.md", "questions.md", "runs.jsonl", "plans/", "STATUS.md"]:
        assert name in ref
    readme = open("README.md").read()
    assert "/plugin install ai-research@ai-research-skills" in readme and "Limitations" in readme
