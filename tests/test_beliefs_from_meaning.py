"""Signed beliefs, addressed questions, direct verdicts, and packet retention."""

import builtins
import math
import random
import re
import sqlite3
import struct
from datetime import datetime, timedelta, timezone

import pytest

from mnemos.code_version import MAINTENANCE_CODE_VERSION
from mnemos.core.belief import Belief
from mnemos.interface.context_packet import build_context_packet
from mnemos.simple_runtime import MnemosRuntime
from mnemos.store.sqlite_store import EngramStore


OPUS = "claude-opus-5-5"
SONNET = "claude-sonnet-5-5"
SCOPE = {"agent_id": "nova", "person_id": "riley", "project_scope": "demo"}


@pytest.fixture
def runtime(tmp_path):
    rt = MnemosRuntime(db_path=str(tmp_path / "memory.db"), use_dedicated_model=False, **SCOPE)
    rt._ensure_init()
    yield rt
    rt.close()


def _memory(rt):
    result = rt.capture("The rendered page showed the missing alignment.",
                        impact="The render is the honest judge.", signed_as=OPUS)
    return re.search(r"Memory ID: (engram_\w+)", result).group(1)


def _packet(rt, **kwargs):
    return build_context_packet(rt._store, **SCOPE, mark_surfaced=False, **kwargs)


def _unit(vector):
    norm = math.sqrt(sum(value * value for value in vector))
    return [value / norm for value in vector]


def _cosine(left, right):
    return sum(a * b for a, b in zip(left, right))


def _vectors(groups=1, size=3, background=37):
    """Fixed 384-dimensional unit vectors (seed 1004): idea groups of members
    close to one base each, and independent background vectors."""
    from mnemos.simple_runtime import _IDEA_FLOOR

    rng = random.Random(1004)
    ideas = []
    for _ in range(groups):
        base = _unit([rng.gauss(0.0, 1.0) for _ in range(384)])
        ideas.append([_unit([value + rng.gauss(0.0, 0.01) for value in base]) for _ in range(size)])
    spread = [_unit([rng.gauss(0.0, 1.0) for _ in range(384)]) for _ in range(background)]
    inside = min(_cosine(a, b) for group in ideas for i, a in enumerate(group) for b in group[i + 1:])
    everything = [vector for group in ideas for vector in group] + spread
    outside = max(_cosine(a, b) for a in spread for b in everything if b is not a)
    assert inside >= 0.9, f"the smallest cosine inside a group is {inside}"
    assert outside < inside, f"a background vector reaches {outside}, the group's smallest is {inside}"
    assert outside < _IDEA_FLOOR, f"a background vector reaches {outside}, the floor is {_IDEA_FLOOR}"
    return ideas, spread


def _idea_store(rt, monkeypatch, *, group_model=OPUS, one_session=False):
    """37 background impact lines and one idea returning three times, all the
    agent's own; returns the idea's memory ids, oldest first."""
    rt.handoff("I will judge the next alignment in the render.", signed_as=OPUS)
    rt.handoff("The rendered page is where I check the work.", signed_as=OPUS)
    ideas, spread = _vectors()
    vectors = {}
    background = []
    for index, vector in enumerate(spread):
        result = rt.capture(f"Background note {index}: Riley looked at item {index} of the list.",
                            impact=f"Item {index} of the list changed how I read entry {index}.", signed_as=OPUS)
        target = re.search(r"Memory ID: (engram_\w+)", result).group(1)
        vectors[target] = vector
        background.append(target)
    group = []
    for index, vector in enumerate(ideas[0]):
        result = rt.capture(f"Riley and I compared draft {index} with what the page rendered.",
                            impact=f"The render is the only honest judge, draft {index} showed it.",
                            signed_as=group_model)
        target = re.search(r"Memory ID: (engram_\w+)", result).group(1)
        vectors[target] = vector
        group.append(target)
    now = datetime.now(timezone.utc)
    conn = rt._store._get_conn()
    for index, target in enumerate(background):
        conn.execute("UPDATE engrams SET created_at = ?, author_session = ? WHERE id = ?",
                     ((now - timedelta(days=index + 1, hours=1)).isoformat(), f"background-{index}", target))
    for index, target in enumerate(group):
        conn.execute("UPDATE engrams SET created_at = ?, author_session = ? WHERE id = ?",
                     ((now - timedelta(days=9 - 3 * index, hours=2)).isoformat(),
                      "one-session" if one_session else f"idea-{index}", target))
    # Every capture ran maintenance on a store too small to ask about.
    conn.execute("DELETE FROM meta WHERE key = ?", (rt._meta_key("ideas_noticed_at"),))
    rt._store._commit()
    monkeypatch.setattr(rt._embedding_index, "impact_vectors",
                        lambda impacts: {item: vectors[item] for item in impacts if item in vectors})
    return group


