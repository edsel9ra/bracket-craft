"""Doble amarilla (spec 017, T4): función pura, código y validación del cierre.

**Regla (RF-006).** Una roja marcada como ``double_yellow_red`` exige
**exactamente dos** amarillas previas del **mismo jugador** en el **mismo
partido**. Cualquier otro caso —cero, una o tres o más— es **409** con el
``code`` aditivo ``DOUBLE_YELLOW_INCONSISTENT`` y no escribe nada.

**Qué significa «previas»** (decisión de esta tarea, fijada por RF-006: «se
cuentan solo los eventos de ese partido, anteriores al minuto de la roja en
orden canónico»):

* el orden canónico del acta es ``(minute, added_minute, índice del acta)``, el
  mismo que usan RF-005 (estado en campo), la proyección por segmento y el
  replay del motor;
* cuentan las amarillas **estrictamente anteriores** a la roja en ese orden: la
  roja no es una amarilla, dos eventos del mismo minuto se desempatan por el
  índice del acta y una amarilla posterior a la roja (mismo minuto con índice
  mayor, ``added_minute`` mayor o minuto mayor) **no** cuenta;
* no hay ventana de «misma jugada»: el acta no declara jugadas, así que la
  única lectura determinista es la del orden canónico (RNF-006).

**Fuente del conteo.** Solo el acta de la petición: dos amarillas guardadas en
otro partido del mismo jugador no cuentan (RF-006). Las actas ya cerradas no se
revalidan, porque el estado del partido las rechaza antes.

**Lo que no cambia.** La roja directa (``direct_red`` o sin ``metadata``) no
exige amarillas; una segunda amarilla **no** crea una roja (DU-10: la registra
el operador); y la acumulación de amarillas de ``evaluate_suspensions`` sigue
siendo otra cosa (sanciones por umbral, no coherencia del acta).

Las pruebas de precedencia con el resto de pasos del orden viven también en
``test_close_validation_order.py``, donde el paso 10 entra en la matriz.
"""

from __future__ import annotations

import json
from uuid import UUID

import pytest
from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request

import app.main as main_module
from app.modules.matches.errors import (
    DOUBLE_YELLOW_INCONSISTENT,
    DoubleYellowInconsistent,
)
from app.modules.matches.router import close_match
from app.modules.matches.schemas import CloseMatchReportDTO, MatchEventPayload
from app.modules.matches.service import double_yellow_violations
from db_helpers import set_tenant_context
from tests.event_ids import event_id
from tests.test_substitutions import (
    committed_application,
    create_closable_match,
    context_for,
    report,
    seeded_match,
)

TEAM = UUID(int=7001)


# ---------------------------------------------------------------------------
# La función pura: eventos del acta, sin base, sin reloj
# ---------------------------------------------------------------------------


def yellow(
    player_id: UUID,
    *,
    minute: int = 20,
    added_minute: int = 0,
    team_id: UUID = TEAM,
) -> dict:
    """Una amarilla del acta, en la forma de ``mapping`` que admite la función."""

    return {
        "event_type": "yellow_card",
        "team_id": team_id,
        "player_id": player_id,
        "minute": minute,
        "added_minute": added_minute,
    }


def red(
    player_id: UUID,
    *,
    minute: int = 40,
    added_minute: int = 0,
    team_id: UUID = TEAM,
    red_card_type: str | None = "double_yellow_red",
) -> dict:
    """Una roja del acta; por defecto, marcada como doble amarilla."""

    event = {
        "event_type": "red_card",
        "team_id": team_id,
        "player_id": player_id,
        "minute": minute,
        "added_minute": added_minute,
    }
    if red_card_type is not None:
        event["metadata"] = {"red_card_type": red_card_type}
    return event


def test_exactly_two_previous_yellows_are_accepted():
    player = UUID(int=1)

    assert double_yellow_violations([yellow(player), yellow(player, minute=30), red(player)]) == ()


