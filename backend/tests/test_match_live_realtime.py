"""B2 invalidations and real SQL/HTTP parity; no production live routers."""

import json
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.realtime_policy import (
    classify_organization_event,
    build_private_invalidation,
    resolve_event_references,
)
from app.core.realtime_authorization import RealtimeAuthorizer
from app.core.realtime_policy import Principal, SocketRecipient, Decision
from app.modules.matches.live_service import LiveMatchService
from test_match_live_db import (
    live_service_db as live_service_db,
    command,
    goal,
    MATCH,
    ORG,
    USER,
    MEMBER,
)
from test_migration_031 import TOURNAMENT
from test_migration_056 import SEGMENT_FIRST
from test_rectification_flow import flow as flow


def envelope(**payload):
    return dict(
        event_id=str(uuid4()),
        organization_id=ORG,
        event_type="MATCH_LIVE_UPDATED",
        payload=dict(
            scope="organization", match_id=MATCH, tournament_id=TOURNAMENT, **payload
        ),
    )


def test_catalog_live_organization_without_version_and_minimal_wire():
    event = classify_organization_event(envelope())
    assert event is not None and event.rule.permission == "VIEW_MATCH_LIVE_DRAFT"
    assert not event.rule.version_read and event.rule.requires_official
    payload = build_private_invalidation(
        event.event_id, resolve_event_references(event.rule, event.envelope["payload"])
    )
    assert set(payload) == {"event_id", "match_id", "tournament_id"}


@pytest.mark.parametrize(
    "extra",
    [
        {"version_id": str(uuid4())},
        {"events": []},
        {"revision": 1},
        {"actor": str(uuid4())},
    ],
)
def test_catalog_rejects_unrelated_or_private_details(extra):
    assert classify_organization_event(envelope(**extra)) is None


@pytest.mark.parametrize(
    "event_type",
    [
        "MATCH_LIVE_PUBLIC_UPDATED",
        "SANCTION_CASE_NOTICE_INTERNAL",
        "SANCTION_CASE_NOTICE_EMAIL",
    ],
)
def test_catalog_never_routes_public_or_f9_as_live_private(event_type):
    data = envelope()
    data["event_type"] = event_type
    assert classify_organization_event(data) is None


async def live_outbox(f):
    return await f.admin.fetch(
        "SELECT id,event_type,payload FROM outbox_events WHERE event_type LIKE 'MATCH_LIVE_%' ORDER BY created_at,id"
    )


async def test_outbox_accepted_retry_rejection_card_and_goal(live_service_db):
    f = live_service_db
    start = command("start_clock", segment_id=SEGMENT_FIRST)
    await f.call("execute", start)
    rows = await live_outbox(f)
    assert {r["event_type"] for r in rows} == {
        "MATCH_LIVE_UPDATED",
        "MATCH_LIVE_PUBLIC_UPDATED",
    }
    first = rows
    await f.call("execute", start)
    assert await live_outbox(f) == first
    card = goal()
    card["event_type"] = "yellow_card"
    await f.call("execute", command("add_event", 1, event=card))
    rows = await live_outbox(f)
    assert (
        len(rows) == 3
        and sum(r["event_type"] == "MATCH_LIVE_PUBLIC_UPDATED" for r in rows) == 1
    )
    await f.call("execute", command("add_event", 2, event=goal()))
    rows = await live_outbox(f)
    assert len(rows) == 5
    for row in rows:
        payload = json.loads(row["payload"])
        assert set(payload) == (
            {"scope", "match_id", "tournament_id"}
            if row["event_type"] == "MATCH_LIVE_UPDATED"
            else {"match_id", "tournament_id"}
        )
    with pytest.raises(Exception):
        await f.call("execute", command("pause_clock", 0))
    assert await live_outbox(f) == rows


async def test_outbox_rollback_on_notice_failure(live_service_db, monkeypatch):
    import app.modules.matches.live_notices as notices

    f = live_service_db
    original = notices.enqueue_outbox

    async def fail_public(db, org, event, payload, **kwargs):
        if event == "MATCH_LIVE_PUBLIC_UPDATED":
            raise RuntimeError("public notice failure")
        return await original(db, org, event, payload, **kwargs)

    monkeypatch.setattr(notices, "enqueue_outbox", fail_public)
    with pytest.raises(RuntimeError):
        await f.call("execute", command("start_clock", segment_id=SEGMENT_FIRST))
    assert await live_outbox(f) == []
    assert await f.admin.fetchval("SELECT count(*) FROM match_live_state") == 0
    assert await f.admin.fetchval("SELECT count(*) FROM match_live_commands") == 0


