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


def _git_toplevel(start):
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"], cwd=str(start),
            capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None
    if out.returncode == 0 and out.stdout.strip():
        return Path(os.path.realpath(out.stdout.strip()))
    return None


def locate(start):
    """The project holding research/ for a directory, or None.

    The search goes up from start but never above the git toplevel, and
    outside a git repo it looks only at start itself: an unrelated
    `research/` folder higher up (say ~/research) is not this project's state.
    """
    start = Path(os.path.realpath(str(start)))
    top = _git_toplevel(start) if start.is_dir() else None
    if top is None:
        return start if (start / RESEARCH).is_dir() else None
    for candidate in (start, *start.parents):
        if (candidate / RESEARCH).is_dir():
            return candidate
        if candidate == top:
            break
    return None


def find_root(start):
    """Project root for the CLI: where research/ is, else the git toplevel, else start."""
    start = Path(os.path.realpath(str(start)))
    return locate(start) or _git_toplevel(start) or start


def resolve(p, cwd):
    """Absolute, symlink-free form of a path written relative to cwd."""
    p = os.path.expanduser(str(p).replace("\0", ""))  # a NUL would make every path call raise
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


_GLOB_CHARS = set("*?[")


def _absolute(pattern, root):
    pattern = os.path.expanduser(pattern)
    if not os.path.isabs(pattern):
        pattern = os.path.join(os.path.realpath(str(root)), pattern)
    return pattern.rstrip("/") or "/"


def literal_prefix(pattern, root):
    """The directory part of a pattern that contains no glob characters."""
    parts = Path(_absolute(pattern, root)).parts
    keep = []
    for part in parts:
        if _GLOB_CHARS & set(part):
            break
        keep.append(part)
    return Path(os.path.realpath(os.path.join(*keep))) if keep else Path("/")


def _variants(pattern, root):
    """The pattern as written and with its literal prefix resolved through symlinks."""
    absolute = _absolute(pattern, root)
    parts = Path(absolute).parts
    literal = []
    for part in parts:
        if _GLOB_CHARS & set(part):
            break
        literal.append(part)
    rest = parts[len(literal):]
    out = {absolute}
    if literal:
        real = os.path.realpath(os.path.join(*literal))
        out.add(os.path.join(real, *rest) if rest else real)
    return out


def matches(path, pattern, root):
    """True if pattern matches path or one of its ancestor directories.

    Relative patterns are relative to root. `**` crosses `/`; `*` and `?` do
    not. A trailing `/**` also matches the directory itself. Symlinks in the
    path and in the pattern's literal prefix are resolved.
    """
    regexes = []
    for variant in _variants(pattern, root):
        regexes.append(_glob_to_regex(variant))
        if variant.endswith("/**"):
            regexes.append(_glob_to_regex(variant[:-3]))
    path = Path(os.path.realpath(str(path)))
    for candidate in (path, *path.parents):
        text = str(candidate)
        if any(rx.fullmatch(text) for rx in regexes):
            return True
    return False
