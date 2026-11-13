"""Organization-delivery policy; no transport or database dependencies."""

from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from enum import StrEnum
from uuid import UUID


@dataclass(frozen=True)
class ReadRule:
    event_type: str
    scope: str | None
    operation_read: bool
    version_read: bool
    permission: str | None = None
    requires_official: bool = False


CATALOG = (
    ReadRule('MATCH_CLOSED', None, True, False),
    ReadRule('MATCH_UPDATED', None, True, False),
    ReadRule('STANDINGS_UPDATED', None, True, False),
    ReadRule('MATCH_UPDATED', 'organization', True, True),
    ReadRule('STANDINGS_UPDATED', 'organization', True, True),
    ReadRule('MATCH_REPORT_RECTIFIED', 'organization', False, True),
)


@dataclass(frozen=True)
class ClassifiedEvent:
    rule: ReadRule
    envelope: Mapping
    event_id: UUID
    organization_id: UUID


def _uuid(value):
    if not isinstance(value, (str, UUID)):
        return None
    try:
        return UUID(str(value))
    except ValueError:
        return None


@dataclass(frozen=True)
class EventReferences:
    match_id: UUID
    tournament_id: UUID
    version_id: UUID | None = None


def build_private_invalidation(event_id, authorized_refs):
    if not isinstance(authorized_refs, EventReferences):
        return None
    identifiers = (event_id, authorized_refs.match_id, authorized_refs.tournament_id)
    normalized = tuple(_uuid(value) for value in identifiers)
    if any(value is None for value in normalized):
        return None
    return dict(zip(('event_id', 'match_id', 'tournament_id'), map(str, normalized)))


@dataclass(frozen=True)
class SocketRecipient:
    sid: str
    generation: str
    jwt_expires_at: datetime


@dataclass(frozen=True)
class Principal:
    organization_id: UUID
    user_id: UUID
    session_id: UUID
    sockets: tuple[SocketRecipient, ...]


class Decision(StrEnum):
    ALLOW = 'ALLOW'
    DENY = 'DENY'
    INDETERMINATE = 'INDETERMINATE'


@dataclass(frozen=True)
class RoleFacts:
    code: str
    permissions: frozenset[str]


@dataclass(frozen=True)
class RecipientFacts:
    organization_id: UUID
    session_valid: bool | None
    user_active: bool | None
    organization_active: bool | None
    membership_active: bool | None
    roles: tuple[RoleFacts, ...] | None
    assigned_official: bool | None
    session_expires_at: datetime | None
    jwt_expires_at: datetime | None


@dataclass(frozen=True)
class ResourceFacts:
    organization_id: UUID
    operation_readable: bool | None
    version_readable: bool | None


class ControlResult(StrEnum):
    RESYNC_SENT = 'RESYNC_SENT'
    RESYNC_FAILED = 'RESYNC_FAILED'


@dataclass(frozen=True)
class DeliveryState:
    generation: str
    needs_resync: bool = False
    pending_resync: bool = False
    next_attempt_at: datetime | None = None


@dataclass(frozen=True)
class DeliveryTransition:
    state: DeliveryState
    request_resync: bool = False


def reduce_delivery_state(state, result, connection_generation, evaluation_time):
    if state is not None and state.generation != connection_generation:
        return DeliveryTransition(DeliveryState(connection_generation))
    state = state or DeliveryState(connection_generation)
    if result == Decision.INDETERMINATE:
        return DeliveryTransition(replace(state, needs_resync=True,
            next_attempt_at=state.next_attempt_at or evaluation_time + timedelta(seconds=30)))
    if result == ControlResult.RESYNC_SENT and state.pending_resync:
        return DeliveryTransition(DeliveryState(connection_generation))
    if result == ControlResult.RESYNC_FAILED and state.pending_resync:
        return DeliveryTransition(replace(state, pending_resync=False,
            next_attempt_at=evaluation_time + timedelta(seconds=30)))
    if result == Decision.ALLOW and state.needs_resync and not state.pending_resync:
        return DeliveryTransition(replace(state, pending_resync=True), True)
    return DeliveryTransition(state)


