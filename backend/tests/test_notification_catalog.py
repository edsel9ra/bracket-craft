"""Catálogo puro y registro de avisos (spec 046, T2: RF-001, RF-002, RF-006, RF-011)."""

from uuid import UUID

import pytest

from app.modules.notifications.catalog import (
    CHANNELS,
    DEFAULT_ENABLED,
    NOTIFICATION_TYPES,
    Preference,
    effective_preferences,
    email_message,
)
from app.modules.notifications.recorder import record_notification

TOURNAMENT = UUID("46000000-0000-4000-8000-000000000001")
MATCH = UUID("46000000-0000-4000-8000-000000000002")
SUSPENSION = UUID("46000000-0000-4000-8000-000000000003")
NOTICE = UUID("46000000-0000-4000-8000-000000000004")
BASE_URL = "https://app.example.test/"
LINK = "https://app.example.test/workspace/notifications"


def payload(kind, **overrides):
    base = {
        "recipient": "member@example.test",
        "notification_id": str(NOTICE),
        "type": kind,
        "tournament_name": "Copa Norte",
        "match_id": str(MATCH),
        "home_team_name": "Leones",
        "away_team_name": "Tigres",
        "match_count": None,
    }
    if kind == "match_scheduled":
        base.update(
            match_id=None, home_team_name=None, away_team_name=None, match_count=12
        )
    base.update(overrides)
    return base


def test_catalog_is_closed_and_ordered():
    assert NOTIFICATION_TYPES == (
        "match_scheduled",
        "result_confirmed",
        "walkover_declared",
        "sanction_generated",
    )
    assert CHANNELS == ("inbox", "email")
    assert DEFAULT_ENABLED == {"inbox": True, "email": False}


def test_catalog_matches_migration_067():
    from pathlib import Path

    sql = (
        Path(__file__).resolve().parents[2]
        / "infra/postgres/migrations/067_notifications.sql"
    ).read_text()
    quoted = ", ".join(f"'{kind}'" for kind in NOTIFICATION_TYPES)
    assert sql.count(f"({quoted})") == 2
    assert "channel IN ('inbox', 'email')" in sql


def test_effective_preferences_defaults_to_inbox_on_email_off():
    assert effective_preferences([]) == [
        Preference(kind, channel, channel == "inbox")
        for kind in NOTIFICATION_TYPES
        for channel in CHANNELS
    ]


def test_effective_preferences_uses_saved_values_and_ignores_unknown():
    saved = [
        {"notification_type": "result_confirmed", "channel": "email", "enabled": True},
        {
            "notification_type": "sanction_generated",
            "channel": "inbox",
            "enabled": False,
        },
        {"notification_type": "webhook_sent", "channel": "email", "enabled": True},
        {"notification_type": "match_scheduled", "channel": "sms", "enabled": True},
    ]
    result = {
        (p.notification_type, p.channel): p.enabled
        for p in effective_preferences(saved)
    }
    assert len(result) == len(NOTIFICATION_TYPES) * len(CHANNELS)
    assert result[("result_confirmed", "email")] is True
    assert result[("sanction_generated", "inbox")] is False
    assert result[("match_scheduled", "inbox")] is True
    assert result[("match_scheduled", "email")] is False


@pytest.mark.parametrize(
    ("kind", "spanish", "english"),
    [
        ("match_scheduled", "Partidos programados", "Matches scheduled"),
        ("result_confirmed", "Resultado confirmado", "Result confirmed"),
        ("walkover_declared", "W.O. declarado", "Walkover declared"),
        ("sanction_generated", "Sanción generada", "Sanction issued"),
    ],
)
def test_email_message_is_bilingual_with_tournament_and_link(kind, spanish, english):
    subject, body = email_message(payload(kind), BASE_URL)
    assert subject == f"{spanish} / {english} — Copa Norte — Bracket Craft"
    assert spanish in body and english in body
    assert "Copa Norte" in body
    assert body.count(LINK) == 1
    if kind == "match_scheduled":
        assert "12" in body and "Leones" not in body
    else:
        assert "Leones vs Tigres" in body


def test_email_message_never_names_a_player_or_leaks_extra_fields():
    data = payload(
        "sanction_generated",
        player_name="Juan Pérez",
        document="123",
        birth_date="2000-01-01",
    )
    subject, body = email_message(data, BASE_URL)
    for secret in ("Juan", "Pérez", "123", "2000-01-01", "member@example.test"):
        assert secret not in subject and secret not in body


def test_email_message_handles_undefined_teams_and_header_injection():
    subject, body = email_message(
        payload(
            "result_confirmed",
            home_team_name=None,
            away_team_name=None,
            tournament_name="Copa\r\nBcc: x@y",
        ),
        "https://app.example.test",
    )
    assert "\n" not in subject and "\r" not in subject
    assert "Por definir vs Por definir" in body and "TBD vs TBD" in body
    assert LINK in body


def test_email_message_rejects_unknown_type():
    with pytest.raises(ValueError, match="NOTIFICATION_TYPE_UNKNOWN"):
        email_message(payload("webhook_sent"), BASE_URL)


class FakeResult:
    def scalar_one(self):
        return NOTICE


class FakeSession:
    def __init__(self):
        self.calls = []

    async def execute(self, statement, params):
        self.calls.append((str(statement), params))
        return FakeResult()


async def test_record_calls_sql_function_in_the_same_session():
    db = FakeSession()
    notice = await record_notification(
        db,
        "sanction_generated",
        tournament_id=TOURNAMENT,
        match_id=MATCH,
        suspension_id=SUSPENSION,
    )
    assert notice == NOTICE
    [(statement, params)] = db.calls
    assert "record_notification(" in statement
    assert params == {
        "notification_type": "sanction_generated",
        "tournament_id": str(TOURNAMENT),
        "match_id": str(MATCH),
        "suspension_id": str(SUSPENSION),
        "match_count": None,
    }


async def test_record_schedule_passes_count_and_skips_empty_operations():
    db = FakeSession()
    assert (
        await record_notification(
            db, "match_scheduled", tournament_id=TOURNAMENT, match_count=0
        )
        is None
    )
    assert db.calls == []
    await record_notification(
        db, "match_scheduled", tournament_id=TOURNAMENT, match_count=7
    )
    assert db.calls[0][1] == {
        "notification_type": "match_scheduled",
        "tournament_id": str(TOURNAMENT),
        "match_id": None,
        "suspension_id": None,
        "match_count": 7,
    }


async def test_record_rejects_unknown_type_without_writing():
    db = FakeSession()
    with pytest.raises(ValueError, match="NOTIFICATION_TYPE_UNKNOWN"):
        await record_notification(db, "webhook_sent", tournament_id=TOURNAMENT)
    assert db.calls == []