@pytest.mark.parametrize("live_service_db", [{"extra_match": True}], indirect=True)
@pytest.mark.parametrize(
    "case",
    [
        "view",
        "operate",
        "both",
        "none",
        "assigned",
        "unassigned",
        "wrong_assignment",
        "multirole",
        "revoked",
        "inactive_member",
        "inactive_user",
        "inactive_org",
        "platform",
        "other_tenant",
    ],
)
async def test_http_sql_parity(live_service_db, case):
    f = live_service_db
    permissions = (
        ["VIEW_MATCH_LIVE_DRAFT"]
        if case not in {"operate", "none", "platform"}
        else (["OPERATE_MATCH_LIVE"] if case == "operate" else [])
    )
    if case == "both":
        permissions.append("OPERATE_MATCH_LIVE")
    await f.permissions(permissions)
    if case in {"assigned", "unassigned", "wrong_assignment"}:
        await f.admin.execute(
            "UPDATE roles SET role_definition_id=(SELECT id FROM role_definitions WHERE code='referee') WHERE organization_id=$1",
            ORG,
        )
        if case != "unassigned":
            target = (
                MATCH if case == "assigned" else "31000000-0000-4000-8000-000000000053"
            )
            await f.admin.execute(
                "INSERT INTO match_officials(organization_id,match_id,organization_user_id,official_role) VALUES ($1,$2,$3,'main_referee')",
                ORG,
                target,
                MEMBER,
            )
    if case == "multirole":
        await f.admin.execute(
            "INSERT INTO roles(organization_id,role_definition_id,name,permissions) SELECT $1,id,'Empty observer','[]' FROM role_definitions WHERE code='observer'",
            ORG,
        )
        await f.admin.execute(
            "INSERT INTO organization_user_roles(organization_id,organization_user_id,role_id) SELECT $1,$2,id FROM roles WHERE name='Empty observer'",
            ORG,
            MEMBER,
        )
    if case == "revoked":
        await f.admin.execute(
            "UPDATE user_sessions SET revoked_at=now() WHERE id=$1", f.session_id
        )
    if case == "inactive_member":
        await f.admin.execute(
            "UPDATE organization_users SET is_active=FALSE WHERE id=$1", MEMBER
        )
    if case == "inactive_user":
        await f.admin.execute("UPDATE users SET is_active=FALSE WHERE id=$1", USER)
    if case == "inactive_org":
        await f.admin.execute(
            "UPDATE organizations SET is_active=FALSE WHERE id=$1", ORG
        )
    if case == "platform":
        await f.admin.execute(
            "INSERT INTO platform_admins(user_id,role_code) VALUES ($1,'platform_admin')",
            USER,
        )
    data = envelope()
    if case == "other_tenant":
        data["payload"]["match_id"] = MATCH.replace("31000000", "32000000")
    event = classify_organization_event(data)
    assert event is not None
    now = datetime.now(timezone.utc)
    principal = Principal(
        UUID(ORG),
        UUID(USER),
        f.session_id,
        (SocketRecipient("socket", "generation", now + timedelta(minutes=10)),),
    )
    authorizer = RealtimeAuthorizer(lambda: AsyncSession(f.engine), lambda: now)
    decision = (await authorizer.evaluate_batch(event, [principal]))[0].decision
    app = FastAPI()

    @app.get("/live")
    async def read():
        async with AsyncSession(f.engine) as db:
            return await LiveMatchService(db).snapshot(
                f.context, UUID(data["payload"]["match_id"]), f.session_id
            )

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/live")
    expected = case in {"view", "both", "assigned", "multirole"}
    assert (response.status_code == 200) is expected
    assert decision == (Decision.ALLOW if expected else Decision.DENY)


# ---------------------------------------------------------------------------
# B3 T50: el aviso público nuevo solo se emite tras revalidar visibilidad actual
# ---------------------------------------------------------------------------

LIVE_PUBLIC = "MATCH_LIVE_PUBLIC_UPDATED"
FOREIGN = "32000000-0000-4000-8000-"


def public_envelope(event_type=LIVE_PUBLIC, **payload):
    return {
        "event_id": str(uuid4()),
        "organization_id": ORG,
        "event_type": event_type,
        "payload": {"match_id": MATCH, "tournament_id": TOURNAMENT, **payload},
    }


class RecordingDelivery:
    def __init__(self):
        self.envelopes = []

    async def deliver(self, envelope):
        self.envelopes.append(envelope)


