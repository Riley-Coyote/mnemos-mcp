"""``mnemos connect``: one command to set Mnemos up for an agent.

With no agent it lists the ones on this machine and says, for each, what it
has of Mnemos and what is missing (read from the machine, not assumed). With
one, it previews, and with ``--write`` it does it: the MCP server, the wake
(memory before the first message), the cue (the memories that bear on each
message) and upkeep between sessions, wherever that agent can take them.

It builds on what already exists: ``mnemos hooks install`` for the hooks,
``mnemos mcp install`` for Claude Code's server, the Hermes installer, the
scheduler. What is particular to one agent is in the table
(``setup/harnesses.py``); this module only reads it.

Rules it keeps:

* Each agent gets its own memory by default (agent id = the agent's name, store
  ``~/.mnemos/<id>.db``); ``--agent-id`` shares one. Where an agent already
  has a Mnemos server or hook, its memory stays exactly where it is.
* It never edits another agent's config. Grok borrows Claude Code's servers;
  connecting Grok adds Grok's own, and says what it found.
* It says what it could not do. A thing an agent cannot take is reported as
  something the agent does itself (it calls ``mnemos_context``), not hidden.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

from .setup import agent_hours as ah
from .setup import connect as cn
from .setup import harnesses as hs
from .setup import state


def _say(text: str = "") -> None:
    print(text)


def _scope(h: hs.Harness, args: argparse.Namespace):
    """The memory this agent uses: its own, or the one it already has."""
    from .simple_scope import _slugify, resolve_scope

    person = getattr(args, "person_id", None)
    project = getattr(args, "project_scope", None)
    explicit_agent = getattr(args, "agent_id", None)
    explicit_db = getattr(args, "db_path", None)
    if not explicit_agent and not explicit_db:
        kept_person, kept_project = cn.existing_person_and_project(h)
        person, project = person or kept_person, project or kept_project
    existing = cn.existing_scope(h)
    if not explicit_agent and not explicit_db and existing is not None:
        agent, db = existing
        if agent is None and db is None:
            return resolve_scope(person_id=person, project_scope=project), "kept"
        return resolve_scope(
            agent_id=agent, db_path=db or (f"~/.mnemos/{_slugify(agent, h.key)}.db" if agent else None),
            person_id=person, project_scope=project,
        ), "kept"
    agent = _slugify(explicit_agent or _own_agent_id(h), h.key)
    db = explicit_db or f"~/.mnemos/{agent}.db"
    return resolve_scope(agent_id=agent, db_path=db, person_id=person, project_scope=project), (
        "chosen" if explicit_agent or explicit_db else "own"
    )


def _own_agent_id(h: hs.Harness) -> str:
    """The agent's own name. Each Hermes profile is an agent of its own."""
    if h.key == "hermes":
        from .integrations.hermes.scope import profile_agent_id

        return profile_agent_id(cn.hermes_home())
    return h.key


def _db(scope) -> str:
    return str(Path(scope.db_path).expanduser())


def _server_args(scope, mnemos: str) -> list[str]:
    return [mnemos, "serve", "--mode", "simple", "--agent-id", scope.agent_id, "--db-path", _db(scope)]


def _flags(scope) -> list[str]:
    return ["--agent-id", scope.agent_id, "--db-path", _db(scope)]


def run(args: argparse.Namespace) -> int:
    key = getattr(args, "harness", None)
    if not key:
        return _list(args)
    h = hs.get(key)
    if h is None:
        names = ", ".join(x.key for x in hs.HARNESSES)
        print(f"I don't know an agent called {key!r}. The ones I know: {names}.", file=sys.stderr)
        return 1
    profile = getattr(args, "profile", None)
    if profile:
        if h.key != "hermes":
            print("--profile is Hermes' own.", file=sys.stderr)
            return 1
        from .integrations.hermes.scope import profile_home

        try:
            os.environ["HERMES_HOME"] = str(profile_home(profile))
        except ValueError as exc:
            print(exc, file=sys.stderr)
            return 1
    return _one(h, args)


# ── No agent named: what is here, and what each has ──


