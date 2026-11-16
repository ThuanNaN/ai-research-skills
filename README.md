# ai-research-skills

Skills and hooks for doing AI/ML research (LLM, VLA, RL) with a coding agent.
The agent can run the work; these skills keep the evidence and the decisions
where you can check them.

The first skill, **research-state**, keeps a project's standing rules,
decisions, research questions, frozen plans and experiment runs in files under
`research/`. A hook puts that state back into the agent's context at every new
session, resume and context compaction, so you stop re-typing "same rules as
before" and both of you know what is running, what waits for your approval and
what comes next.

## Requirements

- Claude Code
- Python 3.9 or later on `PATH` as `python3` (standard library only)

## Install

```
/plugin marketplace add ThuanNaN/ai-research-skills
/plugin install ai-research@ai-research-skills
```

Other agents that read the Agent Skills format can install the skill alone with
`npx skills add ThuanNaN/ai-research-skills`. The hooks are Claude Code only;
without them the rules are guidance, not enforcement.

## Quick start

1. In your project, ask the agent to set up research state. It runs `init`,
   which creates `research/` and offers to move standing rules out of your
   CLAUDE.md.
2. Open `research/rules.md` and list what must hold:

   ```yaml
   ---
   enforce: true
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

3. Work as usual. The agent records decisions when you approve something,
   records each run when it launches or checks one, and freezes plans you agree
   on. Open `research/STATUS.md` at any time.

Commit `research/` with your code. `STATUS.md` is generated and gitignored.

## What the hooks do

- **At session start, resume, `/clear` and after compaction:** inject the
  standing rules and the current status (at most 9,000 characters).
- **Before Write, Edit and Bash:**
  - deny writing, overwriting, moving or deleting a protected path;
  - deny editing a frozen plan (amend it instead);
  - deny hand-editing the decision log, questions file, run log or status;
  - deny a training command that names an eval-only path;
  - deny killing a protected process;
  - ask you before any change to `rules.md`.

Reading, running or copying from a protected file is always allowed, so
"copy the script, then change the copy" works. Every denial names the rule
that fired. To turn enforcement off for a project, set `enforce: false`.

## Limitations

- Bash matching is best effort. The guard reads the command line, not what a
  program does: a Python script can still open or overwrite a protected file.
  For OS-level enforcement, use the Claude Code sandbox as well.
- A command wrapped in `ssh host "…"` is inspected as text; relative paths in
  it are resolved against the local directory.
- The eval-only check sees only the command line. A training config file that
  points at an eval-only path is not caught.
- Process liveness is checked only for runs on the local host. Runs on other
  machines are flagged stale by age alone.
- If `rules.md` cannot be parsed, the guard blocks Bash, Write and Edit until
  it is fixed. Editing `rules.md` itself stays possible.
- The state lives on the machine where the agent runs. Nothing is written to
  remote hosts.

## Roadmap

One skill per stage of the research loop, each producing an artifact you can
check: job monitoring across machines; paper cards and a literature log; idea
and novelty checks; experiment design with a frozen decision rule; execution
sanity gates; analysis by the pre-registered rule; writing with traceable
numbers and verified citations; an independent reviewer.

## Development

```
python3 -m venv .venv && .venv/bin/pip install pytest
.venv/bin/python -m pytest
```

Design and plan: `docs/superpowers/specs/`, `docs/superpowers/plans/`.