def _idea_asks(rt):
    return [dict(row) for row in rt._store._get_conn().execute(
        "SELECT * FROM reflection_queue WHERE kind = 'belief'").fetchall()]


def _evidence(prompt):
    return re.search(r"\[evidence:([A-Za-z0-9_,]+)\]", prompt).group(1).split(",")


def test_an_idea_returning_on_three_days_is_asked_about_once(runtime, monkeypatch):
    group = _idea_store(runtime, monkeypatch)
    runtime.maintain()
    [ask] = _idea_asks(runtime)
    assert ask["prompt"].startswith("On 3 different days you wrote something like this:")
    assert _evidence(ask["prompt"]) == group
    assert ask["for_model"] == "opus"
    runtime.maintain()
    assert len(_idea_asks(runtime)) == 1


def test_three_mentions_in_one_session_are_not_an_idea(runtime, monkeypatch):
    _idea_store(runtime, monkeypatch, one_session=True)
    runtime.maintain()
    assert _idea_asks(runtime) == []


def test_another_models_lines_never_count(runtime, monkeypatch):
    _idea_store(runtime, monkeypatch, group_model=SONNET)
    runtime.maintain()
    assert _idea_asks(runtime) == []


def test_a_held_idea_becomes_a_signed_belief_with_its_evidence(runtime, monkeypatch):
    group = _idea_store(runtime, monkeypatch)
    runtime.maintain()
    [ask] = _idea_asks(runtime)
    runtime.reflect(ask["target_id"], "The render is the only honest judge.", verdict="hold", signed_as=OPUS)
    [belief] = [b for b in runtime._store.get_beliefs(SCOPE["agent_id"], active_only=True)
                if b.content == "The render is the only honest judge."]
    assert belief.author_model == OPUS
    assert belief.supporting_engram_ids == _evidence(ask["prompt"]) == group
    assert belief.domain == "idea"


def test_pure_python_matches_numpy(runtime, monkeypatch):
    pytest.importorskip("numpy")
    from mnemos.simple_runtime import _idea_similarities

    ideas, spread = _vectors()
    values = [vector for group in ideas for vector in group] + spread
    real_import = builtins.__import__

    def hide_numpy(name, *args, **kwargs):
        if name == "numpy" or name.startswith("numpy."):
            raise ImportError("numpy hidden")
        return real_import(name, *args, **kwargs)

    with_numpy = _idea_similarities(values)
    with monkeypatch.context() as hidden:
        hidden.setattr(builtins, "__import__", hide_numpy)
        without_numpy = _idea_similarities(values)
    assert abs(with_numpy[1] - without_numpy[1]) <= 1e-9
    assert abs(with_numpy[2] - without_numpy[2]) <= 1e-9
    for i in range(len(values)):
        for j in range(len(values)):
            assert abs(float(with_numpy[0][i][j]) - without_numpy[0][i][j]) <= 1e-9

    _idea_store(runtime, monkeypatch)

    def chosen():
        assert runtime._enqueue_returning_idea() == 1
        [ask] = _idea_asks(runtime)
        conn = runtime._store._get_conn()
        conn.execute("DELETE FROM reflection_queue WHERE id = ?", (ask["id"],))
        conn.execute("DELETE FROM meta WHERE key = ?", (runtime._meta_key("ideas_noticed_at"),))
        runtime._store._commit()
        return _evidence(ask["prompt"])

    numpy_group = chosen()
    monkeypatch.setattr(builtins, "__import__", hide_numpy)
    assert chosen() == numpy_group


