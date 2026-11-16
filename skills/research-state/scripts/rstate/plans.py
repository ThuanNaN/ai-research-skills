"""Plans under research/plans/: freeze, amend, and detect edits to frozen text."""
import hashlib
import re
from datetime import date as _date
from pathlib import Path

from . import paths

_HEADER = re.compile(r"^Frozen: (\S+) \(sha256 ([0-9a-f]{64})\)\s*$")
_PREFIX = "Frozen: "
_AMENDMENT = "## Amendment"
_AMENDMENT_LINE = re.compile(r"^## Amendment \d{4}-\d{2}-\d{2}\s*$")


def plan_path(root, name):
    name = str(name)
    if name.endswith(".md"):
        name = name[:-3]
    if not name or "/" in name or "\\" in name or name.startswith("."):
        raise ValueError(f"plan name must be a file name under research/plans/, got {name!r}")
    return paths.research_dir(root) / paths.PLANS / f"{name}.md"


def _digest(body):
    return hashlib.sha256(body.strip().encode("utf-8")).hexdigest()


def _body(lines):
    """The frozen text: after the header, before the first amendment."""
    body = []
    for line in lines:
        if _AMENDMENT_LINE.match(line):
            break
        body.append(line)
    return "\n".join(body)


def _read(path):
    return Path(path).read_text(encoding="utf-8", errors="replace")


def is_frozen(path):
    """True once a plan carries a freeze header, even if it was edited since."""
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return f.readline().startswith(_PREFIX)
    except OSError:
        return False


def state(path):
    """'draft', 'frozen', or 'tampered' (frozen text no longer matches its hash)."""
    lines = _read(path).splitlines()
    if not lines or not lines[0].startswith(_PREFIX):
        return "draft"
    m = _HEADER.match(lines[0])
    if not m or _digest(_body(lines[1:])) != m.group(2):
        return "tampered"
    return "frozen"


def freeze(root, name, date=None):
    """Freeze a plan; returns the sha256 of its body."""
    path = plan_path(root, name)
    text = _read(path)  # FileNotFoundError when the plan does not exist
    if text.startswith(_PREFIX):
        raise ValueError(f"{path.name} is already frozen; use amend to add to it")
    digest = _digest(_body(text.splitlines()))
    date = date or _date.today().isoformat()
    path.write_text(f"{_PREFIX}{date} (sha256 {digest})\n\n{text}", encoding="utf-8")
    return digest


def amend(root, name, text, date=None):
    """Append a dated amendment to a frozen plan."""
    path = plan_path(root, name)
    current = _read(path)
    if not current.startswith(_PREFIX):
        raise ValueError(f"{path.name} is not frozen; edit it directly or freeze it first")
    if not str(text).strip():
        raise ValueError("an amendment needs text")
    date = date or _date.today().isoformat()
    sep = "" if current.endswith("\n") else "\n"
    path.write_text(f"{current}{sep}\n{_AMENDMENT} {date}\n\n{str(text).strip()}\n", encoding="utf-8")


def list_plans(root):
    """(name, state) for every plan, sorted by name."""
    folder = paths.research_dir(root) / paths.PLANS
    if not folder.is_dir():
        return []
    return [(p.stem, state(p)) for p in sorted(folder.glob("*.md"))]
