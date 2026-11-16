# Design: `research-state` — project state that survives sessions

Date: 2026-11-16
Status: draft, awaiting owner approval

## 1. Intent and why

`ai-research-skills` is a public Claude Code plugin (English) for experienced
AI researchers working on LLM/NLP and VLA. The long-term plan is a set of skills
that follow the 8-stage research loop (question → literature → idea → design →
execution → analysis → writing → review), where each stage produces a checkable
artifact and hard rules are enforced by hooks rather than prompts
(inspired by the "AI Vibe-Researcher" article, AI Viet Nam 2026).

This document covers only the **first sub-project**: the plugin skeleton plus
one skill, `research-state`, and its hooks. The owner picked this as the
highest-value piece.

Evidence from the owner's own Claude Code history on a real VLA research
project (3 sessions, ~316 user messages over three weeks). Project details are
deliberately left out of this public document:

- The context was compacted ~8 times. After compaction both the agent and the
  owner lost track of where the work stood.
- Nearly every prompt restated the same standing rules: don't kill processes
  you didn't start; don't edit old scripts (copy then edit); don't overwrite
  old outputs; don't train without approval; a named held-out set is eval-only.
  These lived in prompts and one memory file, not in the project.
- Decisions were made in chat and had to be re-explained: e.g. which checkpoint
  is the comparison point; which RQ is closed and its verdict.
- Plans were uploaded into chat instead of living in the repo.
- The owner asked for progress ("done yet? how long left?") ~60–70 times
  across several GPU machines.

The fix: **project state lives in files in the repo, not in the conversation**,
and is re-injected automatically at session start, resume, and after compaction.

## 2. Goals

1. A new session (or a post-compaction session) knows, without the owner
   re-typing anything: the active rules, the decision log, the status of each
   research question, the frozen plans, and the recorded runs.
2. The owner can open one file and see: what is running, what is waiting for
   their approval, what comes next.
3. Rules that matter are enforced by hooks, configured per project, with a
   clear escape hatch.
4. Shareable: installable as a Claude Code plugin from GitHub; the skill also
   follows the open Agent Skills `SKILL.md` format so other agents can read it.
5. Works for any Python project — HF/TRL/accelerate, LeRobot/openpi, or plain
   PyTorch scripts. No dependency on a specific framework.

## 3. Non-goals (this sub-project)

- Live job monitoring, GPU polling across machines, ETA estimation (later skill;
  this one only records what the agent launched and its last known state).
- W&B API integration (only store the run ID/URL as a field).
- The other stage skills (paper cards, novelty check, analysis, writing, review).
- Overleaf sync.

## 4. Anti-goals (would be a failure even if it works)

- **Noise**: the skill asks confirmation for routine bookkeeping, or floods
  context. Injected context must stay short (target ≤ ~150 lines).
- **File sprawl**: more state files than the owner can keep in their head.
- **Lying status**: `STATUS.md` claims a run is running when it died. Every run
  status shows when it was last updated and by whom; stale entries are flagged,
  not hidden.
- **Hooks that block legitimate work with no way out**: every denial says which
  rule fired and how to override it.
- **Rewriting history**: decisions and frozen plans are append-only.

## 5. Design (decided)

### 5.1 Location

State lives in `research/` at the root of the project repo and is committed with
the code, except the generated `STATUS.md`, which `init` adds to `.gitignore`
(it changes at every session start and would keep the tree dirty). Large
outputs stay wherever they are (e.g. a data disk) and are referenced by path.

The state lives on the machine where Claude Code runs. Runs launched on other
hosts over SSH are recorded here, not on the remote host.

### 5.2 Files

```
research/
  rules.md          # active rules: YAML front matter (enforced) + prose (guidance)
  decisions.md      # append-only dated log of decisions
  questions.md      # one section per RQ: status, verdict, evidence links
  runs.jsonl        # append-only event log of runs
  plans/            # plans; frozen plans are immutable
  STATUS.md         # generated; never edited by hand; gitignored
```

**`rules.md`** — front matter is what hooks enforce; body is prose the agent
reads. Example:

