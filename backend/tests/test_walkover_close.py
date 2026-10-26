"""Walkover: marcador derivado y rama del cierre (spec 016, T5).

T5 implementa la **rama** del walkover dentro del orden único de 14 pasos de la
017 (D-1) y la derivación pura de su marcador:

* **RF-003 / RNF-008:** la rama se ejecuta después del paso 5 (resolución
  habilitada) y **omite** los pasos 6 (segmento activo y segmentos), 7
  (participantes y plantilla), 8 (estado en campo y sustituciones), 9
  (asistente), 10 (doble amarilla), 11 (marcador contra eventos) y 12
  (sanciones). No consulta plantilla, ni contadores, ni sanciones, y no toma
  bloqueos de jugador (D-6).
* **RF-004:** si hay un segmento activo se cierra en su **minuto de inicio**; los
  completados y los interrumpidos no cambian y `match_segment_team_state` no se
  reescribe.
* **RF-005:** el marcador se deriva de la configuración efectiva de la fase
  (`walkover_score` con su override) y se publica resuelto en `limits`; un
  marcador informado distinto es **409** `WALKOVER_SCORE_MISMATCH`.
* **RF-008:** el efecto es el vigente —partido `finished` y confirmado, puntos,
  goles y diferencia, avance de llave y los mismos tres eventos de outbox—; una
  pareja efectiva con `winner <= loser` es **409** `WALKOVER_CONFIG_INCONSISTENT`
  antes que el desajuste de marcador (D-4).
* **RF-009:** no se valida, no se sirve y no se crea ninguna suspensión.

Las pruebas **puras** (sin PostgreSQL) cubren la derivación, la forma del bloque
`limits` y la **precedencia de los códigos** con dobles de sesión. Las pruebas
con base son opt-in (`RUN_DATABASE_TESTS=1` y `DATABASE_ADMIN_URL`) y construyen
una base desechable por caso, porque el cierre es dueño de su transacción.
"""

from __future__ import annotations

import json
import secrets
from contextlib import asynccontextmanager
from copy import deepcopy
from dataclasses import dataclass, field
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.core.tenancy import AuthContext
from app.modules.matches import router as matches_router
from app.modules.matches.errors import (
    WALKOVER_CONFIG_INCONSISTENT,
    WALKOVER_SCORE_MISMATCH,
    WALKOVER_STATE_NOT_ALLOWED,
    WalkoverConfigInconsistent,
    WalkoverScoreMismatch,
    WalkoverStateNotAllowed,
)
from app.modules.matches.router import _build_operation_limits
from app.modules.matches.schemas import CloseMatchReportDTO
from app.modules.matches.service import (
    CloseMatchReportService,
    WalkoverScore,
    derive_walkover_score,
)
from app.modules.rules_engine.defaults import DEFAULT_RULES_CONFIG
from db_helpers import (
    TenantContext,
    create_tenant_owner,
    insert_player,
    set_tenant_context,
)
from migration_helpers import (
    apply_init,
    apply_migrations,
    connect,
    create_database,
    drop_database,
    ensure_application_role,
)

ORGANIZATION_ID = UUID(int=9601)
USER_ID = UUID(int=9602)
MEMBER_ID = UUID(int=9603)
TOURNAMENT_ID = UUID(int=9700)
VERSION_ID = UUID(int=9701)
STAGE_ID = UUID(int=9702)
MATCH_ID = UUID(int=9703)
SEGMENT_ID = UUID(int=9704)
HOME = UUID(int=9800)
AWAY = UUID(int=9801)
OTHER_TEAM = UUID(int=9802)

#: Las ocho claves que `limits` ya publicaba antes de la 016 (RNF-003 a).
EXISTING_LIMIT_KEYS = {
    "regular_time_minutes",
    "extra_time_minutes",
    "max_minute",
    "added_minute_max",
    "max_minute_regular",
    "max_minute_extra",
    "extra_time_enabled",
    "penalties_enabled",
}


def context() -> AuthContext:
    return AuthContext(
        user_id=USER_ID,
        organization_id=ORGANIZATION_ID,
        organization_user_id=MEMBER_ID,
    )


def config_with(
    *,
    pair: tuple[int, int] | None = None,
    overrides: dict[UUID, tuple[int, int]] | None = None,
) -> dict:
    """Configuración completa con una pareja de walkover por ámbito."""

    config = deepcopy(DEFAULT_RULES_CONFIG)
    if pair is not None:
        config["stage_defaults"]["walkover_score"] = {
            "winner": pair[0],
            "loser": pair[1],
        }
    if overrides:
        config["stage_overrides"] = {
            str(stage_id): {
                "walkover_score": {"winner": value[0], "loser": value[1]}
            }
            for stage_id, value in overrides.items()
        }
    return config


def walkover_report(
    *,
    winner: UUID = HOME,
    reason: str = "no_show",
    home_score_regular: int | None = None,
    away_score_regular: int | None = None,
    home_score: int | None = None,
    away_score: int | None = None,
) -> CloseMatchReportDTO:
    return CloseMatchReportDTO(
        resolution_type="walkover",
        winner_team_id=winner,
        reason=reason,
        home_score_regular=home_score_regular,
        away_score_regular=away_score_regular,
        home_score=home_score,
        away_score=away_score,
    )


def walkover_for(match: "WalkoverMatch", **overrides) -> CloseMatchReportDTO:
    """W.O. del escenario con el equipo local como ganador declarado."""

    return walkover_report(winner=match.home_team_id, **overrides)


# ---------------------------------------------------------------------------
# Puros: marcador derivado de la configuración efectiva (RF-005, RNF-006)
# ---------------------------------------------------------------------------


