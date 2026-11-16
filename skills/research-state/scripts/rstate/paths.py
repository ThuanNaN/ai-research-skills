"""Project root, research file locations and glob matching."""
import os
import re
import subprocess
from pathlib import Path

RESEARCH = "research"
RULES = "rules.md"
DECISIONS = "decisions.md"
QUESTIONS = "questions.md"
RUNS = "runs.jsonl"
STATUS = "STATUS.md"
PLANS = "plans"


def research_dir(root):
    return Path(root) / RESEARCH


def find_root(start):
    """Nearest ancestor holding research/; else the git toplevel; else start."""
    start = Path(start).resolve()
    for candidate in (start, *start.parents):
        if (candidate / RESEARCH).is_dir():
            return candidate
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"], cwd=start,
            capture_output=True, text=True, timeout=10)
        if out.returncode == 0 and out.stdout.strip():
            return Path(out.stdout.strip())
    except (OSError, subprocess.SubprocessError):
        pass
    return start


def resolve(p, cwd):
    """Absolute, symlink-free form of a path written relative to cwd."""
    p = os.path.expanduser(str(p))
    if not os.path.isabs(p):
        p = os.path.join(str(cwd), p)
    return Path(os.path.realpath(p))


def _glob_to_regex(pattern):
    out, i = [], 0
    while i < len(pattern):
        if pattern.startswith("**/", i):
            out.append("(?:.*/)?")
            i += 3
        elif pattern.startswith("**", i):
            out.append(".*")
            i += 2
        elif pattern[i] == "*":
            out.append("[^/]*")
            i += 1
        elif pattern[i] == "?":
            out.append("[^/]")
            i += 1
        else:
            out.append(re.escape(pattern[i]))
            i += 1
    return re.compile("".join(out))


def matches(path, pattern, root):
    """True if pattern matches path or one of its ancestor directories.

    Relative patterns are relative to root. `**` crosses `/`; `*` and `?` do
    not. A trailing `/**` also matches the directory itself.
    """
    pattern = os.path.expanduser(pattern)
    if not os.path.isabs(pattern):
        pattern = os.path.join(os.path.realpath(str(root)), pattern)
    pattern = pattern.rstrip("/") or "/"
    regexes = [_glob_to_regex(pattern)]
    if pattern.endswith("/**"):
        regexes.append(_glob_to_regex(pattern[:-3]))
    path = Path(os.path.realpath(str(path)))
    for candidate in (path, *path.parents):
        text = str(candidate)
        if any(rx.fullmatch(text) for rx in regexes):
            return True
    return False
