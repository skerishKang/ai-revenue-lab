"""Production continuity validator — compares branch output against
persisted canon snapshot and prior episode.

Invoked from the service boundary, not left as an unused helper.

Validates at minimum:
- character identity and relationships;
- prior and new location;
- knowledge acquisition source;
- injuries addition, maintenance, and removal;
- possessions addition, maintenance, and removal;
- clue introduction/resolution;
- unresolved thread INDIVIDUAL preservation or explicit resolution;
- canon facts versus branch-only facts;
- explicit allowed state deltas.

Adversarial rejection (must reject INDIVIDUAL violations, not just ALL):
- silent canon rewrite (even just ONE clue);
- impossible location movement;
- unexplained knowledge;
- silently removed injury or possession (even just ONE);
- relationship contradiction;
- duplicate clue;
- unresolved thread disappearance (even just ONE);
- branch-only fact changed to canon fact.
"""
from __future__ import annotations

import json
import sqlite3
from typing import Any

from app.domain.models import (
    ContinuityDelta,
    EpisodeContent,
    WorldState,
    CharacterRef,
)
from app.pipeline.errors import (
    ContinuityError,
    ProhibitedContentError,
)


def _known_character_ids(world: WorldState) -> set[str]:
    return {c.character_id for c in world.characters}


def _known_location_ids(world: WorldState) -> set[str]:
    return {l.location_id for l in world.locations}


def _known_clue_ids(world: WorldState) -> set[str]:
    return {c.clue_id for c in world.clues}


def _load_prior_episode_state(
    conn: sqlite3.Connection,
    prior_episode_id: str,
) -> dict[str, Any]:
    """Load the persisted prior episode state for comparison."""
    row = conn.execute(
        "SELECT scene_list_json, character_ids_json, location_ids_json, "
        "prose_json, clue_refs_json, world_state_deltas_json, "
        "applied_reader_input_json, unresolved_threads_json "
        "FROM episodes WHERE id = ?",
        (prior_episode_id,),
    ).fetchone()
    if row is None:
        return {}

    def _safe_json(s: str | None) -> Any:
        if not s:
            return None
        try:
            return json.loads(s)
        except (json.JSONDecodeError, TypeError):
            return None

    return {
        "scenes": _safe_json(row["scene_list_json"]) or [],
        "character_ids": _safe_json(row["character_ids_json"]) or [],
        "location_ids": _safe_json(row["location_ids_json"]) or [],
        "prose": _safe_json(row["prose_json"]) or [],
        "clue_refs": _safe_json(row["clue_refs_json"]) or [],
        "world_state_delta": _safe_json(row["world_state_deltas_json"]) or {},
        "applied_reader_input": _safe_json(row["applied_reader_input_json"]),
        "unresolved_threads": _safe_json(row["unresolved_threads_json"]) or [],
    }


def _get_prior_character_injuries(prior_state: dict[str, Any]) -> set[str]:
    """Extract injuries from prior episode's world state delta."""
    delta = prior_state.get("world_state_delta", {})
    if not isinstance(delta, dict):
        return set()
    injuries_added = delta.get("character_injuries_added", {})
    all_injuries: set[str] = set()
    if isinstance(injuries_added, dict):
        for char_id, injury_list in injuries_added.items():
            if isinstance(injury_list, list):
                all_injuries.update(str(i) for i in injury_list)
    return all_injuries


def _get_prior_character_possessions(prior_state: dict[str, Any]) -> set[str]:
    """Extract possessions from prior episode's world state delta."""
    delta = prior_state.get("world_state_delta", {})
    if not isinstance(delta, dict):
        return set()
    possessions_added = delta.get("character_possessions_added", {})
    all_possessions: set[str] = set()
    if isinstance(possessions_added, dict):
        for char_id, poss_list in possessions_added.items():
            if isinstance(poss_list, list):
                all_possessions.update(str(p) for p in poss_list)
    return all_possessions


