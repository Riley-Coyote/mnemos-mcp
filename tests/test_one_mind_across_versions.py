"""One mind across versions: a model line is one mind.

After an upgrade from Opus 5.5 to Opus 6 the agent is still itself: its
beliefs, handoffs, questions and name are its own. A 1M-context session, a
provider's prefix or a dated snapshot is the same model. Another kind of model
(Sonnet, Haiku) is a colleague.
"""

import math
import random
import re
import struct
import time
from datetime import datetime, timedelta, timezone

import pytest

from mnemos.authorship import display_name, line_name, model_line, same_mind
from mnemos.core.belief import Belief
from mnemos.interface.context_packet import build_context_packet, reader_voice, resident_model
from mnemos.simple_runtime import MnemosRuntime


OPUS = "claude-opus-5-5"
OPUS_6 = "claude-opus-6"
OPUS_1M = "claude-opus-5-5[1m]"
OPUS_DATED = "claude-opus-5-5-20261001"
SONNET = "claude-sonnet-5-5"
SCOPE = {"agent_id": "nova", "person_id": "riley", "project_scope": "demo"}
NOTE = "Where I stopped: the harbour ledger balances. Next: the spring timetable."


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


def _idea_store(rt, monkeypatch, *, group_models=(OPUS, OPUS, OPUS)):
    """37 background impact lines and one idea returning three times, all the
    agent's own; the idea's lines are signed ``group_models`` in turn. Returns
    the idea's memory ids, oldest first."""
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
                            signed_as=group_models[index])
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
                     ((now - timedelta(days=9 - 3 * index, hours=2)).isoformat(), f"idea-{index}", target))
    # Every capture ran maintenance on a store too small to ask about.
    conn.execute("DELETE FROM meta WHERE key = ?", (rt._meta_key("ideas_noticed_at"),))
    rt._store._commit()
    monkeypatch.setattr(rt._embedding_index, "impact_vectors",
                        lambda impacts: {item: vectors[item] for item in impacts if item in vectors})
    return group


def _idea_asks(rt):
    return [dict(row) for row in rt._store._get_conn().execute(
        "SELECT * FROM reflection_queue WHERE kind = 'belief'").fetchall()]


def _idea_prompt(target):
    return ('On 3 different days you wrote something like this:\n'
            '- "The render is the honest judge." (October 1)\n'
            'Is there something you believe here? If there is, say it in one line with verdict hold; '
            f'if not, decline. Or leave it. [evidence:{target}]')


def _handoffs(rt, *models):
    """One handoff per model, each from a session of its own, oldest first."""
    for index, model in enumerate(models):
        rt._store.write_handoff(f"{NOTE} ({index})", **SCOPE, author_model=model,
                                author_session=f"{index + 1:08d}-aaaa-4aaa-8aaa-111111111111")


# ── Lines ──


@pytest.mark.parametrize("model, line", [
    ("claude-opus-5-5", "opus"),
    ("claude-opus-5-5[1m]", "opus"),
    ("anthropic/claude-opus-5-5", "opus"),
    ("us.anthropic.claude-opus-5-5-v1:0", "opus"),
    ("claude-opus-5-5-20260101", "opus"),
    ("CLAUDE-OPUS-5-5", "opus"),
    ("claude-opus-6", "opus"),
    ("claude-3-5-sonnet-20241022", "sonnet"),
    ("claude-haiku-4-5-20251001", "haiku"),
    ("claude-fable-5-1", "fable"),
    ("gpt-5", "gpt-5"),
    ("", ""),
    ("<synthetic>", ""),
])
def test_model_lines(model, line):
    assert model_line(model) == line
    assert same_mind("claude-opus-5-5", "claude-opus-6")
    assert not same_mind("claude-opus-5-5", "claude-sonnet-5-5")
    assert not same_mind("", "")


# ── Waking after an upgrade ──


def test_an_upgraded_opus_keeps_its_beliefs(runtime):
    runtime._store.save_belief(Belief(agent_id=SCOPE["agent_id"], content="The render is the honest judge.",
                                      confidence=0.8, author_model=OPUS))
    assert "The render is the honest judge." in _packet(runtime, reader_model=OPUS_6)["prompt"]
    assert "The render is the honest judge." not in _packet(runtime, reader_model=SONNET)["prompt"]