def test_derive_walkover_score_uses_the_read_default_pair():
    """Sin configuración, el default 3-0 del contrato de reglas (RNF-006)."""

    assert derive_walkover_score({}, None, HOME, AWAY, HOME) == WalkoverScore(
        home_score=3, away_score=0, winner_score=3, loser_score=0
    )
    assert derive_walkover_score(
        deepcopy(DEFAULT_RULES_CONFIG), STAGE_ID, HOME, AWAY, HOME
    ) == WalkoverScore(3, 0, 3, 0)


def test_derive_walkover_score_applies_the_stage_override():
    """Caso límite 8: manda la excepción de la fase, no el default."""

    config = config_with(overrides={STAGE_ID: (3, 1)})

    assert derive_walkover_score(config, STAGE_ID, HOME, AWAY, HOME) == WalkoverScore(
        3, 1, 3, 1
    )


def test_derive_walkover_score_keeps_the_pair_with_a_partial_override():
    """Un override que no declara la pareja no la pierde (clave por clave)."""

    config = config_with(pair=(5, 0))
    config["stage_overrides"] = {
        str(STAGE_ID): {"regular_time_minutes": 40}
    }

    assert derive_walkover_score(config, STAGE_ID, HOME, AWAY, HOME) == WalkoverScore(
        5, 0, 5, 0
    )


def test_derive_walkover_score_is_idempotent_with_a_merged_override():
    """`_lock_match` ya copia el override sobre `stage_defaults`: no cambia nada.

    Se documenta a propósito para que nadie «arregle» el cierre quitando una de
    las dos resoluciones: aplicar dos veces el mismo override es idempotente.
    """

    stage_override = {"walkover_score": {"winner": 3, "loser": 1}}
    config = config_with(pair=(3, 1), overrides={STAGE_ID: (3, 1)})
    merged = deepcopy(config)
    merged["stage_defaults"] = {**merged["stage_defaults"], **stage_override}

    assert derive_walkover_score(merged, STAGE_ID, HOME, AWAY, HOME) == (
        derive_walkover_score(config, STAGE_ID, HOME, AWAY, HOME)
    )


def test_derive_walkover_score_orients_the_pair_to_home_and_away():
    """El ganador recibe `winner`; el rival, `loser`, en su propio lado."""

    config = config_with(overrides={STAGE_ID: (3, 1)})

    assert derive_walkover_score(config, STAGE_ID, HOME, AWAY, HOME) == WalkoverScore(
        3, 1, 3, 1
    )
    assert derive_walkover_score(config, STAGE_ID, HOME, AWAY, AWAY) == WalkoverScore(
        1, 3, 3, 1
    )


def test_derive_walkover_score_returns_none_when_the_winner_does_not_play():
    assert derive_walkover_score({}, None, HOME, AWAY, OTHER_TEAM) is None


def test_the_coherence_flag_is_the_configured_pair():
    """D-3/D-5: la pareja es coherente solo con el ganador por delante."""

    assert WalkoverScore(3, 0, 3, 0).is_coherent is True
    assert WalkoverScore(1, 3, 3, 1).is_coherent is True
    assert WalkoverScore(0, 3, 0, 3).is_coherent is False
    assert WalkoverScore(0, 0, 0, 0).is_coherent is False


def test_operation_limits_publish_the_effective_pair_and_keep_the_eight_keys():
    """RF-005, RNF-003 a: una clave aditiva, las ocho existentes intactas."""

    config = config_with(overrides={STAGE_ID: (3, 1)})

    with_pair = _build_operation_limits(
        {"rules_config": config, "stage_id": STAGE_ID}
    )
    without_override = _build_operation_limits(
        {"rules_config": deepcopy(DEFAULT_RULES_CONFIG), "stage_id": None}
    )

    assert set(with_pair) == EXISTING_LIMIT_KEYS | {"walkover_score"}
    assert with_pair["walkover_score"] == {"winner": 3, "loser": 1}
    assert without_override["walkover_score"] == {"winner": 3, "loser": 0}
    assert {
        key: value for key, value in with_pair.items() if key != "walkover_score"
    } == {
        "regular_time_minutes": 90,
        "extra_time_minutes": 120,
        "max_minute": 90,
        "added_minute_max": 30,
        "max_minute_regular": 90,
        "max_minute_extra": None,
        "extra_time_enabled": False,
        "penalties_enabled": False,
    }


# ---------------------------------------------------------------------------
# Precedencia de los códigos, con dobles de sesión (sin base de datos)
# ---------------------------------------------------------------------------


class StopExecution(Exception):
    """Detiene el doble ante una consulta que el escenario no previó."""


class Result:
    def __init__(self, rows=None, scalar=None):
        self._rows = list(rows or [])
        self._scalar = scalar

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


