"""Append-only event log of runs: research/runs.jsonl."""
import fcntl
import json
import socket
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from . import paths

EVENTS = ("planned", "started", "finished", "failed", "killed", "note")
OPENING = ("planned", "started")


def _git(cwd, *args):
    try:
        out = subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout.strip() if out.returncode == 0 else None


def git_info(cwd):
    """(commit, dirty) for the repo at cwd; (None, None) outside a git repo.

    Changes under research/ do not count as dirty: bookkeeping would
    otherwise mark every run dirty.
    """
    if _git(cwd, "rev-parse", "--is-inside-work-tree") != "true":
        return None, None
    commit = _git(cwd, "rev-parse", "HEAD")
    status = _git(cwd, "status", "--porcelain", "--", ":(top)", ":(top,exclude)research")
    return commit, (bool(status) if status is not None else None)


def _parse(text):
    """(records, number of unreadable lines)."""
    records, bad = [], 0
    for line in text.splitlines():
        if not line.strip():
            continue
        try:
            rec = json.loads(line)
        except ValueError:
            bad += 1
            continue
        if (isinstance(rec, dict) and isinstance(rec.get("run_id"), str)
                and isinstance(rec.get("ts"), str) and rec.get("event") in EVENTS):
            records.append(rec)
        else:
            bad += 1
    return records, bad


def _merge(records):
    runs = {}
    for rec in records:
        run = runs.setdefault(rec["run_id"], {"created": rec.get("ts")})
        run.update(rec)
        if rec["event"] != "note":
            run["status"] = rec["event"]
        run.setdefault("status", "note")
        run["updated"] = rec.get("ts")
    return runs


def load(root):
    """(runs by id in first-seen order, count of unreadable lines)."""
    path = paths.research_dir(root) / paths.RUNS
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except FileNotFoundError:
        return {}, 0
    records, bad = _parse(text)
    return _merge(records), bad


def _next_id(known, day):
    prefix = f"r{day}-"
    used = [int(k[len(prefix):]) for k in known if k.startswith(prefix) and k[len(prefix):].isdigit()]
    return f"{prefix}{max(used, default=0) + 1:03d}"


def append_event(root, event, run_id=None, now=None, **fields):
    """Append one event and return the record written."""
    if event not in EVENTS:
        raise ValueError(f"unknown run event {event!r}; expected one of {', '.join(EVENTS)}")
    now = now or datetime.now(timezone.utc)
    now = now.astimezone(timezone.utc)
    record = {k: v for k, v in fields.items() if v is not None}
    if event == "started":
        local = socket.gethostname()
        record.setdefault("host", local)
        if record["host"] == local:
            # Only a local run can be inspected; for a run on another host
            # the caller passes that host's path and commit.
            commit, dirty = git_info(root)
            record.setdefault("cwd", str(Path.cwd()))
            record.setdefault("git_commit", commit)
            record.setdefault("git_dirty", dirty)
        for key in ("cwd", "git_commit", "git_dirty"):
            record.setdefault(key, None)

    path = paths.research_dir(root) / paths.RUNS
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a+", encoding="utf-8", errors="replace") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        f.seek(0)
        existing = f.read()
        known = {r["run_id"] for r in _parse(existing)[0]}
        if run_id is None:
            if event not in OPENING:
                raise ValueError(f"run event {event!r} needs a run id")
            run_id = _next_id(known, now.strftime("%Y%m%d"))
        elif run_id not in known and event not in OPENING:
            raise ValueError(f"unknown run id {run_id!r}")
        full = {"run_id": run_id, "ts": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "event": event, **record}
        prefix = "" if not existing or existing.endswith("\n") else "\n"
        f.write(prefix + json.dumps(full, ensure_ascii=False, sort_keys=False) + "\n")
    return full
