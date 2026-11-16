# research-state Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a Claude Code plugin whose `research-state` skill and hooks keep a research project's rules, decisions, RQ status, plans and runs in `research/` files and re-inject them at every session start, resume and compaction.

**Architecture:** A dependency-free Python package `rstate` lives inside the skill (`skills/research-state/scripts/rstate/`) so it ships both with the plugin and with a bare `npx skills add` install. A CLI (`research_state.py`) is the only writer of the structured files. Two thin hook scripts in `hooks/` import the same package: one injects context at SessionStart, one guards Write/Edit/Bash at PreToolUse.

**Tech Stack:** Python 3.9+ standard library only; pytest (dev only); Claude Code plugin + hooks.

**Spec:** `docs/superpowers/specs/2026-11-16-research-state-design.md`

## Global Constraints

- Python 3.9+ standard library only in everything shipped. pytest is a dev-only dependency.
- No state is written inside the plugin directory. All state is under `<project>/research/`.
- `decisions.md` and `runs.jsonl` are append-only; frozen plan bodies are immutable.
- Injected SessionStart context ≤ 9,000 characters (Claude Code caps at 10,000).
- Hooks are a silent, fast no-op (exit 0, no output) when `<project>/research/` does not exist.
- Every denial message names the rule that fired and says how to override it.
- Skill, README and all file templates are in English. No owner-specific hostnames, datasets or paths anywhere in the repo.
- Plugin name `ai-research`, marketplace name `ai-research-skills`, version `0.1.0`, same name and version in both manifests.

## Review Focus

1. **Malformed `rules.md` front matter** — the guard must fail closed (deny Bash/Write/Edit with a message naming the parse error) yet still let the user fix the file: Write/Edit on `rules.md` itself returns `ask`. (Task 8)
2. **Corrupt or half-written line in `runs.jsonl`** — skipped and counted, shown in `STATUS.md` as "N unreadable lines"; SessionStart must never crash on it. (Tasks 3, 6)
3. **Path spelling** — `./x`, `a/../x`, absolute vs relative, a symlink to a protected file, cwd in a subdirectory: all resolve to the same protected path. (Tasks 2, 8)
4. **Not a git repo / no `research/`** — CLI `run start` records `git_commit: null, git_dirty: null`; hooks exit 0 silently. (Tasks 3, 9)
5. **Reading or copying *from* a protected file is allowed** — `cat`, `cp protected.py new.py`, `python protected.py` must pass; the owner's "copy, then edit the copy" workflow depends on it. An unparseable shell string (unbalanced quote) must not crash the hook. (Task 8)

---

## File Structure

```
.claude-plugin/plugin.json            manifest
.claude-plugin/marketplace.json       marketplace entry, source "./"
hooks/hooks.json                      hook registration
hooks/session_start.py                thin wrapper → rstate.status.session_context
hooks/pre_tool_use.py                 thin wrapper → rstate.guard.decide
skills/research-state/SKILL.md
skills/research-state/references/file-formats.md
skills/research-state/templates/{rules.md,decisions.md,questions.md}
skills/research-state/scripts/research_state.py   CLI entry
skills/research-state/scripts/rstate/
  paths.py      project root, research file paths, glob matching
  rules.py      rules.md front matter parser
  runs.py       runs.jsonl event log, git info
  decisions.py  decisions.md appends
  questions.py  questions.md read/upsert
  plans.py      freeze / amend / state
  status.py     STATUS.md and session context
  guard.py      PreToolUse decision logic
tests/conftest.py                     puts scripts/ on sys.path; `project` tmp fixture
tests/test_<module>.py                one per module, plus test_cli.py, test_hooks.py
README.md
```

---

### Task 1: Plugin skeleton and install check

**Files:**
- Create: `.claude-plugin/plugin.json`, `.claude-plugin/marketplace.json`, `skills/research-state/SKILL.md` (stub: front matter + one line), `tests/conftest.py`, `tests/test_manifests.py`

- [ ] **Step 1: Write the failing test**

```python
def test_manifests_agree():
    plugin = json.load(open(".claude-plugin/plugin.json"))
    market = json.load(open(".claude-plugin/marketplace.json"))
    entry = market["plugins"][0]
    assert plugin["name"] == entry["name"] == "ai-research"
    assert plugin["version"] == entry["version"] == "0.1.0"
    assert market["name"] == "ai-research-skills"
    assert entry["source"] == "./"
    assert market["owner"]["name"]
```

- [ ] **Step 2: Run** `pytest tests/test_manifests.py -v` — expect FAIL (files missing).
- [ ] **Step 3: Write both manifests.** `plugin.json`: `name`, `version`, `description`, `author.name`, `repository`. `marketplace.json`: `name`, `owner.name`, one plugin entry with `name`, `source: "./"`, `version`, `description`. Owner/author name = the repo's git user name.
- [ ] **Step 4: Write `tests/conftest.py`**: insert `skills/research-state/scripts` into `sys.path`; fixture `project(tmp_path)` returning a tmp dir with `git init` run in it and an empty `research/` directory.
- [ ] **Step 5: Run** `pytest tests/test_manifests.py -v` — expect PASS.
- [ ] **Step 6: Verify the single-repo layout with a real install.**

Run: `claude plugin validate .` then `claude plugin marketplace add ./` and `claude plugin install ai-research@ai-research-skills`.
Expected: validation passes; plugin listed by `claude plugin list`.
If `"source": "./"` is rejected: stop and report to the owner — the spec's fallback (`plugins/ai-research/`) changes every path in this plan.

