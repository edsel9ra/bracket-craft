"""Organisational audit for match operations (R25 / RF-008).

Three operations leave one entry in ``administrative_audit_logs``: saving the
lineup of a segment, publishing or unpublishing the formation of a team and
assigning or removing a match official. The entry depends on the **state
transition** (the content of the lineup changed, the publication flag flipped,
the official was effectively added or removed), never on a timestamp rewrite,
so repeating an identical request adds nothing.

The payload keeps identifiers, role and action codes and counters: never names,
e-mails, documents or the content of the lineup. ``record_match_audit`` only
executes the ``INSERT``; the caller runs it inside its own transaction, so a
failed or reverted action leaves no entry.
"""

from __future__ import annotations

import json
from hashlib import sha256
from typing import Any, Iterable
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

MATCH_ENTITY_TYPE = "matches"

SAVE_MATCH_LINEUP = "SAVE_MATCH_LINEUP"
PUBLISH_MATCH_LINEUP = "PUBLISH_MATCH_LINEUP"
UNPUBLISH_MATCH_LINEUP = "UNPUBLISH_MATCH_LINEUP"
ASSIGN_MATCH_OFFICIAL = "ASSIGN_MATCH_OFFICIAL"
REMOVE_MATCH_OFFICIAL = "REMOVE_MATCH_OFFICIAL"

# team_id, roster_id, player_id, role, position_slot, entered_minute, left_minute
LineupEntry = tuple[UUID, UUID, UUID, str, str | None, int | None, int | None]


def _entry_key(entry: LineupEntry) -> str:
    return "|".join("" if value is None else str(value) for value in entry)


def lineup_signature(
    formations: Iterable[tuple[UUID, str]],
    entries: Iterable[LineupEntry],
) -> str:
    """Return a stable, order-independent fingerprint of a lineup.

    The request may list the same players in any order, so both the formations
    and the entries are normalised before comparing. The signature covers what
    changes the lineup: the formation of each team and every roster entry with
    its role, position and minutes.
    """

    normalized_formations = sorted(
        f"{team_id}|{formation_code}" for team_id, formation_code in formations
    )
    normalized_entries = sorted(_entry_key(entry) for entry in entries)
    return json.dumps(
        {"formations": normalized_formations, "entries": normalized_entries},
        sort_keys=True,
        separators=(",", ":"),
    )


def lineup_audit_action(before: str, after: str) -> str | None:
    """Action to record when the lineup content changes, ``None`` otherwise."""

    return SAVE_MATCH_LINEUP if before != after else None


def publication_audit_action(before: bool, after: bool) -> str | None:
    """Action to record for a publication transition, ``None`` when it repeats."""

    if bool(before) == bool(after):
        return None
    return PUBLISH_MATCH_LINEUP if after else UNPUBLISH_MATCH_LINEUP


def lineup_content_summary(
    formations: Iterable[tuple[UUID, str]],
    entries: Iterable[LineupEntry],
) -> dict[str, Any]:
    """Counts and codes for the audit payload, plus a digest instead of content."""

    formation_list = list(formations)
    entry_list = list(entries)
    return {
        "teams": len({team_id for team_id, _ in formation_list}),
        "formations": {
            str(team_id): formation_code for team_id, formation_code in formation_list
        },
        "entries": len(entry_list),
        "starters": sum(1 for entry in entry_list if entry[3] == "starter"),
        "substitutes": sum(1 for entry in entry_list if entry[3] == "substitute"),
        "content_digest": sha256(
            lineup_signature(formation_list, entry_list).encode("utf-8")
        ).hexdigest(),
    }


async def record_match_audit(
    db: AsyncSession,
    *,
    organization_id: UUID,
    member_id: UUID,
    match_id: UUID,
    action: str,
    payload: dict[str, Any],
) -> None:
    """Insert one audit entry inside the caller's transaction."""

    await db.execute(
        text("""
            INSERT INTO administrative_audit_logs
                (organization_id, entity_type, entity_id, action, payload,
                 performed_by_member_id)
            VALUES (
                :organization_id,
                :entity_type,
                :entity_id,
                :action,
                CAST(:payload AS jsonb),
                :member_id
            )
        """),
        {
            "organization_id": str(organization_id),
            "entity_type": MATCH_ENTITY_TYPE,
            "entity_id": str(match_id),
            "action": action,
            "payload": json.dumps(payload, default=str),
            "member_id": str(member_id),
        },
    )
