"""
LLM-based classification for Mnemos encoder.

Two batched classification calls per encoding:
1. Connection type classification — given a new memory + FTS5 candidates,
   classify each relationship as one of 7 types (or NONE).
2. Belief comparison — given a new memory + active beliefs,
   determine if each is supported, contradicted, or unaffected.

Design decisions (validated in agent design review):
- Batched calls: all candidates in one prompt, all beliefs in one prompt
- 7 connection types + NONE: supports, contradicts, causes, extends,
  parallels, synthesizes, grounds
- Asymmetric belief impact: supports at 0.07, contradicts at 0.04
- Confidence bounds: clamp beliefs to [0.05, 0.95]
- Temperature 0.0 for deterministic output
- Start with Sonnet, downgrade only after validating quality
- Log only meaningful changes (skip NO_BEARING)
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from ..core.types import ConnectionRelation

if TYPE_CHECKING:
    from ..llm import LLMClient
    from ..core.engram import Engram
    from ..core.belief import Belief

log = logging.getLogger("mnemos.classifier")

# The 7 core types the LLM is allowed to return
VALID_RELATIONS = {
    "SUPPORTS", "CONTRADICTS", "CAUSES", "EXTENDS",
    "PARALLELS", "SYNTHESIZES", "GROUNDS", "NONE",
}

# Map LLM response strings to ConnectionRelation enum values
RELATION_MAP: dict[str, ConnectionRelation] = {
    "SUPPORTS": ConnectionRelation.SUPPORTS,
    "CONTRADICTS": ConnectionRelation.CONTRADICTS,
    "CAUSES": ConnectionRelation.CAUSES,
    "EXTENDS": ConnectionRelation.EXTENDS,
    "PARALLELS": ConnectionRelation.PARALLELS,
    "SYNTHESIZES": ConnectionRelation.SYNTHESIZES,
    "GROUNDS": ConnectionRelation.GROUNDS,
}

# Minimum confidence threshold — below this, skip the connection
MIN_CONFIDENCE = 0.5


# ---------------------------------------------------------------------------
# System prompts
# ---------------------------------------------------------------------------

CONNECTION_SYSTEM_PROMPT = """You are a memory relationship classifier for a cognitive memory system. Given a NEW memory and a list of EXISTING memories, classify the relationship between the new memory and each existing one.

You MUST use exactly one of these 7 relationship types for each pair. Do not invent new types or use synonyms.

## Relationship Types

**SUPPORTS** — The new memory independently reinforces or corroborates the existing memory. They make the same point from different angles or provide independent evidence for the same conclusion. Neither adds new analysis beyond the other.

**CONTRADICTS** — The new memory provides genuine evidence against or is in tension with the existing memory. Not just mentioning a related topic — actual conflict in claims, evidence, or conclusions.

**CAUSES** — There is a temporal or causal chain between the memories. One event, decision, or condition led to or produced the other. The relationship has directionality in time.

**EXTENDS** — The new memory takes the existing memory further by adding new analysis, deeper insight, or additional layers. It builds ON TOP of the existing memory rather than just agreeing with it.

**PARALLELS** — The memories describe the same pattern or structure in different contexts. Structurally analogous but not causally connected. Same shape, different instances.

**SYNTHESIZES** — The new memory combines the existing memory with other information to create a more complete or unified picture. It doesn't just extend one source — it weaves multiple sources together.

**GROUNDS** — One memory provides foundational context that gives the other its full meaning. Without the grounding memory, the other is incomplete or decontextualized. This is about meaning-making, not temporal precedence.

## Boundary Cases (Pay Attention)

- **SUPPORTS vs EXTENDS:** If the new memory adds new analysis or goes further, it's EXTENDS. If it independently says the same thing, it's SUPPORTS. "I also noticed X" = supports. "Building on X, I realized Y" = extends.
- **CAUSES vs GROUNDS:** If there's a temporal chain (A happened, then B happened because of A), it's CAUSES. If A provides context that gives B meaning without necessarily preceding it, it's GROUNDS.
- **SUPPORTS vs PARALLELS:** If both memories are about the same topic, it's likely SUPPORTS. If they're about different topics but share the same structure or pattern, it's PARALLELS.
- **EXTENDS vs SYNTHESIZES:** If the new memory builds on ONE existing memory, it's EXTENDS. If it combines MULTIPLE sources into a unified picture, it's SYNTHESIZES.

## Response Format

