"""Tests for the scoped hypomnema continuity layer."""

import pytest


class TestHypomnemaStore:
    def test_init_creates_hypomnema_table(self, store):
        conn = store._get_conn()
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
        table_names = {r[0] for r in rows}

        assert "hypomnema_entries" in table_names

    def test_write_and_search_hypomnema(self, store):
        entry_id = store.write_hypomnema_entry(
            "Riley and Vektor keep functional memory, hypomnema, and Mnemos distinct.",
            agent_id="vektor",
            person_id="riley",
            project_scope="codex-test",
            domain="foundational",
            tags="memory,continuity",
            confidence=0.9,
            salience=0.8,
            foundational=True,
        )

        results = store.search_hypomnema(
            "functional memory mnemos",
            agent_id="vektor",
            person_id="riley",
            project_scope="codex-test",
        )

        assert results[0]["id"] == entry_id
        assert results[0]["tags"] == ["memory", "continuity"]
        assert results[0]["foundational"] is True

    def test_revise_hypomnema_keeps_revision_history(self, store):
        entry_id = store.write_hypomnema_entry(
            "Hypomnema is just a note.",
            agent_id="vektor",
            person_id="riley",
            project_scope="codex-test",
        )

        store.revise_hypomnema_entry(
            entry_id,
            "Hypomnema is scoped continuity that can revise before promotion.",
            reason="sharpen definition",
            agent_id="vektor",
            person_id="riley",
            project_scope="codex-test",
            confidence=0.85,
            salience=0.7,
        )

        entry = store.get_hypomnema_entry(
            entry_id,
            agent_id="vektor",
            person_id="riley",
            project_scope="codex-test",
        )

        assert entry["revision_count"] == 1
        assert entry["confidence"] == pytest.approx(0.85)
        assert entry["revisions"][0]["prior_content"] == "Hypomnema is just a note."

    def test_supersede_hypomnema_hides_original_from_active_search(self, store):
        entry_id = store.write_hypomnema_entry(
            "Old continuity claim",
            agent_id="vektor",
            person_id="riley",
            project_scope="codex-test",
        )

        replacement_id = store.supersede_hypomnema_entry(
            entry_id,
            "New continuity claim",
            reason="better evidence",
            agent_id="vektor",
            person_id="riley",
            project_scope="codex-test",
        )

        active = store.search_hypomnema(
            "",
            agent_id="vektor",
            person_id="riley",
            project_scope="codex-test",
        )
        inactive = store.get_hypomnema_entry(
            entry_id,
            agent_id="vektor",
            person_id="riley",
            project_scope="codex-test",
        )

        assert [entry["id"] for entry in active] == [replacement_id]
        assert inactive["active"] is False
        assert inactive["superseded_by"] == replacement_id

    def test_promotion_candidates_are_the_notes_the_agent_kept_coming_back_to(self, store):
        """WP-R12: a note is ready when the agent revised it and asked for it
        in two sessions. How sure or salient its words were scored, and
        whether it is foundational, decide nothing."""
        scope = {"agent_id": "vektor", "person_id": "riley", "project_scope": "codex-test"}
        attended_id = store.write_hypomnema_entry(
            "Interesting but weak continuity",
            **scope,
            authored_by="agent",
            confidence=0.7,
            salience=0.6,
        )
        store.revise_hypomnema_entry(
            attended_id, "Interesting continuity, checked again.", reason="checked",
            revised_by="claude-opus-5-5", **scope,
        )
        for session in ("session-one", "session-two"):
            store.record_trace(tool="recall", session=session, read_ids=[attended_id], **scope)
        sure_id = store.write_hypomnema_entry(
            "Foundational continuity ready for Mnemos.",
            **scope,
            authored_by="agent",
            confidence=0.9,
            salience=0.8,
            foundational=True,
        )

        candidates = store.get_hypomnema_promotion_candidates(**scope)

        assert [entry["id"] for entry in candidates] == [attended_id]
        assert (candidates[0]["revised_by_agent"], candidates[0]["used_in_sessions"]) == (1, 2)
        assert sure_id not in [entry["id"] for entry in candidates]


def test_a_note_is_reachable_however_full_the_store_gets(store):
    """Ranking must consider every note in scope, not a recent slice.

    A cap applied *before* scoring is silent amnesia. With the old
    `LIMIT 100`, a store of 200 notes could never surface the older half
    no matter how relevant or how foundational — and the packet still
    returned its full complement of entries and looked perfectly healthy.
    """
    scope = dict(agent_id="ceiling", person_id="user", project_scope="global")

    buried_id = store.write_hypomnema_entry(
        "The deploy pipeline runs migrations before rollout",
        source="observed", domain="topical", confidence=0.9, salience=0.9,
        **scope,
    )
    # Bury it under far more than the old ceiling, all revised later.
    for i in range(250):
        store.write_hypomnema_entry(
            f"Routine note number {i} about unrelated day to day work",
            source="observed", domain="situational",
            confidence=0.5, salience=0.4, **scope,
        )

    found = store.search_hypomnema(
        "deploy pipeline migrations rollout", limit=5, **scope
    )

    assert buried_id in [entry["id"] for entry in found], (
        "a highly relevant note became unreachable purely because newer "
        "notes were written after it"
    )
