"""Generated summary of the project state: research/STATUS.md and session context."""
import os
import socket
from datetime import datetime, timezone

from . import decisions, paths, plans, questions, rules, runs

POINTER = "Full state: research/STATUS.md, research/rules.md"
# Sections dropped first when the session context is too long.
DROP_ORDER = ("Recently finished", "Recent decisions", "Plans", "Open questions")
DONE = ("finished", "failed", "killed")


def _short(text, width=80):
    text = " ".join(str(text or "").split())
    return text if len(text) <= width else text[: width - 1] + "…"


def _parse_ts(ts):
    try:
        return datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def _age(ts, now):
    when = _parse_ts(ts)
    if when is None:
        return None, "updated at an unknown time"
    hours = (now - when).total_seconds() / 3600
    if hours < 1:
        return hours, f"updated {max(int(hours * 60), 0)}m ago"
    return hours, f"updated {int(hours)}h ago"


def _process_missing(run):
    pid = run.get("pid")
    if run.get("host") != socket.gethostname() or not isinstance(pid, int) or isinstance(pid, bool):
        return False
    return os.path.isdir("/proc") and not os.path.exists(f"/proc/{pid}")


def _where(run):
    host, gpu = run.get("host"), run.get("gpu")
    if host and gpu not in (None, ""):
        return f"{host} gpu {gpu}"
    return host or "unknown host"


def _run_line(run_id, run):
    rq = f" [{run['rq']}]" if run.get("rq") else ""
    return f"- {run_id}{rq} on {_where(run)}: `{_short(run.get('cmd') or '(no command recorded)')}`"


def _load_rules(root):
    try:
        return rules.load(root), None
    except rules.RulesError as exc:
        return rules.Rules(enforce=False), str(exc)


def sections(root, now=None):
    """Ordered (title, lines) pairs; empty sections are left out."""
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    rule_set, rules_error = _load_rules(root)
    all_runs, unreadable = runs.load(root)
    qs = questions.load(root)
    out = []

    running = []
    for run_id, run in all_runs.items():
        if run.get("status") != "started":
            continue
        hours, age = _age(run.get("updated"), now)
        flags = []
        if hours is None or hours > rule_set.stale_after_hours:
            flags.append("STALE — no update recorded, check whether it is still running")
        if _process_missing(run):
            flags.append("PROCESS NOT FOUND on this host")
        running.append(f"{_run_line(run_id, run)} — {age}" + "".join(f" — {f}" for f in flags))
    out.append(("Running", running))

    waiting = [f"- {q['id']} — {q['title']}" + (f" (verdict: {q['verdict']})" if q["verdict"] != questions.EMPTY else "")
               for q in qs if q["status"] == "awaiting-approval"]
    waiting += [f"{_run_line(run_id, run)} — planned, not started"
                for run_id, run in all_runs.items() if run.get("status") == "planned"]
    out.append(("Awaiting your approval", waiting))

    out.append(("Open questions", [
        f"- {q['id']} ({q['status']}) — {q['title']}" + (f" — Next: {q['next']}" if q["next"] != questions.EMPTY else "")
        for q in qs if q["status"] in ("open", "running")]))

    out.append(("Plans", [
        f"- {name} — " + ("TAMPERED — body no longer matches its hash" if state == "tampered" else state)
        for name, state in plans.list_plans(root)]))

    out.append(("Recent decisions", [f"- {d}" for d in decisions.recent(root, 5)]))

    done = [(run.get("updated") or "", run_id, run) for run_id, run in all_runs.items() if run.get("status") in DONE]
    finished = []
    for _, run_id, run in sorted(done, key=lambda item: item[0], reverse=True)[:5]:
        metrics = run.get("metrics")
        tail = ""
        if isinstance(metrics, dict) and metrics:
            tail = " — " + ", ".join(f"{k}={v}" for k, v in metrics.items())
        finished.append(f"{_run_line(run_id, run)} — {run['status']}{tail}")
    out.append(("Recently finished", finished))

    warnings = []
    if unreadable:
        warnings.append(f"- {unreadable} unreadable line{'s' if unreadable != 1 else ''} in runs.jsonl")
    if rules_error:
        warnings.append(f"- rules.md cannot be parsed: {rules_error}")
    out.append(("Warnings", warnings))
    return [(title, lines) for title, lines in out if lines]


def _render(parts):
    return "\n\n".join(f"## {title}\n" + "\n".join(lines) for title, lines in parts)


def build(root, now=None):
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    head = f"# Research status\nGenerated {now.strftime('%Y-%m-%d %H:%M')} UTC — do not edit"
    body = _render(sections(root, now))
    return head + ("\n\n" + body if body else "\n\nNothing recorded yet.") + "\n"


def write(root, now=None):
    path = paths.research_dir(root) / paths.STATUS
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(build(root, now), encoding="utf-8")
    return path


def _rules_block(root):
    rule_set, error = _load_rules(root)
    lines = ["## Standing rules"]
    if error:
        lines.append(f"research/rules.md cannot be parsed ({error}); the guard blocks tool calls until it is fixed.")
        return "\n".join(lines)
    prose = rule_set.prose.strip()
    if prose:
        lines.append(prose)
    if rule_set.enforce:
        lines.append(
            f"Enforced by hooks: {len(rule_set.protected_paths)} protected path pattern(s), "
            f"{len(rule_set.eval_only_paths)} eval-only path(s) barred from training commands, "
            f"{len(rule_set.protected_processes)} protected process(es); frozen plans, decisions.md, "
            "questions.md and runs.jsonl change only through the research-state commands.")
    else:
        lines.append("Hook enforcement is off for this project.")
    return "\n".join(lines)


def session_context(root, limit=9000, now=None):
    """Rules first, then status, cut to fit the hook's context cap."""
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    head = f"# Research project state (research/) — generated {now.strftime('%Y-%m-%d %H:%M')} UTC"
    rules_block = _rules_block(root)
    parts = sections(root, now)
    omitted = []

    def assemble():
        blocks = [head, rules_block]
        if parts:
            blocks.append(_render(parts))
        if omitted:
            blocks.append("Left out for length: " + ", ".join(omitted) + ".")
        blocks.append(POINTER)
        return "\n\n".join(blocks) + "\n"

    text = assemble()
    for title in DROP_ORDER:
        if len(text) <= limit:
            break
        if any(t == title for t, _ in parts):
            parts = [(t, lines) for t, lines in parts if t != title]
            omitted.append(title)
            text = assemble()
    if len(text) > limit:
        tail = "\n…(cut for length)\n\n" + POINTER + "\n"
        text = text[: limit - len(tail)] + tail
    return text