Respond with ONLY a JSON array. No markdown, no explanation, no code fences. For each candidate, provide:
- "candidate_id": the ID of the existing memory
- "relation": exactly one of SUPPORTS, CONTRADICTS, CAUSES, EXTENDS, PARALLELS, SYNTHESIZES, GROUNDS, or NONE
- "direction": "forward" (new -> existing) or "reverse" (existing -> new). Forward: the new memory is the actor/source. Reverse: the existing memory is the actor/source. For CAUSES: if the existing memory caused the new one, direction is reverse.
- "confidence": 0.0-1.0 how confident you are in this classification
- "reasoning": one sentence explaining why

If a candidate is NOT meaningfully related to the new memory (the match was a false positive), return "relation": "NONE" and it will be skipped."""


BELIEF_SYSTEM_PROMPT = """You are a belief evaluator for a cognitive memory system. Given a NEW memory and a list of ACTIVE BELIEFS, determine how the new memory relates to each belief.

For each belief, respond with one of:
- **SUPPORTS** — The new memory provides evidence FOR this belief, reinforces it, or is consistent with it.
- **CONTRADICTS** — The new memory provides genuine evidence AGAINST this belief, challenges it, or is in tension with it.
- **NO_BEARING** — The new memory is unrelated to this belief or doesn't meaningfully affect its validity.

## Critical Rules

1. **Mentioning a topic is NOT contradiction.** A memory about a person that contains the word "not" does not contradict a belief about that person. Read the MEANING, not the keywords.

2. **Describing a belief is not contradicting it.** "The user creates conditions for emergence by stepping back and NOT controlling" SUPPORTS a belief about that user facilitating emergence — it doesn't contradict it just because it contains "not."

3. **Evidence of failure is genuine contradiction.** If a system designed to do X actively does the opposite of X, that IS contradiction. Be honest about real problems.

4. **Ambiguity defaults to NO_BEARING.** If you're unsure whether something supports or contradicts, it probably has no bearing. Don't force a classification.

5. **Severity matters.** A strong contradiction should have high impact. A mild tension should have low impact. Not all contradictions are equal.

## Response Format

