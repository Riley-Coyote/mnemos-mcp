from mnemos.simple_runtime import MnemosRuntime


_VEKTOR_NOTES = [
    "vektor render queue stalled overnight",
    "vektor shader cache rebuilt following a crash",
    "vektor timeline scrubbing feels sluggish",
    "vektor export finally matches preview",
    "vektor audio drifted during playback",
    "vektor autosave corrupted twice",
    "vektor installer signed properly",
    "vektor plugin loading improved",
]


def test_a_recurring_word_is_never_asked_about(tmp_path):
    runtime = MnemosRuntime(db_path=tmp_path / "memory.db", agent_id="t", person_id="p", project_scope="g")
    try:
        for note in _VEKTOR_NOTES:
            runtime.capture(content=note)
        for _ in range(3):
            runtime.maintain()
        assert runtime._store._get_conn().execute(
            "SELECT COUNT(*) FROM reflection_queue WHERE kind = 'belief'"
        ).fetchone()[0] == 0
    finally:
        runtime.close()
