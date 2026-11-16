"""PreToolUse decisions: which Write/Edit/Bash calls the project rules forbid.

Bash matching is best effort: it reads the command line, not what the
program does once it runs.
"""
import glob
import os
import re
from pathlib import Path
from typing import NamedTuple

from . import paths, plans, rules

SUFFIX = " Rule source: research/rules.md (editing it asks for your confirmation)."
FILE_TOOLS = {"Write": "file_path", "Edit": "file_path", "MultiEdit": "file_path", "NotebookEdit": "notebook_path"}
KEYWORDS = {"if", "then", "else", "elif", "do", "while", "until", "!", "{", "time"}
PLAIN_WRAPPERS = {"nohup", "command", "exec", "nice", "stdbuf", "setsid", "ionice", "builtin"}
XARGS_VALUE_FLAGS = {"-I", "-n", "-P", "-L", "-d", "-s", "-E"}
SHELLS = {"bash", "sh", "zsh", "dash"}
TREE_VERBS = {"rm", "rmdir", "shred"}
FILE_VERBS = {"truncate", "tee"}
COPY_VERBS = {"cp", "mv", "rsync", "install", "ln", "scp"}
KILLERS = {"kill", "pkill", "killall"}
# Commands that only read: naming an eval-only path in them is not training.
READERS = {"grep", "rg", "egrep", "fgrep", "cat", "head", "tail", "less", "more", "wc", "ls", "stat", "file",
           "diff", "cmp", "find", "git", "echo", "printf", "md5sum", "sha256sum", "du", "tree", "awk", "sed",
           "cut", "sort", "uniq", "jq", "cp", "mv", "rsync", "scp", "tar", "zip", "unzip"}
LOG_COMMANDS = {paths.DECISIONS: "decide", paths.QUESTIONS: "rq", paths.RUNS: "run"}
OP_CHARS = set(";|&()<>")
SEP_CHARS = set(";|&()`")
_ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
_SHELL_C = re.compile(r"^-[A-Za-z]*c[A-Za-z]*$")
MAX_GLOB = 2000


class Decision(NamedTuple):
    action: str  # "allow" | "deny" | "ask"
    reason: str = ""


class Target(NamedTuple):
    path: Path
    tree: bool  # the command removes or moves whatever is under this path


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


# --- lexing -----------------------------------------------------------------

def _lex(command):
    """Tokens as (kind, text): 'w' for a word, 'op' for an unquoted operator.

    Keeps what shlex loses: whether `>` or `;` was quoted. Newlines separate
    commands, comments and heredoc bodies are dropped, and nothing here
    raises on malformed input.
    """
    tokens, word, pending = [], None, []
    i, n = 0, len(command)

    def flush():
        nonlocal word
        if word is not None:
            tokens.append(("w", "".join(word)))
            word = None

    while i < n:
        c = command[i]
        if c == "\\":
            if i + 1 < n and command[i + 1] == "\n":
                i += 2
                continue
            word = (word or []) + [command[i + 1] if i + 1 < n else ""]
            i += 2
        elif c == "'":
            end = command.find("'", i + 1)
            end = n if end == -1 else end
            word = (word or []) + [command[i + 1:end]]
            i = end + 1
        elif c == '"':
            j, buf = i + 1, []
            while j < n and command[j] != '"':
                if command[j] == "\\" and j + 1 < n:
                    j += 1
                buf.append(command[j])
                j += 1
            word = (word or []) + ["".join(buf)]
            i = j + 1
        elif c == "\n":
            flush()
            tokens.append(("op", ";"))
            i += 1
            for delimiter in pending:  # skip heredoc bodies
                while i < n:
                    end = command.find("\n", i)
                    end = n if end == -1 else end
                    line = command[i:end]
                    i = min(end + 1, n)
                    if line.strip() == delimiter:
                        break
            pending = []
        elif c in " \t\r":
            flush()
            i += 1
        elif c == "#" and word is None:
            end = command.find("\n", i)
            i = n if end == -1 else end
        elif c == "`":
            flush()
            tokens.append(("op", ";"))
            i += 1
        elif c in OP_CHARS:
            flush()
            j = i
            while j < n and command[j] in OP_CHARS:
                j += 1
            run = command[i:j]
            i = j
            if run.startswith("<<") and not run.startswith("<<<"):
                m = re.match(r"-?\s*(['\"]?)([^\s'\";|&<>()]+)\1", command[i:])
                if m:
                    pending.append(m.group(2))
                    i += m.end()
                continue
            k = next((x for x, ch in enumerate(run) if ch in "<>"), None)
            if k is None:
                tokens.append(("op", run))
            else:
                head = run[:k]
                if head == "&":  # `&>` and `&>>`
                    tokens.append(("op", run))
                else:
                    if head:
                        tokens.append(("op", head))
                    tokens.append(("op", run[k:]))
        else:
            word = (word or []) + [c]
            i += 1
    flush()
    return tokens