class WalkoverSession:
    """Doble mínimo del cierre: solo lo que la rama del walkover puede leer.

    Cualquier otra consulta lanza :class:`StopExecution`, de modo que la prueba
    falla si la rama empieza a cargar plantilla, sanciones, contadores o
    bloqueos de jugador (D-6, RNF-008).
    """

    def __init__(
        self,
        *,
        status: str = "scheduled",
        config: dict | None = None,
        active_segment: bool = True,
        active_minute_start: int = 0,
        allowed: bool = True,
    ):
        self.status = status
        self.config = config if config is not None else deepcopy(DEFAULT_RULES_CONFIG)
        self.active_segment = active_segment
        self.active_minute_start = active_minute_start
        self.allowed = allowed
        self.statements: list[str] = []
        self.calls: list[tuple[str, dict]] = []

    def begin(self):
        return Transaction()

    @property
    def writes(self) -> list[str]:
        prefixes = ("INSERT", "UPDATE", "DELETE")
        return [sql for sql in self.statements if sql.upper().startswith(prefixes)]

    def parameters(self, fragment: str) -> list[dict]:
        return [params for sql, params in self.calls if fragment in sql]

    async def execute(self, statement, params=None):
        sql = " ".join(str(statement).split())
        self.statements.append(sql)
        self.calls.append((sql, dict(params or {})))
        return self.handle(sql, dict(params or {}))

    def handle(self, sql: str, params: dict) -> Result:
        if "set_config" in sql:
            return Result()
        if "SELECT id, tournament_id, tournament_version_id, stage_id, bracket_code" in sql:
            return Result(
                rows=[
                    {
                        "id": MATCH_ID,
                        "tournament_id": TOURNAMENT_ID,
                        "tournament_version_id": VERSION_ID,
                        "stage_id": STAGE_ID,
                        "bracket_code": None,
                    }
                ]
            )
        if "SELECT id, tournament_version_id" in sql and "FROM stages" in sql:
            return Result(rows=[{"id": STAGE_ID, "tournament_version_id": VERSION_ID}])
        if "SELECT status" in sql and "FROM tournament_versions" in sql:
            return Result(scalar="published")
        if "FROM advancement_links" in sql:
            return Result(rows=[])
        if "id = ANY(CAST(:match_ids AS uuid[]))" in sql:
            return Result(rows=[{"id": MATCH_ID}])
        if "FOR UPDATE OF m" in sql:
            return Result(
                rows=[
                    {
                        "id": MATCH_ID,
                        "tournament_id": TOURNAMENT_ID,
                        "tournament_version_id": VERSION_ID,
                        "matchday": 1,
                        "match_date": None,
                        "bracket_code": None,
                        "status": self.status,
                        "stage_id": STAGE_ID,
                        "home_team_id": HOME,
                        "away_team_id": AWAY,
                        "rules_config": self.config,
                        "version_status": "published",
                    }
                ]
            )
        if "FROM roles r" in sql:
            return Result(scalar=1 if self.allowed else None)
        if "FROM match_segments" in sql and "status = 'active'" in sql:
            if not self.active_segment:
                return Result(rows=[])
            return Result(
                rows=[{"id": SEGMENT_ID, "minute_start": self.active_minute_start}]
            )
        if sql.startswith(("INSERT", "UPDATE", "DELETE")):
            return Result()
        raise StopExecution(sql)


async def close_with_double(
    monkeypatch, session: WalkoverSession, report: CloseMatchReportDTO
) -> dict:
    """Cierra con el doble; clasificación y avance se neutralizan (no son la rama)."""

    async def noop(self, *args, **kwargs):
        return None

    monkeypatch.setattr(CloseMatchReportService, "_recalculate_standings", noop)
    monkeypatch.setattr(CloseMatchReportService, "_advance_bracket", noop)
    return await CloseMatchReportService(session).execute(context(), MATCH_ID, report)


@pytest.mark.asyncio
async def test_the_state_code_precedes_the_config_and_the_mismatch(monkeypatch):
    """Paso 3 antes que la guarda del 13′: gana el estado inadmisible."""

    session = WalkoverSession(status="finished", config=config_with(pair=(0, 3)))

    with pytest.raises(WalkoverStateNotAllowed) as error:
        await close_with_double(
            monkeypatch,
            session,
            walkover_report(home_score_regular=1, away_score_regular=0),
        )

    assert error.value.status_code == 409
    assert error.value.code == WALKOVER_STATE_NOT_ALLOWED
    assert session.writes == []


@pytest.mark.asyncio
async def test_the_config_code_precedes_the_score_mismatch(monkeypatch):
    """D-4: la pareja incoherente se informa antes que el marcador informado.

    La petición tiene **los dos** defectos —pareja efectiva 0-3 y marcador
    informado 1-0— y responde el de la guarda, que es el único que ofrece la
    salida documentada (la resolución administrativa).
    """

    session = WalkoverSession(config=config_with(pair=(0, 3)))

    with pytest.raises(WalkoverConfigInconsistent) as error:
        await close_with_double(
            monkeypatch,
            session,
            walkover_report(home_score_regular=1, away_score_regular=0),
        )

    assert error.value.status_code == 409
    assert error.value.code == WALKOVER_CONFIG_INCONSISTENT
    assert "0-3" in error.value.detail
    assert session.writes == []


@pytest.mark.asyncio
async def test_an_incoherent_informed_pair_is_the_score_mismatch(monkeypatch):
    """Con una pareja coherente, el desacuerdo es `WALKOVER_SCORE_MISMATCH`."""

    session = WalkoverSession(config=config_with(pair=(3, 0)))

    with pytest.raises(WalkoverScoreMismatch) as error:
        await close_with_double(
            monkeypatch,
            session,
            walkover_report(home_score_regular=1, away_score_regular=0),
        )

    assert error.value.status_code == 409
    assert error.value.code == WALKOVER_SCORE_MISMATCH
    assert "3-0" in error.value.detail
    assert session.writes == []


@pytest.mark.asyncio
async def test_a_walkover_needs_no_segment_and_no_roster(monkeypatch):
    """RF-003 y D-6: sin segmento activo cierra y no consulta lo prohibido.

    La lista incluye las consultas que la rama **no** debe emitir: plantilla y
    roster, sanciones y sus cumplimientos, la proyección por segmento, el
    historial disciplinario (que se lee de `match_events`) y el bloqueo asesor
    de la clasificación (neutralizada aquí, así que si apareciera vendría de la
    propia rama). `test_close_validation_order.py` fija lo mismo sustituyendo
    los ayudantes, no el texto del SQL (spec 016, T6).
    """

    session = WalkoverSession(active_segment=False, config=config_with(pair=(3, 1)))

    response = await close_with_double(monkeypatch, session, walkover_report())

    assert response["status"] == "success"
    assert (response["home_score"], response["away_score"]) == (3, 1)
    assert response["winner_team_id"] == str(HOME)

    joined = " ".join(session.statements)
    for forbidden in (
        "match_rosters",
        "FROM rosters",
        "player_suspensions",
        "player_suspension_serves",
        "match_segment_team_state",
        "FROM match_events",
        "pg_advisory_xact_lock",
        "INSERT INTO match_events",
        "INSERT INTO match_segments",
    ):
        assert forbidden not in joined, forbidden

    match_update = session.parameters("UPDATE matches")[0]
    assert (match_update["home_score_regular"], match_update["away_score_regular"]) == (3, 1)
    assert (match_update["home_score"], match_update["away_score"]) == (3, 1)
    assert match_update["winner_team_id"] == str(HOME)
    assert match_update["status"] == "finished"
    assert "resolution_type = 'walkover'" in " ".join(session.statements)
    assert match_update["resolution_reason"] == "no_show"
    # El walkover no tiene tanda de penales: la columna se limpia, no se envía.
    assert "home_penalties = NULL" in " ".join(session.statements)
    assert "away_penalties = NULL" in " ".join(session.statements)