def test_an_upgraded_opus_is_home_not_visiting(runtime):
    _handoffs(runtime, OPUS, OPUS)
    assert resident_model(runtime._store, SCOPE) == OPUS

    opus = _packet(runtime, reader_model=OPUS_6)
    assert opus["voice"] == "self"
    assert "visiting" not in opus["prompt"], opus["prompt"]
    assert "### where i left off\n" in opus["prompt"], opus["prompt"]
    assert NOTE in opus["prompt"].split("### where i left off\n", 1)[1]

    sonnet = _packet(runtime, reader_model=SONNET)
    assert sonnet["voice"] == "guest"
    assert "visiting" in sonnet["prompt"], sonnet["prompt"]


def test_a_long_context_session_is_the_same_mind(runtime):
    _handoffs(runtime, OPUS, OPUS)
    runtime._store.save_belief(Belief(agent_id=SCOPE["agent_id"], content="The render is the honest judge.",
                                      confidence=0.8, author_model=OPUS))
    packet = _packet(runtime, reader_model=OPUS_1M)
    assert "The render is the honest judge." in packet["prompt"]
    assert "visiting" not in packet["prompt"], packet["prompt"]


def test_the_resident_is_named_by_its_newest_version(runtime):
    _handoffs(runtime, OPUS, OPUS, OPUS_6)
    assert resident_model(runtime._store, SCOPE) == OPUS_6


# ── Questions ──


def test_a_question_for_the_opus_line(runtime):
    target = _memory(runtime)
    runtime._store.enqueue_reflection("belief", target, _idea_prompt(target), **SCOPE, for_model="opus")
    assert len(_packet(runtime, reader_model=OPUS_6)["reflections"]) == 1
    assert not _packet(runtime, reader_model=SONNET)["reflections"]
    assert runtime.reflect(target, "The render judges.", verdict="hold", signed_as=SONNET) == (
        "This question is for Opus, not you. Nothing was changed."
    )
    assert runtime.reflect(target, "The render judges.", verdict="hold", signed_as=OPUS_6).startswith(
        "Belief recorded"
    )
    [belief] = runtime._store.get_beliefs(SCOPE["agent_id"], active_only=True)
    assert belief.author_model == OPUS_6


def test_the_noticer_counts_every_version_of_the_line(runtime, monkeypatch):
    _idea_store(runtime, monkeypatch, group_models=(OPUS, OPUS_1M, OPUS_6))
    runtime.maintain()
    [ask] = _idea_asks(runtime)
    assert ask["for_model"] == "opus"


# ── Names ──


def test_names_belong_to_a_line(runtime):
    runtime.introduce("claude-opus-5-5", "Nova")
    runtime.introduce("claude-opus-6")
    assert runtime._get_meta("agent_name", "") == "Nova"
    runtime.introduce("claude-sonnet-5-5")
    assert runtime._get_meta("agent_name", "") == ""

    runtime.introduce("grok 4", "Grok")
    runtime.introduce("gpt 5")
    assert runtime._get_meta("agent_name", "") == ""


# ── The reviewer's F1: the same model under another form of its id ──


def test_same_model_under_another_id_form_is_the_same_model():
    assert same_mind(OPUS, OPUS_1M)
    assert same_mind(OPUS, OPUS_DATED)


@pytest.mark.parametrize("reader", [OPUS_1M, OPUS_DATED])
def test_a_reader_wakes_with_its_own_belief_under_any_form_of_its_id(runtime, reader):
    runtime._store.save_belief(Belief(agent_id=SCOPE["agent_id"], content="The render is the honest judge.",
                                      confidence=0.8, author_model=OPUS))
    assert "The render is the honest judge." in _packet(runtime, reader_model=reader)["prompt"]


def test_opus_under_another_id_form_sees_and_answers_a_question_for_opus(runtime):
    target = _memory(runtime)
    runtime._store.enqueue_reflection("belief", target, _idea_prompt(target), **SCOPE, for_model="opus")
    assert len(runtime._store.pending_reflections(**SCOPE, reader_model=OPUS_1M)) == 1
    result = runtime.reflect(target, "The render judges.", verdict="hold", signed_as=OPUS_1M)
    assert result.startswith("Belief recorded"), result


def test_the_owner_under_another_id_form_keeps_its_own_belief(runtime):
    belief = Belief(agent_id=SCOPE["agent_id"], content="The render is the honest judge.",
                    confidence=0.4, author_model=OPUS_DATED)
    runtime._store.save_belief(belief)
    result = runtime.reflect(belief.id, "still true", verdict="hold", signed_as=OPUS)
    assert result.startswith("Kept."), result


