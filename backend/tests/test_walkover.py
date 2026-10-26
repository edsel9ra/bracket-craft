"""Walkover: configuración y DTO del cierre (spec 016, T2 y T3).

RF-011: guardar o publicar la configuración de reglas exige que la pareja del
walkover tenga al ganador por delante; el resto de valores no negativos se
aceptan tal cual. RF-013: ni ``engine_version`` ni la forma de
``walkover_score`` cambian.

T3 (RF-005, RF-006, RF-007, RNF-003): el DTO del cierre acepta un walkover
**sin** marcadores, exige la pareja reglamentaria en el resto de resoluciones y
cambia el dominio de ``reason`` —obligatorio y de catálogo cerrado en
``walkover``, texto libre en ``administrative`` y prohibido en las demás—. La
**coherencia numérica** del marcador sigue siendo del motor (409, spec 017):
aquí solo se prueba la **presencia** de los campos por resolución (422).

T4 (RF-001, RF-005, RF-008): los tres códigos de dominio del walkover
—``WALKOVER_STATE_NOT_ALLOWED``, ``WALKOVER_SCORE_MISMATCH`` y
``WALKOVER_CONFIG_INCONSISTENT``— son **409** con ``detail`` de cadena y
``code`` aditivo, los maneja el manejador único de ``app/main.py`` y no se
cachean. Esta tarea entrega las excepciones y su contrato HTTP; la lógica que
las lanza es T5.

D-2: la comprobación vive en una función **aparte**
(``validate_walkover_score``) que solo se llama al guardar (DTO de payload) y
al publicar (router). Deliberadamente **no** se llama desde
``validate_rules_config``: esa función corre también al cerrar el acta, al
recalcular la clasificación y al clonar versiones, donde una pareja histórica
incoherente debe seguir leyéndose y donde un ``ValueError`` sin captura sería
un 500. Este archivo comprueba las dos caras: la validación nueva y la
ausencia de revalidación en el cierre, la clasificación y el clonado.

Las pruebas no necesitan PostgreSQL: usan dobles de sesión y funciones puras.
"""

from __future__ import annotations

import json
from copy import deepcopy
from datetime import date
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException, Request
from httpx import ASGITransport, AsyncClient
from pydantic import ValidationError

from app import main as main_module
from app.core.database import get_db
from app.core.tenancy import AuthContext, get_auth_context
from app.main import api
from app.modules.matches.errors import (
    ASSIST_PLAYER_INVALID,
    DOUBLE_YELLOW_INCONSISTENT,
    RESOLUTION_NOT_ENABLED,
    WALKOVER_CONFIG_INCONSISTENT,
    WALKOVER_SCORE_MISMATCH,
    WALKOVER_STATE_NOT_ALLOWED,
    AssistPlayerInvalid,
    DoubleYellowInconsistent,
    ResolutionNotEnabled,
    WalkoverConfigInconsistent,
    WalkoverScoreMismatch,
    WalkoverStateNotAllowed,
)
from app.modules.rules_engine.defaults import DEFAULT_RULES_CONFIG
from app.modules.rules_engine.engine import (
    compute_match_outcome,
    normalize_rules_config,
    validate_rules_config,
    validate_walkover_score,
)
from app.modules.matches.schemas import (
    WALKOVER_REASONS,
    CloseMatchReportDTO,
    MatchEventPayload,
)
from app.modules.rules_engine.schemas import (
    CreateTournamentRequest,
    TournamentRulesConfig,
    UpdateRulesConfigRequest,
)
from app.modules.tournaments.router import (
    _create_draft_version_record,
    publish_version,
)

ORGANIZATION_ID = uuid4()
USER_ID = uuid4()
MEMBER_ID = uuid4()
TOURNAMENT_ID = uuid4()
VERSION_ID = uuid4()
SOURCE_VERSION_ID = uuid4()
NEW_VERSION_ID = uuid4()
HOME_TEAM_ID = uuid4()
AWAY_TEAM_ID = uuid4()

# Orden lexicográfico inverso al de inserción: así el mensaje estable se nota.
SMALLER_STAGE_ID = UUID("00000000-0000-4000-8000-000000000001")
LARGER_STAGE_ID = UUID("00000000-0000-4000-8000-000000000002")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def context() -> AuthContext:
    return AuthContext(
        user_id=USER_ID,
        organization_id=ORGANIZATION_ID,
        organization_user_id=MEMBER_ID,
    )


