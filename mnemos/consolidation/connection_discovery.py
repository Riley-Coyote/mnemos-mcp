"""
Connection discovery pass: find semantic connections between engrams
that were missed during encoding.

Phase 2 upgrade:
- Finds candidates by meaning as recall does (each memory by its best passage,
  over only the memories it may be linked to) alongside FTS5
- Uses LLM classifier for typed relationship assignment (7 types + NONE)
- Can reclassify existing low-quality connections (old all-"supports" monoculture)
- Cross-session connections: memories from different conversations that relate
"""

from __future__ import annotations

import logging
import time
from collections.abc import Collection
from typing import TYPE_CHECKING, Any

from ..core.engram import Connection
from ..core.types import ConnectionRelation, DEFAULT_AGENT_ID
from ..store import embedding_index as _embedding
from ..store.fts import distinctive_terms, fts_words, or_query, overlap
from ..encoding.llm_classifier import classify_connections

if TYPE_CHECKING:
    from ..store.sqlite_store import EngramStore
    from ..store.embedding_index import EmbeddingIndex
    from ..llm import LLMClient

log = logging.getLogger("mnemos.consolidation.connections")


class _LinkLookup:
    """The pass's lookups by meaning, read as recall reads, bounded as
    write-path indexing is.

    A memory's nearest are found the way recall finds a cue's
    (``EmbeddingIndex.search_candidates``: each candidate by its best passage
    of this scheme, less the length penalty), with the memory's own words as
    the query, over only the memories it may be linked to. Only passages
    count (``passages_only``): the whole-text vectors capture writes
    (``embeddings``) are not read. The lookup used to read only those, so a
    memory indexed only as passages was never linked by meaning: 139 of the
    554 live memories on a copy of a real store, and 2,890 of 6,654 on a copy
    grown to twelve times its size. ``floor`` is ``similarity_threshold``, a
    floor on the best passage's similarity, as before.

    Maintenance runs inside a capture, and the pass looks up to 50 memories'
    neighbours by meaning, embedding each one. With a network backend each
    lookup waited up to 30 s, so a network that hung held the capture for
    minutes. Now, with a network backend, the pass's lookups share one budget
    (``WRITE_EMBED_SECONDS``), each waits at most ``NETWORK_TIMEOUT`` and never
    past it, and the first that times out ends them: the memories left are
    linked by their words this cycle, and by meaning in a later one. The local
    model waits on no network and is not bounded. ``timeouts`` and
    ``deferred`` go into the cycle's log, where the watchdog counts them."""

    def __init__(self, index: Any | None, *, floor: float) -> None:
        self.index = index
        self.floor = floor
        self.meaning = bool(index is not None and getattr(index, "available", False))
        self.network = self.meaning and bool(getattr(index, "network", False))
        self.deadline = (
            time.monotonic() + _embedding.WRITE_EMBED_SECONDS if self.network else None
        )
        self.spent = False
        self.timeouts = 0
        self.deferred = 0

    def neighbours(self, engram: Any, candidates: Collection[str]) -> list[tuple[str, float]]:
        """``engram``'s nearest by meaning among ``candidates``, at or above
        the floor, nearest first; none when meaning is off, or spent for this
        pass (the memory is then counted as deferred)."""
        if not self.meaning:
            return []
        if self.deadline is None:
            return self._nearest(engram, candidates)
        wait = min(_embedding.NETWORK_TIMEOUT, self.deadline - time.monotonic())
        if self.spent or wait <= 0:
            self.spent = True
            self.deferred += 1
            return []
        before = getattr(self.index, "timeouts", 0)
        found = self._nearest(engram, candidates, timeout=wait)
        if getattr(self.index, "timeouts", 0) > before:
            # The backend isn't answering: nothing more is asked of it here.
            self.timeouts += 1
            self.deferred += 1
            self.spent = True
            return []
        return found

    def _nearest(
        self, engram: Any, candidates: Collection[str], *, timeout: float | None = None,
    ) -> list[tuple[str, float]]:
        return self.index.search_candidates(
            engram.content, candidates, k=10, floor=self.floor,
            passages_only=True, timeout=timeout,
        )

    def off(self) -> str | None:
        """Why this pass linked by words alone, or None when meaning was on
        throughout: no index, one that was off from the start, or one that
        went off during the pass (a local model that failed to load)."""
        if self.index is None:
            return "no embedding index"
        if self.meaning and getattr(self.index, "available", False):
            return None
        reason = getattr(self.index, "unavailable_reason", None) or "the embedding index is off"
        return " ".join(str(reason).split())