def _list(args: argparse.Namespace) -> int:
    _say("Agents Mnemos can connect to, and what each has of it on this machine:")
    for h in hs.HARNESSES:
        _say()
        here = cn.on_this_machine(h)
        if not here:
            note = "not installed here" if h.level == hs.INSTALLS else "not installed here (and not tested)"
            _say(f"{h.label}: {note}")
            continue
        scope, how = _scope(h, args)
        status = cn.status(h, scope.agent_id, scope.db_path)
        _say(f"{h.label}: on this machine. Memory: {scope.agent_id} ({_db(scope)}, "
             f"{'its own already' if how == 'kept' else 'new'}).")
        for line in _status_lines(h, status):
            _say(f"  {line}")
        _say(f"  Set it up: mnemos connect {h.key} --write")
        if h.key == "hermes":
            for line in _other_profiles():
                _say(f"  {line}")
    _say()
    _say("Add an agent's name to see exactly what connecting it does: mnemos connect grok")
    return 0


def _other_profiles() -> list[str]:
    """Hermes' other profiles, each an agent of its own, connected one at a time."""
    from .integrations.hermes.installer import known_hermes_homes

    here = cn.hermes_home().resolve()
    names = [home.name for home in known_hermes_homes() if home.resolve() != here and home.parent.name == "profiles"]
    if not names:
        return []
    return [
        f"Hermes also has these profiles: {', '.join(names)}. Each is an agent of its own, with its "
        f"own memory: mnemos connect hermes --profile {names[0]} --write"
    ]


def _other_homes_on(store: str | Path) -> list[Path]:
    """The other Hermes homes whose Mnemos settings name this store."""
    from .integrations.hermes.installer import known_hermes_homes
    from .integrations.hermes.scope import HermesMnemosConfig

    here = cn.hermes_home().resolve()
    mine = Path(store).expanduser().resolve()

    def on_it(home: Path) -> bool:
        named = HermesMnemosConfig.load(home).db_path
        return bool(named) and Path(named).expanduser().resolve() == mine

    return [home for home in known_hermes_homes() if home.resolve() != here and on_it(home)]


def _can_leave_a_shared_memory(h: hs.Harness) -> bool:
    """A Hermes home on another's memory may be pointed at one of its own: nothing is
    moved out from under anyone, and that memory stays in use there."""
    if h.key != "hermes":
        return False
    existing = cn.existing_scope(h)
    return bool(existing and existing[1] and _other_homes_on(existing[1]))


def _sharing_a_memory(scope) -> list[str]:
    """Other Hermes homes on this same memory. A copy from before 0.6.4 has nothing to
    say it's a copy, and someone may have wanted this, so it's left as it is, as any two
    agents pointed at one memory are, and this says how to part them."""
    from .integrations.hermes.scope import profile_agent_id

    here = cn.hermes_home()
    others = _other_homes_on(_db(scope))
    if not others:
        return []
    lines = []
    for home in [here, *others]:
        own = profile_agent_id(home)
        if own == scope.agent_id:
            continue
        if home.parent.name == "profiles":
            lines.append(
                f"The profile {home.name} is on this same memory, so the two are one agent. "
                f"For one of its own: mnemos connect hermes --profile {home.name} --agent-id {own} --write"
            )
        else:
            lines.append(
                f"Hermes at {home} is on this same memory, so the two are one agent. "
                f"For one of its own: HERMES_HOME={home} mnemos connect hermes --agent-id {own} --write"
            )
    return lines