def rules_config(
    *,
    default_pair: tuple[int, int] | None = None,
    overrides: dict[UUID, tuple[int, int]] | None = None,
) -> dict:
    """A complete rules config with an optional walkover pair per scope."""

    config = deepcopy(DEFAULT_RULES_CONFIG)
    if default_pair is not None:
        config["stage_defaults"]["walkover_score"] = {
            "winner": default_pair[0],
            "loser": default_pair[1],
        }
    if overrides:
        config["stage_overrides"] = {
            str(stage_id): {
                "walkover_score": {"winner": winner, "loser": loser}
            }
            for stage_id, (winner, loser) in overrides.items()
        }
    return config


def pair_of(config: dict) -> tuple[int, int]:
    score = config["stage_defaults"]["walkover_score"]
    return score["winner"], score["loser"]


class StopExecution(Exception):
    """Stop a route or handler once the assertion point has been reached."""


class Result:
    def __init__(self, rows=None, scalar=None, rowcount=0):
        self._rows = list(rows or [])
        self._scalar = scalar
        self.rowcount = rowcount

    def mappings(self):
        return self

    def all(self):
        return list(self._rows)

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


class RecordingSession:
    """AsyncSession double that records every statement and dispatches by SQL."""

    def __init__(self, handle):
        self.handle = handle
        self.statements: list[str] = []
        self.calls: list[tuple[str, dict]] = []

    def begin(self):
        return Transaction()

    async def execute(self, statement, params=None):
        sql = " ".join(str(statement).split())
        self.statements.append(sql)
        self.calls.append((sql, dict(params or {})))
        return self.handle(sql, dict(params or {}))

    def parameters_for(self, prefix: str) -> list[dict]:
        return [params for sql, params in self.calls if sql.startswith(prefix)]


# ---------------------------------------------------------------------------
# validate_walkover_score: la pareja configurada
# ---------------------------------------------------------------------------


def test_the_default_pair_is_valid():
    """RF-011: el default 3-0 sigue siendo válido y no cambia."""

    assert pair_of(deepcopy(DEFAULT_RULES_CONFIG)) == (3, 0)
    validate_walkover_score(deepcopy(DEFAULT_RULES_CONFIG))


@pytest.mark.parametrize("pair", [(3, 0), (3, 1), (5, 0), (1, 0)])
def test_a_winner_ahead_is_accepted_with_any_non_negative_pair(pair):
    """RF-011: cualquier pareja con el ganador por delante se acepta."""

    validate_walkover_score(rules_config(default_pair=pair))


def test_a_level_pair_is_rejected_and_names_the_pair():
    """RF-011: ``winner == loser`` no da un ganador."""

    with pytest.raises(ValueError) as error:
        validate_walkover_score(rules_config(default_pair=(0, 0)))

    message = str(error.value)
    assert "stage_defaults" in message
    assert "0-0" in message
    assert "ganador por delante" in message


def test_a_pair_where_the_winner_loses_is_rejected_and_names_the_pair():
    """RF-011: ``winner < loser`` invertiría la tabla de la clasificación."""

    with pytest.raises(ValueError) as error:
        validate_walkover_score(rules_config(default_pair=(0, 3)))

    message = str(error.value)
    assert "stage_defaults" in message
    assert "0-3" in message


def test_an_incoherent_stage_override_is_rejected_with_its_scope():
    """RF-011: se valida **cada** override, no solo ``stage_defaults``."""

    config = rules_config(overrides={SMALLER_STAGE_ID: (2, 2)})

    with pytest.raises(ValueError) as error:
        validate_walkover_score(config)

    message = str(error.value)
    assert f"stage_id {SMALLER_STAGE_ID}" in message
    assert "2-2" in message


def test_an_allowed_stage_override_is_accepted():
    """RF-011: un override con el ganador por delante es válido (3-1)."""

    validate_walkover_score(
        rules_config(overrides={SMALLER_STAGE_ID: (3, 1), LARGER_STAGE_ID: (5, 2)})
    )


def test_two_incoherent_overrides_report_the_first_in_stable_order():
    """RNF-006: con dos overrides incoherentes el mensaje es determinista."""

    config = rules_config(
        overrides={LARGER_STAGE_ID: (0, 5), SMALLER_STAGE_ID: (0, 4)}
    )

    with pytest.raises(ValueError) as first:
        validate_walkover_score(config)
    with pytest.raises(ValueError) as second:
        validate_walkover_score(deepcopy(config))

    message = str(first.value)
    assert str(first.value) == str(second.value)
    assert f"stage_id {SMALLER_STAGE_ID}" in message
    assert "0-4" in message
    assert f"stage_id {LARGER_STAGE_ID}" not in message


