"""Catálogo cerrado de la auditoría organizacional (spec 041, T2, RF-007 y RF-008)."""

import re
from pathlib import Path

import pytest

from app.modules.organization_audit.catalog import (
    CATALOG,
    FORBIDDEN_PATH_PARTS,
    TEXT_LIMIT,
    assert_catalog_safe,
    project_details,
    referenced_member_ids,
)

ROOT = Path(__file__).resolve().parents[2]
MEMBER = "6f1f8b1e-0000-4000-8000-000000000001"
STRANGER = "6f1f8b1e-0000-4000-8000-000000000002"


def as_dict(details):
    return {item["key"]: item["value"] for item in details}


def test_close_match_report_projects_declared_fields_only():
    payload = {
        "previous_status": "live", "final_status": "finished",
        "tournament_version_id": "v", "event_ids": ["e1"],
        "outcome": {"home_score": 2, "away_score": 1, "winner_team_id": "t"},
        "suspensions": 1,
        "request": {"resolution_type": "regular", "reason": None, "events": [{"player_id": "p"}]},
    }
    assert as_dict(project_details("CLOSE_MATCH_REPORT", payload, {})) == {
        "previous_status": "live", "final_status": "finished", "resolution_type": "regular",
        "home_score": 2, "away_score": 1, "suspensions": 1,
    }


def test_walkover_and_administrative_resolution_show_reason():
    walkover = {"previous_status": "scheduled", "final_status": "finished",
                "outcome": {"home_score": 3, "away_score": 0}, "suspensions": 0,
                "request": {"resolution_type": "walkover", "reason": "no_show"}}
    details = as_dict(project_details("CLOSE_MATCH_REPORT", walkover, {}))
    assert details["reason"] == "no_show" and details["resolution_type"] == "walkover"
    administrative = {"request": {"resolution_type": "administrative", "reason": "Fallo del comité"}}
    assert as_dict(project_details("ADMINISTRATIVE_MATCH_RESOLUTION", administrative, {})) == {
        "resolution_type": "administrative", "reason": "Fallo del comité",
    }