def dispatch_harness(fixture, monkeypatch):
    from app import main

    calls = []

    async def emit(name, payload, **kwargs):
        calls.append((name, payload, kwargs))

    delivery = RecordingDelivery()
    monkeypatch.setattr(
        main, "SessionFactory", lambda: AsyncSession(fixture.engine)
    )
    monkeypatch.setattr(main.sio, "emit", emit)
    monkeypatch.setattr(main, "private_delivery", delivery)
    return main, calls, delivery


async def emit_envelope(main, data):
    await main.emit_domain_event(main.parse_envelope({"event": json.dumps(data)}))


async def start_clock(f):
    """Materializa ``match_live_state``: el partido entra en la proyección."""
    await f.call(
        "execute", command("start_clock", segment_id=SEGMENT_FIRST)
    )


async def test_public_dispatch_emits_after_current_visibility_revalidation(
    live_service_db, monkeypatch
):
    await start_clock(live_service_db)
    main, calls, delivery = dispatch_harness(live_service_db, monkeypatch)
    data = public_envelope()
    await emit_envelope(main, data)
    assert calls == [
        (
            LIVE_PUBLIC,
            {
                "event_id": data["event_id"],
                "match_id": MATCH,
                "tournament_id": TOURNAMENT,
            },
            {"room": f"tournament:{TOURNAMENT}"},
        )
    ]
    assert len(delivery.envelopes) == 1


async def test_public_dispatch_tournament_hidden_after_enqueue_does_not_emit(
    live_service_db, monkeypatch
):
    await start_clock(live_service_db)
    main, calls, _ = dispatch_harness(live_service_db, monkeypatch)
    await live_service_db.admin.execute(
        "UPDATE tournaments SET status='draft' WHERE id=$1", TOURNAMENT
    )
    await emit_envelope(main, public_envelope())
    assert calls == []


@pytest.mark.parametrize(
    "statement",
    [
        # Organización inactiva tras encolar: ya no es proyección autorizada.
        "UPDATE organizations SET is_active=FALSE WHERE id='" + ORG + "'",
        # Versión archivada tras encolar: sale de la selección publicada.
        "UPDATE tournament_versions SET status='archived' WHERE tournament_id='"
        + TOURNAMENT + "'",
    ],
    ids=["organization_inactive", "version_archived"],
)
async def test_public_dispatch_match_out_of_projection_does_not_emit(
    live_service_db, monkeypatch, statement
):
    await start_clock(live_service_db)
    main, calls, _ = dispatch_harness(live_service_db, monkeypatch)
    await live_service_db.admin.execute(statement)
    await emit_envelope(main, public_envelope())
    assert calls == []


@pytest.mark.parametrize(
    "organization_id,match_id,tournament_id",
    [
        (FOREIGN + "000000000001", MATCH, TOURNAMENT),
        (ORG, FOREIGN + "000000000050", TOURNAMENT),
        (ORG, MATCH, FOREIGN + "000000000010"),
        (FOREIGN + "000000000001", FOREIGN + "000000000050", FOREIGN + "000000000010"),
    ],
    ids=["foreign_org", "foreign_match", "foreign_tournament", "all_foreign"],
)
async def test_public_dispatch_foreign_references_do_not_emit(
    live_service_db, monkeypatch, organization_id, match_id, tournament_id
):
    main, calls, _ = dispatch_harness(live_service_db, monkeypatch)
    data = public_envelope(match_id=match_id, tournament_id=tournament_id)
    data["organization_id"] = organization_id
    await emit_envelope(main, data)
    assert calls == []


@pytest.mark.parametrize(
    "event_type,extra",
    [
        # Nombre privado compartiendo identificadores: nunca sale al room público.
        ("MATCH_LIVE_UPDATED", {}),
        ("MATCH_LIVE_UPDATED", {"scope": "organization"}),
        # El nombre público no acepta ámbito organizativo ni claves extra.
        (LIVE_PUBLIC, {"scope": "organization"}),
        (LIVE_PUBLIC, {"home_score": 3}),
        (LIVE_PUBLIC, {"match_id": None}),
        (LIVE_PUBLIC, {"match_id": "no-uuid"}),
        (LIVE_PUBLIC, {"tournament_id": "no-uuid"}),
    ],
    ids=[
        "private_name",
        "private_name_scoped",
        "public_scoped",
        "extra_key",
        "null_match",
        "bad_match",
        "bad_tournament",
    ],
)
async def test_public_dispatch_rejects_private_or_malformed_wires(
    live_service_db, monkeypatch, event_type, extra
):
    main, calls, _ = dispatch_harness(live_service_db, monkeypatch)
    await emit_envelope(main, public_envelope(event_type=event_type, **extra))
    assert calls == []