def test_stage_defaults_win_the_report_when_it_is_the_incoherent_scope():
    """RNF-006: ``stage_defaults`` va primero en el orden de ámbitos."""

    config = rules_config(
        default_pair=(0, 3), overrides={SMALLER_STAGE_ID: (1, 1)}
    )

    with pytest.raises(ValueError) as error:
        validate_walkover_score(config)

    message = str(error.value)
    assert "stage_defaults" in message
    assert "0-3" in message
    assert f"stage_id {SMALLER_STAGE_ID}" not in message


def test_negative_values_are_rejected_by_the_function_itself():
    """RF-011: la función exige dos enteros ≥ 0."""

    with pytest.raises(ValueError) as error:
        validate_walkover_score(rules_config(default_pair=(-1, 0)))

    assert "-1-0" in str(error.value) or "-1" in str(error.value)


# ---------------------------------------------------------------------------
# Guardar reglas: el DTO de payload responde 422 (RF-011)
# ---------------------------------------------------------------------------


def test_saving_a_level_pair_is_rejected_by_the_payload_schema():
    with pytest.raises(ValidationError) as error:
        UpdateRulesConfigRequest(rules_config=rules_config(default_pair=(1, 1)))

    assert "1-1" in str(error.value)


def test_saving_a_pair_where_the_winner_loses_is_rejected_by_the_payload_schema():
    with pytest.raises(ValidationError) as error:
        UpdateRulesConfigRequest(rules_config=rules_config(default_pair=(0, 3)))

    assert "0-3" in str(error.value)


def test_saving_an_incoherent_override_is_rejected_by_the_payload_schema():
    with pytest.raises(ValidationError) as error:
        TournamentRulesConfig.model_validate(
            rules_config(overrides={SMALLER_STAGE_ID: (0, 2)})
        )

    assert f"stage_id {SMALLER_STAGE_ID}" in str(error.value)
    assert "0-2" in str(error.value)


def test_creating_a_tournament_with_an_incoherent_pair_is_rejected():
    with pytest.raises(ValidationError) as error:
        CreateTournamentRequest(
            name="Copa 016",
            season="2026",
            start_date=date(2026, 1, 1),
            rules_config=rules_config(default_pair=(0, 0)),
        )

    assert "0-0" in str(error.value)


def test_negative_values_are_rejected_by_the_payload_schema():
    """El esquema ya exige enteros ≥ 0; la pareja no relaja esa garantía."""

    with pytest.raises(ValidationError) as error:
        UpdateRulesConfigRequest(rules_config=rules_config(default_pair=(-1, 0)))

    assert "winner" in str(error.value)


def test_saving_an_allowed_pair_keeps_the_normalized_config():
    payload = UpdateRulesConfigRequest(
        rules_config=rules_config(default_pair=(3, 1))
    )

    assert pair_of(payload.rules_config.model_dump(mode="json")) == (3, 1)
    assert payload.rules_config.schema_version == "3.3.0"
    assert payload.rules_config.engine_version == "2026.1"


@pytest.mark.asyncio
async def test_the_rules_route_answers_422_without_writing():
    """RF-011: la ruta real de guardado responde 422 y no escribe nada."""

    session = RecordingSession(
        lambda sql, params: (_ for _ in ()).throw(
            AssertionError(f"no debe consultar ni escribir: {sql}")
        )
    )

    async def _db():
        yield session

    async def _context() -> AuthContext:
        return context()

    api.dependency_overrides[get_db] = _db
    api.dependency_overrides[get_auth_context] = _context
    try:
        async with AsyncClient(
            transport=ASGITransport(app=api), base_url="http://test"
        ) as client:
            response = await client.patch(
                f"/api/v1/tournaments/{TOURNAMENT_ID}/versions/{VERSION_ID}/rules",
                json={"rules_config": rules_config(default_pair=(0, 3))},
            )
    finally:
        api.dependency_overrides.pop(get_db, None)
        api.dependency_overrides.pop(get_auth_context, None)

    assert response.status_code == 422
    assert "0-3" in response.text
    assert session.statements == []


# ---------------------------------------------------------------------------
# Publicar reglas: el router mapea el ValueError a 422 (RF-011)
# ---------------------------------------------------------------------------