def test_the_residents_own_lines_count_under_another_id_form(runtime, monkeypatch):
    _idea_store(runtime, monkeypatch, group_models=(OPUS_1M, OPUS_1M, OPUS_1M))
    runtime.maintain()
    assert len(_idea_asks(runtime)) == 1


# ── The second review ──


def _old_signed_belief(rt, target, model=OPUS):
    """A belief ``model`` formed 40 days ago, resting on ``target``: due to be
    put to its owner again."""
    belief = Belief(agent_id=SCOPE["agent_id"], content="The render is the honest judge.",
                    confidence=0.6, source="agent", supporting_engram_ids=[target], author_model=model)
    long_ago = (datetime.now(timezone.utc) - timedelta(days=40)).isoformat()
    belief.last_challenged = long_ago
    belief.created_at = long_ago
    rt._store.save_belief(belief)
    return belief


# F1, F5: every form of a Claude id is its line, and reads by its name.


@pytest.mark.parametrize("model, line", [
    ("US.ANTHROPIC.CLAUDE-OPUS-5-5-V1:0", "opus"),
    ("CLAUDE-OPUS-5-5-V1:0", "opus"),
    ("global.anthropic.claude-opus-4-5-20251101-v1:0", "opus"),
    ("apac.anthropic.claude-sonnet-4-20250514-v1:0", "sonnet"),
    ("us-gov.anthropic.claude-sonnet-4-5-20250929-v1:0", "sonnet"),
    ("claude-opus-4-1@20250805", "opus"),
    ("claude-3-7-sonnet-latest", "sonnet"),
    ("anthropic/claude-opus-4.5", "opus"),
])
def test_every_form_of_a_claude_id_is_its_line(model, line):
    assert model_line(model) == line


@pytest.mark.parametrize("model, name", [
    ("US.ANTHROPIC.CLAUDE-OPUS-5-5-V1:0", "Opus 5.5"),
    ("CLAUDE-OPUS-5-5-V1:0", "Opus 5.5"),
    ("global.anthropic.claude-opus-4-5-20251101-v1:0", "Opus 4.5"),
    ("apac.anthropic.claude-sonnet-4-20250514-v1:0", "Sonnet 4"),
    ("us-gov.anthropic.claude-sonnet-4-5-20250929-v1:0", "Sonnet 4.5"),
    ("claude-opus-4-1@20250805", "Opus 4.1"),
    ("claude-3-7-sonnet-latest", "Sonnet 3.7"),
    ("anthropic/claude-opus-4.5", "Opus 4.5"),
])
def test_every_form_of_a_claude_id_has_its_readable_name(model, name):
    assert display_name(model) == name


def test_opus_through_a_global_bedrock_profile_is_home_not_visiting(runtime):
    _handoffs(runtime, OPUS, OPUS)
    runtime._store.save_belief(Belief(agent_id=SCOPE["agent_id"], content="The render is the honest judge.",
                                      confidence=0.8, author_model=OPUS))
    packet = _packet(runtime, reader_model="global.anthropic.claude-opus-5-5-v1:0")
    assert packet["voice"] == "self", packet["prompt"]
    assert "The render is the honest judge." in packet["prompt"]


def test_opus_in_capitals_through_bedrock_answers_its_own_question(runtime):
    target = _memory(runtime)
    runtime._store.enqueue_reflection(
        "belief", target, f"Is there something you believe here? [evidence:{target}]",
        **SCOPE, for_model="opus",
    )
    result = runtime.reflect(target, "The render judges.", verdict="hold",
                             signed_as="US.ANTHROPIC.CLAUDE-OPUS-5-5-V1:0")
    assert result.startswith("Belief recorded"), result


def test_an_id_in_capitals_has_a_readable_name():
    assert same_mind("CLAUDE-OPUS-6", OPUS)
    assert display_name("CLAUDE-OPUS-6") == "Opus 6"


# F2: the quiet hour reads the queue as the hour's model.


def test_the_opus_hour_still_sees_reaffirmations_of_opus_beliefs(runtime):
    from mnemos import life

    target = _memory(runtime)
    _old_signed_belief(runtime, target, model=OPUS)
    assert runtime._enqueue_belief_reaffirmation(set()) == 1
    [ask] = [dict(r) for r in runtime._store._get_conn().execute(
        "SELECT kind, for_model FROM reflection_queue WHERE kind = 'reaffirm'").fetchall()]
    assert ask["for_model"] == "opus"
    assert model_line(life.HOUR_MODEL) == "opus"  # the hour is Opus: these are its own

    since = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    _, _, questions, _ = life._gather("mine", runtime.db_path, since, SCOPE)
    assert [q["kind"] for q in questions] == ["reaffirm"], questions