async def test_public_dispatch_query_failure_does_not_emit(
    live_service_db, monkeypatch
):
    from app import main

    calls = []

    async def emit(name, payload, **kwargs):
        calls.append((name, payload, kwargs))

    def broken_factory():
        raise RuntimeError("consulta de visibilidad caída")

    monkeypatch.setattr(main, "SessionFactory", broken_factory)
    monkeypatch.setattr(main.sio, "emit", emit)
    monkeypatch.setattr(main, "private_delivery", RecordingDelivery())
    with pytest.raises(RuntimeError):
        await emit_envelope(main, public_envelope())
    assert calls == []


async def test_public_dispatch_preserves_previous_public_events(
    live_service_db, monkeypatch
):
    main, calls, _ = dispatch_harness(live_service_db, monkeypatch)
    await live_service_db.admin.execute(
        "UPDATE tournaments SET status='draft' WHERE id=$1", TOURNAMENT
    )
    for name in ("MATCH_UPDATED", "MATCH_CLOSED", "STANDINGS_UPDATED"):
        await emit_envelope(main, public_envelope(event_type=name))
    assert [c[0] for c in calls] == ["MATCH_UPDATED", "MATCH_CLOSED", "STANDINGS_UPDATED"]
    assert all(c[2] == {"room": f"tournament:{TOURNAMENT}"} for c in calls)


async def test_public_dispatch_draft_never_broadcasts_to_organization_room(
    live_service_db, monkeypatch
):
    await start_clock(live_service_db)
    main, calls, delivery = dispatch_harness(live_service_db, monkeypatch)
    await emit_envelope(main, public_envelope())
    await emit_envelope(
        main, public_envelope(event_type="MATCH_LIVE_UPDATED", scope="organization")
    )
    rooms = [c[2].get("room", "") for c in calls]
    assert all(not room.startswith("organization:") for room in rooms)
    # Solo el aviso privado llega a la entrega organizativa autorizada; el
    # público pasa por el filtro pero el catálogo lo descarta.
    assert len(delivery.envelopes) == 2


@pytest.mark.parametrize('flow', [{'schema': 59}], indirect=True)
async def test_multiprocess_delivery_two_apis_two_tenants(flow):
    """T56: sockets reales en dos API y dos tenants; solo los tres ids de wire."""

    import httpx
    from realtime_process import ProcessCluster

    denied_user = uuid4()
    await flow.admin.execute("""INSERT INTO users(id,email,password_hash,full_name)
        VALUES($1,$2,'hash','Denied live');""", denied_user, f'{denied_user}@example.test')
    member = await flow.admin.fetchval(
        "INSERT INTO organization_users(organization_id,user_id) VALUES($1,$2) RETURNING id",
        UUID(ORG), denied_user)
    role = await flow.admin.fetchval(
        """INSERT INTO roles(organization_id,role_definition_id,name,permissions)
        SELECT $1,id,'Denied live','[]'::jsonb FROM role_definitions
        WHERE code='member' RETURNING id""", UUID(ORG))
    if role is None:
        role = await flow.admin.fetchval(
            """INSERT INTO roles(organization_id,role_definition_id,name,permissions)
            SELECT $1,id,'Denied live','[]'::jsonb FROM role_definitions LIMIT 1 RETURNING id""",
            UUID(ORG))
    await flow.admin.execute(
        "INSERT INTO organization_user_roles(organization_id,organization_user_id,role_id) VALUES($1,$2,$3)",
        UUID(ORG), member, role)

    async with ProcessCluster(flow) as cluster:
        identity = await cluster.identity(USER)
        denied = await cluster.identity(str(denied_user))
        other = await cluster.identity(USER.replace('31000000', '32000000'))
        left = await cluster.connect(0, identity)
        right = await cluster.connect(1, identity)
        denied_wire = await cluster.connect(0, denied)
        outsider = await cluster.connect(1, other, ORG.replace('31000000', '32000000'))
        assert (await cluster.rpc(0, 'probe'))['pid'] != (await cluster.rpc(1, 'probe'))['pid']

        event = await cluster.publish(
            event_type='MATCH_LIVE_UPDATED',
            payload={'scope': 'organization', 'match_id': MATCH, 'tournament_id': TOURNAMENT})
        await cluster.settle(event)
        expected = {'event_id': event, 'match_id': MATCH, 'tournament_id': TOURNAMENT}
        for wire in (left, right):
            assert wire.payload(event) == expected
        for denied_socket in (denied_wire, outsider):
            assert denied_socket.payload(event) is None
            # Cero frames de dominio en ajenos o denegados: solo control.
            assert not any(name == 'MATCH_LIVE_UPDATED' for name, _ in denied_socket.frames)

        # Lectura HTTP posterior sobre el montaje real: el mismo partido.
        async with httpx.AsyncClient() as http:
            response = await http.get(
                f'http://127.0.0.1:{cluster.children[0][2]}/api/v1/matches/{MATCH}/live/access',
                headers={'Authorization': f'Bearer {identity["token"]}',
                         'X-Organization-ID': ORG})
        assert response.status_code == 200
        assert set(response.json()) == {
            'can_view', 'can_operate', 'can_close', 'available'}
        assert response.json()['can_view'] is True