- [ ] **Step 7: Commit** — `feat: plugin skeleton and manifests`.

---

### Task 2: Paths and rules parsing

**Files:**
- Create: `skills/research-state/scripts/rstate/__init__.py`, `rstate/paths.py`, `rstate/rules.py`
- Test: `tests/test_paths.py`, `tests/test_rules.py`

**Interfaces — Produces:**
- `paths.find_root(start: Path) -> Path` — nearest ancestor containing `research/`; else git toplevel; else `start`.
- `paths.research_dir(root: Path) -> Path` and constants `RULES="rules.md"`, `DECISIONS="decisions.md"`, `QUESTIONS="questions.md"`, `RUNS="runs.jsonl"`, `STATUS="STATUS.md"`, `PLANS="plans"`.
- `paths.resolve(p: str, cwd: Path) -> Path` — expands `~`, joins relative to `cwd`, `os.path.realpath`.
- `paths.matches(path: Path, pattern: str, root: Path) -> bool` — relative patterns are relative to `root`; `**` matches across `/`, `*` and `?` do not; a trailing `/**` also matches the directory itself (`out/step*/**` matches `out/step3`); true if the pattern matches `path` **or any ancestor directory of it**.
- `rules.Rules` dataclass: `enforce: bool = True`, `protected_paths: list[str]`, `eval_only_paths: list[str]`, `train_command_patterns: list[str]`, `protected_processes: list[str]`, `stale_after_hours: int = 24`, `prose: str`.
- `rules.load(root: Path) -> Rules` — missing file → defaults with `enforce=False`; raises `rules.RulesError(message)` on malformed front matter.

Front matter grammar (the only YAML accepted): between two `---` lines; `key: value` where value is `true|false`, an integer, or a double-quoted string; `key:` followed by indented `- "double-quoted string"` items; `#` comments (whole-line or trailing after a value); blank lines. Quoted strings are decoded with `json.loads`, so `"train\\.py"` yields `train\.py`. Unknown keys → `RulesError`.

- [ ] **Step 1: Write failing tests**

```python
def test_matches_glob_and_ancestors(tmp_path):
    r = tmp_path
    assert matches(r/"scripts/rq1_a.py", "scripts/rq1_*.py", r)
    assert not matches(r/"scripts/sub/rq1_a.py", "scripts/rq1_*.py", r)
    assert matches(r/"out/step3/x/y.csv", "out/step*/**", r)
    assert matches(r/"out/step3", "out/step*/**", r)           # the directory itself
    assert not matches(r/"out", "out/step*/**", r)
    assert matches(r/"out/step3/x/y.csv", "out/step3", r)      # ancestor dir
    assert matches(Path("/data/p/out/a.bin"), "/data/p/out/**", r)

def test_resolve_normalises(tmp_path):
    (tmp_path/"a").mkdir(); (tmp_path/"x.py").write_text("")
    (tmp_path/"link.py").symlink_to(tmp_path/"x.py")
    target = (tmp_path/"x.py").resolve()
    assert resolve("./x.py", tmp_path) == target
    assert resolve("a/../x.py", tmp_path) == target
    assert resolve("../x.py", tmp_path/"a") == target
    assert resolve("link.py", tmp_path) == target

def test_find_root_from_subdir(project):
    (project/"src/deep").mkdir(parents=True)
    assert find_root(project/"src/deep") == project

def test_load_rules(project):
    (project/"research/rules.md").write_text(
        '---\nenforce: true\nstale_after_hours: 12\n'
        'protected_paths:   # no writes\n  - "scripts/rq1_*.py"\n'
        'train_command_patterns:\n  - "train\\\\.py|accelerate launch"\n---\n- Copy before editing.\n')
    r = load(project)
    assert r.enforce and r.stale_after_hours == 12
    assert r.protected_paths == ["scripts/rq1_*.py"]
    assert r.train_command_patterns == [r"train\.py|accelerate launch"]
    assert r.eval_only_paths == [] and r.prose.strip() == "- Copy before editing."

def test_missing_rules_file_disables_enforcement(project):
    assert load(project).enforce is False

@pytest.mark.parametrize("fm", ["enforce: maybe", "protected_paths:\n  - unquoted", "bogus_key: true", "enforce: true"])  # last: no closing ---
def test_malformed_front_matter_raises(project, fm):
    closing = "" if fm == "enforce: true" else "\n---\n"
    (project/"research/rules.md").write_text("---\n" + fm + closing)
    with pytest.raises(RulesError): load(project)
```

- [ ] **Step 2: Run** `pytest tests/test_paths.py tests/test_rules.py -v` — expect FAIL (import error).
- [ ] **Step 3: Implement `paths.py`.** Translate the glob to a regex by hand (`**/` → `(?:.*/)?`, `**` → `.*`, `*` → `[^/]*`, `?` → `[^/]`); test the path and each of its parents.
- [ ] **Step 4: Implement `rules.py`** per the grammar above.
- [ ] **Step 5: Run** the same pytest command — expect PASS.
- [ ] **Step 6: Commit** — `feat: paths and rules parsing`.

---

### Task 3: Run event log

**Files:**
- Create: `rstate/runs.py`
- Test: `tests/test_runs.py`