def test_the_canonical_order_does_not_depend_on_the_payload_order():
    player = UUID(int=1)

    # La roja llega primero en el payload y sigue siendo la última del acta.
    assert double_yellow_violations([red(player), yellow(player, minute=30), yellow(player)]) == ()


def test_zero_previous_yellows_is_a_violation():
    player = UUID(int=1)

    assert double_yellow_violations([red(player)]) == (0,)


def test_one_previous_yellow_is_a_violation():
    player = UUID(int=1)

    assert double_yellow_violations([yellow(player), red(player)]) == (1,)


def test_three_previous_yellows_are_a_violation():
    player = UUID(int=1)

    events = [
        yellow(player, minute=10),
        yellow(player, minute=20),
        yellow(player, minute=30),
        red(player),
    ]

    # «Exactamente dos»: tres no vale (DU-10 y RF-006).
    assert double_yellow_violations(events) == (3,)


def test_yellows_of_another_player_do_not_count():
    player = UUID(int=1)
    other = UUID(int=2)

    events = [yellow(other, minute=10), yellow(other, minute=20), red(player)]

    assert double_yellow_violations(events) == (2,)


def test_a_direct_red_needs_no_yellows():
    player = UUID(int=1)

    assert double_yellow_violations([red(player, red_card_type="direct_red")]) == ()
    # Sin `metadata` la roja es directa por defecto (contrato del catálogo).
    assert double_yellow_violations([red(player, red_card_type=None)]) == ()


def test_yellows_after_the_red_do_not_count():
    player = UUID(int=1)

    events = [yellow(player, minute=60), yellow(player, minute=70), red(player, minute=30)]

    assert double_yellow_violations(events) == (2,)


def test_added_minute_orders_the_acta():
    player = UUID(int=1)

    # 45+2 y 45+4 son anteriores a 45+5; 45+6 no.
    before = [
        yellow(player, minute=45, added_minute=2),
        yellow(player, minute=45, added_minute=4),
        red(player, minute=45, added_minute=5),
    ]
    assert double_yellow_violations(before) == ()

    after = [
        yellow(player, minute=45, added_minute=2),
        red(player, minute=45, added_minute=3),
        yellow(player, minute=45, added_minute=4),
    ]
    assert double_yellow_violations(after) == (1,)


def test_a_minute_tie_is_broken_by_the_acta_index():
    player = UUID(int=1)

    # La roja es la primera del minuto 30: ninguna amarilla le precede.
    first = [red(player, minute=30), yellow(player, minute=30), yellow(player, minute=30)]
    assert double_yellow_violations(first) == (0,)
    # La roja en medio: solo cuenta la primera amarilla.
    middle = [yellow(player, minute=30), red(player, minute=30), yellow(player, minute=30)]
    assert double_yellow_violations(middle) == (1,)
    # La roja al final del minuto: cuentan las dos.
    last = [yellow(player, minute=30), yellow(player, minute=30), red(player, minute=30)]
    assert double_yellow_violations(last) == ()


def test_the_violations_are_returned_in_canonical_order():
    first = UUID(int=1)
    second = UUID(int=2)

    # En el payload la roja del minuto 60 va antes; el acta la ordena al final.
    events = [red(first, minute=60), red(second, minute=20)]

    assert double_yellow_violations(tuple(events)) == (1, 0)


def test_two_double_yellow_reds_count_the_acta_yellows_accumulated():
    player = UUID(int=1)

    events = [
        yellow(player, minute=10),
        yellow(player, minute=20),
        yellow(player, minute=30),
        red(player, minute=40),
        red(player, minute=80),
    ]

    # El contador es el de amarillas del acta del jugador y no se reinicia con la
    # roja; una segunda roja del mismo jugador es, de todos modos, un defecto del
    # paso 8 (estado en campo) en un acta real.
    assert double_yellow_violations(events) == (3, 4)


def test_the_same_act_gives_the_same_result():
    player = UUID(int=1)
    events = [yellow(player, minute=20), yellow(player, minute=20), red(player, minute=20)]

    assert double_yellow_violations(events) == double_yellow_violations(tuple(events)) == ()


