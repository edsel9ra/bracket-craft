"""Create the development demo account and a partially played bracket.

This module intentionally uses the application database role and sets the same
RLS context as the API. It is not a migration and must not run in production.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import DEVELOPMENT_ENVS, get_settings
from app.core.database import SessionFactory, engine, set_rls_context
from app.core.security import hash_password
from app.core.tenancy import AuthContext
from app.modules.matches.formations import FORMATION_SLOTS
from app.modules.matches.schemas import CloseMatchReportDTO, MatchEventPayload
from app.modules.matches.service import CloseMatchReportService
from app.modules.rules_engine.defaults import DEFAULT_RULES_CONFIG
from app.modules.rules_engine.engine import validate_rules_config


DEMO_USER_EMAIL = "demo.owner@bracketcraft.dev"
DEMO_USER_PASSWORD = "Demo1234!"
DEMO_USER_NAME = "Demo Owner"
DEMO_ORGANIZATION_NAME = "Demo Federation"
DEMO_ORGANIZATION_SLUG = "demo-federation"
DEMO_TOURNAMENT_NAME = "Copa Demo Bracket Craft"
DEMO_TOURNAMENT_SEASON = "2026"
DEMO_PLAYER_COUNT = 12


@dataclass(frozen=True)
class TeamSpec:
    code: str
    name: str


@dataclass(frozen=True)
class PlayerSpec:
    team_code: str
    first_name: str
    last_name: str
    national_id: str
    birth_date: date
    dorsal_number: int


@dataclass(frozen=True)
class MatchSpec:
    code: str
    home_code: str | None
    away_code: str | None
    matchday: int
    days_from_start: int
    home_score: int | None = None
    away_score: int | None = None
    home_formation: str | None = None
    away_formation: str | None = None


@dataclass(frozen=True)
class AdvancementSpec:
    source_code: str
    target_code: str
    outcome: str
    target_side: str


@dataclass(frozen=True)
class RosterRecord:
    roster_id: UUID
    player_id: UUID
    dorsal_number: int


@dataclass(frozen=True)
class SeedState:
    context: AuthContext
    tournament_id: UUID
    version_id: UUID
    stage_id: UUID
    start_date: date
    teams: dict[str, UUID]
    rosters: dict[str, tuple[RosterRecord, ...]]
    matches: dict[str, UUID]


TEAM_SPECS = (
    TeamSpec("AUR", "Aurora FC"),
    TeamSpec("BOR", "Boreal FC"),
    TeamSpec("CEN", "Central FC"),
    TeamSpec("DEL", "Delta FC"),
    TeamSpec("EST", "Estrella FC"),
    TeamSpec("FEN", "Fenix FC"),
    TeamSpec("GLA", "Glacial FC"),
    TeamSpec("HOR", "Horizonte FC"),
)

MATCH_SPECS = (
    MatchSpec("QF1", "AUR", "BOR", 1, 1, 2, 1, "4-3-3", "4-4-2"),
    MatchSpec("QF2", "CEN", "DEL", 1, 2, 1, 0, "3-5-2", "4-2-3-1"),
    MatchSpec("QF3", "EST", "FEN", 1, 3, 2, 0, "4-2-3-1", "4-3-3"),
    MatchSpec("QF4", "GLA", "HOR", 1, 4, 3, 2, "4-4-2", "3-5-2"),
    MatchSpec("SF1", None, None, 2, 14),
    MatchSpec("SF2", None, None, 2, 15),
    MatchSpec("FINAL", None, None, 3, 21),
)

ADVANCEMENT_SPECS = (
    AdvancementSpec("QF1", "SF1", "winner", "home"),
    AdvancementSpec("QF2", "SF1", "winner", "away"),
    AdvancementSpec("QF3", "SF2", "winner", "home"),
    AdvancementSpec("QF4", "SF2", "winner", "away"),
    AdvancementSpec("SF1", "FINAL", "winner", "home"),
    AdvancementSpec("SF2", "FINAL", "winner", "away"),
)

RESULT_SLOT_SOURCES = {
    ("SF1", "home"): ("QF1", "winner"),
    ("SF1", "away"): ("QF2", "winner"),
    ("SF2", "home"): ("QF3", "winner"),
    ("SF2", "away"): ("QF4", "winner"),
    ("FINAL", "home"): ("SF1", "winner"),
    ("FINAL", "away"): ("SF2", "winner"),
}


def build_player_specs() -> tuple[PlayerSpec, ...]:
    """Build stable, synthetic players without storing clear-text documents."""

    players: list[PlayerSpec] = []
    for team_index, team in enumerate(TEAM_SPECS):
        for dorsal_number in range(1, DEMO_PLAYER_COUNT + 1):
            players.append(
                PlayerSpec(
                    team_code=team.code,
                    first_name=team.name.removesuffix(" FC"),
                    last_name=f"Player {dorsal_number:02d}",
                    national_id=f"BC-DEMO-{team.code}-{dorsal_number:02d}",
                    birth_date=date(
                        1990 + ((team_index + dorsal_number) % 10),
                        ((dorsal_number - 1) % 12) + 1,
                        ((dorsal_number * 2 + team_index) % 27) + 1,
                    ),
                    dorsal_number=dorsal_number,
                )
            )
    return tuple(players)


PLAYER_SPECS = build_player_specs()


def validate_demo_definition() -> None:
    team_codes = {team.code for team in TEAM_SPECS}
    match_codes = {match.code for match in MATCH_SPECS}
    if len(TEAM_SPECS) != 8 or len(team_codes) != 8:
        raise ValueError("La definición demo debe contener ocho equipos únicos")
    if len(MATCH_SPECS) != 7 or len(match_codes) != 7:
        raise ValueError("La definición demo debe contener siete partidos únicos")
    if len(ADVANCEMENT_SPECS) != 6:
        raise ValueError("La definición demo debe contener seis enlaces de avance")
    if len(PLAYER_SPECS) != len(TEAM_SPECS) * DEMO_PLAYER_COUNT:
        raise ValueError("La definición demo debe contener doce jugadores por equipo")
    if any(player.team_code not in team_codes for player in PLAYER_SPECS):
        raise ValueError("La plantilla demo contiene un equipo inexistente")
    if any(
        formation not in FORMATION_SLOTS
        for match in MATCH_SPECS
        for formation in (match.home_formation, match.away_formation)
        if formation is not None
    ):
        raise ValueError("La definición demo contiene una formación no soportada")
    for match in MATCH_SPECS:
        if match.home_code not in team_codes and match.home_code is not None:
            raise ValueError(f"Equipo local inexistente en {match.code}")
        if match.away_code not in team_codes and match.away_code is not None:
            raise ValueError(f"Equipo visitante inexistente en {match.code}")
        if (match.home_score is None) != (match.away_score is None):
            raise ValueError(f"El marcador de {match.code} está incompleto")
    for source in ADVANCEMENT_SPECS:
        if source.source_code not in match_codes or source.target_code not in match_codes:
            raise ValueError("Un enlace de avance apunta a un partido inexistente")


def _match_datetime(start_date: date, days_from_start: int) -> datetime:
    match_day = start_date + timedelta(days=days_from_start)
    return datetime(
        match_day.year,
        match_day.month,
        match_day.day,
        18,
        0,
        tzinfo=timezone.utc,
    )


def _player_hmac(national_id: str, player_data_key: str) -> str:
    return hmac.new(
        player_data_key.encode("utf-8"),
        national_id.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def _slot_source(match: MatchSpec, side: str) -> tuple[str, dict[str, str]]:
    team_code = match.home_code if side == "home" else match.away_code
    if team_code is not None:
        return "direct_team", {"team_code": team_code}
    source = RESULT_SLOT_SOURCES.get((match.code, side))
    if source is None:
        raise ValueError(f"No existe fuente para el slot {match.code}_{side}")
    source_code, outcome = source
    return "match_result", {"source_match_code": source_code, "outcome": outcome}


async def _ensure_demo_user(db: AsyncSession) -> UUID:
    result = await db.execute(
        text("""
            SELECT id, is_active
            FROM users
            WHERE LOWER(email) = LOWER(:email)
        """),
        {"email": DEMO_USER_EMAIL},
    )
    user = result.mappings().one_or_none()
    if user is not None:
        if not user["is_active"]:
            raise RuntimeError(f"La cuenta demo está desactivada: {DEMO_USER_EMAIL}")
        return user["id"]

    result = await db.execute(
        text("""
            INSERT INTO users (email, password_hash, full_name)
            VALUES (:email, :password_hash, :full_name)
            RETURNING id
        """),
        {
            "email": DEMO_USER_EMAIL,
            "password_hash": hash_password(DEMO_USER_PASSWORD),
            "full_name": DEMO_USER_NAME,
        },
    )
    return result.scalar_one()


async def _ensure_demo_organization(db: AsyncSession, user_id: UUID) -> UUID:
    await set_rls_context(db, None, user_id)
    result = await db.execute(
        text("""
            SELECT id
            FROM list_user_organizations()
            WHERE slug = :slug
        """),
        {"slug": DEMO_ORGANIZATION_SLUG},
    )
    organization_id = result.scalar_one_or_none()
    if organization_id is not None:
        return organization_id

    result = await db.execute(
        text("SELECT create_organization_with_owner(:name, :slug, :user_id)"),
        {
            "name": DEMO_ORGANIZATION_NAME,
            "slug": DEMO_ORGANIZATION_SLUG,
            "user_id": str(user_id),
        },
    )
    return result.scalar_one()


async def _ensure_tournament(
    db: AsyncSession,
    organization_id: UUID,
    start_date: date,
) -> tuple[UUID, date, str]:
    result = await db.execute(
        text("""
            SELECT id, start_date, status
            FROM tournaments
            WHERE organization_id = :organization_id
              AND name = :name
              AND season = :season
        """),
        {
            "organization_id": str(organization_id),
            "name": DEMO_TOURNAMENT_NAME,
            "season": DEMO_TOURNAMENT_SEASON,
        },
    )
    tournament = result.mappings().one_or_none()
    if tournament is not None:
        if tournament["status"] in {"finished", "archived"}:
            raise RuntimeError("El torneo demo ya está terminado o archivado")
        return tournament["id"], tournament["start_date"], tournament["status"]

    result = await db.execute(
        text("""
            INSERT INTO tournaments
                (organization_id, name, season, start_date, status, current_draft_config)
            VALUES (:organization_id, :name, :season, :start_date, 'draft', CAST(:config AS jsonb))
            RETURNING id, start_date, status
        """),
        {
            "organization_id": str(organization_id),
            "name": DEMO_TOURNAMENT_NAME,
            "season": DEMO_TOURNAMENT_SEASON,
            "start_date": start_date,
            "config": json.dumps(DEFAULT_RULES_CONFIG),
        },
    )
    tournament = result.mappings().one()
    return tournament["id"], tournament["start_date"], tournament["status"]


async def _ensure_version(
    db: AsyncSession,
    organization_id: UUID,
    tournament_id: UUID,
    member_id: UUID,
) -> tuple[UUID, str]:
    result = await db.execute(
        text("""
            SELECT id, status
            FROM tournament_versions
            WHERE organization_id = :organization_id
              AND tournament_id = :tournament_id
              AND version_number = 1
        """),
        {
            "organization_id": str(organization_id),
            "tournament_id": str(tournament_id),
        },
    )
    version = result.mappings().one_or_none()
    if version is not None:
        if version["status"] == "archived":
            raise RuntimeError("La versión demo está archivada y no se puede reutilizar")
        return version["id"], version["status"]

    rules = json.dumps(DEFAULT_RULES_CONFIG)
    result = await db.execute(
        text("""
            INSERT INTO tournament_versions
                (organization_id, tournament_id, version_number, rules_config,
                 phase_config, status, created_by_member_id)
            VALUES (:organization_id, :tournament_id, 1, CAST(:rules AS jsonb),
                    '{}'::jsonb, 'draft', :member_id)
            RETURNING id, status
        """),
        {
            "organization_id": str(organization_id),
            "tournament_id": str(tournament_id),
            "rules": rules,
            "member_id": str(member_id),
        },
    )
    version = result.mappings().one()
    return version["id"], version["status"]


async def _ensure_team(
    db: AsyncSession,
    organization_id: UUID,
    tournament_id: UUID,
    spec: TeamSpec,
) -> UUID:
    result = await db.execute(
        text("""
            SELECT id, name
            FROM teams
            WHERE organization_id = :organization_id
              AND LOWER(short_code) = LOWER(:short_code)
        """),
        {"organization_id": str(organization_id), "short_code": spec.code},
    )
    team = result.mappings().one_or_none()
    if team is None:
        result = await db.execute(
            text("""
                INSERT INTO teams (organization_id, name, short_code)
                VALUES (:organization_id, :name, :short_code)
                RETURNING id
            """),
            {
                "organization_id": str(organization_id),
                "name": spec.name,
                "short_code": spec.code,
            },
        )
        team_id = result.scalar_one()
    else:
        if team["name"] != spec.name:
            raise RuntimeError(f"El código {spec.code} pertenece a otro equipo")
        team_id = team["id"]

    tournament_team = await db.execute(
        text("""
            SELECT status
            FROM tournament_teams
            WHERE organization_id = :organization_id
              AND tournament_id = :tournament_id
              AND team_id = :team_id
        """),
        {
            "organization_id": str(organization_id),
            "tournament_id": str(tournament_id),
            "team_id": str(team_id),
        },
    )
    tournament_team_status = tournament_team.scalar_one_or_none()
    if tournament_team_status is None:
        await db.execute(
            text("""
                INSERT INTO tournament_teams (organization_id, tournament_id, team_id, status)
                VALUES (:organization_id, :tournament_id, :team_id, 'registered')
            """),
            {
                "organization_id": str(organization_id),
                "tournament_id": str(tournament_id),
                "team_id": str(team_id),
            },
        )
    elif tournament_team_status != "registered":
        await db.execute(
            text("""
                UPDATE tournament_teams
                SET status = 'registered'
                WHERE organization_id = :organization_id
                  AND tournament_id = :tournament_id
                  AND team_id = :team_id
            """),
            {
                "organization_id": str(organization_id),
                "tournament_id": str(tournament_id),
                "team_id": str(team_id),
            },
        )
    return team_id


async def _ensure_stage(
    db: AsyncSession,
    organization_id: UUID,
    tournament_id: UUID,
    version_id: UUID,
    version_status: str,
) -> UUID:
    result = await db.execute(
        text("""
            SELECT id, stage_type
            FROM stages
            WHERE organization_id = :organization_id
              AND tournament_id = :tournament_id
              AND tournament_version_id = :version_id
              AND name = 'Eliminatoria Demo'
        """),
        {
            "organization_id": str(organization_id),
            "tournament_id": str(tournament_id),
            "version_id": str(version_id),
        },
    )
    stage = result.mappings().one_or_none()
    if stage is not None:
        if stage["stage_type"] != "single_elimination":
            raise RuntimeError("La fase demo existente no es de eliminación directa")
        return stage["id"]
    if version_status != "draft":
        raise RuntimeError("La versión publicada no contiene la fase demo completa")

    result = await db.execute(
        text("""
            INSERT INTO stages
                (organization_id, tournament_id, tournament_version_id, name, stage_type, stage_order)
            VALUES (:organization_id, :tournament_id, :version_id,
                    'Eliminatoria Demo', 'single_elimination', 1)
            RETURNING id
        """),
        {
            "organization_id": str(organization_id),
            "tournament_id": str(tournament_id),
            "version_id": str(version_id),
        },
    )
    return result.scalar_one()


async def _ensure_stage_teams(
    db: AsyncSession,
    organization_id: UUID,
    tournament_id: UUID,
    version_id: UUID,
    stage_id: UUID,
    version_status: str,
    team_ids: dict[str, UUID],
) -> None:
    for team_id in team_ids.values():
        result = await db.execute(
            text("""
                SELECT 1
                FROM stage_teams
                WHERE organization_id = :organization_id
                  AND tournament_id = :tournament_id
                  AND tournament_version_id = :version_id
                  AND stage_id = :stage_id
                  AND group_id IS NULL
                  AND team_id = :team_id
            """),
            {
                "organization_id": str(organization_id),
                "tournament_id": str(tournament_id),
                "version_id": str(version_id),
                "stage_id": str(stage_id),
                "team_id": str(team_id),
            },
        )
        if result.scalar_one_or_none() is not None:
            continue
        if version_status != "draft":
            raise RuntimeError("La fase publicada no tiene los ocho equipos demo asignados")
        await db.execute(
            text("""
                INSERT INTO stage_teams
                    (organization_id, tournament_id, tournament_version_id, stage_id, team_id)
                VALUES (:organization_id, :tournament_id, :version_id, :stage_id, :team_id)
            """),
            {
                "organization_id": str(organization_id),
                "tournament_id": str(tournament_id),
                "version_id": str(version_id),
                "stage_id": str(stage_id),
                "team_id": str(team_id),
            },
        )


async def _ensure_rosters(
    db: AsyncSession,
    organization_id: UUID,
    tournament_id: UUID,
    team_ids: dict[str, UUID],
    start_date: date,
    player_data_key: str,
) -> dict[str, tuple[RosterRecord, ...]]:
    valid_from = datetime(
        start_date.year,
        start_date.month,
        start_date.day,
        tzinfo=timezone.utc,
    )
    for player in PLAYER_SPECS:
        team_id = team_ids[player.team_code]
        document_hmac = _player_hmac(player.national_id, player_data_key)
        result = await db.execute(
            text("""
                SELECT id
                FROM players
                WHERE document_type = 'internal'
                  AND issuing_country = 'COL'
                  AND national_id_hmac = :national_id_hmac
            """),
            {"national_id_hmac": document_hmac},
        )
        player_id = result.scalar_one_or_none()
        if player_id is None:
            result = await db.execute(
                text("""
                    INSERT INTO players
                        (first_name, last_name, document_type, national_id_encrypted,
                         national_id_hmac, issuing_country, birth_date)
                    VALUES (
                        :first_name, :last_name, 'internal',
                        pgp_sym_encrypt(CAST(:national_id AS TEXT), :player_data_key),
                        :national_id_hmac, 'COL', :birth_date
                    )
                    RETURNING id
                """),
                {
                    "first_name": player.first_name,
                    "last_name": player.last_name,
                    "national_id": player.national_id,
                    "player_data_key": player_data_key,
                    "national_id_hmac": document_hmac,
                    "birth_date": player.birth_date,
                },
            )
            player_id = result.scalar_one()

        roster_result = await db.execute(
            text("""
                SELECT id
                FROM rosters
                WHERE organization_id = :organization_id
                  AND tournament_id = :tournament_id
                  AND team_id = :team_id
                  AND player_id = :player_id
            """),
            {
                "organization_id": str(organization_id),
                "tournament_id": str(tournament_id),
                "team_id": str(team_id),
                "player_id": str(player_id),
            },
        )
        if roster_result.scalar_one_or_none() is None:
            await db.execute(
                text("""
                    INSERT INTO rosters
                        (organization_id, tournament_id, team_id, player_id, dorsal_number,
                         photo_consent, valid_from, eligible_from)
                    VALUES (:organization_id, :tournament_id, :team_id, :player_id,
                            :dorsal_number, FALSE, :valid_from, :valid_from)
                """),
                {
                    "organization_id": str(organization_id),
                    "tournament_id": str(tournament_id),
                    "team_id": str(team_id),
                    "player_id": str(player_id),
                    "dorsal_number": player.dorsal_number,
                    "valid_from": valid_from,
                },
            )

    rosters: dict[str, tuple[RosterRecord, ...]] = {}
    for team in TEAM_SPECS:
        result = await db.execute(
            text("""
                SELECT id, player_id, dorsal_number
                FROM rosters
                WHERE organization_id = :organization_id
                  AND tournament_id = :tournament_id
                  AND team_id = :team_id
                  AND is_active = TRUE
                ORDER BY dorsal_number, id
            """),
            {
                "organization_id": str(organization_id),
                "tournament_id": str(tournament_id),
                "team_id": str(team_ids[team.code]),
            },
        )
        records = tuple(
            RosterRecord(
                roster_id=row["id"],
                player_id=row["player_id"],
                dorsal_number=row["dorsal_number"],
            )
            for row in result.mappings().all()
        )
        if len(records) < 11:
            raise RuntimeError(f"La plantilla de {team.code} no tiene once jugadores activos")
        rosters[team.code] = records
    return rosters


async def _ensure_slot(
    db: AsyncSession,
    organization_id: UUID,
    tournament_id: UUID,
    version_id: UUID,
    stage_id: UUID,
    version_status: str,
    match: MatchSpec,
    side: str,
) -> UUID:
    slot_code = f"{match.code}_{side.upper()}"
    result = await db.execute(
        text("""
            SELECT id, source_type
            FROM phase_slots
            WHERE organization_id = :organization_id
              AND tournament_id = :tournament_id
              AND tournament_version_id = :version_id
              AND stage_id = :stage_id
              AND slot_code = :slot_code
        """),
        {
            "organization_id": str(organization_id),
            "tournament_id": str(tournament_id),
            "version_id": str(version_id),
            "stage_id": str(stage_id),
            "slot_code": slot_code,
        },
    )
    slot = result.mappings().one_or_none()
    source_type, source_reference = _slot_source(match, side)
    if slot is not None:
        if slot["source_type"] != source_type:
            raise RuntimeError(f"El slot {slot_code} tiene una fuente incompatible")
        return slot["id"]
    if version_status != "draft":
        raise RuntimeError("La versión publicada no contiene todos los slots de la llave")

    result = await db.execute(
        text("""
            INSERT INTO phase_slots
                (organization_id, tournament_id, tournament_version_id, stage_id,
                 slot_code, source_type, source_reference)
            VALUES (:organization_id, :tournament_id, :version_id, :stage_id,
                    :slot_code, :source_type, CAST(:source_reference AS jsonb))
            RETURNING id
        """),
        {
            "organization_id": str(organization_id),
            "tournament_id": str(tournament_id),
            "version_id": str(version_id),
            "stage_id": str(stage_id),
            "slot_code": slot_code,
            "source_type": source_type,
            "source_reference": json.dumps(source_reference),
        },
    )
    return result.scalar_one()


async def _ensure_match(
    db: AsyncSession,
    organization_id: UUID,
    tournament_id: UUID,
    version_id: UUID,
    stage_id: UUID,
    version_status: str,
    start_date: date,
    team_ids: dict[str, UUID],
    match: MatchSpec,
    slot_ids: dict[tuple[str, str], UUID],
) -> UUID:
    result = await db.execute(
        text("""
            SELECT id
            FROM matches
            WHERE organization_id = :organization_id
              AND tournament_id = :tournament_id
              AND tournament_version_id = :version_id
              AND bracket_code = :bracket_code
        """),
        {
            "organization_id": str(organization_id),
            "tournament_id": str(tournament_id),
            "version_id": str(version_id),
            "bracket_code": match.code,
        },
    )
    existing = result.mappings().one_or_none()
    if existing is not None:
        return existing["id"]
    if version_status != "draft":
        raise RuntimeError(f"La versión publicada no contiene el partido {match.code}")

    result = await db.execute(
        text("""
            INSERT INTO matches
                (organization_id, tournament_id, tournament_version_id, stage_id,
                 bracket_code, home_slot_id, away_slot_id, home_team_id, away_team_id,
                 matchday, match_date)
            VALUES (:organization_id, :tournament_id, :version_id, :stage_id,
                    :bracket_code, :home_slot_id, :away_slot_id, :home_team_id,
                    :away_team_id, :matchday, :match_date)
            RETURNING id
        """),
        {
            "organization_id": str(organization_id),
            "tournament_id": str(tournament_id),
            "version_id": str(version_id),
            "stage_id": str(stage_id),
            "bracket_code": match.code,
            "home_slot_id": str(slot_ids[(match.code, "home")]),
            "away_slot_id": str(slot_ids[(match.code, "away")]),
            "home_team_id": str(team_ids[match.home_code]) if match.home_code else None,
            "away_team_id": str(team_ids[match.away_code]) if match.away_code else None,
            "matchday": match.matchday,
            "match_date": _match_datetime(start_date, match.days_from_start),
        },
    )
    return result.scalar_one()


async def _refresh_slot_references(
    db: AsyncSession,
    organization_id: UUID,
    stage_id: UUID,
    team_ids: dict[str, UUID],
    match_ids: dict[str, UUID],
) -> None:
    for match in MATCH_SPECS:
        for side in ("home", "away"):
            source_type, source_reference = _slot_source(match, side)
            if source_type == "direct_team":
                source_reference = {
                    "team_id": str(team_ids[source_reference["team_code"]]),
                    **source_reference,
                }
            else:
                source_match_code = source_reference["source_match_code"]
                source_reference = {
                    "source_match_id": str(match_ids[source_match_code]),
                    **source_reference,
                }
            await db.execute(
                text("""
                    UPDATE phase_slots
                    SET source_reference = CAST(:source_reference AS jsonb)
                    WHERE organization_id = :organization_id
                      AND stage_id = :stage_id
                      AND slot_code = :slot_code
                """),
                {
                    "organization_id": str(organization_id),
                    "stage_id": str(stage_id),
                    "slot_code": f"{match.code}_{side.upper()}",
                    "source_reference": json.dumps(source_reference),
                },
            )


async def _ensure_advancement_links(
    db: AsyncSession,
    organization_id: UUID,
    version_status: str,
    match_ids: dict[str, UUID],
) -> None:
    for link in ADVANCEMENT_SPECS:
        result = await db.execute(
            text("""
                SELECT 1
                FROM advancement_links
                WHERE organization_id = :organization_id
                  AND source_match_id = :source_match_id
                  AND target_match_id = :target_match_id
                  AND outcome = :outcome
                  AND target_side = :target_side
            """),
            {
                "organization_id": str(organization_id),
                "source_match_id": str(match_ids[link.source_code]),
                "target_match_id": str(match_ids[link.target_code]),
                "outcome": link.outcome,
                "target_side": link.target_side,
            },
        )
        if result.scalar_one_or_none() is not None:
            continue
        if version_status != "draft":
            raise RuntimeError("La versión publicada no contiene todos los enlaces de la llave")
        await db.execute(
            text("""
                INSERT INTO advancement_links
                    (organization_id, source_match_id, target_match_id, outcome, target_side)
                VALUES (:organization_id, :source_match_id, :target_match_id, :outcome, :target_side)
            """),
            {
                "organization_id": str(organization_id),
                "source_match_id": str(match_ids[link.source_code]),
                "target_match_id": str(match_ids[link.target_code]),
                "outcome": link.outcome,
                "target_side": link.target_side,
            },
        )


async def _publish_version(
    db: AsyncSession,
    organization_id: UUID,
    tournament_id: UUID,
    version_id: UUID,
    version_status: str,
) -> None:
    if version_status == "draft":
        await db.execute(
            text("""
                UPDATE tournament_versions
                SET status = 'published',
                    published_at = COALESCE(published_at, CURRENT_TIMESTAMP)
                WHERE id = :version_id
                  AND organization_id = :organization_id
            """),
            {"version_id": str(version_id), "organization_id": str(organization_id)},
        )
    await db.execute(
        text("""
            UPDATE tournaments
            SET published_version_id = :version_id,
                status = CASE WHEN status = 'draft' THEN 'published' ELSE status END
            WHERE id = :tournament_id
              AND organization_id = :organization_id
        """),
        {
            "version_id": str(version_id),
            "tournament_id": str(tournament_id),
            "organization_id": str(organization_id),
        },
    )


async def _ensure_structure(
    db: AsyncSession,
    user_id: UUID,
    organization_id: UUID,
    player_data_key: str,
) -> SeedState:
    await set_rls_context(db, organization_id, user_id)
    member_result = await db.execute(
        text("""
            SELECT id
            FROM organization_users
            WHERE organization_id = :organization_id
              AND user_id = :user_id
              AND is_active = TRUE
        """),
        {"organization_id": str(organization_id), "user_id": str(user_id)},
    )
    member_id = member_result.scalar_one_or_none()
    if member_id is None:
        raise RuntimeError("La cuenta demo no tiene una membresía activa")

    start_date = date.today() - timedelta(days=10)
    tournament_id, actual_start_date, _ = await _ensure_tournament(
        db,
        organization_id,
        start_date,
    )
    version_id, version_status = await _ensure_version(
        db,
        organization_id,
        tournament_id,
        member_id,
    )
    stage_id = await _ensure_stage(
        db,
        organization_id,
        tournament_id,
        version_id,
        version_status,
    )
    team_ids = {
        team.code: await _ensure_team(db, organization_id, tournament_id, team)
        for team in TEAM_SPECS
    }
    await _ensure_stage_teams(
        db,
        organization_id,
        tournament_id,
        version_id,
        stage_id,
        version_status,
        team_ids,
    )
    rosters = await _ensure_rosters(
        db,
        organization_id,
        tournament_id,
        team_ids,
        actual_start_date,
        player_data_key,
    )

    slot_ids: dict[tuple[str, str], UUID] = {}
    for match in MATCH_SPECS:
        for side in ("home", "away"):
            slot_ids[(match.code, side)] = await _ensure_slot(
                db,
                organization_id,
                tournament_id,
                version_id,
                stage_id,
                version_status,
                match,
                side,
            )

    match_ids = {
        match.code: await _ensure_match(
            db,
            organization_id,
            tournament_id,
            version_id,
            stage_id,
            version_status,
            actual_start_date,
            team_ids,
            match,
            slot_ids,
        )
        for match in MATCH_SPECS
    }
    if version_status == "draft":
        await _refresh_slot_references(db, organization_id, stage_id, team_ids, match_ids)
    await _ensure_advancement_links(db, organization_id, version_status, match_ids)
    await _publish_version(db, organization_id, tournament_id, version_id, version_status)

    return SeedState(
        context=AuthContext(
            user_id=user_id,
            organization_id=organization_id,
            organization_user_id=member_id,
        ),
        tournament_id=tournament_id,
        version_id=version_id,
        stage_id=stage_id,
        start_date=actual_start_date,
        teams=team_ids,
        rosters=rosters,
        matches=match_ids,
    )


async def _ensure_tactical_lineup(
    db: AsyncSession,
    organization_id: UUID,
    match_id: UUID,
    segment_id: UUID,
    team_id: UUID,
    formation_code: str,
    rosters: tuple[RosterRecord, ...],
) -> None:
    await db.execute(
        text("""
            INSERT INTO match_team_lineups
                (organization_id, match_id, segment_id, team_id, formation_code)
            VALUES (:organization_id, :match_id, :segment_id, :team_id, :formation_code)
            ON CONFLICT (segment_id, team_id)
            DO UPDATE SET formation_code = EXCLUDED.formation_code
        """),
        {
            "organization_id": str(organization_id),
            "match_id": str(match_id),
            "segment_id": str(segment_id),
            "team_id": str(team_id),
            "formation_code": formation_code,
        },
    )
    position_slots = FORMATION_SLOTS[formation_code]
    for index, roster in enumerate(rosters):
        is_starter = index < len(position_slots)
        await db.execute(
            text("""
                INSERT INTO match_lineup_snapshots
                    (organization_id, match_id, segment_id, team_id, player_id,
                     is_starter, position_slot)
                VALUES (:organization_id, :match_id, :segment_id, :team_id, :player_id,
                        :is_starter, :position_slot)
                ON CONFLICT (segment_id, team_id, player_id)
                DO UPDATE SET is_starter = EXCLUDED.is_starter,
                              position_slot = EXCLUDED.position_slot
            """),
            {
                "organization_id": str(organization_id),
                "match_id": str(match_id),
                "segment_id": str(segment_id),
                "team_id": str(team_id),
                "player_id": str(roster.player_id),
                "is_starter": is_starter,
                "position_slot": position_slots[index] if is_starter else None,
            },
        )
    await db.execute(
        text("""
            UPDATE match_team_lineups
            SET is_public = TRUE,
                published_at = COALESCE(published_at, CURRENT_TIMESTAMP),
                updated_at = CURRENT_TIMESTAMP
            WHERE organization_id = :organization_id
              AND match_id = :match_id
              AND segment_id = :segment_id
              AND team_id = :team_id
        """),
        {
            "organization_id": str(organization_id),
            "match_id": str(match_id),
            "segment_id": str(segment_id),
            "team_id": str(team_id),
        },
    )


async def _prepare_quarterfinal(
    db: AsyncSession,
    state: SeedState,
    match: MatchSpec,
) -> UUID:
    await set_rls_context(db, state.context.organization_id, state.context.user_id)
    match_id = state.matches[match.code]
    result = await db.execute(
        text("""
            SELECT status, home_team_id, away_team_id
            FROM matches
            WHERE id = :match_id
              AND organization_id = :organization_id
        """),
        {
            "match_id": str(match_id),
            "organization_id": str(state.context.organization_id),
        },
    )
    match_row = result.mappings().one()
    expected_home = state.teams[match.home_code]
    expected_away = state.teams[match.away_code]
    if match_row["home_team_id"] != expected_home or match_row["away_team_id"] != expected_away:
        raise RuntimeError(f"Los participantes del partido {match.code} no coinciden con el seed")

    result = await db.execute(
        text("""
            SELECT id, status
            FROM match_segments
            WHERE match_id = :match_id
              AND organization_id = :organization_id
              AND segment_number = 1
        """),
        {
            "match_id": str(match_id),
            "organization_id": str(state.context.organization_id),
        },
    )
    segment = result.mappings().one_or_none()
    if segment is None:
        result = await db.execute(
            text("""
                INSERT INTO match_segments
                    (organization_id, match_id, segment_number, minute_start)
                VALUES (:organization_id, :match_id, 1, 0)
                RETURNING id, status
            """),
            {
                "organization_id": str(state.context.organization_id),
                "match_id": str(match_id),
            },
        )
        segment = result.mappings().one()
    if match_row["status"] not in {"finished", "administrative_resolution"} and segment["status"] != "active":
        raise RuntimeError(f"El partido {match.code} no tiene un segmento activo")

    for side, team_code, formation_code in (
        ("home", match.home_code, match.home_formation),
        ("away", match.away_code, match.away_formation),
    ):
        del side
        team_id = state.teams[team_code]
        roster_records = state.rosters[team_code]
        existing_result = await db.execute(
            text("""
                SELECT player_id
                FROM match_rosters
                WHERE match_id = :match_id
                  AND organization_id = :organization_id
                  AND is_valid = TRUE
            """),
            {
                "match_id": str(match_id),
                "organization_id": str(state.context.organization_id),
            },
        )
        existing_players = {row[0] for row in existing_result.all()}
        for index, roster in enumerate(roster_records):
            if roster.player_id in existing_players:
                continue
            await db.execute(
                text("""
                    INSERT INTO match_rosters
                        (organization_id, match_id, roster_id, player_id, team_id,
                         tournament_id, role)
                    VALUES (:organization_id, :match_id, :roster_id, :player_id, :team_id,
                            :tournament_id, :role)
                """),
                {
                    "organization_id": str(state.context.organization_id),
                    "match_id": str(match_id),
                    "roster_id": str(roster.roster_id),
                    "player_id": str(roster.player_id),
                    "team_id": str(team_id),
                    "tournament_id": str(state.tournament_id),
                    "role": "starter" if index < 11 else "substitute",
                },
            )
        if formation_code is None:
            raise RuntimeError(f"El partido {match.code} no tiene formación demo")
        await _ensure_tactical_lineup(
            db,
            state.context.organization_id,
            match_id,
            segment["id"],
            team_id,
            formation_code,
            roster_records,
        )
    return segment["id"]


def _goal_events(
    match: MatchSpec,
    segment_id: UUID,
    home_team_id: UUID,
    away_team_id: UUID,
    home_rosters: tuple[RosterRecord, ...],
    away_rosters: tuple[RosterRecord, ...],
) -> list[MatchEventPayload]:
    events: list[MatchEventPayload] = []
    event_number = 1
    for team_id, score, rosters, minute_start in (
        (home_team_id, match.home_score or 0, home_rosters, 11),
        (away_team_id, match.away_score or 0, away_rosters, 23),
    ):
        for goal_number in range(score):
            events.append(
                MatchEventPayload(
                    client_event_id=f"demo-{match.code.lower()}-goal-{event_number}",
                    event_type="goal",
                    team_id=team_id,
                    player_id=rosters[goal_number % 11].player_id,
                    minute=minute_start + goal_number * 17,
                    segment_id=segment_id,
                )
            )
            event_number += 1
    return events


async def _close_quarterfinal(
    db: AsyncSession,
    state: SeedState,
    match: MatchSpec,
    segment_id: UUID,
) -> None:
    match_id = state.matches[match.code]
    async with db.begin():
        await set_rls_context(db, state.context.organization_id, state.context.user_id)
        result = await db.execute(
            text("""
                SELECT status
                FROM matches
                WHERE id = :match_id
                  AND organization_id = :organization_id
            """),
            {
                "match_id": str(match_id),
                "organization_id": str(state.context.organization_id),
            },
        )
        status_value = result.scalar_one()
    if status_value in {"finished", "administrative_resolution"}:
        return
    if match.home_score is None or match.away_score is None:
        raise RuntimeError(f"El partido {match.code} no tiene marcador demo")

    home_team_id = state.teams[match.home_code]
    away_team_id = state.teams[match.away_code]
    payload = CloseMatchReportDTO(
        resolution_type="regular",
        home_score_regular=match.home_score,
        away_score_regular=match.away_score,
        home_score=match.home_score,
        away_score=match.away_score,
        winner_team_id=home_team_id if match.home_score > match.away_score else away_team_id,
        events=_goal_events(
            match,
            segment_id,
            home_team_id,
            away_team_id,
            state.rosters[match.home_code],
            state.rosters[match.away_code],
        ),
    )
    await CloseMatchReportService(db).execute(state.context, match_id, payload)


async def _mark_tournament_live(db: AsyncSession, state: SeedState) -> None:
    await set_rls_context(db, state.context.organization_id, state.context.user_id)
    await db.execute(
        text("""
            UPDATE tournaments
            SET status = CASE WHEN status = 'published' THEN 'live' ELSE status END,
                published_version_id = :version_id
            WHERE id = :tournament_id
              AND organization_id = :organization_id
        """),
        {
            "version_id": str(state.version_id),
            "tournament_id": str(state.tournament_id),
            "organization_id": str(state.context.organization_id),
        },
    )


async def _verify_seed(db: AsyncSession, state: SeedState) -> None:
    await set_rls_context(db, state.context.organization_id, state.context.user_id)
    result = await db.execute(
        text("""
            SELECT
                (SELECT COUNT(*) FROM tournament_teams
                 WHERE tournament_id = :tournament_id AND organization_id = :organization_id
                   AND status = 'registered') AS team_count,
                (SELECT COUNT(*) FROM rosters
                 WHERE tournament_id = :tournament_id AND organization_id = :organization_id
                   AND is_active = TRUE) AS roster_count,
                (SELECT COUNT(*) FROM matches
                 WHERE tournament_id = :tournament_id AND organization_id = :organization_id
                   AND tournament_version_id = :version_id) AS match_count,
                (SELECT COUNT(*) FROM advancement_links al
                 JOIN matches sm ON sm.id = al.source_match_id
                 WHERE al.organization_id = :organization_id
                   AND sm.tournament_id = :tournament_id) AS link_count
        """),
        {
            "tournament_id": str(state.tournament_id),
            "version_id": str(state.version_id),
            "organization_id": str(state.context.organization_id),
        },
    )
    counts = result.mappings().one()
    if (counts["team_count"], counts["roster_count"], counts["match_count"], counts["link_count"]) != (
        8,
        96,
        7,
        6,
    ):
        raise RuntimeError(
            "El seed demo no tiene la estructura esperada: "
            f"equipos={counts['team_count']}, plantillas={counts['roster_count']}, "
            f"partidos={counts['match_count']}, enlaces={counts['link_count']}"
        )

    expected_semifinals = {
        "SF1": (state.teams["AUR"], state.teams["CEN"]),
        "SF2": (state.teams["EST"], state.teams["GLA"]),
    }
    for code, participants in expected_semifinals.items():
        result = await db.execute(
            text("""
                SELECT status, home_team_id, away_team_id
                FROM matches
                WHERE id = :match_id AND organization_id = :organization_id
            """),
            {
                "match_id": str(state.matches[code]),
                "organization_id": str(state.context.organization_id),
            },
        )
        semifinal = result.mappings().one()
        if semifinal["status"] != "scheduled" or (
            semifinal["home_team_id"], semifinal["away_team_id"]
        ) != participants:
            raise RuntimeError(f"El avance de {code} no coincide con el estado demo esperado")

    result = await db.execute(
        text("""
            SELECT status, home_team_id, away_team_id
            FROM matches
            WHERE id = :match_id AND organization_id = :organization_id
        """),
        {
            "match_id": str(state.matches["FINAL"]),
            "organization_id": str(state.context.organization_id),
        },
    )
    final = result.mappings().one()
    if final["status"] != "scheduled" or final["home_team_id"] is not None or final["away_team_id"] is not None:
        raise RuntimeError("La final demo debe permanecer pendiente")


async def seed_demo() -> dict[str, Any]:
    settings = get_settings()
    if settings.app_env.lower().strip() not in DEVELOPMENT_ENVS:
        raise RuntimeError("El seed demo solo puede ejecutarse en desarrollo o local")
    validate_demo_definition()
    validate_rules_config(DEFAULT_RULES_CONFIG)

    async with SessionFactory() as db:
        async with db.begin():
            user_id = await _ensure_demo_user(db)
            organization_id = await _ensure_demo_organization(db, user_id)

        async with db.begin():
            state = await _ensure_structure(
                db,
                user_id,
                organization_id,
                settings.player_data_key,
            )

        quarterfinals = MATCH_SPECS[:4]
        for match in quarterfinals:
            async with db.begin():
                segment_id = await _prepare_quarterfinal(db, state, match)
            await _close_quarterfinal(db, state, match, segment_id)

        async with db.begin():
            await _mark_tournament_live(db, state)
            await _verify_seed(db, state)

    return {
        "email": DEMO_USER_EMAIL,
        "password": DEMO_USER_PASSWORD,
        "organization_id": str(organization_id),
        "tournament_id": str(state.tournament_id),
        "status": "live",
        "teams": 8,
        "players": 96,
        "matches": 7,
        "completed_quarterfinals": 4,
        "formations": 8,
    }


def main() -> None:
    async def run_and_dispose() -> dict[str, Any]:
        try:
            return await seed_demo()
        finally:
            await engine.dispose()

    print(json.dumps(asyncio.run(run_and_dispose()), indent=2))


if __name__ == "__main__":
    main()
