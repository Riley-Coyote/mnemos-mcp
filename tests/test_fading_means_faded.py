import pytest

from mnemos.consolidation.softening import run_softening_pass
from mnemos.simple_runtime import MnemosRuntime


CONTENT = "Riley plans every trip around the ferry timetable."
IMPACT = "The ferry decides every trip."


@pytest.fixture
def runtime(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    runtime = MnemosRuntime(db_path=tmp_path / "memory.db", use_dedicated_model=False, agent_id="demo")
    yield runtime
    runtime.close()


def _capture(runtime, impact=""):
    runtime.capture(content=CONTENT, impact=impact)
    return runtime._store.get_active_engrams(agent_id="demo", limit=1)[0].id


def _age(runtime, engram_id, accessibility):
    runtime._store._get_conn().execute(
        "UPDATE engrams SET created_at = ?, last_accessed = ?, accessibility = ?, resolution = 1.0 WHERE id = ?",
        ("2026-01-01T00:00:00+00:00", "2026-01-01T00:00:00+00:00", accessibility, engram_id),
    )
    runtime._store._commit()


def _pass(runtime):
    return run_softening_pass(
        runtime._store, {}, None, agent_id="demo",
        person_id=runtime.scope.person_id, project_scope=runtime.scope.project_scope,
    )


def _lessons(runtime):
    return [engram for engram in runtime._store.get_active_engrams(agent_id="demo") if "lesson" in engram.tags]


def test_a_memory_still_in_reach_draws_no_lesson(runtime):
    target = _capture(runtime, IMPACT)
    _age(runtime, target, 0.5)
    stats = _pass(runtime)
    assert _lessons(runtime) == []
    assert stats["not_faded"] == 1


def test_a_faded_memory_draws_its_lesson(runtime):
    target = _capture(runtime, IMPACT)
    _age(runtime, target, 0.1)
    _pass(runtime)
    lessons = _lessons(runtime)
    assert len(lessons) == 1
    assert lessons[0].content == IMPACT
    source = runtime._store.get_engram(target)
    assert any(connection.target_id == lessons[0].id and connection.relation == "distilled_into" for connection in source.connections)


def test_a_faded_memory_without_a_meaning_is_asked_what_it_taught(runtime):
    target = _capture(runtime)
    _age(runtime, target, 0.1)
    stats = _pass(runtime)
    runtime._enqueue_lesson_reflections(stats)
    questions = [item for item in runtime.pending_reflections(limit=10) if item["kind"] == "lesson"]
    assert len(questions) == 1
    assert questions[0]["target_id"] == target


def test_a_memory_in_reach_is_not_asked_what_it_taught(runtime):
    target = _capture(runtime)
    _age(runtime, target, 0.5)
    stats = _pass(runtime)
    runtime._enqueue_lesson_reflections(stats)
    assert not [item for item in runtime.pending_reflections(limit=10) if item["kind"] == "lesson"]


def _blur_then_fade(runtime, impact):
    """A memory blurred step by step while it was still in reach (with a model,
    or soften_without_model), then faded below the threshold."""
    target = _capture(runtime, impact)
    _age(runtime, target, 0.16)
    run_softening_pass(
        runtime._store, {"soften_without_model": True}, None, agent_id="demo",
        person_id=runtime.scope.person_id, project_scope=runtime.scope.project_scope,
    )
    blurred = runtime._store.get_engram(target)
    assert blurred.resolution < 1.0 and _lessons(runtime) == []
    runtime._store._get_conn().execute(
        "UPDATE engrams SET accessibility = 0.10 WHERE id = ?", (target,),
    )
    runtime._store._commit()
    stats = run_softening_pass(
        runtime._store, {"soften_without_model": True}, None, agent_id="demo",
        person_id=runtime.scope.person_id, project_scope=runtime.scope.project_scope,
    )
    return target, stats


def test_a_memory_blurred_before_it_faded_still_draws_its_lesson(runtime):
    target, _ = _blur_then_fade(runtime, IMPACT)
    lessons = _lessons(runtime)
    assert len(lessons) == 1 and lessons[0].content == IMPACT
    source = runtime._store.get_engram(target)
    assert any(c.target_id == lessons[0].id and c.relation == "distilled_into" for c in source.connections)


def test_a_memory_blurred_before_it_faded_is_still_asked_what_it_taught(runtime):
    target, stats = _blur_then_fade(runtime, "")
    runtime._enqueue_lesson_reflections(stats)
    asked = [item for item in runtime.pending_reflections(limit=10) if item["kind"] == "lesson"]
    assert [item["target_id"] for item in asked] == [target]


def test_a_memory_that_taught_is_left_as_it_is(runtime):
    target = _capture(runtime, IMPACT)
    _age(runtime, target, 0.1)
    _pass(runtime)
    _pass(runtime)
    assert len(_lessons(runtime)) == 1
    links = runtime._store._get_conn().execute(
        "SELECT COUNT(*) FROM connections WHERE source_id = ? AND relation = 'distilled_into'", (target,),
    ).fetchone()[0]
    assert links == 1


def test_a_misfiled_link_does_not_stand_in_for_the_memorys_own_lesson(runtime):
    """A legacy store can hold a distilled_into link to an unrelated lesson
    (repair-lessons finds them). It must not count as the memory having
    taught: the memory's own impact is still drawn into its lesson."""
    from mnemos.consolidation.softening import _create_or_reinforce_lesson
    from mnemos.core.types import ConnectionRelation

    def by_content(start):
        return next(e.id for e in runtime._store.get_active_engrams(agent_id="demo", limit=50)
                    if e.content.startswith(start))

    runtime.capture(content="Brass lamps on the jetty are polished each Sunday.",
                    impact="Small rituals keep a harbour cared for.")
    unrelated = _create_or_reinforce_lesson(
        runtime._store.get_engram(by_content("Brass lamps")), runtime._store, {},
    )
    assert unrelated is not None
    runtime.capture(content=CONTENT, impact=IMPACT)
    target = by_content(CONTENT)
    source = runtime._store.get_engram(target)
    source.add_connection(target_id=unrelated, relation=ConnectionRelation.DISTILLED_INTO,
                          strength=0.8, formed_by="consolidation")
    runtime._store.save_engram(source)
    _age(runtime, target, 0.1)
    _pass(runtime)
    own = [lesson for lesson in _lessons(runtime) if lesson.content == IMPACT]
    assert len(own) == 1
    source = runtime._store.get_engram(target)
    assert any(c.target_id == own[0].id and c.relation == "distilled_into" for c in source.connections)