@pytest.mark.parametrize(("action", "payload", "expected"), [
    ("INTERRUPT_MATCH_SEGMENT", {"segment_id": "s", "reason": "weather", "minute": 30, "notes": "Lluvia"},
     {"reason": "weather", "minute": 30, "notes": "Lluvia"}),
    ("MATCH_LIVE_COMMAND", {"command_id": "c", "type": "goal", "revision": 4}, {"type": "goal", "revision": 4}),
    ("SAVE_MATCH_LINEUP", {"segment_id": "s", "teams": 2, "formations": {"x": "4-4-2"}, "entries": 22,
                           "starters": 11, "substitutes": 11, "content_digest": "abc"},
     {"teams": 2, "entries": 22, "starters": 11, "substitutes": 11}),
    ("PUBLISH_MATCH_LINEUP", {"team_id": "t", "is_public": True, "formation_code": "4-4-2"}, {"is_public": True}),
    ("UNPUBLISH_MATCH_LINEUP", {"is_public": False}, {"is_public": False}),
    ("REQUEST_MATCH_REPORT_RECTIFICATION", {"request_id": "r", "base_version_number": 2}, {"base_version_number": 2}),
    ("DECIDE_MATCH_REPORT_RECTIFICATION", {"request_id": "r", "decision": "approve", "version_id": "v"},
     {"decision": "approve"}),
    ("DECIDE_SANCTION_CASE", {"decision_id": "d", "authorization_id": "a", "decision": "annul"}, {"decision": "annul"}),
    ("OPEN_COMPETITIVE_IMPACT", {"version_id": "v", "resolution": None}, {}),
    ("CLOSE_COMPETITIVE_IMPACT", {"version_id": "v", "resolution": "keep_as_played"},
     {"resolution": "keep_as_played"}),
    ("CHANGE_MEMBER_ROLE", {"role_code": "operator"}, {"role_code": "operator"}),
    ("SET_MEMBER_ACTIVE", {"is_active": False}, {"is_active": False}),
    ("ACCEPT_INVITATION", {"user_id": "u", "role_code": "viewer"}, {"role_code": "viewer"}),
    ("REOPEN_INVITATION", {"previous_status": "revoked", "role_code": "viewer"},
     {"previous_status": "revoked", "role_code": "viewer"}),
    ("GRANT_RECTIFICATION_AUTHORIZATION", {"request_id": "r", "authorization_id": "a",
                                           "platform_admin_user_id": "p"}, {}),
    ("REVOKE_RECTIFICATION_AUTHORIZATION", {"authorization_id": "a"}, {}),
    ("GRANT_SANCTION_AUTHORIZATION", {"authorization_id": "a", "platform_admin_user_id": "p"}, {}),
    ("REVOKE_SANCTION_AUTHORIZATION", {"authorization_id": "a", "platform_admin_user_id": "p"}, {}),
    ("SET_TEAM_CREST", {"tournament_id": "t"}, {}),
    ("REMOVE_TEAM_CREST", {"tournament_id": "t"}, {}),
    ("STAGE_SLOTS_RESOLVED", {"tournament_id": "t", "version_id": "v", "stage_id": "s"}, {}),
    ("CREATE_WEBHOOK", {"host": "hooks.example.com", "event_types": ["match_scheduled", "result_confirmed"],
                        "is_active": True},
     {"host": "hooks.example.com", "event_types": "match_scheduled,result_confirmed", "is_active": True}),
    ("UPDATE_WEBHOOK", {"host": "h.example", "event_types": ["x" * 65], "is_active": False},
     {"host": "h.example", "is_active": False}),
    ("SET_WEBHOOK_ACTIVE", {"host": "h.example", "event_types": [], "is_active": True},
     {"host": "h.example", "is_active": True}),
    ("ROTATE_WEBHOOK_SECRET", {"host": "h.example", "secret": "whsec_x"}, {"host": "h.example"}),
    ("DELETE_WEBHOOK", {"host": "h.example", "url": "https://h.example/p"}, {"host": "h.example"}),
    ("EXPORT_TOURNAMENT_ROSTERS", {"row_count": 12, "players": ["Ana Ruiz"]}, {"row_count": 12}),
    ("ASSIGN_TOURNAMENT_OPERATOR", {"organization_user_id": MEMBER, "role_code": "tournament_operator",
                                    "email": "ana@example.test"}, {"member": "Ana Ruiz", "role_code": "tournament_operator"}),
    ("REMOVE_TOURNAMENT_OPERATOR", {"organization_user_id": STRANGER, "role_code": "tournament_operator"},
     {"role_code": "tournament_operator"}),
])
def test_projection_per_action(action, payload, expected):
    assert as_dict(project_details(action, payload, {MEMBER: "Ana Ruiz"})) == expected


def test_member_fields_use_member_names_and_skip_foreign_ids():
    payload = {"organization_user_id": MEMBER, "official_role": "referee"}
    assert referenced_member_ids("ASSIGN_MATCH_OFFICIAL", payload) == {MEMBER}
    assert as_dict(project_details("ASSIGN_MATCH_OFFICIAL", payload, {MEMBER: "Ana Ruiz"})) == {
        "member": "Ana Ruiz", "official_role": "referee",
    }
    foreign = {"organization_user_id": STRANGER, "official_role": "referee"}
    assert as_dict(project_details("REMOVE_MATCH_OFFICIAL", foreign, {MEMBER: "Ana Ruiz"})) == {
        "official_role": "referee",
    }
    assert referenced_member_ids("CHANGE_MEMBER_ROLE", {"role_code": "viewer"}) == set()
    assert referenced_member_ids("UNKNOWN_ACTION", {"organization_user_id": MEMBER}) == set()


def test_projection_keeps_declared_order():
    payload = {"notes": "n", "minute": 3, "reason": "injury"}
    assert [item["key"] for item in project_details("INTERRUPT_MATCH_SEGMENT", payload, {})] == [
        "reason", "minute", "notes",
    ]


