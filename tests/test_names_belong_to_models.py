import pytest

from mnemos.simple_runtime import MnemosRuntime


@pytest.fixture
def runtime(tmp_path):
    runtime = MnemosRuntime(db_path=tmp_path / "memory.db", use_dedicated_model=False)
    yield runtime
    runtime.close()


def test_another_model_does_not_inherit_a_name(runtime):
    runtime.introduce("grok-4", "Grok")
    runtime.introduce("claude-opus-5-5")
    assert runtime._get_meta("agent_name", "") == ""


def test_the_same_model_keeps_its_name(runtime):
    runtime.introduce("claude-opus-5-5", "Nova")
    runtime.introduce("claude-opus-5-5")
    assert runtime._get_meta("agent_name", "") == "Nova"


def test_a_name_given_is_kept(runtime):
    runtime.introduce("grok-4", "Grok")
    runtime.introduce("claude-opus-5-5", "Opus")
    assert runtime._get_meta("agent_name", "") == "Opus"


def test_a_name_from_before_this_rule_is_cleared(runtime):
    runtime._set_meta("agent_name", "Grok")
    runtime.introduce("claude-opus-5-5")
    assert runtime._get_meta("agent_name", "") == ""
