"""
Softening pass: what a fading memory taught is kept before it fades.

The forgetting itself is accessibility decay: a fading memory ranks lower and
is reached less. Its words stay as the agent wrote them. A configured model
used to rewrite them at lower resolution, "in the rememberer's own voice", and
to write the lesson a memory taught. That was another mind's words where the
agent's belong (docs/identity-model.md), and since 0.4.0 a model does neither.
Wording is blurred only by the mechanical rule, and only under
``soften_without_model``.

Shift 1 (Traces): before a memory fades, what it taught is kept as its impact.
Only the agent can say what that was, so it is asked (``awaiting_impact``).

Shift 2 (Forgetting that teaches): an impact the agent wrote becomes a "lesson"
engram, created or reinforced. Lessons are procedural engrams with high
stability that persist as accumulated wisdom.

The original content is always preserved in content_at_encoding (immutable).
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

import ulid as _ulid_mod

from ..core.placeholders import is_templated
from ..core.types import ConnectionRelation, EngramKind, SourceType
from ..store.fts import distinctive_terms, fts_words, or_query, overlap
from .lived import LivedClock

if TYPE_CHECKING:
    from ..store.sqlite_store import EngramStore

# How many active memories one softening pass reads, the least accessible first.
SOFTENING_LIMIT = 5000


def _gen_log_id(prefix: str) -> str:
    if hasattr(_ulid_mod, "new"):
        return f"{prefix}_{_ulid_mod.new()}"
    from ulid import ULID

    return f"{prefix}_{ULID()}"


def _hours_since(timestamp: str) -> float:
    """Hours since an ISO timestamp. Unparseable means old, never brand new."""
    from datetime import datetime, timezone

    try:
        then = datetime.fromisoformat(timestamp)
        if then.tzinfo is None:
            then = then.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return float("inf")
    return (datetime.now(timezone.utc) - then).total_seconds() / 3600.0


def _teach(
    engram: Any,
    store: EngramStore,
    stats: dict,
    *,
    invent_impact: bool,
) -> None:
    """Settle what a memory that has faded taught, once.

    Shift 1: before its detail goes, what it meant is kept as its impact.
    Without a licence to invent one, the agent is asked (``awaiting_impact``);
    neither the server nor a model says it for the agent. Shift 2: an impact the
    agent wrote becomes a lesson, linked back by ``distilled_into``. Which
    lesson is the helper's to judge (``_create_or_reinforce_lesson`` reuses a
    linked lesson only when it says the same thing), so a stale or misfiled
    link never stands in for the memory's own; once linked to the lesson it
    names, the memory is left as it is.
    """
    changed = False
    if not engram.impact:
        if invent_impact:
            engram.impact = _rule_based_impact(engram.content)
            engram.impact_source = "template"
            changed = True
        elif getattr(engram, "author_kind", "unknown") == "agent":
            # Shift 2 says the lesson is what survives the forgetting, so a
            # lesson the server guessed at from keywords is the one thing that
            # must not be written here. The meaning is recorded for the agent to
            # supply through mnemos_reflect. Only about its own memories: a
            # lesson is drawn only from the agent's words, so asking what a
            # tool's memory taught leads nowhere.
            stats.setdefault("awaiting_impact", []).append(engram.id)
    if engram.impact:
        lesson_id = _create_or_reinforce_lesson(engram, store, stats)
        linked = any(
            conn.relation == ConnectionRelation.DISTILLED_INTO and conn.target_id == lesson_id
            for conn in engram.connections
        )
        if lesson_id and not linked:
            engram.add_connection(
                target_id=lesson_id,
                relation=ConnectionRelation.DISTILLED_INTO,
                strength=0.8,
                formed_by="consolidation",
            )
            changed = True
    if changed:
        store.save_engram(engram)


def run_softening_pass(
    store: EngramStore,
    config: dict[str, Any],
    llm_client: Any | None,
    agent_id: str | None = None,
    person_id: str | None = None,
    project_scope: str | None = None,
    invent_impact: bool = False,
) -> dict[str, Any]:
    """Settle what faded memories taught, and blur wording only where licensed.

    Args:
        store: The engram store.
        agent_id: Agent whose memories to soften. None preserves legacy
            behavior (the store's own default scope); callers that manage
            multiple agents in one store MUST pass this explicitly —
            softening rewrites memory content, and rewriting another
            agent's memories is identity contamination.
        config: Configuration dict with softening parameters. Set
            softening_dry_run=True to compute and log before/after pairs
            to consolidation_log (pass_name "softening_dry_run") without
            rewriting any engram — audit the conservator before enabling.
        llm_client: Kept for the daemon's call; never called. A model's
            rewording or lesson would be another mind's words in the agent's
            memory.
        config: also honours ``soften_without_model`` (default False). With no
            provider, rewriting prose means `_rule_based_soften`, which
            replaces a memory with "An impression related to <first word>...
            [faded]" and cannot be undone through any product path. The
            forgetting is accessibility decay and happens regardless; the
            blurred wording was only ever a depiction of it. So the default
            install now fades a memory in ranking and leaves its words
            readable — which is also the only way the agent can answer the
            lesson question honestly, since it is asked about a memory that is
            supposedly fading.

    Returns:
        Statistics dict.
    """
    softening_threshold = config.get("softening_threshold", 0.15)
    minimum_resolution = config.get("minimum_resolution", 0.1)
    dry_run = bool(config.get("softening_dry_run", False))
    soften_without_model = bool(config.get("soften_without_model", False))
    started_at = datetime.now(timezone.utc).isoformat()

    stats = {
        "engrams_evaluated": 0,
        "engrams_softened": 0,
        "lessons_created": 0,
        "lessons_reinforced": 0,
        "avg_resolution_before": 0.0,
        "avg_resolution_after": 0.0,
        "dry_run": dry_run,
    }

    # Faded first: what this pass teaches and blurs is what has faded, and on a
    # store with more active memories than the limit, the faded were the ones cut.
    all_engrams = store.get_active_engrams(
        agent_id=agent_id, person_id=person_id, project_scope=project_scope,
        limit=SOFTENING_LIMIT, least_accessible_first=True,
    )

    total_res_before = 0.0
    total_res_after = 0.0
    softened_count = 0
    dry_run_pairs: list[dict[str, Any]] = []

    # Forgetting takes time. Softening triggers on accessibility alone, and a
    # newly encoded engram already sits at 0.5 — so with the pass enabled, a
    # memory captured seconds ago qualified as fading and the agent was asked
    # what it had taught. Nothing had faded; the pass had simply never run
    # before, so the missing notion of age had never mattered.
    # The age is in the lived hours of the pass's agent (see lived.py); with
    # no agent named, in wall hours.
    min_age_hours = float(config.get("softening_min_age_hours", 24))
    clock = LivedClock.for_agent(store, agent_id) if agent_id is not None else None

    for engram in all_engrams:
        age_hours = _hours_since(engram.created_at)
        if clock is not None and age_hours != float("inf"):
            age_hours = clock.hours_between(engram.created_at)
        if age_hours < min_age_hours:
            stats["too_recent"] = stats.get("too_recent", 0) + 1
            continue

        # Forgetting teaches only what was forgotten. A new memory starts at 0.5
        # accessibility and the target resolution starts falling below 0.7, so
        # without this a day-old memory "faded": its meaning was copied into a
        # lesson and it was asked what it taught. softening_threshold was read and
        # never used. What a memory taught is settled here, before the exits
        # below, which are about its wording: under soften_without_model a
        # memory is blurred step by step as it fades,
        # and one already blurred near its floor must still teach when it fades.
        if engram.accessibility >= softening_threshold:
            stats["not_faded"] = stats.get("not_faded", 0) + 1
        elif not dry_run:
            if store.standing_mark(engram.id) is not None:
                # How the person wants the agent to work is never taught.
                stats["standing"] = stats.get("standing", 0) + 1
            else:
                _teach(engram, store, stats, invent_impact=invent_impact)

        if engram.resolution <= minimum_resolution:
            continue  # Already at minimum resolution

        stats["engrams_evaluated"] += 1
        total_res_before += engram.resolution

        # Determine target resolution from accessibility
        target = _calculate_target_resolution(engram.accessibility)

        if target >= engram.resolution:
            total_res_after += engram.resolution
            continue  # No softening needed — accessibility still high enough

        # Hysteresis: only soften if significantly above target
        if engram.resolution <= target + 0.15:
            total_res_after += engram.resolution
            continue

        # Cap at minimum resolution
        target = max(minimum_resolution, target)

        if dry_run:
            # Audit mode: compute what softening WOULD do, log the
            # before/after pair, and leave the engram untouched.
            candidate = _rule_based_soften(engram.content, target)
            softened_content = _conserve(engram.content, candidate, target)
            dry_run_pairs.append(
                {
                    "engram_id": engram.id,
                    "resolution_before": engram.resolution,
                    "resolution_target": round(target, 2),
                    "before": engram.content[:500],
                    "after": softened_content[:500],
                }
            )
            total_res_after += engram.resolution
            continue

        # SOFTEN content (impact is preserved separately)
        candidate = None
        if soften_without_model:
            candidate = _rule_based_soften(engram.content, target)
        else:
            # No licence to guess, and no model rewords the agent's memory.
            # Compressing prose requires reading it; `_rule_based_soften` does
            # not read, it truncates, and the result is unrecoverable through
            # any product path. Record that the wording is still owed — the
            # memory keeps fading through accessibility either way, and the
            # lesson request that goes to the agent shows text it can read.
            stats["awaiting_compression"] = stats.get("awaiting_compression", 0) + 1

        if candidate is not None:
            # Conservation guard: softening may compress, never inflate or
            # invent. A candidate that grows or introduces new named entities
            # is rejected in code, not just in the prompt.
            softened_content = _conserve(engram.content, candidate, target)

            # Version snapshot (preserve pre-softening state)
            engram.add_version(reason="softening")

            # Update content (impact is already set and untouched)
            engram.content = softened_content
            engram.resolution = round(target, 2)

        store.save_engram(engram)

        total_res_after += engram.resolution
        # Only a memory whose wording actually changed was softened. Counting
        # the others would report compression that did not happen, in the one
        # statistic an operator would use to check whether it did.
        if candidate is not None:
            softened_count += 1
            stats["engrams_softened"] += 1

    if dry_run:
        stats["engrams_would_soften"] = len(dry_run_pairs)
        if dry_run_pairs:
            store.log_consolidation(
                log_id=_gen_log_id("softening_dry_run"),
                pass_name="softening_dry_run",
                started_at=started_at,
                completed_at=datetime.now(timezone.utc).isoformat(),
                stats={"agent_id": agent_id, "pairs": dry_run_pairs},
            )

    if stats["engrams_evaluated"] > 0:
        stats["avg_resolution_before"] = round(
            total_res_before / stats["engrams_evaluated"], 3
        )
        stats["avg_resolution_after"] = round(
            total_res_after / stats["engrams_evaluated"], 3
        )

    return stats


def _calculate_target_resolution(accessibility: float) -> float:
    """Map accessibility to appropriate resolution level.

    Ported from Anima's calculate_target_sharpness.
    """
    if accessibility >= 0.7:
        return 1.0
    elif accessibility >= 0.4:
        t = (accessibility - 0.4) / 0.3
        return 0.4 + (0.6 * t)
    elif accessibility >= 0.15:
        t = (accessibility - 0.15) / 0.25
        return 0.1 + (0.3 * t)
    else:
        return 0.0


def _new_named_entities(original: str, softened: str) -> set[str]:
    """Capitalized mid-sentence tokens in the softened text absent from the original."""
    orig_tokens = {t.lower() for t in re.findall(r"[A-Za-z][\w'’-]*", original)}
    out = set()
    for m in re.finditer(r"\b[A-Z][\w'’-]+\b", softened):
        tok = m.group(0)
        if tok.lower() in orig_tokens:
            continue
        prefix = softened[: m.start()].rstrip()
        if not prefix or prefix[-1] in ".!?…":
            continue  # sentence-initial capitalization is not an entity signal
        out.add(tok)
    return out


def _is_conserved(original: str, softened: str) -> bool:
    if not softened or not softened.strip():
        return False
    if len(softened) > len(original):
        return False
    return not _new_named_entities(original, softened)


def _conserve(original: str, candidate: str, target_resolution: float) -> str:
    """Enforce the conservator invariants on a softened candidate.

    Softening may compress, never inflate or invent. A candidate that is
    longer than the original or introduces named entities the original
    never contained is rejected; the rule-based softener is tried next,
    and if even that violates (e.g. on very short memories), the original
    content is kept — there was no detail to shed.
    """
    candidate = (candidate or "").strip()
    if _is_conserved(original, candidate):
        return candidate
    fallback = _rule_based_soften(original, target_resolution)
    if _is_conserved(original, fallback):
        return fallback
    return original


def _rule_based_impact(content: str) -> str:
    """Extract impact without LLM — take the core assertion.

    Heuristic: the last substantive sentence is often the conclusion/lesson.
    """
    sentences = [s.strip() for s in content.split(".") if s.strip()]
    # Take the last substantive sentence (often the insight)
    for s in reversed(sentences):
        if len(s) > 15:
            return s
    return content[:100] if content else ""


# Two lessons are the same lesson when they share at least half of the smaller
# one's distinctive words, and at least two of them (_same_lesson). Measured on
# a real store's 631 distilled_into links: a lesson and the impact it was drawn
# from share all of them (164 links); rewordings of one lesson share 0.49 to
# 0.71; links the old any-word match made share 0.3 at most, and 451 of them
# 0.2 or less.
_SAME_LESSON = 0.5


def _same_lesson(mine: set[str], theirs: set[str]) -> bool:
    """Whether two texts teach the same lesson, by their distinctive words.

    Half of the smaller set is not enough on its own: when a lesson has two
    distinctive words, one shared word is half. #75 made many lessons that
    short ("everything", "else" and "first" became common), and fading
    memories were filed under lessons they share one word with: "Weather is
    the book's clock." under "This book is what we're here for; everything
    else bends around it." So they must also share two words, the rule #74
    set for links made without a model. A false merge loses a lesson; a
    missed one only leaves a near-duplicate.

    A lesson with one distinctive word ("Always verify.") shares only one with
    anything, so it is the same only as a text with exactly that word.
    Otherwise the memory it was drawn from would stop recognising it and
    distil a copy every cycle.
    """
    shared = len(mine & theirs)
    if shared >= 2:
        return overlap(mine, theirs) >= _SAME_LESSON
    return bool(mine) and mine == theirs


def _create_or_reinforce_lesson(
    engram: Any,
    store: EngramStore,
    stats: dict,
    *,
    author_model: str = "",
    author_session: str = "",
) -> str | None:
    """Create or reinforce a lesson engram from the impact of a softened memory.

    Shift 2: Forgetting that teaches. The distilled insight from softening
    becomes a persistent "lesson" engram with high stability. If a similar
    lesson already exists, reinforce it instead of creating a duplicate.

    A lesson copies the words of the impact it is drawn from, and lessons are
    the most durable thing a memory keeps, so one is drawn only from an impact
    the agent wrote (``impact_source`` 'agent') on a memory the agent wrote
    (``author_kind`` 'agent'), and only an agent's lesson is reinforced.
    Words a tool or a model wrote never become one. ``author_model`` and
    ``author_session`` sign a new lesson when the caller knows who wrote the
    impact (an answer just given through mnemos_reflect); softening, which
    finds the impact later, leaves the model unsigned.

    Returns the lesson engram ID, or None if no lesson was created.
    """
    impact_text = engram.impact
    if not impact_text or len(impact_text.strip()) < 10:
        return None
    if getattr(engram, "author_kind", "unknown") != "agent":
        return None
    if getattr(engram, "impact_source", "") != "agent":
        return None
    # A lesson is already what a memory taught. When one fades it fades like any
    # memory, but it is not distilled again: its impact is its own words, so it
    # would become a second copy of itself, linked to the first.
    if "lesson" in engram.tags or "distilled" in engram.tags:
        return None
    # A placeholder the server wrote ("Correction to earlier continuity.") says
    # nothing the memory taught. It must not become a lesson, or strengthen one:
    # every memory carrying the same placeholder reinforced the same "lesson".
    if is_templated(impact_text, getattr(engram, "impact_source", "")):
        return None

    mine = distinctive_terms(impact_text)

    # Already distilled, on an earlier cycle, into a lesson that says this. With
    # no model, a fading memory's wording is never compressed, so it qualifies
    # again every cycle; reinforcing its lesson each time grew the same lessons
    # without end (143 reinforcements a cycle on a real store) and kept them the
    # most-accessed memories in the graph.
    for conn in engram.connections:
        if conn.relation == ConnectionRelation.DISTILLED_INTO:
            lesson = store.get_engram(conn.target_id)
            if (
                lesson is not None and lesson.author_kind == "agent"
                and _same_lesson(mine, distinctive_terms(lesson.content))
            ):
                return lesson.id

    # Look for a lesson that already says the same thing, by the impact's own
    # distinctive words. Its first six words, common ones included, matched
    # nearly every lesson, and the first lesson found was taken as the same one.
    words = [w for w in fts_words(impact_text) if w.lower() in mine] or fts_words(impact_text)
    if not words:
        return None

    query = or_query(words[:8])
    try:
        existing = store.search_fts(
            query, limit=10, agent_id=engram.owner_agent_id,
            person_id=engram.person_id, project_scope=engram.project_scope,
        )
    except Exception:
        existing = []

    # Check if any existing engram is a lesson that says the same thing
    for candidate in existing:
        if candidate.id == engram.id:
            continue
        if candidate.author_kind != "agent":
            continue  # a tool's "lesson" is not strengthened by the agent's evidence
        if ("lesson" in candidate.tags or "distilled" in candidate.tags) and _same_lesson(
            mine, distinctive_terms(candidate.content)
        ):
            # Reinforce existing lesson. Not an access: maintenance reading its
            # own lessons is not the agent reading them, and counting it made
            # lessons nobody had been shown look like the most-read memories.
            candidate.strength = min(1.0, candidate.strength + 0.1)
            candidate.stability = min(1.0, candidate.stability + 0.05)
            store.save_engram(candidate)
            # A second experience teaching the same lesson must also be
            # linked to it, or the lesson's evidence stays invisible.
            _link_distillation(engram, candidate.id, store)
            stats["lessons_reinforced"] = stats.get("lessons_reinforced", 0) + 1
            return candidate.id

    # No existing lesson found — create a new one
    from ..core.engram import Engram, MemorySource
    lesson = Engram(
        content=impact_text,
        impact=impact_text,  # For lessons, impact IS the content
        # The agent's words: an impact it wrote on a memory it wrote.
        author_kind="agent",
        author_model=(author_model or "").strip(),
        author_session=(author_session or "").strip(),
        kind=EngramKind.PROCEDURAL,
        tags=list(set(engram.tags + ["lesson", "distilled"])),
        strength=0.8,
        stability=0.8,  # High stability — lessons persist
        source=MemorySource(
            type=SourceType.REFLECTION,
            confidence=engram.source.confidence,
            confidence_source=engram.source.confidence_source,
        ),
        owner_agent_id=engram.owner_agent_id,
        person_id=engram.person_id,
        project_scope=engram.project_scope,
    )

    store.save_engram(lesson)

    # Shift 2 is not the lesson existing, it is the lesson being *reachable
    # from* the experience it came from. Without this edge the distillate is
    # an orphan, resonance can never travel from a fading memory to what it
    # taught, and the count of DISTILLED_INTO edges stays at zero — which is
    # exactly what it was across every Mnemos store ever built.
    _link_distillation(engram, lesson.id, store)

    stats["lessons_created"] = stats.get("lessons_created", 0) + 1
    return lesson.id


def _link_distillation(engram: Any, lesson_id: str, store: EngramStore) -> None:
    """Connect an experience to the lesson drawn from it."""
    from ..core.types import ConnectionRelation

    already = any(
        c.target_id == lesson_id and c.relation == ConnectionRelation.DISTILLED_INTO
        for c in engram.connections
    )
    if already:
        return
    engram.add_connection(
        target_id=lesson_id,
        relation=ConnectionRelation.DISTILLED_INTO,
        strength=0.9,
        formed_by="softening",
    )
    store.save_engram(engram)


#: Exact tails `_rule_based_soften` produces. Provenance cannot tell a
#: model-written softening from a truncated one — `change_reason` is
#: "softening" for both — so the output signature is what makes a targeted
#: repair possible at all. A model asked to write in the rememberer's own
#: voice does not end a sentence this way.
_RULE_BASED_TAILS = ("... [details faded]", "... [faded]")


def repair_rule_based_softening(
    store: EngramStore,
    agent_id: str = "default",
    *,
    dry_run: bool = False,
) -> int:
    """Restore memories a model-less softening pass truncated.

    Before ``soften_without_model`` defaulted to False, any engram older than
    a day whose accessibility had dropped was rewritten to
    "An impression related to <first word>... [faded]" and its ``impact`` left
    empty. ``add_version(reason="softening")`` snapshotted the prior state
    first, so the words are recoverable — but nothing recovers them on its
    own. Mnemos 0.2.1 also restores archived records through
    ``archive.resharpen``; this repair remains narrower because it targets
    destructive softening performed before archival.

    Only engrams whose current content ends in a rule-based tail *and* which
    have a pre-softening snapshot are touched. Returns how many were restored
    (or would be, when ``dry_run``).

    This is deliberately narrow. Restoring on a guess would be the same
    mistake as the 32,857 keyword-overlap edges written as SUPPORTS: a
    plausible rewrite of memory that nobody can audit afterwards.
    """
    restored = 0
    for engram in store.get_active_engrams(agent_id=agent_id, limit=100000):
        content = (engram.content or "").rstrip()
        if not content.endswith(_RULE_BASED_TAILS):
            continue

        snapshot = next(
            (
                v for v in reversed(getattr(engram, "versions", []) or [])
                if getattr(v, "change_reason", "") == "softening"
                and (getattr(v, "content_snapshot", "") or "").strip()
                and not (getattr(v, "content_snapshot", "") or "")
                .rstrip()
                .endswith(_RULE_BASED_TAILS)
            ),
            None,
        )
        if snapshot is None:
            continue

        restored += 1
        if dry_run:
            continue

        engram.content = snapshot.content_snapshot
        engram.resolution = max(
            engram.resolution, getattr(snapshot, "resolution_at_version", 1.0) or 1.0
        )
        engram.add_version(reason="repair_rule_based_softening")
        store.save_engram(engram)

    return restored


def _rule_based_soften(content: str, target_resolution: float) -> str:
    """Soften memory without LLM — rule-based fallback."""
    if target_resolution >= 0.4:
        # Keep first sentence, blur the rest
        sentences = content.split(".")
        first = sentences[0].strip() if sentences else content[:50]
        return f"{first}... [details faded]"
    else:
        # Deep impression: just the emotional residue
        words = content.split()
        key_word = words[0] if words else "something"
        return f"An impression related to {key_word}... [faded]"


def find_misfiled_distillations(
    store: EngramStore,
    agent_id: str,
    person_id: str,
    project_scope: str,
) -> list[dict[str, Any]]:
    """distilled_into links from this scope's memories that do not hold what they claim.

    A link is misfiled when the memory's impact is a placeholder the server
    wrote, or when the lesson says something else: not the same lesson by
    _same_lesson, the bar _create_or_reinforce_lesson applies before filing
    anything. Links made before that bar existed were filed on any shared
    word, and those made after #75 on one, and still carry recall's light at
    the weight of real evidence.
    """
    rows = store._get_conn().execute(
        """
        SELECT c.source_id, c.target_id, s.impact, s.impact_source,
               s.content AS source_content, l.content AS lesson
        FROM connections c
        JOIN engrams s ON s.id = c.source_id
        JOIN engrams l ON l.id = c.target_id
        WHERE c.relation = 'distilled_into'
          AND s.owner_agent_id = ? AND s.person_id = ? AND s.project_scope = ?
        ORDER BY c.source_id, c.target_id
        """,
        (agent_id, person_id, project_scope),
    ).fetchall()
    misfiled = []
    for row in rows:
        if is_templated(row["impact"], row["impact_source"]):
            reason = "placeholder"
        elif not _same_lesson(
            distinctive_terms(row["impact"] or row["source_content"] or ""),
            distinctive_terms(row["lesson"] or ""),
        ):
            reason = "unrelated"
        else:
            continue
        misfiled.append({"source_id": row["source_id"], "target_id": row["target_id"], "reason": reason})
    return misfiled