@pytest.mark.parametrize("payload", [
    {"minute": "30", "reason": {"x": 1}, "notes": ["a"]},
    {"minute": True, "reason": 5, "notes": 7},
    {"minute": None, "reason": None, "notes": None},
    {},
])
def test_missing_or_mistyped_fields_are_omitted(payload):
    assert project_details("INTERRUPT_MATCH_SEGMENT", payload, {}) == []


def test_boolean_and_code_types_are_strict():
    assert project_details("SET_MEMBER_ACTIVE", {"is_active": 1}, {}) == []
    assert project_details("CHANGE_MEMBER_ROLE", {"role_code": "x" * 65}, {}) == []
    assert project_details("ASSIGN_MATCH_OFFICIAL", {"organization_user_id": 5}, {MEMBER: "Ana"}) == []


def test_text_is_trimmed_to_limit():
    details = as_dict(project_details("INTERRUPT_MATCH_SEGMENT", {"notes": "a" * (TEXT_LIMIT + 50)}, {}))
    assert TEXT_LIMIT == 1000 and details["notes"] == "a" * TEXT_LIMIT


def test_non_object_payload_and_unknown_actions():
    assert project_details("UNKNOWN_ACTION", {"reason": "x"}, {}) is None
    assert project_details("CHANGE_MEMBER_ROLE", None, {}) == []
    assert project_details("CHANGE_MEMBER_ROLE", ["role_code"], {}) == []


def test_catalog_has_no_sensitive_paths():
    assert_catalog_safe()
    assert {"email", "token", "url", "link", "document", "birth", "platform_admin"} <= set(FORBIDDEN_PATH_PARTS)
    for spec in CATALOG.values():
        for field in spec.fields:
            assert not any(part in segment.lower() for segment in field.path for part in FORBIDDEN_PATH_PARTS)


def test_catalog_entity_types():
    assert {spec.entity_type for spec in CATALOG.values()} == {
        "matches", "sanction_cases", "competitive_impact_procedures", "organization_users",
        "organization_invitations", "teams", "stage_slot_resolutions", "organization_webhooks",
        "tournaments",
    }


CODE = r"([A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+)"
SQL_INSERT = re.compile(r"INSERT\s+INTO\s+(?:public\.)?administrative_audit_logs\b(.{0,700}?)(?:\"\"\"|;)", re.S | re.I)
PY_PATTERNS = (
    re.compile(rf"^[A-Z_]+\s*=\s*\"{CODE}\"\s*$", re.M),
    re.compile(rf"\baction\s*=\s*\"{CODE}\""),
    re.compile(rf"\"action\"\s*:\s*\"{CODE}\""),
    re.compile(rf"\b(?:audit_impact|_audit|_authorization_audit)\([^)]*\"{CODE}\"\)"),
)
AUDIT_ACTION = re.compile(r"audit_action\s*=\s*\((.*?)\)", re.S)


def written_actions() -> set[str]:
    found: set[str] = set()
    sources = [*(ROOT / "backend" / "app").rglob("*.py"), *(ROOT / "infra" / "postgres" / "migrations").glob("*.sql")]
    for path in sources:
        source = path.read_text(encoding="utf-8")
        for block in SQL_INSERT.findall(source):
            found.update(re.findall(rf"'{CODE}'", block))
        if path.suffix != ".py":
            continue
        is_audit_module = path.name == "audit.py"
        for index, pattern in enumerate(PY_PATTERNS):
            if index == 0 and not is_audit_module:
                continue
            found.update(pattern.findall(source))
        for block in AUDIT_ACTION.findall(source):
            found.update(re.findall(rf"\"{CODE}\"", block))
    return found


def test_inventory_every_written_action_is_cataloged():
    written = written_actions()
    assert written - set(CATALOG) == set()
    assert set(CATALOG) - written == set()


@pytest.mark.parametrize("action", ["ASSIGN_TOURNAMENT_OPERATOR", "REMOVE_TOURNAMENT_OPERATOR"])
def test_tournament_operator_actions_use_the_tournament_entity_and_member_names(action):
    assert CATALOG[action].entity_type == "tournaments"
    assert referenced_member_ids(action, {"organization_user_id": MEMBER, "role_code": "tournament_operator"}) == {MEMBER}
