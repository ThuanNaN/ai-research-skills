---
name: research-state
description: Keeps a research project's standing rules, decisions, research questions, frozen plans and experiment runs in files under research/, so the state survives new sessions and context compaction. Use when starting or resuming research work in a project, when the user approves or changes a decision, when an experiment run is launched, checked or finished, when a plan is frozen or amended, or when the user asks where things stand or what comes next.
---

# research-state

Project state lives in `research/` in the project repo, not in the conversation.
You and the user both read it; only the CLI below writes the structured files.

```
research/
  rules.md       standing rules: front matter is enforced by hooks, prose is guidance
  decisions.md   append-only log of decisions
  questions.md   research questions: status, verdict, evidence, next step
  runs.jsonl     append-only event log of runs
  plans/         plans; a frozen plan is immutable
  STATUS.md      generated summary: running, awaiting approval, next
```

## Commands

Run the CLI from anywhere inside the project:

```
RS="python3 ${CLAUDE_SKILL_DIR}/scripts/research_state.py"
```

If `CLAUDE_SKILL_DIR` is not set, use this skill's base directory instead.

| Command | Use |
|---|---|
| `$RS init` | Create `research/` from templates. Safe to repeat; never overwrites. |
| `$RS status` | Regenerate and print `STATUS.md`. |
| `$RS decide --title T --why W [--supersedes S]` | Record a decision. |
| `$RS rq ID [--title T] [--status S] [--verdict V] [--evidence E]... [--next N]` | Add or update a research question. Status: `open`, `running`, `awaiting-approval`, `closed`. |
| `$RS run plan --cmd C [--rq ID] ...` | Record a run that waits for approval. Prints the run id. |
| `$RS run start --cmd C [--id ID] [--rq] [--seed] [--gpu] [--pid] [--log] [--output-dir] [--config] [--checkpoint] [--wandb]` | Record a launch. Prints the run id. Fills host, cwd, commit and dirty flag for local runs. |
| `$RS run note --id ID --note TEXT` | Record progress (step, ETA) without changing status. |
| `$RS run finish --id ID [--metric K=V]...` | Record a result. Also `run fail`, `run kill`. |
| `$RS freeze NAME` | Freeze `research/plans/NAME.md`. |
| `$RS amend NAME --text T` | Append a dated amendment to a frozen plan. |

Every command refreshes `STATUS.md`.

## When to record what

- **The user approves, rejects or changes direction** → `decide`, with the reason
  in their terms. A changed decision is a new entry with `--supersedes`.
- **Before launching any job that runs longer than a few minutes** → `run start`
  with the exact command, seed, GPU, pid, log path and output directory. For a
  job on another machine pass `--host`, `--cwd` and `--commit` for that machine;
  nothing can be read from it here.
- **A job that needs approval first** → `run plan`, then `run start --id` once
  approved.
- **Each time you check a job** → `run note` with step and ETA, or `run finish`
  / `run fail` / `run kill`. A run with no update for 24 hours shows as STALE.
- **A research question starts, waits for the user, or is answered** → `rq`.
  Put report paths and run ids in `--evidence`. A verdict of "inconclusive" is
  a verdict; record it as such.
- **A plan is agreed** → write it to `research/plans/NAME.md`, then `freeze`.
  Changes after that go through `amend`, with the date and the reason.

## How to behave

- Do the bookkeeping without asking. Ask only when it is unclear whether a
  remark is a decision.
- At the start of a session the hook has already put the rules and status in
  your context. If the user asks where things stand, run `status` and answer
  from it: what is running, what waits for them, what comes next.
- Never hand-edit `decisions.md`, `questions.md`, `runs.jsonl` or `STATUS.md`,
  and never edit a frozen plan. Use the commands.
- When a hook denies an action, tell the user which rule fired. Do not work
  around it with another tool or a script. If the rule is wrong, propose the
  change to `rules.md`; the edit asks for their confirmation.
- A rule that must hold goes in the front matter of `rules.md`, not only in
  prose. Prose is a request; front matter is enforced.
- On `init`, look for standing rules in the project's CLAUDE.md and memory and
  offer to move them into `rules.md`.
- Report what a run recorded, not what you remember: a number you state should
  be traceable to a run id.

## Reference

File formats, the `rules.md` front matter grammar, and what the hooks block:
[references/file-formats.md](references/file-formats.md).
