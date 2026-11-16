from pathlib import Path

from rstate.paths import find_root, matches, resolve


def test_matches_glob_and_ancestors(tmp_path):
    r = tmp_path
    assert matches(r / "scripts/rq1_a.py", "scripts/rq1_*.py", r)
    assert not matches(r / "scripts/sub/rq1_a.py", "scripts/rq1_*.py", r)
    assert matches(r / "out/step3/x/y.csv", "out/step*/**", r)
    assert matches(r / "out/step3", "out/step*/**", r)  # the directory itself
    assert not matches(r / "out", "out/step*/**", r)
    assert matches(r / "out/step3/x/y.csv", "out/step3", r)  # ancestor dir
    assert matches(Path("/data/p/out/a.bin"), "/data/p/out/**", r)


def test_resolve_normalises(tmp_path):
    (tmp_path / "a").mkdir()
    (tmp_path / "x.py").write_text("")
    (tmp_path / "link.py").symlink_to(tmp_path / "x.py")
    target = (tmp_path / "x.py").resolve()
    assert resolve("./x.py", tmp_path) == target
    assert resolve("a/../x.py", tmp_path) == target
    assert resolve("../x.py", tmp_path / "a") == target
    assert resolve("link.py", tmp_path) == target


def test_find_root_from_subdir(project):
    (project / "src/deep").mkdir(parents=True)
    assert find_root(project / "src/deep") == project