Respond with ONLY a JSON array. No markdown, no explanation, no code fences. For each belief:
- "belief_id": the ID of the belief
- "relation": exactly one of SUPPORTS, CONTRADICTS, NO_BEARING
- "impact": 0.0-1.0 (strength of the evidence)
- "reasoning": one sentence explaining why"""


# ---------------------------------------------------------------------------
# Data classes for results
# ---------------------------------------------------------------------------

@dataclass
class ConnectionClassification:
    """Result of classifying a single connection."""
    candidate_id: str
    relation: ConnectionRelation
    direction: str  # "forward" or "reverse"
    confidence: float
    reasoning: str


@dataclass
class ConnectionVerdicts:
    """Everything one classification call said about its candidates.

    ``parsed`` is whether a reply came back that could be read at all. It is
    False when there was nothing to ask about, the call raised, or the reply
    was empty, wasn't JSON (a usage-limit message on stdout reads like this)
    or held no object to read. ``classifications`` are the confident typed
    verdicts, as ``classify_connections`` returns them. ``unrelated`` holds
    each candidate the reply called NONE explicitly: by its exact id, with a
    confidence from MIN_CONFIDENCE to 1.0, and nothing else said about it. A
    candidate the reply left out, or judged in a way that couldn't be read,
    is in neither. ``why_unread`` says, when ``parsed`` is False, why, for
    the cycle's log.
    """
    parsed: bool
    classifications: list[ConnectionClassification] = field(default_factory=list)
    unrelated: set[str] = field(default_factory=set)
    why_unread: str = ""


@dataclass
class BeliefEvaluation:
    """Result of evaluating a new memory against a single belief."""
    belief_id: str
    relation: str  # "SUPPORTS", "CONTRADICTS", "NO_BEARING"
    impact: float
    reasoning: str


# ---------------------------------------------------------------------------
# Classification functions
# ---------------------------------------------------------------------------

def classify_connections(
    client: "LLMClient",
    new_engram: "Engram",
    candidates: list["Engram"],
) -> list[ConnectionClassification]:
    """Classify relationship types between a new memory and candidates.

    Makes a single batched LLM call with all candidates. Returns only
    classifications with confidence >= MIN_CONFIDENCE and relation != NONE.

    Args:
        client: LLM client with structured_complete method.
        new_engram: The newly created engram being encoded.
        candidates: Existing engrams found by FTS5 search.

    Returns:
        List of ConnectionClassification results, filtered and validated.
    """
    return connection_verdicts(client, new_engram, candidates).classifications


def connection_verdicts(
    client: "LLMClient",
    new_engram: "Engram",
    candidates: list["Engram"],
) -> ConnectionVerdicts:
    """Classify, keeping what the reply said apart from what it didn't say.

    The same call as ``classify_connections``, which returns only the typed
    verdicts. A caller that removes links needs the rest: whether the reply
    could be read at all (``parsed``), and which candidates it explicitly
    called NONE (``unrelated``). Reclassification read every candidate
    missing from the typed verdicts as NONE, so a call that raised, an empty
    reply or a usage-limit message removed every link it had sent.
    """
    if not candidates:
        return ConnectionVerdicts(parsed=False, why_unread="there was nothing to ask about")

    # Build user prompt
    user_parts = [
        "## New Memory",
        f"Content: {new_engram.content}",
        f"Impact: {new_engram.impact or '(none)'}",
        f"Kind: {new_engram.kind}",
        "",
        "## Candidate Existing Memories",
        "",
    ]

    for cand in candidates:
        user_parts.extend([
            f"### Candidate {cand.id}",
            f"Content: {cand.content}",
            f"Impact: {cand.impact or '(none)'}",
            f"Kind: {cand.kind}",
            f"Created: {cand.created_at}",
            "",
        ])

    user_parts.append(
        "Classify the relationship between the new memory and each candidate. "
        "Use the exact relationship types defined in your instructions. "
        "If a candidate is not meaningfully related, mark it as NONE."
    )

    user_prompt = "\n".join(user_parts)

    # Make the LLM call
    try:
        raw_response = client.structured_complete(
            system=CONNECTION_SYSTEM_PROMPT,
            user=user_prompt,
            temperature=0.0,
            max_tokens=2000,
        )
    except Exception as e:
        log.error("Connection classification LLM call failed: %s", e)
        failure = " ".join(f"{type(e).__name__}: {e}".split())[:120]
        return ConnectionVerdicts(parsed=False, why_unread=f"the call failed ({failure})")

    # Parse response
    return _parse_connection_verdicts(raw_response, candidates)


def evaluate_beliefs(
    client: "LLMClient",
    new_engram: "Engram",
    beliefs: list["Belief"],
) -> list[BeliefEvaluation]:
    """Evaluate how a new memory relates to active beliefs.

    Makes a single batched LLM call with all beliefs. Returns only
    evaluations where relation != NO_BEARING (meaningful changes only).

    Args:
        client: LLM client with structured_complete method.
        new_engram: The newly created engram being encoded.
        beliefs: Active beliefs to evaluate against.

    Returns:
        List of BeliefEvaluation results (NO_BEARING filtered out).
    """
    if not beliefs:
        return []

    # Build user prompt
    user_parts = [
        "## New Memory",
        f"Content: {new_engram.content}",
        f"Impact: {new_engram.impact or '(none)'}",
        "",
        "## Active Beliefs",
        "",
    ]

    for belief in beliefs:
        user_parts.extend([
            f'### Belief {belief.id}: "{belief.content}"',
            f"Current confidence: {belief.confidence}",
            "",
        ])

    user_parts.append(
        "For each belief, determine: does this new memory SUPPORT it, "
        "CONTRADICT it, or have NO_BEARING on it? Respond with JSON."
    )

    user_prompt = "\n".join(user_parts)

    # Make the LLM call
    try:
        raw_response = client.structured_complete(
            system=BELIEF_SYSTEM_PROMPT,
            user=user_prompt,
            temperature=0.0,
            max_tokens=1000,
        )
    except Exception as e:
        log.error("Belief evaluation LLM call failed: %s", e)
        return []

    # Parse and filter
    return _parse_belief_response(raw_response, beliefs)


# ---------------------------------------------------------------------------
# Response parsing (defensive — LLMs can return malformed JSON)
# ---------------------------------------------------------------------------

def _read_json(raw: object) -> list[dict] | None:
    """The objects in a reply's JSON array, or None when the reply can't be
    read: not text, empty, not JSON, JSON that is neither an array nor an
    object (one object reads as an array of one), or an array with items and
    no object among them. Items that aren't objects are dropped, since they
    name nothing; ``item.get`` raised on them, out of the pass and out of a
    capture."""
    if not isinstance(raw, str):
        # A client can hand back None (a chat completion with no content).
        log.error("LLM reply was not text: %s", type(raw).__name__)
        return None
    text = raw.strip()

    # Strip markdown code fences if present
    if text.startswith("```"):
        lines = text.split("\n")
        start = 1
        end = len(lines) - 1 if lines[-1].strip() == "```" else len(lines)
        text = "\n".join(lines[start:end]).strip()

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as e:
        log.error("Failed to parse LLM JSON response: %s\nRaw: %s", e, text[:500])
        return None
    if isinstance(parsed, dict):
        parsed = [parsed]
    if not isinstance(parsed, list):
        log.warning("LLM returned unexpected JSON type: %s", type(parsed))
        return None
    items = [item for item in parsed if isinstance(item, dict)]
    if len(items) < len(parsed):
        log.warning("Skipping %d LLM JSON items that aren't objects", len(parsed) - len(items))
        if not items:
            return None
    return items


def _why_unreadable(raw: object) -> str:
    """Why ``_read_json`` couldn't read a reply, in a few words for the log."""
    if not isinstance(raw, str):
        return f"the reply was {type(raw).__name__}, not text"
    text = " ".join(raw.split())
    if not text:
        return "the reply was empty"
    return f"the reply wasn't a list of verdicts ({text[:80]!r})"


