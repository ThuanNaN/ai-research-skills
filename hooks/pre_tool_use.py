#!/usr/bin/env python3
"""PreToolUse hook: deny or confirm tool calls the project's rules forbid."""
import json
import sys
from pathlib import Path

from _common import project_root


def main():
    payload = json.load(sys.stdin)
    if not isinstance(payload, dict):
        raise ValueError("hook input is not a JSON object")
    root = project_root(payload)
    if root is None:
        return 0
    from rstate import guard
    cwd = Path(payload.get("cwd") or root)
    decision = guard.decide(payload.get("tool_name", ""), payload.get("tool_input") or {}, cwd, root)
    if decision.action != "allow":
        print(json.dumps({"hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": decision.action,
            "permissionDecisionReason": decision.reason,
        }}))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # fail closed: exit 2 blocks the tool call
        print(f"research-state guard failed ({type(exc).__name__}: {exc}); blocking to be safe.", file=sys.stderr)
        sys.exit(2)