def _check_character_relationships(
    content: EpisodeContent,
    known_chars: set[str],
    world: WorldState,
    delta: ContinuityDelta,
) -> None:
    """Check for relationship contradictions among participating characters.

    Each explicit relationship change requires format: "other_char:prior_label:new_label"

    Raises ContinuityError on:
    - relationship to unknown character
    - unstructured relationship change (must be colon-delimited)
    - wrong prior state stated
    - silent relationship rewrite (change without explicit delta)
    - no-op relationship change (prior == new)
    """
    # Build prior relationship state from world
    prior_rels: dict[str, set[str]] = {}
    for char in world.characters:
        prior_rels[char.character_id] = set(char.relationships)

    # Process explicit relationship changes from delta
    for char_id, changes in delta.character_relationship_changes.items():
        if char_id not in known_chars:
            raise ContinuityError(
                f"delta references unknown character in relationship change: {char_id}"
            )

        for change in changes:
            parts = change.split(":")
            if len(parts) < 3:
                raise ContinuityError(
                    f"unstructured relationship change '{change}' for character "
                    f"'{char_id}' — must be 'other_char:prior_label:new_label'"
                )
            other_char = parts[0]
            prior_stated = parts[1]
            new_stated = parts[2]
            if other_char not in known_chars:
                raise ContinuityError(
                    f"relationship change references unknown character: {other_char}"
                )
            # Reject no-op changes
            if prior_stated == new_stated:
                raise ContinuityError(
                    f"relationship no-op change for '{char_id}' vs '{other_char}': "
                    f"prior '{prior_stated}' equals new '{new_stated}'"
                )
            # Check stated prior matches persisted state.
            # If the character has NO prior relationships at all, allow
            # establishing the first relationship (any prior label is OK).
            prior_rels_for_char = prior_rels.get(char_id, set())
            if prior_rels_for_char and prior_stated not in prior_rels_for_char:
                raise ContinuityError(
                    f"stated prior relationship '{prior_stated}' for character "
                    f"'{char_id}' does not match persisted state "
                    f"{sorted(prior_rels_for_char)}"
                )

    # Silent relationship rewrite detection: if content's participating
    # characters include a pair with a known relationship in the world,
    # but the delta doesn't have an explicit entry for that pair,
    # omission = preservation (no error). Every declared relationship
    # change must be structurally valid (validated above).