def decide_private_delivery(rule, recipient_facts, resource_facts, evaluation_time):
    if not isinstance(rule, ReadRule) or not isinstance(recipient_facts, RecipientFacts) or not isinstance(resource_facts, ResourceFacts):
        return Decision.INDETERMINATE
    if recipient_facts.organization_id != resource_facts.organization_id:
        return Decision.DENY
    times = (evaluation_time, recipient_facts.session_expires_at, recipient_facts.jwt_expires_at)
    if any(not isinstance(value, datetime) or value.utcoffset() is None for value in times):
        return Decision.INDETERMINATE
    if any(value <= evaluation_time for value in times[1:]):
        return Decision.DENY
    checks = [recipient_facts.session_valid, recipient_facts.user_active,
              recipient_facts.organization_active, recipient_facts.membership_active]
    if rule.operation_read:
        checks.append(resource_facts.operation_readable)
    if rule.version_read:
        checks.append(resource_facts.version_readable)
    if any(value is False for value in checks):
        return Decision.DENY
    if any(value is not True for value in checks) or recipient_facts.roles is None:
        return Decision.INDETERMINATE
    if not recipient_facts.roles:
        return Decision.DENY
    unknown_assignment = False
    for role in recipient_facts.roles:
        if rule.permission is not None and rule.permission not in role.permissions:
            continue
        if not rule.requires_official or role.code in {'owner', 'administrator', 'operator'}:
            return Decision.ALLOW
        if recipient_facts.assigned_official is True:
            return Decision.ALLOW
        unknown_assignment |= recipient_facts.assigned_official is None
    return Decision.INDETERMINATE if unknown_assignment else Decision.DENY


def group_recipients(server_sessions, organization_id, batch_size=256):
    if type(batch_size) is not int or not 1 <= batch_size <= 256:
        raise ValueError('batch_size must be between 1 and 256')
    organization_id = _uuid(organization_id)
    if organization_id is None or not isinstance(server_sessions, Mapping):
        return ()
    grouped = {}
    for sid, metadata in server_sessions.items():
        if not isinstance(sid, str) or not sid or not isinstance(metadata, Mapping):
            continue
        if metadata.get('scope') != 'organization' or _uuid(metadata.get('organization_id')) != organization_id:
            continue
        user, session = _uuid(metadata.get('user_id')), _uuid(metadata.get('session_id'))
        generation, expiry = metadata.get('generation'), metadata.get('jwt_expires_at')
        if user is None or session is None or not isinstance(generation, str) or not generation:
            continue
        if not isinstance(expiry, datetime) or expiry.utcoffset() is None:
            continue
        grouped.setdefault((user, session), []).append(SocketRecipient(sid, generation, expiry))
    principals = tuple(
        Principal(organization_id, user, session, tuple(sorted(sockets, key=lambda socket: socket.sid)))
        for (user, session), sockets in sorted(grouped.items())
    )
    return tuple(principals[start:start + batch_size] for start in range(0, len(principals), batch_size))


def resolve_event_references(rule, payload):
    if rule not in CATALOG or not isinstance(payload, Mapping):
        return None
    allowed = {'match_id', 'tournament_id'}
    if rule.version_read:
        allowed |= {'scope', 'version_id', 'rectified_at'}
    if set(payload) - allowed or payload.get('scope') != rule.scope:
        return None
    match_id = _uuid(payload.get('match_id'))
    tournament_id = _uuid(payload.get('tournament_id'))
    version_id = _uuid(payload.get('version_id')) if rule.version_read else None
    if match_id is None or tournament_id is None or (rule.version_read and version_id is None):
        return None
    if 'rectified_at' in payload:
        try:
            if not isinstance(payload['rectified_at'], str):
                return None
            datetime.fromisoformat(payload['rectified_at'])
        except ValueError:
            return None
    return EventReferences(match_id, tournament_id, version_id)


def classify_organization_event(envelope, catalog=CATALOG):
    if not isinstance(envelope, Mapping):
        return None
    payload = envelope.get('payload')
    if not isinstance(payload, Mapping):
        return None
    organization_id = _uuid(envelope.get('organization_id'))
    event_id = _uuid(envelope.get('event_id', envelope.get('id')))
    if organization_id is None or event_id is None:
        return None
    if 'id' in envelope and _uuid(envelope['id']) != event_id:
        return None
    for rule in catalog:
        if (envelope.get('event_type'), payload.get('scope')) == (rule.event_type, rule.scope):
            if resolve_event_references(rule, payload) is None:
                return None
            return ClassifiedEvent(rule, envelope, event_id, organization_id)
    return None
