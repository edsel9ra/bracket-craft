"""Orden único de validación del cierre del acta (spec 017, T1 y spec 016, T6).

La matriz de precedencia se ejerce con **dobles**: cada caso envía una petición
con **dos** defectos de dominio de pasos distintos y comprueba que responde el
del paso anterior del orden declarado en RF-001, sin escribir nada. Los **422
estructurales** del esquema se resuelven antes del handler y no se repiten aquí:
los cubren la validación del DTO en `test_close_substitutions.py` y el catálogo
cerrado en `test_match_events_contract.py`.

La spec 016 añade al final de este archivo el **escalón propio del walkover**:
la misma matriz, con su escalera (paso 2 de permiso → paso 3 de estado y
versión → paso 4 de equipos → 13′ del acierto del ganador → 13′ de la pareja
coherente → 13′ del marcador informado) y el par cruzado con el tronco, más los
422 estructurales del walkover.

El orden que estas pruebas fijan (RF-001):

1. sesión, organización y aislamiento (404 al cargar el partido, antes del
   permiso; no es un paso de dominio);
2. permiso (conjunción);
3. estado del partido y versión publicada;
4. dos equipos participantes;
5. resolución habilitada por la configuración efectiva;
6. estructura del acta: segmento activo (RF-017), segmentos, tiempos y máximo
   efectivo;
7. participantes y plantilla (el aislamiento de equipos es 404 y precede al
   409 de «no participa», regla única de identificadores de la 015);
8. estado en campo y sustituciones;
9. asistente del gol;
10. coherencia disciplinaria (doble amarilla: exactamente dos amarillas
   previas del mismo jugador en orden canónico, RF-006);
11. marcador frente a eventos;
12. sanciones vigentes de la plantilla;
13. coherencia numérica de la resolución y del ganador (el marcador vive aquí
    desde la T2 y el **cálculo del resultado antes de escribir**, sobre los
    eventos de la petición, desde la T3);
14. escritura atómica.

La coherencia numérica del marcador y el resultado calculado antes de escribir
se ejercen como defectos más del paso 13.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable
from uuid import UUID

import pytest
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient

from app.core.database import get_db
from app.core.tenancy import AuthContext, get_auth_context
from app.main import api
from app.modules.matches import router as matches_router
from app.modules.matches.errors import (
    ASSIST_PLAYER_INVALID,
    DOUBLE_YELLOW_INCONSISTENT,
    RESOLUTION_NOT_ENABLED,
    WALKOVER_CONFIG_INCONSISTENT,
    WALKOVER_SCORE_MISMATCH,
    WALKOVER_STATE_NOT_ALLOWED,
    ResolutionNotEnabled,
    WalkoverConfigInconsistent,
    WalkoverScoreMismatch,
    WalkoverStateNotAllowed,
)
from app.modules.matches.schemas import CloseMatchReportDTO, MatchEventPayload
from app.modules.matches.service import (
    CloseMatchReportService,
    effective_match_minutes,
    resolution_enabled,
)
from app.modules.rules_engine.defaults import DEFAULT_RULES_CONFIG
from app.modules.rules_engine.engine import compute_match_outcome
from app.modules.rules_engine.substitutions import SubstitutionError, SubstitutionErrorCode
from tests.event_ids import event_id

ORGANIZATION_ID = UUID(int=9001)
USER_ID = UUID(int=9002)
MEMBER_ID = UUID(int=9003)
TOURNAMENT_ID = UUID(int=9100)
VERSION_ID = UUID(int=9101)
STAGE_ID = UUID(int=9102)
MATCH_ID = UUID(int=9103)
SEGMENT_1 = UUID(int=9104)
SEGMENT_2 = UUID(int=9105)
HOME = UUID(int=9200)
AWAY = UUID(int=9201)
# Equipo de la organización que no juega este partido (409 de participantes).
OTHER_TEAM = UUID(int=9202)
# Equipo que el doble no conoce: pertenece a otra organización (404).
FOREIGN_TEAM = UUID(int=5555)
# Segmento que no existe en este partido y organización (404).
FOREIGN_SEGMENT = UUID(int=7777)

MATCH_DATE = datetime(2026, 5, 1, 12, 0, tzinfo=timezone.utc)

ACTIVE_SEGMENT = {
    "id": SEGMENT_1,
    "segment_number": 1,
    "minute_start": 0,
    "minute_end": None,
    "status": "active",
}
INTERRUPTED_SEGMENT = {
    "id": SEGMENT_1,
    "segment_number": 1,
    "minute_start": 0,
    "minute_end": 45,
    "status": "interrupted",
}


def context() -> AuthContext:
    return AuthContext(
        user_id=USER_ID,
        organization_id=ORGANIZATION_ID,
        organization_user_id=MEMBER_ID,
    )


def starter(number: int, team: UUID = HOME) -> UUID:
    return UUID(int=(number if team == HOME else 300 + number))


def substitute(number: int, team: UUID = HOME) -> UUID:
    return UUID(int=(100 + number if team == HOME else 400 + number))


def roster_rows(*, team: UUID = HOME, starters: int = 11, substitutes: int = 3) -> list[dict]:
    rows: list[dict] = []
    for index in range(1, starters + 1):
        rows.append(_roster_row(starter(index, team), team, "starter"))
    for index in range(1, substitutes + 1):
        rows.append(_roster_row(substitute(index, team), team, "substitute"))
    return rows


def _roster_row(player_id: UUID, team: UUID, role: str) -> dict:
    return {
        "player_id": player_id,
        "team_id": team,
        "role": role,
        "is_valid": True,
        "is_active": True,
        "valid_from": MATCH_DATE,
        "valid_to": None,
        "eligible_from": MATCH_DATE,
        "entered_minute": None,
        "left_minute": None,
    }


def rules_config() -> dict:
    config = deepcopy(DEFAULT_RULES_CONFIG)
    config["stage_defaults"] = {
        **config["stage_defaults"],
        "regular_time_minutes": 90,
        "extra_time_minutes": 120,
    }
    return config


def match_row(**overrides) -> dict:
    row = {
        "id": MATCH_ID,
        "tournament_id": TOURNAMENT_ID,
        "tournament_version_id": VERSION_ID,
        "matchday": 1,
        "match_date": MATCH_DATE,
        "bracket_code": None,
        "status": "scheduled",
        "stage_id": STAGE_ID,
        "home_team_id": HOME,
        "away_team_id": AWAY,
        "rules_config": rules_config(),
        "version_status": "published",
    }
    row.update(overrides)
    return row


# ---------------------------------------------------------------------------
# Doble de sesión: responde a las lecturas del cierre y registra cada escritura
# ---------------------------------------------------------------------------


class StopExecution(Exception):
    """Detiene el doble ante una consulta que el escenario no previó."""


class Result:
    def __init__(self, rows=None, scalar=None, rowcount=0):
        self._rows = list(rows or [])
        self._scalar = scalar
        self.rowcount = rowcount

    def mappings(self):
        return self

    def all(self):
        return list(self._rows)

    def first(self):
        return self._rows[0] if self._rows else None

    def one_or_none(self):
        return self._rows[0] if self._rows else None

    def one(self):
        assert self._rows, "se esperaba una fila"
        return self._rows[0]

    def scalar_one_or_none(self):
        return self._scalar

    def scalar_one(self):
        return self._scalar


class Transaction:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return False


class CloseOrderSession:
    """Sesión doble con los interruptores que necesita la matriz de precedencia."""

    def __init__(
        self,
        *,
        match: dict,
        rosters: list[dict],
        segments: list[dict],
        teams: list[UUID],
        allowed: bool = True,
        active_segment_available: bool = True,
        suspended: bool = False,
        match_available: bool = True,
        existing_events: list[dict] | None = None,
    ):
        self.match = match
        self.rosters = rosters
        self.segments = segments
        self.teams = teams
        self.allowed = allowed
        self.active_segment_available = active_segment_available
        self.suspended = suspended
        self.match_available = match_available
        self.existing_events = list(existing_events or [])
        self.statements: list[str] = []
        self.calls: list[tuple[str, dict]] = []
        self._event_rows: list[dict] = []

    def begin(self):
        return Transaction()

    async def execute(self, statement, params=None):
        sql = " ".join(str(statement).split())
        self.statements.append(sql)
        self.calls.append((sql, dict(params or {})))
        return self.handle(sql, dict(params or {}))

    @property
    def writes(self) -> list[str]:
        prefixes = ("INSERT", "UPDATE", "DELETE")
        return [sql for sql in self.statements if sql.upper().startswith(prefixes)]

    def parameters(self, fragment: str) -> list[dict]:
        return [params for sql, params in self.calls if fragment in sql]

    def handle(self, sql: str, params: dict) -> Result:
        if "set_config" in sql:
            return Result()
        if "SELECT id, tournament_id, tournament_version_id, stage_id, bracket_code" in sql:
            return Result(
                rows=[]
                if not self.match_available
                else [
                    {
                        "id": MATCH_ID,
                        "tournament_id": TOURNAMENT_ID,
                        "tournament_version_id": VERSION_ID,
                        "stage_id": STAGE_ID,
                        "bracket_code": None,
                    }
                ]
            )
        if "FROM roles r" in sql:
            # Una sola consulta resuelve la conjunción: permiso **y** (rol
            # operativo **o** asignación como oficial). Sin fila = 403.
            return Result(scalar=1 if self.allowed else None)
        if "SELECT id, tournament_version_id" in sql and "FROM stages" in sql:
            return Result(rows=[{"id": STAGE_ID, "tournament_version_id": VERSION_ID}])
        if "SELECT status" in sql and "FROM tournament_versions" in sql:
            return Result(scalar="published")
        if "FROM advancement_links" in sql:
            return Result(rows=[])
        if "id = ANY(CAST(:match_ids AS uuid[]))" in sql:
            return Result(rows=[{"id": MATCH_ID}])
        if "FOR UPDATE OF m" in sql:
            return Result(rows=[self.match])
        if "pg_advisory_xact_lock" in sql:
            return Result()
        if "FROM match_segments" in sql and "status = 'active'" in sql:
            if not self.active_segment_available or not self.segments:
                return Result(rows=[])
            segment = self.segments[-1]
            return Result(rows=[{"id": segment["id"], "minute_start": segment["minute_start"]}])
        if "FROM match_rosters mr" in sql:
            return Result(rows=self.rosters)
        if "FROM match_segments" in sql:
            return Result(rows=self.segments)
        if "SELECT id" in sql and "FROM teams" in sql:
            requested = {str(team_id) for team_id in params.get("team_ids") or []}
            return Result(rows=[{"id": team_id} for team_id in self.teams if str(team_id) in requested])
        if "FROM player_suspensions" in sql:
            if self.suspended:
                return Result(rows=[{"player_id": self.rosters[0]["player_id"]}])
            return Result(rows=[])
        if "FROM match_events" in sql and "client_event_id = :client_event_id" in sql:
            wanted = str(params.get("client_event_id") or "")
            return Result(
                rows=[row for row in self.existing_events if row.get("client_event_id") == wanted]
            )
        if "FROM match_events" in sql:
            return Result(rows=[])
        if sql.startswith("INSERT INTO match_events"):
            return Result(rows=[self._persist_event_row(params)])
        if sql.startswith(("INSERT", "UPDATE", "DELETE")):
            return Result()
        raise StopExecution(sql)

    def _persist_event_row(self, params: dict) -> dict:
        row = {
            "id": UUID(int=9800 + len(self._event_rows)),
            "event_type": params["event_type"],
            "team_id": UUID(str(params["team_id"])),
            "beneficiary_team_id": (
                UUID(str(params["beneficiary_team_id"])) if params.get("beneficiary_team_id") else None
            ),
            "player_id": UUID(str(params["player_id"])) if params.get("player_id") else None,
            "player_out_id": UUID(str(params["player_out_id"])) if params.get("player_out_id") else None,
            "player_in_id": UUID(str(params["player_in_id"])) if params.get("player_in_id") else None,
            "assist_player_id": (
                UUID(str(params["assist_player_id"])) if params.get("assist_player_id") else None
            ),
            "minute": params["minute"],
            "added_minute": params["added_minute"],
            "segment_id": UUID(str(params["segment_id"])),
        }
        self._event_rows.append(row)
        return row


# ---------------------------------------------------------------------------
# Escenarios: defectos de un solo paso, componibles entre sí
# ---------------------------------------------------------------------------


@dataclass
class State:
    """Defectos acumulables: cada uno toca el doble o el acta, nunca ambos."""

    session: dict[str, Any] = field(default_factory=dict)
    report: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Expected:
    """Lo que debe responder el primer defecto del orden."""

    status: int
    fragment: str
    code: str | None = None
    exception: type[BaseException] = HTTPException


def base_state() -> State:
    return State(
        report={
            "resolution_type": "regular",
            "home_score_regular": 0,
            "away_score_regular": 0,
        }
    )


def _match_overrides(state: State) -> dict:
    return state.session.setdefault("match_overrides", {})


def _add_event(state: State, event: MatchEventPayload) -> None:
    state.report.setdefault("events", []).append(event)


def _goal(
    state: State,
    *,
    team: UUID = HOME,
    player: UUID | None = None,
    segment_id: UUID = SEGMENT_1,
    minute: int = 30,
    added_minute: int = 0,
    label: str,
) -> None:
    _add_event(
        state,
        MatchEventPayload(
            client_event_id=event_id(label),
            event_type="goal",
            team_id=team,
            player_id=player or starter(2),
            minute=minute,
            added_minute=added_minute,
            segment_id=segment_id,
        ),
    )


def permission_denied(state: State) -> Expected:
    """Paso 2: la conjunción (permiso y rol operativo u oficial) no se cumple."""

    state.session["allowed"] = False
    return Expected(403, "Permiso requerido: CLOSE_MATCH_REPORT")


def finished_match(state: State) -> Expected:
    """Paso 3: un estado terminal no admite un cierre normal."""

    _match_overrides(state)["status"] = "finished"
    return Expected(409, "no admite cierre normal")


def unpublished_version(state: State) -> Expected:
    """Paso 3: la versión del torneo debe estar publicada."""

    _match_overrides(state)["version_status"] = "draft"
    return Expected(409, "no está publicada")


def missing_team(state: State) -> Expected:
    """Paso 4: el partido debe tener dos equipos participantes."""

    _match_overrides(state)["away_team_id"] = None
    return Expected(409, "dos equipos participantes")


def resolution_disabled(state: State) -> Expected:
    """Paso 5: la fase no habilita la resolución pedida."""

    state.report.update(
        resolution_type="extra_time",
        home_score=0,
        away_score=0,
        winner_team_id=HOME,
    )
    return Expected(409, "resolución no está habilitada", code=RESOLUTION_NOT_ENABLED)


def no_active_segment(state: State) -> Expected:
    """Paso 6: sin segmento activo no se cierra el acta (RF-017)."""

    state.session["active_segment_available"] = False
    state.session["segments"] = [dict(INTERRUPTED_SEGMENT)]
    return Expected(409, "necesita un segmento activo")


def foreign_segment(state: State) -> Expected:
    """Paso 6 / RF-020: un segmento de otra organización es 404."""

    _goal(state, segment_id=FOREIGN_SEGMENT, label="order-foreign-segment")
    return Expected(404, "Segmento no encontrado")


def foreign_team(state: State) -> Expected:
    """Paso 7 / RF-020: un equipo de otra organización es 404."""

    _goal(state, team=FOREIGN_TEAM, label="order-foreign-team")
    return Expected(404, "Equipo no encontrado")


def non_participating_team(state: State) -> Expected:
    """Paso 7: un equipo de la organización que no juega es 409."""

    state.session["teams"] = [OTHER_TEAM]
    _goal(state, team=OTHER_TEAM, label="order-other-team")
    return Expected(409, "no participa")


def non_participating_beneficiary(state: State) -> Expected:
    """Paso 7: el beneficiario del autogol debe participar en el partido."""

    state.session["teams"] = [OTHER_TEAM]
    _add_event(
        state,
        MatchEventPayload(
            client_event_id=event_id("order-other-beneficiary"),
            event_type="own_goal",
            team_id=HOME,
            beneficiary_team_id=OTHER_TEAM,
            player_id=starter(1),
            minute=20,
            segment_id=SEGMENT_1,
        ),
    )
    return Expected(409, "beneficiario no participa")


def incomplete_roster(state: State) -> Expected:
    """Paso 7: la plantilla debe tener al menos un jugador de cada equipo."""

    state.session["rosters"] = roster_rows()
    return Expected(409, "al menos un jugador de cada equipo")


def substitution_outside_the_field(state: State) -> Expected:
    """Paso 8: el estado en campo lo decide el motor puro, antes de escribir."""

    _add_event(
        state,
        MatchEventPayload(
            client_event_id=event_id("order-out-not-on-field"),
            event_type="substitution",
            team_id=HOME,
            player_id=substitute(1),
            player_out_id=substitute(1),
            player_in_id=substitute(2),
            minute=30,
            segment_id=SEGMENT_1,
        ),
    )
    return Expected(409, "no está en campo")


def invalid_assist(state: State) -> Expected:
    """Paso 9: el asistente del gol se valida después del estado en campo.

    El gol es del **minuto 10** y la sustitución inválida del paso 8 está en el
    30: una implementación que valide el asistente dentro del bucle canónico
    informa el asistente (minuto 10) antes que la sustitución (minuto 30), y el
    orden declarado dice lo contrario. El asistente es un suplente, así que no
    está en campo en el minuto del gol (``ASSIST_PLAYER_INVALID``).
    """

    _add_event(
        state,
        MatchEventPayload(
            client_event_id=event_id("order-invalid-assist"),
            event_type="goal",
            team_id=HOME,
            player_id=starter(2),
            assist_player_id=substitute(1),
            minute=10,
            segment_id=SEGMENT_1,
        ),
    )
    return Expected(
        409, "no está en campo en el minuto del gol", code=ASSIST_PLAYER_INVALID
    )


def double_yellow_inconsistent(state: State) -> Expected:
    """Paso 10: la roja por doble amarilla exige dos amarillas previas contadas.

    Con una sola amarilla el acta es incoherente (RF-006), así que este defecto
    se puede componer con cualquier otro paso para comprobar la precedencia.
    """

    _add_event(
        state,
        MatchEventPayload(
            client_event_id=event_id("order-double-yellow-card"),
            event_type="yellow_card",
            team_id=HOME,
            player_id=starter(1),
            minute=20,
            segment_id=SEGMENT_1,
        ),
    )
    _add_event(
        state,
        MatchEventPayload(
            client_event_id=event_id("order-double-yellow-red"),
            event_type="red_card",
            team_id=HOME,
            player_id=starter(1),
            minute=30,
            segment_id=SEGMENT_1,
            metadata={"red_card_type": "double_yellow_red"},
        ),
    )
    return Expected(
        409, "exactamente dos amarillas previas", code=DOUBLE_YELLOW_INCONSISTENT
    )


def score_mismatch(state: State) -> Expected:
    """Paso 11: el marcador reglamentario debe coincidir con los goles."""

    _goal(state, label="order-score-mismatch")
    return Expected(409, "marcador reglamentario no coincide")


def suspended_player(state: State) -> Expected:
    """Paso 12: la plantilla no admite un jugador con sanción vigente."""

    state.session["suspended"] = True
    return Expected(409, "jugador suspendido")


def score_coherence(state: State) -> Expected:
    """Paso 13: la coherencia numérica del marcador es de dominio (409)."""

    # `regular` con el final distinto del reglamentario: el marcador
    # reglamentario sí coincide con los goles (paso 11), así que el primer
    # defecto es el del paso 13.
    _goal(state, label="order-regular-final-mismatch")
    state.report.update(
        home_score_regular=1,
        away_score_regular=0,
        home_score=2,
        away_score=0,
        winner_team_id=HOME,
    )
    return Expected(409, "marcador de prórroga")


# El orden declarado (RF-001). Dos defectos del **mismo** número no tienen un
# ganador declarado por este orden: el desempate dentro del paso es el que ya
# tiene cada validación y se fija en sus propias pruebas.
DECLARED_STEPS: tuple[tuple[int, str, Callable[[State], Expected]], ...] = (
    (2, "permiso", permission_denied),
    (3, "estado", finished_match),
    (3, "versión", unpublished_version),
    (4, "dos equipos", missing_team),
    (5, "resolución habilitada", resolution_disabled),
    (6, "segmento activo", no_active_segment),
    (6, "estructura", foreign_segment),
    (7, "participantes", non_participating_team),
    (7, "aislamiento", foreign_team),
    (7, "beneficiario", non_participating_beneficiary),
    (7, "plantilla", incomplete_roster),
    (8, "sustituciones", substitution_outside_the_field),
    (9, "asistente", invalid_assist),
    (10, "doble amarilla", double_yellow_inconsistent),
    (11, "marcador", score_mismatch),
    (12, "sanciones", suspended_player),
    (13, "coherencia del marcador", score_coherence),
)


def build_session(state: State) -> CloseOrderSession:
    return CloseOrderSession(
        match=match_row(**{**state.session.get("match_overrides", {})}),
        rosters=state.session.get("rosters", roster_rows() + roster_rows(team=AWAY)),
        segments=state.session.get("segments", [dict(ACTIVE_SEGMENT)]),
        teams=state.session.get("teams", []),
        allowed=state.session.get("allowed", True),
        active_segment_available=state.session.get("active_segment_available", True),
        suspended=state.session.get("suspended", False),
        match_available=state.session.get("match_available", True),
        existing_events=state.session.get("existing_events"),
    )


def build_report(state: State) -> CloseMatchReportDTO:
    return CloseMatchReportDTO(**state.report)


def scenario(*defects: Callable[[State], Expected]) -> tuple[CloseOrderSession, CloseMatchReportDTO]:
    state = base_state()
    for defect in defects:
        defect(state)
    return build_session(state), build_report(state)


async def close_through_the_route(
    session: CloseOrderSession, report: CloseMatchReportDTO
) -> dict[str, Any]:
    return await matches_router.close_match(MATCH_ID, report, context(), session)


def assert_expected(error: BaseException, expected: Expected) -> None:
    assert isinstance(error, expected.exception), f"excepción inesperada: {error!r}"
    assert error.status_code == expected.status, getattr(error, "detail", error)
    detail = error.detail
    assert isinstance(detail, str), "los 409 y los 404 del cierre llevan `detail` cadena"
    assert expected.fragment in detail, detail
    if expected.code is None:
        assert getattr(error, "code", None) is None
    else:
        assert getattr(error, "code", None) == expected.code


# ---------------------------------------------------------------------------
# Matriz de precedencia exigida por la spec
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_resolution_not_enabled_wins_over_the_missing_active_segment():
    session, report = scenario(resolution_disabled, no_active_segment)

    with pytest.raises(HTTPException) as error:
        await close_through_the_route(session, report)

    assert_expected(error.value, resolution_disabled(base_state()))
    assert isinstance(error.value, ResolutionNotEnabled)
    assert session.writes == []


@pytest.mark.asyncio
async def test_a_segment_of_another_organization_wins_over_a_non_participating_team():
    # RF-020: el 404 del aislamiento precede al 409 de participantes.
    session, report = scenario(foreign_segment, non_participating_team)

    with pytest.raises(HTTPException) as error:
        await close_through_the_route(session, report)

    assert_expected(error.value, foreign_segment(base_state()))
    assert session.writes == []


@pytest.mark.asyncio
async def test_a_team_of_another_organization_wins_over_an_inconsistent_score():
    session, report = scenario(foreign_team, score_mismatch)

    with pytest.raises(HTTPException) as error:
        await close_through_the_route(session, report)

    assert_expected(error.value, foreign_team(base_state()))
    assert session.writes == []


@pytest.mark.asyncio
async def test_a_foreign_team_wins_over_a_non_participating_team_in_the_same_report():
    # Misma regla de identificadores dentro del paso 7: primero el 404.
    session, report = scenario(foreign_team, non_participating_team)

    with pytest.raises(HTTPException) as error:
        await close_through_the_route(session, report)

    assert_expected(error.value, foreign_team(base_state()))
    assert session.writes == []


@pytest.mark.asyncio
async def test_a_non_participating_team_wins_over_an_inconsistent_score():
    # Este es el defecto que antes se informaba después del marcador: ahora el
    # participantes del paso 7 gana al marcador del paso 11.
    session, report = scenario(non_participating_team, score_mismatch)

    with pytest.raises(HTTPException) as error:
        await close_through_the_route(session, report)

    assert_expected(error.value, non_participating_team(base_state()))
    assert session.writes == []


@pytest.mark.asyncio
async def test_a_non_participating_beneficiary_wins_over_an_inconsistent_score():
    # El beneficiario del autogol solo se comprobaba al persistir, después del
    # marcador: ahora es participantes del paso 7.
    session, report = scenario(non_participating_beneficiary, score_mismatch)

    with pytest.raises(HTTPException) as error:
        await close_through_the_route(session, report)

    assert_expected(error.value, non_participating_beneficiary(base_state()))
    assert session.writes == []


@pytest.mark.asyncio
async def test_the_missing_active_segment_wins_over_an_incomplete_roster():
    session, report = scenario(no_active_segment, incomplete_roster)

    with pytest.raises(HTTPException) as error:
        await close_through_the_route(session, report)

    assert_expected(error.value, no_active_segment(base_state()))
    assert session.writes == []


@pytest.mark.asyncio
async def test_resolution_not_enabled_wins_over_an_incomplete_roster():
    session, report = scenario(resolution_disabled, incomplete_roster)

    with pytest.raises(HTTPException) as error:
        await close_through_the_route(session, report)

    assert_expected(error.value, resolution_disabled(base_state()))
    assert session.writes == []


@pytest.mark.asyncio
async def test_the_roster_defect_wins_over_the_score_coherence_defect():
    # RF-001 y RF-007: el 409 de la coherencia numérica se informa en el paso
    # 13, así que un defecto del paso 7 gana.
    session, report = scenario(incomplete_roster, score_coherence)

    with pytest.raises(HTTPException) as error:
        await close_through_the_route(session, report)

    assert_expected(error.value, incomplete_roster(base_state()))
    assert session.writes == []


@pytest.mark.asyncio
async def test_sanctions_win_over_the_score_coherence_defect():
    # Paso 12 antes que 13: la coherencia del marcador es el último paso de
    # dominio antes de escribir.
    session, report = scenario(suspended_player, score_coherence)

    with pytest.raises(HTTPException) as error:
        await close_through_the_route(session, report)

    assert_expected(error.value, suspended_player(base_state()))
    assert session.writes == []


@pytest.mark.asyncio
async def test_the_score_mismatch_wins_over_the_score_coherence_defect():
    # Paso 11 antes que 13: son defectos distintos del marcador.
    session, report = scenario(score_mismatch, score_coherence)

    with pytest.raises(HTTPException) as error:
        await close_through_the_route(session, report)

    assert_expected(error.value, score_mismatch(base_state()))
    assert session.writes == []


@pytest.mark.asyncio
async def test_a_report_with_no_defect_closes_and_writes(monkeypatch):
    state = base_state()
    state.report.update(home_score_regular=1, away_score_regular=0, home_score=1, away_score=0)
    _goal(state, label="order-valid-close")
    session = build_session(state)
    report = build_report(state)

    async def noop(self, *args, **kwargs):
        return None

    monkeypatch.setattr(CloseMatchReportService, "_recalculate_standings", noop)
    monkeypatch.setattr(CloseMatchReportService, "_advance_bracket", noop)

    response = await close_through_the_route(session, report)

    assert response["status"] == "success"
    assert (response["home_score"], response["away_score"]) == (1, 0)
    assert response["winner_team_id"] == str(HOME)
    # La escritura ocurrió: partido, segmento, evento, contadores y outbox.
    assert any(sql.startswith("UPDATE matches SET") for sql in session.writes)
    update_match = session.parameters("UPDATE matches SET home_score_regular")[0]
    assert update_match["status"] == "finished"
    assert any(sql.startswith("UPDATE match_segments") for sql in session.writes)
    assert any(sql.startswith("INSERT INTO match_events") for sql in session.writes)
    assert any(sql.startswith("INSERT INTO match_segment_team_state") for sql in session.writes)
    outbox = [params["event_type"] for params in session.parameters("INSERT INTO outbox_events")]
    assert outbox == ["MATCH_CLOSED", "MATCH_UPDATED", "STANDINGS_UPDATED"]
    assert any(sql.startswith("INSERT INTO administrative_audit_logs") for sql in session.writes)


# ---------------------------------------------------------------------------
# El resultado se calcula antes de escribir (T3, RF-007 y RF-009)
# ---------------------------------------------------------------------------


def valid_goal_state() -> State:
    """Acta válida y mínima: un gol local y el marcador que le corresponde."""

    state = base_state()
    state.report.update(home_score_regular=1, away_score_regular=0, home_score=1, away_score=0)
    _goal(state, label="order-outcome-goal")
    return state


def stored_row(event: MatchEventPayload) -> dict:
    """Fila de `match_events` idéntica al evento de la petición (RF-008)."""

    return {
        "id": UUID(int=9850),
        "event_type": event.event_type,
        "team_id": event.team_id,
        "beneficiary_team_id": event.beneficiary_team_id,
        "player_id": event.player_id,
        "player_out_id": event.player_out_id,
        "player_in_id": event.player_in_id,
        "minute": event.minute,
        "added_minute": event.added_minute,
        "segment_id": event.segment_id,
        "assist_player_id": event.assist_player_id,
        "metadata": {},
        "client_event_id": event.client_event_id.lower(),
    }


async def close_without_side_effects(
    monkeypatch,
    session: CloseOrderSession,
    report: CloseMatchReportDTO,
) -> dict[str, Any]:
    async def noop(self, *args, **kwargs):
        return None

    monkeypatch.setattr(CloseMatchReportService, "_recalculate_standings", noop)
    monkeypatch.setattr(CloseMatchReportService, "_advance_bracket", noop)
    return await close_through_the_route(session, report)


def assert_nothing_was_written(session: CloseOrderSession) -> None:
    """Ni eventos, ni marcador, ni segmento, ni contadores, ni sanciones,
    clasificación, avance, auditoría u outbox: el paso 13 no escribe."""

    assert session.writes == [], session.writes


@pytest.mark.asyncio
async def test_an_incoherent_regular_final_writes_nothing():
    # Antes de la T3 el defecto del paso 13 se descubría después de insertar el
    # gol: la transacción lo deshacía, pero el orden declarado no se respetaba.
    session, report = scenario(score_coherence)

    with pytest.raises(HTTPException) as error:
        await close_through_the_route(session, report)

    assert_expected(error.value, score_coherence(base_state()))
    assert_nothing_was_written(session)


@pytest.mark.asyncio
async def test_an_incoherent_winner_writes_nothing():
    state = valid_goal_state()
    state.report["winner_team_id"] = AWAY
    session = build_session(state)

    with pytest.raises(HTTPException) as error:
        await close_through_the_route(session, build_report(state))

    assert error.value.status_code == 409
    assert "ganador informado no coincide" in error.value.detail
    assert_nothing_was_written(session)


@pytest.mark.asyncio
async def test_a_walkover_with_an_incoherent_score_writes_nothing():
    # El walkover no admite eventos (422 del esquema) y deriva el marcador de la
    # configuración: informar otro es un defecto de dominio del paso 13. El
    # motivo de catálogo (T3) se informa para que el 422 no lo intercepte antes.
    state = base_state()
    state.report.update(
        resolution_type="walkover",
        home_score_regular=1,
        away_score_regular=0,
        winner_team_id=HOME,
        reason="no_show",
    )
    session = build_session(state)

    with pytest.raises(HTTPException) as error:
        await close_through_the_route(session, build_report(state))

    assert error.value.status_code == 409
    assert "walkover" in error.value.detail
    assert_nothing_was_written(session)


@pytest.mark.asyncio
async def test_an_administrative_resolution_with_an_incoherent_score_writes_nothing():
    state = base_state()
    state.report.update(
        resolution_type="administrative",
        home_score_regular=1,
        away_score_regular=0,
        home_score=2,
        away_score=0,
        winner_team_id=HOME,
        reason="Resolución administrativa",
    )
    session = build_session(state)

    with pytest.raises(HTTPException) as error:
        await close_through_the_route(session, build_report(state))

    assert error.value.status_code == 409
    assert "único marcador final" in error.value.detail
    assert_nothing_was_written(session)


@pytest.mark.asyncio
async def test_a_reused_event_produces_the_same_outcome_as_a_new_one(monkeypatch):
    """Equivalencia idempotente (RF-008) del cálculo del paso 13.

    El resultado se calcula con los eventos de la **petición**. Un evento que
    ya estaba persistido se reutiliza solo si es idéntico (si difiere, 409
    «inmutable»), así que el marcador contado sobre la petición y el contado
    sobre las filas guardadas coinciden; esta prueba lo fija con el mismo acta
    en los dos caminos.
    """

    fresh_state = valid_goal_state()
    fresh_report = build_report(fresh_state)
    fresh_session = build_session(fresh_state)
    fresh_response = await close_without_side_effects(monkeypatch, fresh_session, fresh_report)

    reused_state = valid_goal_state()
    reused_report = build_report(reused_state)
    reused_state.session["existing_events"] = [stored_row(event) for event in reused_report.events]
    reused_session = build_session(reused_state)
    reused_response = await close_without_side_effects(monkeypatch, reused_session, reused_report)

    assert reused_response == fresh_response
    assert any(sql.startswith("INSERT INTO match_events") for sql in fresh_session.writes)
    assert not any(sql.startswith("INSERT INTO match_events") for sql in reused_session.writes)

    # El motor puro obtiene el mismo resultado con los eventos de la petición y
    # con las filas que se habrían persistido.
    arguments = ("regular", HOME, AWAY, 1, 0, 1, 0, None, None, None)
    from_request = compute_match_outcome(
        rules_config(),
        [
            {
                "event_type": event.event_type,
                "team_id": event.team_id,
                "beneficiary_team_id": event.beneficiary_team_id,
            }
            for event in fresh_report.events
        ],
        *arguments,
    )
    from_persisted = compute_match_outcome(
        rules_config(),
        [stored_row(event) for event in fresh_report.events],
        *arguments,
    )
    assert from_request == from_persisted
    assert fresh_response["home_score"] == from_persisted.home_score
    assert fresh_response["away_score"] == from_persisted.away_score
    assert fresh_response["winner_team_id"] == str(from_persisted.winner_team_id)


@pytest.mark.asyncio
async def test_the_match_is_looked_up_before_the_permission_step():
    # La existencia y el aislamiento se resuelven al cargar el partido: 404
    # incluso con la autorización sin resolver (RF-001).
    state = base_state()
    state.session["match_available"] = False
    state.session["allowed"] = False
    session = build_session(state)

    with pytest.raises(HTTPException) as error:
        await close_through_the_route(session, build_report(state))

    assert error.value.status_code == 404
    assert "Partido no encontrado" in error.value.detail
    assert session.writes == []


@pytest.mark.asyncio
async def test_participants_keep_the_engine_codes_of_the_single_identifier_rule():
    """El paso 7 conserva los códigos internos que ya usaba el motor puro."""

    session, report = scenario(non_participating_team)
    with pytest.raises(SubstitutionError) as error:
        await CloseMatchReportService(session).execute(context(), MATCH_ID, report)
    assert error.value.code is SubstitutionErrorCode.TEAM_MISMATCH
    assert session.writes == []

    state = base_state()
    state.report.update(home_score_regular=1, away_score_regular=0, home_score=1, away_score=0)
    _add_event(
        state,
        MatchEventPayload(
            client_event_id=event_id("order-player-outsider"),
            event_type="goal",
            team_id=HOME,
            player_id=UUID(int=999),
            minute=30,
            segment_id=SEGMENT_1,
        ),
    )
    session = build_session(state)
    with pytest.raises(SubstitutionError) as error:
        await CloseMatchReportService(session).execute(context(), MATCH_ID, build_report(state))
    # Un jugador de otra organización (o fuera de la plantilla) es 409, nunca 404.
    assert error.value.code is SubstitutionErrorCode.PLAYER_NOT_IN_ROSTER
    assert session.writes == []


@pytest.mark.asyncio
async def test_a_member_without_the_conjunction_answers_403():
    # El doble devuelve una sola consulta para la conjunción completa, así que
    # aquí se fija el **403** sin distinguir el motivo: «permiso sin rol
    # operativo ni asignación» y «oficial asignado sin permiso» son la misma
    # ausencia de fila en `require_permission` (RF-002). Los dos casos con roles
    # reales —un árbitro con el permiso y sin asignación y un observador
    # asignado como oficial sin el permiso— se ejercen contra PostgreSQL en
    # `tests/test_close_authorization_db.py`.
    session, report = scenario(permission_denied)

    with pytest.raises(HTTPException) as error:
        await close_through_the_route(session, report)

    assert error.value.status_code == 403
    assert "CLOSE_MATCH_REPORT" in error.value.detail
    assert session.writes == []


# ---------------------------------------------------------------------------
# Paso 8 antes que 9, y 9 antes que 10, 11, 12 y 13 (RF-001)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_field_state_defect_wins_over_an_assist_at_an_earlier_minute():
    """El orden es por **paso**, no por minuto (RF-001).

    El asistente inválido está en el minuto 10 y la sustitución inválida en el
    30. Mientras el asistente se validaba dentro del bucle canónico del replay,
    el minuto 10 ganaba; con el orden declarado gana el paso 8, que es el que
    informa el primer defecto.
    """

    session, report = scenario(substitution_outside_the_field, invalid_assist)

    with pytest.raises(HTTPException) as error:
        await close_through_the_route(session, report)

    assert_expected(error.value, substitution_outside_the_field(base_state()))
    # No es el 409 del asistente: ese llega después, y aquí no se informa.
    assert getattr(error.value, "code", None) is None
    assert session.writes == []


STEP_9_LATER_DEFECTS = (
    double_yellow_inconsistent,
    score_mismatch,
    suspended_player,
    score_coherence,
)


@pytest.mark.parametrize(
    "later",
    STEP_9_LATER_DEFECTS,
    ids=[defect.__name__ for defect in STEP_9_LATER_DEFECTS],
)
@pytest.mark.asyncio
async def test_the_assist_wins_over_every_later_step(later):
    """El paso 9 gana a 10 (doble amarilla), 11 (marcador), 12 y 13."""

    session, report = scenario(invalid_assist, later)

    with pytest.raises(HTTPException) as error:
        await close_through_the_route(session, report)

    assert_expected(error.value, invalid_assist(base_state()))
    assert session.writes == []


# ---------------------------------------------------------------------------
# Estructura del acta: intervalo del evento y monotonía entre segmentos (RF-003)
# ---------------------------------------------------------------------------


def assert_structure_conflict(session, error, fragment: str) -> None:
    assert isinstance(error.value, HTTPException)
    assert error.value.status_code == 409
    assert isinstance(error.value.detail, str)
    assert fragment in error.value.detail, error.value.detail
    assert session.writes == []


@pytest.mark.asyncio
async def test_an_event_before_the_start_of_its_segment_is_a_domain_409():
    # El minuto del evento se mide contra **su** segmento, no solo contra el
    # máximo de la resolución.
    state = base_state()
    state.session["segments"] = [
        {
            "id": SEGMENT_1,
            "segment_number": 1,
            "minute_start": 20,
            "minute_end": None,
            "status": "active",
        }
    ]
    _goal(state, minute=10, label="structure-before-segment-start")
    session = build_session(state)

    with pytest.raises(HTTPException) as error:
        await close_through_the_route(session, build_report(state))

    assert_structure_conflict(session, error, "antes del inicio de su segmento")


@pytest.mark.asyncio
async def test_an_event_after_the_end_of_its_segment_is_a_domain_409():
    state = base_state()
    state.session["segments"] = [
        {
            "id": SEGMENT_1,
            "segment_number": 1,
            "minute_start": 0,
            "minute_end": 45,
            "status": "completed",
        },
        {
            "id": SEGMENT_2,
            "segment_number": 2,
            "minute_start": 45,
            "minute_end": None,
            "status": "active",
        },
    ]
    # El minuto 60 cabe en el máximo de la resolución (90), pero no en el
    # intervalo del segmento al que el evento dice pertenecer.
    _goal(state, segment_id=SEGMENT_1, minute=60, label="structure-after-segment-end")
    session = build_session(state)

    with pytest.raises(HTTPException) as error:
        await close_through_the_route(session, build_report(state))

    assert_structure_conflict(session, error, "después del final de su segmento")


@pytest.mark.asyncio
async def test_segments_whose_times_overlap_are_a_domain_409():
    # Monotonía **entre** segmentos: el segundo no puede empezar antes del final
    # del anterior.
    state = base_state()
    state.session["segments"] = [
        {
            "id": SEGMENT_1,
            "segment_number": 1,
            "minute_start": 0,
            "minute_end": 45,
            "status": "completed",
        },
        {
            "id": SEGMENT_2,
            "segment_number": 2,
            "minute_start": 30,
            "minute_end": None,
            "status": "active",
        },
    ]
    session = build_session(state)

    with pytest.raises(HTTPException) as error:
        await close_through_the_route(session, build_report(state))

    assert_structure_conflict(session, error, "tiempos incompatibles")


@pytest.mark.asyncio
async def test_an_event_in_an_interrupted_segment_is_a_domain_409():
    # RF-014: un segmento interrumpido no admite eventos, ni en el borrador ni
    # al cerrar.
    state = base_state()
    state.session["segments"] = [
        {
            "id": SEGMENT_1,
            "segment_number": 1,
            "minute_start": 0,
            "minute_end": 45,
            "status": "interrupted",
        },
        {
            "id": SEGMENT_2,
            "segment_number": 2,
            "minute_start": 45,
            "minute_end": None,
            "status": "active",
        },
    ]
    _goal(state, segment_id=SEGMENT_1, minute=20, label="structure-interrupted-segment")
    session = build_session(state)

    with pytest.raises(HTTPException) as error:
        await close_through_the_route(session, build_report(state))

    assert_structure_conflict(session, error, "segmento interrumpido")


# ---------------------------------------------------------------------------
# El minuto reglamentario no mira el minuto añadido (RF-007)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_goal_in_the_added_time_of_the_regular_minute_counts_as_regular(monkeypatch):
    """Un gol en el 90+3 con reglamentario 90 es **reglamentario**.

    La clasificación usa solo ``minute``; si el añadido interviniera, el gol
    caería en la prórroga y una resolución ``regular`` lo rechazaría.
    """

    state = base_state()
    state.report.update(home_score_regular=1, away_score_regular=0, home_score=1, away_score=0)
    _goal(state, minute=90, added_minute=3, label="regular-minute-90-plus-3")
    session = build_session(state)

    response = await close_without_side_effects(monkeypatch, session, build_report(state))

    assert (response["home_score"], response["away_score"]) == (1, 0)
    assert response["status"] == "success"
    update_match = session.parameters("UPDATE matches SET home_score_regular")[0]
    assert update_match["home_score_regular"] == 1
    assert update_match["away_score_regular"] == 0


@pytest.mark.asyncio
async def test_a_goal_after_the_regular_minute_is_rejected_by_a_regular_resolution():
    # El límite está en el minuto, no en la suma: el 91 con reglamentario 90 no
    # cabe en una resolución `regular` y el cierre es 409. El 90+3 sí cabía.
    state = base_state()
    _goal(state, minute=91, label="regular-minute-91")
    session = build_session(state)

    with pytest.raises(HTTPException) as error:
        await close_through_the_route(session, build_report(state))

    assert error.value.status_code == 409
    assert "máximo de 90 minutos" in error.value.detail
    assert session.writes == []


# ---------------------------------------------------------------------------
# El orden no es accidental: cada pareja de pasos distintos informa el anterior
# ---------------------------------------------------------------------------

# Pares (anterior, posterior) en los que el posterior no depende del anterior.
# Se recorren todos los pares del orden declarado con pasos distintos.
ORDER_PAIRS = [
    (earlier, later)
    for index, earlier in enumerate(DECLARED_STEPS)
    for later in DECLARED_STEPS[index + 1 :]
    if earlier[0] != later[0]
]


@pytest.mark.parametrize(
    ("earlier", "later"),
    ORDER_PAIRS,
    ids=[f"{earlier[1]}-{later[1]}" for earlier, later in ORDER_PAIRS],
)
@pytest.mark.asyncio
async def test_two_domain_defects_report_the_earlier_step(earlier, later):
    earlier_step, earlier_name, earlier_defect = earlier
    later_step, later_name, later_defect = later
    assert earlier_step < later_step

    session, report = scenario(earlier_defect, later_defect)

    with pytest.raises(HTTPException) as error:
        await close_through_the_route(session, report)

    assert_expected(error.value, earlier_defect(base_state()))
    assert session.writes == [], (
        f"el paso {earlier_step} ({earlier_name}) escribió; el posterior era "
        f"{later_step} ({later_name})"
    )


# ---------------------------------------------------------------------------
# Walkover (spec 016, T6): escalón propio dentro de la misma matriz
# ---------------------------------------------------------------------------
#
# La rama del walkover **se inserta** en el orden de la 017: no reordena nada.
# Sus defectos siguen siendo eslabones de la misma cadena (RF-001, RF-002,
# RF-003, RF-005, RF-008), así que se declaran aquí, con el mismo `State`, el
# mismo `Expected` y el mismo doble de sesión que el resto de la matriz:
#
# 2   permiso (conjunción, RF-002) — precede a la rama;
# 3   estado (RF-001) y versión publicada;
# 4   dos equipos participantes;
# 13.1 el ganador declarado participa (409 sin `code`, mensaje del motor);
# 13.2 la pareja efectiva da la victoria al ganador (D-4/D-5);
# 13.3 el marcador informado coincide con el derivado (D-10/RF-005).
#
# El paso 5 (resolución habilitada) **no tiene defecto posible** para el
# walkover: `resolution_enabled` lo admite sin mirar la configuración (plan
# §5.1), así que no compite con nada y se fija en su propia prueba.


def walkover_base(state: State) -> None:
    """Convierte el acta del escenario en un walkover, sin perder defectos.

    La primera vez quita la pareja reglamentaria del escenario base: el walkover
    se declara **sin** marcadores (RF-005) y un 0-0 heredado sería el desajuste
    del paso 13.3. Las llamadas siguientes solo fijan la resolución y el motivo,
    para que dos defectos compuestos se acumulen.
    """

    if not state.session.get("walkover"):
        state.session["walkover"] = True
        state.report.pop("home_score_regular", None)
        state.report.pop("away_score_regular", None)
        state.report["winner_team_id"] = HOME
    state.report["resolution_type"] = "walkover"
    state.report["reason"] = "no_show"


def _walkover_pair(state: State, winner: int, loser: int) -> None:
    """Configuración efectiva con la pareja de walkover publicada (D-3/D-5)."""

    config = deepcopy(DEFAULT_RULES_CONFIG)
    config["stage_defaults"] = {
        **config["stage_defaults"],
        "walkover_score": {"winner": winner, "loser": loser},
    }
    _match_overrides(state)["rules_config"] = config


def walkover_permission_denied(state: State) -> Expected:
    """Paso 2: la conjunción se resuelve **antes** de la rama (RF-002)."""

    walkover_base(state)
    state.session["allowed"] = False
    return Expected(403, "Permiso requerido: CLOSE_MATCH_REPORT")


def walkover_state_not_allowed(state: State) -> Expected:
    """Paso 3: `suspended` y los tres terminales llevan el código del walkover."""

    walkover_base(state)
    _match_overrides(state)["status"] = "suspended"
    return Expected(
        409,
        "no admite la declaración de un walkover",
        code=WALKOVER_STATE_NOT_ALLOWED,
        exception=WalkoverStateNotAllowed,
    )


def walkover_unpublished_version(state: State) -> Expected:
    """Paso 3: el walkover no se declara sobre una versión en borrador."""

    walkover_base(state)
    _match_overrides(state)["version_status"] = "draft"
    return Expected(409, "no está publicada")


def walkover_missing_team(state: State) -> Expected:
    """Paso 4: el walkover también exige los dos participantes."""

    walkover_base(state)
    _match_overrides(state)["away_team_id"] = None
    return Expected(409, "dos equipos participantes")


def walkover_winner_does_not_play(state: State) -> Expected:
    """13.1: un ganador que no participa es 409 **sin** `code` (plan §6.2)."""

    walkover_base(state)
    state.report["winner_team_id"] = OTHER_TEAM
    return Expected(409, "El ganador informado no participa en el partido")


def walkover_config_inconsistent(state: State) -> Expected:
    """13.2: pareja efectiva 0-3 publicada antes de D-3 → su propio `code`."""

    walkover_base(state)
    _walkover_pair(state, 0, 3)
    return Expected(
        409,
        "no da la victoria al ganador declarado",
        code=WALKOVER_CONFIG_INCONSISTENT,
        exception=WalkoverConfigInconsistent,
    )


def walkover_score_mismatch(state: State) -> Expected:
    """13.3: un marcador informado distinto del derivado (D-10, RF-005)."""

    walkover_base(state)
    state.report.update(home_score_regular=1, away_score_regular=0)
    return Expected(
        409,
        "no coincide con la configuración",
        code=WALKOVER_SCORE_MISMATCH,
        exception=WalkoverScoreMismatch,
    )


# Los tres últimos comparten el paso 13′ del orden declarado (la rama tiene su
# versión reducida del 13), y se numeran 13.1/13.2/13.3 en el orden en que la
# rama los informa (RF-008 y D-4). Los 422 estructurales no están aquí: se
# resuelven antes del handler y se prueban al final del archivo.
DECLARED_WALKOVER_STEPS: tuple[tuple[float | int, str, Callable[[State], Expected]], ...] = (
    (2, "permiso (walkover)", walkover_permission_denied),
    (3, "estado (walkover)", walkover_state_not_allowed),
    (3, "versión (walkover)", walkover_unpublished_version),
    (4, "dos equipos (walkover)", walkover_missing_team),
    (13.1, "ganador (walkover)", walkover_winner_does_not_play),
    (13.2, "configuración (walkover)", walkover_config_inconsistent),
    (13.3, "marcador informado (walkover)", walkover_score_mismatch),
)

# El walkover tiene sus defectos en su propio escalón: los pares cruzados con el
# tronco **no** se recorren aquí, porque cada defecto del tronco describe un acta
# jugada y el walkover la omite por completo (RF-003). Las dos excepciones que sí
# se cruzan —el 403 del paso 2 y el 422 estructural— tienen su prueba explícita.
WALKOVER_ORDER_PAIRS = [
    (earlier, later)
    for index, earlier in enumerate(DECLARED_WALKOVER_STEPS)
    for later in DECLARED_WALKOVER_STEPS[index + 1 :]
    if earlier[0] != later[0]
]


@pytest.mark.parametrize(
    ("earlier", "later"),
    WALKOVER_ORDER_PAIRS,
    ids=[f"{earlier[1]}-{later[1]}" for earlier, later in WALKOVER_ORDER_PAIRS],
)
@pytest.mark.asyncio
async def test_two_walkover_defects_report_the_earlier_step(earlier, later):
    """La escalera del walkover respeta el orden de los 14 pasos (RF-001)."""

    earlier_step, earlier_name, earlier_defect = earlier
    later_step, later_name, later_defect = later
    assert earlier_step < later_step, f"{earlier_name} debe preceder a {later_name}"

    session, report = scenario(earlier_defect, later_defect)

    with pytest.raises(HTTPException) as error:
        await close_through_the_route(session, report)

    assert_expected(error.value, earlier_defect(base_state()))
    assert_nothing_was_written(session)


@pytest.mark.asyncio
async def test_walkover_state_not_allowed_wins_over_every_act_defect():
    """El paso 3 gana a cualquier defecto del acta, también del walkover.

    La petición acumula el estado inadmisible, la pareja incoherente y un
    marcador informado distinto: responde el estado y no escribe.
    """

    state = base_state()
    expected = walkover_state_not_allowed(state)
    walkover_config_inconsistent(state)
    walkover_score_mismatch(state)
    session = build_session(state)

    with pytest.raises(HTTPException) as error:
        await close_through_the_route(session, build_report(state))

    assert_expected(error.value, expected)
    assert_nothing_was_written(session)


@pytest.mark.asyncio
async def test_the_winner_that_does_not_play_sits_between_the_state_and_the_config():
    """Orden exacto del 13′: ganador → pareja coherente → marcador (D-4)."""

    # 1) El ganador gana a la pareja incoherente.
    session, report = scenario(walkover_winner_does_not_play, walkover_config_inconsistent)
    with pytest.raises(HTTPException) as error:
        await close_through_the_route(session, report)
    assert_expected(error.value, walkover_winner_does_not_play(base_state()))
    assert getattr(error.value, "code", None) is None
    assert_nothing_was_written(session)

    # 2) La pareja incoherente gana al marcador informado (D-4).
    session, report = scenario(walkover_config_inconsistent, walkover_score_mismatch)
    with pytest.raises(HTTPException) as error:
        await close_through_the_route(session, report)
    assert_expected(error.value, walkover_config_inconsistent(base_state()))
    assert_nothing_was_written(session)


@pytest.mark.asyncio
async def test_a_walkover_without_segment_and_without_roster_reaches_the_write(monkeypatch):
    """RF-003: sin segmento activo, sin segmentos y sin plantilla cierra.

    Es la exención que la 017 delegó en la 016: el tronco respondería «necesita
    un segmento activo» (paso 6) y «al menos un jugador de cada equipo» (paso 7)
    y el walkover no llega a mirarlos.
    """

    state = base_state()
    walkover_base(state)
    state.session["active_segment_available"] = False
    state.session["segments"] = []
    state.session["rosters"] = []
    session = build_session(state)

    response = await close_without_side_effects(monkeypatch, session, build_report(state))

    assert response["status"] == "success"
    assert (response["home_score"], response["away_score"]) == (3, 0)
    assert response["winner_team_id"] == str(HOME)
    joined = " ".join(session.statements)
    assert "match_rosters" not in joined
    assert "player_suspensions" not in joined
    # Sin segmentos no se crea ninguno ni se cierra nada (RF-004).
    assert not any(sql.startswith("UPDATE match_segments") for sql in session.writes)
    assert not any(sql.startswith("INSERT INTO match_segments") for sql in session.writes)
    match_update = session.parameters("UPDATE matches SET")[0]
    assert match_update["resolution_reason"] == "no_show"
    assert match_update["status"] == "finished"


@pytest.mark.asyncio
async def test_a_walkover_with_an_incomplete_roster_does_not_fail(monkeypatch):
    """RF-003: una plantilla de un solo equipo no impide la declaración."""

    state = base_state()
    walkover_base(state)
    state.session["rosters"] = roster_rows()
    session = build_session(state)

    response = await close_without_side_effects(monkeypatch, session, build_report(state))

    assert response["status"] == "success"
    assert (response["home_score"], response["away_score"]) == (3, 0)


@pytest.mark.asyncio
async def test_a_walkover_with_an_active_segment_closes_it_without_interrupting(monkeypatch):
    """RF-004: el segmento activo se cierra en su inicio; nada más cambia."""

    state = base_state()
    walkover_base(state)
    state.session["segments"] = [
        {
            "id": SEGMENT_1,
            "segment_number": 1,
            "minute_start": 45,
            "minute_end": None,
            "status": "active",
        }
    ]
    session = build_session(state)

    response = await close_without_side_effects(monkeypatch, session, build_report(state))

    assert response["status"] == "success"
    segment_update = session.parameters("UPDATE match_segments")[0]
    assert segment_update["segment_id"] == str(SEGMENT_1)
    assert segment_update["minute_end"] == 45
    joined = " ".join(session.statements)
    assert "interrupted" not in joined
    assert "match_segment_team_state" not in joined


@pytest.mark.asyncio
async def test_the_walkover_branch_never_calls_the_forbidden_helpers(monkeypatch):
    """D-6 y RNF-008: la rama no lee plantilla, contadores ni sanciones.

    Se sustituyen los ayudantes —no se inspecciona el SQL— para que la prueba
    falle si alguien mueve una llamada por delante de la rama, aunque su
    sentencia cambie de texto.
    """

    forbidden = (
        "_load_match_rosters",
        "_lock_player",
        "_load_match_segments",
        "_validate_rosters",
        "_validate_segments",
        "_validate_substitutions",
        "_validate_event_score_consistency",
        "_validate_double_yellow",
        "_validate_suspensions",
        "_load_discipline_history",
        "_serve_suspensions",
        "_insert_suspensions",
        "_rewrite_segment_team_state",
        "_persist_events",
    )
    called: list[str] = []

    for name in forbidden:
        async def explode(*args, __name=name, **kwargs):
            called.append(__name)
            raise AssertionError(f"la rama del walkover llamó a {__name}")

        monkeypatch.setattr(CloseMatchReportService, name, explode)

    state = base_state()
    walkover_base(state)
    session = build_session(state)

    response = await close_without_side_effects(monkeypatch, session, build_report(state))

    assert response["status"] == "success"
    assert called == []


def test_the_resolution_step_cannot_disable_a_walkover():
    """Paso 5: el walkover se admite con la configuración por defecto.

    `resolution_enabled` lo admite sin mirar los indicadores de prórroga y
    penales, así que el 409 `RESOLUTION_NOT_ENABLED` **no** puede competir con la
    rama (plan §5.1): no existe un escenario con «walkover no habilitado».
    """

    minutes = effective_match_minutes(rules_config(), STAGE_ID)

    assert minutes["extra_time_enabled"] is False
    assert minutes["penalties_enabled"] is False
    assert resolution_enabled(minutes, "walkover") is True
    assert resolution_enabled(minutes, "extra_time") is False
    assert resolution_enabled(minutes, "penalties") is False


# ---------------------------------------------------------------------------
# Los 422 estructurales prevalecen sobre cualquier 409 (RF-001, excepción
# declarada)
# ---------------------------------------------------------------------------


@pytest.fixture
async def api_client():
    """Cliente HTTP de la app real con sesión e identidad sustituidas.

    El cuerpo inválido no llega al handler, así que la base nunca se usa: el
    doble de sesión no ejecuta nada y basta para que la ruta se resuelva.
    """

    async def auth_context() -> AuthContext:
        return context()

    async def session():
        yield None

    api.dependency_overrides[get_auth_context] = auth_context
    api.dependency_overrides[get_db] = session
    try:
        async with AsyncClient(
            transport=ASGITransport(app=api), base_url="http://test"
        ) as client:
            yield client
    finally:
        api.dependency_overrides.pop(get_auth_context, None)
        api.dependency_overrides.pop(get_db, None)


def structural_body(**overrides) -> dict:
    """Acta con la coherencia numérica del paso 13 rota y un defecto estructural."""

    body = {
        "resolution_type": "regular",
        "home_score_regular": 1,
        "away_score_regular": 0,
        # `regular` con el final distinto del reglamentario: sería el 409 del
        # paso 13 si el handler llegara a ejecutarse.
        "home_score": 2,
        "away_score": 0,
        "winner_team_id": str(HOME),
        "events": [],
    }
    body.update(overrides)
    return body


@pytest.mark.asyncio
async def test_a_structural_defect_prevails_over_the_domain_409(api_client):
    # `reason` no aplica a `regular`: 422 del esquema, antes del handler.
    response = await api_client.post(
        f"/api/v1/matches/{MATCH_ID}/close",
        json=structural_body(reason="no aplica"),
    )

    assert response.status_code == 422
    body = response.json()
    assert isinstance(body["detail"], list), "los 422 llevan una lista saneada"
    assert "code" not in body, "los 422 no llevan `code`"
    assert "marcador de prórroga" not in response.text
    assert any(
        "La razón solo aplica" in error["msg"] for error in body["detail"]
    ), body["detail"]
    for error in body["detail"]:
        assert set(error) == {"type", "loc", "msg"}, error


@pytest.mark.asyncio
async def test_a_duplicated_client_event_id_prevails_over_the_domain_409(api_client):
    # El mismo `client_event_id` dos veces en el acta es estructural (RF-003),
    # no el 409 de un paso de dominio.
    duplicated = str(event_id("order-structural-duplicate"))
    event = {
        "client_event_id": duplicated,
        "event_type": "goal",
        "team_id": str(HOME),
        "player_id": str(starter(2)),
        "minute": 10,
        "segment_id": str(SEGMENT_1),
    }
    response = await api_client.post(
        f"/api/v1/matches/{MATCH_ID}/close",
        json=structural_body(events=[event, dict(event)]),
    )

    assert response.status_code == 422
    body = response.json()
    assert isinstance(body["detail"], list)
    assert "code" not in body
    assert "marcador de prórroga" not in response.text


# ---------------------------------------------------------------------------
# Walkover: un 422 estructural gana a cualquier 409 de la rama (spec 016)
# ---------------------------------------------------------------------------


def walkover_structural_body(**overrides) -> dict:
    """Walkover con un marcador informado que sería el 409 del 13.3.

    Con la configuración por defecto el derivado es 3-0, así que un 1-0
    informado es `WALKOVER_SCORE_MISMATCH` si el handler llegara a ejecutarse:
    sirve de defecto de dominio para comprobar que el 422 estructural del
    esquema se resuelve antes.
    """

    body = {
        "resolution_type": "walkover",
        "winner_team_id": str(HOME),
        "reason": "no_show",
        "home_score_regular": 1,
        "away_score_regular": 0,
        "events": [],
    }
    body.update(overrides)
    return body


@pytest.mark.asyncio
async def test_a_structural_walkover_defect_prevails_over_the_walkover_409(api_client):
    # Un motivo fuera del catálogo es 422 del esquema (RF-007), antes del
    # handler: gana al `WALKOVER_SCORE_MISMATCH` que informaría la rama.
    response = await api_client.post(
        f"/api/v1/matches/{MATCH_ID}/close",
        json=walkover_structural_body(reason="home_win"),
    )

    assert response.status_code == 422
    body = response.json()
    assert isinstance(body["detail"], list), "los 422 llevan una lista saneada"
    assert "code" not in body, "los 422 no llevan `code`"
    assert "no coincide con la configuración" not in response.text
    assert any(
        "El motivo del walkover no es válido" in error["msg"] for error in body["detail"]
    ), body["detail"]


@pytest.mark.asyncio
async def test_an_event_in_a_walkover_prevails_over_the_walkover_409(api_client):
    # La prohibición de eventos en el walkover (RF-006) es estructural y gana al
    # 409 del marcador informado.
    event = {
        "client_event_id": str(event_id("order-walkover-structural-event")),
        "event_type": "goal",
        "team_id": str(HOME),
        "player_id": str(starter(2)),
        "minute": 10,
        "segment_id": str(SEGMENT_1),
    }
    response = await api_client.post(
        f"/api/v1/matches/{MATCH_ID}/close",
        json=walkover_structural_body(events=[event]),
    )

    assert response.status_code == 422
    body = response.json()
    assert isinstance(body["detail"], list)
    assert "code" not in body
    assert "no coincide con la configuración" not in response.text
    assert any(
        "no permite eventos individuales" in error["msg"] for error in body["detail"]
    ), body["detail"]
