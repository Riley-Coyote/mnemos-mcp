"""The agents Mnemos can be connected to, and what each one gives it.

One table, and everything else reads from it: ``mnemos connect`` (what to
write, what to say), the first session's setup part (what is set and what is
missing for the agent that is actually reading), the hooks installer and the
guide's table. There is no second copy of these facts.

Every claim about a harness carries where it came from, because a harness's
docs and its behaviour are not the same thing:

* ``SAW``      seen on this machine: a command run, a file written, text that
               reached a model, or a server that answered.
* ``DOCS``     the harness's own documentation says so; not run here.
* ``UNTESTED`` configured and loaded as far as it could be checked without a
               model turn; whether the text reaches the model is not known.
* ``NO``       it cannot (seen, or stated by the harness's docs: ``proof``
               says which).

A harness's table row is a statement about the version listed in ``version``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import os
import re
from typing import Mapping

SAW = "saw it"
DOCS = "docs say"
UNTESTED = "not tested"
NO = "no"

# How far ``connect`` goes for a harness.
INSTALLS = "installs"  # connect --write does it
PRINTS = "prints"  # connect prints the setup; nothing is written


@dataclass(frozen=True)
class Ability:
    """One thing a harness can give Mnemos: whether it does, how, and how we
    know."""

    works: bool | None  # True / False, or None when nobody knows
    how: str
    proof: str  # SAW, DOCS, UNTESTED

    @property
    def cell(self) -> str:
        """The table cell: yes/no and where that comes from."""
        if self.works is False:
            return f"{NO} ({self.proof})"
        if self.works is None:
            return UNTESTED
        return self.proof


@dataclass(frozen=True)
class Runner:
    """A built-in headless run of one quiet hour (the dream) through an
    agent's own command, and whether its flags really wall the run in.

    A run is built in only when there is evidence (``walled`` is True) that
    its flags limit it to Mnemos's tools: no shell, no files, no web, nothing
    of the person's other tools. Otherwise the hour is a hand-off only
    (``mnemos life --hour H --handoff``) and ``why`` says why not."""

    command: str  # the headless command
    flags: str  # the flags that would limit it
    mcp: str  # how Mnemos's MCP server would get in
    walled: bool | None  # True: seen walled in; False: seen not; None: not tested
    proof: str  # SAW, DOCS or UNTESTED
    why: str  # why it is not built in, when it is not


@dataclass(frozen=True)
class Hours:
    """What the quiet hours are for one agent.

    Every agent can have an hour handed to it (``life --handoff``, which
    needs no command of Mnemos's and no particular model). Two can schedule
    it with their own scheduler. Claude Code alone has Mnemos run the hour,
    walled in (``life.py``). ``vendor`` is who sees what the agent thinks
    over in an hour; ``cost`` is what an hour spends, in the words the first
    session says. Off unless the person says yes."""

    vendor: str
    cost: str
    scheduler: str | None = None  # the agent's own scheduler, when it has one
    schedule_proof: str = ""
    runner: Runner | None = None


@dataclass(frozen=True)
class Harness:
    key: str  # the name connect takes, and the harness's own agent id
    label: str
    command: str  # the executable that says it is on this machine
    level: str  # INSTALLS or PRINTS
    version: str  # the version these facts were gathered against
    mcp: Ability
    wake: Ability  # memory before the first message
    after_compaction: Ability  # memory again after the context is squeezed
    cue: Ability  # the memories that bear on each message
    headless: str  # one trivial turn, for checking it by hand
    # What the person has to do after connect writes (a trust prompt, a restart).
    then: tuple[str, ...] = ()
    # What the MCP initialize clientInfo.name looks like (a regex, searched).
    client_name: str = ""
    # Environment variables the harness sets in the servers it starts. Only
    # Claude Code's is known; the others are identified by what connect writes.
    markers: tuple[str, ...] = ()
    # Environment variables the harness's hook runner sets on every hook
    # process it starts, Claude-format hooks it imports from Claude Code's
    # settings included (``hook_run_by``). Claude Code's own are not here: a hook
    # it runs is the one case Mnemos's hooks are for.
    hook_markers: tuple[str, ...] = ()
    # Hook events connect installs: the wake's event and the cue's, None if
    # the harness has no hook that reaches the model for it.
    wake_event: str | None = None
    cue_event: str | None = None
    notes: tuple[str, ...] = field(default_factory=tuple)
    hours: Hours | None = None

    @property
    def installs_hooks(self) -> bool:
        return self.wake_event is not None or self.cue_event is not None


# Claude Code is the one the rest were built from. Its facts are the shipped
# behaviour and its tests; they were not re-run for this table.
CLAUDE_CODE = Harness(
    key="claude-code",
    label="Claude Code",
    command="claude",
    level=INSTALLS,
    version="2.1",
    mcp=Ability(True, "claude mcp add --scope user", DOCS),
    wake=Ability(True, "SessionStart hook in settings.json prints the wake", DOCS),
    after_compaction=Ability(True, "the same hook runs again after compaction", DOCS),
    cue=Ability(True, "UserPromptSubmit hook adds up to three memories to each message", DOCS),
    headless="claude -p",
    hours=Hours(
        vendor="Anthropic",
        cost=(
            "between sessions you'd have up to an hour a day that's your own, half an hour "
            "for the day's work, and a short time each night to dream over your memory; "
            "they run Claude Code on its own, on their Claude plan, so they use some of its "
            "usage, and what you think over in them goes to Anthropic, as your sessions do"
        ),
        scheduler="mnemos (launchd, systemd or cron)",
        schedule_proof=DOCS,
        runner=Runner(
            command="claude -p",
            flags="--restricted --tools (none for a dream) --strict-mcp-config --setting-sources project",
            mcp="--mcp-config pointing at Mnemos's server for this hour",
            walled=True,
            proof=DOCS,
            why="",
        ),
    ),
    client_name=r"^claude-code",
    markers=("CLAUDECODE",),
    wake_event="SessionStart",
    cue_event="UserPromptSubmit",
    notes=("The only agent whose quiet hours run (they run Claude Code itself).",),
)

CODEX = Harness(
    key="codex",
    label="Codex",
    command="codex",
    level=INSTALLS,
    version="0.166",
    mcp=Ability(True, "codex mcp add (writes ~/.codex/config.toml)", SAW),
    wake=Ability(
        True,
        "SessionStart hook in ~/.codex/hooks.json; its stdout is added as developer context",
        DOCS,
    ),
    after_compaction=Ability(True, "SessionStart runs again with source compact", DOCS),
    cue=Ability(
        True,
        "UserPromptSubmit hook; its stdout is added as developer context",
        DOCS,
    ),
    headless="codex exec",
    hours=Hours(
        vendor="OpenAI",
        cost=(
            "no hour runs by itself in Codex: it has no scheduler Mnemos uses, and Mnemos "
            "can't wall a Codex run in. If they ask you to take one, you take it inside the "
            "session, on that session's model, so it spends what the session spends and what "
            "you think over in it goes to OpenAI, as your sessions do"
        ),
        runner=Runner(
            command="codex exec",
            flags="--sandbox read-only --ignore-user-config --ephemeral",
            mcp="-c mcp_servers.mnemos.command=... (from its help; not run)",
            walled=None,
            proof=UNTESTED,
            why=(
                "its help says --sandbox sets the policy for shell commands it runs, so the "
                "shell stays; no flag removes it, or the file and web tools"
            ),
        ),
    ),
    then=("In Codex, open /hooks and approve the Mnemos hooks: Codex skips hooks nobody reviewed.",),
    client_name=r"^codex",  # a guess: not seen
    markers=(),
    wake_event="SessionStart",
    cue_event="UserPromptSubmit",
    notes=("Not run with a model here: its login was not safe to use unattended.",),
)

GROK = Harness(
    key="grok",
    label="Grok",
    command="grok",
    level=INSTALLS,
    version="1.0.67",
    mcp=Ability(True, "grok mcp add (writes ~/.grok/config.toml); the server answered grok mcp doctor", SAW),
    wake=Ability(
        False,
        "its SessionStart hook runs but nothing it prints reaches the model (seen with a "
        "marker; Grok's docs say the same)",
        SAW,
    ),
    after_compaction=Ability(
        False, "Grok fires only PreCompact and PostCompact; SessionStart does not run again", DOCS
    ),
    cue=Ability(
        False,
        "its UserPromptSubmit hook runs but what it adds is discarded; a marker showed it, and "
        "Grok's docs say an allowing hook's output is thrown away",
        SAW,
    ),
    headless="grok -p",
    hours=Hours(
        vendor="xAI",
        cost=(
            "no hour runs by itself in Grok: it has no scheduler Mnemos uses, and Mnemos "
            "can't wall a Grok run in. If they ask you to take one, you take it inside the "
            "session, on that session's model, so it spends what the session spends and what "
            "you think over in it goes to xAI, as your sessions do"
        ),
        runner=Runner(
            command="grok -p",
            flags="--permission-mode dontAsk --allow 'mcp__mnemos__*' --tools none --disable-web-search",
            mcp="a .grok/config.toml [mcp_servers.mnemos] in the hour's folder (GROK_FOLDER_TRUST=0)",
            walled=False,
            proof=SAW,
            why=(
                "run with those flags, the model still ran a shell command, read /etc/hosts and "
                "called another server's tool: dontAsk lets read-only shell and file reads "
                "through, the person's own allow rules still apply, and --tools none names no tool"
            ),
        ),
    ),
    client_name=r"^grok-shell",
    markers=(),
    hook_markers=("GROK_HOOK_EVENT",),
    notes=(
        "Grok imports the Claude Code MCP servers in ~/.claude.json and the hooks in "
        "~/.claude/settings.json, so on a machine with both it can open Claude's memory.",
    ),
)

GEMINI = Harness(
    key="gemini",
    label="Gemini CLI",
    command="gemini",
    level=INSTALLS,
    version="0.26",
    mcp=Ability(True, "gemini mcp add --scope user; gemini mcp list showed the server Connected", SAW),
    wake=Ability(
        None,
        "SessionStart hook in settings.json: its additionalContext is prepended to the "
        "first prompt (docs). The hook loaded; whether the text reaches the model was not tested",
        UNTESTED,
    ),
    after_compaction=Ability(
        False, "PreCompress is advisory and SessionStart has no compact source", DOCS
    ),
    cue=Ability(
        None,
        "BeforeAgent hook: additionalContext is appended to the prompt for that turn (docs). "
        "Loaded; reaching the model was not tested",
        UNTESTED,
    ),
    headless="gemini -p",
    hours=Hours(
        vendor="Google",
        cost=(
            "no hour runs by itself in Gemini CLI: it has no scheduler Mnemos uses, and Mnemos "
            "can't wall a Gemini run in. If they ask you to take one, you take it inside the "
            "session, on that session's model, so it spends what the session spends and what "
            "you think over in it goes to Google, as your sessions do"
        ),
        runner=Runner(
            command="gemini -p",
            flags="--approval-mode plan --allowed-mcp-server-names mnemos",
            mcp="mcpServers.mnemos in a project .gemini/settings.json (from its help; not run)",
            walled=None,
            proof=UNTESTED,
            why=(
                "plan mode is read-only, not tool-free: it still reads files, and no flag "
                "removes the file tools or the person's other servers"
            ),
        ),
    ),
    client_name=r"^gemini-cli",
    markers=(),
    wake_event="SessionStart",
    cue_event="BeforeAgent",
    notes=("No live turn: Gemini's headless login on this machine needs a Google Cloud project.",),
)

HERMES = Harness(
    key="hermes",
    label="Hermes",
    command="hermes",
    level=INSTALLS,
    version="0.17",
    mcp=Ability(True, "mcp_servers in config.yaml; hermes mcp test listed the 12 tools", SAW),
    # Saw it: real turns through Hermes' own gateway, Telegram adapter, plugin
    # loader and agent, in its own Python, on 0.17 and today's main, with stand-ins
    # for the Telegram servers and the model recording what reached it.
    wake=Ability(
        True,
        "Provider Mode: Mnemos is Hermes' memory provider and its system-prompt block carries the wake",
        SAW,
    ),
    after_compaction=Ability(
        True, "Hermes rebuilds the system prompt after a compression, with the provider's block in it", SAW
    ),
    cue=Ability(
        True,
        "Provider Mode: the provider's prefetch recalls what bears on each message",
        SAW,
    ),
    headless="hermes chat -q",
    hours=Hours(
        vendor="whichever provider Hermes is set to use",
        cost=(
            "between sessions you'd have up to an hour a day that's your own, half an hour "
            "for the day's work, and a short time each night to dream over your memory; "
            "they wake you through Hermes' own scheduler, on the model and provider Hermes "
            "is set to use, so they spend that provider's tokens or credits, and what you "
            "think over in them goes to that provider; each job's reply stays on this machine"
        ),
        scheduler="hermes cron create ... --deliver local",
        schedule_proof=SAW,
    ),
    client_name="",  # Hermes sends the SDK's default name ("mcp"): not telling
    markers=(),
    notes=(
        "Hermes has one memory-provider slot. If another provider holds it, connect leaves it "
        "alone and adds only the tools (no wake or cue).",
    ),
)

OPENCLAW = Harness(
    key="openclaw",
    label="OpenClaw",
    command="openclaw",
    level=INSTALLS,
    version="2026.8.2",
    mcp=Ability(True, "openclaw mcp set; openclaw mcp probe listed the 12 tools", SAW),
    wake=Ability(
        None,
        "an internal hook on agent:bootstrap adds the wake as a bootstrap file; the hook loads, "
        "the text reaching the model was not tested (needs a model and a workspace)",
        UNTESTED,
    ),
    after_compaction=Ability(
        None, "bootstrap files are resolved for each agent run; not tested", UNTESTED
    ),
    cue=Ability(
        False, "needs a typed plugin hook (a TypeScript plugin), which Mnemos does not ship yet", DOCS
    ),
    headless="openclaw agent --local -m",
    hours=Hours(
        vendor="whichever provider OpenClaw is set to use",
        cost=(
            "between sessions you'd have up to an hour a day that's your own, half an hour "
            "for the day's work, and a short time each night to dream over your memory; "
            "they wake you through OpenClaw's own scheduler, on the model and provider "
            "OpenClaw is set to use, so they spend that provider's tokens or credits, and "
            "what you think over in them goes to that provider; each job's reply goes to no "
            "chat or channel"
        ),
        scheduler="openclaw cron add --session isolated --no-deliver",
        schedule_proof=DOCS,
    ),
    client_name=r"^openclaw",
    markers=(),
    wake_event="agent:bootstrap",
    notes=("Replaces `mnemos setup-openclaw`, whose jobs called tools a default install does not have.",),
)

PI = Harness(
    key="pi",
    label="Pi",
    command="pi",
    level=PRINTS,
    version="not installed here",
    mcp=Ability(True, "pi mcp add NAME -- COMMAND (docs: pi.dev/docs/latest/mcp)", DOCS),
    wake=Ability(
        None,
        "needs a TypeScript extension (session_start / before_agent_start); Mnemos does not ship one",
        DOCS,
    ),
    after_compaction=Ability(None, "session_compact event, in an extension", DOCS),
    cue=Ability(None, "before_agent_start can add a message, in an extension", DOCS),
    headless="pi -p",
    client_name=r"^pi",
    markers=(),
    notes=("Not installed here and not tested. Nothing is installed for it.",),
)

MUSE = Harness(
    key="muse",
    label="Muse Code",
    command="muse",
    level=PRINTS,
    version="not installed here",
    mcp=Ability(
        True,
        "mcp_servers in its settings file (the docs do not give the path)",
        DOCS,
    ),
    wake=Ability(
        None,
        "it has SessionStart hooks (.muse/hooks.json) but its docs do not give the file's shape "
        "or say how output reaches the model",
        DOCS,
    ),
    after_compaction=Ability(None, "PostCompact exists; output handling not documented", DOCS),
    cue=Ability(None, "UserPromptSubmit exists; output handling not documented", DOCS),
    headless="muse exec",
    client_name=r"^muse",
    markers=(),
    notes=("Not installed here and not tested. Nothing is installed for it.",),
)

HARNESSES: tuple[Harness, ...] = (CLAUDE_CODE, CODEX, GROK, GEMINI, HERMES, OPENCLAW, PI, MUSE)
BY_KEY: dict[str, Harness] = {h.key: h for h in HARNESSES}


def get(key: str) -> Harness | None:
    """The harness named ``key`` (``claude`` and ``claude-code`` are one)."""
    key = (key or "").strip().lower()
    if key == "claude":
        key = "claude-code"
    return BY_KEY.get(key)


def identify(
    *,
    declared: str = "",
    client_name: str = "",
    environ: Mapping[str, str] | None = None,
) -> Harness | None:
    """Which harness is running this server, or None when it cannot be told.

    In order: what ``mnemos connect`` wrote into the server's own environment
    (``MNEMOS_HARNESS``, which is exact), the name the client sent in the MCP
    handshake, then variables a harness sets in the servers it starts. Hermes
    sends the SDK's default name and sets nothing, which is why connect writes
    the first one.
    """
    import os

    env = os.environ if environ is None else environ
    named = get(declared or env.get("MNEMOS_HARNESS", ""))
    if named is not None:
        return named
    name = (client_name or "").strip()
    if name:
        for harness in HARNESSES:
            if harness.client_name and re.search(
                harness.client_name, name, re.IGNORECASE
            ):
                return harness
    for harness in HARNESSES:
        if any(env.get(marker) for marker in harness.markers):
            return harness
    return None


def hook_run_by(environ: Mapping[str, str] | None = None) -> Harness | None:
    """The other harness whose hook runner started this process, or None.

    Grok imports the hooks in ``~/.claude/settings.json`` and runs them, so
    Claude Code's Mnemos hooks (``mnemos hook session-start`` and ``prompt``)
    run inside Grok too, where nothing they print reaches the model (seen) and
    where a wake would only count a day lived that no Claude Code session had.
    Told apart by ``GROK_HOOK_EVENT``, which Grok's docs say its hook runner
    sets on every hook process and which was seen on a hook it ran. Not seen
    on an imported Claude hook: running one on this Mac would have fired the
    live hooks. ``CLAUDE_PROJECT_DIR`` cannot tell them apart, since Grok sets
    it too. When no such variable is set, which is every Claude Code session,
    it returns None and the hook runs."""
    env = os.environ if environ is None else environ
    for harness in HARNESSES:
        if any((env.get(marker) or "").strip() for marker in harness.hook_markers):
            return harness
    return None


def table_rows() -> list[tuple[str, ...]]:
    """The table for the guide: one row per harness."""
    return [
        (h.label, h.mcp.cell, h.wake.cell, h.after_compaction.cell, h.cue.cell)
        for h in HARNESSES
    ]