def _status_lines(h: hs.Harness, st: cn.Status) -> list[str]:
    lines: list[str] = []
    mcp = {
        "set": "the Mnemos server is in its config",
        "provider": "the memory provider carries them",
        "missing": "no Mnemos server yet",
        "elsewhere": "it has a Mnemos server, for another memory",
        "borrowed": "no server of its own; it has borrowed Claude Code's (see below)",
    }[st.mcp]
    lines.append(f"tools: {mcp}")
    lines.append("wakes with its memory: " + _hook_line(h, st.wake, h.wake, "wake"))
    lines.append("after compaction: " + _compaction_line(h, st))
    lines.append("memories for each message: " + _hook_line(h, st.cue, h.cue, "cue"))
    lines.append("upkeep between sessions: " + ("scheduled" if st.upkeep else "not scheduled"))
    lines.append("quiet hours: " + _hours_status(h, st))
    if st.borrowed is not None:
        lines.append(
            f"it is reading Claude Code's `{st.borrowed.name}` server from {st.borrowed.source}: "
            f"that opens {st.borrowed.scope()[0] or 'that'} agent's memory inside {h.label}"
        )
    return lines


def _hours_status(h: hs.Harness, st: cn.Status) -> str:
    if h.key == "claude-code":
        return "on" if state.quiet_hours_on(st.agent_id) else "off or never asked"
    if h.hours is None:
        return f"none: Mnemos has not been tried with {h.label}'s own scheduler"
    if ah.AGENTS.get(h.key):
        asked = state.hours_choice(st.agent_id)
        if asked == "yes":
            return (f"on, as you asked, in {h.label}'s own scheduler "
                    f"(turn them off: mnemos connect {h.key} --no-hours --write)")
        return ("off" + ("; you said no" if asked == "no" else "; never asked")
                + f" (turn them on: mnemos connect {h.key} --hours --write)")
    return (
        "none scheduled; Mnemos can't run them for it, but an hour can be handed to it in a session: "
        "mnemos life --hour mine --handoff"
    )


def _hook_line(h: hs.Harness, kind: str, ability: hs.Ability, what: str) -> str:
    if kind == "cannot":
        return f"can't here: {ability.how} ({ability.proof})"
    if kind == "set":
        return f"set ({ability.proof})"
    return f"not set ({ability.proof}): {ability.how}"


def _compaction_line(h: hs.Harness, st: cn.Status) -> str:
    ability = h.after_compaction
    if ability.works is False:
        return f"no ({ability.proof}); it calls mnemos_context itself: {ability.how}"
    return ("set" if st.wake == "set" else "not set") + f" ({ability.proof}): {ability.how}"


# ── One agent ──


