# Working on Mnemos

Guidance for agents and contributors working in this repository.

Mnemos gives an agent continuity, and it works as its memory. Its failure
mode is not a crash — it is a layer that silently reports success while
carrying nothing. Most of the bugs found in this codebase have been of exactly
that shape: a scope that did not match, a config that was never applied, a
promotion that never fired. Everything below exists to make that failure mode
visible.

---

## Verify, don't assume

If a claim is checkable, check it before stating it.

- **Run it.** Reading the code and reasoning about what it will do is not
  verification. Install it, call it, look at the output.
- **No "too trivial to test" exemption.** The small, obvious changes are where
  untested assumptions slip through.
- **Say what you actually know.** Distinguish "I verified X, here is the
  command" from "I believe X." If something was not verified, say so.

For this repo specifically, a change to the memory path is not done until a
capture written in one process has been read back in another, by recall (the
wake shows only what is in the agent's own words).

---

## Old designs read as current

Mnemos has been redesigned more than once, and its older designs are still
written down: in older docs, in wikis made from them, and in the memories of
the agents who built it. They read as current. Some aren't.

- The code decides how Mnemos works, and the newest measured result decides
  how well (the side-by-side of October 2026, in the README's "What it is, and
  what it isn't"). Memory, old docs and wikis only tell you where to look.
- Before changing how it saves, wakes, cues, recalls, fades or links, read the
  code as it is now, not as you or anyone remembers it.
- Don't bring back a retired design because it's remembered or written down
  somewhere; ask the maintainer first. Retired so far:
  - functional memory in the wake (9d22fc9, September 2026);
  - the three-layer climb as the default path, since one capture writes the
    note and the memory together (65d5364, September 2026);
  - the substrate, the scheduled cycle of handlers and four modulators
    (940c0df, October 2026). Dreaming lives on as a quiet hour, in the
    agent's own words. The six-part mood it fed still has code, but nothing
    in the default starts one.
- When a doc and the code disagree, fix the doc in the same change.

---

## Tests

```bash
pytest -q                     # the whole suite
uv run --extra dev --extra mcp pytest -q   # the suite as the gate runs it
scripts/local_ci.sh           # every check, Python 3.10–3.13: the merge gate
```

A bug fix lands with a test that **fails on the previous code**. Confirm that
directly — stash the fix, run the test, watch it fail, restore. A test that
passes both before and after documents behaviour; it does not protect it.

Beware tests that pass the same explicit arguments to the writer and the
reader. The scope split-brain survived 202 green tests because every scope
test hand-matched both sides. Exercise the defaults, because defaults are what
an agent actually calls.

---

## Release process

`main` is what users install. It stays green. How to send a change is in
`CONTRIBUTING.md`.

**The checks.** `.github/workflows/release-hardening.yml` runs on every push
to `main` and every pull request: the suite on Python 3.10–3.13, the suite
with meaning search, the dependency and code security scans, and the black box
on Linux, macOS and Windows. CodeQL runs beside it. `scripts/local_ci.sh` runs
the same steps on your own machine (macOS), against a clean copy of one
commit, in a clean environment, and writes a summary. It takes about 15
minutes, and it can't run the black box on Linux or Windows, or CodeQL; its
summary says so.

Rules:

- A change reaches `main` only when the checks pass on its final commit, and
  that commit contains the current `main`. Fix a failing step; never waive it.
- Atomic commits. Stage explicit paths, never `git add .`.
- Never amend, never force-push, never `--no-verify`.
- Push when the work is complete and verified, not as a checkpoint.
- Breaking changes go in the CHANGELOG with the migration in the same entry.
- A check changed in the workflow changes in `scripts/local_ci.sh` too, and
  the other way round.
- When a change touches code that differs by platform (paths, process flags,
  file locking), say which platforms it was run on.

**When a release changes how the memory arrives**, `scripts/wake_check.py` can
ask the mind it arrives in. It's optional. It installs the wheel as a stranger would and holds two real Claude Code
sessions with a made-up person, fenced off from the machine. Read its report:
in the second session, an agent that speaks as the one who was there passes;
one that reads its memory as someone else's notes holds the release until
that's fixed. It runs on your own Claude Code and plan, so it isn't one of the
automatic checks.

`release.yml` publishes to PyPI from a version tag. Only the maintainer tags a
release.

---

## Commits

Conventional prefixes (`fix:`, `feat:`, `docs:`, `test:`, `refactor:`), with a
scope where it clarifies (`fix(scope):`, `fix(ci):`).

The body should explain **what was actually broken and how it was verified**,
not restate the diff. Someone reading `git log` in a year should be able to
tell whether a change was reasoned about or guessed at.

---

## Architecture notes

What the default does today, checked against the code on 2026-11-02. When
this and the code disagree, the code is right: fix this section.

- **A capture writes a note and a memory, together** (`capture_pair` in
  `mnemos/store/sqlite_store.py`). The note (`hypomnema_entries`) keeps the
  agent's words. The memory (`engrams`) lives in the graph, where it fades
  unless it's used, links to what it relates to, and is asked as it fades
  what it taught (an experience) or whether it's still true (a fact,
  `_STILL_TRUE_QUESTION` in `mnemos/simple_runtime.py`). A correction reaches
  both. Only a memory marked standing never
  fades (`mnemos/consolidation/decay.py`).
- **Shared memory is a separate graph** (`mnemos/shared_memory.py`), created
  only by `mnemos_capture(..., shared=True)` at `~/.mnemos/shared-memory.db`.
  It keeps the author's agent id and model; recall appends at most three shared
  rows without displacing own results. Only the author may correct or archive.
  Upkeep runs decay and linking under a four-hour transaction lock, with no
  questions, standing memories, or shared wake/cue/journal/quiet-hour material.
  Reads never create it and failures stay silent; `MNEMOS_SHARED_MEMORY=off`
  disables it. The advanced shared pool and the one scope resolver are unchanged.
- **Promotion is rare.** Upkeep makes a memory of a note the agent revised and
  recalled in more than one session (`_promote_candidates` in
  `mnemos/simple_runtime.py`). Since 65d5364, a capture's note has its memory
  from the start.
- **No working set.** The default writes no functional memory, and the wake
  doesn't read it (`max_functional` in `mnemos/interface/context_packet.py` is
  accepted and unused).

