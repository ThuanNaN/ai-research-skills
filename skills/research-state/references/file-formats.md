# research/ file formats

## rules.md

Front matter between two `---` lines is enforced by hooks. Everything after it
is prose the agent reads at the start of every session.

```yaml
---
enforce: true
stale_after_hours: 24
protected_paths:
  - "scripts/rq1_*.py"
  - "/data/myproject/outputs/step*/**"
eval_only_paths:
  - "data/heldout.json"
train_command_patterns:
  - "train\\.py|accelerate launch"
protected_processes:
  - "llama-server"
---
- Do not start training without my approval.
```

Grammar (a small subset of YAML, parsed without dependencies):

- `key: value` where the value is `true`, `false` or a whole number.
- `key:` followed by indented `- item` lines. An item is plain text (a ` #`
  starts a comment), `'single-quoted'` (`''` for a quote) or
  `"double-quoted"` with JSON escapes, where a regex backslash is written `\\`.
- `key: []` for an empty list, or `key: ["a", "b"]` with double-quoted items.
- `#` starts a comment. Unknown keys are an error.

| Key | Meaning |
|---|---|
| `enforce` | `false` turns the guard off for this project. |
| `stale_after_hours` | A running run with no update for this long is flagged STALE. |
| `protected_paths` | Globs. No write, edit, overwrite, move or delete. `*` stays inside one directory, `**` crosses directories, and a pattern on a directory covers everything under it. Relative patterns start at the project root. |
| `eval_only_paths` | Paths that must not appear in a command matching `train_command_patterns`. |
| `train_command_patterns` | Regular expressions that identify a training launch. |
| `protected_processes` | Names that `kill`, `pkill` and `killall` must not target. |

If the front matter cannot be parsed, the guard blocks Bash, Write and Edit
until the file is fixed; editing `rules.md` itself stays possible.

## decisions.md

```
## 2026-11-03 — Comparison point is the 20k checkpoint
Why: 100k steps would take too long; 20k answers the question.
Supersedes: —
```

Append-only. Written by `decide`.

## questions.md

```
## RQ1 — Does the method help on held-out instructions?
- Status: awaiting-approval
- Verdict: inconclusive
- Evidence: reports/rq1.md, r20261116-001
- Next: run seed 2
```

Status is one of `open`, `running`, `awaiting-approval`, `closed`. Written by
`rq`; other text in the file is kept.

## runs.jsonl

One JSON object per line, one line per event. The latest event of a `run_id` is
its state; fields from earlier events carry over.

```json
{"run_id": "r20261116-001", "ts": "2026-11-16T09:12:44Z", "event": "started", "rq": "RQ1", "host": "gpu-box", "gpu": "0", "cmd": "python train.py --seed 1", "cwd": "/home/me/project", "git_commit": "4f2a…", "git_dirty": false, "seed": 1, "pid": 41233, "log_path": "logs/s1.log"}
{"run_id": "r20261116-001", "ts": "2026-11-16T13:40:02Z", "event": "finished", "metrics": {"success_rate": 0.34}}
```

Events: `planned`, `started`, `finished`, `failed`, `killed`, `note`.
Other fields: `config`, `checkpoint`, `output_dir`, `wandb`, `note`.
`git_dirty` ignores changes under `research/`. For a run on another host,
`cwd`, `git_commit` and `git_dirty` are whatever the caller passed.

## plans/

`research/plans/NAME.md`. `freeze` adds a first line:

```
Frozen: 2026-11-16 (sha256 <hash of the plan body>)
```

The hash covers the text after that line and before the first
`## Amendment` heading. `amend` appends:

```
## Amendment 2026-11-18

Found near-duplicates between train and test; adding an exploratory analysis.
```

A frozen plan whose body no longer matches its hash shows as TAMPERED in
`STATUS.md`.

## STATUS.md

Generated on every command and at every session start; gitignored. Sections:
Running, Awaiting your approval, Open questions, Plans, Recent decisions,
Recently finished, Warnings.

## What the hooks block

| Action | Result |
|---|---|
| Write or edit a `protected_paths` match, or `rm`/`mv`/overwrite it in Bash | denied |
| Edit a frozen plan | denied (use `amend`) |
| Write `decisions.md`, `questions.md`, `runs.jsonl`, `STATUS.md` directly | denied (use the commands) |
| A training command that names an eval-only path | denied |
| `kill`/`pkill`/`killall` on a protected process | denied |
| Edit `rules.md` | asks the user |
| Read, run, or copy *from* a protected file | allowed |
