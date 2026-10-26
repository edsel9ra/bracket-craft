"""Motor puro: validación de dominio del asistente (spec 015, RF-008).

Estas pruebas no tocan la base de datos: ejercitan el replay del acta
(``replay_report_state``) y las primitivas del motor de estado en campo. La
asistencia se valida **dentro del replay** (D-7), con el mismo estado derivado
del XI y de los eventos en orden ``(minute, added_minute, índice)`` que ya usan
el goleador, la sustitución y la tarjeta roja.

Contrato de esta tarea (T4):

* ``assist_player_id`` es un campo del evento de gol y del modelo del motor.
* La violación de pertenencia, equipo o presencia en campo es un
  :class:`SubstitutionError` con el código ``ASSIST_PLAYER_INVALID``; el
  servicio de cierre lo traduce a **409** con el ``code`` aditivo (T5).
* La igualdad con el goleador es **422** estructural y no se comprueba aquí
  (vive en ``schemas.py``, T3).
"""

from __future__ import annotations

import json
from uuid import UUID

import pytest
from fastapi import Request

from app import main as main_module
from app.modules.matches.errors import ASSIST_PLAYER_INVALID, AssistPlayerInvalid
from app.modules.matches.service import replay_report_state
from app.modules.rules_engine.substitutions import (
    MatchEvent,
    RosterEntry,
    SubstitutionError,
    SubstitutionErrorCode,
    SubstitutionLimits,
)

TEAM = UUID(int=1)
RIVAL = UUID(int=2)
SEGMENT_1 = UUID(int=501)

DEFAULT_LIMITS = SubstitutionLimits(max_per_team=5, max_windows=3, allow_reentry=False)
REENTRY_LIMITS = SubstitutionLimits(max_per_team=5, max_windows=3, allow_reentry=True)


def starter(number: int, team: UUID = TEAM) -> UUID:
    """Titulares 1-11 para el local y 201-211 para el rival."""

    return UUID(int=(number if team == TEAM else 200 + number))


def substitute(number: int, team: UUID = TEAM) -> UUID:
    """Suplentes 101-103 para el local y 301-303 para el rival."""

    return UUID(int=(100 + number if team == TEAM else 300 + number))


def lineup(
    *,
    team: UUID = TEAM,
    starters: int = 11,
    substitutes: int = 3,
    valid: bool = True,
) -> list[RosterEntry]:
    entries = [
        RosterEntry(
            player_id=starter(index, team),
            team_id=team,
            role="starter",
            is_valid=valid,
        )
        for index in range(1, starters + 1)
    ]
    entries += [
        RosterEntry(
            player_id=substitute(index, team),
            team_id=team,
            role="substitute",
            is_valid=valid,
        )
        for index in range(1, substitutes + 1)
    ]
    return entries


def match_roster() -> list[RosterEntry]:
    return lineup() + lineup(team=RIVAL)


def goal(
    player_id: UUID,
    *,
    assist_player_id: UUID | None = None,
    minute: int,
    added_minute: int = 0,
    team: UUID = TEAM,
    segment_id: UUID = SEGMENT_1,
    index: int = 0,
) -> MatchEvent:
    return MatchEvent(
        event_type="goal",
        team_id=team,
        minute=minute,
        added_minute=added_minute,
        index=index,
        player_id=player_id,
        assist_player_id=assist_player_id,
        segment_id=segment_id,
    )


def substitution(
    out_id: UUID,
    in_id: UUID,
    *,
    minute: int,
    added_minute: int = 0,
    team: UUID = TEAM,
    segment_id: UUID = SEGMENT_1,
    index: int = 0,
) -> MatchEvent:
    return MatchEvent(
        event_type="substitution",
        team_id=team,
        minute=minute,
        added_minute=added_minute,
        index=index,
        player_id=out_id,
        player_out_id=out_id,
        player_in_id=in_id,
        segment_id=segment_id,
    )


def red_card(
    player_id: UUID,
    *,
    minute: int,
    added_minute: int = 0,
    team: UUID = TEAM,
    segment_id: UUID = SEGMENT_1,
    index: int = 0,
) -> MatchEvent:
    return MatchEvent(
        event_type="red_card",
        team_id=team,
        minute=minute,
        added_minute=added_minute,
        index=index,
        player_id=player_id,
        segment_id=segment_id,
    )


