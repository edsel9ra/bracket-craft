from datetime import datetime, timedelta, timezone
from dataclasses import replace
from uuid import uuid4

import pytest

from app.core import realtime_policy as policy


def envelope(event_type='MATCH_UPDATED', private=False):
    payload = {'match_id': str(uuid4()), 'tournament_id': str(uuid4())}
    if private:
        payload.update(scope='organization', version_id=str(uuid4()))
    return {'event_id': str(uuid4()), 'organization_id': str(uuid4()),
            'event_type': event_type, 'payload': payload}


@pytest.mark.parametrize('name,private', [
    ('MATCH_CLOSED', False), ('MATCH_UPDATED', False), ('STANDINGS_UPDATED', False),
    ('MATCH_UPDATED', True), ('STANDINGS_UPDATED', True), ('MATCH_REPORT_RECTIFIED', True),
])
def test_catalog_declares_exact_http_read(name, private):
    event = policy.classify_organization_event(envelope(name, private))
    assert event is not None
    assert event.rule.operation_read is (name != 'MATCH_REPORT_RECTIFIED')
    assert event.rule.version_read is private
    assert event.rule.permission is None
    assert not event.rule.requires_official


@pytest.mark.parametrize('name,private', [
    ('MATCH_CLOSED', True), ('MATCH_REPORT_RECTIFIED', False), ('RESYNC', False),
    ('VERIFICATION_OUTBOX_PROBE', False), ('SANCTION_CASE_NOTICE_INTERNAL', False),
    ('SANCTION_CASE_NOTICE_EMAIL', False), ('RECTIFICATION_DECISION_EMAIL', False),
    ('MATCH_DRAFT_UPDATED', False), ('UNKNOWN', False),
])
def test_catalog_exclusions_have_no_delivery_intent(name, private):
    assert policy.classify_organization_event(envelope(name, private)) is None


def test_catalog_rejects_unknown_scope():
    data = envelope()
    data['payload']['scope'] = 'public'
    assert policy.classify_organization_event(data) is None


@pytest.mark.parametrize('mode', ['primary', 'legacy', 'both'])
def test_envelope_canonical_id(mode):
    data = envelope()
    identity = data['event_id']
    if mode != 'primary':
        data['id'] = identity
    if mode == 'legacy':
        del data['event_id']
    result = policy.classify_organization_event(data)
    assert str(result.event_id) == identity
    assert str(result.organization_id) == data['organization_id']


@pytest.mark.parametrize('changes', [
    {'event_id': None}, {'event_id': ''}, {'event_id': 123}, {'event_id': []},
    {'id': str(uuid4())}, {'organization_id': 'bad'}, {'organization_id': None},
    {'payload': None}, {'payload': []}, {'event_type': None},
])
def test_envelope_incoherence_is_denied(changes):
    assert policy.classify_organization_event({**envelope(), **changes}) is None


@pytest.mark.parametrize('data', [None, [], '', {}, {'event_type': 'MATCH_UPDATED', 'payload': {}}])
def test_envelope_missing_or_malformed(data):
    assert policy.classify_organization_event(data) is None


@pytest.mark.parametrize('private', [False, True])
def test_references_are_typed_but_not_authorization(private):
    data = envelope(private=private)
    rule = policy.classify_organization_event(data).rule
    references = policy.resolve_event_references(rule, data['payload'])
    assert references is not None
    assert str(references.match_id) == data['payload']['match_id']
    assert str(references.tournament_id) == data['payload']['tournament_id']
    assert (references.version_id is not None) is private
    assert not hasattr(references, 'authorized')


@pytest.mark.parametrize('private,key,value', [
    (False, 'match_id', None), (False, 'tournament_id', []),
    (False, 'version_id', str(uuid4())), (True, 'version_id', 'invalid'),
    (True, 'version_id', None), (True, 'score', 7), (False, 'scope', 'organization'),
    (True, 'rectified_at', {}),
])
def test_references_missing_incoherent_or_unexpected(private, key, value):
    data = envelope(private=private)
    rule = policy.classify_organization_event(data).rule
    data['payload'][key] = value
    assert policy.resolve_event_references(rule, data['payload']) is None


def test_references_reject_empty_and_unknown_rule():
    assert policy.resolve_event_references(policy.CATALOG[0], {}) is None
    assert policy.resolve_event_references(None, envelope()['payload']) is None


def test_invalidation_whitelist_ignores_internal_and_historical_fields():
    data = envelope(private=True)
    data['payload']['rectified_at'] = '2026-11-13T12:00:00+00:00'
    event = policy.classify_organization_event(data)
    refs = policy.resolve_event_references(event.rule, data['payload'])
    data['payload']['evidence'] = 'not for transport'
    assert policy.build_private_invalidation(event.event_id, refs) == {
        'event_id': data['event_id'], 'match_id': str(refs.match_id),
        'tournament_id': str(refs.tournament_id),
    }