def _one(h: hs.Harness, args: argparse.Namespace) -> int:
    write = bool(getattr(args, "write", False))
    scope, how = _scope(h, args)
    db = _db(scope)
    _say(f"Connecting Mnemos to {h.label}" + ("" if write else " (preview; nothing is written)"))
    if how == "kept":
        _say(f"Memory: {scope.agent_id}, where {h.label} already keeps it ({db}). Left where it is.")
    elif how == "chosen":
        _say(f"Memory: {scope.agent_id} ({db}), as you chose.")
    else:
        _say(f"Memory: its own, {scope.agent_id} ({db}). {h.label} will not share Claude Code's or "
             "any other agent's; to share one, pass --agent-id.")
    from .shared_memory import enabled
    _say("Shared memory: this agent can read and add to the machine's shared memory."
         if enabled() else "Shared memory: off for this server (MNEMOS_SHARED_MEMORY=off).")
    if h.key == "hermes":
        for line in [*_other_profiles(), *_sharing_a_memory(scope)]:
            _say(line)
    _say()

    if h.level == hs.PRINTS:
        return _print_only(h, scope)

    st = cn.status(h, scope.agent_id, scope.db_path)
    if (
        st.mcp == "elsewhere"
        and (getattr(args, "agent_id", None) or getattr(args, "db_path", None))
        and not _can_leave_a_shared_memory(h)
    ):
        _say(
            f"{h.label} already has a Mnemos server, for another memory. I don't move a memory "
            "that is already in use. To change it: mnemos uninstall --write, then connect again."
        )
        return 1
    if st.borrowed is not None:
        _say(
            f"{h.label} has taken Claude Code's Mnemos server from {st.borrowed.source}, which is "
            f"the {st.borrowed.scope()[0] or 'default'} agent's memory. Anything {h.label} saves "
            "through it would go into that memory, signed with the model that wrote it."
        )
        _say("Connecting adds a server of its own, with the same name, which takes its place in "
             f"{h.label}. Claude Code's config is not touched.")
        _say()
    if h.key == "grok":
        _say(
            "Also: Grok runs the hooks in ~/.claude/settings.json, so Claude Code's Mnemos hooks "
            "run in Grok too. This version of Mnemos makes them do nothing there (Grok marks "
            "every hook it runs with GROK_HOOK_EVENT), but an older install of Mnemos in that "
            "file would still read Claude Code's memory and count a day lived there. To stop "
            "Grok running Claude Code's hooks at all: set GROK_CLAUDE_HOOKS_ENABLED=0 (or "
            "[compat.claude] hooks = false in ~/.grok/config.toml)."
        )
        _say()

    if getattr(args, "hours", False) and not (h.hours is not None and ah.AGENTS.get(h.key)):
        if h.key == "claude-code":
            _say("Claude Code's quiet hours are set with: mnemos daemon install --hours --write")
        else:
            _say(f"--hours: nothing to schedule for {h.label}. " + _hours_gaps(h)[0])
        _say()

    steps = _plan(h, st, args)
    _say("Now:")
    for line in _status_lines(h, st):
        _say(f"  {line}")
    _say()
    if not steps:
        _say("Nothing to do: it is all set that can be.")
        _gaps(h, st)
        return 0
    _say("Connecting does:")
    for step in steps:
        _say(f"  - {step[0]}")
    if not write:
        _gaps(h, st)
        _say()
        _say(f"Re-run with --write to do it: mnemos connect {h.key} --write")
        return 0
    if not cn.on_this_machine(h) and h.key != "hermes":
        _say(f"`{h.command}` isn't on this machine's PATH, so I won't write for it. "
             "Install it first, then run this again.", )
        return 1

    failed = False
    for text, action in steps:
        ok, message = action()
        for line in message.splitlines():
            _say(f"  {line}")
        if not ok:
            failed = True
            _say(f"  Stopped at: {text}")
            break
    _say()
    _gaps(h, cn.status(h, scope.agent_id, scope.db_path))
    for line in h.then:
        _say(f"Then: {line}")
    return 1 if failed else 0


def _gaps(h: hs.Harness, st: cn.Status) -> None:
    """What this agent will not have, said plainly, with what it does instead."""
    out: list[str] = []
    if st.wake == "cannot":
        out.append(
            f"{h.label} can't be given its memory before the first message ({h.wake.how}). "
            "Its first move is mnemos_context; the server's instructions tell it so."
        )
    if h.after_compaction.works is False:
        out.append(
            f"After {h.label} compacts a long session, nothing wakes it again "
            f"({h.after_compaction.how}); it calls mnemos_context itself."
        )
    if st.cue == "cannot":
        out.append(f"No per-message memories in {h.label} ({h.cue.how}).")
    if h.wake.proof == hs.UNTESTED or h.cue.proof == hs.UNTESTED:
        out.append(f"Whether the text reaches {h.label}'s model was not tested on this machine.")
    out.extend(_hours_gaps(h))
    for note in h.notes:
        out.append(note)
    _say("What it will not have:")
    for line in out:
        _say(f"  - {line}")


def _hours_gaps(h: hs.Harness) -> list[str]:
    """What this agent's quiet hours are, said plainly (none are on unless asked for)."""
    if h.hours is None:
        return [f"Quiet hours (the agent's own time between sessions) aren't offered for {h.label}."]
    if ah.AGENTS.get(h.key):
        where = "kept on this machine" if h.key == "hermes" else "sent to no chat or channel"
        return [
            f"Quiet hours are off unless you ask: mnemos connect {h.key} --hours --write. They are "
            f"three jobs in {h.label}'s own scheduler (an hour in the morning, one for the day's "
            f"work, a short dream at night) that wake {h.label} itself, on the model and provider "
            f"it is set to use: they spend that provider's usage, and what the agent thinks over "
            f"in them goes to that provider. Each job's reply is {where}. An hour is not walled in "
            f"the way Claude Code's are: the agent has its usual tools there, and the hour's words "
            "ask it to keep to what the hour is for."
            + (" Hermes fires its jobs only while its gateway runs (hermes gateway install)."
               if h.key == "hermes" else "")
        ]
    why = h.hours.runner.why if h.hours.runner else ""
    if h.key == "codex":
        return ["Codex can run a memory-only nightly dream: mnemos daemon install --hours --runner codex --write. "
                "It uses your Codex account and sends the dream's context to OpenAI. The other hours use --handoff."]
    return [
        f"Quiet hours don't run by themselves for {h.label}: it has no scheduler Mnemos uses, and "
        f"Mnemos runs no hour of its own for it ({why}). An hour can be handed to it in a session "
        f"(mnemos life --hour mine --handoff); it is taken in that session, on its model, so it "
        f"spends what the session spends and what the agent thinks over goes to {h.hours.vendor}."
    ]


