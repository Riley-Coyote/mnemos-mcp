"""From ChatGPT's independent review of the F1-F7 fixes (Nov 2, 2026), kept as
regressions. Each was written against a10c83f, where some failed.
"""
"""Independent adversarial review probes; no Mnemos source modifications."""
import json
import pytest

from mnemos.integrations.hermes import HermesMnemosConfig, MnemosMemoryProviderCore
from mnemos.encoding.encoder import Encoder
from mnemos.encoding.llm_classifier import ConnectionClassification, ConnectionVerdicts
from mnemos.store.sqlite_store import EngramStore
from mnemos.core.engram import Connection
from mnemos.core.types import ConnectionRelation


@pytest.fixture(autouse=True)
def isolation(monkeypatch, tmp_path):
    monkeypatch.setenv("MNEMOS_DISABLE_DOTENV", "1")
    monkeypatch.setenv("MNEMOS_MAINTENANCE", "inline")
    monkeypatch.setenv("MNEMOS_JEV_KEY_FILE", "/dev/null")
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    for key in ("MNEMOS_LLM_PROVIDER", "MNEMOS_MODEL", "MNEMOS_AGENT_MODEL",
                "MNEMOS_DB_PATH", "MNEMOS_AGENT_ID", "MNEMOS_PERSON_ID",
                "MNEMOS_PROJECT_SCOPE", "MNEMOS_EMBEDDING_MODEL",
                "MNEMOS_EMBEDDING_PROVIDER", "CLAUDE_CODE_SESSION_ID",
                "CLAUDE_CONFIG_DIR", "CLAUDECODE", "AI_AGENT"):
        monkeypatch.delenv(key, raising=False)


@pytest.fixture
def provider(tmp_path):
    instance = MnemosMemoryProviderCore(HermesMnemosConfig(
        db_path=str(tmp_path / "mnemos.db"), agent_id="review",
        person_id="fictional", project_scope="review",
        deep_maintenance=False, max_context_chars=10000))
    instance.initialize("review-session", hermes_home=tmp_path)
    yield instance
    instance.shutdown()


def test_mirrored_replace_cannot_retire_unrelated_native_capture(provider):
    """Hermes holds an old image-service entry not previously mirrored.
    Its old_text selects that native entry; it is not an identity in Mnemos.
    """
    provider.handle_tool_call("mnemos_capture", {
        "content": "The billing service deploys to Vercel.",
    })
    store = provider._runtime._store
    original = store.get_active_engrams(agent_id="review")[0]
    provider.on_memory_write("replace", "memory",
        "The image service deploys to Fly.io.",
        metadata={"old_text": "deploys to Vercel",
                  "previous_content": "The image service deploys to Vercel."})
    after = store.get_engram(original.id)
    print("UNRELATED_AFTER_REPLACE", after.state, after.content)
    print("ACTIVE_AFTER_REPLACE", [m.content for m in store.get_active_engrams(agent_id="review")])
    assert after.state == "active", "Mirroring image-service replacement retired unrelated billing-service memory"


def test_reverse_reclassification_preserves_direction(tmp_path, monkeypatch):
    import mnemos.consolidation.connection_discovery as module
    store = EngramStore(tmp_path / "edge.db")
    try:
        encoder = Encoder(store)
        cause = encoder.encode("The migration dropped the sessions index", agent_id="review",
                               discover_connections=False, skip_surprise_detection=True)
        effect = encoder.encode("Logins slowed after the migration dropped the sessions index", agent_id="review",
                                discover_connections=False, skip_surprise_detection=True)
        store.save_connection(effect.id, Connection(target_id=cause.id, relation=ConnectionRelation.CO_ACTIVATED,
                                                    strength=0.6, formed_by="retrieval"))
        monkeypatch.setattr(module, "classify_connections", lambda *args: [])
        def verdict(_client, engram, targets):
            return ConnectionVerdicts(parsed=True, classifications=[
                ConnectionClassification(candidate_id=cause.id, relation=ConnectionRelation.CAUSES,
                                         direction="reverse", confidence=0.8, reasoning="")
            ] if engram.id == effect.id else [])
        monkeypatch.setattr(module, "connection_verdicts", verdict)
        stats = module.run_connection_discovery(store, llm_client=object(), agent_id="review")
        edges = {(r["source_id"], r["target_id"]) for r in store._get_conn().execute(
            "SELECT source_id,target_id FROM connections WHERE relation=?", (ConnectionRelation.CAUSES,))}
        print("RECLASSIFIED", stats["connections_reclassified"], "correct", (cause.id, effect.id) in edges,
              "reversed", (effect.id, cause.id) in edges)
        assert (cause.id, effect.id) in edges
        assert (effect.id, cause.id) not in edges
    finally:
        store.close()