def _linkable(
    store: EngramStore, agent_id: str, person_id: str | None, project_scope: str | None,
) -> set[str]:
    """The memories a new link may reach by meaning: the active ones in the
    pass's scope, as the scope check and the state check admitted them, or
    every active one when the pass has no scope (``get_engram`` and the state
    check). Read once a pass: nothing in the pass changes a memory's state."""
    if person_id is not None and project_scope is not None:
        return store.active_engram_ids(
            agent_id=agent_id, person_id=person_id, project_scope=project_scope,
        )
    rows = store._get_conn().execute("SELECT id FROM engrams WHERE state = 'active'").fetchall()
    return {row[0] for row in rows}


def run_connection_discovery(
    store: EngramStore,
    embedding_index: Any | None = None,
    config: dict[str, Any] | None = None,
    llm_client: Any | None = None,
    agent_id: str = DEFAULT_AGENT_ID,
    person_id: str | None = None,
    project_scope: str | None = None,
) -> dict[str, Any]:
    """Find semantically related engrams and create/reclassify connections.

    Two modes:
    1. **New connections** — find engrams with few connections and discover new ones
    2. **Reclassify** — upgrade old "supports" connections using LLM classification

    Uses both FTS5 and embedding similarity for candidate discovery.
    Uses LLM classifier for typed relationship assignment.

    Args:
        store: The engram store.
        embedding_index: Embedding index for semantic search (Phase 1.5+).
        config: Configuration dict with discovery parameters.
        llm_client: LLM client for typed classification. Falls back to
            SUPPORTS if not available.

    Returns:
        Statistics dict.
    """
    config = config or {}
    max_per_pass = config.get("max_engrams_per_discovery_pass", 50)
    max_per_engram = config.get("max_connections_per_engram", 10)
    # A link says two memories belong together. By meaning, that is the
    # configured similarity (0.7 in the defaults and in users' config files; the
    # pass read nothing and took anything above 0.3). By words, it is sharing a
    # good part of what they are about: at least this much of the smaller
    # memory's distinctive words (lessons need 0.5, the same thing said again;
    # related memories need less). A memory with nothing that close gets no new
    # link, rather than being topped up with whatever shares "the" or "every".
    # Over a simulated week on a real store this cut the links the pass made
    # from 1,491 to 265, and recall found as much or more (see the PR).
    similarity_threshold = config.get("similarity_threshold", 0.7)
    keyword_overlap = config.get("discovery_keyword_overlap", 0.3)
    reclassify_batch = config.get("reclassify_batch_size", 20)

    stats = {
        "engrams_processed": 0,
        "connections_created": 0,
        "connections_reclassified": 0,
        "connections_removed": 0,
        "connections_strengthened": 0,
        "embedding_candidates": 0,
        "fts_candidates": 0,
    }

    all_active = store.get_active_engrams(
        agent_id=agent_id, person_id=person_id, project_scope=project_scope,
        limit=max_per_pass * 2,
    )

    # ── Phase A: Discover new connections for underconnected engrams ──
    underconnected = []
    for engram in all_active:
        existing = store.get_connections(engram.id)
        if len(existing) < max_per_engram:
            underconnected.append((engram, existing))

    lookup = _LinkLookup(embedding_index, floor=similarity_threshold)
    # What a link by meaning may reach, read once: none while meaning is off.
    linkable = _linkable(store, agent_id, person_id, project_scope) if lookup.meaning else set()
    for engram, existing_connections in underconnected[:max_per_pass]:
        stats["engrams_processed"] += 1
        existing_target_ids = {c.target_id for c in existing_connections}
        candidates = []

        # 1. Candidates by meaning (if available, within the pass's time):
        # the memories it isn't linked to yet, at or above the similarity.
        if lookup.meaning:
            reachable = linkable - existing_target_ids - {engram.id}
            for eid, _similarity in lookup.neighbours(engram, reachable):
                candidate = (
                    store.get_engram_in_scope(
                        eid, agent_id=agent_id, person_id=person_id,
                        project_scope=project_scope,
                    )
                    if person_id is not None and project_scope is not None
                    else store.get_engram(eid)
                )
                # Only a live memory takes a new link, as with keyword
                # candidates and recall's seeds. The index still holds the
                # vectors of archived and dormant memories, and a correction
                # reads almost like the memory it retired: linking the two
                # let recall carry light back into what was retired.
                if candidate and candidate.state == "active":
                    candidates.append(candidate)
                    stats["embedding_candidates"] += 1

        # 2. FTS5 candidates (supplement, catches keyword matches embeddings miss)
        mine = distinctive_terms(engram.content)
        words = [w for w in fts_words(engram.content) if w.lower() in mine]
        if words:
            query = or_query(words[:8])
            try:
                fts_results = store.search_fts(
                    query, limit=10, agent_id=agent_id,
                    person_id=person_id, project_scope=project_scope,
                )
                for match in fts_results:
                    if (
                        match.id != engram.id and match.id not in existing_target_ids
                        and overlap(mine, distinctive_terms(match.content)) >= keyword_overlap
                    ):
                        # Don't duplicate embedding candidates
                        if not any(c.id == match.id for c in candidates):
                            candidates.append(match)
                            stats["fts_candidates"] += 1
            except Exception:
                pass

        if not candidates:
            continue

        # 3. Classify relationships via LLM (or fallback)
        if llm_client:
            classifications = classify_connections(llm_client, engram, candidates)
            for cls in classifications:
                tag_overlap = 0
                candidate = next((c for c in candidates if c.id == cls.candidate_id), None)
                if candidate:
                    tag_overlap = len(set(engram.tags) & set(candidate.tags))

                strength = min(0.95, cls.confidence + 0.05 * tag_overlap)

                engram.add_connection(
                    target_id=cls.candidate_id,
                    relation=cls.relation,
                    strength=round(strength, 3),
                    formed_by="consolidation",
                )
                stats["connections_created"] += 1
        else:
            # Fallback when no LLM client is available: FTS keyword overlap
            # is correlation, not evidence of support. Write CO_ACTIVATED so
            # later passes can reclassify (or strip) these edges rather than
            # locking the graph into a SUPPORTS monoculture from keyword hits.
            for match in candidates[:5]:
                tag_overlap = len(set(engram.tags) & set(match.tags))
                strength = min(0.8, 0.3 + 0.1 * tag_overlap)
                engram.add_connection(
                    target_id=match.id,
                    relation=ConnectionRelation.CO_ACTIVATED,
                    strength=strength,
                    formed_by="consolidation_no_llm",
                )
                stats["connections_created"] += 1

        store.save_engram(engram)

    if lookup.network:
        # Lookups by meaning that timed out, and memories linked by their
        # words alone this cycle for want of the backend's time.
        stats["embedding_timeouts"] = lookup.timeouts
        stats["embedding_deferred"] = lookup.deferred
    off = lookup.off()
    if off:
        # Said in the cycle's log and by `mnemos consolidate`: a pass that
        # linked by words alone, and why, rather than as if meaning had run.
        stats["words_only"] = f"links by words only: meaning search is off ({off})"

    # ── Phase B: Reclassify unclassified connections ──
    if llm_client:
        _reclassify_old_connections(
            store, llm_client, all_active,
            batch_size=reclassify_batch, stats=stats,
        )

    return stats


