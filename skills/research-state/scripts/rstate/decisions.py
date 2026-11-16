"""Append-only decision log: research/decisions.md."""
import fcntl
from datetime import date as _date

from . import paths

HEADER = "# Decisions\n\nAppend-only. A changed decision is a new entry that names what it supersedes.\n"


def _one_line(text):
    return " ".join(str(text).split())


def append(root, title, why, supersedes=None, date=None):
    """Append a decision; returns its heading line."""
    title, why = _one_line(title), _one_line(why)
    if not title or not why:
        raise ValueError("a decision needs both a title and a reason")
    date = date or _date.today().isoformat()
    heading = f"## {date} — {title}"
    entry = f"\n{heading}\nWhy: {why}\nSupersedes: {_one_line(supersedes) if supersedes else '—'}\n"
    path = paths.research_dir(root) / paths.DECISIONS
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a+", encoding="utf-8", errors="replace") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        f.seek(0)
        existing = f.read()
        if not existing:
            f.write(HEADER)
        elif not existing.endswith("\n"):
            f.write("\n")
        f.write(entry)
    return heading


def recent(root, n=5):
    """Heading text of the last n decisions, newest first."""
    path = paths.research_dir(root) / paths.DECISIONS
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except FileNotFoundError:
        return []
    headings = [line[3:].strip() for line in text.splitlines() if line.startswith("## ")]
    return headings[::-1][:n]