**Interfaces:**
- Consumes: `paths.research_dir`, `paths.RUNS`.
- Produces:
  - `runs.EVENTS = ("planned","started","finished","failed","killed","note")`
  - `runs.append_event(root: Path, event: str, run_id: str | None = None, now: datetime | None = None, **fields) -> dict` — returns the record written. `run_id=None` is allowed only for `planned`/`started` and generates `rYYYYMMDD-NNN` (NNN = next unused 3-digit number that day). `ts` is UTC ISO-8601 with seconds and `Z`. On `started`, fills `host` (`socket.gethostname()`), `cwd`, `git_commit`, `git_dirty` unless passed explicitly. Unknown event → `ValueError`; a non-planned/started event for an unknown `run_id` → `ValueError`. One `write()` call per line, under `fcntl.flock`.
  - `runs.git_info(cwd: Path) -> tuple[str | None, bool | None]` — dirty is computed with `git status --porcelain -- . ":(exclude)research"`; `(None, None)` outside a git repo.
  - `runs.load(root: Path) -> tuple[dict[str, dict], int]` — `(runs by id in first-seen order, count of unreadable lines)`. A run's dict is all its events merged, later keys overriding earlier, plus `status` = last non-`note` event and `updated` = `ts` of the last event.

- [ ] **Step 1: Write failing tests**

```python
def test_started_autofills_and_merges(project):
    a = append_event(project, "started", cmd="python train.py", seed=7, rq="RQ1", pid=123)
    assert re.fullmatch(r"r\d{8}-001", a["run_id"])
    assert a["host"] == socket.gethostname() and a["git_dirty"] is False
    append_event(project, "finished", run_id=a["run_id"], metrics={"sr": 0.34})
    runs, bad = load(project)
    r = runs[a["run_id"]]
    assert (r["status"], r["cmd"], r["seed"], r["metrics"], bad) == ("finished", "python train.py", 7, {"sr": 0.34}, 0)

def test_dirty_ignores_research_dir(project):
    (project/"research/decisions.md").write_text("x")
    assert git_info(project)[1] is False
    (project/"train.py").write_text("x")
    assert git_info(project)[1] is True

def test_explicit_remote_fields_win(project):
    a = append_event(project, "started", host="gpu-box", git_commit="abc123", cwd="/remote/repo")
    assert (a["host"], a["git_commit"], a["cwd"]) == ("gpu-box", "abc123", "/remote/repo")

def test_not_a_git_repo(tmp_path):
    (tmp_path/"research").mkdir()
    a = append_event(tmp_path, "started", cmd="x")
    assert a["git_commit"] is None and a["git_dirty"] is None

def test_corrupt_lines_are_skipped_and_counted(project):
    a = append_event(project, "started", cmd="x")
    with open(project/"research/runs.jsonl", "a") as f: f.write('{"run_id": "r1", "ev\n\nnot json\n')
    runs, bad = load(project)
    assert list(runs) == [a["run_id"]] and bad == 2

def test_append_only_and_validation(project):
    a = append_event(project, "started", cmd="x"); before = (project/"research/runs.jsonl").read_text()
    append_event(project, "note", run_id=a["run_id"], note="eta 2h")
    assert (project/"research/runs.jsonl").read_text().startswith(before)
    with pytest.raises(ValueError): append_event(project, "exploded", run_id=a["run_id"])
    with pytest.raises(ValueError): append_event(project, "finished", run_id="nope")
    assert load(project)[0][a["run_id"]]["status"] == "started"   # note does not change status
```

- [ ] **Step 2: Run** `pytest tests/test_runs.py -v` — expect FAIL.
- [ ] **Step 3: Implement `runs.py`.**
- [ ] **Step 4: Run** — expect PASS.
- [ ] **Step 5: Commit** — `feat: append-only run event log`.

---

### Task 4: Decisions and questions

**Files:**
- Create: `rstate/decisions.py`, `rstate/questions.py`
- Test: `tests/test_decisions.py`, `tests/test_questions.py`

**Interfaces — Produces:**
- `decisions.append(root, title: str, why: str, supersedes: str | None = None, date: str | None = None) -> str` — appends exactly:

  ```
  ## <date> — <title>
  Why: <why>
  Supersedes: <supersedes or —>
  ```
  preceded by a blank line; `date` defaults to today (local, `YYYY-MM-DD`); creates the file with a `# Decisions` heading if missing. Returns the heading line.
- `decisions.recent(root, n: int = 5) -> list[str]` — the last `n` heading lines without `## `, newest first.
- `questions.STATUSES = ("open","running","awaiting-approval","closed")`
- `questions.upsert(root, qid: str, title: str | None = None, status: str | None = None, verdict: str | None = None, evidence: list[str] | None = None, next_step: str | None = None) -> dict` — creates or updates the section; `evidence` items are appended without duplicates; other fields replace. New question requires `title`, defaults `status="open"`. Invalid status → `ValueError`.
- `questions.load(root) -> list[dict]` — keys `id, title, status, verdict, evidence (list), next` in file order.

  File format, one section per question:
  ```
  ## RQ1 — <title>
  - Status: open
  - Verdict: —
  - Evidence: reports/rq1.md, r20261116-001
  - Next: —
  ```

- [ ] **Step 1: Write failing tests**