def test_review_note_write_invalidates_prefetch(provider):
    provider.handle_tool_call("mnemos_capture", {"content": "Cobalt1234 mailbox routes to Ingrid."})
    before = provider.prefetch("Cobalt1234 mailbox")
    provider.handle_tool_call("mnemos_capture", {
        "content": "Cobalt1234 mailbox also routes to Soren.", "review": True,
    })
    fresh = provider._runtime.recall("Cobalt1234 mailbox", max_results=4)
    after = provider.prefetch("Cobalt1234 mailbox")
    print("REVIEW_NOTE", "fresh_has_Soren", "Soren" in fresh, "cached_has_Soren", "Soren" in after)
    assert "Soren" in fresh
    assert "Soren" in after


def test_hermes_native_remove_empty_content_is_mirrored(provider):
    previous = "The studio door code is ZEBRA4471."
    provider.on_memory_write("add", "memory", previous, metadata={})
    provider.on_memory_write("remove", "memory", "", metadata={
        "old_text": "studio door code", "previous_content": previous})
    remaining = provider._runtime.recall("studio door code")
    print("NATIVE_REMOVE_RECALL", remaining)
    assert "ZEBRA4471" not in remaining


def test_reverse_edge_failure_reports_maintenance_failure_and_can_be_retried(provider, monkeypatch):
    """Fault injection. At a10c83f a retried finish() could not restore the
    edge; it is now kept until saved."""
    import mnemos.encoding.encoder as module
    runtime = provider._runtime
    runtime.capture("The migration dropped the sessions index")
    cause = runtime._store.get_active_engrams(agent_id="review")[0]
    runtime._encoder._llm_client = object()
    monkeypatch.setattr(module, "classify_connections", lambda client, engram, candidates: [
        ConnectionClassification(candidate_id=cause.id, relation=ConnectionRelation.CAUSES,
                                 direction="reverse", confidence=0.8, reasoning="")
    ])
    connection = runtime._store._get_conn()
    connection.execute("CREATE TEMP TRIGGER fail_reverse_edge BEFORE INSERT ON connections "
                       "WHEN NEW.relation = 'causes' BEGIN SELECT RAISE(ABORT, 'injected edge failure'); END")
    result = runtime.capture("Logins slowed after the migration dropped the sessions index")
    effect = next(m for m in runtime._store.get_active_engrams(agent_id="review")
                  if m.content.startswith("Logins"))
    assert "Captured continuity." in result
    assert "injected edge failure" in result
    connection.execute("DROP TRIGGER fail_reverse_edge")
    runtime._encoder.finish(effect)
    incoming = runtime._store.get_connections(cause.id)
    assert any(c.target_id == effect.id and c.relation == ConnectionRelation.CAUSES for c in incoming)


def test_host_mutation_rolls_back_reverse_edge_failure(provider, monkeypatch):
    import sqlite3
    import mnemos.encoding.encoder as module
    runtime = provider._runtime
    runtime.capture("The migration dropped the sessions index")
    cause = runtime._store.get_active_engrams(agent_id="review")[0]
    runtime._encoder._llm_client = object()
    monkeypatch.setattr(module, "classify_connections", lambda client, engram, candidates: [
        ConnectionClassification(candidate_id=cause.id, relation=ConnectionRelation.CAUSES,
                                 direction="reverse", confidence=0.8, reasoning="")
    ])
    connection = runtime._store._get_conn()
    connection.execute("CREATE TEMP TRIGGER fail_reverse_edge BEFORE INSERT ON connections "
                       "WHEN NEW.relation = 'causes' BEGIN SELECT RAISE(ABORT, 'injected edge failure'); END")
    with pytest.raises(sqlite3.IntegrityError, match="injected edge failure"):
        runtime.execute_host_mutation("capture", {"content": "Logins slowed after the migration dropped the sessions index"},
                                      host_namespace="review", idempotency_key="capture1")
    all_active = runtime._store.get_active_engrams(agent_id="review")
    assert [m.id for m in all_active] == [cause.id]
    assert runtime._store.get_host_mutation("review", "capture1") is None
    print("HOST_EDGE_FAILURE", "no captured effect; no ledger success")


def test_mirrored_replace_respects_target_and_previous_content(provider):
    """The native memory target selects the image entry uniquely; the user
    target is a separate file and must not participate in its replacement.
    """
    provider.on_memory_write("add", "memory", "The image service deploys to Vercel.", metadata={})
    provider.on_memory_write("add", "user", "The billing service deploys to Vercel.", metadata={})
    store = provider._runtime._store
    originals = store.get_active_engrams(agent_id="review")
    billing = next(m for m in originals if m.content.startswith("The billing"))
    image = next(m for m in originals if m.content.startswith("The image"))
    provider.on_memory_write("replace", "memory", "The image service deploys to Fly.io.", metadata={
        "old_text": "deploys to Vercel", "previous_content": "The image service deploys to Vercel.",
    })
    billing_after = store.get_engram(billing.id)
    image_after = store.get_engram(image.id)
    print("CROSS_TARGET_REPLACE", "billing", billing_after.state, "old_image", image_after.state)
    print("CROSS_TARGET_ACTIVE", [m.content for m in store.get_active_engrams(agent_id="review")])
    assert billing_after.state == "active", "memory-target replacement retired user-target billing memory"