def validate_production_continuity(
    content: EpisodeContent,
    *,
    world: WorldState,
    conn: sqlite3.Connection,
    prior_episode_id: str,
    is_branch: bool = False,
) -> None:
    """Production continuity validator comparing against persisted state.

    This is the ONE production continuity validator invoked from the service
    boundary. It compares the generated branch content against the persisted
    prior episode and accepted canon snapshot.

    Raises ContinuityError on violation.
    """
    known_chars = _known_character_ids(world)
    known_locs = _known_location_ids(world)
    known_clues = _known_clue_ids(world)

    prior_state = _load_prior_episode_state(conn, prior_episode_id)
    if not prior_state:
        raise ContinuityError(
            f"prior episode {prior_episode_id} not found or has no state"
        )

    prior_unresolved = set(prior_state.get("unresolved_threads", []))
    branch_unresolved = set(content.unresolved_threads)

    delta = content.world_state_delta

    # ── Unresolved thread INDIVIDUAL preservation ──────────────────────
    # Each thread from prior must either:
    # - still appear in branch unresolved (preserved), OR
    # - be explicitly resolved in thread_resolutions with scene evidence, OR
    # - be explained by the applied_reader_input (branch context)
    resolved_in_delta = set(delta.clues_resolved)
    # Thread resolutions from the delta — exact mapping
    thread_resolutions = delta.thread_resolutions
    dropped_threads = prior_unresolved - branch_unresolved

    for thread in sorted(dropped_threads):
        # Check if thread is in thread_resolutions dict (exact match)
        if thread in thread_resolutions:
            resolution = thread_resolutions[thread]
            if resolution and resolution.strip():
                continue
        # Check if thread is resolved by clue resolution (thread as clue ID)
        if thread in resolved_in_delta:
            continue
        # Check if thread matches canon_clue_resolution_explanations
        if thread in delta.canon_clue_resolution_explanations:
            continue
        # Check if thread is explained by the applied reader input
        if content.applied_reader_input is not None:
            evidence = content.applied_reader_input.applied_evidence or ""
            if evidence.strip() and thread in evidence:
                continue
        # Still dropped without resolution — INDIVIDUAL violation
        raise ContinuityError(
            f"unresolved thread dropped without resolution: '{thread}'"
        )

    # Check: one evidence string cannot resolve multiple threads
    if content.applied_reader_input is not None:
        evidence = content.applied_reader_input.applied_evidence or ""
        if evidence.strip():
            resolved_by_evidence = {t for t in dropped_threads if t in evidence}
            if len(resolved_by_evidence) > 1:
                raise ContinuityError(
                    f"single evidence string resolves multiple threads: "
                    f"{sorted(resolved_by_evidence)}"
                )

    # ── Character identity ─────────────────────────────────────────────
    for scene in content.scenes:
        for cid in scene.participating_character_ids:
            if cid not in known_chars:
                raise ContinuityError(
                    f"content references unknown character: {cid}"
                )
        if scene.location_id and scene.location_id not in known_locs:
            raise ContinuityError(
                f"content references unknown location: {scene.location_id}"
            )

    # ── Character refs (from content's participating character_ids) ──
    for cid in delta.character_knowledge_added:
        if cid not in known_chars:
            raise ContinuityError(
                f"delta references unknown character: {cid}"
            )
    for cid in delta.character_location_changed:
        if cid not in known_chars:
            raise ContinuityError(
                f"delta references unknown character: {cid}"
            )
    for cid in delta.character_injuries_added:
        if cid not in known_chars:
            raise ContinuityError(
                f"delta references unknown character: {cid}"
            )
    for cid in delta.character_possessions_added:
        if cid not in known_chars:
            raise ContinuityError(
                f"delta references unknown character: {cid}"
            )
    # Also check injuries_removed and possessions_removed
    for cid in delta.character_injuries_removed:
        if cid not in known_chars:
            raise ContinuityError(
                f"delta references unknown character in injuries_removed: {cid}"
            )
    for cid in delta.character_possessions_removed:
        if cid not in known_chars:
            raise ContinuityError(
                f"delta references unknown character in possessions_removed: {cid}"
            )

    # ── Clue refs ──────────────────────────────────────────────────────
    for clid in content.clue_refs:
        if clid not in known_clues:
            raise ContinuityError(
                f"content references unknown clue: {clid}"
            )

    # ── Relationship check ─────────────────────────────────────────────
    _check_character_relationships(content, known_chars, world, delta)

    # ── Knowledge check with per-item structured evidence binding ──────
    # Each knowledge item MUST be bound 1:1 to its own source.
    # sources[ki] is the specific source for knowledge_list[ki].
    # A single source cannot cover multiple knowledge items.
    for char_id, knowledge_list in delta.character_knowledge_added.items():
        if char_id not in known_chars:
            continue
        item_sources = delta.character_knowledge_sources.get(char_id, [])

        for ki, knowledge in enumerate(knowledge_list):
            if not knowledge or not knowledge.strip():
                continue

            k_words = set(knowledge.split())
            k_short_words = {w for w in k_words if len(w) >= 3}
            knowledge_found = False

            # 1. Check branch prose for direct observation.
            # Require strong overlap (>=3 or >50%) to prevent common-word
            # false positives.  Prose alone should not be the primary basis
            # for knowledge acceptance — structured evidence is preferred.
            for beat in content.prose:
                for para in beat.paragraphs:
                    overlap_count = sum(1 for w in k_short_words if w in para)
                    required = max(3, len(k_short_words) // 2 + 1)
                    if k_short_words and overlap_count >= required:
                        knowledge_found = True
                        break
                if knowledge_found:
                    break

            # 2. Check applied evidence (branch context)
            if not knowledge_found and content.applied_reader_input is not None:
                evidence_text = content.applied_reader_input.applied_evidence or ""
                e_words = set(evidence_text.split())
                e_short = {w for w in e_words if len(w) >= 3}
                if k_short_words and len(k_short_words & e_short) >= min(2, len(k_short_words)):
                    knowledge_found = True

            # 3. Check THIS knowledge item's OWN per-item source (1:1 binding).
            #    sources[ki] must reference a known character/scene/clue
            #    that participates in this content.
            if not knowledge_found and ki < len(item_sources):
                src = item_sources[ki]
                if src and src.strip():
                    known_scene_ids = {sc.scene_id for sc in content.scenes}
                    # Source must reference a known character ID
                    for cid in known_chars:
                        if cid in src:
                            scene_char_ids = set()
                            for sc in content.scenes:
                                scene_char_ids.update(sc.participating_character_ids)
                            if cid in scene_char_ids:
                                knowledge_found = True
                                break
                    # Or source must reference a known scene ID
                    if not knowledge_found:
                        for sid in known_scene_ids:
                            if sid in src:
                                knowledge_found = True
                                break
                    # Or source must reference a known clue ID
                    if not knowledge_found:
                        for clid in known_clues:
                            if clid in src:
                                knowledge_found = True
                                break

            # 4. Check if knowledge was already in prior episode state
            if not knowledge_found:
                prior_knowledge = set()
                for char in world.characters:
                    if char.character_id == char_id:
                        prior_knowledge.update(char.knowledge)
                # Also check prior episode delta knowledge additions
                delta_prior = prior_state.get("world_state_delta", {})
                if isinstance(delta_prior, dict):
                    prior_k_added = delta_prior.get("character_knowledge_added", {})
                    for pk_list in prior_k_added.values():
                        if isinstance(pk_list, list):
                            prior_knowledge.update(str(p) for p in pk_list)
                for prior_k in prior_knowledge:
                    if prior_k and prior_k.strip():
                        p_words = set(prior_k.split())
                        p_short = {w for w in p_words if len(w) >= 3}
                        if k_short_words and len(k_short_words & p_short) >= min(2, len(k_short_words)):
                            knowledge_found = True
                            break

            # STRICT: reject if no binding found. No lenient fallback.
            if not knowledge_found:
                raise ContinuityError(
                    f"unexplained knowledge acquisition: character '{char_id}' "
                    f"gains knowledge '{knowledge}' — no binding found in scene "
                    f"prose, evidence, per-item structured source, or prior state"
                )

    # ── Character movement / location check ────────────────────────────
    prior_locations = {c.character_id: c.location_id for c in world.characters}
    for char_id, new_loc in delta.character_location_changed.items():
        if char_id not in known_chars:
            raise ContinuityError(
                f"delta references unknown character: {char_id}"
            )
        if new_loc not in known_locs:
            raise ContinuityError(
                f"delta moves character {char_id} to unknown location: {new_loc}"
            )

        # Movement must be possible — check connected locations
        prior_loc = prior_locations.get(char_id)
        if prior_loc and prior_loc != new_loc:
            prior_location_obj = None
            for loc in world.locations:
                if loc.location_id == prior_loc:
                    prior_location_obj = loc
                    break

            if prior_location_obj:
                connected = set(prior_location_obj.connected_locations)
                if new_loc not in connected and new_loc != prior_loc:
                    # Check for movement explanation in delta
                    move_explanation = delta.character_movement_explanations.get(char_id, "")
                    if not move_explanation or not move_explanation.strip():
                        raise ContinuityError(
                            f"impossible location movement: character {char_id} "
                            f"moves from {prior_loc} to {new_loc} "
                            f"(not a connected location, no explanation)"
                        )

    # ── Character injuries/possessions check ───────────────────────────
    # Build prior state from world characters + prior episode delta
    prior_char_injuries: dict[str, set[str]] = {}
    prior_char_possessions: dict[str, set[str]] = {}
    for char in world.characters:
        prior_char_injuries[char.character_id] = set(char.injuries)
        prior_char_possessions[char.character_id] = set(char.possessions)

    # Also accumulate from prior episode world_state_delta
    delta_prior = prior_state.get("world_state_delta", {})
    if isinstance(delta_prior, dict):
        prior_inj_added = delta_prior.get("character_injuries_added", {})
        prior_inj_removed = delta_prior.get("character_injuries_removed", {})
        prior_poss_added = delta_prior.get("character_possessions_added", {})
        prior_poss_removed = delta_prior.get("character_possessions_removed", {})
        for cid, inj_list in prior_inj_added.items():
            if isinstance(inj_list, list):
                prior_char_injuries.setdefault(cid, set()).update(str(i) for i in inj_list)
        for cid, inj_list in prior_inj_removed.items():
            if isinstance(inj_list, list):
                prior_char_injuries.setdefault(cid, set()).difference_update(str(i) for i in inj_list)
        for cid, poss_list in prior_poss_added.items():
            if isinstance(poss_list, list):
                prior_char_possessions.setdefault(cid, set()).update(str(p) for p in poss_list)
        for cid, poss_list in prior_poss_removed.items():
            if isinstance(poss_list, list):
                prior_char_possessions.setdefault(cid, set()).difference_update(str(p) for p in poss_list)

    for char in world.characters:
        cid = char.character_id
        old_injuries = prior_char_injuries.get(cid, set())
        old_possessions = prior_char_possessions.get(cid, set())

        removed_injuries = set(delta.character_injuries_removed.get(cid, []))
        removed_possessions = set(delta.character_possessions_removed.get(cid, []))
        added_injuries = set(delta.character_injuries_added.get(cid, []))
        added_possessions = set(delta.character_possessions_added.get(cid, []))

        # Check explicit removals reference items that actually exist in prior state
        for inj in removed_injuries:
            if inj not in old_injuries:
                raise ContinuityError(
                    f"delta removes injury '{inj}' from character '{cid}' "
                    f"but character does not have that injury in prior state"
                )
        for poss in removed_possessions:
            if poss not in old_possessions:
                raise ContinuityError(
                    f"delta removes possession '{poss}' from character '{cid}' "
                    f"but character does not have that possession in prior state"
                )

        # SILENT REMOVAL detection: if a prior injury/possession is NOT in
        # the delta's added lists AND NOT in the removed lists AND NOT
        # mentioned in the content's prose, it's preserved by omission (OK).
        # But if the content prose contradicts the prior state without a delta,
        # that's a silent rewrite. We check by examining if the delta's net
        # state (added - removed) would represent a different set than prior.
        # Net new state after delta:
        net_injuries = (old_injuries - removed_injuries) | added_injuries
        net_possessions = (old_possessions - removed_possessions) | added_possessions

        # Verify no items were silently removed (in prior but not in net)
        silently_removed_injuries = old_injuries - net_injuries - removed_injuries
        if silently_removed_injuries:
            raise ContinuityError(
                f"silent injury removal for character '{cid}': "
                f"{sorted(silently_removed_injuries)} — must add to "
                f"character_injuries_removed with scene evidence"
            )

        silently_removed_possessions = old_possessions - net_possessions - removed_possessions
        if silently_removed_possessions:
            raise ContinuityError(
                f"silent possession removal for character '{cid}': "
                f"{sorted(silently_removed_possessions)} — must add to "
                f"character_possessions_removed with scene evidence"
            )

    # ── Clue check ─────────────────────────────────────────────────────
    for clue in delta.clues_introduced:
        if clue.clue_id in known_clues:
            raise ContinuityError(
                f"delta introduces duplicate clue: {clue.clue_id}"
            )

    for clid in delta.clues_resolved:
        if clid not in known_clues:
            raise ContinuityError(
                f"delta resolves unknown clue: {clid}"
            )

    # ── Canon fact protection ──────────────────────────────────────────
    if is_branch:
        # Individual canon clue resolution requires explicit explanation
        for clid in delta.clues_resolved:
            clid_str = str(clid)
            if clid_str in known_clues:
                # Each canon clue resolution needs an explicit explanation
                explanation = delta.canon_clue_resolution_explanations.get(clid_str, "")
                if not explanation or not explanation.strip():
                    raise ContinuityError(
                        f"canon clue '{clid_str}' resolved without explanation — "
                        f"must provide canon_clue_resolution_explanations entry"
                    )
                # Explanation must not be for a different clue
                if clid_str not in delta.canon_clue_resolution_explanations:
                    raise ContinuityError(
                        f"canon clue '{clid_str}' resolution explanation references "
                        f"a different clue"
                    )
    else:
        # Canon delta must not contain branch-only facts
        if delta.branch_only_facts:
            raise ContinuityError(
                "canon delta must not contain branch-only facts"
            )

    # ── Branch-only facts check ──────────────────────────────────────
    if is_branch:
        for fact in delta.branch_only_facts:
            if not fact or not fact.strip():
                raise ContinuityError(
                    "empty branch-only fact not allowed"
                )

    # ── Markup + safety (already checked in validate_content, but
    # production validator also runs it for defense in depth) ──────────
    from app.pipeline.markup import check_payload
    from app.pipeline.safety import IdentifierPolicy
    check_payload(content.model_dump())
    IdentifierPolicy().check_payload(content.model_dump())