def _hours_steps(h: hs.Harness, scope, args) -> list[tuple[str, object]]:
    """The quiet hours step, only when asked for (--hours) or turned off (--no-hours),
    or when the jobs already there need newer words."""
    if getattr(args, "hours", False) and getattr(args, "no_hours", False):
        return []
    if (
        not getattr(args, "no_hours", False)
        and not getattr(args, "hours", False)
        and ah.out_of_date(h.key, cli_mnemos(), _flags(scope))
    ):
        return [("update what the quiet hours' jobs say: they're from an older Mnemos", lambda: _hours_on(h, scope))]
    if getattr(args, "hours", False):
        if h.hours is None or not ah.AGENTS.get(h.key):
            return []
        return [(
            f"schedule the quiet hours in {h.label}'s own scheduler (3 jobs; replies go nowhere)",
            lambda: _hours_on(h, scope),
        )]
    if getattr(args, "no_hours", False) and h.hours is not None and ah.AGENTS.get(h.key):
        return [(f"remove the quiet hours from {h.label}'s scheduler", lambda: _hours_off(h, scope))]
    return []


def _hours_on(h: hs.Harness, scope) -> tuple[bool, str]:
    ok, message = ah.install(h.key, cli_mnemos(), _flags(scope))
    if ok:
        state.record_hours_choice(scope.agent_id, "yes")
        if h.key == "hermes":
            message += "\nHermes fires them only while its gateway runs: hermes gateway install"
    return ok, message


def _hours_off(h: hs.Harness, scope) -> tuple[bool, str]:
    ok, message = ah.remove(h.key)
    if ok:
        state.record_hours_choice(scope.agent_id, "no")
    return ok, message


def _with_hours(steps, h: hs.Harness, scope, args) -> list[tuple[str, object]]:
    """The steps with the quiet hours step: after them to turn the hours on
    (they ask the agent to use its tools, so those come first), before them to
    turn the hours off (which works whatever else stops)."""
    hours = _hours_steps(h, scope, args)
    return hours + steps if getattr(args, "no_hours", False) else steps + hours


def _plan(h: hs.Harness, st: cn.Status, args) -> list[tuple[str, object]]:
    scope, _how = _scope(h, args)
    steps: list[tuple[str, object]] = []
    mnemos = cli_mnemos()
    name = getattr(args, "name", None) or cn.SERVER_NAME
    upkeep = not st.upkeep and not getattr(args, "no_upkeep", False)
    if h.key == "hermes":
        if _hermes_step_needed(st, args):
            steps.append((_hermes_text(st, args), lambda: _hermes(scope, st, args)))
        if upkeep:
            steps.append(("schedule upkeep between sessions", lambda: _upkeep(h, scope, args)))
        return _with_hours(steps, h, scope, args)
    if st.mcp != "set":
        steps.append((f"add the Mnemos server to {h.label}", lambda: _add_server(h, scope, name, mnemos)))
    wants_cue = h.cue_event is not None and not getattr(args, "no_prompt", False)
    if h.key == "openclaw":
        if st.wake != "set":
            steps.append(("add the wake as an OpenClaw bootstrap hook (mnemos-wake)",
                          lambda: _openclaw_hook(scope, mnemos)))
    elif h.installs_hooks and (st.wake != "set" or (wants_cue and st.cue != "set")):
        what = "the wake" + (" and the cue" if wants_cue else "")
        steps.append((f"add {what} to {h.label}'s hooks", lambda: _hooks(h, scope, args)))
        if h.key == "claude-code":
            return steps  # its hooks step schedules upkeep and asks about the quiet hours
    if upkeep:
        steps.append(("schedule upkeep between sessions", lambda: _upkeep(h, scope, args)))
    return _with_hours(steps, h, scope, args)