def test_it_accepts_the_payload_objects_of_the_request():
    player = UUID(int=1)

    payload = [
        MatchEventPayload(
            client_event_id=event_id("dy-payload-yellow-1"),
            event_type="yellow_card",
            team_id=TEAM,
            player_id=player,
            minute=20,
            segment_id=UUID(int=7003),
        ),
        MatchEventPayload(
            client_event_id=event_id("dy-payload-yellow-2"),
            event_type="yellow_card",
            team_id=TEAM,
            player_id=player,
            minute=30,
            segment_id=UUID(int=7003),
        ),
        MatchEventPayload(
            client_event_id=event_id("dy-payload-red"),
            event_type="red_card",
            team_id=TEAM,
            player_id=player,
            minute=40,
            segment_id=UUID(int=7003),
            metadata={"red_card_type": "double_yellow_red"},
        ),
    ]

    assert double_yellow_violations(payload) == ()


def test_an_empty_act_has_no_violations():
    assert double_yellow_violations([]) == ()


# ---------------------------------------------------------------------------
# Contrato HTTP del código nuevo (RF-010)
# ---------------------------------------------------------------------------


def _request() -> Request:
    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/v1/matches/00000000-0000-4000-8000-000000000001/close",
            "headers": [],
            "query_string": b"",
        }
    )


def test_the_double_yellow_error_is_registered_with_the_coded_handler():
    assert main_module.api.exception_handlers.get(DoubleYellowInconsistent) is (
        main_module._coded_exception_handler
    )


async def test_the_double_yellow_error_answers_409_with_a_string_detail_and_the_code():
    handler = main_module.api.exception_handlers[DoubleYellowInconsistent]

    response = await handler(_request(), DoubleYellowInconsistent())

    body = json.loads(response.body)
    assert response.status_code == 409
    assert body["code"] == DOUBLE_YELLOW_INCONSISTENT
    assert isinstance(body["detail"], str) and body["detail"]
    assert response.headers["cache-control"] == "no-store"
# ---------------------------------------------------------------------------
# El cierre (opt-in con base): 409 con `code`, sin escrituras, y el acta válida
# ---------------------------------------------------------------------------


def yellow_payload(
    player_id: UUID,
    *,
    team_id: UUID,
    segment_id: UUID,
    minute: int,
    label: str,
    added_minute: int = 0,
) -> MatchEventPayload:
    return MatchEventPayload(
        client_event_id=event_id(label),
        event_type="yellow_card",
        team_id=team_id,
        player_id=player_id,
        minute=minute,
        added_minute=added_minute,
        segment_id=segment_id,
    )


def red_payload(
    player_id: UUID,
    *,
    team_id: UUID,
    segment_id: UUID,
    minute: int,
    label: str,
    red_card_type: str = "double_yellow_red",
) -> MatchEventPayload:
    return MatchEventPayload(
        client_event_id=event_id(label),
        event_type="red_card",
        team_id=team_id,
        player_id=player_id,
        minute=minute,
        segment_id=segment_id,
        metadata={"red_card_type": red_card_type},
    )


def assert_inconsistent(error: BaseException, *, minute: int) -> None:
    assert isinstance(error, DoubleYellowInconsistent), error
    assert error.status_code == 409
    assert error.code == DOUBLE_YELLOW_INCONSISTENT
    assert isinstance(error.detail, str) and error.detail
    assert "exactamente dos amarillas previas" in error.detail
    # El mensaje lleva el minuto y nunca un nombre (RNF-002).
    assert f"minuto {minute}" in error.detail


