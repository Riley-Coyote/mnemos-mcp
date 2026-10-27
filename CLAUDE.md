# Working on Mnemos

Guidance for agents and contributors working in this repository.

Mnemos is a memory system. Its failure mode is not a crash — it is a layer
that silently reports success while carrying nothing. Most of the bugs found
in this codebase have been of exactly that shape: a scope that did not match,
a config that was never applied, a promotion that never fired. Everything
below exists to make that failure mode visible.

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

`main` is what users install. It stays green.

All work happens on a branch and lands through a pull request. Agents can run
the entire pipeline — nothing here requires anyone to open GitHub.

```bash
git fetch origin
git switch -c <type>/<slug> origin/main
# work, atomic commits
git push -u origin <type>/<slug>
gh pr create --title "..." --body "..."
```

**The checks.** `.github/workflows/release-hardening.yml` runs on every pull
request: the suite on Python 3.10–3.13, the suite with meaning search, the
dependency and code security scans, and the black box on Linux, macOS and
Windows. CodeQL runs beside it. `scripts/local_ci.sh` runs the same steps on
your own machine (macOS), against a clean copy of one commit, in a clean
environment, and writes a summary to post on the pull request. It takes about
15 minutes, and it can't run the black box on Linux or Windows, or CodeQL; its
summary says so.

Rules:

- Never commit or push directly to `main`.
- A pull request merges only when the checks pass on its final commit, and
  that commit contains the current `main`. Fix a failing step; never waive it.
- One PR is one unit of work, so squash by default. Use `--merge` only when a
  branch carries several genuinely independent fixes worth keeping separately
  revertable.
- Atomic commits. Stage explicit paths, never `git add .`.
- Never amend, never force-push, never `--no-verify`.
- Push when the work is complete and verified, not as a checkpoint.
- Breaking changes go in the CHANGELOG with the migration in the same entry.
- A check changed in the workflow changes in `scripts/local_ci.sh` too, and
  the other way round.
- When a change touches code that differs by platform (paths, process flags,
  file locking), say on the pull request which platforms it was run on.

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

Three memory layers, most durable last:

1. **Functional memory** — the live working set for a session or task.
2. **Hypomnema** — scoped continuity that survives sessions and stays revisable.
3. **Engrams** — the long-term graph, with decay, connections, and beliefs.

Two MCP tool surfaces on one server: the eleven **simple** tools are the
product; the **advanced** tools are an operator console. New user-facing
capability belongs in simple mode.

**Scope is a three-tuple** — `agent_id / person_id / project_scope` — and there
is exactly one resolver for it: `mnemos/simple_scope.py`. Both tool surfaces,
the CLI, and every serve mode route through `resolve_scope()` or
`resolve_tool_scope()`. Do not add a second answer to "whose memory is this."
Scope must never be inferred from ambient state such as the working directory;
an MCP server's cwd belongs to whichever client spawned it.

Storage is local SQLite, one file per agent by default
(`~/.mnemos/<agent>.db`). Nothing leaves the machine unless a provider is
configured, or the quiet hours are on: then the agent thinks over its memory
through the person's own Claude Code (`docs/privacy-security.md`, "Quiet
Hours").

---

## Continuity is the product

Memory an agent must be asked to load is not continuity. Two mechanisms carry
it automatically, and changes must not quietly break either:

- **Server instructions** (`SERVER_INSTRUCTIONS` in `mnemos/simple_mcp.py`) are
  passed to every MCP client and tell the agent to load context at session
  start and capture as it goes.
- **The SessionStart hook** (`mnemos hooks install`) injects the packet before
  the agent's first turn.

Anything that runs on the read path must fail silent and must never create a
store as a side effect of reading it.
