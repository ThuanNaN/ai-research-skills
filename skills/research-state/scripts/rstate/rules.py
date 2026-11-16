"""Parser for research/rules.md: enforced front matter plus prose."""
import json
from dataclasses import dataclass, field

from . import paths

LIST_KEYS = ("protected_paths", "eval_only_paths", "train_command_patterns", "protected_processes")
BOOL_KEYS = ("enforce",)
INT_KEYS = ("stale_after_hours",)


class RulesError(Exception):
    """research/rules.md front matter cannot be parsed."""


@dataclass
class Rules:
    enforce: bool = True
    protected_paths: list = field(default_factory=list)
    eval_only_paths: list = field(default_factory=list)
    train_command_patterns: list = field(default_factory=list)
    protected_processes: list = field(default_factory=list)
    stale_after_hours: int = 24
    prose: str = ""


def _strip_comment(rest, lineno):
    rest = rest.strip()
    if rest and not rest.startswith("#"):
        raise RulesError(f"line {lineno}: unexpected text {rest!r}")


def _quoted(text, lineno):
    """Decode a leading double-quoted string; the rest may only be a comment."""
    text = text.strip()
    if not text.startswith('"'):
        raise RulesError(f"line {lineno}: expected a double-quoted string, got {text!r}")
    try:
        value, end = json.JSONDecoder().raw_decode(text)
    except ValueError as exc:
        raise RulesError(f"line {lineno}: bad string ({exc})") from None
    _strip_comment(text[end:], lineno)
    return value


def parse(text):
    rules = Rules()
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        rules.prose = text
        return rules
    try:
        end = next(i for i in range(1, len(lines)) if lines[i].strip() == "---")
    except StopIteration:
        raise RulesError("front matter is not closed with a '---' line") from None
    rules.prose = "\n".join(lines[end + 1:]) + ("\n" if len(lines) > end + 1 else "")

    current = None
    for lineno, raw in enumerate(lines[1:end], start=2):
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("- ") or stripped == "-":
            if current is None or not raw[:1].isspace():
                raise RulesError(f"line {lineno}: list item outside a list")
            getattr(rules, current).append(_quoted(stripped[1:], lineno))
            continue
        if raw[:1].isspace() or ":" not in stripped:
            raise RulesError(f"line {lineno}: expected 'key: value', got {stripped!r}")
        key, _, rest = stripped.partition(":")
        key, rest = key.strip(), rest.strip()
        current = None
        if key in LIST_KEYS:
            _strip_comment(rest, lineno)
            setattr(rules, key, [])
            current = key
        elif key in BOOL_KEYS:
            word = rest.split("#", 1)[0].strip()
            if word not in ("true", "false"):
                raise RulesError(f"line {lineno}: {key} must be true or false, got {word!r}")
            setattr(rules, key, word == "true")
        elif key in INT_KEYS:
            word = rest.split("#", 1)[0].strip()
            if not word.isdigit():
                raise RulesError(f"line {lineno}: {key} must be a whole number, got {word!r}")
            setattr(rules, key, int(word))
        else:
            raise RulesError(f"line {lineno}: unknown key {key!r}")
    return rules


def load(root):
    """Rules for a project. A missing rules.md means nothing is enforced."""
    path = paths.research_dir(root) / paths.RULES
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except FileNotFoundError:
        return Rules(enforce=False)
    return parse(text)