def test_older_code_keeps_no_belief_directly(runtime):
    belief = Belief(agent_id=SCOPE["agent_id"], content="The render is the honest judge.", confidence=0.4)
    runtime._store.save_belief(belief)
    runtime._store.raise_min_code_version(MAINTENANCE_CODE_VERSION + 1)
    result = runtime.reflect(belief.id, "still true", verdict="hold", signed_as=OPUS)
    assert result.startswith(
        "Nothing was changed: this code is older than the memory, so it doesn't keep or retire beliefs."
    )
    held = runtime._store.get_belief(belief.id)
    assert held.confidence == 0.4
    assert held.author_model == ""


def test_too_few_memories_ask_nothing(runtime):
    runtime.handoff("I will judge the next alignment in the render.", signed_as=OPUS)
    runtime.handoff("The rendered page is where I check the work.", signed_as=OPUS)
    for index in range(20):
        result = runtime.capture(f"Riley inspected layout number {index} in the rendered page.",
                                 impact=f"The render showed alignment number {index}.", signed_as=OPUS)
        target = re.search(r"Memory ID: (engram_\w+)", result).group(1)
        runtime._store._get_conn().execute(
            "UPDATE engrams SET author_session = ? WHERE id = ?", (f"session-{index}", target),
        )
        runtime._store._commit()
    runtime.maintain()
    assert not runtime._store._get_conn().execute(
        "SELECT id FROM reflection_queue WHERE kind = 'belief'",
    ).fetchall()
    assert runtime._get_meta("ideas_noticed_at", "")


def test_the_packet_shows_a_reader_its_own_beliefs_only(runtime):
    for model, content in ((OPUS, "The render is the honest judge."),
                           (SONNET, "Read the evidence before deciding."),
                           ("", "Keep promises to the person.")):
        runtime._store.save_belief(Belief(agent_id=SCOPE["agent_id"], content=content,
                                        confidence=0.8, author_model=model))
    opus = _packet(runtime, reader_model=OPUS)["prompt"]
    sonnet = _packet(runtime, reader_model=SONNET)["prompt"]
    assert "The render is the honest judge." in opus
    assert "Keep promises to the person." in opus
    assert "Read the evidence before deciding." not in opus
    assert "Read the evidence before deciding." in sonnet
    assert "Keep promises to the person." in sonnet
    assert "The render is the honest judge." not in sonnet


def test_a_question_for_one_model_is_not_shown_to_another(runtime):
    target = _memory(runtime)
    prompt = ('On 3 different days you wrote something like this:\n- "The render is the honest judge." (October 1)\n'
              '- "The render is the honest judge." (October 2)\n'
              '- "The render is the honest judge." (October 3)\n'
              'Is there something you believe here? If there is, say it in one line with verdict hold; '
              f'if not, decline. Or leave it. [evidence:{target}]')
    runtime._store.enqueue_reflection("belief", target, prompt, **SCOPE, for_model="opus")
    sonnet = _packet(runtime, reader_model=SONNET)
    opus = _packet(runtime, reader_model=OPUS)
    assert not sonnet["reflections"]
    assert len(opus["reflections"]) == 1
    assert "On 3 different days you wrote something like this:" in opus["prompt"]
    assert 'about "' not in opus["prompt"]
    assert "[evidence:" not in opus["prompt"]


def test_a_question_for_one_model_is_not_answered_by_another(runtime):
    target = _memory(runtime)
    prompt = ('On 3 different days you wrote something like this:\n- "The render is the honest judge." (October 1)\n'
              'Is there something you believe here? If there is, say it in one line with verdict hold; '
              f'if not, decline. Or leave it. [evidence:{target}]')
    ask = runtime._store.enqueue_reflection("belief", target, prompt, **SCOPE, for_model="opus")
    conn = runtime._store._get_conn()
    result = runtime.reflect(target, "The render judges.", verdict="hold", signed_as=SONNET)
    assert result == "This question is for Opus, not you. Nothing was changed."
    assert conn.execute("SELECT answered_at FROM reflection_queue WHERE id = ?", (ask,)).fetchone()[0] is None
    assert runtime._store.get_beliefs(SCOPE["agent_id"], active_only=True) == []
    runtime.reflect(target, "The render judges.", verdict="hold", signed_as=OPUS)
    [belief] = runtime._store.get_beliefs(SCOPE["agent_id"], active_only=True)
    assert belief.author_model == OPUS