async def act_state(reader, match) -> dict:
    """Estado observable del acta: eventos, contadores, partido, sanciones y outbox.

    ``reader`` es una sesión (caso que cierra con ``db_session``) o un motor (los
    casos que fallan: el cierre revierte su transacción y hay que leer desde una
    sesión independiente, como en el resto de pruebas con base).
    """

    async def read(session) -> dict:
        params = {
            "organization_id": str(match.tenant.organization_id),
            "match_id": str(match.match_id),
        }

        async def count(sql: str) -> int:
            return (await session.execute(text(sql), params)).scalar_one()

        row = (
            await session.execute(
                text("""
                    SELECT status, result_confirmed, home_score, away_score
                    FROM matches
                    WHERE id = :match_id AND organization_id = :organization_id
                """),
                params,
            )
        ).mappings().one()
        return {
            "events": await count(
                "SELECT count(*) FROM match_events "
                "WHERE match_id = :match_id AND organization_id = :organization_id"
            ),
            "states": await count(
                "SELECT count(*) FROM match_segment_team_state "
                "WHERE match_id = :match_id AND organization_id = :organization_id"
            ),
            "suspensions": await count(
                "SELECT count(*) FROM player_suspensions "
                "WHERE origin_match_id = :match_id AND organization_id = :organization_id"
            ),
            "outbox": await count(
                "SELECT count(*) FROM outbox_events "
                "WHERE organization_id = :organization_id "
                "AND payload ->> 'match_id' = :match_id"
            ),
            "status": row["status"],
            "result_confirmed": row["result_confirmed"],
            "score": (row["home_score"], row["away_score"]),
        }

    if isinstance(reader, AsyncSession):
        return await read(reader)
    async with AsyncSession(reader, expire_on_commit=False) as session:
        await set_tenant_context(session, match.tenant)
        return await read(session)


def assert_nothing_was_written(state: dict) -> None:
    assert state == {
        "events": 0,
        "states": 0,
        "suspensions": 0,
        "outbox": 0,
        "status": "scheduled",
        "result_confirmed": False,
        "score": (None, None),
    }, state


async def close_in_session(engine, context, match_id, dto):
    """Ejecuta el cierre como una petición: su propia sesión y transacción."""

    async with AsyncSession(engine, expire_on_commit=False) as session:
        return await close_match(match_id, dto, context, session)


async def run_sql(engine, match, statements) -> UUID | None:
    """Ejecuta sentencias de siembra en su propia transacción confirmada."""

    async with AsyncSession(engine, expire_on_commit=False) as session:
        await set_tenant_context(session, match.tenant)
        scalar = None
        for sql, params in statements:
            result = await session.execute(text(sql), params)
            scalar = result.scalar_one_or_none() if result.returns_rows else scalar
        await session.commit()
    return scalar


async def test_a_double_yellow_with_two_previous_yellows_closes_and_writes(
    db_session, tenant_factory
):
    tenant = await tenant_factory("017 T4 doble amarilla válida")
    match = await create_closable_match(db_session, tenant)
    await db_session.commit()
    player = match.home_starters[0]

    dto = report(
        [
            yellow_payload(
                player,
                team_id=match.home_team_id,
                segment_id=match.segment_1,
                minute=20,
                label="dy-valid-yellow-1",
            ),
            yellow_payload(
                player,
                team_id=match.home_team_id,
                segment_id=match.segment_1,
                minute=30,
                label="dy-valid-yellow-2",
            ),
            red_payload(
                player,
                team_id=match.home_team_id,
                segment_id=match.segment_1,
                minute=40,
                label="dy-valid-red",
            ),
        ]
    )

    outcome = await close_match(match.match_id, dto, context_for(tenant), db_session)

    assert outcome["status"] == "success"
    state = await act_state(db_session, match)
    assert state["events"] == 3
    assert state["status"] == "finished"
    assert state["result_confirmed"] is True
    assert state["score"] == (0, 0)
    # La roja genera su suspensión (una por defecto) y las dos amarillas no
    # llegan al umbral de acumulación (3): solo hay una.
    assert state["suspensions"] == 1
    rows = (
        await db_session.execute(
            text("""
                SELECT event_type, player_id, metadata
                FROM match_events
                WHERE match_id = :match_id AND organization_id = :organization_id
                ORDER BY minute, added_minute, id
            """),
            {
                "match_id": str(match.match_id),
                "organization_id": str(match.tenant.organization_id),
            },
        )
    ).mappings().all()
    assert [row["event_type"] for row in rows] == ["yellow_card", "yellow_card", "red_card"]
    assert all(row["player_id"] == player for row in rows)
    assert rows[-1]["metadata"] == {"red_card_type": "double_yellow_red"}