```python
def test_decision_format_and_append_only(project):
    append(project, "Comparison point is checkpoint 20k", "100k takes too long", date="2026-11-03")
    first = (project/"research/decisions.md").read_text()
    assert "## 2026-11-03 — Comparison point is checkpoint 20k\nWhy: 100k takes too long\nSupersedes: —\n" in first
    append(project, "Use 40k instead", "20k was noisy", supersedes="2026-11-03 — Comparison point is checkpoint 20k", date="2026-11-09")
    assert (project/"research/decisions.md").read_text().startswith(first)
    assert recent(project, 1) == ["2026-11-09 — Use 40k instead"]

def test_question_upsert_roundtrip(project):
    upsert(project, "RQ1", title="Does X hold?")
    upsert(project, "RQ2", title="Why?", status="running", next_step="run seed 2")
    upsert(project, "RQ1", status="closed", verdict="inconclusive", evidence=["reports/rq1.md"])
    upsert(project, "RQ1", evidence=["reports/rq1.md", "r20261116-001"])
    q1, q2 = load(project)
    assert q1 == {"id": "RQ1", "title": "Does X hold?", "status": "closed", "verdict": "inconclusive",
                  "evidence": ["reports/rq1.md", "r20261116-001"], "next": "—"}
    assert (q2["status"], q2["next"]) == ("running", "run seed 2")

def test_question_validation(project):
    with pytest.raises(ValueError): upsert(project, "RQ9", status="open")          # new without title
    with pytest.raises(ValueError): upsert(project, "RQ1", title="t", status="done")
```

- [ ] **Step 2: Run** `pytest tests/test_decisions.py tests/test_questions.py -v` — expect FAIL.
- [ ] **Step 3: Implement both modules.** `questions.upsert` rewrites only that question's section and leaves any other text in the file untouched.
- [ ] **Step 4: Run** — expect PASS.
- [ ] **Step 5: Commit** — `feat: decision log and research questions`.

---

### Task 5: Plan freeze and amend

**Files:**
- Create: `rstate/plans.py`
- Test: `tests/test_plans.py`

**Interfaces — Produces:**
- `plans.freeze(root, name: str, date: str | None = None) -> str` — `name` is the file stem under `research/plans/`. Inserts first line `Frozen: <date> (sha256 <hex>)` plus a blank line; returns the hex digest. Already frozen → `ValueError`; missing file → `FileNotFoundError`.
- `plans.amend(root, name: str, text: str, date: str | None = None) -> None` — appends `\n## Amendment <date>\n\n<text>\n`. Not frozen → `ValueError`.
- `plans.state(path: Path) -> str` — `"draft" | "frozen" | "tampered"`.
- `plans.list_plans(root) -> list[tuple[str, str]]` — `(name, state)` sorted by name.
- `plans.is_frozen(path: Path) -> bool` — first line starts with `Frozen: ` (true for tampered too).

Hash input: the text after the header line, up to but excluding the first line that starts with `## Amendment`, with trailing whitespace stripped, UTF-8 encoded.

- [ ] **Step 1: Write failing tests**

```python
def test_freeze_amend_and_tamper(project):
    p = project/"research/plans/rq2.md"; p.parent.mkdir(parents=True)
    p.write_text("# RQ2 plan\n\nDecision rule: interval above 0 → supported.\n")
    assert state(p) == "draft"
    digest = freeze(project, "rq2", date="2026-11-16")
    assert p.read_text().splitlines()[0] == f"Frozen: 2026-11-16 (sha256 {digest})"
    assert state(p) == "frozen" and is_frozen(p)
    amend(project, "rq2", "Found near-duplicates in test; adding exploratory analysis.", date="2026-11-18")
    assert "## Amendment 2026-11-18" in p.read_text() and state(p) == "frozen"
    p.write_text(p.read_text().replace("above 0", "above -1"))
    assert state(p) == "tampered" and is_frozen(p)
    assert list_plans(project) == [("rq2", "tampered")]

def test_freeze_errors(project):
    (project/"research/plans").mkdir()
    with pytest.raises(FileNotFoundError): freeze(project, "nope")
    (project/"research/plans/a.md").write_text("x\n"); freeze(project, "a")
    with pytest.raises(ValueError): freeze(project, "a")
    (project/"research/plans/b.md").write_text("x\n")
    with pytest.raises(ValueError): amend(project, "b", "t")
```

- [ ] **Step 2: Run** `pytest tests/test_plans.py -v` — expect FAIL.
- [ ] **Step 3: Implement `plans.py`.**
- [ ] **Step 4: Run** — expect PASS.
- [ ] **Step 5: Commit** — `feat: freeze and amend plans`.

---

### Task 6: Status and session context

**Files:**
- Create: `rstate/status.py`
- Test: `tests/test_status.py`

**Interfaces:**
- Consumes: `rules.load`, `runs.load`, `questions.load`, `decisions.recent`, `plans.list_plans`.
- Produces:
  - `status.build(root, now: datetime | None = None) -> str` — markdown with these sections in order, each omitted when empty except the first line: `# Research status` + `Generated <UTC ts> — do not edit`; `## Running` (one line per run with status `started`: id, rq, host/gpu, cmd truncated to 80 chars, `updated <N>h ago`, and flags); `## Awaiting your approval` (questions with status `awaiting-approval`; runs with status `planned`); `## Open questions` (status `open`/`running`, with `Next:`); `## Plans` (name — state; `tampered` rendered as `TAMPERED — body no longer matches its hash`); `## Recent decisions` (5); `## Recently finished` (last 5 runs with status finished/failed/killed, with metrics); `## Warnings` (`N unreadable lines in runs.jsonl`; `rules.md cannot be parsed: <error>`).
  - Flags on a running run: `STALE` when `now - updated > stale_after_hours`; `PROCESS NOT FOUND` when `host == socket.gethostname()`, a `pid` is recorded and `/proc/<pid>` does not exist (skip the check on systems without `/proc`).
  - `status.write(root, now=None) -> Path` — writes `research/STATUS.md`.
  - `status.session_context(root, limit: int = 9000, now=None) -> str` — `## Standing rules` (rules prose + a one-line summary of what is enforced), then the status text. If over `limit`, drop whole sections from the end (`Recently finished`, `Recent decisions`, `Plans`, `Open questions` in that order) and, if still over, hard-truncate; always end with `Full state: research/STATUS.md, research/rules.md`.