@pytest.mark.asyncio
async def test_the_branch_closes_the_active_segment_on_its_own_start(monkeypatch):
    """RF-004: el activo se cierra en su minuto de inicio y no se proyecta nada."""

    session = WalkoverSession(active_segment=True, active_minute_start=45)

    await close_with_double(monkeypatch, session, walkover_report())

    segment_update = session.parameters("UPDATE match_segments")[0]
    assert segment_update["minute_end"] == 45
    assert "match_segment_team_state" not in " ".join(session.statements)


@pytest.mark.asyncio
async def test_the_branch_emits_the_audit_entry_and_the_three_outbox_events(monkeypatch):
    """RF-007, RNF-010 y RNF-011: misma auditoría y mismos eventos que un cierre."""

    session = WalkoverSession()

    await close_with_double(monkeypatch, session, walkover_report(reason="withdrawal"))

    audit = session.parameters("INSERT INTO administrative_audit_logs")[0]
    assert audit["action"] == "CLOSE_MATCH_REPORT"
    payload = audit["payload"]
    assert '"resolution_reason": "withdrawal"' in payload
    assert '"resolution_type": "walkover"' in payload
    outbox = [
        params["event_type"]
        for params in session.parameters("INSERT INTO outbox_events")
    ]
    assert outbox == ["MATCH_CLOSED", "MATCH_UPDATED", "STANDINGS_UPDATED"]


# ---------------------------------------------------------------------------
# Con base de datos (opt-in)
# ---------------------------------------------------------------------------


@asynccontextmanager
async def committed_application(database_admin_url):
    """Base desechable en la última migración y rol dedicado de la app."""

    await ensure_application_role(database_admin_url)
    database = await create_database(database_admin_url)
    admin = await connect(database_admin_url, database)
    role_name = f"bc016_{secrets.token_hex(8)}"
    role_password = secrets.token_hex(16)
    engine = None
    try:
        await apply_init(admin)
        await apply_migrations(admin, first=1)
        await admin.execute(
            f"""
            CREATE ROLE "{role_name}" LOGIN PASSWORD '{role_password}'
            NOSUPERUSER NOCREATEDB NOCREATEROLE INHERIT NOBYPASSRLS
            """
        )
        await admin.execute(f'GRANT bracket_app TO "{role_name}"')
        parsed = make_url(database_admin_url)
        app_url = (
            f"postgresql+asyncpg://{role_name}:{role_password}"
            f"@{parsed.host or '127.0.0.1'}:{parsed.port or 5432}/{database}"
        )
        engine = create_async_engine(app_url, pool_pre_ping=True)
        yield engine
    finally:
        if engine is not None:
            await engine.dispose()
        await admin.close()
        await drop_database(database_admin_url, database)
        cleaner = await connect(database_admin_url)
        try:
            await cleaner.execute(f'DROP ROLE IF EXISTS "{role_name}"')
        finally:
            await cleaner.close()


@dataclass(frozen=True)
class WalkoverMatch:
    tenant: TenantContext
    tournament_id: UUID
    version_id: UUID
    stage_id: UUID
    match_id: UUID
    home_team_id: UUID
    away_team_id: UUID
    target_match_id: UUID
    active_segment_id: UUID | None = None
    completed_segment_id: UUID | None = None
    suspended_player_id: UUID | None = None


@dataclass
class WalkoverSeed:
    """Opciones del escenario; todo lo que no se pide **no existe** en la base."""

    config: dict = field(default_factory=lambda: deepcopy(DEFAULT_RULES_CONFIG))
    status: str = "scheduled"
    stage_pair: tuple[int, int] | None = None
    with_active_segment: bool = False
    with_completed_segment: bool = False
    with_suspension: bool = False
    match_date: str | None = None


def _context_for(tenant: TenantContext) -> AuthContext:
    return AuthContext(
        user_id=tenant.user_id,
        organization_id=tenant.organization_id,
        organization_user_id=tenant.member_id,
    )


async def _create_tournament(session, tenant: TenantContext, *, config: dict) -> tuple[UUID, UUID, UUID]:
    payload = json.dumps(config)
    tournament_id = (
        await session.execute(
            text("""
                INSERT INTO tournaments
                    (organization_id, name, season, start_date, status, current_draft_config)
                VALUES
                    (:organization_id, :name, '2026', '2026-01-01', 'draft',
                     CAST(:config AS jsonb))
                RETURNING id
            """),
            {
                "organization_id": str(tenant.organization_id),
                "name": f"W016 {uuid4().hex[:8]}",
                "config": payload,
            },
        )
    ).scalar_one()
    version_id = (
        await session.execute(
            text("""
                INSERT INTO tournament_versions
                    (organization_id, tournament_id, version_number, rules_config,
                     phase_config, status, created_by_member_id)
                VALUES
                    (:organization_id, :tournament_id, 1, CAST(:config AS jsonb),
                     '{}'::jsonb, 'draft', :member_id)
                RETURNING id
            """),
            {
                "organization_id": str(tenant.organization_id),
                "tournament_id": str(tournament_id),
                "member_id": str(tenant.member_id),
                "config": payload,
            },
        )
    ).scalar_one()
    stage_id = (
        await session.execute(
            text("""
                INSERT INTO stages
                    (organization_id, tournament_id, tournament_version_id, name,
                     stage_type, stage_order)
                VALUES
                    (:organization_id, :tournament_id, :version_id, 'Group stage',
                     'round_robin', 1)
                RETURNING id
            """),
            {
                "organization_id": str(tenant.organization_id),
                "tournament_id": str(tournament_id),
                "version_id": str(version_id),
            },
        )
    ).scalar_one()
    return tournament_id, version_id, stage_id