def test_only_the_owner_keeps_or_retires(runtime):
    target = _memory(runtime)
    belief = Belief(agent_id=SCOPE["agent_id"], content="Read the evidence before deciding.",
                    confidence=0.4, author_model=SONNET, supporting_engram_ids=[target])
    runtime._store.save_belief(belief)
    ask = runtime._store.enqueue_reflection("reaffirm", target,
                                           f'You hold this belief. [belief:{belief.id}]', **SCOPE)
    before = runtime._store.get_belief(belief.id).to_dict()
    conn = runtime._store._get_conn()
    before_ask = dict(conn.execute("SELECT * FROM reflection_queue WHERE id = ?", (ask,)).fetchone())
    result = runtime.reflect(target, "no longer", verdict="retire", signed_as=OPUS)
    assert result == "This belief is Sonnet 5.5's to keep or retire, not yours. Nothing was changed."
    assert runtime._store.get_belief(belief.id).to_dict() == before
    assert dict(conn.execute("SELECT * FROM reflection_queue WHERE id = ?", (ask,)).fetchone()) == before_ask


def test_holding_an_unsigned_belief_adopts_it(runtime, monkeypatch):
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "11111111-aaaa-4aaa-8aaa-111111111111")
    belief = Belief(agent_id=SCOPE["agent_id"], content="The render is the honest judge.", confidence=0.4)
    runtime._store.save_belief(belief)
    runtime.reflect(belief.id, "still true", verdict="hold", signed_as=OPUS)
    held = runtime._store.get_belief(belief.id)
    assert held.confidence == 0.45
    assert held.author_model == OPUS
    assert held.author_session == "11111111-aaaa-4aaa-8aaa-111111111111"
    assert runtime._store._get_conn().execute("SELECT COUNT(*) FROM reflection_queue").fetchone()[0] == 0


def test_a_belief_can_be_retired_directly(runtime):
    belief = Belief(agent_id=SCOPE["agent_id"], content="The render is the honest judge.", confidence=0.8)
    runtime._store.save_belief(belief)
    assert belief.content in _packet(runtime, reader_model=OPUS)["prompt"]
    runtime.reflect(belief.id, "no longer", verdict="retire", signed_as=OPUS)
    assert runtime._store.get_belief(belief.id).confidence == 0
    assert belief.content not in _packet(runtime, reader_model=OPUS)["prompt"]
    assert runtime._store._get_conn().execute("SELECT COUNT(*) FROM reflection_queue").fetchone()[0] == 0


def test_direct_verdict_needs_hold_or_retire(runtime):
    belief = Belief(agent_id=SCOPE["agent_id"], content="The render is the honest judge.")
    runtime._store.save_belief(belief)
    before = runtime._store.get_belief(belief.id).to_dict()
    assert runtime.reflect(belief.id, "still true", verdict="", signed_as=OPUS) == (
        "Nothing recorded: to keep or retire a belief directly, give verdict hold or retire."
    )
    assert runtime._store.get_belief(belief.id).to_dict() == before


