#!/usr/bin/env python3
"""research-state CLI: the only writer of the structured files in research/."""
import argparse
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from rstate import decisions, paths, plans, questions, runs, status  # noqa: E402
from rstate.rules import RulesError  # noqa: E402

TEMPLATES = Path(__file__).resolve().parent.parent / "templates"
RUN_EVENTS = {"plan": "planned", "start": "started", "finish": "finished",
              "fail": "failed", "kill": "killed", "note": "note"}
IGNORE_LINE = "research/STATUS.md"


def _number(text):
    try:
        return int(text)
    except ValueError:
        try:
            return float(text)
        except ValueError:
            return text


def cmd_init(root, args):
    folder = paths.research_dir(root)
    (folder / paths.PLANS).mkdir(parents=True, exist_ok=True)
    for name in (paths.RULES, paths.DECISIONS, paths.QUESTIONS):
        if not (folder / name).exists():
            shutil.copyfile(TEMPLATES / name, folder / name)
    ignore = root / ".gitignore"
    text = ignore.read_text(encoding="utf-8") if ignore.exists() else ""
    if IGNORE_LINE not in text.splitlines():
        sep = "" if not text or text.endswith("\n") else "\n"
        ignore.write_text(f"{text}{sep}{IGNORE_LINE}\n", encoding="utf-8")
    print(f"research state ready in {folder}")


def cmd_status(root, args):
    print(status.build(root), end="")


def cmd_decide(root, args):
    print(decisions.append(root, args.title, args.why, supersedes=args.supersedes))


def cmd_rq(root, args):
    q = questions.upsert(root, args.id, title=args.title, status=args.status, verdict=args.verdict,
                         evidence=args.evidence, next_step=args.next)
    print(f"{q['id']} — {q['status']}")


def cmd_run(root, args):
    metrics = {}
    for item in args.metric or []:
        key, sep, value = item.partition("=")
        if not sep or not key:
            raise ValueError(f"--metric takes KEY=VALUE, got {item!r}")
        metrics[key] = _number(value)
    record = runs.append_event(
        root, RUN_EVENTS[args.action], run_id=args.id,
        rq=args.rq, host=args.host, gpu=args.gpu, cmd=args.cmd, cwd=args.cwd,
        git_commit=args.commit, seed=None if args.seed is None else _number(args.seed),
        config=args.config, checkpoint=args.checkpoint, output_dir=args.output_dir,
        log_path=args.log, pid=args.pid, wandb=args.wandb,
        metrics=metrics or None, note=args.note)
    print(record["run_id"])


def cmd_freeze(root, args):
    print(f"frozen {args.name} (sha256 {plans.freeze(root, args.name)})")


def cmd_amend(root, args):
    plans.amend(root, args.name, args.text)
    print(f"amended {args.name}")


def build_parser():
    parser = argparse.ArgumentParser(prog="research_state.py", description=__doc__)
    parser.add_argument("--root", help="project root (default: nearest directory holding research/)")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("init", help="create research/ with templates").set_defaults(func=cmd_init)
    sub.add_parser("status", help="regenerate and print STATUS.md").set_defaults(func=cmd_status)

    p = sub.add_parser("decide", help="append a decision")
    p.add_argument("--title", required=True)
    p.add_argument("--why", required=True)
    p.add_argument("--supersedes")
    p.set_defaults(func=cmd_decide)

    p = sub.add_parser("rq", help="add or update a research question")
    p.add_argument("id")
    p.add_argument("--title")
    p.add_argument("--status", help=", ".join(questions.STATUSES))
    p.add_argument("--verdict")
    p.add_argument("--evidence", action="append", help="path or run id; repeatable")
    p.add_argument("--next")
    p.set_defaults(func=cmd_rq)

    p = sub.add_parser("run", help="record a run event")
    p.add_argument("action", choices=list(RUN_EVENTS))
    p.add_argument("--id", help="run id (required except for plan/start)")
    for flag in ("--rq", "--host", "--gpu", "--cmd", "--cwd", "--commit", "--seed", "--config",
                 "--checkpoint", "--output-dir", "--log", "--wandb", "--note"):
        p.add_argument(flag)
    p.add_argument("--pid", type=int)
    p.add_argument("--metric", action="append", help="KEY=VALUE; repeatable")
    p.set_defaults(func=cmd_run)

    p = sub.add_parser("freeze", help="freeze a plan in research/plans/")
    p.add_argument("name")
    p.set_defaults(func=cmd_freeze)

    p = sub.add_parser("amend", help="append an amendment to a frozen plan")
    p.add_argument("name")
    p.add_argument("--text", required=True)
    p.set_defaults(func=cmd_amend)
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        root = Path(args.root).resolve() if args.root else paths.find_root(Path.cwd())
        if args.command != "init" and not paths.research_dir(root).is_dir():
            raise ValueError(f"no research/ directory in {root}; run the init command first")
        args.func(root, args)
    except (ValueError, FileNotFoundError, RulesError, OSError) as exc:
        print(f"research-state: {' '.join(str(exc).split())}", file=sys.stderr)
        return 1
    try:
        status.write(root)
    except Exception as exc:  # the command itself succeeded; do not invite a retry
        print(f"research-state: recorded, but STATUS.md could not be refreshed ({exc})", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