# F3: a guest sees only its own beliefs, as its own.


def test_a_guests_own_belief_is_not_headed_as_the_residents(runtime):
    _handoffs(runtime, OPUS, OPUS)
    runtime._store.save_belief(Belief(agent_id=SCOPE["agent_id"], content="Sonnet's own view of the ledger.",
                                      confidence=0.8, author_model=SONNET))
    runtime._store.save_belief(Belief(agent_id=SCOPE["agent_id"], content="The store's own view of the timetable.",
                                      confidence=0.8))
    prompt = _packet(runtime, reader_model=SONNET)["prompt"]
    assert "Sonnet's own view of the ledger." in prompt
    section = prompt.split("Sonnet's own view of the ledger.")[0].rsplit("###", 1)[1]
    assert section.startswith(" what i've come to see\n"), f"heading: ###{section}"
    assert "The store's own view of the timetable." not in prompt


# F4: a direct verdict closes the waiting question in every scope.


def test_a_direct_verdict_from_another_project_closes_the_waiting_question(runtime, tmp_path):
    target = _memory(runtime)
    belief = _old_signed_belief(runtime, target, model=OPUS)
    assert runtime._enqueue_belief_reaffirmation(set()) == 1

    other = MnemosRuntime(db_path=runtime.db_path, use_dedicated_model=False,
                          agent_id="nova", person_id="riley", project_scope="elsewhere")
    try:
        assert other.reflect(belief.id, "still true", verdict="hold", signed_as=OPUS_6).startswith("Kept.")
    finally:
        other.close()

    waiting = runtime._store.pending_reflections(**SCOPE, reader_model=OPUS_6)
    assert not [q for q in waiting if f"[belief:{belief.id}]" in q["prompt"]], waiting


# F6: batches of 32, none started after the deadline.


def test_impact_vectors_keeps_to_its_time_with_a_local_embedder(runtime, monkeypatch):
    from mnemos.store import embedding_index

    monkeypatch.setattr(embedding_index, "WRITE_EMBED_SECONDS", 0.2)
    calls = []

    class SlowLocal:
        model_name = "fake-model"
        dims = 4

        def embed(self, text):
            return [1.0, 0.0, 0.0, 0.0]

        def batch_embed(self, texts):
            calls.append(len(texts))
            time.sleep(0.15)
            return [[1.0, 0.0, 0.0, 0.0] for _ in texts]

    index = runtime._embedding_index
    index._available = True
    index._embedder = SlowLocal()
    index._init_table()
    started = time.monotonic()
    vectors = index.impact_vectors({f"line_{i}": f"lesson {i}" for i in range(100)})
    took = time.monotonic() - started
    assert len(calls) == 2, calls
    assert len(vectors) == 64
    assert took < 0.6, f"took {took:.2f}s"


# ── What the second review confirmed (guards) ──


def _write(rt, model, created_at, n=1):
    for i in range(n):
        entry = rt._store.write_hypomnema_entry(
            f"A note {model} {created_at} {i}", **SCOPE, source="observed", entry_kind="continuity",
            authored_by="agent", author_id="nova", author_model=model,
        )
        rt._store._get_conn().execute(
            "UPDATE hypomnema_entries SET created_at = ? WHERE id = ?", (created_at, entry))
    rt._store._commit()


@pytest.mark.parametrize("model, line", [
    ("gpt-5", "gpt-5"), ("GPT-5", "gpt-5"), ("gpt-4o", "gpt-4o"),
    ("grok 4", ""), ("<synthetic>", ""), ("", ""), ("   ", ""), (None, ""),
    ("claude-opus-5-5[1M]", "opus"),
    ("arn:aws:bedrock:us-east-1::foundation-model/anthropic.claude-opus-5-5-v1:0", "opus"),
])
def test_lines_of_odd_ids(model, line):
    assert model_line(model) == line


def test_two_unknown_ids_are_two_minds_and_no_id_is_no_one():
    assert not same_mind("gpt-5", "gpt-4o")
    assert same_mind("gpt-5", "GPT-5")
    assert not same_mind("", "")
    assert not same_mind("<synthetic>", "<synthetic>")
    assert not same_mind("grok 4", "grok 4")  # not an id at all
    assert line_name("opus") == "Opus" and line_name("gpt-5") == "gpt-5"