def publish_session(rules: dict, *, reach_readiness: bool = False) -> RecordingSession:
    """Session double for ``publish_version`` up to the rules validation."""

    def handle(sql, params):
        if "set_config" in sql:
            return Result()
        if "FROM roles r" in sql:
            return Result(scalar=1)
        if "FROM tournament_versions tv" in sql:
            return Result(
                rows=[
                    {
                        "id": VERSION_ID,
                        "tournament_id": TOURNAMENT_ID,
                        "status": "draft",
                        "rules_config": deepcopy(rules),
                        "tournament_status": "draft",
                        "published_version_id": None,
                    }
                ]
            )
        if reach_readiness and "AS stage_count" in sql:
            raise StopExecution(sql)
        raise AssertionError(f"consulta inesperada: {sql}")

    return RecordingSession(handle)


@pytest.mark.asyncio
async def test_publishing_an_incoherent_pair_answers_422():
    """RF-011: publicar un borrador con la pareja incoherente no publica nada."""

    session = publish_session(rules_config(default_pair=(0, 3)))

    with pytest.raises(HTTPException) as error:
        await publish_version(VERSION_ID, context(), session)

    assert error.value.status_code == 422
    assert "0-3" in str(error.value.detail)
    assert "walkover" in str(error.value.detail)
    assert not any(
        sql.startswith(("UPDATE", "INSERT", "DELETE")) for sql in session.statements
    )


@pytest.mark.asyncio
async def test_publishing_an_incoherent_override_answers_422():
    session = publish_session(rules_config(overrides={SMALLER_STAGE_ID: (2, 2)}))

    with pytest.raises(HTTPException) as error:
        await publish_version(VERSION_ID, context(), session)

    assert error.value.status_code == 422
    assert "2-2" in str(error.value.detail)
    assert not any(
        sql.startswith(("UPDATE", "INSERT", "DELETE")) for sql in session.statements
    )


@pytest.mark.asyncio
async def test_publishing_an_allowed_pair_goes_past_the_validation():
    """RF-011: una pareja válida (3-1) no bloquea la publicación."""

    session = publish_session(
        rules_config(default_pair=(3, 1)), reach_readiness=True
    )

    with pytest.raises(StopExecution):
        await publish_version(VERSION_ID, context(), session)

    assert any("AS stage_count" in sql for sql in session.statements)


# ---------------------------------------------------------------------------
# D-2: ningún otro camino revalida la pareja
# ---------------------------------------------------------------------------


def test_the_shared_rule_validator_does_not_revalidate_the_pair():
    """D-2: ``validate_rules_config`` corre al cerrar, clasificar y clonar."""

    validate_rules_config(rules_config(default_pair=(0, 3)))
    validate_rules_config(rules_config(overrides={SMALLER_STAGE_ID: (0, 0)}))


def test_the_cloning_normalisation_does_not_revalidate_the_pair():
    """D-2/D-11: copiar una versión publicada no es «guardar»."""

    cloned = normalize_rules_config(rules_config(default_pair=(0, 3)))

    assert pair_of(cloned) == (0, 3)


def test_the_close_still_reads_an_incoherent_published_pair():
    """RF-008/RF-011: el caso histórico se resuelve en el cierre (409), no 500."""

    outcome = compute_match_outcome(
        rules_config(default_pair=(0, 3)),
        [],
        "walkover",
        HOME_TEAM_ID,
        AWAY_TEAM_ID,
        0,
        3,
        None,
        None,
        None,
        None,
        HOME_TEAM_ID,
    )

    assert (outcome.home_score, outcome.away_score) == (0, 3)
    assert outcome.winner_team_id == HOME_TEAM_ID


@pytest.mark.parametrize("pair", [(3, 0), (3, 1), (5, 0)])
def test_compute_match_outcome_keeps_working_for_valid_pairs(pair):
    """Sin regresión: la pareja válida se deriva igual que antes."""

    winner, loser = pair
    outcome = compute_match_outcome(
        rules_config(default_pair=pair),
        [],
        "walkover",
        HOME_TEAM_ID,
        AWAY_TEAM_ID,
        winner,
        loser,
        winner,
        loser,
        None,
        None,
        HOME_TEAM_ID,
    )

    assert (outcome.home_score, outcome.away_score) == (winner, loser)
    assert outcome.home_penalties is None
    assert outcome.away_penalties is None

    reversed_outcome = compute_match_outcome(
        rules_config(default_pair=pair),
        [],
        "walkover",
        HOME_TEAM_ID,
        AWAY_TEAM_ID,
        loser,
        winner,
        loser,
        winner,
        None,
        None,
        AWAY_TEAM_ID,
    )

    assert (reversed_outcome.home_score, reversed_outcome.away_score) == (
        loser,
        winner,
    )
    assert reversed_outcome.winner_team_id == AWAY_TEAM_ID