LIVE_WIRE = {'scope': 'organization', 'match_id': MATCH, 'tournament_id': TOURNAMENT}


@pytest.mark.parametrize('flow', [{'schema': 59}], indirect=True)
@pytest.mark.parametrize('withdrawal', ['session', 'membership', 'roles', 'live_view'])
async def test_multiprocess_recovery_cutoff_fail_closed_no_replay(flow, withdrawal):
    """T57: retirada confirmada en la barrera de evaluación; nada llega tras el corte."""

    from realtime_process import ProcessCluster

    async with ProcessCluster(flow) as cluster:
        identity = await cluster.identity(USER)
        left = await cluster.connect(0, identity)
        right = await cluster.connect(1, identity)
        outsider = await cluster.connect(
            1, await cluster.identity(USER.replace('31000000', '32000000')),
            ORG.replace('31000000', '32000000'))
        event = await cluster.publish(
            event_type='MATCH_LIVE_UPDATED', payload=dict(LIVE_WIRE))
        await cluster.settle(event)
        for wire in (left, right):
            assert wire.payload(event) == {
                'event_id': event, 'match_id': MATCH, 'tournament_id': TOURNAMENT}

        pending_event = await cluster.enqueue(
            event_type='MATCH_LIVE_UPDATED', payload=dict(LIVE_WIRE))
        await cluster.gate(pending_event)
        await cluster.flush()
        await cluster.paused()
        if withdrawal == 'live_view':
            await flow.admin.execute(
                "UPDATE roles SET permissions=permissions-'VIEW_MATCH_LIVE_DRAFT' WHERE organization_id=$1",
                UUID(ORG))
            # La lectura clásica sigue autorizada (permiso distinto); lo
            # denegado es solo el canal live, visible en /live/access.
            import httpx
            async with httpx.AsyncClient() as http:
                access = await http.get(
                    f'http://127.0.0.1:{cluster.children[1][2]}/api/v1/matches/{MATCH}/live/access',
                    headers={'Authorization': f'Bearer {identity["token"]}',
                             'X-Organization-ID': ORG})
            assert access.status_code == 200
            assert access.json()['can_view'] is False
        else:
            await cluster.withdraw(withdrawal, identity)
            assert (await cluster.http(1, identity)) in (401, 403, 404)
        await cluster.release()
        await cluster.settle(pending_event)
        # El corte evalúa al inicio del lote: frames ya comprometidos no se
        # prometen «retirar», y nada nuevo atraviesa sin replay.
        assert left.payload(pending_event) is None
        assert right.payload(pending_event) is None
        assert outsider.payload(event) is None
        assert outsider.payload(pending_event) is None


