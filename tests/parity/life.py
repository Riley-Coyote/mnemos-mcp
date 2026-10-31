"""The scripted life: one companion's week, as the ops its runners send.

Two runners share one memory: the Mac (``ghost-mac/v1``) and the phone
(``phone/v1``). Each op is what a runner persisted before delivery: its
namespace, its idempotency key, when it was observed, and its arguments. The
words are synthetic, written for this harness; no real memory is in them.

An argument may name the memory or note an earlier op made, as a runner names
the id it got back: ``{"$memory": "<key>"}`` or ``{"$note": "<key>"}``. The
worker resolves it from that op's ledger row before delivery, so every
delivery of an op carries the same arguments and the same fingerprint.

Some corrections are stale on purpose: the phone corrects or forgets a memory
by the id it saw, after the Mac has already corrected it. Those are the
collisions ONE-COMPANION.md names ("a correction aimed at an engram that has
since changed"); the harness reports what the engine does with them.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from .determinism import T0

RUNNERS = {
    # runner: (namespace, session id it acts in)
    "mac": ("ghost-mac/v1", "parity-mac-session"),
    "phone": ("phone/v1", "phone:parity-device"),
}
SCOPE = {"agent_id": "parity", "person_id": "parity-person", "project_scope": "parity"}
MODEL = "claude-opus-5-5"


@dataclass(frozen=True)
class Op:
    index: int
    runner: str
    key: str
    operation: str
    arguments: dict[str, Any]
    observed_at: str
    tags: tuple[str, ...] = field(default=())

    @property
    def namespace(self) -> str:
        return RUNNERS[self.runner][0]

    @property
    def session(self) -> str:
        return RUNNERS[self.runner][1]

    def to_json(self) -> dict[str, Any]:
        return {
            "index": self.index, "runner": self.runner, "key": self.key,
            "operation": self.operation, "arguments": self.arguments,
            "observed_at": self.observed_at, "tags": list(self.tags),
        }

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> "Op":
        return cls(
            index=data["index"], runner=data["runner"], key=data["key"],
            operation=data["operation"], arguments=data["arguments"],
            observed_at=data["observed_at"], tags=tuple(data.get("tags") or ()),
        )

    def moment(self) -> datetime:
        return datetime.fromisoformat(self.observed_at)


def M(key: str) -> dict[str, str]:
    return {"$memory": key}


def N(key: str) -> dict[str, str]:
    return {"$note": key}


def scripted_life() -> list[Op]:
    """The life, in the order its first deliveries happen."""
    steps: list[tuple[float, str, str, str, dict[str, Any], tuple[str, ...]]] = []

    def at(day: float, runner: str, key: str, operation: str, tags: tuple[str, ...] = (), **arguments: Any) -> None:
        steps.append((day, runner, key, operation, arguments, tags))

    # Day 0: the Mac meets the person.
    at(0.00, "mac", "mac-01", "introduce", agent_model=MODEL, agent_name="Ghost")
    at(0.01, "mac", "mac-02", "capture",
       content="The person takes their coffee black and drinks it before nine.",
       impact="Mornings start early; plan anything that needs them before nine.",
       signed_as=MODEL)
    at(0.02, "mac", "mac-03", "capture",
       content="The person is building a small boat in the garage, a cedar-strip canoe.",
       importance="high", signed_as=MODEL)
    at(0.03, "mac", "mac-04", "capture",
       content="Always ask before deleting files in the person's projects.",
       impact="Destructive steps need a yes first.", standing=True, signed_as=MODEL)
    at(0.04, "mac", "mac-05", "capture",
       content="The person's sister is called Mara and lives in Lisbon.",
       signed_as=MODEL)
    at(0.20, "mac", "mac-06", "maintain")

    # Day 1: the phone joins, and both runners write.
    at(1.00, "phone", "phone-01", "introduce", agent_model=MODEL, agent_name="Ghost")
    at(1.01, "phone", "phone-02", "capture",
       content="On a walk the person said the canoe needs two more coats of varnish.",
       signed_as=MODEL)
    at(1.02, "mac", "mac-07", "correct", ("fresh",),
       target_id=M("mac-05"),
       correction="The person's sister is called Mara and moved from Lisbon to Porto in spring.",
       impact="Ask about Porto, not Lisbon.", signed_as=MODEL)
    # Stale: the phone still holds the Lisbon memory's id.
    at(1.03, "phone", "phone-03", "correct", ("stale",),
       target_id=M("mac-05"),
       correction="The person's sister Mara works as a translator.",
       signed_as=MODEL)
    at(1.04, "mac", "mac-08", "capture",
       content="The person prefers short replies on the phone and long ones at the desk.",
       impact="Match length to the device.", signed_as=MODEL)
    at(1.05, "mac", "mac-09", "reflect",
       target_id=M("mac-02"),
       text="Early mornings are when the person is clearest; that's when to raise hard things.",
       signed_as=MODEL)

    # Day 2: corrections by note id, a forget, and a stale forget.
    at(2.00, "mac", "mac-10", "capture",
       content="The canoe's name will be Heron.", signed_as=MODEL)
    at(2.01, "mac", "mac-11", "correct", ("fresh",),
       target_id=N("mac-10"),
       correction="The canoe's name will be Grey Heron, after the bird on the river.",
       signed_as=MODEL)
    at(2.02, "phone", "phone-04", "capture",
       content="The person is learning the cello on Thursday evenings.", signed_as=MODEL)
    at(2.03, "mac", "mac-12", "correct", ("fresh",),
       target_id=M("phone-04"), action="archive", correction="",
       signed_as=MODEL)
    at(2.04, "phone", "phone-05", "correct", ("stale",),
       target_id=M("phone-04"), action="archive", correction="",
       signed_as=MODEL)
    at(2.10, "mac", "mac-13", "maintain")

    # Day 3: a correction of a correction, and the phone behind by two.
    at(3.00, "mac", "mac-14", "correct", ("fresh",),
       target_id=M("mac-07"),
       correction="The person's sister Mara lives in Porto and visits every August.",
       signed_as=MODEL)
    at(3.01, "phone", "phone-06", "correct", ("stale",),
       target_id=M("mac-05"),
       correction="Mara, the person's sister, is coming to stay in August.",
       signed_as=MODEL)
    at(3.02, "mac", "mac-15", "capture",
       content="The person dislikes being reminded about the gym.",
       impact="Leave exercise alone unless asked.", signed_as=MODEL)
    at(3.03, "phone", "phone-07", "correct", ("fresh",),
       target_id=M("mac-15"), action="mark_standing", correction="",
       signed_as=MODEL)
    at(3.04, "mac", "mac-16", "reflect",
       target_id=M("mac-03"), text="The canoe is a long project; it matters to them.",
       verdict="", signed_as=MODEL)

    # Day 4: a correction found by words, not id, and more captures.
    at(4.00, "phone", "phone-08", "capture",
       content="The person's favourite tea is a smoky lapsang.", signed_as=MODEL)
    at(4.01, "mac", "mac-17", "correct", ("query",),
       query="favourite tea lapsang",
       correction="The person's favourite tea is a smoky lapsang, brewed weak.",
       signed_as=MODEL)
    at(4.02, "mac", "mac-18", "capture",
       content="The person wants the canoe in the water before the first of June.",
       impact="A deadline worth keeping in view.", signed_as=MODEL)
    at(4.03, "phone", "phone-09", "correct", ("stale",),
       target_id=M("mac-10"),
       correction="The canoe is to be called Heron Two.",
       signed_as=MODEL)
    at(4.10, "mac", "mac-19", "maintain", deep=True)

    # Day 5: the last of the week.
    at(5.00, "mac", "mac-20", "capture",
       content="The person finished varnishing the canoe on Saturday.", signed_as=MODEL)
    at(5.01, "phone", "phone-10", "capture",
       content="The person asked to be reminded to buy paddles.", signed_as=MODEL)
    at(5.02, "mac", "mac-21", "correct", ("fresh",),
       target_id=M("phone-10"), action="archive", correction="",
       signed_as=MODEL)
    at(5.03, "phone", "phone-11", "reflect",
       target_id=M("mac-18"), text="The June deadline is close now; it's nearly done.",
       signed_as=MODEL)
    at(5.04, "mac", "mac-22", "capture",
       content="The person's canoe Grey Heron was launched on the river at dawn.",
       impact="A long project, finished; worth remembering how it felt.",
       signed_as=MODEL)
    at(5.10, "mac", "mac-23", "maintain")

    ops: list[Op] = []
    for index, (day, runner, key, operation, arguments, tags) in enumerate(steps):
        moment = T0 + timedelta(days=day)
        ops.append(Op(
            index=index, runner=runner, key=key, operation=operation,
            arguments=arguments, observed_at=moment.astimezone(timezone.utc).isoformat(),
            tags=tags,
        ))
    keys = [op.key for op in ops]
    assert len(keys) == len(set(keys)), "every op has a key of its own"
    return ops