- [ ] **Step 1: Write failing tests**

```python
NOW = datetime(2026, 11, 16, 12, 0, tzinfo=timezone.utc)

def test_status_sections(project):
    a = append_event(project, "started", cmd="python train.py --seed 1", rq="RQ1", host="gpu-box", now=NOW - timedelta(hours=30))
    b = append_event(project, "started", cmd="python eval.py", host="gpu-box", now=NOW - timedelta(hours=1))
    append_event(project, "finished", run_id=b["run_id"], metrics={"sr": 0.34}, now=NOW)
    append_event(project, "planned", cmd="python train.py --seed 2", now=NOW)
    upsert(project, "RQ1", title="Does X hold?", status="awaiting-approval")
    upsert(project, "RQ2", title="Why?", next_step="run seed 2")
    append(project, "Use 20k checkpoint", "time", date="2026-11-03")
    text = build(project, now=NOW)
    running = text.split("## Running")[1].split("##")[0]
    assert a["run_id"] in running and "STALE" in running and b["run_id"] not in running
    waiting = text.split("## Awaiting your approval")[1].split("##")[0]
    assert "RQ1" in waiting and "--seed 2" in waiting
    assert "run seed 2" in text and "Use 20k checkpoint" in text and "0.34" in text

def test_dead_local_pid_flagged(project):
    append_event(project, "started", cmd="x", pid=2**22 + 12345, now=NOW)   # above pid_max
    assert "PROCESS NOT FOUND" in build(project, now=NOW)

def test_warnings_never_crash(project):
    (project/"research/runs.jsonl").write_text("garbage\n")
    (project/"research/rules.md").write_text("---\nbogus: 1\n---\n")
    text = build(project, now=NOW)
    assert "1 unreadable line" in text and "rules.md cannot be parsed" in text

def test_empty_project(project):
    assert build(project, now=NOW).startswith("# Research status")

def test_context_keeps_rules_under_limit(project):
    (project/"research/rules.md").write_text('---\nenforce: true\n---\n- Never train on the held-out set.\n')
    for i in range(200): upsert(project, f"RQ{i}", title="q" * 80, next_step="n" * 80)
    append_event(project, "started", cmd="python train.py", now=NOW)
    ctx = session_context(project, now=NOW)
    assert len(ctx) <= 9000
    assert "Never train on the held-out set." in ctx and "python train.py" in ctx
    assert ctx.rstrip().endswith("Full state: research/STATUS.md, research/rules.md")
```

- [ ] **Step 2: Run** `pytest tests/test_status.py -v` — expect FAIL.
- [ ] **Step 3: Implement `status.py`.** `build` catches `RulesError` and reports it under Warnings (using default rules for the staleness threshold).
- [ ] **Step 4: Run** — expect PASS.
- [ ] **Step 5: Commit** — `feat: generated status and session context`.

---

### Task 7: CLI, init and templates

**Files:**
- Create: `skills/research-state/scripts/research_state.py`, `skills/research-state/templates/rules.md`, `templates/decisions.md`, `templates/questions.md`
- Test: `tests/test_cli.py` (runs the script with `subprocess`, `cwd` = a subdirectory of the tmp project)

**Interfaces:**
- Consumes: every `rstate` module above.
- Produces the commands the skill documents (`--root PATH` global option; default `paths.find_root(cwd)`):

| Command | Behaviour |
|---|---|
| `init` | create `research/`, `research/plans/`, copy the three templates if absent, add `research/STATUS.md` to `.gitignore` (create or append, once), write STATUS. Never overwrites an existing file. |
| `status` | regenerate `STATUS.md` and print it |
| `decide --title T --why W [--supersedes S]` | `decisions.append` |
| `rq ID [--title T] [--status S] [--verdict V] [--evidence E]... [--next N]` | `questions.upsert` |
| `run {plan,start,finish,fail,kill,note} [--id ID] [--rq] [--host] [--gpu] [--cmd] [--cwd] [--commit] [--seed] [--config] [--checkpoint] [--output-dir] [--log] [--pid] [--wandb] [--metric K=V]... [--note]` | `runs.append_event`; prints the `run_id`; `--metric` values parsed as float when possible |
| `freeze NAME` / `amend NAME --text T` | `plans.freeze` / `plans.amend` |

Every mutating command regenerates `STATUS.md`. Errors (`ValueError`, `FileNotFoundError`, `RulesError`) print one line to stderr and exit 1, no traceback.

`templates/rules.md` ships `enforce: true`, all four lists empty with a commented example line each, `stale_after_hours: 24`, and three starter prose rules (no training without approval; copy a script before modifying it; report every seed).

Test helpers (add to `tests/conftest.py`): fixture `project_no_research` (tmp dir with `git init`, no `research/`); `cli(*args, cwd=None, check=True)` runs the script with `sys.executable` and `--root` unset, `cwd` defaulting to the fixture directory, returning `CompletedProcess` with text output. In the tests below `root` is the fixture directory.

- [ ] **Step 1: Write failing tests**