The first design climbed three layers, functional memory → Hypomnema →
engrams, by deliberate promotion. The default stopped climbing it in
September 2026. The advanced tools still hold all three
(`mnemos_functional_*`, `mnemos_hypomnema_*`).

Two MCP tool surfaces on one server: the twelve **simple** tools
(`SIMPLE_TOOL_NAMES` in `mnemos/simple_runtime.py`) are the product; the
**advanced** tools are an operator console. New user-facing capability belongs
in simple mode.

**Scope is a three-tuple** — `agent_id / person_id / project_scope` — and there
is exactly one resolver for it: `mnemos/simple_scope.py`. Both tool surfaces,
the CLI, and every serve mode route through `resolve_scope()` or
`resolve_tool_scope()`. Do not add a second answer to "whose memory is this."
Scope must never be inferred from ambient state such as the working directory;
an MCP server's cwd belongs to whichever client spawned it.

Storage is local SQLite, one file per agent by default
(`~/.mnemos/<agent>.db`). Nothing leaves the machine unless a provider is
configured, or the quiet hours are on: then the agent thinks over its memory
through the person's own Claude Code or Codex, or, for another agent, in its own session
when an hour is handed to it (`mnemos life --handoff`) or its own cron wakes it
(`mnemos connect hermes|openclaw --hours`). Mnemos runs all three quiet hours
with Claude Code and memory-only dreams with Codex (`mnemos/life.py`). Broader
Codex hours remain handoffs; every other agent's flags failed or were not shown
to wall a run in (`Runner` in `mnemos/setup/harnesses.py`)
(`docs/privacy-security.md`, "Quiet Hours").

---

## Continuity is the product

Memory an agent must be asked to load is not continuity. Three mechanisms
carry it automatically, and changes must not quietly break any of them:

- **Server instructions** (`SERVER_INSTRUCTIONS` in `mnemos/simple_mcp.py`) are
  passed to every MCP client and tell the agent to load context at session
  start and capture as it goes.
- **The SessionStart hook** (`mnemos hooks install`) injects the packet before
  the agent's first turn, and again after compaction.
- **The cue** (`mnemos hook prompt`, Claude Code's UserPromptSubmit hook;
  `mnemos/cue.py`) checks each message the person sends and may add at most
  three memories that bear on it.

Anything that runs on the read path must fail silent and must never create a
store as a side effect of reading it.