def test_older_stores_gain_the_new_columns(runtime):
    target = _memory(runtime)
    belief = Belief(agent_id=SCOPE["agent_id"], content="The render is the honest judge.")
    runtime._store.save_belief(belief)
    ask = runtime._store.enqueue_reflection("belief", target, "Is there something you believe here?", **SCOPE)
    db_path = runtime.scope.db_path
    runtime.close()
    conn = sqlite3.connect(str(db_path))
    for table, removed in (("beliefs", {"author_model", "author_session"}),
                           ("reflection_queue", {"for_model"})):
        sql = conn.execute("SELECT sql FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)).fetchone()[0]
        columns = [row[1] for row in conn.execute(f"PRAGMA table_info({table})") if row[1] not in removed]
        for name in removed:
            sql = re.sub(r",\s*" + name + r" TEXT NOT NULL DEFAULT ''", "", sql)
        conn.execute(f"ALTER TABLE {table} RENAME TO {table}_v17")
        conn.execute(sql)
        names = ", ".join(columns)
        conn.execute(f"INSERT INTO {table} ({names}) SELECT {names} FROM {table}_v17")
        conn.execute(f"DROP TABLE {table}_v17")
    conn.execute("UPDATE meta SET value = '16' WHERE key = 'schema_version'")
    conn.commit()
    conn.close()
    store = EngramStore(str(db_path))
    try:
        held = store.get_belief(belief.id)
        assert held.author_model == ""
        assert held.author_session == ""
        row = store._get_conn().execute("SELECT for_model FROM reflection_queue WHERE id = ?", (ask,)).fetchone()
        assert row["for_model"] == ""
        assert store._get_conn().execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone()[0] == "18"
    finally:
        store.close()


def test_light_wake_has_no_foundational_notes(runtime):
    runtime._store.write_hypomnema_entry("Judge the layout in the render.", **SCOPE,
                                        foundational=True, confidence=0.9, salience=0.9)
    assert "also:" not in _packet(runtime, wake="light")["prompt"]
    assert "Judge the layout in the render." not in _packet(runtime, wake="light")["prompt"]


def test_the_journal_line_stays_when_room_is_short(runtime):
    runtime.handoff("Riley and I inspected the rendered page. The remaining work is to compare the spacing in the header, verify the mobile layout, and read the next render before accepting the alignment changes.", signed_as=OPUS)
    runtime.journal("I returned to the render and saw what needed to change.", signed_as=OPUS)
    for day in range(1, 5):
        runtime._store.write_hypomnema_entry(
            f"On October {day}, Riley inspected the rendered page and found the missing alignment.",
            **SCOPE, confidence=0.8, salience=0.8,
        )
    short = _packet(runtime, token_budget=200)
    assert "I returned to the render and saw what needed to change." in short["prompt"]


# ── What the review found ──


def _idea_prompt(target):
    return ('On 3 different days you wrote something like this:\n'
            '- "The render is the honest judge." (October 1)\n'
            'Is there something you believe here? If there is, say it in one line with verdict hold; '
            f'if not, decline. Or leave it. [evidence:{target}]')


def test_an_idea_question_on_a_memory_with_an_older_open_question_can_be_answered(runtime, monkeypatch):
    group = _idea_store(runtime, monkeypatch)
    newest = group[-1]
    runtime._store.enqueue_reflection(
        "lesson", newest, "This is fading. What did it teach you? The lesson outlives the details.",
        **SCOPE,
    )
    runtime.maintain()
    [idea] = [ask for ask in _idea_asks(runtime) if "[evidence:" in ask["prompt"]]
    # One question per memory: the newest already has one, so the next is asked.
    assert idea["target_id"] == group[-2]
    result = runtime.reflect(idea["target_id"], "The render is the only honest judge.",
                             verdict="hold", signed_as=OPUS)
    assert result.startswith("Belief recorded"), result


def test_an_unsigned_answer_does_not_take_a_question_addressed_to_opus(runtime):
    assert runtime.author_model("") == ""
    target = _memory(runtime)
    runtime._store.enqueue_reflection("belief", target, _idea_prompt(target), **SCOPE, for_model="opus")
    result = runtime.reflect(target, "The render judges.", verdict="hold")
    assert result == (
        "Nothing was changed: this question is for Opus, and your answer isn't signed. "
        "Pass signed_as with your exact model id."
    )
    assert runtime._store.get_beliefs(SCOPE["agent_id"], active_only=True) == []


def test_an_unsigned_answer_does_not_retire_a_signed_belief(runtime):
    assert runtime.author_model("") == ""
    belief = Belief(agent_id=SCOPE["agent_id"], content="Read the evidence before deciding.",
                    confidence=0.6, author_model=SONNET)
    runtime._store.save_belief(belief)
    result = runtime.reflect(belief.id, "no longer", verdict="retire")
    assert result == (
        "Nothing was changed: this belief is Sonnet 5.5's, and your answer isn't signed. "
        "Pass signed_as with your exact model id."
    )
    assert runtime._store.get_belief(belief.id).confidence == 0.6


def _drop_to_v16(db_path):
    conn = sqlite3.connect(str(db_path))
    for table, removed in (("beliefs", {"author_model", "author_session"}),
                           ("reflection_queue", {"for_model"})):
        sql = conn.execute("SELECT sql FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)).fetchone()[0]
        columns = [row[1] for row in conn.execute(f"PRAGMA table_info({table})") if row[1] not in removed]
        for name in removed:
            sql = re.sub(r",\s*" + name + r" TEXT NOT NULL DEFAULT ''", "", sql)
        conn.execute(f"ALTER TABLE {table} RENAME TO {table}_v17")
        conn.execute(sql)
        names = ", ".join(columns)
        conn.execute(f"INSERT INTO {table} ({names}) SELECT {names} FROM {table}_v17")
        conn.execute(f"DROP TABLE {table}_v17")
    conn.execute("UPDATE meta SET value = '16' WHERE key = 'schema_version'")
    conn.commit()
    conn.close()


def test_two_openers_upgrading_one_v16_store_both_open(tmp_path):
    """Opener A reads the columns, opener B (a hook, say) opens and migrates
    the store, then A adds what it read as missing."""
    db = tmp_path / "memory.db"
    EngramStore(str(db)).close()
    _drop_to_v16(db)

    class Interleaved:
        def __init__(self, conn):
            self.conn, self.done = conn, False

        def execute(self, sql, *args):
            if sql.startswith("ALTER TABLE") and not self.done:
                self.done = True
                EngramStore(str(db)).close()  # B opens between A's read and A's ALTER
            return self.conn.execute(sql, *args)

    conn = sqlite3.connect(str(db))
    try:
        EngramStore._reconcile_columns(Interleaved(conn))
    finally:
        conn.close()


def test_a_direct_decline_does_not_claim_words_kept_on_a_question(runtime):
    belief = Belief(agent_id=SCOPE["agent_id"], content="The render is the honest judge.", confidence=0.5)
    runtime._store.save_belief(belief)
    result = runtime.reflect(belief.id, "I'd rather not say", verdict="decline", signed_as=OPUS)
    rows = runtime._store._get_conn().execute("SELECT COUNT(*) FROM reflection_queue").fetchone()[0]
    assert rows == 0
    assert result == "Left as it is. The belief is unchanged."


def test_another_models_belief_is_not_put_to_a_reader_as_its_own(runtime):
    target = _memory(runtime)
    belief = Belief(agent_id=SCOPE["agent_id"], content="Read the evidence before deciding.", confidence=0.6,
                    source="agent", supporting_engram_ids=[target], author_model=OPUS)
    belief.last_challenged = (datetime.now(timezone.utc) - timedelta(days=40)).isoformat()
    runtime._store.save_belief(belief)
    runtime.maintain()
    [ask] = [dict(r) for r in runtime._store._get_conn().execute(
        "SELECT * FROM reflection_queue WHERE kind = 'reaffirm'").fetchall()]
    sonnet = _packet(runtime, reader_model=SONNET)
    assert "Read the evidence before deciding." not in sonnet["prompt"], (
        f"for_model={ask['for_model']!r}; Sonnet's packet shows: "
        + sonnet["prompt"][sonnet["prompt"].find("You hold"):][:120])


def test_a_noticer_failure_is_noted_and_maintenance_finishes(runtime, monkeypatch):
    _idea_store(runtime, monkeypatch)

    def broken(impacts):
        raise struct.error("unpack requires a buffer of 16 bytes")

    monkeypatch.setattr(runtime._embedding_index, "impact_vectors", broken)
    said = runtime.maintain()
    assert "Completed: local deterministic maintenance completed" in said, said
    assert runtime._get_meta("ideas_noticed_at", ""), "the failure was not noted, so it is retried every cycle"


# ── Answers the review's questions asked for ──


def test_a_packet_without_a_reader_shows_the_residents_questions(runtime):
    runtime.handoff("I will judge the next alignment in the render.", signed_as=OPUS)
    target = _memory(runtime)
    runtime._store.enqueue_reflection("belief", target, _idea_prompt(target), **SCOPE, for_model="opus")
    assert len(_packet(runtime)["reflections"]) == 1


def test_an_evidence_question_that_can_no_longer_be_shown_does_not_block(runtime, monkeypatch):
    group = _idea_store(runtime, monkeypatch)
    background = runtime._store._get_conn().execute(
        "SELECT id FROM engrams WHERE id NOT IN (?, ?, ?) AND impact != '' LIMIT 1", group,
    ).fetchone()[0]
    runtime._store.enqueue_reflection("belief", background, _idea_prompt(background), **SCOPE, for_model="opus")
    runtime._store._get_conn().execute(
        "UPDATE reflection_queue SET surfaced_count = ? WHERE target_id = ?",
        (EngramStore.MAX_SURFACINGS, background),
    )
    runtime._store._commit()
    assert runtime._enqueue_returning_idea() == 1


def test_a_direct_verdict_answers_the_question_waiting_on_its_belief(runtime):
    target = _memory(runtime)
    belief = Belief(agent_id=SCOPE["agent_id"], content="The render is the honest judge.", confidence=0.5,
                    source="agent", supporting_engram_ids=[target], author_model=OPUS)
    runtime._store.save_belief(belief)
    ask = runtime._store.enqueue_reflection(
        "reaffirm", target, f'You hold this belief: "{belief.content}". Still true? [belief:{belief.id}]',
        **SCOPE, for_model="opus",
    )
    assert runtime.reflect(belief.id, "still true", verdict="hold", signed_as=OPUS).startswith("Kept.")
    answered = runtime._store._get_conn().execute(
        "SELECT answered_at, answer FROM reflection_queue WHERE id = ?", (ask,),
    ).fetchone()
    assert answered["answered_at"] is not None
    assert answered["answer"] == "still true"


class _FakeEmbedder:
    model_name = "fake-model"
    dims = 4

    def embed(self, text):
        return [1.0, 0.0, 0.0, 0.0]

    def batch_embed(self, texts):
        return [self.embed(text) for text in texts]


def _live_index(rt, embedder=None):
    index = rt._embedding_index
    index._available = True
    index._embedder = embedder or _FakeEmbedder()
    index._init_table()
    return index


def test_a_stored_lesson_vector_of_the_wrong_shape_counts_as_missing(runtime):
    from mnemos.store.embedding_index import LESSON_PART, PASSAGE_SCHEME, text_hash

    index = _live_index(runtime)
    conn = index._get_conn()
    conn.execute(
        "INSERT INTO passage_vectors (item_id, model_name, part, text_hash, dims, embedding, scheme) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("engram_x", "fake-model", LESSON_PART, text_hash("The render judges."), 4,
         struct.pack("2f", 1.0, 0.0), PASSAGE_SCHEME),
    )
    conn.commit()
    assert index.impact_vectors({"engram_x": "The render judges."}) == {"engram_x": [1.0, 0.0, 0.0, 0.0]}


def test_the_noticer_embeds_in_batches_within_the_write_paths_time(runtime, monkeypatch):
    """capture() runs maintenance as it writes: the lines no lesson passage
    holds yet are embedded in batches of 32, not one call each."""
    import time

    from mnemos.store.embedding_index import WRITE_EMBED_SECONDS, EmbeddingIndex

    _idea_store(runtime, monkeypatch)
    index = runtime._embedding_index
    monkeypatch.setattr(index, "impact_vectors", EmbeddingIndex.impact_vectors.__get__(index))
    calls = []

    class Slow(_FakeEmbedder):
        def batch_embed(self, texts):
            calls.append(len(texts))
            time.sleep(0.1)
            return [[1.0, 0.0, 0.0, 0.0] for _ in texts]

        def embed(self, text):
            time.sleep(0.1)
            return [1.0, 0.0, 0.0, 0.0]

    _live_index(runtime, Slow())
    runtime._set_meta("ideas_noticed_at", "")
    started = time.perf_counter()
    runtime._enqueue_returning_idea()
    assert time.perf_counter() - started <= WRITE_EMBED_SECONDS + 1
    assert calls == [32, 8]