@pytest.mark.parametrize('flow', [{'schema': 59}], indirect=True)
async def test_multiprocess_load_1000_sockets_257_principals(flow):
    """T77: carga reproducible con receptores reales — 257 principales
    (lote 256/1) con ~4 sockets cada uno (~1028) repartidos entre dos APIs,
    ráfaga de eventos y fallo/recuperación; registra p50/p95, lotes SQL y RSS,
    sin duplicación ni backlog."""

    import asyncio
    from time import perf_counter
    from realtime_process import ProcessCluster, percentile

    PRINCIPALS = 257
    SOCKETS_EACH = 4
    BURST = 6

    async with ProcessCluster(flow) as cluster:
        principals = await cluster.identities(PRINCIPALS)
        wires = []
        started = perf_counter()
        # Conexión concurrente por lotes para caber en el presupuesto del test.
        pending = [cluster.connect(0, identity) for identity in principals
                   for _ in range(SOCKETS_EACH)]
        for offset in range(0, len(pending), 128):
            wires.extend(await asyncio.gather(*pending[offset:offset + 128]))
        # Dos APIs: los principales cargan el proceso 0 (lote 256/N) y un
        # testigo sano escucha en el proceso 1.
        healthy_wires = [
            await cluster.connect(1, principals[0]),
            await cluster.connect(1, principals[1])]
        print(f'LOAD connect {len(wires) + len(healthy_wires)} sockets: {perf_counter() - started:.1f}s')
        async with asyncio.timeout(60):
            while (await cluster.rpc(0, 'probe'))['connections'] != len(wires):
                await asyncio.sleep(0.05)
            while (await cluster.rpc(1, 'probe'))['connections'] != 2:
                await asyncio.sleep(0.05)
        rss_before = [await cluster.rpc(i, 'probe') for i in range(2)]

        # Ráfaga: cada evento debe llegar a cada socket exactamente una vez.
        latencies = []
        events = []
        for _ in range(BURST):
            sent = perf_counter()
            event = await cluster.publish(
                event_type='MATCH_LIVE_UPDATED', payload=dict(LIVE_WIRE))
            await cluster.settle(event)
            for wire in wires:
                latencies.append(wire.received_at(event) - sent)
            events.append(event)
        for event in events:
            for wire in wires + healthy_wires:
                occurrences = sum(
                    1 for _, payload in wire.frames
                    if payload.get('event_id') == event)
                assert occurrences == 1
        print(f'LOAD delivery p50={percentile(latencies, 0.5) * 1000:.1f}ms '
              f'p95={percentile(latencies, 0.95) * 1000:.1f}ms n={len(latencies)}')
        probes = [await cluster.rpc(i, 'probe') for i in range(2)]
        for index, probe in enumerate(probes):
            assert all(size <= 256 for size in probe['batches'])
            assert probe['counts'].get('calls', 0) >= BURST
            print(f'LOAD api{index} batches={probe["batches"]} '
                  f'calls={probe["counts"].get("calls")} '
                  f'rss={rss_before[index]["rss_kib"]}->{probe["rss_kib"]}KiB '
                  f'current={probe["current_rss_kib"]}KiB')

        # Fallo en la API 0 durante la ráfaga: suspensión fail-closed.
        await cluster.rpc(0, 'mode', values={'fail': True})
        lost = await cluster.publish(
            event_type='MATCH_LIVE_UPDATED', payload=dict(LIVE_WIRE))
        await cluster.settle(lost)
        dropped = wires
        healthy = healthy_wires
        for wire in dropped:
            assert wire.payload(lost) is None
        for wire in healthy:
            assert wire.payload(lost) is not None
        probe0 = await cluster.rpc(0, 'probe')
        print(f'LOAD api0 suspended={probe0["suspended"]} '
              f'controls={probe0["controls"]}')
        assert probe0['suspended'] >= 1

        # Recuperación: las sesiones vigentes se re-suscriben y reciben el
        # evento fresco; el backlog perdido nunca se reproduce; sin duplicados.
        await cluster.rpc(0, 'mode', values={'fail': False})
        await cluster.rpc(0, 'recover')
        fresh = await cluster.publish(
            event_type='MATCH_LIVE_UPDATED', payload=dict(LIVE_WIRE))
        await cluster.settle(fresh)
        for wire in dropped:
            assert wire.payload(lost) is None
            occurrences = sum(
                1 for _, payload in wire.frames
                if payload.get('event_id') == fresh)
            assert occurrences == 1
        for wire in healthy:
            occurrences = sum(
                1 for _, payload in wire.frames
                if payload.get('event_id') == fresh)
            assert occurrences == 1
        rss_after = [await cluster.rpc(i, 'probe') for i in range(2)]
        for index in range(2):
            growth = rss_after[index]['current_rss_kib'] - rss_before[index]['current_rss_kib']
            print(f'LOAD api{index} rss growth={growth}KiB')
            # Sin fuga: el crecimiento queda por debajo de un tope razonable
            # para ~500 sockets (no se exige memoria constante).
            assert growth < 128 * 1024