```yaml
---
enforce: true
protected_paths:          # no Write/Edit/overwrite/delete
  - "scripts/rq1_*.py"
  - "/data/myproject/outputs/step*/**"
eval_only_paths:          # must never appear in a training command
  - "data/heldout_human.json"
train_command_patterns:   # regexes identifying a training launch
  - "lerobot-train|train\\.py|accelerate launch"
protected_processes:      # never kill/pkill these
  - "llama-server"
---
- Do not start training without my approval.
- Copy a script before modifying it; never edit the original.
- Report every seed, including bad ones.
```

**`decisions.md`** — entries like:

```
## 2026-11-03 — Comparison point is checkpoint 20k (P and P+para)
Why: 100k would take ~31h; 20k is enough to answer RQ3.
Supersedes: —
```

Never edited; a changed decision is a new entry with `Supersedes:`.

**`questions.md`** — per RQ: `id`, title, status (`open | running |
awaiting-approval | closed`), verdict (one line), evidence (paths to reports,
run IDs).

**`runs.jsonl`** — one JSON object per event; the latest event for a `run_id`
is its current state. Fields: `run_id`, `ts`, `event`
(`planned|started|finished|failed|killed|note`), `rq`, `host`, `gpu`, `cmd`,
`cwd`, `git_commit`, `git_dirty`, `seed`, `config`, `checkpoint`, `output_dir`,
`log_path`, `pid`, `wandb`, `metrics` (dict, on finish), `note`.
`git_dirty` ignores changes under `research/` (bookkeeping would otherwise
always mark the tree dirty). Auto-filled fields (`host`, `cwd`, `git_commit`)
describe the local machine; for a run launched on another host the agent
passes the remote host, path and commit explicitly.

