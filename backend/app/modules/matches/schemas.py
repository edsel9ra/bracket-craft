import json
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.modules.rule_contract import FORMATION_CODES


# Catálogo cerrado de eventos del acta (RF-004). Ampliarlo exige cambiar la
# spec 015: no es configuración ni se deduce del `rules_config`.
EVENT_TYPES: tuple[str, ...] = (
    "goal",
    "own_goal",
    "penalty_goal",
    "yellow_card",
    "red_card",
    "substitution",
    "foul",
)
EventType = Literal[*EVENT_TYPES]

RedCardType = Literal["direct_red", "double_yellow_red"]
RED_CARD_TYPES: tuple[RedCardType, ...] = ("direct_red", "double_yellow_red")

# Claves admitidas en `metadata` por tipo de evento (RF-002). Un tipo ausente
# no admite ninguna; cualquier otra clave es 422.
METADATA_KEYS_BY_EVENT_TYPE: dict[str, frozenset[str]] = {
    "red_card": frozenset({"red_card_type"}),
}

# Forma canónica de `client_event_id` (RF-015, D-5): el identificador de cliente
# deja de ser texto libre, pero la forma se valida solo en la API —la base
# conserva la columna y una `CHECK` sobre datos históricos añadiría superficie
# de migración sin garantía nueva—. Se admiten mayúsculas y minúsculas, igual
# que el patrón de UUID que ya usa el resto del esquema.
CLIENT_EVENT_ID_PATTERN = (
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)


OfficialRole = Literal[
    "main_referee",
    "assistant_referee_1",
    "assistant_referee_2",
    "fourth_official",
    "match_commissioner",
]

SegmentStatus = Literal["active", "completed", "interrupted"]
SegmentInterruptionReason = Literal["lighting_failure", "weather", "pitch_invasion", "other"]
FormationCode = Literal[*FORMATION_CODES]
# Resolución prevista que el operador anuncia al crear o interrumpir un
# segmento (SG-1, P5). Es el mismo catálogo que el cierre. El campo es
# opcional: sin él, el servidor aplica el máximo de la fase (P1).
ResolutionType = Literal["regular", "extra_time", "penalties", "walkover", "administrative"]

# Catálogo cerrado del motivo de walkover (RF-007, D-5): no hay texto libre ni
# código «otra». La obligatoriedad y el catálogo son de la API; la base solo
# almacena el código en `matches.resolution_reason` (migración 027).
WALKOVER_REASONS: tuple[str, ...] = (
    "no_show",
    "withdrawal",
    "insufficient_players",
    "sanction",
)


class OfficialAssignmentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    organization_user_id: UUID
    official_role: OfficialRole