@pytest.mark.parametrize('flow', [{'schema': 59}], indirect=True)
async def test_multiprocess_restart_recovery_preserves_accepted_state(flow):
    """T76: suspensión repetida + revocación durante el fallo + reinicio real de
    la API; la reconexión al otro proceso conserva lo aceptado, sin replay del
    backlog privado ni recuperación de permisos retirados."""

    from realtime_process import ProcessCluster

    async with ProcessCluster(flow) as cluster:
        victim, healthy = await cluster.identities(2)
        affected = await cluster.connect(0, victim)
        independent = await cluster.connect(1, healthy)

        accepted = await cluster.publish(
            event_type='MATCH_LIVE_UPDATED', payload=dict(LIVE_WIRE))
        await cluster.settle(accepted)
        assert affected.payload(accepted) is not None
        assert independent.payload(accepted) is not None

        # Suspensión por fallo SQL repetida (dos rondas) con recuperación real.
        lost_ids = []
        for _ in range(2):
            await cluster.rpc(0, 'mode', values={'fail': True})
            lost = await cluster.publish(
                event_type='MATCH_LIVE_UPDATED', payload=dict(LIVE_WIRE))
            await cluster.settle(lost)
            lost_ids.append(lost)
            assert affected.payload(lost) is None
            assert independent.payload(lost) is not None
            probe = await cluster.rpc(0, 'probe')
            assert probe['suspended'] >= 1
            await cluster.rpc(0, 'mode', values={'fail': False})
            await cluster.rpc(0, 'recover')

        # Revocación durante el fallo: VIEW_MATCH_LIVE_DRAFT se retira al rol
        # del socket suspendido mientras `healthy` conserva un rol propio; la
        # lectura clásica no usa ese permiso.
        healthy_member = await flow.admin.fetchval(
            'SELECT id FROM organization_users WHERE organization_id=$1 AND user_id=$2',
            UUID(ORG), UUID(healthy['user']))
        await flow.admin.execute('''WITH newrole AS (
            INSERT INTO roles (organization_id,role_definition_id,name,permissions)
            SELECT $1, role_definition_id, 'Lector live', permissions
            FROM roles WHERE organization_id=$1 LIMIT 1 RETURNING id)
            UPDATE organization_user_roles SET role_id=(SELECT id FROM newrole)
            WHERE organization_id=$1 AND organization_user_id=$2''',
            UUID(ORG), healthy_member)
        await flow.admin.execute(
            "UPDATE roles SET permissions=permissions-'VIEW_MATCH_LIVE_DRAFT' WHERE organization_id=$1 AND name<>'Lector live'",
            UUID(ORG))
        for _ in range(2):
            await cluster.rpc(0, 'recover')
        # El permiso retirado no se recupera tras la suspensión.
        import httpx
        async with httpx.AsyncClient() as http:
            access = await http.get(
                f'http://127.0.0.1:{cluster.children[0][2]}/api/v1/matches/{MATCH}/live/access',
                headers={'Authorization': f'Bearer {victim["token"]}',
                         'X-Organization-ID': ORG})
        assert access.status_code == 200
        assert access.json()['can_view'] is False

        # Reinicio real del proceso 0: la conexión cae y el relay vuelve limpio.
        await cluster.restart(0)
        await cluster.fence()
        # Reconexión al otro proceso con la misma identidad: solo lo vigente.
        reconnected = await cluster.connect(1, victim)
        fresh = await cluster.publish(
            event_type='MATCH_LIVE_UPDATED', payload=dict(LIVE_WIRE))
        await cluster.settle(fresh)
        assert reconnected.payload(fresh) is None
        assert independent.payload(fresh) is not None
        # Nada del backlog privado llega: ni antes ni después del reinicio.
        # Un RESYNC de control sí puede alcanzar el socket suspendido al
        # recuperar (su sesión sigue válida); nunca un evento de dominio.
        for lost in lost_ids:
            assert affected.payload(lost) is None
            assert reconnected.payload(lost) is None
        assert not any(
            name == 'MATCH_LIVE_UPDATED'
            for name, _ in affected.frames
            if _ is not None and _.get('event_id') in lost_ids)


# ---------------------------------------------------------------------------
# T79: privacidad — la salida técnica/pública nunca transporta datos del borrador
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "extra",
    [
        # Datos personales/de evento del borrador: jamás en el wire privado.
        {"player_id": str(uuid4())},
        {"player_name": "Nombre Privado"},
        {"assist_player_id": str(uuid4())},
        {"events": [{"event_type": "goal", "player_id": str(uuid4())}]},
        {"metadata": {"note": "dato privado"}},
        {"birth_date": "2000-01-01"},
        {"document_number": "123456789"},
        # Identificadores internos de estado o usuario.
        {"revision": 7},
        {"content_revision": 3},
        {"session_id": str(uuid4())},
        {"user_id": str(uuid4())},
        {"home_score": 2},
    ],
    ids=[
        "player_id", "player_name", "assist", "events", "metadata",
        "birth_date", "document", "revision", "content_revision",
        "session_id", "user_id", "score",
    ],
)
def test_privacy_live_wire_rejects_personal_or_internal_fields(extra):
    """El catálogo privado descarta cualquier envoltura con campos ajenos a los tres ids."""
    assert classify_organization_event(envelope(**extra)) is None


