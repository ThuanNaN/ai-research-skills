#!/usr/bin/env python3
"""SessionStart hook: put the project's research state into the session context."""
import json
import sys

from _common import project_root


def emit(text):
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": text}}))


def main():
    try:
        payload = json.load(sys.stdin)
    except ValueError:
        payload = {}
    root = project_root(payload)
    if root is None:
        return 0
    try:
        from rstate import status
        context = status.session_context(root)
    except Exception as exc:  # a broken status must never block the session
        emit(f"research-state: could not build status ({type(exc).__name__}: {exc}). Read research/ directly.")
        return 0
    try:
        status.write(root)
    except Exception:  # STATUS.md is a convenience; the context matters more
        pass
    emit(context)
    return 0


if __name__ == "__main__":
    sys.exit(main())