def replay(
    events: list[MatchEvent],
    *,
    rosters: list[RosterEntry] | None = None,
    limits: SubstitutionLimits = DEFAULT_LIMITS,
):
    return replay_report_state(
        rosters if rosters is not None else match_roster(),
        events,
        (TEAM, RIVAL),
        limits,
    )


def error_code(callable_):
    with pytest.raises(SubstitutionError) as error:
        callable_()
    return error.value.code


# --- Casos válidos ---------------------------------------------------------


def test_a_goal_with_an_assist_on_the_field_is_valid():
    state = replay([goal(starter(2), assist_player_id=starter(3), minute=30)])

    assert state.states[TEAM].is_on_field_at(starter(3), 30)


def test_an_assist_of_the_same_team_of_a_rival_goal_is_valid():
    state = replay(
        [
            goal(
                starter(2, RIVAL),
                assist_player_id=starter(4, RIVAL),
                minute=55,
                team=RIVAL,
            )
        ]
    )

    assert state.states[RIVAL].is_on_field_at(starter(4, RIVAL), 55)


def test_a_goal_without_an_assist_is_always_valid():
    # No regresión: el asistente es opcional siempre (DU-2, RF-013).
    state = replay(
        [
            substitution(starter(1), substitute(1), minute=20, index=0),
            goal(starter(2), minute=30, index=1),
            goal(starter(2), minute=75, index=2),
        ]
    )

    assert state.usage[TEAM].substitutions == 1


def test_a_goal_without_an_assist_does_not_need_the_assist_column():
    # Un evento histórico con la columna nula (o sin la clave) sigue siendo
    # válido: el replay no lo revalida ni lo reescribe (RF-013).
    event = MatchEvent.from_mapping(
        {
            "event_type": "goal",
            "team_id": str(TEAM),
            "minute": 10,
            "player_id": str(starter(1)),
            "segment_id": str(SEGMENT_1),
        }
    )

    assert event.assist_player_id is None
    replay([event])


def test_the_same_player_can_assist_two_goals_of_the_same_match():
    # RF-008: el asistente no consume ningún cupo ni se agota.
    state = replay(
        [
            goal(starter(2), assist_player_id=starter(3), minute=15, index=0),
            goal(starter(4), assist_player_id=starter(3), minute=60, index=1),
        ]
    )

    assert state.states[TEAM].is_on_field_at(starter(3), 60)


def test_an_assist_who_entered_as_a_substitute_before_the_goal_is_valid():
    state = replay(
        [
            substitution(starter(1), substitute(1), minute=40, index=0),
            goal(starter(2), assist_player_id=substitute(1), minute=55, index=1),
        ]
    )

    assert state.states[TEAM].is_on_field_at(substitute(1), 55)


# --- Casos rechazados con ASSIST_PLAYER_INVALID ----------------------------


def test_an_assist_from_the_other_team_is_rejected():
    assert error_code(
        lambda: replay(
            [goal(starter(2), assist_player_id=starter(3, RIVAL), minute=30)]
        )
    ) is SubstitutionErrorCode.ASSIST_PLAYER_INVALID


def test_an_assist_outside_the_match_roster_is_rejected():
    outsider = UUID(int=999)

    assert error_code(
        lambda: replay([goal(starter(2), assist_player_id=outsider, minute=30)])
    ) is SubstitutionErrorCode.ASSIST_PLAYER_INVALID


def test_an_invalid_roster_entry_cannot_assist():
    # Una fila de planilla invalidada no está en el estado en campo, así que el
    # asistente no se considera de la plantilla del partido (RF-008/RF-014).
    roster = match_roster() + [
        RosterEntry(
            player_id=UUID(int=888),
            team_id=TEAM,
            role="starter",
            is_valid=False,
        )
    ]

    assert error_code(
        lambda: replay(
            [goal(starter(2), assist_player_id=UUID(int=888), minute=30)],
            rosters=roster,
        )
    ) is SubstitutionErrorCode.ASSIST_PLAYER_INVALID


