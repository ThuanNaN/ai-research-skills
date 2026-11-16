"""PreToolUse decisions: which Write/Edit/Bash calls the project rules forbid.

Bash matching is best effort: it reads the command line, not what the
program does once it runs.
"""
import os
import re
import shlex
from pathlib import Path
from typing import NamedTuple

from . import paths, plans, rules

SUFFIX = " Rule source: research/rules.md (editing it asks for your confirmation)."
FILE_TOOLS = {"Write": "file_path", "Edit": "file_path", "MultiEdit": "file_path", "NotebookEdit": "notebook_path"}
WRAPPERS = {"sudo", "nohup", "time", "env", "command", "exec", "nice", "stdbuf"}
SHELLS = {"bash", "sh", "zsh", "dash"}
ALL_ARGS = {"rm", "mv", "rmdir", "truncate", "shred", "tee", "touch"}
SKIP_FIRST = {"chmod", "chown", "chgrp"}
LAST_ARG = {"cp", "rsync", "install", "ln", "scp"}
KILLERS = {"kill", "pkill", "killall"}
LOG_COMMANDS = {paths.DECISIONS: "decide", paths.QUESTIONS: "rq", paths.RUNS: "run"}
_SEPARATOR = re.compile(r"^[;|&()]+$")
_ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")


class Decision(NamedTuple):
    action: str  # "allow" | "deny" | "ask"
    reason: str = ""


ALLOW = Decision("allow")


def _deny(reason):
    return Decision("deny", reason + SUFFIX)


def _ask(reason):
    return Decision("ask", reason + SUFFIX)


def _cmdline(pid):
    try:
        with open(f"/proc/{pid}/cmdline", "rb") as f:
            return f.read().replace(b"\0", b" ").decode("utf-8", "replace")
    except OSError:
        return ""


def _tokens(command):
    try:
        lexer = shlex.shlex(command, posix=True, punctuation_chars=True)
        lexer.whitespace_split = True
        return list(lexer)
    except ValueError:  # unbalanced quote: fall back to a plain split
        return command.split()


def _simple_commands(tokens):
    current = []
    for token in tokens:
        if _SEPARATOR.match(token):
            if current:
                yield current
            current = []
        else:
            current.append(token)
    if current:
        yield current


def _split_redirects(tokens):
    """(words, redirect targets) of one simple command."""
    words, targets, i = [], [], 0
    while i < len(tokens):
        token = tokens[i]
        if ">" in token and set(token) <= set("<>&|"):
            nxt = tokens[i + 1] if i + 1 < len(tokens) else None
            duplicate = token.endswith("&") and nxt is not None and (nxt.isdigit() or nxt == "-")
            if nxt is not None and not duplicate:
                targets.append(nxt)
            if words and words[-1].isdigit():  # the fd in `2> file`
                words.pop()
            i += 2
            continue
        if "<" in token and set(token) <= set("<>&|"):
            i += 2  # input redirect: not a write
            continue
        words.append(token)
        i += 1
    return words, targets


def _analyse(command, depth=0):
    """(write targets, commands as (verb, args, words)) found in a shell string."""
    targets, commands = [], []
    for simple in _simple_commands(_tokens(command)):
        words, redirects = _split_redirects(simple)
        targets.extend(redirects)
        while words and (_ASSIGNMENT.match(words[0]) or os.path.basename(words[0]) in WRAPPERS):
            wrapper = os.path.basename(words.pop(0))
            if wrapper in ("sudo", "env"):
                while words and (words[0].startswith("-") or _ASSIGNMENT.match(words[0])):
                    words.pop(0)
        if not words:
            continue
        verb = os.path.basename(words[0])
        rest = words[1:]
        args = [w for w in rest if not w.startswith("-")]
        commands.append((verb, args, words))
        if verb in ALL_ARGS:
            targets.extend(args)
        elif verb in SKIP_FIRST:
            targets.extend(args[1:])
        elif verb in LAST_ARG:
            targets.extend(args[-1:] if len(args) > 1 else [])
        elif verb == "sed" and any(w == "--in-place" or re.match(r"^-[a-zA-Z]*i", w) for w in rest):
            script_given = any(w in ("-e", "-f") or w.startswith("--expression") or w.startswith("--file") for w in rest)
            targets.extend(args if script_given else args[1:])
        elif verb == "dd":
            targets.extend(w[3:] for w in rest if w.startswith("of="))
        elif depth < 2 and (verb in SHELLS and "-c" in rest or verb == "ssh"):
            for inner in (w for w in args if " " in w or verb in SHELLS):
                more_targets, more_commands = _analyse(inner, depth + 1)
                targets.extend(more_targets)
                commands.extend(more_commands)
    return targets, commands