@pytest.mark.parametrize('identity,refs', [
    (None, None), ('bad', None), (uuid4(), {}), (uuid4(), None),
    (uuid4(), policy.EventReferences(None, uuid4())),
])
def test_invalidation_empty_incomplete_or_untyped_is_denied(identity, refs):
    assert policy.build_private_invalidation(identity, refs) is None


NOW = datetime(2026, 11, 13, 12, tzinfo=timezone.utc)


def socket_metadata(org, user=None, session=None, **changes):
    return {'scope': 'organization', 'organization_id': str(org),
            'user_id': str(user or uuid4()), 'session_id': str(session or uuid4()),
            'generation': str(uuid4()), 'jwt_expires_at': NOW + timedelta(hours=1), **changes}


def test_recipients_share_session_not_identity_and_preserve_generation():
    org, user, session = uuid4(), uuid4(), uuid4()
    first = socket_metadata(org, user, session)
    second = socket_metadata(org, user, session)
    sessions = {'b': second, 'a': first, 'c': socket_metadata(org, user)}
    batches = policy.group_recipients(sessions, org)
    assert len(batches) == 1 and len(batches[0]) == 2
    shared = next(p for p in batches[0] if str(p.session_id) == str(session))
    assert [s.sid for s in shared.sockets] == ['a', 'b']
    assert shared.sockets[0].generation == first['generation']
    assert policy.group_recipients(dict(reversed(list(sessions.items()))), org) == batches


@pytest.mark.parametrize('count,expected', [(0, []), (256, [256]), (257, [256, 1])])
def test_recipients_batch_limits(count, expected):
    org = uuid4()
    result = policy.group_recipients({str(i): socket_metadata(org) for i in range(count)}, org)
    assert [len(batch) for batch in result] == expected


def test_recipients_invalid_metadata_and_other_tenant():
    org = uuid4()
    invalid = [None, {}, socket_metadata(uuid4()), socket_metadata(org, scope='public'),
               socket_metadata(org, user_id='bad'), socket_metadata(org, generation=''),
               socket_metadata(org, jwt_expires_at=None)]
    assert policy.group_recipients({str(i): row for i, row in enumerate(invalid)}, org) == ()
    assert policy.group_recipients({}, 'bad') == ()


@pytest.mark.parametrize('size', [0, -1, 257, None, True])
def test_recipients_reject_unbounded_batch(size):
    with pytest.raises(ValueError):
        policy.group_recipients({}, uuid4(), size)


def facts():
    org = uuid4()
    return (
        policy.RecipientFacts(org, True, True, True, True,
            (policy.RoleFacts('reader', frozenset()),), False,
            NOW + timedelta(hours=1), NOW + timedelta(hours=1)),
        policy.ResourceFacts(org, True, True),
    )


def test_permissions_general_read_does_not_require_write_or_official():
    recipient, resource = facts()
    for rule in policy.CATALOG:
        assert policy.decide_private_delivery(rule, recipient, resource, NOW) == policy.Decision.ALLOW


@pytest.mark.parametrize('role_rows,assigned,expected', [
    ([('reader', {'CONDITIONAL_READ'})], True, 'ALLOW'),
    ([('reader', {'CONDITIONAL_READ'})], False, 'DENY'),
    ([('reader', set())], True, 'DENY'),
    ([('operator', {'CONDITIONAL_READ'})], False, 'ALLOW'),
    ([('operator', set()), ('reader', {'CONDITIONAL_READ'})], False, 'DENY'),
    ([('reader', set()), ('reader', {'CONDITIONAL_READ'})], True, 'ALLOW'),
    ([('reader', {'CONDITIONAL_READ'})], None, 'INDETERMINATE'),
])
def test_permissions_conditional_rule_keeps_same_role_conjunction(role_rows, assigned, expected):
    recipient, resource = facts()
    rule = replace(policy.CATALOG[0], permission='CONDITIONAL_READ', requires_official=True)
    recipient = replace(recipient, roles=tuple(policy.RoleFacts(code, frozenset(perms)) for code, perms in role_rows),
                        assigned_official=assigned)
    assert policy.decide_private_delivery(rule, recipient, resource, NOW) == expected


@pytest.mark.parametrize('change,expected', [({'roles': ()}, 'DENY'), ({'roles': None}, 'INDETERMINATE')])
def test_permissions_missing_roles(change, expected):
    recipient, resource = facts()
    assert policy.decide_private_delivery(policy.CATALOG[0], replace(recipient, **change), resource, NOW) == expected