def test_an_assist_who_was_ejected_before_the_goal_is_rejected():
    assert error_code(
        lambda: replay(
            [
                red_card(starter(3), minute=40, index=0),
                goal(starter(2), assist_player_id=starter(3), minute=50, index=1),
            ]
        )
    ) is SubstitutionErrorCode.ASSIST_PLAYER_INVALID


def test_an_assist_who_left_before_the_goal_is_rejected():
    assert error_code(
        lambda: replay(
            [
                substitution(starter(3), substitute(1), minute=40, index=0),
                goal(starter(2), assist_player_id=starter(3), minute=55, index=1),
            ]
        )
    ) is SubstitutionErrorCode.ASSIST_PLAYER_INVALID


def test_a_substitute_who_has_not_entered_yet_cannot_assist():
    assert error_code(
        lambda: replay(
            [
                substitution(starter(3), substitute(1), minute=40, index=0),
                goal(starter(2), assist_player_id=substitute(2), minute=55, index=1),
            ]
        )
    ) is SubstitutionErrorCode.ASSIST_PLAYER_INVALID


def test_the_error_message_never_needs_the_player_name():
    with pytest.raises(SubstitutionError) as error:
        replay([goal(starter(2), assist_player_id=UUID(int=999), minute=30)])

    assert error.value.code is SubstitutionErrorCode.ASSIST_PLAYER_INVALID
    assert str(error.value)


# --- Reentrada: la unión de intervalos [entrada, salida) -------------------


def test_a_re_entering_assist_is_valid_only_inside_his_intervals():
    def report(minute: int) -> list[MatchEvent]:
        return [
            substitution(starter(1), substitute(1), minute=30, index=0),
            substitution(substitute(1), starter(1), minute=50, index=1),
            goal(starter(2), assist_player_id=starter(1), minute=minute, index=2),
        ]

    # Primer intervalo [0, 30).
    replay(report(20), limits=REENTRY_LIMITS)
    # Fuera de sus dos intervalos: ya había salido y todavía no había vuelto.
    assert error_code(lambda: replay(report(40), limits=REENTRY_LIMITS)) is (
        SubstitutionErrorCode.ASSIST_PLAYER_INVALID
    )
    # Segundo intervalo [50, ∞).
    replay(report(70), limits=REENTRY_LIMITS)


# --- Minuto exacto de la sustitución --------------------------------------


def test_a_goal_in_the_exact_minute_of_the_substitution_follows_the_canonical_order():
    """El estado usado es el que precede al gol en orden ``(minuto, añadido, índice)``.

    El intervalo de un jugador es ``[entrada, salida)``: quien sale a los 60
    deja de estar en campo **en** el 60. Pero el replay aplica los eventos en
    orden canónico y el índice del acta desempata el mismo minuto, igual que ya
    ocurre con la comprobación del goleador: un gol anterior a la sustitución ve
    el estado anterior y uno posterior ve el estado ya sustituido. Por eso un
    gol de índice menor **sí** admite como asistente al jugador que sale en ese
    mismo minuto y no admite al que entra; con el índice mayor, al revés.
    """

    leaving, entering = starter(1), substitute(1)

    # El gol precede a la sustitución: el que sale aún está en campo y el que
    # entra todavía no ha entrado.
    replay(
        [
            goal(starter(2), assist_player_id=leaving, minute=60, index=0),
            substitution(leaving, entering, minute=60, index=1),
        ]
    )
    assert error_code(
        lambda: replay(
            [
                goal(starter(2), assist_player_id=entering, minute=60, index=0),
                substitution(leaving, entering, minute=60, index=1),
            ]
        )
    ) is SubstitutionErrorCode.ASSIST_PLAYER_INVALID

    # El gol sigue a la sustitución: el que entra ya está en campo y el que
    # sale ya no lo está.
    replay(
        [
            substitution(leaving, entering, minute=60, index=0),
            goal(starter(2), assist_player_id=entering, minute=60, index=1),
        ]
    )
    assert error_code(
        lambda: replay(
            [
                substitution(leaving, entering, minute=60, index=0),
                goal(starter(2), assist_player_id=leaving, minute=60, index=1),
            ]
        )
    ) is SubstitutionErrorCode.ASSIST_PLAYER_INVALID