def _simple_commands(tokens):
    """Yield (words, redirect targets) for each simple command."""
    words, redirects, i = [], [], 0

    def done():
        nonlocal words, redirects
        result = (words, redirects)
        words, redirects = [], []
        return result

    while i < len(tokens):
        kind, text = tokens[i]
        if kind == "w":
            words.append(text)
            i += 1
            continue
        if ">" in text or "<" in text:
            nxt = tokens[i + 1] if i + 1 < len(tokens) and tokens[i + 1][0] == "w" else None
            if ">" in text:
                duplicate = text.endswith("&") and nxt is not None and (nxt[1].isdigit() or nxt[1] == "-")
                if nxt is not None and not duplicate:
                    redirects.append(nxt[1])
                if words and words[-1].isascii() and words[-1].isdigit():  # the fd in `2> file`
                    words.pop()
            i += 2 if nxt is not None else 1
            continue
        if words or redirects:
            yield done()
        i += 1
    if words or redirects:
        yield done()


def _strip_wrappers(words):
    """Drop keywords, env assignments and wrapper commands in front of the verb."""
    words = list(words)
    while words:
        head = os.path.basename(words[0])
        if _ASSIGNMENT.match(words[0]) or words[0] in KEYWORDS or head in PLAIN_WRAPPERS:
            words.pop(0)
            while head in PLAIN_WRAPPERS and words and words[0].startswith("-"):
                flag = words.pop(0)
                if flag in ("-n",) and words:
                    words.pop(0)
        elif head in ("sudo", "env"):
            words.pop(0)
            while words and (words[0].startswith("-") or _ASSIGNMENT.match(words[0])):
                flag = words.pop(0)
                if flag in ("-u", "-g") and words:
                    words.pop(0)
        elif head == "timeout":
            words.pop(0)
            while words and words[0].startswith("-"):
                flag = words.pop(0)
                if flag in ("-s", "-k") and words:
                    words.pop(0)
            if words:
                words.pop(0)  # the duration
        elif head == "xargs":
            words.pop(0)
            while words and words[0].startswith("-"):
                flag = words.pop(0)
                if flag in XARGS_VALUE_FLAGS and words:
                    words.pop(0)
        else:
            break
    return words


# --- what a command writes --------------------------------------------------

def _expand(arg, cwd):
    """Paths an argument names: itself, plus its glob matches on this machine."""
    out = [paths.resolve(arg, cwd)]
    if set(arg) & set("*?["):
        try:
            pattern = arg if os.path.isabs(os.path.expanduser(arg)) else os.path.join(str(cwd), arg)
            for hit in glob.glob(os.path.expanduser(pattern))[:MAX_GLOB]:
                out.append(paths.resolve(hit, cwd))
        except (OSError, ValueError, re.error):
            pass
    return out