async def _register_team(session, tenant: TenantContext, tournament_id: UUID, version_id: UUID, stage_id: UUID) -> UUID:
    team_id = (
        await session.execute(
            text("""
                INSERT INTO teams (organization_id, name, short_code)
                VALUES (:organization_id, :name, :short_code)
                RETURNING id
            """),
            {
                "organization_id": str(tenant.organization_id),
                "name": f"W016 {uuid4().hex[:8]}",
                "short_code": f"W{uuid4().hex[:5].upper()}",
            },
        )
    ).scalar_one()
    await session.execute(
        text("""
            INSERT INTO tournament_teams (organization_id, tournament_id, team_id, status)
            VALUES (:organization_id, :tournament_id, :team_id, 'registered')
        """),
        {
            "organization_id": str(tenant.organization_id),
            "tournament_id": str(tournament_id),
            "team_id": str(team_id),
        },
    )
    await session.execute(
        text("""
            INSERT INTO stage_teams
                (organization_id, tournament_id, tournament_version_id, stage_id, team_id)
            VALUES (:organization_id, :tournament_id, :version_id, :stage_id, :team_id)
        """),
        {
            "organization_id": str(tenant.organization_id),
            "tournament_id": str(tournament_id),
            "version_id": str(version_id),
            "stage_id": str(stage_id),
            "team_id": str(team_id),
        },
    )
    return team_id


async def _create_walkover_match(
    session,
    tenant: TenantContext,
    seed: WalkoverSeed,
) -> WalkoverMatch:
    """Partido publicado y, solo si el escenario lo pide, segmentos y sanción."""

    await set_tenant_context(session, tenant)
    tournament_id, version_id, stage_id = await _create_tournament(
        session, tenant, config=seed.config
    )
    if seed.stage_pair is not None:
        # El override por fase necesita el id real de la fase: se escribe sobre
        # la versión antes de publicarla (el escenario es de configuración, no
        # una escritura del cierre).
        config = deepcopy(seed.config)
        config.setdefault("stage_overrides", {})[str(stage_id)] = {
            "walkover_score": {
                "winner": seed.stage_pair[0],
                "loser": seed.stage_pair[1],
            }
        }
        await session.execute(
            text("""
                UPDATE tournament_versions
                SET rules_config = CAST(:config AS jsonb)
                WHERE id = :version_id
            """),
            {"config": json.dumps(config), "version_id": str(version_id)},
        )
    home_team_id = await _register_team(
        session, tenant, tournament_id, version_id, stage_id
    )
    away_team_id = await _register_team(
        session, tenant, tournament_id, version_id, stage_id
    )

    async def new_match(*, matchday: int, teams: bool, status: str) -> UUID:
        return (
            await session.execute(
                text("""
                    INSERT INTO matches
                        (organization_id, tournament_id, tournament_version_id, stage_id,
                         home_team_id, away_team_id, status, matchday, match_date)
                    VALUES
                        (:organization_id, :tournament_id, :version_id, :stage_id,
                         :home_team_id, :away_team_id, :status, :matchday,
                         CAST(:match_date AS TIMESTAMPTZ))
                    RETURNING id
                """),
                {
                    "organization_id": str(tenant.organization_id),
                    "tournament_id": str(tournament_id),
                    "version_id": str(version_id),
                    "stage_id": str(stage_id),
                    "home_team_id": str(home_team_id) if teams else None,
                    "away_team_id": str(away_team_id) if teams else None,
                    "status": status,
                    "matchday": matchday,
                    "match_date": seed.match_date,
                },
            )
        ).scalar_one()

    # Destino del avance: existe desde el principio y no tiene equipos.
    target_match_id = await new_match(matchday=2, teams=False, status="scheduled")
    # `chk_terminal_result` exige marcador y confirmación en el mismo INSERT, así
    # que un estado terminal se materializa con un UPDATE que ya trae todo.
    terminal = seed.status in {"finished", "administrative_resolution"}
    match_id = await new_match(
        matchday=1, teams=True, status="scheduled" if terminal else seed.status
    )
    if terminal:
        await session.execute(
            text("""
                UPDATE matches
                SET status = :status,
                    home_score_regular = 1, away_score_regular = 0,
                    home_score = 1, away_score = 0, winner_team_id = :winner_team_id,
                    resolution_type = 'regular', result_confirmed = TRUE
                WHERE id = :match_id
            """),
            {
                "match_id": str(match_id),
                "status": seed.status,
                "winner_team_id": str(home_team_id),
            },
        )
    await session.execute(
        text("""
            INSERT INTO advancement_links
                (organization_id, source_match_id, target_match_id, outcome, target_side)
            VALUES
                (:organization_id, :source_match_id, :target_match_id, 'winner', 'home')
        """),
        {
            "organization_id": str(tenant.organization_id),
            "source_match_id": str(match_id),
            "target_match_id": str(target_match_id),
        },
    )

    completed_segment_id: UUID | None = None
    active_segment_id: UUID | None = None
    if seed.with_completed_segment:
        completed_segment_id = (
            await session.execute(
                text("""
                    INSERT INTO match_segments
                        (organization_id, match_id, segment_number, minute_start,
                         minute_end, status)
                    VALUES (:organization_id, :match_id, 1, 0, 45, 'completed')
                    RETURNING id
                """),
                {
                    "organization_id": str(tenant.organization_id),
                    "match_id": str(match_id),
                },
            )
        ).scalar_one()
        await session.execute(
            text("""
                INSERT INTO match_segment_team_state
                    (organization_id, match_id, segment_id, team_id,
                     substitutions_remaining, substitution_windows_remaining)
                VALUES
                    (:organization_id, :match_id, :segment_id, :team_id, 2, 1)
            """),
            {
                "organization_id": str(tenant.organization_id),
                "match_id": str(match_id),
                "segment_id": str(completed_segment_id),
                "team_id": str(home_team_id),
            },
        )
    if seed.with_active_segment:
        active_segment_id = (
            await session.execute(
                text("""
                    INSERT INTO match_segments
                        (organization_id, match_id, segment_number, minute_start, status)
                    VALUES (:organization_id, :match_id, :segment_number, :minute_start, 'active')
                    RETURNING id
                """),
                {
                    "organization_id": str(tenant.organization_id),
                    "match_id": str(match_id),
                    "segment_number": 2 if seed.with_completed_segment else 1,
                    "minute_start": 45 if seed.with_completed_segment else 0,
                },
            )
        ).scalar_one()

    suspended_player_id: UUID | None = None
    if seed.with_suspension:
        suspended_player_id = await insert_player(
            session,
            tenant.organization_id,
            first_name="W016",
            last_name="Suspended",
            reference_year=2026,
        )
        await session.execute(
            text("""
                INSERT INTO rosters
                    (organization_id, tournament_id, team_id, player_id, dorsal_number,
                     photo_consent, valid_from, eligible_from)
                VALUES
                    (:organization_id, :tournament_id, :team_id, :player_id, 9,
                     FALSE, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            """),
            {
                "organization_id": str(tenant.organization_id),
                "tournament_id": str(tournament_id),
                "team_id": str(home_team_id),
                "player_id": str(suspended_player_id),
            },
        )
        await session.execute(
            text("""
                INSERT INTO player_suspensions
                    (organization_id, source_tournament_id, player_id, source_type,
                     dedupe_key, scope_type, matches_suspended, reason)
                VALUES
                    (:organization_id, :tournament_id, :player_id, 'administrative_resolution',
                     :dedupe_key, 'organization', 1, 'walkover_test')
            """),
            {
                "organization_id": str(tenant.organization_id),
                "tournament_id": str(tournament_id),
                "player_id": str(suspended_player_id),
                "dedupe_key": f"w016:{uuid4().hex}",
            },
        )

    await session.execute(
        text("""
            UPDATE tournament_versions
            SET status = 'published', published_at = CURRENT_TIMESTAMP
            WHERE id = :version_id
        """),
        {"version_id": str(version_id)},
    )
    await session.execute(
        text("""
            UPDATE tournaments
            SET status = 'published', published_version_id = :version_id
            WHERE id = :tournament_id
        """),
        {"tournament_id": str(tournament_id), "version_id": str(version_id)},
    )
    return WalkoverMatch(
        tenant=tenant,
        tournament_id=tournament_id,
        version_id=version_id,
        stage_id=stage_id,
        match_id=match_id,
        home_team_id=home_team_id,
        away_team_id=away_team_id,
        target_match_id=target_match_id,
        active_segment_id=active_segment_id,
        completed_segment_id=completed_segment_id,
        suspended_player_id=suspended_player_id,
    )