def test_the_added_minute_orders_the_goal_against_the_substitution():
    # ``minute + added_minute`` es el minuto efectivo: un gol en el 60+2 es
    # posterior a una sustitución en el 60, sin importar el índice del acta.
    assert error_code(
        lambda: replay(
            [
                goal(
                    starter(2),
                    assist_player_id=starter(1),
                    minute=60,
                    added_minute=2,
                    index=0,
                ),
                substitution(starter(1), substitute(1), minute=60, index=1),
            ]
        )
    ) is SubstitutionErrorCode.ASSIST_PLAYER_INVALID

    replay(
        [
            substitution(starter(1), substitute(1), minute=60, index=0),
            goal(
                starter(2),
                assist_player_id=substitute(1),
                minute=60,
                added_minute=2,
                index=1,
            ),
        ]
    )


# --- Modelo del motor -----------------------------------------------------


def test_match_event_reads_the_assist_from_a_row_mapping():
    event = MatchEvent.from_mapping(
        {
            "event_type": "goal",
            "team_id": str(TEAM),
            "minute": 30,
            "added_minute": 1,
            "player_id": str(starter(2)),
            "assist_player_id": str(starter(3)),
            "segment_id": str(SEGMENT_1),
        },
        index=7,
    )

    assert event.assist_player_id == starter(3)
    assert event.effective_minute == 31
    assert event.index == 7


# --- Contrato HTTP del código (D-8) ---------------------------------------


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


def test_the_assist_error_is_registered_with_the_coded_handler():
    assert main_module.api.exception_handlers.get(AssistPlayerInvalid) is (
        main_module._coded_exception_handler
    )


@pytest.mark.asyncio
async def test_the_assist_error_answers_409_with_a_string_detail_and_the_code():
    handler = main_module.api.exception_handlers[AssistPlayerInvalid]

    response = await handler(_request(), AssistPlayerInvalid())

    body = json.loads(response.body)
    assert response.status_code == 409
    assert body["code"] == ASSIST_PLAYER_INVALID
    assert isinstance(body["detail"], str) and body["detail"]


# --- Traducción en el servicio de cierre (T5, D-8) -------------------------


def _close_report(assist_player_id: UUID, *, player_id: UUID | None = None):
    from app.modules.matches.schemas import CloseMatchReportDTO, MatchEventPayload

    return CloseMatchReportDTO(
        resolution_type="regular",
        home_score_regular=1,
        away_score_regular=0,
        home_score=1,
        away_score=0,
        winner_team_id=None,
        events=[
            MatchEventPayload(
                client_event_id=str(UUID(int=50101)),
                event_type="goal",
                team_id=TEAM,
                player_id=player_id or starter(2),
                assist_player_id=assist_player_id,
                minute=30,
                segment_id=SEGMENT_1,
            )
        ],
    )


def _match_participants() -> dict:
    return {"home_team_id": TEAM, "away_team_id": RIVAL}


def test_the_closing_service_translates_the_assist_error_to_the_coded_409():
    # El motor no importa HTTP: el servicio de cierre traduce su código a la
    # excepción de dominio registrada en ``app/main.py`` (D-8).
    from app.modules.matches.service import CloseMatchReportService

    report = _close_report(starter(3, RIVAL))

    with pytest.raises(AssistPlayerInvalid) as error:
        CloseMatchReportService._validate_substitutions(
            report, _match_participants(), match_roster(), DEFAULT_LIMITS
        )

    assert error.value.status_code == 409
    assert error.value.code == ASSIST_PLAYER_INVALID
    assert isinstance(error.value.detail, str) and error.value.detail


def test_the_closing_service_keeps_the_engine_error_for_any_other_code():
    # Sin regresión: un jugador fuera de la plantilla sigue siendo el 409 de
    # pertenencia que ya existía, sin ``code`` (RF-014).
    from app.modules.matches.service import CloseMatchReportService

    report = _close_report(starter(3), player_id=UUID(int=999))

    with pytest.raises(SubstitutionError) as error:
        CloseMatchReportService._validate_substitutions(
            report, _match_participants(), match_roster(), DEFAULT_LIMITS
        )

    assert error.value.code is SubstitutionErrorCode.PLAYER_NOT_IN_ROSTER