@pytest.mark.parametrize(
    "event_type",
    [
        "VERIFICATION_OUTBOX_PROBE",
        "SANCTION_CASE_NOTICE_INTERNAL",
        "SANCTION_CASE_NOTICE_EMAIL",
        "MATCH_LIVE_UNKNOWN_KIND",
        "PLAYER_SUSPENSION_NOTICE",
    ],
    ids=["probe", "f9_internal", "f9_email", "unknown_live", "player_sanction"],
)
def test_privacy_unknown_catalog_and_f9_never_route_as_live(event_type):
    """Catálogo desconocido, sonda de verificación y avisos F9 no son eventos live."""
    data = envelope()
    data["event_type"] = event_type
    assert classify_organization_event(data) is None


async def test_privacy_public_and_technical_output_never_carry_draft_detail(
    live_service_db, monkeypatch
):
    """Wire público, outbox y auditoría solo transportan identificadores mínimos."""
    f = live_service_db
    await f.permissions(["OPERATE_MATCH_LIVE", "VIEW_MATCH_LIVE_DRAFT"])
    await f.call("execute", command("start_clock", segment_id=SEGMENT_FIRST))
    private_event = goal()
    private_event["event_type"] = "red_card"
    private_event["metadata"] = {"red_card_type": "direct_red"}
    await f.call("execute", command("add_event", 1, event=private_event))

    # Outbox: ambos wires solo llevan los ids acordados, nunca el hecho ni el jugador.
    rows = await live_outbox(f)
    assert rows
    for row in rows:
        payload = json.loads(row["payload"])
        allowed = {"match_id", "tournament_id"}
        if row["event_type"] == "MATCH_LIVE_UPDATED":
            allowed.add("scope")
        assert set(payload) == allowed
        serialized = json.dumps(payload)
        for forbidden in ("player", "Nombre", "Privado", "assist", "metadata", "goal"):
            assert forbidden not in serialized

    # Auditoría administrativa: solo tipo, comando y revisión — sin el evento.
    audit = await f.admin.fetch(
        "SELECT payload FROM administrative_audit_logs WHERE action='MATCH_LIVE_COMMAND'"
    )
    assert len(audit) == 2
    for row in audit:
        payload = json.loads(row["payload"])
        assert set(payload) == {"command_id", "type", "revision"}
        assert "event" not in payload

    # Emisión pública revalidada: el emit solo lleva los tres ids del aviso.
    main, calls, _ = dispatch_harness(f, monkeypatch)
    await emit_envelope(main, public_envelope())
    assert calls == [
        (LIVE_PUBLIC, {
            "event_id": calls[0][1]["event_id"],
            "match_id": MATCH,
            "tournament_id": TOURNAMENT,
        }, {"room": f"tournament:{TOURNAMENT}"})
    ]

    # La lectura autorizada sí devuelve el detalle; la pública jamás lo contiene.
    snapshot = await f.call("snapshot")
    assert snapshot.events and snapshot.events[0].client_event_id == private_event["client_event_id"]


@pytest.mark.parametrize('flow', [{'schema': 59}], indirect=True)
async def test_multiprocess_recovery_sql_failure_suspends_and_resyncs(flow):
    """T57: fallo SQL suspende fail-closed; `recover` reanuda solo lo vigente."""

    from realtime_process import ProcessCluster

    async with ProcessCluster(flow) as cluster:
        victim, healthy = await cluster.identities(2)
        affected = await cluster.connect(0, victim)
        independent = await cluster.connect(1, healthy)
        await cluster.rpc(0, 'mode', values={'fail': True})
        lost = await cluster.publish(
            event_type='MATCH_LIVE_UPDATED', payload=dict(LIVE_WIRE))
        await cluster.settle(lost)
        assert affected.payload(lost) is None
        assert independent.payload(lost) is not None
        # Sesión/JWT expirado de verdad: el socket suspendido no se reanuda.
        await flow.admin.execute(
            "UPDATE user_sessions SET expires_at=CURRENT_TIMESTAMP-INTERVAL '1 hour' WHERE id=$1",
            victim['session'])
        await cluster.rpc(0, 'mode', values={'fail': False})
        for _ in range(2):
            await cluster.rpc(0, 'recover')
            probe = await cluster.rpc(0, 'probe')
        # Fail-closed: la sesión expirada no vuelve a quedar suscripta.
        assert probe['suspended'] == 0
        await cluster.fence()
        assert affected.payload(lost) is None
        assert not any(
            name == 'RESYNC' and value['reason'] == 'RELAY_START'
            for name, value in affected.frames)
        fresh = await cluster.publish(
            event_type='MATCH_LIVE_UPDATED', payload=dict(LIVE_WIRE))
        await cluster.settle(fresh)
        assert affected.payload(fresh) is None
        assert independent.payload(fresh) is not None
        assert (await cluster.http(0, victim)) in (401, 403)