async def seed_match(engine, seed: WalkoverSeed | None = None) -> tuple[AuthContext, WalkoverMatch]:
    async with AsyncSession(engine, expire_on_commit=False) as session:
        tenant = await create_tenant_owner(session, full_name="W016 committed")
        match = await _create_walkover_match(session, tenant, seed or WalkoverSeed())
        await session.commit()
    return _context_for(tenant), match


async def close(engine, context_: AuthContext, match_id: UUID, report: CloseMatchReportDTO):
    """Cierra en su propia sesión, exactamente como una petición."""

    async with AsyncSession(engine, expire_on_commit=False) as session:
        return await CloseMatchReportService(session).execute(context_, match_id, report)


async def snapshot(engine, match: WalkoverMatch) -> dict[str, object]:
    """Estado completo del escenario, para comparar «cero escrituras»."""

    async with AsyncSession(engine, expire_on_commit=False) as session:
        await set_tenant_context(session, match.tenant)
        row = (
            await session.execute(
                text("""
                    SELECT status, resolution_type, resolution_reason, result_confirmed,
                           winner_team_id, home_score_regular, away_score_regular,
                           home_score, away_score, home_penalties, away_penalties
                    FROM matches
                    WHERE id = :match_id
                """),
                {"match_id": str(match.match_id)},
            )
        ).mappings().one()
        segments = [
            dict(item)
            for item in (
                await session.execute(
                    text("""
                        SELECT id, segment_number, minute_start, minute_end, status
                        FROM match_segments
                        WHERE match_id = :match_id
                        ORDER BY segment_number
                    """),
                    {"match_id": str(match.match_id)},
                )
            ).mappings().all()
        ]
        segment_state = [
            dict(item)
            for item in (
                await session.execute(
                    text("""
                        SELECT segment_id, team_id, substitutions_remaining,
                               substitution_windows_remaining
                        FROM match_segment_team_state
                        WHERE match_id = :match_id
                        ORDER BY segment_id, team_id
                    """),
                    {"match_id": str(match.match_id)},
                )
            ).mappings().all()
        ]
        events = (
            await session.execute(
                text("SELECT count(*) FROM match_events WHERE match_id = :match_id"),
                {"match_id": str(match.match_id)},
            )
        ).scalar_one()
        outbox = [
            item["event_type"]
            for item in (
                await session.execute(
                    text("""
                        SELECT event_type
                        FROM outbox_events
                        WHERE organization_id = :organization_id
                        ORDER BY event_type
                    """),
                    {"organization_id": str(match.tenant.organization_id)},
                )
            ).mappings().all()
        ]
        audits = (
            await session.execute(
                text("""
                    SELECT count(*)
                    FROM administrative_audit_logs
                    WHERE entity_id = :match_id
                """),
                {"match_id": str(match.match_id)},
            )
        ).scalar_one()
        standings = [
            dict(item)
            for item in (
                await session.execute(
                    text("""
                        SELECT team_id, played, won, drawn, lost, goals_for,
                               goals_against, goal_difference, points
                        FROM standings
                        WHERE stage_id = :stage_id
                        ORDER BY team_id
                    """),
                    {"stage_id": str(match.stage_id)},
                )
            ).mappings().all()
        ]
        serves = (
            await session.execute(
                text("""
                    SELECT count(*)
                    FROM player_suspension_serves
                    WHERE match_id = :match_id
                """),
                {"match_id": str(match.match_id)},
            )
        ).scalar_one()
        suspensions = [
            dict(item)
            for item in (
                await session.execute(
                    text("""
                        SELECT player_id, status
                        FROM player_suspensions
                        WHERE organization_id = :organization_id
                        ORDER BY player_id
                    """),
                    {"organization_id": str(match.tenant.organization_id)},
                )
            ).mappings().all()
        ]
        target = (
            await session.execute(
                text("SELECT home_team_id, away_team_id FROM matches WHERE id = :match_id"),
                {"match_id": str(match.target_match_id)},
            )
        ).mappings().one()
    return {
        **dict(row),
        "segments": segments,
        "segment_state": segment_state,
        "events": events,
        "outbox": outbox,
        "audits": audits,
        "standings": standings,
        "suspension_serves": serves,
        "suspensions": suspensions,
        "target": dict(target),
    }


