"""A host app's read-only view of one resident, end to end, with made-up data.

Run it from the repository's root, with no network:

    uv run python examples/host_read_view/run.py

It makes a throwaway home in a temporary folder and, through Mnemos's normal
write path, one store file that two residents share: Wren, who keeps memories
about Pat in a project called "lighthouse", and Otter, who keeps memories
about Sam in a project called "orchard". Wren also keeps one memory about a
third person, Quinn, in the same project. Every name and every word is made
up for this example.

Then it asks ``mnemos view`` for Wren's memory about Pat, one section at a
time, the way a host app would (a separate process, one JSON document a
call), and checks that nothing of Otter's, and nothing of Quinn's, appears
in any reply: no words, no ids, no names. It prints what each section
returned and exits non-zero if any check fails. The temporary folder is
removed at the end.
"""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

SIGNED = "example-model"
WREN = {"agent_id": "wren", "person_id": "pat-example", "project_scope": "lighthouse"}
QUINN = {"agent_id": "wren", "person_id": "quinn-example", "project_scope": "lighthouse"}
OTTER = {"agent_id": "otter", "person_id": "sam-example", "project_scope": "orchard"}
SECTIONS = ("summary", "memories", "standing", "journal", "notes", "handoffs", "beliefs")


def memory_id(said: str) -> str:
    return said.split("Memory ID: ", 1)[1].split()[0]


def build(db: Path) -> None:
    """Two residents in one file, written as an agent writes: captures, a
    standing memory, a journal entry, notes both ways, a handoff, a belief."""
    from mnemos import EngramStore, MnemosRuntime
    from mnemos.core.belief import Belief

    beliefs = []
    for scope, words in (
        (WREN, {
            "memories": ["The keeper's log lives in the blue binder on the shelf.",
                         "The harbour tide table is pinned beside the door."],
            "standing": "Pat likes replies short and plain.",
            "journal": "A quiet day. I sorted the blue binder by month.",
            "note": "I noticed the blue binder is nearly full.",
            "reply": "Thanks, a new binder is on its way.",
            "handoff": "Next time: ask whether the new binder arrived.",
            "belief": "Pat keeps paper records close at hand.",
        }),
        (QUINN, {
            "memories": ["Quinn's spare shed key hangs on the green hook."],
            "belief": "Quinn trusts hooks more than drawers.",
        }),
        (OTTER, {
            "memories": ["Otter's orchard ledger counts the plum trees each spring.",
                         "The orchard gate sticks after rain."],
            "standing": "Sam wants the orchard numbers in a table.",
            "journal": "Otter walked the orchard rows and counted forty plums.",
            "note": "I noticed the orchard gate needs oil.",
            "reply": "Sam will bring the oil can on Friday.",
            "handoff": "Next time: check the orchard gate after the oil.",
            "belief": "Sam plans the orchard a season ahead.",
        }),
    ):
        runtime = MnemosRuntime(db_path=str(db), use_dedicated_model=False, **scope)
        try:
            kept = [memory_id(runtime.capture(text, signed_as=SIGNED)) for text in words["memories"]]
            if "standing" in words:
                runtime.capture(words["standing"], signed_as=SIGNED, standing=True)
                runtime.journal(words["journal"], signed_as=SIGNED)
                runtime.note(words["note"], kind="noticed", signed_as=SIGNED)
                runtime.person_note(words["reply"])
                runtime.handoff(words["handoff"], signed_as=SIGNED)
        finally:
            runtime.close()
        beliefs.append(Belief(agent_id=scope["agent_id"], content=words["belief"], confidence=0.6,
                              supporting_engram_ids=kept[:1], source="agent", author_model=SIGNED))
    store = EngramStore(db)
    try:
        for belief in beliefs:
            store.save_belief(belief)
    finally:
        store.close()