def test_voice_of_odd_readers():
    assert reader_voice("", OPUS) == "unknown"
    assert reader_voice("<synthetic>", OPUS) == "unknown"
    assert reader_voice("grok 4", OPUS) == "unknown"
    assert reader_voice("gpt-5", OPUS) == "guest"
    assert reader_voice("gpt-5", "") == "self"


def test_for_model_filter_with_odd_readers(runtime):
    target = _memory(runtime)
    runtime._store.enqueue_reflection("belief", target, f"q [evidence:{target}]", **SCOPE, for_model="opus")
    for reader in ("", "<synthetic>", "grok 4", "gpt-5"):
        assert runtime._store.pending_reflections(**SCOPE, reader_model=reader) == []
    assert len(runtime._store.pending_reflections(**SCOPE, reader_model="CLAUDE-OPUS-6")) == 1


def test_names_with_odd_ids(runtime):
    runtime.introduce("grok 4", "Grok")
    runtime.introduce("grok 4")
    assert runtime._get_meta("agent_name", "") == "Grok"   # same unknown giver keeps it
    runtime.introduce("GROK 4")
    assert runtime._get_meta("agent_name", "") == "Grok"   # case folded
    runtime.introduce("<synthetic>")
    assert runtime._get_meta("agent_name", "") == ""


def test_a_stored_full_id_still_names_its_line(runtime):
    runtime._set_meta("agent_name", "Nova")
    runtime._set_meta("agent_name_model", "claude-opus-5-5[1m]")  # as f1703e0 stored it
    runtime.introduce(OPUS_6)
    assert runtime._get_meta("agent_name", "") == "Nova"
    runtime.introduce(SONNET)
    assert runtime._get_meta("agent_name", "") == ""


def test_a_belief_signed_with_an_exact_id_belongs_to_its_line(runtime):
    runtime._store.save_belief(Belief(agent_id="nova", content="Held by 4.1 once.", confidence=0.8,
                                      author_model="claude-opus-4-1-20250805"))
    assert "Held by 4.1 once." in _packet(runtime, reader_model=OPUS_6)["prompt"]
    assert "Held by 4.1 once." not in _packet(runtime, reader_model=SONNET)["prompt"]


def test_a_question_addressed_to_an_exact_id_by_6f0654c(runtime):
    """What a store written by B's first commit does (no migration, by
    decision): its idea question names an exact id. No reader is shown it, no
    model can answer it, and while it waits the noticer asks nothing new; it
    expires after _IDEA_EXPIRES_DAYS (14)."""
    target = _memory(runtime)
    runtime._store.enqueue_reflection("belief", target, f"q [evidence:{target}]", **SCOPE,
                                      for_model=OPUS, expires_in_days=14)
    for reader in (OPUS, OPUS_6, SONNET, ""):
        assert runtime._store.pending_reflections(**SCOPE, reader_model=reader) == []
    assert _packet(runtime, reader_model=OPUS)["reflections"] == []
    assert runtime.reflect(target, "x", verdict="hold", signed_as=OPUS) == (
        "This question is for claude-opus-5-5, not you. Nothing was changed.")
    runtime._set_meta("ideas_noticed_at", "")
    assert runtime._enqueue_returning_idea() == 0
    assert runtime._get_meta("ideas_noticed_at", "") == ""  # returned at the open-question check


def test_resident_ties_and_forms(runtime):
    _write(runtime, OPUS, "2026-09-01T00:00:00+00:00", 2)
    _write(runtime, SONNET, "2026-09-02T00:00:00+00:00", 2)
    assert resident_model(runtime._store, SCOPE) == ""                  # two lines tie
    _write(runtime, "claude-opus-5-5[1m]", "2026-09-03T00:00:00+00:00", 1)
    assert resident_model(runtime._store, SCOPE) == "claude-opus-5-5[1m]"  # line wins, newest form
    _write(runtime, OPUS_6, "2026-09-03T00:00:00+00:00", 1)               # same moment, other form
    assert model_line(resident_model(runtime._store, SCOPE)) == "opus"