# ---------------------------------------------------------------------------
# Clonado de una versión con pareja incoherente: no hay 500 (D-11)
# ---------------------------------------------------------------------------


def clone_session(rules: dict) -> RecordingSession:
    """Session double for ``_create_draft_version_record`` (empty structure)."""

    def handle(sql, params):
        if "set_config" in sql:
            return Result()
        if "FROM roles r" in sql:
            return Result(scalar=1)
        if "SELECT 1 FROM tournaments" in sql:
            return Result(scalar=1)
        if "SELECT published_version_id, status" in sql:
            return Result(
                rows=[
                    {
                        "published_version_id": SOURCE_VERSION_ID,
                        "status": "draft",
                    }
                ]
            )
        if "SELECT id, rules_config, phase_config, status" in sql:
            return Result(
                rows=[
                    {
                        "id": SOURCE_VERSION_ID,
                        "rules_config": deepcopy(rules),
                        "phase_config": {},
                        "status": "published",
                    }
                ]
            )
        if sql.startswith("SELECT id FROM tournament_versions"):
            return Result(scalar=None)
        if sql.startswith("SELECT COALESCE(MAX(version_number), 0) + 1"):
            return Result(scalar=1)
        if sql.startswith("INSERT INTO tournament_versions"):
            return Result()
        if "FROM stages" in sql:
            return Result(rows=[])
        if sql.startswith("UPDATE tournament_versions"):
            return Result()
        if "FROM groups" in sql:
            return Result(rows=[])
        if "FROM phase_slots" in sql:
            return Result(rows=[])
        if "FROM stage_teams" in sql:
            return Result(rows=[])
        if "FROM matches" in sql:
            return Result(rows=[])
        if "FROM advancement_links" in sql:
            return Result(rows=[])
        if sql.startswith("UPDATE tournaments"):
            return Result()
        if "SELECT id, version_number, status, published_at, created_at, rules_config" in sql:
            return Result(
                rows=[
                    {
                        "id": str(NEW_VERSION_ID),
                        "version_number": 2,
                        "status": "draft",
                        "published_at": None,
                        "created_at": None,
                        "rules_config": deepcopy(rules),
                    }
                ]
            )
        raise AssertionError(f"consulta inesperada: {sql}")

    return RecordingSession(handle)


@pytest.mark.asyncio
async def test_cloning_an_incoherent_published_version_is_not_a_500():
    """D-11: copiar una versión publicada incoherente no falla ni se reescribe."""

    session = clone_session(rules_config(default_pair=(0, 3)))

    cloned = await _create_draft_version_record(
        session, context(), TOURNAMENT_ID, None
    )

    assert pair_of(cloned["rules_config"]) == (0, 3)
    updates = session.parameters_for("UPDATE tournament_versions")
    assert len(updates) == 1
    assert '"winner": 0' in updates[0]["rules"]
    assert '"loser": 3' in updates[0]["rules"]


@pytest.mark.asyncio
async def test_cloning_an_incoherent_override_is_not_a_500():
    """El override se copia tal cual, sin revalidar la pareja (D-11)."""

    session = clone_session(rules_config(overrides={SMALLER_STAGE_ID: (1, 1)}))

    cloned = await _create_draft_version_record(
        session, context(), TOURNAMENT_ID, None
    )

    override = cloned["rules_config"]["stage_overrides"][str(SMALLER_STAGE_ID)]
    assert override["walkover_score"] == {"winner": 1, "loser": 1}


# ---------------------------------------------------------------------------
# DTO del cierre (T3): qué campos son obligatorios en cada resolución
# ---------------------------------------------------------------------------

# El catálogo cerrado de RF-007: no hay texto libre ni código «otra».
CATALOGUE_REASONS = ("no_show", "withdrawal", "insufficient_players", "sanction")


def goal_event(team_id: UUID | None = None) -> MatchEventPayload:
    """Un evento estructuralmente válido para probar la prohibición."""

    return MatchEventPayload(
        client_event_id=str(uuid4()),
        event_type="goal",
        team_id=team_id or HOME_TEAM_ID,
        player_id=uuid4(),
        minute=10,
        segment_id=uuid4(),
    )


def walkover(**overrides) -> CloseMatchReportDTO:
    body = {
        "resolution_type": "walkover",
        "winner_team_id": HOME_TEAM_ID,
        "reason": "no_show",
    }
    body.update(overrides)
    return CloseMatchReportDTO(**body)