# Relations that were mechanically formed rather than semantically
# classified: legacy "supports" monoculture edges and the structural
# co-activation edges written by retrieval reconsolidation.
_RECLASSIFIABLE_RELATIONS = (
    ConnectionRelation.SUPPORTS,
    "supports",
    ConnectionRelation.CO_ACTIVATED,
    "co_activated",
)


def _reclassify_old_connections(
    store: EngramStore,
    llm_client: Any,
    all_active: list,
    batch_size: int,
    stats: dict,
) -> None:
    """Reclassify mechanically-formed connections using LLM classification.

    Finds connections that carry no real semantic judgment — the legacy
    "supports" monoculture and retrieval's "co_activated" edges — and
    classifies them. NONE results → remove the connection (false positive).
    """
    # Find engrams with unclassified connections
    reclassified_count = 0

    for engram in all_active:
        if reclassified_count >= batch_size:
            break

        connections = store.get_connections(engram.id)
        raw_connections = [
            c for c in connections
            if c.relation in _RECLASSIFIABLE_RELATIONS
        ]

        if not raw_connections:
            continue

        # Load the target engrams
        targets = []
        for conn in raw_connections:
            target = store.get_engram(conn.target_id)
            if target:
                targets.append(target)

        if not targets:
            continue

        # Classify the batch
        classifications = classify_connections(llm_client, engram, targets)
        classified_ids = {cls.candidate_id for cls in classifications}

        for cls in classifications:
            # Find the existing connection to update
            for conn in raw_connections:
                if conn.target_id == cls.candidate_id:
                    # Update the connection type and strength
                    conn.relation = cls.relation
                    conn.strength = round(cls.confidence, 3)
                    conn.formed_by = "consolidation_reclassified"
                    store.save_connection(engram.id, conn)
                    stats["connections_reclassified"] += 1
                    reclassified_count += 1
                    break

        # Remove connections where LLM returned NONE (false positives)
        for conn in raw_connections:
            if conn.target_id not in classified_ids:
                # Target wasn't classified → check if it was in our targets list
                if any(t.id == conn.target_id for t in targets):
                    # It was sent to the LLM and came back NONE → remove
                    store.remove_connection(engram.id, conn.target_id)
                    stats["connections_removed"] += 1