async def assert_nothing_was_written(
    engine, match: WalkoverMatch, before: dict[str, object]
) -> None:
    assert await snapshot(engine, match) == before


def assert_code(error: pytest.ExceptionInfo, code: str) -> None:
    assert error.value.status_code == 409
    assert error.value.code == code
    assert isinstance(error.value.detail, str)


@pytest.mark.asyncio
async def test_a_walkover_without_segments_or_roster_closes_the_match(database_admin_url):
    """Casos 1 y 2: sin segmentos y con los dos equipos sin plantilla."""

    async with committed_application(database_admin_url) as engine:
        context_, match = await seed_match(engine)

        response = await close(engine, context_, match.match_id, walkover_for(match))

        assert response == {
            "status": "success",
            "match_id": str(match.match_id),
            "home_score": 3,
            "away_score": 0,
            "winner_team_id": str(match.home_team_id),
        }
        state = await snapshot(engine, match)
        assert state["status"] == "finished"
        assert state["result_confirmed"] is True
        assert state["resolution_type"] == "walkover"
        assert state["resolution_reason"] == "no_show"
        assert state["winner_team_id"] == match.home_team_id
        assert (
            state["home_score_regular"],
            state["away_score_regular"],
            state["home_score"],
            state["away_score"],
        ) == (3, 0, 3, 0)
        assert (state["home_penalties"], state["away_penalties"]) == (None, None)
        # Sin segmentos no se crea ninguno (RF-004).
        assert state["segments"] == []
        assert state["events"] == 0
        # DU-6: cuenta como jugado, con sus puntos y sus goles en la diferencia.
        standings = {row["team_id"]: row for row in state["standings"]}
        home = standings[match.home_team_id]
        away = standings[match.away_team_id]
        assert (home["played"], home["won"], home["lost"], home["points"]) == (1, 1, 0, 3)
        assert (home["goals_for"], home["goals_against"], home["goal_difference"]) == (3, 0, 3)
        assert (away["played"], away["won"], away["lost"], away["points"]) == (1, 0, 1, 0)
        assert (away["goals_for"], away["goals_against"], away["goal_difference"]) == (0, 3, -3)
        # RF-008: el ganador avanza de llave.
        assert state["target"]["home_team_id"] == match.home_team_id
        # RNF-011: los mismos tres eventos de outbox que un cierre normal.
        assert state["outbox"] == ["MATCH_CLOSED", "MATCH_UPDATED", "STANDINGS_UPDATED"]
        # RNF-010: la acción de cierre, con el motivo en su contenido.
        assert state["audits"] == 1
        async with AsyncSession(engine, expire_on_commit=False) as session:
            await set_tenant_context(session, match.tenant)
            payload = (
                await session.execute(
                    text("""
                        SELECT action, payload
                        FROM administrative_audit_logs
                        WHERE entity_id = :match_id
                    """),
                    {"match_id": str(match.match_id)},
                )
            ).mappings().one()
        assert payload["action"] == "CLOSE_MATCH_REPORT"
        assert payload["payload"]["resolution_reason"] == "no_show"
        assert payload["payload"]["resolution_type"] == "walkover"


@pytest.mark.asyncio
async def test_a_walkover_with_an_active_segment_closes_it_at_its_start(database_admin_url):
    """Casos 3 y 4: el activo se cierra en su inicio y la proyección no cambia."""

    async with committed_application(database_admin_url) as engine:
        context_, match = await seed_match(
            engine, WalkoverSeed(with_completed_segment=True, with_active_segment=True)
        )
        before = await snapshot(engine, match)

        await close(engine, context_, match.match_id, walkover_for(match))

        state = await snapshot(engine, match)
        segments = {row["segment_number"]: row for row in state["segments"]}
        completed = segments[1]
        assert completed["id"] == match.completed_segment_id
        assert (completed["status"], completed["minute_start"], completed["minute_end"]) == (
            "completed",
            0,
            45,
        )
        closed = segments[2]
        assert closed["id"] == match.active_segment_id
        assert closed["status"] == "completed"
        assert closed["minute_start"] == 45
        assert closed["minute_end"] == 45
        # La proyección por equipo no se reescribe ni se crea para el nuevo cierre.
        assert state["segment_state"] == before["segment_state"]
        assert state["segment_state"] == [
            {
                "segment_id": match.completed_segment_id,
                "team_id": match.home_team_id,
                "substitutions_remaining": 2,
                "substitution_windows_remaining": 1,
            }
        ]