async def test_one_previous_yellow_is_rejected_without_writing(database_admin_url):
    async with committed_application(database_admin_url) as engine:
        context, match = await seeded_match(engine)
        player = match.home_starters[0]

        dto = report(
            [
                yellow_payload(
                    player,
                    team_id=match.home_team_id,
                    segment_id=match.segment_1,
                    minute=20,
                    label="dy-one-yellow",
                ),
                red_payload(
                    player,
                    team_id=match.home_team_id,
                    segment_id=match.segment_1,
                    minute=40,
                    label="dy-one-red",
                ),
            ]
        )

        with pytest.raises(DoubleYellowInconsistent) as error:
            await close_in_session(engine, context, match.match_id, dto)

        assert_inconsistent(error.value, minute=40)
        assert_nothing_was_written(await act_state(engine, match))


async def test_zero_previous_yellows_is_rejected_without_writing(database_admin_url):
    async with committed_application(database_admin_url) as engine:
        context, match = await seeded_match(engine)

        dto = report(
            [
                red_payload(
                    match.home_starters[0],
                    team_id=match.home_team_id,
                    segment_id=match.segment_1,
                    minute=40,
                    label="dy-zero-red",
                )
            ]
        )

        with pytest.raises(DoubleYellowInconsistent) as error:
            await close_in_session(engine, context, match.match_id, dto)

        assert_inconsistent(error.value, minute=40)
        assert_nothing_was_written(await act_state(engine, match))


async def test_three_previous_yellows_are_rejected_without_writing(database_admin_url):
    async with committed_application(database_admin_url) as engine:
        context, match = await seeded_match(engine)
        player = match.home_starters[0]

        dto = report(
            [
                yellow_payload(
                    player,
                    team_id=match.home_team_id,
                    segment_id=match.segment_1,
                    minute=10,
                    label="dy-three-yellow-1",
                ),
                yellow_payload(
                    player,
                    team_id=match.home_team_id,
                    segment_id=match.segment_1,
                    minute=20,
                    label="dy-three-yellow-2",
                ),
                yellow_payload(
                    player,
                    team_id=match.home_team_id,
                    segment_id=match.segment_1,
                    minute=30,
                    label="dy-three-yellow-3",
                ),
                red_payload(
                    player,
                    team_id=match.home_team_id,
                    segment_id=match.segment_1,
                    minute=40,
                    label="dy-three-red",
                ),
            ]
        )

        with pytest.raises(DoubleYellowInconsistent) as error:
            await close_in_session(engine, context, match.match_id, dto)

        assert_inconsistent(error.value, minute=40)
        assert_nothing_was_written(await act_state(engine, match))


async def test_yellows_of_another_player_do_not_count(database_admin_url):
    async with committed_application(database_admin_url) as engine:
        context, match = await seeded_match(engine)
        player, other = match.home_starters[:2]

        dto = report(
            [
                yellow_payload(
                    other,
                    team_id=match.home_team_id,
                    segment_id=match.segment_1,
                    minute=10,
                    label="dy-other-yellow-1",
                ),
                yellow_payload(
                    other,
                    team_id=match.home_team_id,
                    segment_id=match.segment_1,
                    minute=20,
                    label="dy-other-yellow-2",
                ),
                red_payload(
                    player,
                    team_id=match.home_team_id,
                    segment_id=match.segment_1,
                    minute=40,
                    label="dy-other-red",
                ),
            ]
        )

        with pytest.raises(DoubleYellowInconsistent) as error:
            await close_in_session(engine, context, match.match_id, dto)

        assert_inconsistent(error.value, minute=40)
        assert_nothing_was_written(await act_state(engine, match))