def test_the_walkover_reason_catalogue_is_closed():
    """RF-007: cuatro códigos, ni uno más ni uno menos."""

    assert WALKOVER_REASONS == CATALOGUE_REASONS


def test_a_walkover_without_any_score_is_accepted():
    """RF-005/D-9: el servidor deriva los seis marcadores que no se informan."""

    report = walkover()

    assert report.home_score_regular is None
    assert report.away_score_regular is None
    assert report.home_score is None
    assert report.away_score is None
    assert report.home_penalties is None
    assert report.away_penalties is None


@pytest.mark.parametrize("reason", CATALOGUE_REASONS)
def test_a_walkover_accepts_every_catalogue_reason(reason):
    """RF-007: los cuatro códigos del catálogo son válidos."""

    assert walkover(reason=reason).reason == reason


def test_a_walkover_accepts_reported_scores_and_leaves_coherence_to_the_engine():
    """RF-005/D-10: con marcadores informados el DTO no decide coherencia."""

    report = walkover(
        home_score_regular=3,
        away_score_regular=0,
        home_score=3,
        away_score=0,
    )

    assert (report.home_score_regular, report.away_score_regular) == (3, 0)
    assert (report.home_score, report.away_score) == (3, 0)


def test_a_walkover_still_requires_the_winner():
    """RF-001: la falta de ganador sigue siendo 422."""

    with pytest.raises(ValidationError, match="winner_team_id"):
        walkover(winner_team_id=None)


def test_a_walkover_without_a_reason_is_rejected():
    """RF-007: el motivo deja de ser opcional en el walkover."""

    with pytest.raises(ValidationError, match="motivo"):
        walkover(reason=None)


@pytest.mark.parametrize(
    "reason", ["home_win", "No_Show", "no-show", "other", "walkover"]
)
def test_a_walkover_reason_outside_the_catalogue_is_rejected(reason):
    """RF-007: fuera del catálogo es 422; no hay texto libre ni alias."""

    with pytest.raises(ValidationError, match="motivo del walkover"):
        walkover(reason=reason)


def test_a_walkover_reason_is_normalized_before_the_catalogue_check():
    """RF-007: el espacio sobrante no convierte un código válido en inválido."""

    assert walkover(reason="  withdrawal  ").reason == "withdrawal"


@pytest.mark.parametrize("reason", ["", "   "])
def test_an_empty_walkover_reason_is_rejected(reason):
    """RF-007: el motivo no puede quedar vacío tras normalizarse."""

    with pytest.raises(ValidationError):
        walkover(reason=reason)


def test_a_half_informed_regular_pair_is_rejected_in_a_walkover():
    """Presencia, no coherencia: un marcador reglamentario suelto es 422."""

    with pytest.raises(ValidationError, match="reglamentarios"):
        walkover(home_score_regular=3)


def test_a_walkover_with_events_is_still_rejected():
    """RF-006: la prohibición de eventos vigente no cambia."""

    with pytest.raises(ValidationError, match="no permite eventos"):
        walkover(events=[goal_event()])


@pytest.mark.parametrize(
    "scores",
    [
        {"home_penalties": 4, "away_penalties": 3},
        {"home_penalties": 4},
        {"away_penalties": 3},
    ],
)
def test_a_walkover_with_penalties_is_rejected(scores):
    """RF-005: los penales solo aplican con `resolution_type=penalties` (422).

    Un walkover no juega tanda, así que informar la pareja de penales —completa
    o suelta— es un error estructural del acta, no una decisión del operador.
    """

    with pytest.raises(ValidationError, match="penales"):
        walkover(**scores)


def test_a_walkover_without_penalties_stays_valid():
    """RF-005: el walkover válido no informa penales y el DTO los deja nulos."""

    report = walkover()

    assert report.resolution_type == "walkover"
    assert (report.home_penalties, report.away_penalties) == (None, None)
    assert report.winner_team_id == HOME_TEAM_ID
    assert report.reason == "no_show"


def test_the_administrative_resolution_still_requires_a_reason():
    """RF-007: la administrativa mantiene su motivo obligatorio."""

    with pytest.raises(ValidationError, match="requiere una razón"):
        CloseMatchReportDTO(
            resolution_type="administrative",
            home_score_regular=0,
            away_score_regular=0,
            home_score=0,
            away_score=0,
            winner_team_id=HOME_TEAM_ID,
        )