class MatchEventPayload(BaseModel):
    # Catálogo cerrado en la raíz (RF-002, D-4): una clave de primer nivel que
    # el tipo no declara es 422 en vez de ignorarse. El evento viaja completo a
    # la auditoría del cierre, así que una clave ignorada sería un canal de
    # texto libre hacia el acta. Con la spec 019 (RNF-007) la bandera `extra`
    # con valor `forbid` ya no es una excepción justificada por el catálogo de
    # la 015, sino la regla general de toda petición JSON; este modelo la
    # conservaba antes de ella.
    model_config = ConfigDict(extra="forbid")

    # El identificador de cliente es un UUID (RF-015): si no tiene esa forma es
    # 422 y no se persiste. El patrón sustituye al antiguo tope de longitud, que
    # ya no aporta nada sobre una cadena de 36 caracteres.
    client_event_id: str = Field(pattern=CLIENT_EVENT_ID_PATTERN)
    event_type: EventType
    team_id: UUID
    beneficiary_team_id: UUID | None = None
    player_id: UUID | None = None
    # Only a substitution carries the pair; every other event must leave both
    # null (RF-011). The contract is enforced here so a structural violation is
    # a 422 before the handler runs.
    player_out_id: UUID | None = None
    player_in_id: UUID | None = None
    # Asistencia (RF-007): campo opcional del gol, como máximo una por gol y
    # nunca del propio goleador. La pertenencia a la plantilla, el mismo equipo
    # y la presencia en campo son del motor (RF-008): T4 y T5.
    assist_player_id: UUID | None = None
    minute: int = Field(ge=0, le=180)
    added_minute: int = Field(default=0, ge=0, le=30)
    segment_id: UUID
    metadata: dict[str, Any] | None = Field(default=None, max_length=50)

    @field_validator("metadata")
    @classmethod
    def validate_metadata_size(cls, value: dict[str, Any] | None) -> dict[str, Any] | None:
        if value is not None and len(json.dumps(value, default=str)) > 10_000:
            raise ValueError("metadata supera el tamaño máximo permitido")
        return value

    @model_validator(mode="after")
    def validate_event(self) -> "MatchEventPayload":
        if self.player_id is None:
            raise ValueError(f"{self.event_type} requiere player_id")
        if self.event_type == "substitution":
            if self.player_out_id is None or self.player_in_id is None:
                raise ValueError("Una sustitución requiere player_out_id y player_in_id")
            if self.player_out_id == self.player_in_id:
                raise ValueError("El jugador que sale y el que entra deben ser distintos")
            if self.player_id != self.player_out_id:
                raise ValueError("player_id debe coincidir con player_out_id")
        elif self.player_out_id is not None or self.player_in_id is not None:
            raise ValueError("player_out_id y player_in_id solo aplican a una sustitución")
        if self.event_type == "own_goal":
            if self.beneficiary_team_id is None or self.beneficiary_team_id == self.team_id:
                raise ValueError("Un autogol requiere un equipo beneficiario distinto")
        elif self.beneficiary_team_id is not None:
            # Incluye `goal`/`penalty_goal` con su propio equipo, que antes se
            # toleraba (RF-002, RNF-003 d).
            raise ValueError("beneficiary_team_id solo aplica a un autogol")
        if self.event_type == "goal":
            if self.assist_player_id is not None and self.assist_player_id == self.player_id:
                # RF-008: el asistente no puede ser el goleador (estructural).
                raise ValueError("El asistente debe ser distinto del goleador")
        elif self.assist_player_id is not None:
            # RF-009: el autogol, el penalti, las tarjetas, la sustitución y la
            # falta no admiten asistencia.
            raise ValueError("assist_player_id solo aplica a un gol")
        allowed_metadata_keys = METADATA_KEYS_BY_EVENT_TYPE.get(self.event_type, frozenset())
        unknown_metadata_keys = set(self.metadata or {}) - allowed_metadata_keys
        if unknown_metadata_keys:
            # El mensaje no repite las claves recibidas: son texto del cliente
            # y no deben viajar al 422 ni a la auditoría (RNF-002).
            if unknown_metadata_keys == {"red_card_type"}:
                raise ValueError("red_card_type solo aplica a una tarjeta roja")
            raise ValueError("metadata solo admite la clave red_card_type")
        if self.event_type == "red_card":
            red_card_type = (self.metadata or {}).get("red_card_type", "direct_red")
            if red_card_type not in RED_CARD_TYPES:
                raise ValueError("red_card_type no es válido")
        return self