def test_permissions_foreign_and_incomplete_resources():
    recipient, resource = facts()
    rule = policy.CATALOG[0]
    assert policy.decide_private_delivery(rule, recipient, replace(resource, organization_id=uuid4()), NOW) == 'DENY'
    assert policy.decide_private_delivery(rule, recipient, replace(resource, operation_readable=False), NOW) == 'DENY'
    assert policy.decide_private_delivery(rule, recipient, replace(resource, operation_readable=None), NOW) == 'INDETERMINATE'
    assert policy.decide_private_delivery(rule, None, resource, NOW) == 'INDETERMINATE'


@pytest.mark.parametrize('field', ['session_expires_at', 'jwt_expires_at'])
@pytest.mark.parametrize('delta,expected', [(-1, 'DENY'), (0, 'DENY'), (1, 'ALLOW')])
def test_temporal_expiry_boundary(field, delta, expected):
    recipient, resource = facts()
    recipient = replace(recipient, **{field: NOW + timedelta(seconds=delta)})
    assert policy.decide_private_delivery(policy.CATALOG[0], recipient, resource, NOW) == expected


@pytest.mark.parametrize('field', ['session_valid', 'user_active', 'organization_active', 'membership_active'])
def test_temporal_inactive_identity_or_missing_facts(field):
    recipient, resource = facts()
    assert policy.decide_private_delivery(policy.CATALOG[0], replace(recipient, **{field: False}), resource, NOW) == 'DENY'
    assert policy.decide_private_delivery(policy.CATALOG[0], replace(recipient, **{field: None}), resource, NOW) == 'INDETERMINATE'


@pytest.mark.parametrize('value', [None, NOW.replace(tzinfo=None), 'tomorrow'])
def test_temporal_unknown_or_naive_time(value):
    recipient, resource = facts()
    assert policy.decide_private_delivery(policy.CATALOG[0], recipient, resource, value) == 'INDETERMINATE'
    assert policy.decide_private_delivery(policy.CATALOG[0], replace(recipient, jwt_expires_at=value), resource, NOW) == 'INDETERMINATE'


def test_temporal_same_session_does_not_share_jwt_expiry():
    org, user, session = uuid4(), uuid4(), uuid4()
    batches = policy.group_recipients({
        'a': socket_metadata(org, user, session, jwt_expires_at=NOW),
        'b': socket_metadata(org, user, session, jwt_expires_at=NOW + timedelta(seconds=1)),
    }, org)
    recipient, _ = facts()
    recipient = replace(recipient, organization_id=org)
    resource = policy.ResourceFacts(org, True, True)
    assert [policy.decide_private_delivery(policy.CATALOG[0],
            replace(recipient, jwt_expires_at=socket.jwt_expires_at), resource, NOW)
            for socket in batches[0][0].sockets] == ['DENY', 'ALLOW']


def test_recovery_state_suspends_repeated_errors_and_recovers_once():
    generation = str(uuid4())
    transition = policy.reduce_delivery_state(None, 'INDETERMINATE', generation, NOW)
    assert transition.state.needs_resync and not transition.request_resync
    assert transition.state.next_attempt_at == NOW + timedelta(seconds=30)
    repeated = policy.reduce_delivery_state(transition.state, 'INDETERMINATE', generation, NOW)
    assert repeated == transition
    denied = policy.reduce_delivery_state(repeated.state, 'DENY', generation, NOW)
    assert denied.state.needs_resync and not denied.request_resync
    recovered = policy.reduce_delivery_state(denied.state, 'ALLOW', generation, NOW)
    assert recovered.request_resync and recovered.state.pending_resync
    assert not policy.reduce_delivery_state(recovered.state, 'ALLOW', generation, NOW).request_resync
    sent = policy.reduce_delivery_state(recovered.state, policy.ControlResult.RESYNC_SENT, generation, NOW)
    assert not sent.state.needs_resync and not sent.state.pending_resync
    assert not policy.reduce_delivery_state(sent.state, 'ALLOW', generation, NOW).request_resync


def test_recovery_state_failed_control_keeps_episode_without_resource_history():
    state = policy.DeliveryState('generation', True, True)
    failed = policy.reduce_delivery_state(state, policy.ControlResult.RESYNC_FAILED, 'generation', NOW)
    assert failed.state.needs_resync and not failed.state.pending_resync
    assert failed.state.next_attempt_at == NOW + timedelta(seconds=30)
    assert policy.reduce_delivery_state(failed.state, 'ALLOW', 'generation', NOW).request_resync
    assert set(vars(failed.state)) == {'generation', 'needs_resync', 'pending_resync', 'next_attempt_at'}


def test_recovery_state_empty_and_obsolete_generation_do_not_resync():
    empty = policy.reduce_delivery_state(None, 'ALLOW', 'new', NOW)
    assert empty.state == policy.DeliveryState('new') and not empty.request_resync
    obsolete = policy.reduce_delivery_state(policy.DeliveryState('old', True), 'ALLOW', 'new', NOW)
    assert obsolete == empty