def test_unsigned_answers_are_refused_where_a_model_owns_the_question(runtime, monkeypatch):
    monkeypatch.delenv("MNEMOS_AGENT_MODEL", raising=False)
    monkeypatch.delenv("CLAUDE_CODE_SESSION_ID", raising=False)
    target = _memory(runtime)
    belief = _old_signed_belief(runtime, target)
    # queued, addressed
    assert runtime._enqueue_belief_reaffirmation(set()) == 1
    assert runtime.reflect(target, "x", verdict="hold").startswith("Nothing was changed: this question is for Opus")
    # queued, addressed to no one (as 6f0654c wrote reaffirmations), signed belief
    runtime._store._get_conn().execute("UPDATE reflection_queue SET for_model = ''")
    runtime._store._commit()
    assert runtime.reflect(target, "x", verdict="hold").startswith("Nothing was changed: this belief is Opus 5.5's")
    # direct
    assert runtime.reflect(belief.id, "x", verdict="retire").startswith("Nothing was changed: this belief is")
    assert runtime._store.get_belief(belief.id).confidence == pytest.approx(0.6)
    # a colleague, direct
    assert runtime.reflect(belief.id, "x", verdict="retire", signed_as=SONNET).endswith("Nothing was changed.")
    # a later version, direct, closes the waiting question in this scope
    assert runtime.reflect(belief.id, "x", verdict="hold", signed_as=OPUS_6).startswith("Kept.")
    assert runtime._store.pending_reflections(**SCOPE, reader_model=OPUS) == []


class _Embedder:
    model_name = "fake-model"
    dims = 4

    def __init__(self, batch):
        self._batch = batch

    def embed(self, text):
        return [0.0, 1.0, 0.0, 0.0]

    def batch_embed(self, texts):
        return self._batch(texts)


def _index(rt, batch):
    index = rt._embedding_index
    index._available = True
    index._embedder = _Embedder(batch)
    index._init_table()
    return index


def _store_lesson(index, item, text, blob, dims=4):
    from mnemos.store.embedding_index import LESSON_PART, PASSAGE_SCHEME, text_hash

    conn = index._get_conn()
    conn.execute(
        "INSERT INTO passage_vectors (item_id, model_name, part, text_hash, dims, embedding, scheme) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (item, "fake-model", LESSON_PART, text_hash(text), dims, blob, PASSAGE_SCHEME),
    )
    conn.commit()


def test_a_stored_zero_vector_is_embedded_again(runtime):
    index = _index(runtime, lambda texts: [[0.0, 1.0, 0.0, 0.0] for _ in texts])
    _store_lesson(index, "a", "lesson a", struct.pack("4f", 0, 0, 0, 0))
    _store_lesson(index, "b", "lesson b", struct.pack("4f", 1, 0, 0, 0))
    assert index.impact_vectors({"a": "lesson a", "b": "lesson b"}) == {
        "a": [0.0, 1.0, 0.0, 0.0], "b": [1.0, 0.0, 0.0, 0.0]}


def test_a_failing_batch_leaves_out_what_it_didnt_embed(runtime):
    def broken(texts):
        raise RuntimeError("down")
    index = _index(runtime, broken)
    _store_lesson(index, "b", "lesson b", struct.pack("4f", 1, 0, 0, 0))
    assert index.impact_vectors({"a": "lesson a", "b": "lesson b"}) == {"b": [1.0, 0.0, 0.0, 0.0]}


def test_none_nan_and_short_batches_are_left_out(runtime):
    index = _index(runtime, lambda texts: [None, [float("nan")] * 4, [1.0, 0, 0, 0]][: len(texts) - 1])
    assert index.impact_vectors({"a": "x", "b": "y", "c": "z"}) == {}
    index = _index(runtime, lambda texts: [None, [1.0, 0, 0, 0], [0, 0, 0, 0]])
    assert index.impact_vectors({"a": "x", "b": "y", "c": "z"}) == {"b": [1.0, 0.0, 0.0, 0.0]}


def test_the_instructions_fit_whole():
    from mnemos.mcp_server import ADVANCED_INSTRUCTIONS
    from mnemos.simple_mcp import SERVER_INSTRUCTIONS

    assert (len(SERVER_INSTRUCTIONS), len(ADVANCED_INSTRUCTIONS)) == (1891, 2047)
    assert ADVANCED_INSTRUCTIONS[:2048] == ADVANCED_INSTRUCTIONS
    assert "Your earlier versions are you" in ADVANCED_INSTRUCTIONS[:2048]
    assert ADVANCED_INSTRUCTIONS.endswith("administer memory.")