def test_the_administrative_resolution_keeps_free_text():
    """D-8: el catálogo es solo del walkover; la administrativa no cambia."""

    report = CloseMatchReportDTO(
        resolution_type="administrative",
        home_score_regular=0,
        away_score_regular=0,
        home_score=0,
        away_score=0,
        winner_team_id=HOME_TEAM_ID,
        reason="  Incomparecencia del club visitante  ",
    )

    assert report.reason == "Incomparecencia del club visitante"


def test_the_administrative_resolution_still_forbids_events():
    """RF-006: la prohibición sigue cubriendo la administrativa."""

    with pytest.raises(ValidationError, match="no permite eventos"):
        CloseMatchReportDTO(
            resolution_type="administrative",
            home_score_regular=0,
            away_score_regular=0,
            home_score=0,
            away_score=0,
            winner_team_id=HOME_TEAM_ID,
            reason="Sancion administrativa",
            events=[goal_event()],
        )


# Cierres válidos de cada resolución **sin** el marcador reglamentario: solo el
# walkover puede omitirlo (el resto del cuerpo está completo).
REPORTS_WITHOUT_REGULAR_PAIR = {
    "regular": {},
    "extra_time": {
        "home_score": 1,
        "away_score": 0,
        "winner_team_id": HOME_TEAM_ID,
    },
    "penalties": {
        "home_score": 0,
        "away_score": 0,
        "home_penalties": 4,
        "away_penalties": 3,
        "winner_team_id": HOME_TEAM_ID,
    },
    "administrative": {
        "home_score": 0,
        "away_score": 0,
        "winner_team_id": HOME_TEAM_ID,
        "reason": "Sancion administrativa",
    },
}


@pytest.mark.parametrize(
    "resolution_type", sorted(REPORTS_WITHOUT_REGULAR_PAIR)
)
def test_the_regular_pair_is_still_required_outside_walkover(resolution_type):
    """D-9: la pareja reglamentaria solo deja de ser obligatoria en walkover."""

    with pytest.raises(ValidationError, match="marcadores reglamentarios"):
        CloseMatchReportDTO(
            resolution_type=resolution_type,
            **REPORTS_WITHOUT_REGULAR_PAIR[resolution_type],
        )


@pytest.mark.parametrize("resolution_type", ["regular", "extra_time", "penalties"])
def test_the_reason_is_still_forbidden_in_sporting_resolutions(resolution_type):
    """RF-007: el motivo solo aplica a walkover y administrativa."""

    body = {
        "regular": {"winner_team_id": HOME_TEAM_ID},
        "extra_time": {
            "home_score": 1,
            "away_score": 0,
            "winner_team_id": HOME_TEAM_ID,
        },
        "penalties": {
            "home_score": 0,
            "away_score": 0,
            "home_penalties": 4,
            "away_penalties": 3,
            "winner_team_id": HOME_TEAM_ID,
        },
    }[resolution_type]

    with pytest.raises(ValidationError, match="solo aplica"):
        CloseMatchReportDTO(
            resolution_type=resolution_type,
            home_score_regular=1,
            away_score_regular=0,
            reason="no aplica",
            **body,
        )


def test_a_valid_closure_of_every_resolution_is_still_accepted():
    """Sin regresión: cada resolución conserva un cierre válido."""

    regular = CloseMatchReportDTO(
        resolution_type="regular", home_score_regular=1, away_score_regular=0
    )
    extra_time = CloseMatchReportDTO(
        resolution_type="extra_time",
        home_score_regular=1,
        away_score_regular=0,
        home_score=2,
        away_score=0,
        winner_team_id=HOME_TEAM_ID,
    )
    penalties = CloseMatchReportDTO(
        resolution_type="penalties",
        home_score_regular=1,
        away_score_regular=1,
        home_score=1,
        away_score=1,
        home_penalties=4,
        away_penalties=3,
        winner_team_id=HOME_TEAM_ID,
    )
    administrative = CloseMatchReportDTO(
        resolution_type="administrative",
        home_score_regular=0,
        away_score_regular=3,
        home_score=0,
        away_score=3,
        winner_team_id=AWAY_TEAM_ID,
        reason="Retirada del club local",
    )

    assert regular.resolution_type == "regular"
    assert (extra_time.home_score, extra_time.away_score) == (2, 0)
    assert (penalties.home_penalties, penalties.away_penalties) == (4, 3)
    assert administrative.reason == "Retirada del club local"
    assert walkover().resolution_type == "walkover"


# ---------------------------------------------------------------------------
# T4: los tres códigos de dominio del walkover (RF-001, RF-005, RF-008)
# ---------------------------------------------------------------------------

