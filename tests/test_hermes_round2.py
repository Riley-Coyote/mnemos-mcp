"""From ChatGPT's second review of the F1-F7 fixes (Nov 3, 2026), kept as
regressions. Written against cd31971.
"""

import os
from dataclasses import replace

import pytest

from mnemos.integrations.hermes import HermesMnemosConfig, MnemosMemoryProviderCore
from mnemos.simple_runtime import MnemosRuntime


@pytest.fixture(autouse=True)
def isolate(monkeypatch, tmp_path):
    for name in tuple(os.environ):
        if name.startswith("MNEMOS_") or name in {
            "ANTHROPIC_API_KEY", "OPENAI_API_KEY", "OPENROUTER_API_KEY",
            "GEMINI_API_KEY", "CLAUDE_CODE_SESSION_ID", "CLAUDE_CONFIG_DIR",
            "CLAUDE_PID", "CLAUDECODE", "AI_AGENT",
        }:
            monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("MNEMOS_DISABLE_DOTENV", "1")
    monkeypatch.setenv("MNEMOS_MAINTENANCE", "inline")
    monkeypatch.setenv("MNEMOS_JEV_KEY_FILE", os.devnull)
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)


@pytest.fixture
def provider(tmp_path):
    item = MnemosMemoryProviderCore(HermesMnemosConfig(
        db_path=str(tmp_path / "mnemos.db"), agent_id="review",
        person_id="fictional", project_scope="review",
        deep_maintenance=False, max_context_chars=10000,
    ))
    item.initialize("review-session", hermes_home=tmp_path)
    yield item
    item.shutdown()


def test_external_forget_during_recall_does_not_pin_stale_cache(provider, monkeypatch):
    token = "CEDARVAULT7741"
    provider.handle_tool_call("mnemos_capture", {
        "content": f"The studio door code is {token}.",
    })
    memory = provider._runtime._store.get_active_engrams(agent_id="review")[0]
    scope = provider.scope
    other = MnemosRuntime(
        db_path=scope.db_path, agent_id=scope.agent_id,
        person_id=scope.person_id, project_scope=scope.project_scope,
        use_dedicated_model=False,
    )
    other._ensure_init()
    recall = provider._runtime._recall_own
    calls = []
    revisions = []

    def recall_then_concurrent_forget(*args, **kwargs):
        text = recall(*args, **kwargs)
        calls.append(text)
        if len(calls) == 1:
            assert token in text
            revisions.append(provider._store_revision())
            # The first recall has selected/formatted old data. Another
            # process can now commit before prefetch samples its revision.
            result = other.correct("", target_id=memory.id, action="forget")
            assert "Archived" in result
            assert other._store.get_engram(memory.id).state == "archived"
            revisions.append(provider._store_revision())
        return text

    monkeypatch.setattr(provider._runtime, "_recall_own", recall_then_concurrent_forget)
    try:
        first = provider.prefetch("studio door code")
        assert token in first  # One in-flight read may return its older snapshot.
        second = provider.prefetch("studio door code")
        third = provider.prefetch("studio door code")
        fresh = recall("studio door code")
        print("EXTERNAL_FORGET_REVISIONS", revisions)
        print("PREFETCH_RECALL_CALLS", len(calls))
        print("TOKEN_IN_SECOND_THIRD_FRESH", token in second, token in third, token in fresh)
        assert token not in fresh, "the external forget must really remove normal recall"
        assert token not in second, (
            "prefetch tagged pre-forget output with post-forget data_version, "
            "so the next request still serves forgotten content"
        )
        assert token not in third
    finally:
        other.close()


@pytest.mark.parametrize("space", ["  ", "\n"], ids=["repeated-space", "newline"])
def test_legacy_replace_retires_literal_whitespace_match(provider, space):
    old_text = f"deploys{space}to Vercel"
    old_content = f"The billing service {old_text}."
    provider.on_memory_write("add", "memory", old_content, metadata={})
    store = provider._runtime._store
    old = store.get_active_engrams(agent_id="review")[0]
    provider.on_memory_write("replace", "memory", "The billing service deploys to Fly.io.",
                             metadata={"old_text": old_text})
    current = store.get_engram(old.id)
    print("LITERAL_WHITESPACE_PREDECESSOR", repr(old_text), current.state)
    print("ACTIVE_CONTENTS", [row.content for row in store.get_active_engrams(agent_id="review")])
    assert current.state == "archived", (
        "old_text literally names the sole mirrored predecessor, but only "
        "the candidate's whitespace was normalized before the substring test"
    )


@pytest.mark.parametrize("with_previous_content", [
    pytest.param(False, marks=pytest.mark.xfail(strict=True, reason=(
        "accepted limitation: with only old_text, a mirror that drifted out of "
        "sync with Hermes can match a stale entry; previous_content is exact"))),
    True,
], ids=["legacy", "full-entry"])
def test_diverged_mirror_does_not_reidentify_another_entry(provider, with_previous_content):
    """Residual compatibility limit, not a newly introduced regression.

    Native memory changes normally while mirroring is disabled. Its unique
    selector later refers to a different entry than the sole stale local
    substring match. Full previous_content makes the identities distinguishable.
    """
    native = {"billing": "The billing service deploys to Vercel."}
    provider.on_memory_write("add", "memory", native["billing"], metadata={})
    store = provider._runtime._store
    old_billing = store.get_active_engrams(agent_id="review")[0]

    provider._config = replace(provider._config, mirror_builtin_memory=False)
    native["billing"] = "The billing service deploys to Render."
    provider.on_memory_write("replace", "memory", native["billing"],
                             metadata={"old_text": "billing service"})
    native["image"] = "The image service deploys to Vercel."
    provider.on_memory_write("add", "memory", native["image"], metadata={})
    provider._config = replace(provider._config, mirror_builtin_memory=True)

    selector = "deploys to Vercel"
    assert [key for key, text in native.items() if selector in text] == ["image"]
    metadata = {"old_text": selector}
    if with_previous_content:
        metadata["previous_content"] = native["image"]
    native["image"] = "The image service deploys to Fly.io."
    provider.on_memory_write("replace", "memory", native["image"], metadata=metadata)
    state = store.get_engram(old_billing.id).state
    print("DIVERGED_MIRROR_BILLING_STATE", with_previous_content, state)
    assert state == "active", (
        "the image-service operation incorrectly used the stale billing "
        "entry as its predecessor; upstream uniqueness did not identify it"
    )
