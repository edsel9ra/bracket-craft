"""Audit entries for team crest changes (RF-45, RF-46, RNF-7).

The module only decides and writes: ``crest_audit_action`` is pure and maps the
before/after object keys to the two catalog actions (or to no action at all) and
``record_crest_audit`` executes one ``INSERT`` inside the caller's transaction —
it never opens, commits or rolls back a transaction of its own.

The entry keeps identifiers and the action only: application audit rows name the
organisation member (``performed_by_member_id`` references ``organization_users``)
and never store the object key, the file name, the content type, the size or any
personal data. The tests use a recording session double, so no database is
needed.
"""

from __future__ import annotations

import inspect
import json
from uuid import UUID

import pytest

from app.modules.crests.audit import (
    REMOVE_TEAM_CREST,
    SET_TEAM_CREST,
    TEAM_ENTITY_TYPE,
    crest_audit_action,
    record_crest_audit,
)

ORG = UUID("0b000000-0000-4000-8000-000000000001")
MEMBER = UUID("0b000000-0000-4000-8000-000000000002")
TOURNAMENT = UUID("0b000000-0000-4000-8000-000000000010")
TEAM = UUID("0b000000-0000-4000-8000-000000000020")

PREVIOUS_KEY = "private/organizations/old/teams/team/crest/previous.webp"
NEW_KEY = "private/organizations/new/teams/team/crest/current.jpg"


class Transaction:
    """Transaction double: records whether the audit opened one."""

    def __init__(self) -> None:
        self.entered = 0
        self.exited = 0

    async def __aenter__(self) -> "Transaction":
        self.entered += 1
        return self

    async def __aexit__(self, *_exc_info) -> bool:
        self.exited += 1
        return False


class RecordingSession:
    """Async session double that records statements and never touches a DB."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []
        self.transactions: list[Transaction] = []
        self.begin_calls = 0

    def begin(self) -> Transaction:
        self.begin_calls += 1
        transaction = Transaction()
        self.transactions.append(transaction)
        return transaction

    async def execute(self, statement, params=None):
        self.calls.append((" ".join(str(statement).split()), dict(params or {})))
        return None


# ---------------------------------------------------------------------------
# Pure transition: load, replace, remove and no effective change
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("before", "after", "expected"),
    [
        (None, NEW_KEY, SET_TEAM_CREST),  # first upload
        (PREVIOUS_KEY, NEW_KEY, SET_TEAM_CREST),  # replacement
        (NEW_KEY, NEW_KEY, SET_TEAM_CREST),  # a new key is a new image
        (PREVIOUS_KEY, None, REMOVE_TEAM_CREST),  # deletion with an image
        (None, None, None),  # deletion without an image: nothing to audit
    ],
)
def test_crest_audit_action_maps_the_transition(before, after, expected):
    assert crest_audit_action(before, after) == expected


def test_crest_audit_actions_are_the_two_catalog_names():
    assert SET_TEAM_CREST == "SET_TEAM_CREST"
    assert REMOVE_TEAM_CREST == "REMOVE_TEAM_CREST"
    assert TEAM_ENTITY_TYPE == "teams"


# ---------------------------------------------------------------------------
# One INSERT inside the caller's transaction
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("before", "after"),
    [(None, NEW_KEY), (PREVIOUS_KEY, NEW_KEY), (PREVIOUS_KEY, None)],
)
async def test_record_crest_audit_inserts_one_entry_without_opening_a_transaction(
    before, after
):
    session = RecordingSession()
    action = crest_audit_action(before, after)
    assert action is not None

    await record_crest_audit(
        session,
        organization_id=ORG,
        member_id=MEMBER,
        tournament_id=TOURNAMENT,
        team_id=TEAM,
        action=action,
    )

    # Exactly one INSERT, in the caller's transaction: no begin/commit/rollback.
    assert session.begin_calls == 0
    assert session.transactions == []
    assert len(session.calls) == 1

    sql, params = session.calls[0]
    assert sql.startswith("INSERT INTO administrative_audit_logs")
    assert "VALUES" in sql

    assert params == {
        "organization_id": str(ORG),
        "entity_type": "teams",
        "entity_id": str(TEAM),
        "action": action,
        "payload": json.dumps({"tournament_id": str(TOURNAMENT)}),
        "member_id": str(MEMBER),
    }
    assert json.loads(params["payload"]) == {"tournament_id": str(TOURNAMENT)}


@pytest.mark.asyncio
async def test_record_crest_audit_payload_has_only_the_tournament_identifier():
    session = RecordingSession()

    await record_crest_audit(
        session,
        organization_id=ORG,
        member_id=MEMBER,
        tournament_id=TOURNAMENT,
        team_id=TEAM,
        action=SET_TEAM_CREST,
    )

    sql, params = session.calls[0]
    payload = json.loads(params["payload"])
    assert list(payload) == ["tournament_id"]

    # No object key, file name, detected type or size anywhere in the entry.
    serialized = f"{sql} {json.dumps(params)}".lower()
    for forbidden in (
        "crest_object_key",
        "logo_url",
        "private/",
        ".jpg",
        ".png",
        ".webp",
        "image/",
        "filename",
        "file_name",
        "content_type",
        "size",
        "bytes",
        "first_name",
        "last_name",
        "national_id",
        "birth_date",
    ):
        assert forbidden not in serialized
    assert "private/" not in params["payload"]
    assert NEW_KEY not in params["payload"]


@pytest.mark.asyncio
@pytest.mark.parametrize("action", (None, "", "SET_CREST", "REMOVE"))
async def test_record_crest_audit_refuses_a_non_effective_action(action):
    session = RecordingSession()

    with pytest.raises(ValueError):
        await record_crest_audit(
            session,
            organization_id=ORG,
            member_id=MEMBER,
            tournament_id=TOURNAMENT,
            team_id=TEAM,
            action=action,
        )

    # Deletion without an image (``crest_audit_action(None, None)`` is None)
    # cannot leave an entry: nothing is written.
    assert session.calls == []
    assert session.begin_calls == 0


# ---------------------------------------------------------------------------
# Signature contract: the caller owns the transaction and the actor is a member
# ---------------------------------------------------------------------------


def test_record_crest_audit_signature_is_keyword_only_and_receives_the_context():
    signature = inspect.signature(record_crest_audit)
    parameters = signature.parameters

    assert list(parameters)[0] == "db"
    assert parameters["db"].kind is inspect.Parameter.POSITIONAL_OR_KEYWORD
    for name in (
        "organization_id",
        "member_id",
        "tournament_id",
        "team_id",
        "action",
    ):
        assert parameters[name].kind is inspect.Parameter.KEYWORD_ONLY, name

    # The actor is the organisation member the audit table references; the auth
    # ``user_id`` is not accepted because it is not what ``performed_by_member_id``
    # stores.
    assert "user_id" not in parameters