```python
def test_init_is_idempotent_and_ignores_status(project_no_research):
    cli("init"); (root/"research/rules.md").write_text("mine")
    cli("init")
    assert (root/"research/rules.md").read_text() == "mine"
    assert (root/".gitignore").read_text().count("research/STATUS.md") == 1
    assert (root/"research/plans").is_dir() and (root/"research/STATUS.md").exists()

def test_template_rules_parse(project_no_research):
    cli("init"); assert rules.load(root).enforce is True

def test_run_lifecycle_from_subdir(project):
    rid = cli("run", "start", "--cmd", "python train.py", "--seed", "3", "--rq", "RQ1", cwd=project/"src").stdout.strip()
    cli("run", "finish", "--id", rid, "--metric", "sr=0.34", "--metric", "tag=best")
    r = runs.load(project)[0][rid]
    assert r["status"] == "finished" and r["metrics"] == {"sr": 0.34, "tag": "best"} and r["seed"] == 3
    assert rid in (project/"research/STATUS.md").read_text()

def test_errors_are_one_line(project):
    p = cli("rq", "RQ1", "--status", "done", "--title", "t", check=False)
    assert p.returncode == 1 and "Traceback" not in p.stderr and len(p.stderr.strip().splitlines()) == 1
```

- [ ] **Step 2: Run** `pytest tests/test_cli.py -v` — expect FAIL.
- [ ] **Step 3: Write the templates, then implement `research_state.py`** with `argparse` subcommands; the script inserts its own directory into `sys.path` before importing `rstate`.
- [ ] **Step 4: Run** — expect PASS.
- [ ] **Step 5: Commit** — `feat: research_state CLI and templates`.

---

### Task 8: Guard logic and PreToolUse hook

**Files:**
- Create: `rstate/guard.py`, `hooks/pre_tool_use.py`
- Test: `tests/test_guard.py`

**Interfaces:**
- Consumes: `rules.load`, `RulesError`, `paths.resolve`, `paths.matches`, `plans.is_frozen`.
- Produces:
  - `guard.Decision` — `NamedTuple(action: str, reason: str)`, action in `"allow" | "deny" | "ask"`.
  - `guard.decide(tool_name: str, tool_input: dict, cwd: Path, root: Path) -> Decision`
  - `hooks/pre_tool_use.py` — reads the hook JSON from stdin, uses `CLAUDE_PROJECT_DIR` (fallback: input `cwd`) as root, exits 0 silently when `research/` is absent or the decision is `allow`; otherwise prints `{"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": <action>, "permissionDecisionReason": <reason>}}`. Any uncaught exception → message on stderr, exit 2.

Decision rules, first match wins:

1. `research/` missing → allow.
2. Rules cannot be parsed → Write/Edit on `research/rules.md`: **ask**; everything else: **deny** (`research/rules.md cannot be parsed (<error>). Fix that file first.`).
3. `enforce` false → allow.
4. Write targets = `file_path` (Write, Edit) or `notebook_path` (NotebookEdit); for Bash, the targets extracted below. For each target, resolved with `paths.resolve`:
   - `research/STATUS.md` → deny (generated file).
   - `research/decisions.md`, `research/questions.md`, `research/runs.jsonl` → deny (use the `research_state.py` command; name it in the reason).
   - a file under `research/plans/` that `is_frozen` → deny (use `amend`).
   - matches a `protected_paths` pattern → deny (name the pattern).
   - `research/rules.md` → ask.
5. Bash only: the command matches any `train_command_patterns` regex **and** mentions an eval-only path (a token that resolves to a match of an `eval_only_paths` pattern, or the pattern text appearing literally) → deny.
6. Bash only: command contains the word `kill`, `pkill` or `killall` and either names a `protected_processes` entry, or has a numeric argument whose `/proc/<pid>/cmdline` contains one → deny.
7. Otherwise allow.

Every deny/ask reason ends with: `Rule source: research/rules.md (editing it asks for your confirmation).`

Bash target extraction (best effort): split with `shlex.split(command, posix=True)` after spacing out `;`, `&&`, `||`, `|`; on `ValueError` fall back to `command.split()`. Targets are: the token after `>`, `>>`, `&>`, `2>` or attached to them (`>out.txt`); every non-option argument of `rm`, `mv`, `rmdir`, `truncate`, `shred`, `tee`, `touch`, `chmod`, `chown` (for the last two, skip the first non-option argument); the **last** argument only of `cp`, `rsync`, `install`, `ln`; every non-option argument of `sed` when `-i`/`--in-place` is present (skip the script argument); the value of `of=` for `dd`. A leading `sudo` is skipped. Reading is never a target.

- [ ] **Step 1: Write failing tests**

