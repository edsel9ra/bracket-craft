"""Catálogo cerrado de acciones de la auditoría organizacional (spec 041, RF-007/RF-008).

Cada acción declara su tipo de entidad y los campos del ``payload`` que se
muestran. Nunca se devuelve el JSON guardado completo: lo no declarado, ausente
o de un tipo distinto se omite, y una acción desconocida no muestra contenido.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal

FieldKind = Literal["text", "number", "boolean", "code", "codes", "member"]

TEXT_LIMIT = 1000
CODE_LIMIT = 64
CODES_LIMIT = 10
FORBIDDEN_PATH_PARTS = ("email", "token", "url", "link", "document", "birth", "platform_admin")


@dataclass(frozen=True)
class FieldSpec:
    key: str
    path: tuple[str, ...]
    kind: FieldKind


@dataclass(frozen=True)
class ActionSpec:
    entity_type: str
    fields: tuple[FieldSpec, ...] = ()


def _field(key: str, kind: FieldKind, *path: str) -> FieldSpec:
    return FieldSpec(key, path or (key,), kind)


_MATCH_CLOSE = (
    _field("previous_status", "code"),
    _field("final_status", "code"),
    _field("resolution_type", "code", "request", "resolution_type"),
    _field("home_score", "number", "outcome", "home_score"),
    _field("away_score", "number", "outcome", "away_score"),
    _field("reason", "text", "request", "reason"),
    _field("suspensions", "number"),
)
_OFFICIAL = (_field("member", "member", "organization_user_id"), _field("official_role", "code"))
_PUBLICATION = (_field("is_public", "boolean"),)
_WEBHOOK = (_field("host", "text"), _field("event_types", "codes"), _field("is_active", "boolean"))

CATALOG: dict[str, ActionSpec] = {
    "CLOSE_MATCH_REPORT": ActionSpec("matches", _MATCH_CLOSE),
    "ADMINISTRATIVE_MATCH_RESOLUTION": ActionSpec("matches", _MATCH_CLOSE),
    "INTERRUPT_MATCH_SEGMENT": ActionSpec("matches", (
        _field("reason", "code"), _field("minute", "number"), _field("notes", "text"),
    )),
    "MATCH_LIVE_COMMAND": ActionSpec("matches", (_field("type", "code"), _field("revision", "number"))),
    "SAVE_MATCH_LINEUP": ActionSpec("matches", (
        _field("teams", "number"), _field("entries", "number"),
        _field("starters", "number"), _field("substitutes", "number"),
    )),
    "PUBLISH_MATCH_LINEUP": ActionSpec("matches", _PUBLICATION),
    "UNPUBLISH_MATCH_LINEUP": ActionSpec("matches", _PUBLICATION),
    "ASSIGN_MATCH_OFFICIAL": ActionSpec("matches", _OFFICIAL),
    "REMOVE_MATCH_OFFICIAL": ActionSpec("matches", _OFFICIAL),
    "REQUEST_MATCH_REPORT_RECTIFICATION": ActionSpec("matches", (_field("base_version_number", "number"),)),
    "DECIDE_MATCH_REPORT_RECTIFICATION": ActionSpec("matches", (_field("decision", "code"),)),
    "GRANT_RECTIFICATION_AUTHORIZATION": ActionSpec("matches"),
    "REVOKE_RECTIFICATION_AUTHORIZATION": ActionSpec("matches"),
    "DECIDE_SANCTION_CASE": ActionSpec("sanction_cases", (_field("decision", "code"),)),
    "GRANT_SANCTION_AUTHORIZATION": ActionSpec("sanction_cases"),
    "REVOKE_SANCTION_AUTHORIZATION": ActionSpec("sanction_cases"),
    "OPEN_COMPETITIVE_IMPACT": ActionSpec("competitive_impact_procedures", (_field("resolution", "code"),)),
    "CLOSE_COMPETITIVE_IMPACT": ActionSpec("competitive_impact_procedures", (_field("resolution", "code"),)),
    "CHANGE_MEMBER_ROLE": ActionSpec("organization_users", (_field("role_code", "code"),)),
    "SET_MEMBER_ACTIVE": ActionSpec("organization_users", (_field("is_active", "boolean"),)),
    "ACCEPT_INVITATION": ActionSpec("organization_invitations", (_field("role_code", "code"),)),
    "REOPEN_INVITATION": ActionSpec("organization_invitations", (
        _field("previous_status", "code"), _field("role_code", "code"),
    )),
    "SET_TEAM_CREST": ActionSpec("teams"),
    "REMOVE_TEAM_CREST": ActionSpec("teams"),
    "STAGE_SLOTS_RESOLVED": ActionSpec("stage_slot_resolutions"),
    "CREATE_WEBHOOK": ActionSpec("organization_webhooks", _WEBHOOK),
    "UPDATE_WEBHOOK": ActionSpec("organization_webhooks", _WEBHOOK),
    "SET_WEBHOOK_ACTIVE": ActionSpec("organization_webhooks", _WEBHOOK),
    "ROTATE_WEBHOOK_SECRET": ActionSpec("organization_webhooks", (_field("host", "text"),)),
    "DELETE_WEBHOOK": ActionSpec("organization_webhooks", (_field("host", "text"),)),
}


def assert_catalog_safe() -> None:
    """Falla si alguna ruta declarada apunta a un dato sensible (RF-007)."""

    for action, spec in CATALOG.items():
        for field in spec.fields:
            for segment in field.path:
                if any(part in segment.lower() for part in FORBIDDEN_PATH_PARTS):
                    raise AssertionError(f"{action}.{field.key} apunta a un dato sensible")


def _read(payload: Any, path: tuple[str, ...]) -> Any:
    value = payload
    for segment in path:
        if not isinstance(value, Mapping):
            return None
        value = value.get(segment)
    return value


def _project(field: FieldSpec, value: Any, member_names: Mapping[str, str]) -> Any:
    if field.kind == "text":
        return value[:TEXT_LIMIT] if isinstance(value, str) else None
    if field.kind == "number":
        return value if isinstance(value, int | float) and not isinstance(value, bool) else None
    if field.kind == "boolean":
        return value if isinstance(value, bool) else None
    if field.kind == "code":
        return value if isinstance(value, str) and 0 < len(value) <= CODE_LIMIT else None
    if field.kind == "codes":
        # Lista de códigos mostrada como texto separado por comas; la detalle sigue siendo escalar.
        if not isinstance(value, list) or not 0 < len(value) <= CODES_LIMIT:
            return None
        if not all(isinstance(item, str) and 0 < len(item) <= CODE_LIMIT for item in value):
            return None
        return ",".join(value)
    return member_names.get(value) if isinstance(value, str) else None


def project_details(
    action: str, payload: Any, member_names: Mapping[str, str]
) -> list[dict[str, Any]] | None:
    """Campos declarados de ``action`` en su orden; ``None`` si no está catalogada."""

    spec = CATALOG.get(action)
    if spec is None:
        return None
    details: list[dict[str, Any]] = []
    for field in spec.fields:
        value = _read(payload, field.path)
        if value is None:
            continue
        projected = _project(field, value, member_names)
        if projected is not None:
            details.append({"key": field.key, "value": projected})
    return details


def referenced_member_ids(action: str, payload: Any) -> set[str]:
    """IDs de miembro que ``project_details`` necesitará resolver a nombre."""

    spec = CATALOG.get(action)
    if spec is None:
        return set()
    values = (_read(payload, field.path) for field in spec.fields if field.kind == "member")
    return {value for value in values if isinstance(value, str)}