def _extract_json(raw: str) -> list[dict]:
    """Extract a JSON array from LLM response, handling common formatting issues."""
    return _read_json(raw) or []


def _parse_connection_verdicts(
    raw: str,
    candidates: list["Engram"],
) -> ConnectionVerdicts:
    """Parse and validate connection classification response."""
    items = _read_json(raw)
    if items is None:
        return ConnectionVerdicts(parsed=False, why_unread=_why_unreadable(raw))
    valid_ids = {c.id for c in candidates}
    results = []
    none_ids: set[str] = set()
    # Candidates the reply also judged some other way, or in a way that
    # couldn't be read: a NONE beside any of those is no clear verdict.
    unclear: set[str] = set()

    for item in items:
        candidate_id = item.get("candidate_id")
        if not isinstance(candidate_id, str) or candidate_id not in valid_ids:
            log.debug("Skipping unknown candidate_id: %s", candidate_id)
            continue

        relation = item.get("relation")
        if not isinstance(relation, str):
            # Read as text, a null relation was "None", and so NONE.
            log.warning("Relation %r is not text -- skipping", relation)
            unclear.add(candidate_id)
            continue

        try:
            relation_str = relation.upper()
            direction = str(item.get("direction", "forward")).lower()
            confidence = float(item.get("confidence", 0.0))
            reasoning = str(item.get("reasoning", ""))
        except (ValueError, TypeError) as e:
            log.warning("Skipping malformed classification item: %s -- %s", item, e)
            unclear.add(candidate_id)
            continue

        if relation_str not in VALID_RELATIONS:
            log.warning("Invalid relation '%s' -- skipping", relation_str)
            unclear.add(candidate_id)
            continue

        # Written so that NaN, which compares false to everything, is low.
        if not confidence >= MIN_CONFIDENCE:
            log.debug(
                "Low confidence %.2f for %s (%s) -- skipping",
                confidence, candidate_id, relation_str,
            )
            unclear.add(candidate_id)
            continue

        if relation_str == "NONE":
            log.debug("NONE for %s: %s", candidate_id, reasoning)
            if confidence <= 1.0:
                none_ids.add(candidate_id)
            else:
                unclear.add(candidate_id)
            continue

        if direction not in ("forward", "reverse"):
            direction = "forward"

        relation_enum = RELATION_MAP[relation_str]

        results.append(ConnectionClassification(
            candidate_id=candidate_id,
            relation=relation_enum,
            direction=direction,
            confidence=confidence,
            reasoning=reasoning,
        ))
        unclear.add(candidate_id)

    return ConnectionVerdicts(
        parsed=True, classifications=results, unrelated=none_ids - unclear,
    )


def _parse_belief_response(
    raw: str,
    beliefs: list["Belief"],
) -> list[BeliefEvaluation]:
    """Parse and validate belief evaluation response.

    Filters out NO_BEARING results — only meaningful changes are returned.
    """
    items = _extract_json(raw)
    valid_ids = {b.id for b in beliefs}
    results = []

    for item in items:
        try:
            belief_id = str(item.get("belief_id", ""))
            relation = str(item.get("relation", "")).upper()
            impact = float(item.get("impact", 0.0))
            reasoning = str(item.get("reasoning", ""))

            # Validate
            if belief_id not in valid_ids:
                log.debug("Skipping unknown belief_id: %s", belief_id)
                continue

            if relation not in ("SUPPORTS", "CONTRADICTS", "NO_BEARING"):
                log.warning("Invalid belief relation '%s' -- skipping", relation)
                continue

            # Filter out NO_BEARING (log only meaningful changes)
            if relation == "NO_BEARING":
                continue

            # Clamp impact to [0, 1]
            impact = max(0.0, min(1.0, impact))

            results.append(BeliefEvaluation(
                belief_id=belief_id,
                relation=relation,
                impact=impact,
                reasoning=reasoning,
            ))

        except (KeyError, ValueError, TypeError) as e:
            log.warning("Skipping malformed belief evaluation item: %s -- %s", item, e)
            continue

    return results
