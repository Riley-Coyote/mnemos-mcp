#!/usr/bin/env python
"""Distribution-readiness proof for Mnemos, run against the real artifact.

Not a unit test — this exercises the shipped wheel the way a stranger would,
and the agent's own judgement on a keyless store, so a launch can claim what
is actually true. Run from the repo root with the dev environment:

    uv run --extra dev --extra embeddings python scripts/readiness_check.py

It prints a PASS, FAIL or SKIP line per check and a JSON block of the
mind-state numbers for the readiness report, and exits non-zero if anything
fails. A SKIP says what was missing: beliefs need the local meaning model
(the ``embeddings`` extra, then ``mnemos embeddings download``).

Checks
  C1  a fresh, keyless `pip install` of the built wheel yields a server whose
      simple tools list over the real stdio protocol, and a capture survives a
      process restart — the amnesia gate against the actual artifact.
  C2  on a keyless store of the agent's own signed captures, all five shifts
      are alive (impact coverage, distilled-into edges, surprise on a novel
      capture, links beyond 'supports', identity rows).
  C3  `mnemos doctor` reports a real store honestly.
  C4  the agent judges, by its own verdict: a surprising capture is asked
      about and the verdict types the edge; an idea returning on three days
      is asked about, held as a signed belief, and retired by the agent.
  C5  nothing leaves the machine: with a provider key in the environment and
      no provider chosen for Mnemos, saving and maintaining open no
      connection.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import socket
import subprocess
import sys
import tempfile
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
RESULTS: list[tuple[str, str, str]] = []

# The agent whose memory this is: every capture it makes is signed.
AGENT = "claude-opus-5-5"

SIMPLE_TOOLS = {
    "mnemos_capture", "mnemos_context", "mnemos_correct", "mnemos_handoff",
    "mnemos_health", "mnemos_introduce", "mnemos_journal", "mnemos_maintain",
    "mnemos_note", "mnemos_recall", "mnemos_reflect",
}


def check(name: str, ok: bool, detail: str = "") -> None:
    status = "PASS" if ok else "FAIL"
    RESULTS.append((name, status, detail))
    print(f"  [{status}] {name}" + (f" — {detail}" if detail else ""))


def skip(name: str, reason: str) -> None:
    RESULTS.append((name, "SKIP", reason))
    print(f"  [SKIP] {name} — {reason}")


def _memory_id(said: str) -> str:
    return re.search(r"Memory ID: (engram_\w+)", said).group(1)


# ─────────────────────────── C1: the shipped wheel ───────────────────────────

def build_and_install_wheel(workdir: Path) -> Path:
    """Build the wheel and install it UNLOCKED into a clean venv.

    Unlocked (no uv.lock) so dependencies resolve from PyPI exactly as a user's
    `pip install` does — the only way to catch a bad declared dependency range.
    Returns the venv's `mnemos` executable path.
    """
    dist = workdir / "dist"
    subprocess.run(
        ["uv", "build", "--wheel", "--out-dir", str(dist)],
        cwd=REPO, check=True, capture_output=True, text=True,
    )
    wheel = next(dist.glob("mnemos*.whl"))

    venv = workdir / "venv"
    subprocess.run([sys.executable, "-m", "venv", str(venv)], check=True,
                   capture_output=True)
    pip = venv / "bin" / "pip"
    subprocess.run([str(pip), "install", "--quiet", "--upgrade", "pip"],
                   check=True, capture_output=True)
    subprocess.run([str(pip), "install", "--quiet", str(wheel)],
                   check=True, capture_output=True, text=True)
    return venv / "bin" / "mnemos"


def c1_stdio_and_restart(mnemos_bin: Path, home: Path) -> None:
    """Drive the installed server over real stdio, then prove a restart remembers."""
    from mcp.client.session import ClientSession
    from mcp.client.stdio import StdioServerParameters, stdio_client

    db = str(home / ".mnemos" / "readiness.db")
    token = f"cold-brew-{uuid.uuid4().hex[:12]}"
    env = {
        "HOME": str(home),
        "PATH": f"{mnemos_bin.parent}:/usr/bin:/bin",
        "MNEMOS_DISABLE_DOTENV": "1",
    }

    def params():
        return StdioServerParameters(
            command=str(mnemos_bin),
            args=["serve", "--mode", "simple", "--db-path", db,
                  "--agent-id", "readiness", "--person-id", "tester",
                  "--project-scope", "check"],
            env=env,
        )

    async def journey():
        # Session one: list the tools, then capture.
        async with stdio_client(params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                tools = {t.name for t in (await s.list_tools()).tools}
                missing, extra = sorted(SIMPLE_TOOLS - tools), sorted(tools - SIMPLE_TOOLS)
                check(f"C1 stdio: the {len(SIMPLE_TOOLS)} simple tools list over the wire",
                      not missing and not extra,
                      f"{len(tools)} tools" + (f"; missing {missing}" if missing else "")
                      + (f"; unexpected {extra}" if extra else ""))
                await s.call_tool(
                    "mnemos_capture",
                    {"content": f"Riley drinks {token} every morning", "signed_as": AGENT},
                )
        # Session two: a fresh process. Nothing carried but the filesystem.
        async with stdio_client(params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                result = await s.call_tool("mnemos_recall", {"query": "morning drink"})
                text = "\n".join(
                    b.text for b in result.content
                    if getattr(b, "type", None) == "text"
                )
                check("C1 restart: a capture survives a new process (real wheel)",
                      token in text, "recall returned the earlier capture")

    asyncio.run(journey())


# ─────────────────────────── C2: the five shifts ─────────────────────────────

def c2_mind_state(workdir: Path) -> dict:
    """Build a keyless store where every shift should fire, then measure it."""
    sys.path.insert(0, str(REPO))
    import sqlite3

    from benchmarks.continuity_eval import mind_state
    from mnemos.consolidation.softening import run_softening_pass
    from mnemos.simple_runtime import MnemosRuntime

    db = str(workdir / "mind.db")
    rt = MnemosRuntime(db_path=db, agent_id="mind", person_id="tester",
                       project_scope="check")

    # The agent's own captures, each with an impact it wrote (shift 1). Three
    # are about the same work, so they link to each other (shift 4).
    facts = [
        ("Riley ships every Mnemos change through a pull request, never straight to main.",
         "changes how I land my work"),
        ("Every Mnemos pull request waits for CI before Riley merges it.",
         "changes when I call work done"),
        ("The Mnemos release checklist ends with a pull request and a green CI run.",
         "changes how I ship a release"),
        ("Riley prefers short answers in plain words, with no preamble.",
         "changes how I write to him"),
        ("Riley works best at night; his peak is between two and four.",
         "changes when I expect deep work"),
        ("Verify by running the real thing, never by reading the code.",
         "the discipline under everything I do here"),
    ]
    for content, impact in facts:
        rt.capture(content=content, importance="high", impact=impact, signed_as=AGENT)

    # Surprise is an encode-time signal: a genuinely novel capture should
    # register non-zero prediction error.
    engram = rt._encoder.encode(
        content="An entirely unrelated fact about deep-sea bioluminescent squid",
        agent_id="mind", author_kind="agent", author_model=AGENT,
    )
    surprise = float(getattr(engram.encoding_context, "surprise_level", 0.0) or 0.0)

    # Let memory fade so softening teaches (DISTILLED_INTO, shift 2): faint, and
    # old. The age is the agent's lived hours, which a check cannot live
    # through, so the pass is told memories this young may teach.
    conn = sqlite3.connect(db)
    conn.execute(
        "UPDATE engrams SET created_at='2020-01-01T00:00:00+00:00', "
        "last_accessed='2020-01-01T00:00:00+00:00', accessibility=0.1"
    )
    conn.commit()
    conn.close()
    run_softening_pass(store=rt._store, config={"softening_min_age_hours": 0},
                       llm_client=None, agent_id="mind")
    rt.maintain(deep=False)  # identity pass + connection discovery
    rt.close()

    state = mind_state(db)
    state["shift_3_surprise"] = {"surprise_level": round(surprise, 3),
                                 "alive": surprise > 0.0}

    check("C2 shift 1 — traces (impact coverage)",
          state["shift_1_traces"]["alive"],
          f"{state['shift_1_traces']['impact_coverage']:.0%}")
    check("C2 shift 2 — forgetting that teaches (distilled-into)",
          state["shift_2_lessons"]["alive"],
          f"{state['shift_2_lessons']['distilled_into']} edges")
    check("C2 shift 3 — surprise as growth (encode-time)",
          state["shift_3_surprise"]["alive"],
          f"surprise={state['shift_3_surprise']['surprise_level']}")
    check("C2 shift 4 — resonance (links, not all 'supports')",
          state["shift_4_resonance"]["alive"],
          f"{state['shift_4_resonance']['supports_share']:.0%} supports, "
          f"{state['shift_4_resonance']['relation_kinds']} kinds")
    check("C2 shift 5 — identity from the graph",
          state["shift_5_identity"]["alive"],
          f"{state['shift_5_identity']['identity_rows']} rows")
    return state


# ──────────── C4: the agent judges, by its own verdict, keyless ────────────

# Thirty-seven lessons about unrelated things, and one idea returning three
# times. The detector asks about an idea only when it stands out among at
# least thirty of the agent's own impact lines, by meaning.
_BACKGROUND_LESSONS = [
    "Bread needs a long cold proof to taste of anything.",
    "Saturn's rings are mostly water ice, and younger than the dinosaurs.",
    "Tomatoes split when a dry week ends in heavy rain.",
    "A minor seventh chord leaves a question open.",
    "Code review goes faster when the diff is small.",
    "Night trains let you wake up in another country.",
    "Cast iron wants oil after every wash.",
    "Owls turn their heads because their eyes cannot move.",
    "A chess opening is only as good as the middlegame it leads to.",
    "Concrete keeps curing for years after it is poured.",
    "The Dead Sea is sinking about a metre a year.",
    "Watercolour cannot be fixed once the paper dries.",
    "Bees dance to tell each other where the flowers are.",
    "A bicycle chain lasts longer when it is cleaned often.",
    "Glaciers move faster in summer than in winter.",
    "Sourdough starter smells of acetone when it is hungry.",
    "Japanese joinery holds without a single nail.",
    "Coral bleaches when the water stays too warm.",
    "A good map leaves out almost everything.",
    "Violin varnish changes how the wood vibrates.",
    "Deserts can be freezing at night.",
    "Tea steeped too long turns bitter.",
    "Octopuses taste with their arms.",
    "Old bridges were tuned by soldiers breaking step.",
    "Basil hates the refrigerator.",
    "A marathon is mostly the last ten kilometres.",
    "Moss grows where the light is low and steady.",
    "Spreadsheets hide errors in the cells nobody reads.",
    "Lighthouses each flash a pattern of their own.",
    "Ice skates glide on a film of melted water.",
    "Fermented chillies keep for a year in brine.",
    "Wolves changed the course of rivers in Yellowstone.",
    "A typewriter teaches you to finish the sentence in your head.",
    "Salt draws the water out of an aubergine.",
    "Pianos drift out of tune when the seasons change.",
    "Fog forms when warm air crosses cold water.",
    "A kite flies best on a steady wind, not a strong one.",
]
_RETURNING_IDEA = [
    "The rendered page is the only honest judge of the work.",
    "Only the render tells the truth about whether the work is right.",
    "What the page actually renders is the honest judge, not my reasoning about it.",
]


def c4_agent_judgment(workdir: Path) -> dict:
    """Contradiction and belief, through the agent's own verdicts, no provider.

    Drives the real runtime end to end. A surprising capture becomes a
    question the agent answers with a verdict, which types the edge. An idea
    the agent keeps returning to on three days becomes a question, held as a
    signed belief, then retired by the agent. Noticing an idea that returns is
    done by meaning, so this half needs the local meaning model.
    """
    import sqlite3 as _sq

    from benchmarks.continuity_eval import mind_state
    from mnemos.simple_runtime import MnemosRuntime

    db = str(workdir / "judgment.db")
    rt = MnemosRuntime(db_path=db, agent_id="mind", person_id="tester",
                       project_scope="check")

    # Contradiction: a surprising capture against what was held.
    for i in range(6):
        rt.capture(content=f"The vektor renderer needs another optimization pass, item {i}",
                   signed_as=AGENT)
    eng = rt._encoder.encode(
        content="Vektor's renderer is finished and needs no further optimization",
        agent_id="mind", author_kind="agent", author_model=AGENT,
    )
    eng.encoding_context.surprise_level = 0.7
    rt._store.save_engram(eng)
    rt.maintain()
    contra_asks = [i for i in rt.pending_reflections(limit=10) if i["kind"] == "contradiction"]
    check("C4 contradiction: a surprising capture is asked about", bool(contra_asks))
    if contra_asks:
        rt.reflect(contra_asks[0]["target_id"], "It conflicts with what I held about the renderer.",
                   verdict="contradicts", signed_as=AGENT)
    conn = _sq.connect(db)
    contradictions = conn.execute(
        "SELECT COUNT(*) FROM connections WHERE relation='contradicts' "
        "AND formed_by='agent_reflection'"
    ).fetchone()[0]
    conn.close()
    check("C4 contradiction: the agent's verdict types the edge",
          contradictions > 0, f"{contradictions} agent contradiction edge(s)")

    # Belief: an idea the agent returns to on three days, by meaning.
    meaning = rt.semantic_status(verify=True)
    names = ("C4 belief: an idea returning on three days is asked about",
             "C4 belief: held by the agent's verdict, it stands, signed",
             "C4 belief: the agent can retire it (the ratchet runs down)")
    if not meaning.get("active"):
        why = " ".join(str(meaning.get("reason") or "unavailable").split())
        print(f"  meaning: off — {why[:160]}")
        for name in names:
            skip(name, "needs the local meaning model (the embeddings extra, "
                       "then `mnemos embeddings download`)")
    else:
        rt.handoff("I check the work where it renders.", signed_as=AGENT)
        rt.handoff("Next I look at the rendered page before anything else.", signed_as=AGENT)
        ids = []
        for lesson in _BACKGROUND_LESSONS:
            ids.append(_memory_id(rt.capture(f"A note on: {lesson}", impact=lesson, signed_as=AGENT)))
        idea = [_memory_id(rt.capture(f"Riley and I compared draft {i} with what the page rendered.",
                                      impact=lesson, signed_as=AGENT))
                for i, lesson in enumerate(_RETURNING_IDEA)]
        now = datetime.now(timezone.utc)
        conn = rt._store._get_conn()
        for index, target in enumerate(ids):
            conn.execute("UPDATE engrams SET created_at = ?, author_session = ? WHERE id = ?",
                         ((now - timedelta(days=index + 1, hours=1)).isoformat(),
                          f"background-{index}", target))
        for index, target in enumerate(idea):
            conn.execute("UPDATE engrams SET created_at = ?, author_session = ? WHERE id = ?",
                         ((now - timedelta(days=9 - 3 * index, hours=2)).isoformat(),
                          f"idea-{index}", target))
        # Every capture ran maintenance on a store too small to ask about.
        conn.execute("DELETE FROM meta WHERE key = ?", (rt._meta_key("ideas_noticed_at"),))
        rt._store._commit()
        rt.maintain()
        asks = [dict(row) for row in rt._store._get_conn().execute(
            "SELECT * FROM reflection_queue WHERE kind = 'belief' AND answered_at IS NULL")]
        evidence = []
        for ask in asks:
            found = re.search(r"\[evidence:([A-Za-z0-9_,]+)\]", ask["prompt"] or "")
            if found and set(found.group(1).split(",")) == set(idea):
                evidence.append(ask)
        check(names[0], bool(evidence), f"{len(asks)} belief question(s)")
        if evidence:
            held = "The rendered page is the only honest judge of the work."
            rt.reflect(evidence[0]["target_id"], held, verdict="hold", signed_as=AGENT)
            beliefs = [b for b in rt._store.get_beliefs("mind", active_only=True)
                       if b.content == held]
            check(names[1], bool(beliefs) and beliefs[0].author_model == AGENT,
                  f"{len(beliefs)} belief(s), signed {beliefs[0].author_model if beliefs else '—'}")
            if beliefs:
                rt.correct(correction="", target_id=beliefs[0].id, action="forget", signed_as=AGENT)
                left = [b for b in rt._store.get_beliefs("mind", active_only=True)
                        if b.content == held]
                check(names[2], not left)
            else:
                skip(names[2], "no belief to retire")
        else:
            skip(names[1], "no question was asked")
            skip(names[2], "no question was asked")

    rt.close()
    return mind_state(db)


# ─────────────────────────── C3: doctor honesty ──────────────────────────────

def c3_doctor(mnemos_bin: Path, home: Path) -> None:
    db = str(home / ".mnemos" / "readiness.db")  # the C1 store, now populated
    out = subprocess.run(
        [str(mnemos_bin), "doctor", "--db-path", db, "--agent-id", "readiness",
         "--person-id", "tester", "--project-scope", "check"],
        capture_output=True, text=True,
        env={"HOME": str(home), "PATH": f"{mnemos_bin.parent}:/usr/bin:/bin",
             "MNEMOS_DISABLE_DOTENV": "1"},
    ).stdout
    check("C3 doctor: reports a real store honestly",
          "DB exists:    yes" in out and "Continuity:" in out)


# ─────────────────────────── C5: nothing leaves ──────────────────────────────

def c5_nothing_leaves(workdir: Path) -> None:
    """A provider key in the environment chooses nothing: saves and upkeep
    open no connection. Any socket opened in this process is caught before it
    connects, whichever client opens it."""
    from mnemos.simple_runtime import MnemosRuntime

    opened: list[object] = []
    connect, connect_ex = socket.socket.connect, socket.socket.connect_ex

    def caught(self, address):
        opened.append(address)
        raise OSError("readiness: no connection may leave the machine")

    held = {name: os.environ.get(name) for name in ("OPENROUTER_API_KEY", "MNEMOS_LLM_PROVIDER")}
    os.environ["OPENROUTER_API_KEY"] = "readiness-not-a-real-key"
    os.environ.pop("MNEMOS_LLM_PROVIDER", None)
    socket.socket.connect, socket.socket.connect_ex = caught, caught
    try:
        rt = MnemosRuntime(db_path=str(workdir / "privacy.db"), agent_id="mind",
                           person_id="tester", project_scope="check")
        for words in ("Riley keeps his health details private; never repeat them.",
                      "Riley said his health details stay private, even from notes."):
            rt.capture(words, signed_as=AGENT)
        rt.maintain()
        rt.close()
    finally:
        socket.socket.connect, socket.socket.connect_ex = connect, connect_ex
        for name, value in held.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
    check("C5 privacy: a provider key alone sends nothing", not opened,
          f"{len(opened)} connection(s) attempted")


def main() -> int:
    print("Mnemos readiness check — against the built wheel and a keyless store")
    print("=" * 70)
    with tempfile.TemporaryDirectory() as td:
        workdir = Path(td)
        home = workdir / "home"
        (home / ".mnemos").mkdir(parents=True)

        print("\nC1 — fresh keyless install of the built wheel")
        mnemos_bin = build_and_install_wheel(workdir)
        c1_stdio_and_restart(mnemos_bin, home)

        print("\nC2 — the five shifts on a keyless store")
        state = c2_mind_state(workdir)

        print("\nC4 — the agent judges, by its own verdict (keyless)")
        state["agent_judgment"] = c4_agent_judgment(workdir)["agent_judgment"]

        print("\nC3 — doctor")
        c3_doctor(mnemos_bin, home)

        print("\nC5 — nothing leaves the machine")
        c5_nothing_leaves(workdir)

    passed = sum(1 for _, status, _ in RESULTS if status == "PASS")
    failed = sum(1 for _, status, _ in RESULTS if status == "FAIL")
    skipped = sum(1 for _, status, _ in RESULTS if status == "SKIP")
    print("\n" + "=" * 70)
    print(f"Readiness: {passed} passed, {failed} failed, {skipped} skipped "
          f"of {len(RESULTS)} checks")
    print("\nMind-state baseline (for the readiness report):")
    print(json.dumps(state, indent=2))
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
