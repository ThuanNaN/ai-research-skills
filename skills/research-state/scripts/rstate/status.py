"""Generated summary of the project state: research/STATUS.md and session context."""
import json
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
    """ISO 8601 time; `Z` or an offset, and no offset means UTC."""
    if not isinstance(ts, str):
        return None
    text = ts.strip()
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    try:
        when = datetime.fromisoformat(text)
    except ValueError:
        return None
    return when if when.tzinfo else when.replace(tzinfo=timezone.utc)


def _age(ts, now):
    when = _parse_ts(ts)
    if when is None:
        return None, "updated at an unknown time"
    hours = (now - when).total_seconds() / 3600
    if hours < 1:
        return hours, f"updated {max(int(hours * 60), 0)}m ago"
    return hours, f"updated {int(hours)}h ago"


def _same_host(host):
    """Hostnames compared without case and domain: gpu1 and GPU1.lab.example.org match."""
    def short(name):
        return str(name or "").split(".")[0].lower()
    return bool(host) and short(host) == short(socket.gethostname())


def _process_missing(run):
    pid = run.get("pid")
    if not _same_host(run.get("host")) or not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0:
        return False
    try:
        os.kill(pid, 0)  # signal 0 checks existence on Linux and macOS alike
    except ProcessLookupError:
        return True
    except (PermissionError, OSError):
        return False
    return False


def _stale_flag(hours, limit):
    if hours is None:
        return "STALE — no update time recorded, check whether it is still running"
    if hours > limit:
        return f"STALE — no update for {int(hours)}h (limit {limit}h), check whether it is still running"
    return None


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
        flags = [f for f in (_stale_flag(hours, rule_set.stale_after_hours),) if f]
        if _process_missing(run):
            flags.append("PROCESS NOT FOUND on this host")
        running.append(f"{_run_line(run_id, run)} — {age}" + "".join(f" — {f}" for f in flags))
    out.append(("Running", running))

    waiting = [f"- {q['id']} — {q['title']}" + (f" (verdict: {q['verdict']})" if q["verdict"] != questions.EMPTY else "")
               for q in qs if q["status"] == "awaiting-approval"]
    for run_id, run in all_runs.items():
        if run.get("status") != "planned":
            continue
        hours, age = _age(run.get("updated"), now)
        line = f"{_run_line(run_id, run)} — planned, not started ({age.replace('updated ', '')})"
        if hours is None or hours > rule_set.stale_after_hours:
            line += " — STALE — still waiting; start it or record it as killed"
        waiting.append(line)
    out.append(("Awaiting your approval", waiting))

    out.append(("Open questions", [
        f"- {q['id']} ({q['status']}) — {q['title']}" + (f" — Next: {q['next']}" if q["next"] != questions.EMPTY else "")
        for q in qs if q["status"] in ("open", "running")]))

    out.append(("Plans", [
        f"- {name} — " + ("TAMPERED — body no longer matches its hash" if state == "tampered" else state)
        for name, state in plans.list_plans(root)]))

    out.append(("Recent decisions", [f"- {d}" for d in decisions.recent(root, 5)]))

    done = [(str(run.get("updated") or ""), run_id, run) for run_id, run in all_runs.items() if run.get("status") in DONE]
    finished = []
    for _, run_id, run in sorted(done, key=lambda item: item[0], reverse=True)[:5]:
        metrics = run.get("metrics")
        tail = ""
        if isinstance(metrics, dict) and metrics:
            tail = " — " + ", ".join(f"{_short(k, 30)}={_short(v, 40)}" for k, v in list(metrics.items())[:8])
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
    rules_part = "## Rules\n- " + _rules_summary(*_load_rules(root)) + " Details: research/rules.md"
    return head + "\n\n" + rules_part + ("\n\n" + body if body else "\n\nNothing recorded yet.") + "\n"


def write(root, now=None):
    path = paths.research_dir(root) / paths.STATUS
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(build(root, now), encoding="utf-8")
    return path


def _rules_summary(rule_set, error):
    if error:
        return f"research/rules.md cannot be parsed ({error}); the guard blocks tool calls until it is fixed."
    if not rule_set.enforce:
        return "Hook enforcement is off for this project."
    return (f"Enforced by hooks: {len(rule_set.protected_paths)} protected path pattern(s), "
            f"{len(rule_set.eval_only_paths)} eval-only path(s) barred from training commands, "
            f"{len(rule_set.protected_processes)} protected process(es); frozen plans, decisions.md, "
            f"questions.md and runs.jsonl change only through the research-state commands. "
            f"Runs are flagged STALE after {rule_set.stale_after_hours}h without an update.")


def _rules_block(root):
    rule_set, error = _load_rules(root)
    lines = ["## Standing rules"]
    prose = "" if error else rule_set.prose.strip()
    if prose:
        lines.append(prose)
    lines.append(_rules_summary(rule_set, error))
    return "\n".join(lines)


def encoded_size(text):
    """Bytes the text takes inside the hook's JSON output (escapes and UTF-8 included)."""
    return len(json.dumps(text, ensure_ascii=False).encode("utf-8"))


def session_context(root, limit=9000, now=None):
    """Rules first, then status, cut to fit the hook's context cap."""
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    head = f"# Research project state (research/) — generated {now.strftime('%Y-%m-%d %H:%M')} UTC"
    rules_block = _rules_block(root)
    omitted = []
    try:
        parts = sections(root, now)
    except Exception as exc:  # the rules must still reach the session
        parts = [("Warnings", [f"- status could not be built ({type(exc).__name__}: {exc}); read research/ directly"])]

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
        if encoded_size(text) <= limit:
            break
        if any(t == title for t, _ in parts):
            parts = [(t, lines) for t, lines in parts if t != title]
            omitted.append(title)
            text = assemble()
    if encoded_size(text) > limit:
        tail = "\n…(cut for length)\n\n" + POINTER + "\n"
        keep = len(text)
        while keep > 0 and encoded_size(text[:keep] + tail) > limit:
            keep -= max(1, (encoded_size(text[:keep] + tail) - limit) // 3)
        text = text[:max(keep, 0)] + tail
    return text