class CloseMatchReportDTO(BaseModel):
    model_config = ConfigDict(extra="forbid")

    resolution_type: Literal["regular", "extra_time", "penalties", "walkover", "administrative"]
    # D-9: la pareja reglamentaria solo deja de ser obligatoria en `walkover`.
    # Con `0` como «no informado» un walkover 0-3 legítimo sería indistinguible
    # de un cliente que envía 0-0 por defecto.
    home_score_regular: int | None = Field(default=None, ge=0)
    away_score_regular: int | None = Field(default=None, ge=0)
    home_score: int | None = Field(default=None, ge=0)
    away_score: int | None = Field(default=None, ge=0)
    home_penalties: int | None = Field(default=None, ge=0)
    away_penalties: int | None = Field(default=None, ge=0)
    winner_team_id: UUID | None = None
    reason: str | None = Field(default=None, min_length=1, max_length=1000)
    events: list[MatchEventPayload] = Field(default_factory=list, max_length=500)

    @field_validator("reason")
    @classmethod
    def normalize_reason(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("La razón no puede estar vacía")
        return normalized

    @model_validator(mode="after")
    def validate_resolution(self) -> "CloseMatchReportDTO":
        """Comprueba solo la **estructura** del acta (422).

        La coherencia **numérica** del marcador (final menor que el
        reglamentario, `regular` con final distinto, `penalties` sin empate tras
        la prórroga y tanda igualada) no se valida aquí: es dominio del paso 13
        del cierre y responde **409** con `detail` cadena (RF-007, RNF-003 f).

        Lo que sí decide este validador es la **presencia** de cada campo por
        resolución (D-9): la pareja reglamentaria es obligatoria salvo en
        `walkover`, cuyo marcador deriva el servidor de la configuración (RF-005).
        """
        regular_scores_set = (
            self.home_score_regular is not None or self.away_score_regular is not None
        )
        regular_pair_set = (
            self.home_score_regular is not None and self.away_score_regular is not None
        )
        if regular_scores_set and not regular_pair_set:
            raise ValueError(
                "Los dos marcadores reglamentarios son obligatorios cuando se informa uno"
            )
        if self.resolution_type != "walkover" and not regular_pair_set:
            # D-9: solo el walkover puede omitirlos; el resto de resoluciones no
            # cambia su contrato (422).
            raise ValueError("Esta resolución requiere los dos marcadores reglamentarios")

        penalties_set = self.home_penalties is not None or self.away_penalties is not None
        final_scores_set = self.home_score is not None or self.away_score is not None
        if final_scores_set and (self.home_score is None or self.away_score is None):
            raise ValueError("Los dos marcadores finales son obligatorios cuando se informa uno")

        if self.resolution_type == "penalties":
            if self.home_penalties is None or self.away_penalties is None:
                raise ValueError("Los dos marcadores de penales son obligatorios")
        elif penalties_set:
            raise ValueError("Los penales solo aplican con resolution_type=penalties")
        if self.resolution_type in {"extra_time", "penalties", "administrative"}:
            if self.home_score is None or self.away_score is None:
                raise ValueError("Esta resolución requiere los dos marcadores finales")
        if self.resolution_type in {"extra_time", "penalties", "walkover", "administrative"} and self.winner_team_id is None:
            raise ValueError("Esta resolución requiere winner_team_id")
        if self.resolution_type == "walkover":
            # RF-007: motivo obligatorio y de catálogo cerrado (D-8: es el mismo
            # campo que la administrativa, con otro dominio).
            if self.reason is None:
                raise ValueError("El walkover requiere un motivo")
            if self.reason not in WALKOVER_REASONS:
                raise ValueError("El motivo del walkover no es válido")
        elif self.resolution_type == "administrative":
            if self.reason is None:
                raise ValueError("La resolución administrativa requiere una razón")
        elif self.reason is not None:
            raise ValueError(
                "La razón solo aplica a un walkover o a una resolución administrativa"
            )
        if self.resolution_type in {"walkover", "administrative"} and self.events:
            raise ValueError("Esta resolución no permite eventos individuales")
        # La identidad del evento no distingue caja: el UUID se compara en su
        # forma canónica (RF-012), igual que la escritura y la búsqueda de un
        # evento ya persistido.
        event_ids = [event.client_event_id.lower() for event in self.events]
        if len(event_ids) != len(set(event_ids)):
            raise ValueError("No se permiten client_event_id duplicados en la misma acta")
        return self


class MatchCloseResponse(BaseModel):
    status: str
    match_id: UUID
    home_score: int
    away_score: int
    winner_team_id: UUID | None = None


class CreateMatchSegmentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    segment_number: int = Field(ge=1)
    minute_start: int = Field(ge=0)
    # Opcional y aditivo (SG-1): con valor, el máximo es el de esa resolución;
    # sin él, el máximo de la fase, que es el comportamiento anterior (P1).
    resolution_type: ResolutionType | None = None


class InterruptMatchSegmentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: SegmentInterruptionReason
    minute: int = Field(ge=0)
    notes: str | None = Field(default=None, max_length=1000)
    # Misma regla opcional que la creación de segmento para el minuto final.
    resolution_type: ResolutionType | None = None


class MatchLineupEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    roster_id: UUID
    role: Literal["starter", "substitute"]
    position_slot: str | None = Field(default=None, max_length=20, pattern=r"^[A-Z0-9_]+$")
    entered_minute: int | None = Field(default=None, ge=0)
    left_minute: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def validate_minutes(self) -> "MatchLineupEntry":
        if self.left_minute is not None and self.entered_minute is not None and self.left_minute < self.entered_minute:
            raise ValueError("left_minute no puede ser menor que entered_minute")
        if self.role == "substitute" and self.position_slot is not None:
            raise ValueError("Un suplente no puede tener una posición táctica")
        return self


class MatchTeamLineupConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    team_id: UUID
    formation_code: FormationCode


class SaveMatchLineupRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    segment_id: UUID
    entries: list[MatchLineupEntry] = Field(max_length=100)
    team_lineups: list[MatchTeamLineupConfig] = Field(default_factory=list, max_length=2)

    @model_validator(mode="after")
    def validate_unique_rosters(self) -> "SaveMatchLineupRequest":
        roster_ids = [entry.roster_id for entry in self.entries]
        if len(roster_ids) != len(set(roster_ids)):
            raise ValueError("Una plantilla no puede repetir el mismo jugador")
        team_ids = [lineup.team_id for lineup in self.team_lineups]
        if len(team_ids) != len(set(team_ids)):
            raise ValueError("Una formación no puede repetirse para el mismo equipo")
        return self


class PublishMatchLineupRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    segment_id: UUID
    team_id: UUID
    is_public: bool


class MatchSegmentResponse(BaseModel):
    id: UUID
    segment_number: int
    minute_start: int
    minute_end: int | None = None
    status: str


class MatchSegmentInterruptionResponse(BaseModel):
    id: UUID
    match_id: UUID
    segment_id: UUID
    reason: SegmentInterruptionReason
    minute: int
    notes: str | None = None
    created_at: Any


class NextSegmentProposal(BaseModel):
    """Propuesta del siguiente segmento derivada de lo persistido (RF-015).

    Es una **propuesta de solo lectura**: ``GET /matches/{id}/operation`` no
    crea ni modifica nada y el servidor sigue validando número y minuto al crear
    un segmento (RF-013/RF-014). ``derived`` verdadero significa que
    ``minute_start`` sale de lo persistido (el fin del último segmento o el
    minuto de su interrupción); falso significa que no hay de dónde derivarlo
    —último segmento activo o completado sin ``minute_end``— y el operador lo
    indica, con ``minute_start`` nulo.
    """

    segment_number: int
    minute_start: int | None = None
    derived: bool


class MatchOperationResponse(BaseModel):
    match: dict[str, Any]
    segments: list[dict[str, Any]]
    interruptions: list[dict[str, Any]]
    officials: list[dict[str, Any]]
    eligible_officials: list[dict[str, Any]]
    rosters: list[dict[str, Any]]
    lineup: list[dict[str, Any]]
    tactical_lineups: list[dict[str, Any]]
    events: list[dict[str, Any]]
    substitutions: dict[str, Any]
    limits: dict[str, Any]
    next_segment: NextSegmentProposal | None = None


class MatchOfficialResponse(BaseModel):
    id: UUID
    match_id: UUID
    organization_user_id: UUID
    official_role: OfficialRole


class MatchOfficialSummaryResponse(MatchOfficialResponse):
    full_name: str
    email: str