```python
RULES = ('---\nenforce: true\nprotected_paths:\n  - "scripts/rq1_*.py"\n  - "out/step*/**"\n'
         'eval_only_paths:\n  - "data/heldout.json"\ntrain_command_patterns:\n  - "train\\\\.py|accelerate launch"\n'
         'protected_processes:\n  - "llama-server"\n---\n')

@pytest.fixture
def guarded(project):
    (project/"research/rules.md").write_text(RULES); (project/"scripts").mkdir(); return project

def bash(root, cmd, cwd=None): return decide("Bash", {"command": cmd}, cwd or root, root).action

@pytest.mark.parametrize("cmd", [
    "echo x > scripts/rq1_eval.py", "echo x >>out/step3/a/b.csv", "rm -rf out/step3", "mv scripts/rq1_eval.py old.py",
    "cp new.py scripts/rq1_eval.py", "sed -i 's/a/b/' ./scripts/../scripts/rq1_eval.py", "python x.py | tee out/step2/log.txt",
    "sudo rm out/step3/a", "python train.py --eval data/heldout.json", "accelerate launch t.py --data ./data/heldout.json",
    "pkill -f llama-server", "killall llama-server", "echo x >> research/runs.jsonl", "rm research/decisions.md",
])
def test_bash_denied(guarded, cmd): assert bash(guarded, cmd) == "deny"

@pytest.mark.parametrize("cmd", [
    "cat scripts/rq1_eval.py", "cp scripts/rq1_eval.py scripts/rq1_eval_v2_copy.py", "python scripts/rq1_eval.py",
    "python eval.py --data data/heldout.json", "python train.py --data data/train.json", "ls out/step3",
    "pkill -f my_train", "echo 'unbalanced", "grep llama-server ps.txt",
    "python skills/research-state/scripts/research_state.py decide --title t --why w",
])
def test_bash_allowed(guarded, cmd): assert bash(guarded, cmd) == "allow"

def test_cwd_in_subdirectory(guarded):
    assert bash(guarded, "rm rq1_eval.py", cwd=guarded/"scripts") == "deny"

def test_symlink_to_protected(guarded):
    (guarded/"scripts/rq1_a.py").write_text(""); (guarded/"alias.py").symlink_to(guarded/"scripts/rq1_a.py")
    assert decide("Edit", {"file_path": str(guarded/"alias.py")}, guarded, guarded).action == "deny"

def test_write_edit_rules(guarded):
    d = lambda rel: decide("Write", {"file_path": str(guarded/rel), "content": ""}, guarded, guarded)
    assert d("scripts/rq1_eval.py").action == "deny" and "scripts/rq1_*.py" in d("scripts/rq1_eval.py").reason
    assert d("scripts/other.py").action == "allow"
    assert d("research/rules.md").action == "ask"
    assert d("research/STATUS.md").action == d("research/runs.jsonl").action == d("research/decisions.md").action == "deny"
    assert "research/rules.md" in d("scripts/rq1_eval.py").reason

def test_frozen_plan_is_immutable(guarded):
    p = guarded/"research/plans/a.md"; p.parent.mkdir(); p.write_text("x\n")
    edit = lambda: decide("Edit", {"file_path": str(p), "old_string": "x", "new_string": "y"}, guarded, guarded).action
    assert edit() == "allow"; freeze(guarded, "a"); assert edit() == "deny"

def test_malformed_rules_fail_closed_but_fixable(guarded):
    (guarded/"research/rules.md").write_text("---\nbogus: 1\n---\n")
    assert bash(guarded, "ls") == "deny"
    assert decide("Edit", {"file_path": str(guarded/"research/rules.md")}, guarded, guarded).action == "ask"

def test_disabled_or_absent(guarded, tmp_path):
    (guarded/"research/rules.md").write_text("---\nenforce: false\n---\n")
    assert bash(guarded, "rm -rf out/step3") == "allow"
    assert decide("Bash", {"command": "rm -rf /"}, tmp_path, tmp_path).action == "allow"   # no research/ → not our business
```

- [ ] **Step 2: Run** `pytest tests/test_guard.py -v` — expect FAIL.
- [ ] **Step 3: Implement `guard.py`** per the rules above, then `hooks/pre_tool_use.py`.
- [ ] **Step 4: Run** — expect PASS.
- [ ] **Step 5: Commit** — `feat: PreToolUse guard`.

---

### Task 9: SessionStart hook and hook registration

**Files:**
- Create: `hooks/session_start.py`, `hooks/hooks.json`
- Test: `tests/test_hooks.py` (runs both hook scripts with `subprocess`, JSON on stdin, `CLAUDE_PROJECT_DIR` set)

**Interfaces:**
- Consumes: `status.write`, `status.session_context`, `guard.decide`.
- Produces `hooks/hooks.json`:

```json
{
  "description": "research-state: inject project state at session start; guard protected files",
  "hooks": {
    "SessionStart": [
      {"matcher": "startup|resume|clear|compact",
       "hooks": [{"type": "command", "command": "python3 \"${CLAUDE_PLUGIN_ROOT}/hooks/session_start.py\"", "timeout": 20}]}
    ],
    "PreToolUse": [
      {"matcher": "Write|Edit|NotebookEdit|Bash",
       "hooks": [{"type": "command", "command": "python3 \"${CLAUDE_PLUGIN_ROOT}/hooks/pre_tool_use.py\"", "timeout": 10, "onFailure": "block"}]}
    ]
  }
}
```

`session_start.py`: no `research/` → exit 0, no output. Otherwise write `STATUS.md` and print `{"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": <session_context>}}`. On any exception: print a JSON `additionalContext` of `research-state: could not build status (<error>). Read research/ directly.` and exit 0 — a broken status must not block the session.

Both hook scripts locate the package as `Path(__file__).resolve().parent.parent / "skills/research-state/scripts"`.

Test helper (add to `tests/conftest.py`): `run_hook(script, payload, project_dir)` runs `hooks/<script>` with `sys.executable`, `payload` JSON-encoded on stdin (a `str` payload is sent as is), env `CLAUDE_PROJECT_DIR=project_dir`, returning `CompletedProcess` with text output.

- [ ] **Step 1: Write failing tests**

