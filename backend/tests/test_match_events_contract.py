"""Contrato cerrado del catálogo de eventos (spec 015, T2 y T3).

RF-002 cierra el catálogo en los dos niveles —la raíz del evento y su
``metadata``— y exige que ``beneficiary_team_id`` solo exista en un autogol.
RF-007/RF-009 admiten el asistente solo en un gol y RF-015 exige que
``client_event_id`` tenga forma de UUID. Todo se resuelve en el esquema, antes
del handler: un ``ValidationError`` es el 422 saneado de la API y no escribe
nada.

El resto de reglas del asistente (plantilla del partido, mismo equipo, en campo
y el 409 ``ASSIST_PLAYER_INVALID``) son del motor y del servicio: T4 y T5.
"""

from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.modules.matches.schemas import CloseMatchReportDTO, MatchEventPayload

TEAM = uuid4()
OTHER_TEAM = uuid4()
PLAYER = uuid4()
PLAYER_IN = uuid4()
ASSIST = uuid4()
SEGMENT = uuid4()

EVENT_TYPES = (
    "goal",
    "own_goal",
    "penalty_goal",
    "yellow_card",
    "red_card",
    "substitution",
    "foul",
)
TYPES_WITHOUT_BENEFICIARY = tuple(event_type for event_type in EVENT_TYPES if event_type != "own_goal")
TYPES_WITHOUT_ASSIST = tuple(event_type for event_type in EVENT_TYPES if event_type != "goal")


def payload(event_type: str, **overrides: object) -> dict[str, object]:
    """Un payload completo y válido del tipo indicado, listo para sobreescribir."""
    data: dict[str, object] = {
        # RF-015: el identificador de cliente es opaco y con forma de UUID.
        "client_event_id": str(uuid4()),
        "event_type": event_type,
        "team_id": TEAM,
        "player_id": PLAYER,
        "minute": 10,
        "segment_id": SEGMENT,
    }
    if event_type == "own_goal":
        data["beneficiary_team_id"] = OTHER_TEAM
    if event_type == "red_card":
        data["metadata"] = {"red_card_type": "direct_red"}
    if event_type == "substitution":
        data["player_out_id"] = PLAYER
        data["player_in_id"] = PLAYER_IN
    data.update(overrides)
    return data


def build(event_type: str, **overrides: object) -> MatchEventPayload:
    return MatchEventPayload(**payload(event_type, **overrides))


def assert_rejected(event_type: str, **overrides: object) -> None:
    with pytest.raises(ValidationError):
        build(event_type, **overrides)


# ---------------------------------------------------------------------------
# Catálogo válido: ningún tipo pierde su formulario completo
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("event_type", EVENT_TYPES)
def test_a_complete_payload_of_every_type_is_accepted(event_type):
    event = build(event_type)

    assert event.event_type == event_type
    assert event.player_id == PLAYER
    if event_type == "own_goal":
        assert event.beneficiary_team_id == OTHER_TEAM
    else:
        assert event.beneficiary_team_id is None


@pytest.mark.parametrize("event_type", TYPES_WITHOUT_BENEFICIARY)
def test_a_null_beneficiary_is_accepted_in_every_type_that_does_not_use_it(event_type):
    # El cliente actual envía `beneficiary_team_id: null` fuera del autogol.
    assert build(event_type, beneficiary_team_id=None).beneficiary_team_id is None


def test_empty_metadata_stays_accepted_in_every_type():
    # `metadata` se cierra por claves, no por presencia: un objeto vacío no
    # declara ninguna y sigue siendo válido (el servicio lo guarda como `{}`).
    for event_type in EVENT_TYPES:
        assert build(event_type, metadata={}).metadata == {}


# ---------------------------------------------------------------------------
# Raíz del evento (RF-002, D-4)
# ---------------------------------------------------------------------------


def test_an_unknown_top_level_key_is_rejected():
    with pytest.raises(ValidationError) as excinfo:
        build("goal", free_text="texto libre")

    assert "extra_forbidden" in {error["type"] for error in excinfo.value.errors()}


def test_the_closed_catalog_applies_to_the_close_request():
    with pytest.raises(ValidationError) as excinfo:
        CloseMatchReportDTO(
            resolution_type="regular",
            home_score_regular=0,
            away_score_regular=0,
            events=[payload("goal", free_text="texto libre")],
        )

    locations = [error["loc"] for error in excinfo.value.errors()]
    assert ("events", 0, "free_text") in locations


# ---------------------------------------------------------------------------
# `metadata` (RF-002)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("event_type", EVENT_TYPES)
def test_metadata_with_an_undeclared_key_is_rejected(event_type):
    assert_rejected(event_type, metadata={"note": "texto libre"})


def test_red_card_metadata_does_not_admit_extra_keys():
    assert_rejected("red_card", metadata={"red_card_type": "direct_red", "note": "texto libre"})


@pytest.mark.parametrize("event_type", [event_type for event_type in EVENT_TYPES if event_type != "red_card"])
def test_red_card_type_only_applies_to_a_red_card(event_type):
    assert_rejected(event_type, metadata={"red_card_type": "direct_red"})