def _check_target(target, cwd, root, rule_set):
    """Decision for one path that is about to be written, or None."""
    path = paths.resolve(target, cwd)
    research = paths.resolve(paths.RESEARCH, root)
    shown = os.path.relpath(path, paths.resolve(".", root)) if path.is_relative_to(paths.resolve(".", root)) else str(path)
    if path == research / paths.STATUS:
        return _deny("research/STATUS.md is generated; refresh it with `research_state.py status`.")
    for name, command in LOG_COMMANDS.items():
        if path == research / name:
            return _deny(f"research/{name} changes only through `research_state.py {command}`, never by editing the file.")
    if path.parent == research / paths.PLANS and plans.is_frozen(path):
        return _deny(f"{shown} is a frozen plan; add to it with `research_state.py amend {path.stem} --text ...`.")
    for pattern in rule_set.protected_paths:
        if paths.matches(path, pattern, root):
            return _deny(f'{shown} matches protected path pattern "{pattern}". Copy it and change the copy.')
    if path == research / paths.RULES:
        return _ask("research/rules.md holds the rules the hooks enforce; changing it needs your confirmation.")
    return None


def _worst(decisions):
    decisions = [d for d in decisions if d is not None]
    for action in ("deny", "ask"):
        for d in decisions:
            if d.action == action:
                return d
    return None


def _check_eval_only(command, cwd, root, rule_set):
    if not rule_set.eval_only_paths:
        return None
    if not any(re.search(p, command) for p in rule_set.train_command_patterns):
        return None
    words = []
    for token in _tokens(command):
        words.extend(part for part in re.split(r"[=,:]", token) if part)
    for pattern in rule_set.eval_only_paths:
        literal = pattern in command
        if literal or any(paths.matches(paths.resolve(w, cwd), pattern, root) for w in words):
            return _deny(f'"{pattern}" is eval-only and this looks like a training command.')
    return None


def _check_kill(commands, rule_set):
    if not rule_set.protected_processes:
        return None
    for verb, args, words in commands:
        if verb not in KILLERS:
            continue
        candidates = [" ".join(words)] + [_cmdline(int(a)) for a in args if a.isdigit()]
        for name in rule_set.protected_processes:
            if any(name in text for text in candidates):
                return _deny(f'"{name}" is a protected process and must not be killed.')
    return None


def decide(tool_name, tool_input, cwd, root):
    """What to do with a tool call under the project's rules."""
    root, cwd = Path(root), Path(cwd)
    if not paths.research_dir(root).is_dir():
        return ALLOW
    file_key = FILE_TOOLS.get(tool_name)
    if file_key is None and tool_name != "Bash":
        return ALLOW
    tool_input = tool_input if isinstance(tool_input, dict) else {}

    try:
        rule_set = rules.load(root)
    except rules.RulesError as exc:
        target = tool_input.get(file_key) if file_key else None
        if target and paths.resolve(target, cwd) == paths.resolve(paths.RESEARCH, root) / paths.RULES:
            return _ask(f"research/rules.md cannot be parsed ({exc}); this edit can fix it.")
        return _deny(f"research/rules.md cannot be parsed ({exc}). Fix that file first.")
    if not rule_set.enforce:
        return ALLOW

    if file_key:
        target = tool_input.get(file_key)
        return (_check_target(target, cwd, root, rule_set) if target else None) or ALLOW

    command = str(tool_input.get("command") or "")
    targets, commands = _analyse(command)
    found = _worst([_check_target(t, cwd, root, rule_set) for t in targets]
                   + [_check_eval_only(command, cwd, root, rule_set), _check_kill(commands, rule_set)])
    return found or ALLOW