def _copy_targets(verb, rest, cwd):
    """Targets of cp/mv-style commands: the destination, or the files landing in a destination directory."""
    args, dest = [], None
    i = 0
    while i < len(rest):
        w = rest[i]
        if w in ("-t", "--target-directory") and i + 1 < len(rest):
            dest = rest[i + 1]
            i += 2
            continue
        if w.startswith("--target-directory="):
            dest = w.split("=", 1)[1]
        elif not w.startswith("-"):
            args.append(w)
        i += 1
    sources = args
    if dest is None:
        if len(args) < 2:
            return []
        dest, sources = args[-1], args[:-1]
    out = []
    dest_path = paths.resolve(dest, cwd)
    if dest.endswith("/") or dest_path.is_dir():
        for src in sources:
            name = os.path.basename(src.rstrip("/"))
            if name:
                out.append(Target(dest_path / name, False))
    else:
        out.append(Target(dest_path, False))
    if verb == "mv":
        for src in sources:
            out.extend(Target(p, True) for p in _expand(src, cwd))
    return out


def _git_targets(rest, cwd):
    args = [w for w in rest if not w.startswith("-")]
    if not args:
        return []
    sub, operands = args[0], args[1:]
    if sub in ("restore", "rm"):
        return [Target(p, sub == "rm") for a in operands for p in _expand(a, cwd)]
    if sub == "mv":
        return [Target(p, True) for a in operands for p in _expand(a, cwd)]
    if sub == "clean":
        return [Target(p, True) for a in (operands or ["."]) for p in _expand(a, cwd)]
    if sub == "checkout":
        if "--" in rest:
            operands = [w for w in rest[rest.index("--") + 1:] if not w.startswith("-")]
        else:  # without `--`, only arguments that are existing paths are files
            operands = [a for a in operands if paths.resolve(a, cwd).exists()]
        return [Target(p, False) for a in operands for p in _expand(a, cwd)]
    return []


def _analyse(command, cwd, depth=0):
    """(write targets, commands) found in a shell string.

    Each command is (verb, args, words). A leading `cd` changes the
    directory later paths are resolved against.
    """
    targets, commands = [], []
    cwd = Path(cwd)
    for raw_words, redirects in _simple_commands(_lex(command)):
        targets.extend(Target(paths.resolve(r, cwd), False) for r in redirects)
        words = _strip_wrappers(raw_words)
        if not words:
            continue
        verb = os.path.basename(words[0])
        rest = words[1:]
        args = [w for w in rest if not w.startswith("-")]
        commands.append((verb, args, words))
        if verb == "cd":
            if len(args) == 1 and args[0] != "-":
                cwd = paths.resolve(args[0], cwd)
        elif verb in TREE_VERBS:
            targets.extend(Target(p, True) for a in args for p in _expand(a, cwd))
        elif verb in FILE_VERBS:
            targets.extend(Target(p, False) for a in args for p in _expand(a, cwd))
        elif verb in COPY_VERBS:
            targets.extend(_copy_targets(verb, rest, cwd))
        elif verb == "git":
            targets.extend(_git_targets(rest, cwd))
        elif verb == "sed" and any(w == "--in-place" or re.match(r"^-[a-zA-Z]*i", w) for w in rest):
            script_given = any(w in ("-e", "-f") or w.startswith(("--expression", "--file")) for w in rest)
            for a in (args if script_given else args[1:]):
                targets.extend(Target(p, False) for p in _expand(a, cwd))
        elif verb == "dd":
            targets.extend(Target(paths.resolve(w[3:], cwd), False) for w in rest if w.startswith("of=") and w[3:])
        elif depth < 2:
            inner = []
            if verb in SHELLS:
                for index, w in enumerate(rest):
                    if _SHELL_C.match(w):
                        inner = [x for x in rest[index + 1:] if not x.startswith("-")][:1]
                        break
            elif verb == "eval":
                inner = [" ".join(rest)]
            elif verb == "ssh":
                inner = [w for w in args if " " in w]
            for text in inner:
                more_targets, more_commands = _analyse(text, cwd, depth + 1)
                targets.extend(more_targets)
                commands.extend(more_commands)
    return targets, commands