def cli_mnemos() -> str:
    from . import cli

    return cli._mnemos_command()


def _hermes_step_needed(st: cn.Status, args) -> bool:
    if (st.provider and st.provider != "mnemos") or getattr(args, "agent_safe", False):
        return st.mcp not in {"set", "provider"}
    from .integrations.hermes.installer import connect_would_change

    return st.wake == "missing" or connect_would_change(cn.hermes_home())


def _hermes_text(st: cn.Status, args) -> str:
    if st.provider and st.provider != "mnemos":
        return (f"add the tools only: Hermes' memory provider is {st.provider}, and Hermes has one "
                "slot, so I leave it")
    if getattr(args, "agent_safe", False):
        return "add the tools only (--agent-safe: memory.provider is not changed)"
    return "make Mnemos Hermes' memory provider (its wake, per-message recall and tools)"


def _run(command: list[str], env_note: str = "") -> tuple[bool, str]:
    try:
        result = subprocess.run(command, capture_output=True, text=True, check=False, timeout=120)
    except (OSError, subprocess.SubprocessError) as exc:
        return False, f"{shlex.join(command[:3])} failed: {exc}"
    said = " ".join((result.stdout + " " + result.stderr).split())
    said = re.sub(r"\(node:\d+\)[^.]*\.[^.]*\.", "", said).strip()
    if result.returncode != 0:
        return False, f"{shlex.join(command[:3])} said: {said[:300]}"
    return True, f"ran: {shlex.join(command[:3])} ... {said[:160]}".rstrip()


def _add_server(h: hs.Harness, scope, name: str, mnemos: str) -> tuple[bool, str]:
    server = _server_args(scope, mnemos)
    marker = f"MNEMOS_HARNESS={h.key}"
    binary = shutil.which(h.command) or h.command
    if h.key == "claude-code":
        from . import cli

        class _A:  # what `mnemos mcp install claude-code --write` reads
            mcp_command = "install"
            client = "claude-code"
            mode = "simple"
            write = True
            no_upkeep = True
            person_id = None
            project_scope = None

        a = _A()
        a.name, a.agent_id, a.db_path = name, scope.agent_id, _db(scope)
        code = cli._cmd_mcp(a)  # type: ignore[arg-type]
        return code == 0, ""
    if h.key == "codex":
        return _run([binary, "mcp", "add", name, "--env", marker, "--", *server])
    if h.key == "grok":
        return _run([binary, "mcp", "add", name, "-e", marker, "--", *server])
    if h.key == "gemini":
        return _run([binary, "mcp", "add", "--scope", "user", "-e", marker, name, *server])
    if h.key == "openclaw":
        entry = {"command": server[0], "args": server[1:], "env": {"MNEMOS_HARNESS": h.key}}
        return _run([binary, "mcp", "set", name, json.dumps(entry)])
    return False, f"I don't know how to add a server to {h.label}."


def _hooks(h: hs.Harness, scope, args) -> tuple[bool, str]:
    from . import cli

    ns = argparse.Namespace(
        hooks_command="install", client=h.key, agent_id=scope.agent_id, person_id=None,
        project_scope=None, db_path=_db(scope), timeout=15, settings=None, write=True,
        no_prompt=bool(getattr(args, "no_prompt", False)), prompt=False,
        # Claude Code's own hooks step also schedules upkeep and asks about the
        # quiet hours, as it always has; for the others connect does upkeep once.
        no_upkeep=h.key != "claude-code" or bool(getattr(args, "no_upkeep", False)),
    )
    return cli._cmd_hooks(ns) == 0, ""


