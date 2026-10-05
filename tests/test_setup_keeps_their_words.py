"""Advanced setup keeps what the person says as their own words.

Setup asked the person for the starting context and wrote it as up to five
memories: two in the agent's voice ("My user is …", "I am Nova …") and the
rest as sentence fragments ("Riley told me: …"), each with a lesson the agent
never drew. None of it landed: every write named a source that doesn't exist,
failed, and setup said "Encoded 0 seed memories". Promoting a note failed the
same way. Then it wrote two beliefs for the agent from the person's answers
and told them, in the agent's voice, "I'm forming my first beliefs", after
asking for history to import that it never imported. Now the person's answer
is kept once, whole, as theirs; the projects as setup's own lines; setup
forms no beliefs and asks nothing it won't use; and a promoted note keeps
whose words it was.
"""

import pytest

pytest.importorskip("mcp.server.fastmcp")

from mnemos import mcp_server  # noqa: E402
from mnemos.config.loader import load_config, save_config  # noqa: E402

_STATE = ("_store", "_encoder", "_retriever", "_llm_client", "_embedding_index", "_shared_pool")

WORDS = (
    "I'm Riley. I build memory for minds like yours. Be careful with what "
    "I tell you about my health: keep it private."
)


@pytest.fixture
def server(monkeypatch):
    """The server, with a store of its own in this test's home."""
    for name in _STATE:
        monkeypatch.setattr(mcp_server, name, None)
    mcp_server._config_invalidate()
    yield mcp_server
    if mcp_server._store is not None:
        mcp_server._store.close()
    mcp_server._config_invalidate()


def _set_up(server, **config):
    save_config(config)
    server._config_invalidate()


def _memories(server):
    rows = server._store._get_conn().execute(
        "SELECT content, author_kind, author_model, owner_agent_id, person_id, impact "
        "FROM engrams ORDER BY content"
    )
    return [dict(row) for row in rows]


def test_setup_keeps_what_the_person_said_once_whole_and_as_theirs(server):
    _set_up(server, setup_step=3, agent_id="nova", agent_name="Nova",
            user_name="Riley", person_id="riley")

    said = server.mnemos_setup(WORDS)

    assert said == "Kept what Riley said, in their own words.\n\n" + server.ONBOARDING_PROMPTS[4]
    # Nothing in the agent's voice, no fragments, no lesson: only their words.
    assert _memories(server) == [{
        "content": WORDS, "author_kind": "person", "author_model": "",
        "owner_agent_id": "nova", "person_id": "riley", "impact": "",
    }]
    assert load_config()["setup_step"] == 4


def test_an_empty_answer_keeps_nothing_and_says_nothing_about_it(server):
    _set_up(server, setup_step=3, agent_id="nova", user_name="Riley", person_id="riley")

    said = server.mnemos_setup("   ")

    assert said == server.ONBOARDING_PROMPTS[4]
    assert _memories(server) == []


def test_setup_keeps_the_projects_as_its_own_lines_not_the_agents(server):
    _set_up(server, setup_step=4, agent_id="nova", user_name="Riley", person_id="riley")

    said = server.mnemos_setup("mnemos, the sanctuary")

    assert said == server.ONBOARDING_PROMPTS[8]
    assert load_config()["setup_step"] == 7
    assert [(m["content"], m["author_kind"], m["person_id"], m["impact"])
            for m in _memories(server)] == [
        ("Active project: mnemos", "system", "riley", ""),
        ("Active project: the sanctuary", "system", "riley", ""),
    ]


def _beliefs(server):
    return server._store._get_conn().execute("SELECT content FROM beliefs").fetchall()


def test_a_setup_saved_on_the_import_question_moves_on_and_forms_no_beliefs(server):
    """Step 5 asked for history it never imported, then wrote "Riley is
    deeply invested in mnemos" (70%) and "The work centers on …" (65%) as the
    agent's beliefs. A setup saved there moves on to the provider question."""
    _set_up(server, setup_step=5, agent_id="nova", user_name="Riley", person_id="riley",
            user_description=WORDS, indexer={"known_projects": ["mnemos", "the sanctuary"]})

    said = server.mnemos_setup("~/notes")

    assert said == server.ONBOARDING_PROMPTS[8]
    assert load_config()["setup_step"] == 7
    server._ensure_store()
    assert _beliefs(server) == []


def test_the_whole_setup_speaks_for_no_one_and_says_what_it_kept(server):
    answers = ["", "Nova", "Riley", WORDS, "mnemos, the sanctuary", "skip"]
    said = [server.mnemos_setup(answer) for answer in answers]

    asked = server.ONBOARDING_PROMPTS
    # No import question, no beliefs: the projects go straight to the provider.
    assert said[:5] == [
        asked[0] + "\n\n" + asked[1],
        asked[2],
        asked[3],
        "Kept what Riley said, in their own words.\n\n" + asked[4],
        asked[8],
    ]
    assert said[5].startswith("Nova is ready: 3 memories, ")
    assert sorted(m["author_kind"] for m in _memories(server)) == ["person", "system", "system"]
    assert _beliefs(server) == []
    assert load_config()["setup_complete"] is True


def test_promoting_a_note_keeps_whose_words_it_was(server):
    _set_up(server, setup_complete=True, agent_id="nova", person_id="riley")
    store = server._ensure_store()
    mine = store.write_hypomnema_entry(
        "The cue should ask, not tell.", agent_id="nova", person_id="riley",
        authored_by="agent", author_id="nova", author_model="claude-opus-5-5",
    )
    together = store.write_hypomnema_entry(
        "Active project for this relationship: mnemos", agent_id="nova",
        person_id="riley", source="co-formed",
    )

    for entry_id in (mine, together):
        said = server.mnemos_hypomnema_promote(
            entry_id, dry_run=False, agent_id="nova", person_id="riley",
        )
        assert said.startswith(f"Hypomnema promoted: {entry_id}")

    promoted = {m["content"]: m for m in _memories(server)}
    own = promoted["[promoted from hypomnema; de-identified] The cue should ask, not tell."]
    assert (own["author_kind"], own["author_model"], own["impact"]) == (
        "agent", "claude-opus-5-5", "")
    shared = promoted[
        "[promoted from hypomnema; de-identified] Active project for this relationship: mnemos"]
    assert (shared["author_kind"], shared["author_model"], shared["impact"]) == ("unknown", "", "")
