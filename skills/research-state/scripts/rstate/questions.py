"""Research questions and their status: research/questions.md."""
import re

from . import paths

STATUSES = ("open", "running", "awaiting-approval", "closed")
HEADER = "# Research questions\n"
_HEADING = re.compile(r"^## (\S+) — (.*)$")
_FIELDS = (("status", "Status"), ("verdict", "Verdict"), ("evidence", "Evidence"), ("next", "Next"))
_FIELD_LINE = re.compile(r"^- (Status|Verdict|Evidence|Next):\s*(.*)$")
EMPTY = "—"


def _one_line(text):
    return " ".join(str(text).split())


def _split(text):
    """(preamble lines, [section]) where a section is {heading fields, extra lines}."""
    preamble, sections, current = [], [], None
    for line in text.splitlines():
        m = _HEADING.match(line)
        if m:
            current = {"id": m.group(1), "title": m.group(2).strip(), "status": "open",
                       "verdict": EMPTY, "evidence": [], "next": EMPTY, "_extra": []}
            sections.append(current)
            continue
        if current is None:
            preamble.append(line)
            continue
        f = _FIELD_LINE.match(line)
        if not f:
            current["_extra"].append(line)
            continue
        label, value = f.group(1), f.group(2).strip()
        if label == "Evidence":
            current["evidence"] = [] if value in ("", EMPTY) else [v.strip() for v in value.split(",") if v.strip()]
        else:
            current[label.lower()] = value or EMPTY
    return preamble, sections


def _render(preamble, sections):
    out = list(preamble)
    for s in sections:
        if out and out[-1].strip():
            out.append("")
        out.append(f"## {s['id']} — {s['title']}")
        out.append(f"- Status: {s['status']}")
        out.append(f"- Verdict: {s['verdict']}")
        out.append(f"- Evidence: {', '.join(s['evidence']) if s['evidence'] else EMPTY}")
        out.append(f"- Next: {s['next']}")
        extra = list(s["_extra"])
        while extra and not extra[-1].strip():
            extra.pop()
        out.extend(extra)
    return "\n".join(out) + "\n"


def _public(section):
    return {k: section[k] for k in ("id", "title", "status", "verdict", "evidence", "next")}


def _read(root):
    path = paths.research_dir(root) / paths.QUESTIONS
    text = path.read_text(encoding="utf-8", errors="replace") if path.exists() else HEADER
    return path, _split(text)


def load(root):
    """Questions in file order."""
    return [_public(s) for s in _read(root)[1][1]]


def upsert(root, qid, title=None, status=None, verdict=None, evidence=None, next_step=None):
    """Create or update one question; other text in the file is left alone."""
    qid = _one_line(qid)
    if not qid or " " in qid:
        raise ValueError("a question id is one word, e.g. RQ1")
    if status is not None and status not in STATUSES:
        raise ValueError(f"status must be one of {', '.join(STATUSES)}; got {status!r}")
    path, (preamble, sections) = _read(root)
    section = next((s for s in sections if s["id"] == qid), None)
    if section is None:
        if not title:
            raise ValueError(f"{qid} is new: give it a title")
        section = {"id": qid, "title": "", "status": "open", "verdict": EMPTY,
                   "evidence": [], "next": EMPTY, "_extra": []}
        sections.append(section)
    if title:
        section["title"] = _one_line(title)
    if status is not None:
        section["status"] = status
    if verdict is not None:
        section["verdict"] = _one_line(verdict) or EMPTY
    if next_step is not None:
        section["next"] = _one_line(next_step) or EMPTY
    for item in evidence or []:
        item = _one_line(item).replace(",", ";")
        if item and item not in section["evidence"]:
            section["evidence"].append(item)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_render(preamble, sections), encoding="utf-8")
    return _public(section)