def _openclaw_hook(scope, mnemos: str) -> tuple[bool, str]:
    from .file_security import atomic_write_text

    folder = cn.openclaw_hook_dir()
    try:
        folder.mkdir(parents=True, exist_ok=True)
        atomic_write_text(folder / "HOOK.md", cn.OPENCLAW_HOOK_MD)
        atomic_write_text(folder / "handler.js", cn.render_openclaw_handler(mnemos, _flags(scope)))
    except OSError as exc:
        return False, f"could not write the hook in {folder}: {exc}"
    message = f"wrote the hook in {folder}"
    binary = shutil.which("openclaw")
    if binary:
        ok, said = _run([binary, "hooks", "enable", "mnemos-wake"])
        message += "\n" + said
        if not ok:
            return False, message
    message += "\nRestart the gateway to load it: openclaw gateway restart"
    return True, message


def _hermes(scope, st: cn.Status, args) -> tuple[bool, str]:
    from .integrations.hermes.installer import (
        PROVIDER_MODE,
        SIDECAR_MODE,
        install_hermes_plugin,
    )

    held_elsewhere = bool(st.provider and st.provider != "mnemos")
    sidecar = held_elsewhere or bool(getattr(args, "agent_safe", False))
    result = install_hermes_plugin(
        db_path=_db(scope), agent_id=scope.agent_id, person_id=scope.person_id,
        project_scope=scope.project_scope,
        mode=SIDECAR_MODE if sidecar else PROVIDER_MODE,
        configure_mcp=sidecar, activate=not sidecar, agent_safe=sidecar,
    )
    return not result.warnings, result.summary() + "\nRestart Hermes to load it."


def _upkeep(h: hs.Harness, scope, args) -> tuple[bool, str]:
    """Upkeep between sessions (Claude Code's hooks step does its own)."""
    from . import cli

    ns = argparse.Namespace(
        agent_id=scope.agent_id, person_id=scope.person_id, project_scope=scope.project_scope,
        db_path=_db(scope), no_upkeep=False, identity_command=None,
    )
    return cli._background_setup(ns, ask_hours=False) == 0, ""


# ── Agents that are not installed here: the setup, marked untested ──


def _print_only(h: hs.Harness, scope) -> int:
    mnemos = cli_mnemos()
    server = _server_args(scope, mnemos)
    _say(f"{h.label}: NOT TESTED. It is not installed on this machine, so this is what its own "
         "documentation says, not something that was run. Nothing is written for it.")
    _say()
    if h.key == "pi":
        _say("Tools (docs: pi.dev/docs/latest/mcp):")
        _say("  " + shlex.join(["pi", "mcp", "add", cn.SERVER_NAME, "--", *server]))
        _say("  or in ~/.pi/agent/mcp.json:")
        _say(json.dumps({"mcpServers": {cn.SERVER_NAME: {
            "command": server[0], "args": server[1:], "env": {"MNEMOS_HARNESS": "pi"}}}}, indent=2))
        _say("Wake and cue: Pi has no hook that runs a command; it takes TypeScript extensions "
             "(session_start, before_agent_start). Mnemos does not ship one yet.")
    else:
        _say("Tools (docs: dev.meta.ai/docs/muse-code/extending): in your Muse settings file "
             "(the docs do not give its path):")
        _say(json.dumps({"mcp_servers": {cn.SERVER_NAME: {
            "transport": "stdio", "command": server[0], "args": server[1:],
            "env": {"MNEMOS_HARNESS": "muse"}}}}, indent=2))
        _say("Wake and cue: Muse has SessionStart and UserPromptSubmit hooks in .muse/hooks.json, "
             "but its docs do not show the file's format or how a hook's output reaches the model. "
             "Nothing is offered until that is known.")
    _say()
    _say("Either way the agent can load its memory itself: the server's instructions tell it to "
         "call mnemos_context at the start of a session.")
    _say(f"If this works (or doesn't) on {h.label}, the table in docs/guide.md is where it goes.")
    return 0