**`plans/`** — `plans/<name>.md`. Freezing a plan writes a header line
`Frozen: <date> (sha256 <hash>)`; afterwards hooks block edits. The hash covers
the plan body only: everything after the header line and before the first
`## Amendment` heading, so appending an amendment does not invalidate it.
Amendments are appended in a dated `## Amendment` section via the skill, never
by editing frozen text (mirrors the article's "don't silently change the
plan"). `status` reports a frozen plan whose body no longer matches its hash.

**`STATUS.md`** — generated by `status.py`: running runs (with last update age;
flag if older than a threshold or pid not alive on this host), items awaiting
approval, open RQs, last 5 decisions, active rules summary, next steps
(taken from `questions.md`).

### 5.3 Skill `research-state`

One skill, triggered when the user starts/resumes research work, approves or
changes a decision, launches or finishes a run, freezes a plan, or asks
"where are we / what's next". Operations (each backed by a script in
`scripts/` so the agent doesn't hand-edit structured files):

| Operation | What it does |
|---|---|
| init | create `research/` with templates; offer to import rules from an existing CLAUDE.md/memory |
| status | regenerate and show `STATUS.md` |
| decide | append a decision (title, why, supersedes) |
| rq | add/update an RQ's status/verdict/evidence |
| run | append a run event; `started` auto-fills commit, dirty flag, host, cwd |
| freeze | freeze a plan; `amend` appends an amendment |

Bookkeeping is done without asking. The skill asks only when the user's intent
is ambiguous (e.g. is this a decision or just a remark?).

### 5.4 Hooks

Formats below were checked against the Claude Code hooks and plugins docs on
2026-11-16; the builder re-verifies before coding.

- **SessionStart** (matchers `startup`, `resume`, `compact`, `clear`; it fires
  again after a compaction): if `research/` exists, regenerate `STATUS.md` and
  inject `STATUS.md` + the prose part of `rules.md` via
  `hookSpecificOutput.additionalContext`. Injected text is capped by Claude
  Code at 10,000 characters (longer output is replaced by a file path and a
  preview), so the script must truncate deliberately: rules first, then
  running runs and items awaiting approval, then the rest, ending with a
  pointer to the full files. Silent no-op when `research/` does not exist.
- **PreToolUse** guard (matchers `Write`, `Edit`, `Bash`; only when
  `enforce: true`). Denials use `permissionDecision: "deny"` with
  `permissionDecisionReason`; confirmations use `"ask"`. The hook sets
  `onFailure: "block"` so a crash or timeout does not silently allow the call.
  - `Write`/`Edit` on `protected_paths` or a frozen plan → deny.
  - `Write`/`Edit` on `research/rules.md` → **ask** the user. Without this the
    agent could loosen a rule and then do what the rule forbade.
  - `Write`/`Edit` on `decisions.md`, `questions.md`, `runs.jsonl` → deny;
    these change only through the skill's scripts, which keeps the two logs
    append-only.
  - `Bash` commands that redirect into, `rm`, `mv`, or `cp` over a protected
    path → deny (best effort pattern matching).
  - `Bash` matching `train_command_patterns` and referencing an
    `eval_only_paths` entry → deny.
  - `Bash` `kill`/`pkill`/`killall` naming a `protected_processes` entry → deny.
  - Any write to `STATUS.md` → deny (generated file).
  - Denial message names the rule and how to override (edit `rules.md`, which
    triggers a confirmation prompt for the user).
- Known limitations, documented in README:
  - Bash matching is best-effort; a Python script can still open or overwrite
    a protected file, and a command wrapped in `ssh host "…"` is matched only
    as text. Recommend the Claude Code sandbox for OS-level enforcement (as
    the article notes).
  - The eval-only check sees only the command line. A training config file
    that points at an eval-only path is not caught.
  - A pid can be checked only for runs on the local host; remote runs are
    flagged stale by age alone.

### 5.5 Implementation constraints

- Hooks and scripts: Python 3 standard library only (YAML front matter parsed
  with a minimal parser for the subset above, or the file uses JSON-compatible
  YAML) — no install step. *(builder's call how, as long as there are no deps.)*
- Hooks call `python3` from PATH (the docs give no guidance on interpreters);
  README states Python 3.9+ as the only requirement.
- Plugin layout: `.claude-plugin/plugin.json`,
  `.claude-plugin/marketplace.json` so the repo can be added with
  `/plugin marketplace add <owner>/ai-research-skills` and installed with
  `/plugin install <plugin>@<marketplace>`,
  `skills/research-state/SKILL.md` (+ `scripts/`, `references/`, `templates/`),
  `hooks/hooks.json` (events under a top-level `"hooks"` key), scripts
  referenced through `${CLAUDE_PLUGIN_ROOT}`. No state is stored in the plugin
  directory (it changes on update).
- **One repo is both the marketplace and the plugin** (owner's decision):
  the marketplace entry uses `"source": "./"`, and `skills/` sits at the repo
  root so other agents can install with `npx skills add`. All stage skills
  ship in this single plugin. Accepted trade-offs: installing copies the whole
  repo (docs, tests, specs); one shared version; splitting into several
  plugins later means moving to `plugins/<name>/` and a reinstall; name and
  version must match in `plugin.json` and `marketplace.json`; users must add
  the marketplace as a git repo, not as a URL to `marketplace.json`.
- `"source": "./"` was not found stated in the docs (it is used by
  `anthropics/skills`). Builder verifies it with a real install as the first
  step; fallback is `plugins/ai-research/` inside this repo.
- SKILL.md short (progressive disclosure); file formats documented in
  `references/`.
- Tests: pytest for scripts and hook decisions (allow/deny cases, stale run
  detection, append-only behavior, freeze hash check).
- README: install, quick start, the `lerobot`-style example, limitations.

## 6. Left to the builder

- Exact CLI shape of the scripts, template wording, staleness threshold
  default, how the YAML subset is parsed, naming inside `scripts/`.

## 7. Calls made by Claude (not explicitly confirmed by the owner)

- State in `research/` inside the repo, committed (owner asked for share/reuse;
  location question was not answered directly).
- Five files + `plans/`; rules split into enforced front matter and prose.
- `runs.jsonl` as an append-only event log.
- Python stdlib only; hooks inject at startup/resume/compact/clear.
- Job monitoring and W&B API are out of scope for this sub-project.
- `STATUS.md` is gitignored; `git_dirty` ignores `research/`.
- Editing `rules.md` prompts the user; the logs and `questions.md` change only
  through scripts.
- The owner's project specifics (hosts, datasets, paths, quotes) are kept out
  of this public document.

## 8. Roadmap after this (not designed here)

Stage skills, one at a time: job monitoring across machines; paper card +
literature log; idea/novelty check; experiment design + plan freeze (builds on
`research-state`); execution sanity gates (model actually uses its input,
config matches paper, data matches key); analysis by pre-registered decision
rule; writing with traceable numbers and verified citations
(NeurIPS/ICML/ICLR/AAAI); independent reviewer subagent.