def others(db: Path) -> dict[str, set[str]]:
    """Everything of Otter's and Quinn's the view must never show: their
    words, their ids, their names. Read straight from the file, for the check."""
    conn = sqlite3.connect(f"{db.resolve().as_uri()}?mode=ro&immutable=1", uri=True)
    words: set[str] = set()
    ids: set[str] = set()
    try:
        for table, owner, text in (("engrams", "owner_agent_id", "content"), ("journal_entries", "agent_id", "text"),
                                   ("notes", "agent_id", "text"), ("hypomnema_entries", "agent_id", "content")):
            for row in conn.execute(
                    f"SELECT id, {text} FROM {table} WHERE NOT ({owner}=? AND person_id=? AND project_scope=?)",
                    (WREN["agent_id"], WREN["person_id"], WREN["project_scope"])):
                ids.add(row[0])
                words.add(row[1].strip())
        for row in conn.execute("SELECT id, content FROM beliefs WHERE agent_id != ?", (WREN["agent_id"],)):
            ids.add(row[0])
            words.add(row[1])
        quinn = conn.execute("SELECT id, content FROM beliefs WHERE content LIKE 'Quinn%'").fetchone()
        ids.add(quinn[0])
        words.add(quinn[1])
    finally:
        conn.close()
    return {"words": words, "ids": ids, "names": {"otter", "sam-example", "orchard", "quinn-example"}}


def view(db: Path, home: Path, section: str) -> dict:
    """One section, asked for as a host asks: a process of its own."""
    done = subprocess.run(
        [sys.executable, "-m", "mnemos.cli", "view", "--protocol", "1", "--section", section,
         "--db-path", str(db), "--agent-id", WREN["agent_id"], "--person-id", WREN["person_id"],
         "--project-scope", WREN["project_scope"]],
        capture_output=True, text=True, timeout=120,
        env={"HOME": str(home), "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
             "PYTHONPATH": os.pathsep.join(sys.path), "PYTHONDONTWRITEBYTECODE": "1",
             "MNEMOS_DISABLE_DOTENV": "1"},
    )
    if done.returncode != 0:
        raise SystemExit(f"view --section {section} failed ({done.returncode}): {done.stdout}{done.stderr}")
    return json.loads(done.stdout)


def main() -> int:
    home = Path(tempfile.mkdtemp(prefix="mnemos-host-view-example-"))
    os.environ["HOME"] = str(home)
    os.environ["MNEMOS_DISABLE_DOTENV"] = "1"
    os.environ["MNEMOS_MAINTENANCE"] = "inline"  # upkeep here, not in a process left running
    for name in ("MNEMOS_AGENT_ID", "MNEMOS_PERSON_ID", "MNEMOS_PROJECT_SCOPE", "MNEMOS_DB_PATH"):
        os.environ.pop(name, None)
    failures: list[str] = []
    try:
        db = home / ".mnemos" / "residents.db"
        db.parent.mkdir(parents=True)
        build(db)
        hidden = others(db)
        print(f"One store, two residents: wren (about pat-example, in lighthouse) and otter "
              f"(about sam-example, in orchard), and one memory of wren's about quinn-example.")
        print("Asking for wren / pat-example / lighthouse, section by section:\n")
        for section in SECTIONS:
            reply = view(db, home, section)
            text = json.dumps(reply, ensure_ascii=False)
            leaks = sorted(x for kind in ("words", "ids", "names") for x in hidden[kind] if x and x in text)
            if leaks:
                failures.append(f"{section}: {leaks}")
            if reply["scope"] != WREN:
                failures.append(f"{section}: answered for {reply['scope']}")
            if section == "summary":
                print(f"summary   protocol {reply['protocol_version']}, schema {reply['schema_version']}, "
                      f"counts {json.dumps(reply['counts'])}")
                continue
            print(f"{section:<9} {len(reply['items'])} item(s), truncated {str(reply['truncated']).lower()}")
            for item in reply["items"]:
                print(f"          - {item.get('words') or item.get('text')}")
        print()
        if failures:
            print("FAILED: something of another resident's appeared:")
            for failure in failures:
                print(f"  {failure}")
            return 1
        print(f"Nothing of otter's or quinn-example's appeared in any reply "
              f"({len(hidden['words'])} texts, {len(hidden['ids'])} ids and {len(hidden['names'])} names checked).")
        return 0
    finally:
        shutil.rmtree(home, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