async def test_two_yellows_persisted_in_another_match_do_not_count(database_admin_url):
    """RF-006: el conteo es del partido del acta, no del historial del jugador."""

    async with committed_application(database_admin_url) as engine:
        context, match = await seeded_match(engine)
        player = match.home_starters[0]
        await seed_other_match_yellows(engine, match, player=player)

        dto = report(
            [
                red_payload(
                    player,
                    team_id=match.home_team_id,
                    segment_id=match.segment_1,
                    minute=40,
                    label="dy-elsewhere-red",
                )
            ]
        )

        with pytest.raises(DoubleYellowInconsistent) as error:
            await close_in_session(engine, context, match.match_id, dto)

        assert_inconsistent(error.value, minute=40)
        assert_nothing_was_written(await act_state(engine, match))


async def seed_other_match_yellows(engine, match, *, player) -> None:
    """Crea otro partido del torneo vecino con dos amarillas del mismo jugador.

    Las filas se insertan directamente (sin pasar por el cierre) porque el
    escenario necesita un historial disciplinario **anterior** en otro partido:
    es justo lo que RF-006 dice que no cuenta para la coherencia del acta. El
    segundo partido vive en su propio torneo del mismo tenant y se crea con el
    sembrado habitual, así que su versión ya está publicada; el jugador del
    primer partido se inscribe en él para que el trigger de contexto acepte los
    eventos.
    """

    async with AsyncSession(engine, expire_on_commit=False) as session:
        other = await create_closable_match(session, match.tenant)
        roster_id = (
            await session.execute(
                text("""
                    INSERT INTO rosters
                        (organization_id, tournament_id, team_id, player_id,
                         dorsal_number, photo_consent, valid_from, eligible_from)
                    VALUES
                        (:organization_id, :tournament_id, :team_id, :player_id,
                         99, FALSE, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                    RETURNING id
                """),
                {
                    "organization_id": str(match.tenant.organization_id),
                    "tournament_id": str(other.tournament_id),
                    "team_id": str(other.home_team_id),
                    "player_id": str(player),
                },
            )
        ).scalar_one()
        await session.execute(
            text("""
                INSERT INTO match_rosters
                    (organization_id, match_id, roster_id, player_id, team_id, role, is_valid)
                VALUES
                    (:organization_id, :match_id, :roster_id, :player_id, :team_id,
                     'starter', TRUE)
            """),
            {
                "organization_id": str(match.tenant.organization_id),
                "match_id": str(other.match_id),
                "roster_id": str(roster_id),
                "player_id": str(player),
                "team_id": str(other.home_team_id),
            },
        )
        for index, label in enumerate(("dy-elsewhere-1", "dy-elsewhere-2")):
            await session.execute(
                text("""
                    INSERT INTO match_events
                        (organization_id, match_id, segment_id, team_id, player_id,
                         event_type, minute, added_minute, client_event_id, metadata)
                    VALUES (:organization_id, :match_id, :segment_id, :team_id,
                            :player_id, 'yellow_card', :minute, 0, :client_event_id,
                            '{}'::jsonb)
                """),
                {
                    "organization_id": str(match.tenant.organization_id),
                    "match_id": str(other.match_id),
                    "segment_id": str(other.segment_1),
                    "team_id": str(other.home_team_id),
                    "player_id": str(player),
                    "minute": 10 + index,
                    "client_event_id": event_id(label),
                },
            )
        await session.commit()


async def test_a_direct_red_closes_without_yellows(db_session, tenant_factory):
    tenant = await tenant_factory("017 T4 roja directa")
    match = await create_closable_match(db_session, tenant)
    await db_session.commit()

    dto = report(
        [
            red_payload(
                match.home_starters[0],
                team_id=match.home_team_id,
                segment_id=match.segment_1,
                minute=40,
                label="dy-direct-red",
                red_card_type="direct_red",
            )
        ]
    )

    outcome = await close_match(match.match_id, dto, context_for(tenant), db_session)

    assert outcome["status"] == "success"
    state = await act_state(db_session, match)
    assert state["events"] == 1
    assert state["status"] == "finished"
    assert state["suspensions"] == 1