# --- checks -----------------------------------------------------------------

def _is_within(path, ancestor):
    return path == ancestor or ancestor in path.parents


def _check_target(target, root, rule_set):
    """Decision for one path that is about to be written or removed, or None."""
    path = target.path
    top = paths.resolve(".", root)
    research = top / paths.RESEARCH
    shown = os.path.relpath(path, top) if _is_within(path, top) else str(path)
    if path == research / paths.STATUS:
        return _deny("research/STATUS.md is generated; refresh it with `research_state.py status`.")
    for name, command in LOG_COMMANDS.items():
        if path == research / name:
            return _deny(f"research/{name} changes only through `research_state.py {command}`, never by editing the file.")
    if path.parent == research / paths.PLANS and plans.is_frozen(path):
        return _deny(f"{shown} is a frozen plan; add to it with `research_state.py amend {path.stem} --text ...`.")
    if path == research / paths.RULES:
        return _ask("research/rules.md holds the rules the hooks enforce; changing it needs your confirmation.")
    for pattern in rule_set.protected_paths:
        if paths.matches(path, pattern, root):
            return _deny(f'{shown} matches protected path pattern "{pattern}". Copy it and change the copy.')
    if target.tree:
        if _is_within(research, path):
            return _deny(f"{shown} contains research/, the project's rules, decisions and run log.")
        plans_dir = research / paths.PLANS
        if path == plans_dir and any(state != "draft" for _, state in plans.list_plans(root)):
            return _deny("research/plans holds frozen plans; it cannot be moved or removed.")
        for pattern in rule_set.protected_paths:
            if _is_within(paths.literal_prefix(pattern, root), path):
                return _deny(f'{shown} contains paths protected by "{pattern}".')
    return None


def _worst(decisions):
    decisions = [d for d in decisions if d is not None]
    for action in ("deny", "ask"):
        for d in decisions:
            if d.action == action:
                return d
    return None


def _starts_a_word(text, index):
    return index == 0 or text[index - 1] in " /"


def _check_eval_only(commands, cwd, root, rule_set):
    """A training launch that names an eval-only path, within one command."""
    if not rule_set.eval_only_paths or not rule_set.train_command_patterns:
        return None
    for verb, _args, words in commands:
        if verb in READERS:
            continue
        joined = " ".join(words)
        launches = any(_starts_a_word(joined, m.start())
                       for p in rule_set.train_command_patterns for m in re.finditer(p, joined))
        if not launches:
            continue
        pieces = [part for w in words for part in re.split(r"[=,:]", w) if part]
        for pattern in rule_set.eval_only_paths:
            if pattern in joined or any(paths.matches(paths.resolve(x, cwd), pattern, root) for x in pieces):
                return _deny(f'"{pattern}" is eval-only and this looks like a training command.')
    return None


def _check_kill(command, commands, rule_set):
    if not rule_set.protected_processes:
        return None
    killers = [(args, words) for verb, args, words in commands if verb in KILLERS]
    if not killers:
        return None
    for name in rule_set.protected_processes:
        # `kill $(pgrep name)` and `pgrep name | xargs kill` name it elsewhere in the line.
        if name in command:
            return _deny(f'"{name}" is a protected process and must not be killed.')
        for args, _words in killers:
            if any(name in _cmdline(int(a)) for a in args if a.isascii() and a.isdigit()):
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
        if not target:
            return ALLOW
        return _check_target(Target(paths.resolve(target, cwd), False), root, rule_set) or ALLOW

    command = str(tool_input.get("command") or "")
    targets, commands = _analyse(command, cwd)
    found = _worst([_check_target(t, root, rule_set) for t in targets]
                   + [_check_eval_only(commands, cwd, root, rule_set), _check_kill(command, commands, rule_set)])
    return found or ALLOW
