"""Sanciones (spec 018, T4): el cierre real, con base de datos.

Opt-in: ``RUN_DATABASE_TESTS=1`` (y ``DATABASE_URL`` con el rol de aplicación,
que inyecta Compose). Sin la variable, todos los casos se omiten y la suite
sin base sigue midiendo el motor puro en ``test_sanctions.py``.

**Qué fija esta tarea** (RF-001, RF-002, RF-003, RF-005, RF-006, RF-008,
RF-009, RF-010, RF-011, RF-012, RF-013, RF-014):

* una expulsión por doble amarilla es **una** sanción aunque una de sus
  amarillas cruce el umbral de acumulación, y su duración es la de expulsión
  (``direct_red_suspension_matches``), aplicada una sola vez;
* la roja **recién registrada** lleva su motivo correcto en ese mismo cierre
  (``metadata`` del ``RETURNING``, RF-010);
* el historial **solo cuenta**: no origina sanciones, no duplica una roja
  histórica mal etiquetada y no reescribe la fila existente (RF-005, RF-006);
* un evento de roja tiene **como máximo una** sanción, con cualquier motivo,
  comprobado aparte de la identidad torneo+jugador+evento+motivo;
* la auditoría del cierre cuenta las sanciones **realmente creadas**;
* el reinicio por cambio de fase decide qué amarillas cuentan, y la
  organización del contexto aísla el historial (RF-008, RF-014);
* la coherencia de la doble amarilla de la 017 sigue rechazando tres amarillas
  previas con su 409 y sin escribir (RF-013).

El escenario de dos actas se siembra con ``create_sibling_match``, que inserta
un segundo partido del **mismo torneo y versión** mientras la versión sigue en
borrador (el trigger de estructura prohíbe añadir partidos a una versión ya
publicada) y reutiliza los ``rosters`` del primero. El historial se escribe con
``INSERT INTO match_events`` directo, como en ``test_double_yellow.py``. El
esquema se queda en **027**: no hay migración.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text

from app.modules.matches.errors import DoubleYellowInconsistent
from app.modules.matches.router import close_match
from app.modules.matches.service import CloseMatchReportService
from app.modules.rules_engine.defaults import DEFAULT_RULES_CONFIG
from db_helpers import TenantContext, create_tenant_owner, set_tenant_context
from tests.event_ids import event_id
from tests.test_double_yellow import (
    act_state,
    assert_inconsistent,
    assert_nothing_was_written,
    close_in_session,
    red_payload,
    yellow_payload,
)
from tests.test_substitutions import (
    ClosableMatch,
    _add_lineup_player,
    _create_tournament,
    _register_team,
    committed_application,
    context_for,
    report,
    rules_config,
    seeded_match,
)

SIBLING_DATE = datetime(2026, 4, 1, 12, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Configuración de disciplina y lecturas del cierre
# ---------------------------------------------------------------------------


def discipline_config(
    *,
    limit: int = 3,
    yellow_matches: int = 1,
    red_matches: int = 1,
    clear_yellows_on_stage_change: bool = True,
) -> dict:
    """Configuración de la versión con las cinco claves de disciplina existentes."""

    config = rules_config()
    config["discipline"] = {
        **DEFAULT_RULES_CONFIG["discipline"],
        "yellow_card_limit": limit,
        "yellow_card_suspension_matches": yellow_matches,
        "direct_red_suspension_matches": red_matches,
        "clear_yellows_on_stage_change": clear_yellows_on_stage_change,
    }
    return config


def match_mapping(match: ClosableMatch, config: dict) -> dict:
    """La forma que consume ``_load_discipline_history`` (no es un ``dict``)."""

    return {
        "id": match.match_id,
        "tournament_id": match.tournament_id,
        "tournament_version_id": match.version_id,
        "stage_id": match.stage_id,
        "rules_config": config,
    }


async def suspension_rows(
    session, tenant: TenantContext, player_id: UUID
) -> list[dict]:
    """Sanciones del jugador, en orden estable (``created_at``, ``id``)."""

    await set_tenant_context(session, tenant)
    rows = (
        await session.execute(
            text("""
                SELECT id, origin_match_id, source_event_id, reason,
                       matches_suspended, status
                FROM player_suspensions
                WHERE organization_id = :organization_id
                  AND player_id = :player_id
                ORDER BY created_at, id
            """),
            {
                "organization_id": str(tenant.organization_id),
                "player_id": str(player_id),
            },
        )
    ).mappings().all()
    return [dict(row) for row in rows]


async def suspension_count(session, tenant: TenantContext, match_id: UUID) -> int:
    """Sanciones cuyo partido de origen es ``match_id``."""

    await set_tenant_context(session, tenant)
    return (
        await session.execute(
            text("""
                SELECT count(*)
                FROM player_suspensions
                WHERE organization_id = :organization_id
                  AND origin_match_id = :match_id
            """),
            {
                "organization_id": str(tenant.organization_id),
                "match_id": str(match_id),
            },
        )
    ).scalar_one()


async def serves_count(session, tenant: TenantContext, suspension_id: UUID) -> int:
    await set_tenant_context(session, tenant)
    return (
        await session.execute(
            text("""
                SELECT count(*)
                FROM player_suspension_serves
                WHERE organization_id = :organization_id
                  AND suspension_id = :suspension_id
                  AND is_voided = FALSE
            """),
            {
                "organization_id": str(tenant.organization_id),
                "suspension_id": str(suspension_id),
            },
        )
    ).scalar_one()


async def audit_suspensions(session, tenant: TenantContext, match_id: UUID) -> str | None:
    """``payload->>'suspensions'`` de la auditoría del cierre (``None`` si no hay)."""

    await set_tenant_context(session, tenant)
    return (
        await session.execute(
            text("""
                SELECT payload ->> 'suspensions'
                FROM administrative_audit_logs
                WHERE organization_id = :organization_id
                  AND entity_type = 'matches'
                  AND entity_id = :match_id
                  AND action = 'CLOSE_MATCH_REPORT'
            """),
            {
                "organization_id": str(tenant.organization_id),
                "match_id": str(match_id),
            },
        )
    ).scalar_one_or_none()


# ---------------------------------------------------------------------------
# Sembrado: torneo en borrador, partido vecino, tarjetas y sanciones
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SiblingMatch:
    match_id: UUID
    segment_id: UUID
    stage_id: UUID


async def create_draft_match(
    session,
    tenant: TenantContext,
    *,
    config: dict,
    second_stage: bool = False,
) -> tuple[ClosableMatch, UUID | None]:
    """Un torneo con la versión **en borrador** y su primer partido.

    La versión no se publica aquí: los partidos vecinos se insertan con
    :func:`create_sibling_match` (el trigger de estructura impide añadirlos
    después) y la publicación la hace :func:`publish_tournament`. Con
    ``second_stage`` se crea además una segunda fase para el caso del reinicio.
    """

    await set_tenant_context(session, tenant)
    tournament_id, version_id, stage_one = await _create_tournament(
        session, tenant, config=config
    )
    stage_two: UUID | None = None
    if second_stage:
        stage_two = (
            await session.execute(
                text("""
                    INSERT INTO stages
                        (organization_id, tournament_id, tournament_version_id,
                         name, stage_type, stage_order)
                    VALUES (:organization_id, :tournament_id, :version_id,
                            'Second stage', 'round_robin', 2)
                    RETURNING id
                """),
                {
                    "organization_id": str(tenant.organization_id),
                    "tournament_id": str(tournament_id),
                    "version_id": str(version_id),
                },
            )
        ).scalar_one()
    home_team_id = await _register_team(
        session, tenant, tournament_id, version_id, stage_one, label="home"
    )
    away_team_id = await _register_team(
        session, tenant, tournament_id, version_id, stage_one, label="away"
    )
    if stage_two is not None:
        for team_id in (home_team_id, away_team_id):
            await session.execute(
                text("""
                    INSERT INTO stage_teams
                        (organization_id, tournament_id, tournament_version_id,
                         stage_id, team_id)
                    VALUES (:organization_id, :tournament_id, :version_id,
                            :stage_id, :team_id)
                """),
                {
                    "organization_id": str(tenant.organization_id),
                    "tournament_id": str(tournament_id),
                    "version_id": str(version_id),
                    "stage_id": str(stage_two),
                    "team_id": str(team_id),
                },
            )
    match_id = (
        await session.execute(
            text("""
                INSERT INTO matches
                    (organization_id, tournament_id, tournament_version_id, stage_id,
                     home_team_id, away_team_id, status, matchday)
                VALUES
                    (:organization_id, :tournament_id, :version_id, :stage_id,
                     :home_team_id, :away_team_id, 'scheduled', NULL)
                RETURNING id
            """),
            {
                "organization_id": str(tenant.organization_id),
                "tournament_id": str(tournament_id),
                "version_id": str(version_id),
                "stage_id": str(stage_one),
                "home_team_id": str(home_team_id),
                "away_team_id": str(away_team_id),
            },
        )
    ).scalar_one()
    segment_1 = (
        await session.execute(
            text("""
                INSERT INTO match_segments
                    (organization_id, match_id, segment_number, minute_start,
                     minute_end, status)
                VALUES (:organization_id, :match_id, 1, 0, 45, 'completed')
                RETURNING id
            """),
            {"organization_id": str(tenant.organization_id), "match_id": str(match_id)},
        )
    ).scalar_one()
    segment_2 = (
        await session.execute(
            text("""
                INSERT INTO match_segments
                    (organization_id, match_id, segment_number, minute_start, status)
                VALUES (:organization_id, :match_id, 2, 45, 'active')
                RETURNING id
            """),
            {"organization_id": str(tenant.organization_id), "match_id": str(match_id)},
        )
    ).scalar_one()

    home_starters: list[UUID] = []
    home_substitutes: list[UUID] = []
    for index in range(1, 12):
        home_starters.append(
            await _add_lineup_player(
                session,
                tenant,
                tournament_id=tournament_id,
                match_id=match_id,
                team_id=home_team_id,
                role="starter",
                dorsal_number=index,
            )
        )
    for index in range(12, 15):
        home_substitutes.append(
            await _add_lineup_player(
                session,
                tenant,
                tournament_id=tournament_id,
                match_id=match_id,
                team_id=home_team_id,
                role="substitute",
                dorsal_number=index,
            )
        )
    for index in range(1, 12):
        await _add_lineup_player(
            session,
            tenant,
            tournament_id=tournament_id,
            match_id=match_id,
            team_id=away_team_id,
            role="starter",
            dorsal_number=index,
        )
    for index in range(12, 15):
        await _add_lineup_player(
            session,
            tenant,
            tournament_id=tournament_id,
            match_id=match_id,
            team_id=away_team_id,
            role="substitute",
            dorsal_number=index,
        )

    return (
        ClosableMatch(
            tenant=tenant,
            tournament_id=tournament_id,
            version_id=version_id,
            stage_id=stage_one,
            match_id=match_id,
            segment_1=segment_1,
            segment_2=segment_2,
            home_team_id=home_team_id,
            away_team_id=away_team_id,
            home_starters=tuple(home_starters),
            home_substitutes=tuple(home_substitutes),
        ),
        stage_two,
    )


async def create_sibling_match(
    session,
    first: ClosableMatch,
    *,
    stage_id: UUID | None = None,
    match_date: datetime | None = None,
    exclude_player: UUID | None = None,
) -> SiblingMatch:
    """Un segundo partido del **mismo torneo y versión** que el primero.

    Se inserta con la versión todavía en borrador (el trigger de estructura
    prohíbe añadir partidos a una versión publicada). Comparte los equipos y
    reutiliza las filas de ``match_rosters`` del primero (mismo ``roster_id``):
    el jugador sigue convocado salvo que se excluya con ``exclude_player``, que
    es lo que necesita el caso de los partidos cumplidos. La fase es la del
    primero por defecto y otra cuando el caso del reinicio lo pide. Sin
    ``matchday`` a propósito: el índice único de planilla por jornada no
    colisiona con el primer partido. El historial de este partido se siembra
    después con :func:`seed_card`.
    """

    tenant = first.tenant
    await set_tenant_context(session, tenant)
    target_stage = stage_id or first.stage_id
    match_id = (
        await session.execute(
            text("""
                INSERT INTO matches
                    (organization_id, tournament_id, tournament_version_id, stage_id,
                     home_team_id, away_team_id, status, matchday, match_date)
                VALUES
                    (:organization_id, :tournament_id, :version_id, :stage_id,
                     :home_team_id, :away_team_id, 'scheduled', NULL, :match_date)
                RETURNING id
            """),
            {
                "organization_id": str(tenant.organization_id),
                "tournament_id": str(first.tournament_id),
                "version_id": str(first.version_id),
                "stage_id": str(target_stage),
                "home_team_id": str(first.home_team_id),
                "away_team_id": str(first.away_team_id),
                "match_date": match_date,
            },
        )
    ).scalar_one()
    segment_id = (
        await session.execute(
            text("""
                INSERT INTO match_segments
                    (organization_id, match_id, segment_number, minute_start,
                     minute_end, status)
                VALUES (:organization_id, :match_id, 1, 0, 90, 'active')
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
            INSERT INTO match_rosters
                (organization_id, match_id, roster_id, player_id, team_id, role, is_valid)
            SELECT organization_id, :match_id, roster_id, player_id, team_id, role, is_valid
            FROM match_rosters
            WHERE organization_id = :organization_id
              AND match_id = :first_match_id
              AND (CAST(:exclude_player AS uuid) IS NULL
                   OR player_id <> CAST(:exclude_player AS uuid))
        """),
        {
            "organization_id": str(tenant.organization_id),
            "match_id": str(match_id),
            "first_match_id": str(first.match_id),
            "exclude_player": str(exclude_player) if exclude_player else None,
        },
    )
    return SiblingMatch(match_id=match_id, segment_id=segment_id, stage_id=target_stage)


async def publish_tournament(session, first: ClosableMatch) -> None:
    """Publica la versión y el torneo del sembrado, después de crear los partidos."""

    await session.execute(
        text("""
            UPDATE tournament_versions
            SET status = 'published', published_at = CURRENT_TIMESTAMP
            WHERE id = :version_id
        """),
        {"version_id": str(first.version_id)},
    )
    await session.execute(
        text("""
            UPDATE tournaments
            SET status = 'published', published_version_id = :version_id
            WHERE id = :tournament_id
        """),
        {"tournament_id": str(first.tournament_id), "version_id": str(first.version_id)},
    )


async def seed_card(
    session,
    first: ClosableMatch,
    *,
    player_id: UUID,
    event_type: str,
    minute: int,
    label: str,
    sibling: SiblingMatch | None = None,
    red_card_type: str | None = None,
    segment_id: UUID | None = None,
) -> UUID:
    """Escribe la tarjeta directamente en ``match_events`` (historial o acta).

    El trigger de contexto exige que el jugador esté en la planilla del partido;
    ``create_sibling_match`` la ha copiado y el primer partido ya la tiene.
    """

    tenant = first.tenant
    await set_tenant_context(session, tenant)
    match_id = sibling.match_id if sibling else first.match_id
    segment = segment_id or (sibling.segment_id if sibling else first.segment_1)
    metadata = {"red_card_type": red_card_type} if red_card_type else {}
    return (
        await session.execute(
            text("""
                INSERT INTO match_events
                    (organization_id, match_id, segment_id, team_id, player_id,
                     event_type, minute, added_minute, client_event_id, metadata)
                VALUES
                    (:organization_id, :match_id, :segment_id, :team_id, :player_id,
                     :event_type, :minute, 0, :client_event_id, CAST(:metadata AS jsonb))
                RETURNING id
            """),
            {
                "organization_id": str(tenant.organization_id),
                "match_id": str(match_id),
                "segment_id": str(segment),
                "team_id": str(first.home_team_id),
                "player_id": str(player_id),
                "event_type": event_type,
                "minute": minute,
                "client_event_id": event_id(label),
                "metadata": json.dumps(metadata),
            },
        )
    ).scalar_one()


async def seed_suspension(
    session,
    first: ClosableMatch,
    *,
    player_id: UUID,
    origin_match_id: UUID,
    source_event_id: UUID,
    reason: str,
    matches_suspended: int,
    status: str = "served",
) -> UUID:
    """Una sanción ya registrada (``served`` por defecto para no bloquear el paso 12)."""

    tenant = first.tenant
    await set_tenant_context(session, tenant)
    return (
        await session.execute(
            text("""
                INSERT INTO player_suspensions
                    (organization_id, source_tournament_id, player_id,
                     origin_match_id, source_event_id, source_type, dedupe_key,
                     scope_type, matches_suspended, reason, status)
                VALUES
                    (:organization_id, :tournament_id, :player_id,
                     :origin_match_id, :source_event_id, 'match_event', :dedupe_key,
                     'organization', :matches_suspended, :reason, :status)
                RETURNING id
            """),
            {
                "organization_id": str(tenant.organization_id),
                "tournament_id": str(first.tournament_id),
                "player_id": str(player_id),
                "origin_match_id": str(origin_match_id),
                "source_event_id": str(source_event_id),
                "dedupe_key": f"018-t4:{uuid4().hex}",
                "matches_suspended": matches_suspended,
                "reason": reason,
                "status": status,
            },
        )
    ).scalar_one()


# ---------------------------------------------------------------------------
# Escenarios compartidos por los casos de absorción, duración y auditoría
# ---------------------------------------------------------------------------


async def close_absorbed_double_yellow(
    session, tenant: TenantContext, *, config: dict
) -> ClosableMatch:
    """Una amarilla histórica + dos amarillas y una roja por doble amarilla.

    Con ``limit`` 3 la segunda amarilla del acta cruza el umbral: la lista
    derivada tiene dos sanciones (acumulación + expulsión) y la absorción deja
    **una**, la de la expulsión.
    """

    match, _ = await create_draft_match(session, tenant, config=config)
    sibling = await create_sibling_match(session, match, match_date=SIBLING_DATE)
    await publish_tournament(session, match)
    await session.commit()
    player = match.home_starters[0]
    await seed_card(
        session,
        match,
        player_id=player,
        event_type="yellow_card",
        minute=10,
        label="018-absorbed-history-yellow",
        sibling=sibling,
    )
    await session.commit()

    dto = report(
        [
            yellow_payload(
                player,
                team_id=match.home_team_id,
                segment_id=match.segment_1,
                minute=20,
                label="018-absorbed-yellow-1",
            ),
            yellow_payload(
                player,
                team_id=match.home_team_id,
                segment_id=match.segment_1,
                minute=30,
                label="018-absorbed-yellow-2",
            ),
            red_payload(
                player,
                team_id=match.home_team_id,
                segment_id=match.segment_1,
                minute=40,
                label="018-absorbed-red",
            ),
        ]
    )
    await close_match(match.match_id, dto, context_for(tenant), session)
    return match


async def close_reused_red_with_threshold(
    session, tenant: TenantContext, *, config: dict
) -> tuple[ClosableMatch, UUID]:
    """Un evento de roja **preexistente** con sanción y un umbral en el acta.

    El acta reutiliza la roja (mismo ``client_event_id`` y mismos campos) y sus
    dos amarillas cruzan el umbral con ``limit`` 2. La acumulación se absorbe y
    la sanción de la roja ya está registrada con **otro** motivo, así que su
    clave de deduplicación no colisiona: sin la unicidad por evento de roja se
    crearía una segunda fila con el motivo corregido.
    """

    match, _ = await create_draft_match(session, tenant, config=config)
    await publish_tournament(session, match)
    await session.commit()
    player = match.home_starters[0]
    red_event_id = await seed_card(
        session,
        match,
        player_id=player,
        event_type="red_card",
        minute=40,
        label="018-reused-red",
        red_card_type="double_yellow_red",
    )
    seeded = await seed_suspension(
        session,
        match,
        player_id=player,
        origin_match_id=match.match_id,
        source_event_id=red_event_id,
        reason="direct_red_card",
        matches_suspended=2,
    )
    await session.commit()

    dto = report(
        [
            yellow_payload(
                player,
                team_id=match.home_team_id,
                segment_id=match.segment_1,
                minute=20,
                label="018-reused-yellow-1",
            ),
            yellow_payload(
                player,
                team_id=match.home_team_id,
                segment_id=match.segment_1,
                minute=30,
                label="018-reused-yellow-2",
            ),
            red_payload(
                player,
                team_id=match.home_team_id,
                segment_id=match.segment_1,
                minute=40,
                label="018-reused-red",
            ),
        ]
    )
    await close_match(match.match_id, dto, context_for(tenant), session)
    return match, seeded


# ---------------------------------------------------------------------------
# Casos con base
# ---------------------------------------------------------------------------


async def test_a_double_yellow_with_a_historical_yellow_writes_one_suspension(
    db_session, tenant_factory
):
    """RF-001, RF-002, RF-003, RF-010: una jugada, una sanción."""

    tenant = await tenant_factory("018 T4 una sanción")
    config = discipline_config(limit=3, yellow_matches=1, red_matches=2)
    match = await close_absorbed_double_yellow(db_session, tenant, config=config)
    player = match.home_starters[0]

    rows = await suspension_rows(db_session, tenant, player)

    assert len(rows) == 1, rows
    assert rows[0]["reason"] == "double_yellow_red"
    assert rows[0]["matches_suspended"] == 2
    assert rows[0]["origin_match_id"] == match.match_id
    assert rows[0]["status"] == "active"


async def test_the_single_suspension_keeps_the_expulsion_duration(
    db_session, tenant_factory
):
    """RF-003: 2 partidos de expulsión frente a 4 de acumulación; no hay dos filas."""

    tenant = await tenant_factory("018 T4 duración")
    config = discipline_config(limit=3, yellow_matches=4, red_matches=2)
    match = await close_absorbed_double_yellow(db_session, tenant, config=config)
    player = match.home_starters[0]

    rows = await suspension_rows(db_session, tenant, player)

    assert [row["matches_suspended"] for row in rows] == [2], rows
    assert rows[0]["reason"] == "double_yellow_red"
    assert all(row["matches_suspended"] != 4 for row in rows)


async def test_the_red_registered_in_this_close_carries_its_own_reason(
    db_session, tenant_factory
):
    """RF-010: el motivo sale del ``metadata`` que devuelve el ``RETURNING``."""

    tenant = await tenant_factory("018 T4 motivo del cierre")
    config = discipline_config(limit=3, yellow_matches=4, red_matches=2)
    match, _ = await create_draft_match(db_session, tenant, config=config)
    await publish_tournament(db_session, match)
    await db_session.commit()
    player = match.home_starters[0]

    dto = report(
        [
            yellow_payload(
                player,
                team_id=match.home_team_id,
                segment_id=match.segment_1,
                minute=20,
                label="018-own-reason-yellow-1",
            ),
            yellow_payload(
                player,
                team_id=match.home_team_id,
                segment_id=match.segment_1,
                minute=30,
                label="018-own-reason-yellow-2",
            ),
            red_payload(
                player,
                team_id=match.home_team_id,
                segment_id=match.segment_1,
                minute=40,
                label="018-own-reason-red",
            ),
        ]
    )
    await close_match(match.match_id, dto, context_for(tenant), db_session)

    rows = await suspension_rows(db_session, tenant, player)

    # Sin umbral cruzado: la única sanción es la de la roja y ya se etiqueta bien
    # en el cierre que la registra (antes se guardaba como roja directa).
    assert len(rows) == 1, rows
    assert rows[0]["reason"] == "double_yellow_red"
    assert rows[0]["matches_suspended"] == 2


async def test_served_matches_match_the_configured_duration(db_session, tenant_factory):
    """RF-003, RF-011: con duración 2, el tercer partido deja la sanción ``served``."""

    tenant = await tenant_factory("018 T4 partidos cumplidos")
    config = discipline_config(limit=3, yellow_matches=4, red_matches=2)
    match, _ = await create_draft_match(db_session, tenant, config=config)
    player = match.home_starters[0]
    # Segundo y tercer partido del equipo sin convocar al sancionado: se crean
    # con la versión en borrador y se publican junto al primero.
    siblings = [
        await create_sibling_match(db_session, match, exclude_player=player)
        for _ in range(2)
    ]
    await publish_tournament(db_session, match)
    await db_session.commit()

    await close_match(
        match.match_id,
        report(
            [
                yellow_payload(
                    player,
                    team_id=match.home_team_id,
                    segment_id=match.segment_1,
                    minute=20,
                    label="018-served-yellow-1",
                ),
                yellow_payload(
                    player,
                    team_id=match.home_team_id,
                    segment_id=match.segment_1,
                    minute=30,
                    label="018-served-yellow-2",
                ),
                red_payload(
                    player,
                    team_id=match.home_team_id,
                    segment_id=match.segment_1,
                    minute=40,
                    label="018-served-red",
                ),
            ]
        ),
        context_for(tenant),
        db_session,
    )
    [suspension] = await suspension_rows(db_session, tenant, player)
    assert suspension["matches_suspended"] == 2
    # La lectura anterior abrió una transacción implícita; el cierre abre la suya.
    await db_session.commit()

    for sibling in siblings:
        await close_match(
            sibling.match_id, report([]), context_for(tenant), db_session
        )

    rows = await suspension_rows(db_session, tenant, player)

    assert len(rows) == 1, rows
    assert rows[0]["id"] == suspension["id"]
    assert rows[0]["status"] == "served"
    assert await serves_count(db_session, tenant, rows[0]["id"]) == 2
    # Sin filas residuales: ninguna sanción vigente que la corrección habría dejado.
    assert [row for row in rows if row["status"] == "active"] == []


async def test_a_later_act_without_cards_creates_no_suspensions(
    db_session, tenant_factory
):
    """RF-005, RF-006: el historial no origina sanciones en el acta siguiente."""

    tenant = await tenant_factory("018 T4 sin origen")
    config = discipline_config(limit=3, yellow_matches=1, red_matches=2)
    match, _ = await create_draft_match(db_session, tenant, config=config)
    player = match.home_starters[0]
    # El acta siguiente es del equipo: el sancionado no puede estar convocado
    # mientras la sanción siga vigente (paso 12), así que se excluye.
    sibling = await create_sibling_match(db_session, match, exclude_player=player)
    await publish_tournament(db_session, match)
    await db_session.commit()

    await close_match(
        match.match_id,
        report(
            [
                red_payload(
                    player,
                    team_id=match.home_team_id,
                    segment_id=match.segment_1,
                    minute=40,
                    label="018-no-origin-red",
                    red_card_type="direct_red",
                )
            ]
        ),
        context_for(tenant),
        db_session,
    )
    assert await suspension_count(db_session, tenant, match.match_id) == 1
    # La lectura anterior abrió una transacción implícita; el cierre abre la suya.
    await db_session.commit()

    await close_match(sibling.match_id, report([]), context_for(tenant), db_session)

    rows = await suspension_rows(db_session, tenant, player)

    assert len(rows) == 1, rows
    assert rows[0]["origin_match_id"] == match.match_id
    assert await suspension_count(db_session, tenant, sibling.match_id) == 0


async def test_a_historical_double_yellow_red_is_not_duplicated_or_rewritten(
    db_session, tenant_factory
):
    """RF-005, RF-006, R-3: la etiqueta heredada no se corrige ni se duplica."""

    tenant = await tenant_factory("018 T4 roja heredada")
    config = discipline_config(limit=3, yellow_matches=1, red_matches=2)
    match, _ = await create_draft_match(db_session, tenant, config=config)
    sibling = await create_sibling_match(db_session, match, match_date=SIBLING_DATE)
    await publish_tournament(db_session, match)
    await db_session.commit()
    player = match.home_starters[0]

    red_event_id = await seed_card(
        db_session,
        match,
        player_id=player,
        event_type="red_card",
        minute=40,
        label="018-legacy-red",
        sibling=sibling,
        red_card_type="double_yellow_red",
    )
    seeded = await seed_suspension(
        db_session,
        match,
        player_id=player,
        origin_match_id=sibling.match_id,
        source_event_id=red_event_id,
        reason="direct_red_card",
        matches_suspended=2,
    )
    await db_session.commit()

    await close_match(match.match_id, report([]), context_for(tenant), db_session)

    rows = await suspension_rows(db_session, tenant, player)

    assert len(rows) == 1, rows
    assert rows[0]["id"] == seeded
    assert rows[0]["origin_match_id"] == sibling.match_id
    # Intacta: motivo heredado, duración y estado no se reescriben.
    assert rows[0]["reason"] == "direct_red_card"
    assert rows[0]["matches_suspended"] == 2
    assert rows[0]["status"] == "served"


async def test_a_recorded_red_event_is_not_sanctioned_twice(
    db_session, tenant_factory
):
    """RF-005, RF-012: la unicidad por evento de roja es aparte del motivo."""

    tenant = await tenant_factory("018 T4 roja reutilizada")
    config = discipline_config(limit=2, yellow_matches=4, red_matches=2)
    match, seeded = await close_reused_red_with_threshold(
        db_session, tenant, config=config
    )
    player = match.home_starters[0]

    rows = await suspension_rows(db_session, tenant, player)

    assert len(rows) == 1, rows
    assert rows[0]["id"] == seeded
    assert rows[0]["reason"] == "direct_red_card"
    assert rows[0]["status"] == "served"
    assert await audit_suspensions(db_session, tenant, match.match_id) == "0"


async def test_the_audit_counts_the_rows_actually_created(db_session, tenant_factory):
    """RF-012, RNF-008: el recuento es el de filas creadas, no el de la lista derivada."""

    absorbing_tenant = await tenant_factory("018 T4 auditoría absorción")
    absorbing = await close_absorbed_double_yellow(
        db_session,
        absorbing_tenant,
        config=discipline_config(limit=3, yellow_matches=1, red_matches=2),
    )

    # La lista derivada tiene 2 (acumulación + expulsión): la absorción deja 1.
    assert (
        await audit_suspensions(db_session, absorbing_tenant, absorbing.match_id)
        == "1"
    )
    assert (
        await suspension_count(db_session, absorbing_tenant, absorbing.match_id) == 1
    )

    reused_tenant = await tenant_factory("018 T4 auditoría unicidad")
    reused, _ = await close_reused_red_with_threshold(
        db_session,
        reused_tenant,
        config=discipline_config(limit=2, yellow_matches=4, red_matches=2),
    )

    # No se creó ninguna: la única fila del partido ya estaba registrada.
    assert await audit_suspensions(db_session, reused_tenant, reused.match_id) == "0"
    assert await suspension_count(db_session, reused_tenant, reused.match_id) == 1


async def test_a_direct_red_plus_a_threshold_keeps_two_suspensions(
    db_session, tenant_factory
):
    """RF-009: la roja directa no absorbe el umbral cruzado."""

    tenant = await tenant_factory("018 T4 roja directa")
    config = discipline_config(limit=3, yellow_matches=4, red_matches=2)
    match, _ = await create_draft_match(db_session, tenant, config=config)
    await publish_tournament(db_session, match)
    await db_session.commit()
    player = match.home_starters[0]

    dto = report(
        [
            yellow_payload(
                player,
                team_id=match.home_team_id,
                segment_id=match.segment_1,
                minute=10,
                label="018-direct-yellow-1",
            ),
            yellow_payload(
                player,
                team_id=match.home_team_id,
                segment_id=match.segment_1,
                minute=20,
                label="018-direct-yellow-2",
            ),
            yellow_payload(
                player,
                team_id=match.home_team_id,
                segment_id=match.segment_1,
                minute=30,
                label="018-direct-yellow-3",
            ),
            red_payload(
                player,
                team_id=match.home_team_id,
                segment_id=match.segment_1,
                minute=40,
                label="018-direct-red",
                red_card_type="direct_red",
            ),
        ]
    )
    await close_match(match.match_id, dto, context_for(tenant), db_session)

    rows = await suspension_rows(db_session, tenant, player)

    assert len(rows) == 2, rows
    durations = {row["reason"]: row["matches_suspended"] for row in rows}
    assert durations == {
        "yellow_card_accumulation": 4,
        "direct_red_card": 2,
    }


async def test_the_discipline_history_is_isolated_by_organization(
    db_session, tenant_factory
):
    """RF-014, RNF-001: otra organización no ve el historial de este torneo."""

    tenant = await tenant_factory("018 T4 aislamiento")
    config = discipline_config()
    match, _ = await create_draft_match(db_session, tenant, config=config)
    sibling = await create_sibling_match(db_session, match)
    await publish_tournament(db_session, match)
    await db_session.commit()
    player = match.home_starters[0]

    history_event = await seed_card(
        db_session,
        match,
        player_id=player,
        event_type="yellow_card",
        minute=10,
        label="018-isolation-yellow",
        sibling=sibling,
    )
    await db_session.commit()
    service = CloseMatchReportService(db_session)

    await set_tenant_context(db_session, tenant)
    own_history = await service._load_discipline_history(
        context_for(tenant), match_mapping(match, config)
    )
    assert [row["id"] for row in own_history] == [history_event]

    other = await create_tenant_owner(db_session, full_name="018 T4 otra organización")
    other_history = await service._load_discipline_history(
        context_for(other), match_mapping(match, config)
    )
    assert other_history == []


async def test_the_recorded_red_read_is_isolated_by_organization(
    db_session, tenant_factory
):
    """RF-014, RNF-001: la lectura acotada de rojas no ve sanciones ajenas.

    La clave foránea compuesta ``(source_event_id, origin_match_id, player_id,
    organization_id)`` de ``player_suspensions`` impide que una organización
    registre una sanción sobre el evento de roja de otra: la fila solo puede
    apuntar a un evento de su propia organización. El escenario siembra por
    tanto **un evento de roja propio y su sanción en cada organización** y
    comprueba las dos caras del aislamiento: la lectura del contexto del torneo
    que se cierra no devuelve la sanción ajena (conjunto vacío), la de la
    organización dueña sí la devuelve, y el cierre del acta **inserta** su
    propia sanción en vez de descartarla.
    """

    tenant = await tenant_factory("018 T4 aislamiento de rojas")
    config = discipline_config(limit=3, yellow_matches=4, red_matches=2)
    match, _ = await create_draft_match(db_session, tenant, config=config)
    await publish_tournament(db_session, match)
    await db_session.commit()
    player = match.home_starters[0]

    other = await create_tenant_owner(db_session, full_name="018 T4 rojas ajenas")
    other_match, _ = await create_draft_match(db_session, other, config=config)
    await publish_tournament(db_session, other_match)
    await db_session.commit()
    other_player = other_match.home_starters[0]
    other_event = await seed_card(
        db_session,
        other_match,
        player_id=other_player,
        event_type="red_card",
        minute=40,
        label="018-isolation-red-other",
        red_card_type="direct_red",
    )
    await seed_suspension(
        db_session,
        other_match,
        player_id=other_player,
        origin_match_id=other_match.match_id,
        source_event_id=other_event,
        reason="direct_red_card",
        matches_suspended=2,
    )
    await db_session.commit()
    service = CloseMatchReportService(db_session)

    await set_tenant_context(db_session, tenant)
    assert (
        await service._load_recorded_red_suspensions(context_for(tenant), [other_event])
        == set()
    )
    # La fila existe y la ve su propia organización: el vacío es aislamiento.
    await set_tenant_context(db_session, other)
    assert await service._load_recorded_red_suspensions(
        context_for(other), [other_event]
    ) == {str(other_event)}
    # Las lecturas anteriores abrieron una transacción implícita; el cierre
    # abre la suya.
    await set_tenant_context(db_session, tenant)
    await db_session.commit()

    await close_match(
        match.match_id,
        report(
            [
                yellow_payload(
                    player,
                    team_id=match.home_team_id,
                    segment_id=match.segment_1,
                    minute=20,
                    label="018-isolation-yellow-1",
                ),
                yellow_payload(
                    player,
                    team_id=match.home_team_id,
                    segment_id=match.segment_1,
                    minute=30,
                    label="018-isolation-yellow-2",
                ),
                red_payload(
                    player,
                    team_id=match.home_team_id,
                    segment_id=match.segment_1,
                    minute=40,
                    label="018-isolation-red",
                ),
            ]
        ),
        context_for(tenant),
        db_session,
    )

    rows = await suspension_rows(db_session, tenant, player)

    assert len(rows) == 1, rows
    assert rows[0]["reason"] == "double_yellow_red"
    assert rows[0]["origin_match_id"] == match.match_id
    # La sanción ajena sigue siendo la única de su organización.
    other_rows = await suspension_rows(db_session, other, other_player)
    assert [row["source_event_id"] for row in other_rows] == [other_event]


async def test_the_stage_reset_decides_which_yellows_count(db_session, tenant_factory):
    """RF-008: con el reinicio activo, la amarilla de otra fase no cuenta (y sí al revés)."""

    async def close_across_stages(tenant, *, clear_yellows_on_stage_change: bool):
        config = discipline_config(
            limit=3,
            yellow_matches=4,
            red_matches=2,
            clear_yellows_on_stage_change=clear_yellows_on_stage_change,
        )
        # Dos fases en la misma versión: el segundo partido se crea en la otra
        # fase, todavía en borrador.
        match, stage_two = await create_draft_match(
            db_session, tenant, config=config, second_stage=True
        )
        player = match.home_starters[0]
        other_stage = await create_sibling_match(
            db_session, match, stage_id=stage_two
        )
        await publish_tournament(db_session, match)
        await db_session.commit()
        await seed_card(
            db_session,
            match,
            player_id=player,
            event_type="yellow_card",
            minute=10,
            label="018-stage-yellow",
            sibling=other_stage,
        )
        await db_session.commit()

        # Dos amarillas en el acta (sin roja por doble amarilla): con el reinicio
        # activo solo son 2 y no cruzan el umbral 3; sin él, la de la otra fase
        # suma la tercera y la acumulación se emite.
        dto = report(
            [
                yellow_payload(
                    player,
                    team_id=match.home_team_id,
                    segment_id=match.segment_1,
                    minute=20,
                    label="018-stage-yellow-1",
                ),
                yellow_payload(
                    player,
                    team_id=match.home_team_id,
                    segment_id=match.segment_1,
                    minute=30,
                    label="018-stage-yellow-2",
                ),
                red_payload(
                    player,
                    team_id=match.home_team_id,
                    segment_id=match.segment_1,
                    minute=40,
                    label="018-stage-red",
                    red_card_type="direct_red",
                ),
            ]
        )
        await close_match(match.match_id, dto, context_for(tenant), db_session)
        return await suspension_rows(db_session, tenant, player)

    reset_tenant = await tenant_factory("018 T4 reinicio activo")
    reset_rows = await close_across_stages(
        reset_tenant, clear_yellows_on_stage_change=True
    )
    assert [row["reason"] for row in reset_rows] == ["direct_red_card"]

    no_reset_tenant = await tenant_factory("018 T4 reinicio desactivado")
    no_reset_rows = await close_across_stages(
        no_reset_tenant, clear_yellows_on_stage_change=False
    )
    assert sorted(row["reason"] for row in no_reset_rows) == [
        "direct_red_card",
        "yellow_card_accumulation",
    ]


async def test_three_previous_yellows_are_rejected_without_writing(
    database_admin_url,
):
    """RF-013 (regresión de la 017): tres amarillas previas → 409 y escritura cero."""

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
                    label="018-regression-yellow-1",
                ),
                yellow_payload(
                    player,
                    team_id=match.home_team_id,
                    segment_id=match.segment_1,
                    minute=20,
                    label="018-regression-yellow-2",
                ),
                yellow_payload(
                    player,
                    team_id=match.home_team_id,
                    segment_id=match.segment_1,
                    minute=30,
                    label="018-regression-yellow-3",
                ),
                red_payload(
                    player,
                    team_id=match.home_team_id,
                    segment_id=match.segment_1,
                    minute=40,
                    label="018-regression-red",
                ),
            ]
        )

        with pytest.raises(DoubleYellowInconsistent) as error:
            await close_in_session(engine, context, match.match_id, dto)

        assert_inconsistent(error.value, minute=40)
        assert_nothing_was_written(await act_state(engine, match))
