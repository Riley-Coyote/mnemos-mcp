"""The agent forms and judges its own beliefs, keyless.

Two reflection kinds were legal in the schema but never produced or applied.
Wiring them completed the inversion: a keyless install does belief formation
through the agent's own turns, no provider. The server only ever *proposes*;
the agent's answer is what becomes a belief. (The other kind, the
contradiction question, is retired: test_contradiction_question_retired.py.)
"""

from __future__ import annotations

import re

import pytest

from mnemos.core.belief import Belief
from mnemos.simple_runtime import MnemosRuntime


@pytest.fixture
def db(tmp_path):
    return str(tmp_path / "kinds.db")


def _runtime(db):
    return MnemosRuntime(db_path=db, agent_id="t", person_id="p", project_scope="g")


def _evidence_ask(target):
    return ('On 3 different days you wrote something like this:\n'
            '- "The vektor project needs another perf pass" (October 1)\n'
            '- "The vektor project needs another perf pass" (October 2)\n'
            '- "The vektor project needs another perf pass" (October 3)\n'
            'Is there something you believe here? If there is, say it in one line with verdict hold; '
            f'if not, decline. Or leave it. [evidence:{target}]')


def _pending(rt, kind):
    return [
        i for i in rt.pending_reflections(limit=10) if i["kind"] == kind
    ]


class TestBeliefFormation:
    def test_a_legacy_word_question_is_never_offered(self, db):
        rt = _runtime(db)
        # Five captures sharing a real (non-structural) theme tag.
        for i in range(5):
            captured = rt.capture(content=f"The vektor project needs another perf pass, note {i}",
                       importance="high")
        target = re.search(r"Memory ID: (engram_\w+)", captured).group(1)
        assert rt._store.enqueue_reflection(
            "belief", target,
            'You keep returning to "vektor" (5 memories). Is that a belief you now hold? If it is, state it in one line with verdict hold; if it is not, decline. Or leave it. [theme:vektor]',
            agent_id="t", person_id="p", project_scope="g",
        )
        assert not any(
            i["prompt"].startswith('You keep returning to "') for i in rt.pending_reflections(limit=10)
        )
        assert "You keep returning to" not in rt.context()

    def test_answering_forms_an_agent_belief(self, db):
        rt = _runtime(db)
        for i in range(5):
            captured = rt.capture(content=f"The vektor project needs another perf pass, note {i}")
        target = re.search(r"Memory ID: (engram_\w+)", captured).group(1)
        rt._store.enqueue_reflection(
            "belief", target, _evidence_ask(target),
            agent_id="t", person_id="p", project_scope="g",
        )
        item = _pending(rt, "belief")[0]
        out = rt.reflect(
            item["target_id"], "Vektor's performance is never quite finished.", verdict="hold",
        )
        assert "Belief recorded" in out, out
        beliefs = rt._store.get_beliefs("t", active_only=True)
        mine = [b for b in beliefs if b.source == "agent"]
        assert any("never quite finished" in b.content for b in mine)

    def test_an_empty_answer_forms_nothing(self, db):
        rt = _runtime(db)
        for i in range(5):
            captured = rt.capture(content=f"The vektor project needs another perf pass, note {i}")
        target = re.search(r"Memory ID: (engram_\w+)", captured).group(1)
        rt._store.enqueue_reflection(
            "belief", target, _evidence_ask(target),
            agent_id="t", person_id="p", project_scope="g",
        )
        item = _pending(rt, "belief")[0]
        before = len(rt._store.get_beliefs("t"))
        rt.reflect(item["target_id"], "   ")
        assert len(rt._store.get_beliefs("t")) == before


class TestBeliefReaffirmation:
    def test_retire_retires_a_belief(self, db):
        rt = _runtime(db)
        rt._ensure_init()
        # Capture with an impact so no impact reflection is queued on this
        # engram — the belief reaffirmation must own its target uncontended
        # (the tool answers by target_id alone).
        rt.capture(content="anchor memory for the belief", impact="grounds a belief")
        eid = rt._store.get_active_engrams(agent_id="t", limit=1)[0].id
        rt._store.save_belief(Belief(agent_id="t", content="An outdated belief",
                                     confidence=0.6, source="agent",
                                     supporting_engram_ids=[eid]))
        # Reaffirmation reflection targets the supporting engram with a marker.
        rt._store.enqueue_reflection(
            "belief", eid,
            "You hold this belief: \"An outdated belief\". Still true? "
            f"[belief:{[b.id for b in rt._store.get_beliefs('t')][0]}]",
            agent_id="t", person_id="p", project_scope="g",
        )
        item = _pending(rt, "belief")[0]
        out = rt.reflect(item["target_id"], "No, not any more.", verdict="retire")
        assert "Retired" in out
        assert rt._store.get_beliefs("t", active_only=True) == []


class TestRestraintHolds:
    def test_the_packet_never_shows_more_than_two_reflections(self, db):
        rt = _runtime(db)
        for i in range(6):
            rt.capture(content=f"The vektor project needs another perf pass note {i}",
                       importance="high")
        rt.maintain()
        assert len(rt.pending_reflections(limit=2)) <= 2
