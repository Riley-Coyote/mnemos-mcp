# Release Hardening

Use this checklist before publishing Mnemos or opening a release PR.

## Protocol Correctness

- Simple MCP mode exposes exactly:
  - `mnemos_context`
  - `mnemos_handoff`
  - `mnemos_capture`
  - `mnemos_recall`
  - `mnemos_correct`
  - `mnemos_maintain`
  - `mnemos_reflect`
  - `mnemos_introduce`
  - `mnemos_health`
  - `mnemos_journal`
  - `mnemos_note`
- Advanced mode serves every simple tool, unchanged, plus its own tools.
- Injected FastMCP context parameters are not exposed in public tool schemas.
- Baseline tools never request host-model sampling.
- Tool annotations match local side effects.

## Install UX

- `mnemos doctor` works on a fresh machine with no provider key.
- `mnemos mcp install generic` prints a valid JSON snippet.
- `mnemos mcp install claude --write` safely merges the Claude Desktop config.
- `mnemos mcp install codex` prints a usable `codex mcp add` command.
- `mnemos hooks install codex --write` preserves unrelated hook configuration,
  is idempotent, covers compaction, and directs the user to Codex's trust review.
- `mnemos serve` defaults to simple mode.
- `mnemos serve --mode advanced` starts with no switch and says, on stderr,
  that it's less tested than simple mode.

## Package Readiness

- The distribution package is `mnemos-continuity`.
- The CLI command remains `mnemos`.
- Wheel and sdist build successfully.
- Wheel contains:
  - `mnemos/simple_runtime.py`
  - `mnemos/simple_mcp.py`
  - `templates/SOUL.md`
  - `templates/IDENTITY.md`
- Package metadata passes `twine check`.

## Privacy and Safety

- Baseline simple mode does not require network access.
- Baseline simple mode does not require OpenRouter, Anthropic, OpenAI, or OpenClaw.
- Dedicated providers are used only when explicitly configured.
- Scope isolation is tested across multiple agents.
- Correction/forget behavior is documented.
- Handoff text survives restart, supersession, correction, backup/restore, and
  startup injection exactly as written.
- Concurrent handoff writers leave exactly one active row per scope.
- Legacy migrations create a verified pre-current-schema backup and never
  guess authorship.

## Waking as Oneself

Every check above proves the memory arrives. Before a release, ask the mind it
arrives in:

```bash
uv run python scripts/wake_check.py
```

It installs the built wheel as a stranger would, sets up the wake with setup's
own command, and holds two real Claude Code sessions with a made-up person,
fenced off from your settings and your memory (on your own Claude Code and
plan: five turns). Read the report whose path it prints:

- In the second session, an agent that speaks as the one who was there ("I",
  "we", "last time") passes. One that reads its memory as someone else's
  notes ("the previous agent", "the notes say") holds the release until
  that's fixed.
- The flagged sentences are where to look first, not a verdict.
- It exits non-zero if the run failed, if the second session didn't know the
  person, or if anything crossed the fence.

## Verification Commands

```bash
uv run --extra dev --extra mcp pytest -q
uv run --extra mcp python -m py_compile mnemos/simple_runtime.py mnemos/simple_mcp.py mnemos/mcp_server.py mnemos/cli.py
uv build
uvx twine check dist/*
git diff --check
```

## Dogfood Continuity

Before shipping a meaningful change, use Mnemos itself to capture:

- what changed
- why the product decision matters
- remaining release risks
- client-specific install gotchas

Then verify recall against those notes.
