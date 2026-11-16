"""Research questions and their status: research/questions.md."""
import fcntl
import re

from . import paths

STATUSES = ("open", "running", "awaiting-approval", "closed")
HEADER = "# Research questions\n"
EMPTY = "—"
LABELS = ("Status", "Verdict", "Evidence", "Next")
_HEADING = re.compile(r"^## (\S+)\s+[—–-]\s+(.*)$")
_FIELD_LINE = re.compile(r"^- (Status|Verdict|Evidence|Next):\s*(.*)$")


def _one_line(text):
    return " ".join(str(text).split())


def _split(text):
    """(preamble lines, sections). A section keeps its lines exactly as written.

    The first line carrying each field label is that field; a later line with
    the same label is ordinary text the user wrote.
    """
    preamble, sections, current = [], [], None
    for line in text.splitlines():
        m = _HEADING.match(line)
        if m:
            current = {"id": m.group(1), "title": m.group(2).strip(), "lines": [], "at": {}}
            sections.append(current)
        elif current is None:
            preamble.append(line)
        else:
            f = _FIELD_LINE.match(line)
            if f and f.group(1) not in current["at"]:
                current["at"][f.group(1)] = len(current["lines"])
            current["lines"].append(line)
    return preamble, sections


def _value(section, label):
    index = section["at"].get(label)
    if index is None:
        return ""
    return _FIELD_LINE.match(section["lines"][index]).group(2).strip()


def _public(section):
    evidence = _value(section, "Evidence")
    return {
        "id": section["id"],
        "title": section["title"],
        "status": _value(section, "Status") or "open",
        "verdict": _value(section, "Verdict") or EMPTY,
        "evidence": [] if evidence in ("", EMPTY) else [v.strip() for v in evidence.split(",") if v.strip()],
        "next": _value(section, "Next") or EMPTY,
    }


def _set(section, label, value):
    """Rewrite a field in place, or add it after the last field already there."""
    line = f"- {label}: {value}"
    at = section["at"]
    if label in at:
        section["lines"][at[label]] = line
        return
    index = max(at.values()) + 1 if at else 0
    section["lines"].insert(index, line)
    for other, pos in at.items():
        if pos >= index:
            at[other] = pos + 1
    at[label] = index


def _render(preamble, sections):
    out = list(preamble)
    for s in sections:
        if out and out[-1].strip():
            out.append("")
        out.append(f"## {s['id']} — {s['title']}")
        out.extend(s["lines"])
    while out and not out[-1].strip():
        out.pop()
    return "\n".join(out) + "\n"


def load(root):
    """Questions in file order."""
    path = paths.research_dir(root) / paths.QUESTIONS
    text = path.read_text(encoding="utf-8", errors="replace") if path.exists() else HEADER
    return [_public(s) for s in _split(text)[1]]


def upsert(root, qid, title=None, status=None, verdict=None, evidence=None, next_step=None):
    """Create or update one question; everything else in the file stays as written."""
    qid = _one_line(qid)
    if not qid or " " in qid:
        raise ValueError("a question id is one word, e.g. RQ1")
    if status is not None and status not in STATUSES:
        raise ValueError(f"status must be one of {', '.join(STATUSES)}; got {status!r}")
    path = paths.research_dir(root) / paths.QUESTIONS
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a+", encoding="utf-8", errors="replace") as f:
        fcntl.flock(f, fcntl.LOCK_EX)  # read-modify-write: one writer at a time
        f.seek(0)
        preamble, sections = _split(f.read() or HEADER)
        section = next((s for s in sections if s["id"] == qid), None)
        if section is None:
            if not title:
                raise ValueError(f"{qid} is new: give it a title")
            section = {"id": qid, "title": "", "lines": [], "at": {}}
            sections.append(section)
        current = _public(section)
        if title:
            section["title"] = _one_line(title)
        items = list(current["evidence"])
        for item in evidence or []:
            item = _one_line(item).replace(",", ";")
            if item and item not in items:
                items.append(item)
        _set(section, "Status", status if status is not None else current["status"])
        _set(section, "Verdict", (_one_line(verdict) or EMPTY) if verdict is not None else current["verdict"])
        _set(section, "Evidence", ", ".join(items) if items else EMPTY)
        _set(section, "Next", (_one_line(next_step) or EMPTY) if next_step is not None else current["next"])
        f.seek(0)
        f.truncate()
        f.write(_render(preamble, sections))
        return _public(section)
