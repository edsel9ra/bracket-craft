import json
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator


OfficialRole = Literal[
    "main_referee",
    "assistant_referee_1",
    "assistant_referee_2",
    "fourth_official",
    "match_commissioner",
]

SegmentStatus = Literal["active", "completed", "interrupted"]
SegmentInterruptionReason = Literal["lighting_failure", "weather", "pitch_invasion", "other"]
FormationCode = Literal["4-3-3", "4-4-2", "3-5-2", "4-2-3-1"]


class OfficialAssignmentRequest(BaseModel):
    organization_user_id: UUID
    official_role: OfficialRole


class MatchEventPayload(BaseModel):
    client_event_id: str = Field(min_length=1, max_length=100)
    event_type: Literal["goal", "own_goal", "penalty_goal", "yellow_card", "red_card", "substitution", "foul"]
    team_id: UUID
    beneficiary_team_id: UUID | None = None
    player_id: UUID | None = None
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
        if self.event_type in {"goal", "own_goal", "penalty_goal", "yellow_card", "red_card", "substitution", "foul"} and self.player_id is None:
            raise ValueError(f"{self.event_type} requiere player_id")
        if self.event_type == "own_goal":
            if self.beneficiary_team_id is None or self.beneficiary_team_id == self.team_id:
                raise ValueError("Un autogol requiere un equipo beneficiario distinto")
        if self.event_type in {"goal", "penalty_goal"} and self.beneficiary_team_id not in (None, self.team_id):
            raise ValueError("Un gol normal debe beneficiar al equipo que ejecuta la acción")
        if self.event_type == "red_card":
            red_card_type = (self.metadata or {}).get("red_card_type", "direct_red")
            if red_card_type not in {"direct_red", "double_yellow_red"}:
                raise ValueError("red_card_type no es válido")
        elif self.metadata and "red_card_type" in self.metadata:
            raise ValueError("red_card_type solo aplica a una tarjeta roja")
        return self


class CloseMatchReportDTO(BaseModel):
    resolution_type: Literal["regular", "extra_time", "penalties", "walkover", "administrative"]
    home_score_regular: int = Field(ge=0)
    away_score_regular: int = Field(ge=0)
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
        penalties_set = self.home_penalties is not None or self.away_penalties is not None
        final_scores_set = self.home_score is not None or self.away_score is not None
        if final_scores_set and (self.home_score is None or self.away_score is None):
            raise ValueError("Los dos marcadores finales son obligatorios cuando se informa uno")

        if self.resolution_type == "penalties":
            if self.home_penalties is None or self.away_penalties is None:
                raise ValueError("Los dos marcadores de penales son obligatorios")
            if self.home_penalties == self.away_penalties:
                raise ValueError("La tanda de penales debe tener un ganador")
            if self.home_score is None or self.away_score is None or self.home_score != self.away_score:
                raise ValueError("El partido debe estar empatado después de la prórroga")
        elif penalties_set:
            raise ValueError("Los penales solo aplican con resolution_type=penalties")
        if self.resolution_type in {"extra_time", "penalties", "administrative"}:
            if self.home_score is None or self.away_score is None:
                raise ValueError("Esta resolución requiere los dos marcadores finales")
            if self.home_score < self.home_score_regular or self.away_score < self.away_score_regular:
                raise ValueError("El marcador final no puede ser menor al reglamentario")
        if self.resolution_type in {"extra_time", "penalties", "walkover", "administrative"} and self.winner_team_id is None:
            raise ValueError("Esta resolución requiere winner_team_id")
        if self.resolution_type == "regular":
            if self.reason is not None:
                raise ValueError("La razón solo aplica a una resolución administrativa")
            if final_scores_set and (
                self.home_score != self.home_score_regular or self.away_score != self.away_score_regular
            ):
                raise ValueError("Una resolución regular debe coincidir con el marcador reglamentario")
        elif self.resolution_type == "administrative":
            if self.reason is None:
                raise ValueError("La resolución administrativa requiere una razón")
        elif self.reason is not None:
            raise ValueError("La razón solo aplica a una resolución administrativa")
        if self.resolution_type in {"walkover", "administrative"} and self.events:
            raise ValueError("Esta resolución no permite eventos individuales")
        event_ids = [event.client_event_id for event in self.events]
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
    segment_number: int = Field(ge=1)
    minute_start: int = Field(ge=0)


class InterruptMatchSegmentRequest(BaseModel):
    reason: SegmentInterruptionReason
    minute: int = Field(ge=0)
    notes: str | None = Field(default=None, max_length=1000)


class MatchLineupEntry(BaseModel):
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
    team_id: UUID
    formation_code: FormationCode


class SaveMatchLineupRequest(BaseModel):
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


class MatchOfficialResponse(BaseModel):
    id: UUID
    match_id: UUID
    organization_user_id: UUID
    official_role: OfficialRole


class MatchOfficialSummaryResponse(MatchOfficialResponse):
    full_name: str
    email: str