async def test_yellows_after_the_red_are_reported_by_the_field_state_first(database_admin_url):
    """RF-001: el paso 8 gana al 10; la regla pura sigue siendo la del acta.

    Una amarilla posterior a la roja del mismo jugador no cuenta para RF-006
    (lo fija la prueba pura), y en el cierre ni siquiera se llega al paso 10:
    el jugador ya no está en campo y el replay del paso 8 lo rechaza con su
    propio 409, sin `code`.
    """

    async with committed_application(database_admin_url) as engine:
        context, match = await seeded_match(engine)
        player = match.home_starters[0]

        dto = report(
            [
                yellow_payload(
                    player,
                    team_id=match.home_team_id,
                    segment_id=match.segment_2,
                    minute=60,
                    label="dy-after-yellow-1",
                ),
                yellow_payload(
                    player,
                    team_id=match.home_team_id,
                    segment_id=match.segment_2,
                    minute=70,
                    label="dy-after-yellow-2",
                ),
                red_payload(
                    player,
                    team_id=match.home_team_id,
                    segment_id=match.segment_1,
                    minute=30,
                    label="dy-after-red",
                ),
            ]
        )

        with pytest.raises(HTTPException) as error:
            await close_in_session(engine, context, match.match_id, dto)

        assert error.value.status_code == 409
        assert getattr(error.value, "code", None) is None
        assert "campo" in str(error.value)
        assert_nothing_was_written(await act_state(engine, match))


async def test_the_double_yellow_wins_over_the_score_mismatch(database_admin_url):
    """El paso 10 se informa antes que el 11 (RF-001)."""

    async with committed_application(database_admin_url) as engine:
        context, match = await seeded_match(engine)
        player = match.home_starters[0]

        dto = report(
            [
                yellow_payload(
                    player,
                    team_id=match.home_team_id,
                    segment_id=match.segment_1,
                    minute=20,
                    label="dy-order-yellow",
                ),
                red_payload(
                    player,
                    team_id=match.home_team_id,
                    segment_id=match.segment_1,
                    minute=40,
                    label="dy-order-red",
                ),
            ],
            home=1,
            away=0,
        )

        with pytest.raises(DoubleYellowInconsistent) as error:
            await close_in_session(engine, context, match.match_id, dto)

        assert_inconsistent(error.value, minute=40)
        assert_nothing_was_written(await act_state(engine, match))


async def test_participants_win_over_the_double_yellow(database_admin_url):
    """Un defecto del paso 7 gana al paso 10 (RF-001: gana el anterior)."""

    async with committed_application(database_admin_url) as engine:
        context, match = await seeded_match(engine)
        outsider_team = await run_sql(
            engine,
            match,
            [
                (
                    """
                    INSERT INTO teams (organization_id, name, short_code)
                    VALUES (:organization_id, 'Equipo ajeno', :short_code)
                    RETURNING id
                    """,
                    {
                        "organization_id": str(match.tenant.organization_id),
                        "short_code": f"X{match.match_id.hex[:5].upper()}",
                    },
                )
            ],
        )
        player = match.home_starters[0]

        dto = report(
            [
                MatchEventPayload(
                    client_event_id=event_id("dy-order-other-team"),
                    event_type="goal",
                    team_id=outsider_team,
                    player_id=player,
                    minute=30,
                    segment_id=match.segment_1,
                ),
                red_payload(
                    player,
                    team_id=match.home_team_id,
                    segment_id=match.segment_1,
                    minute=40,
                    label="dy-order-participants-red",
                ),
            ]
        )

        with pytest.raises(HTTPException) as error:
            await close_in_session(engine, context, match.match_id, dto)

        assert error.value.status_code == 409
        assert getattr(error.value, "code", None) is None
        assert "no participa" in str(error.value)
        assert_nothing_was_written(await act_state(engine, match))