@pytest.mark.asyncio
async def test_the_effective_override_pair_is_applied_and_accepted_when_informed(database_admin_url):
    """Casos 8 y 19: la fase manda (3-1) y un marcador informado igual se acepta."""

    async with committed_application(database_admin_url) as engine:
        context_, match = await seed_match(engine, WalkoverSeed(stage_pair=(3, 1)))

        await close(
            engine,
            context_,
            match.match_id,
            walkover_for(
                match,
                home_score_regular=3,
                away_score_regular=1,
                home_score=3,
                away_score=1,
            ),
        )

        state = await snapshot(engine, match)
        assert (state["home_score_regular"], state["away_score_regular"]) == (3, 1)
        assert (state["home_score"], state["away_score"]) == (3, 1)
        assert state["status"] == "finished"
        standings = {row["team_id"]: row for row in state["standings"]}
        assert standings[match.home_team_id]["goals_for"] == 3
        assert standings[match.away_team_id]["goals_for"] == 1


@pytest.mark.asyncio
async def test_an_incoherent_informed_pair_is_rejected_without_writing(database_admin_url):
    """Caso 7: `WALKOVER_SCORE_MISMATCH` y cero escrituras."""

    async with committed_application(database_admin_url) as engine:
        context_, match = await seed_match(engine)
        before = await snapshot(engine, match)

        with pytest.raises(HTTPException) as error:
            await close(
                engine,
                context_,
                match.match_id,
                walkover_for(match, home_score_regular=1, away_score_regular=0),
            )

        assert_code(error, WALKOVER_SCORE_MISMATCH)
        await assert_nothing_was_written(engine, match, before)


@pytest.mark.asyncio
async def test_a_historical_incoherent_pair_is_rejected_with_its_own_code(database_admin_url):
    """Caso 18 y D-5: pareja 0-3 publicada antes de D-3 → `CONFIG_INCONSISTENT`.

    La petición informa además un marcador distinto, para comprobar que la
    guarda de la pareja gana al desajuste (D-4).
    """

    async with committed_application(database_admin_url) as engine:
        context_, match = await seed_match(engine, WalkoverSeed(config=config_with(pair=(0, 3))))
        before = await snapshot(engine, match)

        with pytest.raises(HTTPException) as error:
            await close(
                engine,
                context_,
                match.match_id,
                walkover_for(match, home_score_regular=1, away_score_regular=0),
            )

        assert_code(error, WALKOVER_CONFIG_INCONSISTENT)
        assert "0-3" in error.value.detail
        await assert_nothing_was_written(engine, match, before)


@pytest.mark.asyncio
async def test_a_terminal_or_suspended_match_rejects_the_walkover(database_admin_url):
    """RF-001 y RF-010: los cuatro estados inadmisibles, sin escribir."""

    async with committed_application(database_admin_url) as engine:
        for status in ("finished", "cancelled", "administrative_resolution", "suspended"):
            context_, match = await seed_match(engine, WalkoverSeed(status=status))
            before = await snapshot(engine, match)

            with pytest.raises(HTTPException) as error:
                await close(engine, context_, match.match_id, walkover_for(match))

            assert_code(error, WALKOVER_STATE_NOT_ALLOWED)
            assert status in error.value.detail
            await assert_nothing_was_written(engine, match, before)


@pytest.mark.asyncio
async def test_the_second_walkover_on_the_confirmed_act_is_rejected(database_admin_url):
    """RF-010: un acta confirmada no admite un segundo W.O. ni lo cambia."""

    async with committed_application(database_admin_url) as engine:
        context_, match = await seed_match(engine)
        await close(engine, context_, match.match_id, walkover_for(match))
        after_first = await snapshot(engine, match)

        with pytest.raises(HTTPException) as error:
            await close(
                engine,
                context_,
                match.match_id,
                walkover_report(reason="withdrawal", winner=match.away_team_id),
            )

        assert_code(error, WALKOVER_STATE_NOT_ALLOWED)
        await assert_nothing_was_written(engine, match, after_first)


@pytest.mark.asyncio
async def test_a_walkover_does_not_serve_nor_create_suspensions(database_admin_url):
    """RF-009: un partido no disputado no cumple sanción ni crea ninguna."""

    async with committed_application(database_admin_url) as engine:
        context_, match = await seed_match(engine, WalkoverSeed(with_suspension=True))

        await close(engine, context_, match.match_id, walkover_for(match))

        state = await snapshot(engine, match)
        assert state["status"] == "finished"
        assert state["suspension_serves"] == 0
        assert state["suspensions"] == [
            {"player_id": match.suspended_player_id, "status": "active"}
        ]


@pytest.mark.asyncio
async def test_the_operation_publishes_the_effective_walkover_pair(database_admin_url):
    """RF-005 y RNF-003 a: `limits.walkover_score` sin tocar las ocho claves."""

    async with committed_application(database_admin_url) as engine:
        context_, match = await seed_match(engine, WalkoverSeed(stage_pair=(3, 1)))

        async with AsyncSession(engine, expire_on_commit=False) as session:
            response = await matches_router.get_match_operation(
                match.match_id, context_, session
            )

        limits = response["limits"]
        assert set(limits) == EXISTING_LIMIT_KEYS | {"walkover_score"}
        assert limits["walkover_score"] == {"winner": 3, "loser": 1}
        assert limits["regular_time_minutes"] == 90
        assert limits["max_minute"] == 90
        assert limits["extra_time_enabled"] is False
        assert limits["penalties_enabled"] is False