@pytest.mark.parametrize("red_card_type", ["direct_red", "double_yellow_red"])
def test_a_red_card_accepts_its_declared_card_types(red_card_type):
    event = build("red_card", metadata={"red_card_type": red_card_type})

    assert event.metadata == {"red_card_type": red_card_type}


def test_a_red_card_accepts_no_metadata_and_rejects_another_card_type():
    assert build("red_card", metadata=None).metadata is None
    assert_rejected("red_card", metadata={"red_card_type": "orange"})


# ---------------------------------------------------------------------------
# `beneficiary_team_id` (RF-002)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("event_type", TYPES_WITHOUT_BENEFICIARY)
@pytest.mark.parametrize("beneficiary", [TEAM, OTHER_TEAM])
def test_beneficiary_team_id_is_only_admitted_in_an_own_goal(event_type, beneficiary):
    # Incluye `goal`/`penalty_goal` con el propio equipo: antes se toleraba.
    assert_rejected(event_type, beneficiary_team_id=beneficiary)


def test_own_goal_requires_a_beneficiary_that_is_not_its_own_team():
    assert_rejected("own_goal", beneficiary_team_id=None)
    assert_rejected("own_goal", beneficiary_team_id=TEAM)
    assert build("own_goal", beneficiary_team_id=OTHER_TEAM).beneficiary_team_id == OTHER_TEAM


@pytest.mark.parametrize("event_type", ["goal", "penalty_goal"])
def test_a_goal_without_beneficiary_is_valid(event_type):
    assert build(event_type, beneficiary_team_id=None).beneficiary_team_id is None


# ---------------------------------------------------------------------------
# Asistente (RF-007, RF-009)
# ---------------------------------------------------------------------------


def test_a_goal_accepts_one_assistant():
    event = build("goal", assist_player_id=ASSIST)

    assert event.assist_player_id == ASSIST
    assert event.player_id == PLAYER


@pytest.mark.parametrize("event_type", TYPES_WITHOUT_ASSIST)
def test_an_assistant_is_rejected_in_every_type_that_does_not_declare_it(event_type):
    # Autogol y penalti incluidos: el primero ya tiene beneficiario y el
    # segundo no nace de un pase (DU-3, RF-009).
    assert_rejected(event_type, assist_player_id=ASSIST)


def test_the_assistant_must_be_a_different_player_than_the_scorer():
    # RF-008: incoherencia estructural, 422 y no 409.
    assert_rejected("goal", assist_player_id=PLAYER)


def test_a_goal_without_assistant_stays_valid():
    # DU-2: la asistencia es opcional siempre.
    assert build("goal", assist_player_id=None).assist_player_id is None
    assert build("goal").assist_player_id is None


def test_two_goals_may_share_the_same_assistant():
    # Caso límite 9: un mismo jugador puede asistir dos goles del partido.
    dto = CloseMatchReportDTO(
        resolution_type="regular",
        home_score_regular=2,
        away_score_regular=0,
        events=[
            payload("goal", assist_player_id=ASSIST),
            payload("goal", assist_player_id=ASSIST),
        ],
    )

    assert [event.assist_player_id for event in dto.events] == [ASSIST, ASSIST]


# ---------------------------------------------------------------------------
# `client_event_id` con forma de UUID (RF-015, D-5)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("value", [str(uuid4()).upper(), str(uuid4())])
def test_a_client_event_id_with_uuid_shape_is_accepted(value):
    assert build("goal", client_event_id=value).client_event_id == value


@pytest.mark.parametrize(
    "value",
    [
        "event-123",
        "event-1234",
        "",
        "9f1c1e2a3b4c4d5e8f60718293a4b5c6",  # sin guiones
        "9f1c1e2a-3b4c-4d5e-8f60-718293a4b5c",  # 35 caracteres
        "9f1c1e2a-3b4c-4d5e-8f60-718293a4b5c6z",  # hex inválido
        "a" * 101,
    ],
)
def test_a_client_event_id_that_is_not_a_uuid_is_rejected(value):
    assert_rejected("goal", client_event_id=value)


def test_the_close_request_requires_uuid_client_event_ids():
    with pytest.raises(ValidationError) as excinfo:
        CloseMatchReportDTO(
            resolution_type="regular",
            home_score_regular=0,
            away_score_regular=0,
            events=[payload("goal", client_event_id="event-1")],
        )

    locations = [error["loc"] for error in excinfo.value.errors()]
    assert ("events", 0, "client_event_id") in locations


# ---------------------------------------------------------------------------
# No regresión del catálogo con el acta endurecida (spec 019, T3)
# ---------------------------------------------------------------------------


def test_the_close_request_keeps_the_declared_catalog_fields_valid():
    # Spec 019 (RNF-007): endurecer CloseMatchReportDTO con extra="forbid" no
    # convierte en «claves extra» los campos declarados del catálogo: la
    # asistencia del gol y el metadata.red_card_type de la roja siguen siendo
    # válidos dentro del cuerpo del cierre.
    dto = CloseMatchReportDTO(
        resolution_type="regular",
        home_score_regular=2,
        away_score_regular=1,
        events=[
            payload("goal", assist_player_id=ASSIST),
            payload("red_card", metadata={"red_card_type": "double_yellow_red"}),
        ],
    )

    assert dto.events[0].assist_player_id == ASSIST
    assert dto.events[1].metadata == {"red_card_type": "double_yellow_red"}