```python
def test_session_start_injects_and_writes_status(project):
    (project/"research/rules.md").write_text('---\nenforce: true\n---\n- Never train on the held-out set.\n')
    out = run_hook("session_start.py", {"hook_event_name": "SessionStart", "source": "compact", "cwd": str(project)}, project)
    ctx = json.loads(out.stdout)["hookSpecificOutput"]["additionalContext"]
    assert "Never train on the held-out set." in ctx and len(ctx) <= 9000
    assert (project/"research/STATUS.md").exists()

def test_hooks_silent_without_research_dir(tmp_path):
    for script, payload in [("session_start.py", {"source": "startup"}),
                            ("pre_tool_use.py", {"tool_name": "Bash", "tool_input": {"command": "rm -rf x"}})]:
        out = run_hook(script, {**payload, "cwd": str(tmp_path)}, tmp_path)
        assert out.returncode == 0 and out.stdout == "" and out.stderr == ""

def test_session_start_survives_garbage(project):
    (project/"research/runs.jsonl").write_bytes(b"\xff\xfe garbage")
    out = run_hook("session_start.py", {"source": "startup", "cwd": str(project)}, project)
    assert out.returncode == 0 and "additionalContext" in out.stdout

def test_pre_tool_use_outputs(project):
    (project/"research/rules.md").write_text('---\nenforce: true\nprotected_paths:\n  - "out/**"\n---\n')
    deny = run_hook("pre_tool_use.py", {"tool_name": "Bash", "tool_input": {"command": "rm out/a"}, "cwd": str(project)}, project)
    h = json.loads(deny.stdout)["hookSpecificOutput"]
    assert (h["hookEventName"], h["permissionDecision"]) == ("PreToolUse", "deny") and "out/**" in h["permissionDecisionReason"]
    ok = run_hook("pre_tool_use.py", {"tool_name": "Bash", "tool_input": {"command": "ls"}, "cwd": str(project)}, project)
    assert ok.returncode == 0 and ok.stdout == ""
    bad = run_hook("pre_tool_use.py", "not json", project)
    assert bad.returncode == 2 and bad.stderr

def test_hooks_json_is_valid():
    cfg = json.load(open("hooks/hooks.json"))["hooks"]
    assert cfg["PreToolUse"][0]["hooks"][0]["onFailure"] == "block"
    assert set(cfg["SessionStart"][0]["matcher"].split("|")) == {"startup", "resume", "clear", "compact"}
```

- [ ] **Step 2: Run** `pytest tests/test_hooks.py -v` — expect FAIL.
- [ ] **Step 3: Write `hooks/hooks.json` and `hooks/session_start.py`;** make `runs.load` tolerant of undecodable bytes (`errors="replace"`) if the garbage test requires it.
- [ ] **Step 4: Run** `pytest -v` (whole suite) — expect PASS.
- [ ] **Step 5: Commit** — `feat: SessionStart and PreToolUse hooks`.

---

### Task 10: Skill text, reference, README and live check

**Files:**
- Modify: `skills/research-state/SKILL.md` (replace stub)
- Create: `skills/research-state/references/file-formats.md`
- Modify: `README.md`
- Test: `tests/test_skill.py`

- [ ] **Step 1: Write the failing test**

```python
def test_skill_front_matter_and_size():
    text = open("skills/research-state/SKILL.md").read()
    fm = text.split("---")[1]
    assert "name: research-state" in fm and "description:" in fm
    assert len(text.splitlines()) <= 120                      # progressive disclosure
    for cmd in ["init", "status", "decide", "rq ", "run start", "run finish", "freeze", "amend"]:
        assert cmd in text
    assert "references/file-formats.md" in text
```

- [ ] **Step 2: Run** `pytest tests/test_skill.py -v` — expect FAIL.
- [ ] **Step 3: Write `SKILL.md`.** Front matter `name`, `description` (third person; triggers: starting or resuming research work, the user approves/changes a decision, a run is launched or ends, a plan is frozen, "where are we / what's next"). Body, in this order:
  1. One paragraph: state lives in `research/`, the CLI is the only writer of the structured files.
  2. The command table from Task 7, invoked as `python3 "${CLAUDE_SKILL_DIR}/scripts/research_state.py"` (verify the variable name against the skills docs; otherwise use the path relative to the skill directory).
  3. When to record what: approval or change of direction → `decide`; before launching any long job → `run start` with cmd/seed/host/gpu/log/pid (and remote host, path and commit for SSH runs); when checking a job → `run note` or `run finish` with metrics; RQ verdicts → `rq`.
  4. Behaviour rules: do bookkeeping without asking; ask only when it is unclear whether a remark is a decision; never hand-edit `decisions.md`, `questions.md`, `runs.jsonl`, `STATUS.md`; never edit a frozen plan — use `amend`; when a hook denies an action, tell the user which rule fired instead of working around it; on `init`, offer to import standing rules found in the project's CLAUDE.md or memory into `rules.md`.
  5. Pointer to `references/file-formats.md`.
- [ ] **Step 4: Write `references/file-formats.md`** — the five file formats and the front matter grammar, copied from the spec §5.2 and Task 2, with one generic example each.
- [ ] **Step 5: Write `README.md`** — what it is and why (three sentences); requirements (Claude Code, Python 3.9+); install (`/plugin marketplace add <owner>/ai-research-skills`, `/plugin install ai-research@ai-research-skills`; `npx skills add` for other agents, noting hooks are Claude Code only); quick start (`init`, edit `rules.md`, start working); what the hooks block; **Limitations** copied from spec §5.4 (best-effort Bash matching, SSH-wrapped commands, config files pointing at eval-only data, remote pid checks) with the sandbox recommendation; roadmap (spec §8).
- [ ] **Step 6: Run** `pytest -v` — expect all PASS.
- [ ] **Step 7: Live check in a scratch project** (not this repo). Reinstall the plugin, run `init`, add one protected path, start a new Claude Code session and confirm: (a) the first turn's context contains "Standing rules"; (b) asking Claude to overwrite the protected file is denied with the rule named; (c) asking it to edit `research/rules.md` shows a confirmation prompt; (d) after `/compact` the status is injected again. Record the four results in the commit message body.
- [ ] **Step 8: Commit** — `docs: research-state skill, reference and README`.