# Cada error con su código: el nombre y el valor son contrato.
WALKOVER_ERRORS = (
    (WalkoverStateNotAllowed, WALKOVER_STATE_NOT_ALLOWED),
    (WalkoverScoreMismatch, WALKOVER_SCORE_MISMATCH),
    (WalkoverConfigInconsistent, WALKOVER_CONFIG_INCONSISTENT),
)

# Texto libre que un cliente podría enviar en otro campo del acta (el motivo de
# una resolución administrativa, por ejemplo). Ningún mensaje lo repite.
CLIENT_SENTINEL = "Incomparecencia del club visitante <script>"


def close_request() -> Request:
    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": (
                "/api/v1/matches/00000000-0000-4000-8000-000000000001/close"
            ),
            "headers": [],
            "query_string": b"",
        }
    )


@pytest.mark.parametrize("error_class, code", WALKOVER_ERRORS)
def test_each_walkover_error_is_registered_with_the_coded_handler(error_class, code):
    """RF-001/RF-005/RF-008: el manejador único de ``main.py`` los traduce."""

    assert main_module.api.exception_handlers.get(error_class) is (
        main_module._coded_exception_handler
    )
    assert issubclass(error_class, HTTPException)
    assert error_class().status_code == 409
    assert error_class().code == code


@pytest.mark.asyncio
@pytest.mark.parametrize("error_class, code", WALKOVER_ERRORS)
async def test_each_walkover_error_answers_409_with_a_string_detail_and_the_code(
    error_class, code
):
    """El cuerpo es ``{detail: str, code}`` y la respuesta no se cachea."""

    handler = main_module.api.exception_handlers[error_class]

    response = await handler(close_request(), error_class())

    body = json.loads(response.body)
    assert response.status_code == 409
    assert set(body) == {"detail", "code"}
    assert isinstance(body["detail"], str) and body["detail"]
    assert body["code"] == code
    assert response.headers["cache-control"] == "no-store"


@pytest.mark.asyncio
@pytest.mark.parametrize("error_class, code", WALKOVER_ERRORS)
async def test_the_walkover_error_body_does_not_echo_client_data(
    error_class, code
):
    """RNF-002: ni datos personales ni el texto que envió el cliente."""

    handler = main_module.api.exception_handlers[error_class]

    response = await handler(close_request(), error_class())
    text = response.body.decode()

    assert CLIENT_SENTINEL not in text
    for forbidden in ("input", "ctx", "player", "document", "birth_date", "email"):
        assert forbidden not in text


def test_the_state_detail_names_the_server_status():
    """RF-001: el mensaje nombra el estado leído del servidor, no del cliente."""

    detail = str(WalkoverStateNotAllowed("suspended").detail)

    assert "suspended" in detail
    assert "walkover" in detail
    assert WalkoverStateNotAllowed().code == WALKOVER_STATE_NOT_ALLOWED


def test_the_pair_details_name_the_configured_pair():
    """RF-005/RF-008: el mensaje nombra la pareja efectiva, no la informada."""

    mismatch = str(WalkoverScoreMismatch(3, 0).detail)
    assert "(3-0)" in mismatch
    assert "no coincide" in mismatch

    inconsistent = str(WalkoverConfigInconsistent(0, 3).detail)
    assert "(0-3)" in inconsistent
    assert "resolución administrativa" in inconsistent


def test_the_three_codes_are_distinct_and_do_not_collide_with_the_existing_ones():
    """RNF-003: tres códigos aditivos, distintos entre sí y de los previos."""

    codes = [code for _, code in WALKOVER_ERRORS]
    assert len(set(codes)) == 3
    assert all(code.startswith("WALKOVER_") for code in codes)
    assert set(codes).isdisjoint(
        {RESOLUTION_NOT_ENABLED, ASSIST_PLAYER_INVALID, DOUBLE_YELLOW_INCONSISTENT}
    )
    assert all(
        isinstance(cls().detail, str)
        for cls in (
            ResolutionNotEnabled,
            AssistPlayerInvalid,
            DoubleYellowInconsistent,
        )
    )


@pytest.mark.asyncio
async def test_a_plain_409_from_the_017_still_has_no_code():
    """La 017 conserva sus 409 de dominio sin ``code``."""

    handler = main_module.api.exception_handlers[HTTPException]

    response = await handler(
        close_request(), HTTPException(status_code=409, detail="Conflicto de dominio")
    )

    body = json.loads(response.body)
    assert response.status_code == 409
    assert set(body) == {"detail"}
    assert body["detail"] == "Conflicto de dominio"

